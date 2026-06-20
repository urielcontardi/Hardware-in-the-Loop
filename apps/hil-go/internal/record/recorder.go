package record

import (
	"encoding/binary"
	"encoding/json"
	"io"
	"math"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pwmrecv"
)

const (
	clockHz       = 100_000_000
	sampleBytes   = 28
	queueCapacity = 512
	maxPWMEvents  = 2_000_000
)

type metadata struct {
	Version     int    `json:"version"`
	Date        string `json:"date"`
	Name        string `json:"name"`
	SampleCount uint64 `json:"sample_count"`
	PWMCount    int    `json:"pwm_count"`
	Raw         bool   `json:"raw"`
	ClockHz     int    `json:"clock_hz"`
}

type pwmRecord struct {
	t       float32
	a, b, c uint8
}

type batch struct {
	generation uint64
	samples    []frame.Sample
	flushed    chan struct{}
}

// Recorder persists full-rate samples without blocking the UDP receiver.
type Recorder struct {
	dir           string
	mu            sync.Mutex
	submitMu      sync.RWMutex
	file          *os.File
	path          string
	countOff      int64
	sampleCount   uint64
	runEpoch      uint16
	haveEpoch     bool
	baseEpoch     uint16
	lastCycles    uint32
	wrapCycles    uint64
	baseAbsCycles uint64
	pwmClockHz    uint32
	pwmEpoch      uint16
	pwmLastCycles uint32
	pwmWrapCycles uint64
	pwmHaveBase   bool
	pwmEvents     []pwmRecord
	haveBase      bool
	generation    uint64
	latestPath    string
	latestUsed    bool
	queue         chan batch
	done          chan struct{}
	wg            sync.WaitGroup
	active        atomic.Bool
	dropped       atomic.Uint64
	written       atomic.Uint64
}

func New(dir string) *Recorder {
	r := &Recorder{dir: dir, queue: make(chan batch, queueCapacity), done: make(chan struct{})}
	r.wg.Add(1)
	go r.loop()
	return r
}

func (r *Recorder) Close() error {
	_ = r.Stop()
	close(r.done)
	r.wg.Wait()
	return nil
}

func (r *Recorder) Start(name string) (string, error) {
	if err := r.Stop(); err != nil {
		return "", err
	}
	if err := os.MkdirAll(r.dir, 0755); err != nil {
		return "", err
	}
	if name == "" {
		name = "capture_" + time.Now().Format("20060102_150405.000")
	}
	path := filepath.Join(r.dir, "."+filepath.Base(name)+".partial")
	f, err := os.Create(path)
	if err != nil {
		return "", err
	}
	metaBytes, err := json.Marshal(metadata{Version: 1, Date: time.Now().UTC().Format(time.RFC3339Nano), Name: name, Raw: true, ClockHz: clockHz})
	if err != nil {
		f.Close()
		return "", err
	}
	header := make([]byte, 12+len(metaBytes))
	copy(header, "HILDATA")
	header[7] = 1
	binary.LittleEndian.PutUint32(header[8:], uint32(len(metaBytes)))
	copy(header[12:], metaBytes)
	if _, err := f.Write(header); err != nil {
		f.Close()
		return "", err
	}
	aligned := int64((len(header) + 7) &^ 7)
	if _, err := f.Seek(aligned, io.SeekStart); err != nil {
		f.Close()
		return "", err
	}
	if err := binary.Write(f, binary.LittleEndian, uint32(0)); err != nil {
		f.Close()
		return "", err
	}
	r.mu.Lock()
	r.generation++
	r.file, r.path, r.countOff = f, path, aligned
	r.sampleCount, r.haveEpoch, r.haveBase, r.wrapCycles = 0, false, false, 0
	r.pwmClockHz, r.pwmHaveBase, r.pwmWrapCycles = clockHz, false, 0
	r.pwmEvents = r.pwmEvents[:0]
	r.latestPath, r.latestUsed = "", false
	r.mu.Unlock()
	r.active.Store(true)
	return path, nil
}

func (r *Recorder) Stop() error {
	r.active.Store(false)
	r.submitMu.Lock()
	r.submitMu.Unlock()
	r.mu.Lock()
	generation := r.generation
	hasFile := r.file != nil
	r.mu.Unlock()
	if hasFile {
		flushed := make(chan struct{})
		r.queue <- batch{generation: generation, flushed: flushed}
		<-flushed
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.file == nil {
		return nil
	}
	if _, err := r.file.Seek(r.countOff, io.SeekStart); err != nil {
		return err
	}
	if err := binary.Write(r.file, binary.LittleEndian, uint32(r.sampleCount)); err != nil {
		return err
	}
	end := r.countOff + 4 + int64(r.sampleCount)*sampleBytes
	if _, err := r.file.Seek(end, io.SeekStart); err != nil {
		return err
	}
	if err := binary.Write(r.file, binary.LittleEndian, uint32(len(r.pwmEvents))); err != nil {
		return err
	}
	for _, ev := range r.pwmEvents {
		var raw [8]byte
		binary.LittleEndian.PutUint32(raw[:4], math.Float32bits(ev.t))
		raw[4], raw[5], raw[6] = ev.a, ev.b, ev.c
		if _, err := r.file.Write(raw[:]); err != nil {
			return err
		}
	}
	if err := r.file.Sync(); err != nil {
		return err
	}
	if err := r.file.Close(); err != nil {
		return err
	}
	base := strings.TrimSuffix(strings.TrimPrefix(filepath.Base(r.path), "."), ".partial")
	finalPath := filepath.Join(r.dir, base+".hilbin")
	if err := os.Rename(r.path, finalPath); err != nil {
		return err
	}
	r.latestPath, r.latestUsed = finalPath, false
	r.file, r.path = nil, ""
	return nil
}

// Submit copies a decoded burst into the bounded writer queue.
func (r *Recorder) Submit(samples []frame.Sample) {
	r.submitMu.RLock()
	defer r.submitMu.RUnlock()
	if !r.active.Load() || len(samples) == 0 {
		return
	}
	r.mu.Lock()
	generation := r.generation
	r.mu.Unlock()
	cp := append([]frame.Sample(nil), samples...)
	select {
	case r.queue <- batch{generation: generation, samples: cp}:
	default:
		r.dropped.Add(uint64(len(samples)))
	}
}

// SubmitPWM appends PWM events using the same run-local hardware timeline.
func (r *Recorder) SubmitPWM(clock uint32, events []pwmrecv.Event) {
	r.submitMu.RLock()
	defer r.submitMu.RUnlock()
	if !r.active.Load() || len(events) == 0 {
		return
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.file == nil {
		return
	}
	if clock != 0 {
		r.pwmClockHz = clock
	}
	for _, ev := range events {
		if !r.prepareEpochLocked(ev.Epoch) {
			continue
		}
		if !r.pwmHaveBase {
			r.pwmEpoch, r.pwmLastCycles, r.pwmHaveBase = ev.Epoch, ev.TCycles, true
		} else if ev.TCycles < r.pwmLastCycles && r.pwmLastCycles-ev.TCycles > 0x80000000 {
			r.pwmWrapCycles += 1 << 32
		}
		r.pwmLastCycles = ev.TCycles
		t := float32(float64(r.pwmWrapCycles+uint64(ev.TCycles)) / float64(r.pwmClockHz))
		if len(r.pwmEvents) >= maxPWMEvents {
			r.dropped.Add(1)
			continue
		}
		r.pwmEvents = append(r.pwmEvents, pwmRecord{t: t, a: ev.A, b: ev.B, c: ev.C})
	}
}

// CopyLatest copies the latest completed raw capture to dst once.
func (r *Recorder) CopyLatest(dst string) (bool, error) {
	r.mu.Lock()
	if r.latestPath == "" || r.latestUsed {
		r.mu.Unlock()
		return false, nil
	}
	src := r.latestPath
	r.mu.Unlock()
	if filepath.Clean(src) == filepath.Clean(dst) {
		r.mu.Lock()
		r.latestUsed = true
		r.mu.Unlock()
		return true, nil
	}
	in, err := os.Open(src)
	if err != nil {
		return false, err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return false, err
	}
	_, copyErr := io.Copy(out, in)
	closeErr := out.Close()
	if copyErr != nil {
		return false, copyErr
	}
	if closeErr == nil {
		_ = os.Remove(src)
	}
	if closeErr == nil {
		r.mu.Lock()
		r.latestUsed = true
		r.mu.Unlock()
	}
	return true, closeErr
}

func (r *Recorder) Stats() (active bool, written, dropped uint64) {
	return r.active.Load(), r.written.Load(), r.dropped.Load()
}

func (r *Recorder) loop() {
	defer r.wg.Done()
	for {
		select {
		case <-r.done:
			return
		case b := <-r.queue:
			r.writeBatch(b)
			if b.flushed != nil {
				close(b.flushed)
			}
		}
	}
}

func epochNewer(next, current uint16) bool {
	delta := (next - current) & 0x3fff
	return delta != 0 && delta < 0x2000
}

func (r *Recorder) prepareEpochLocked(epoch uint16) bool {
	epoch &= 0x3fff
	if !r.haveEpoch {
		r.runEpoch, r.haveEpoch = epoch, true
		return true
	}
	if epoch == r.runEpoch {
		return true
	}
	if !epochNewer(epoch, r.runEpoch) {
		return false
	}
	if err := r.file.Truncate(r.countOff + 4); err != nil {
		r.dropped.Add(1)
		return false
	}
	if _, err := r.file.Seek(r.countOff+4, io.SeekStart); err != nil {
		r.dropped.Add(1)
		return false
	}
	r.runEpoch = epoch
	r.sampleCount, r.haveBase, r.wrapCycles, r.baseAbsCycles = 0, false, 0, 0
	r.pwmHaveBase, r.pwmWrapCycles = false, 0
	r.pwmEvents = r.pwmEvents[:0]
	return true
}

func (r *Recorder) writeBatch(b batch) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.file == nil || b.generation != r.generation {
		return
	}
	buf := make([]byte, len(b.samples)*sampleBytes)
	off := 0
	for _, s := range b.samples {
		prevHaveEpoch, prevEpoch := r.haveEpoch, r.runEpoch
		epoch := s.Epoch & 0x3fff
		if !r.prepareEpochLocked(s.Epoch) {
			continue
		}
		if prevHaveEpoch && epoch != prevEpoch && epoch == r.runEpoch {
			off = 0
		}
		if !r.haveBase {
			r.lastCycles, r.baseEpoch, r.haveBase = s.TCycles, s.Epoch, true
			r.baseAbsCycles = uint64(s.TCycles)
		} else if s.Epoch == r.baseEpoch &&
			s.TCycles <= r.lastCycles &&
			!(s.TCycles < r.lastCycles && r.lastCycles-s.TCycles > 0x80000000) {
			continue
		}
		if s.TCycles < r.lastCycles && r.lastCycles-s.TCycles > 0x80000000 {
			r.wrapCycles += 1 << 32
		}
		r.lastCycles = s.TCycles
		absCycles := r.wrapCycles + uint64(s.TCycles)
		if absCycles < r.baseAbsCycles {
			continue
		}
		t := float32(float64(absCycles-r.baseAbsCycles) / clockHz)
		values := [...]float32{t, s.Ia, s.Ib, s.FluxA, s.FluxB, s.Speed, 0}
		for _, value := range values {
			binary.LittleEndian.PutUint32(buf[off:], math.Float32bits(value))
			off += 4
		}
		r.sampleCount++
	}
	if off == 0 {
		return
	}
	if _, err := r.file.Write(buf[:off]); err != nil {
		r.dropped.Add(uint64(off / sampleBytes))
		return
	}
	r.written.Add(uint64(off / sampleBytes))
}
