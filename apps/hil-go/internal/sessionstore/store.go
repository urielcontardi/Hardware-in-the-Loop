package sessionstore

import (
	"bufio"
	"encoding/binary"
	"math"
	"os"
	"sync"

	"hil.local/daemon/internal/frame"
)

const recBytes = 28 // t(float64) + 5 float32

// Store is an always-on, disk-backed full-rate session with a sparse time
// index. Append is from the receiver goroutine; ReadWindow is from query
// handlers. A RWMutex guards the index and counters; reads use a private
// file handle so they do not disturb the append cursor.
type Store struct {
	mu         sync.RWMutex
	f          *os.File
	w          *bufio.Writer
	path       string
	ix         index
	blockN     int
	n          int64
	tFirst     float64
	tLast      float64
	haveFirst  bool
	maxSamples int64
}

// Open creates (truncating) a session file. indexEvery is the sample stride
// between sparse index entries (e.g. 4096).
func Open(path string, indexEvery int) (*Store, error) {
	if indexEvery < 1 {
		indexEvery = 4096
	}
	f, err := os.Create(path)
	if err != nil {
		return nil, err
	}
	return &Store{f: f, w: bufio.NewWriterSize(f, 1<<20), path: path, blockN: indexEvery}, nil
}

func putF32(b []byte, off int, v float32) {
	binary.LittleEndian.PutUint32(b[off:], math.Float32bits(v))
}

// Append writes one full-rate sample and updates the sparse index.
func (s *Store) Append(t float64, smp frame.Sample) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.haveFirst && t <= s.tLast {
		return
	}
	if !s.haveFirst {
		s.tFirst, s.haveFirst = t, true
	}
	if s.n%int64(s.blockN) == 0 {
		_ = s.w.Flush()
		off, _ := s.f.Seek(0, os.SEEK_CUR)
		s.ix.add(t, off)
	}
	var rec [recBytes]byte
	binary.LittleEndian.PutUint64(rec[0:], math.Float64bits(t))
	putF32(rec[:], 8, smp.Ia)
	putF32(rec[:], 12, smp.Ib)
	putF32(rec[:], 16, smp.FluxA)
	putF32(rec[:], 20, smp.FluxB)
	putF32(rec[:], 24, smp.Speed)
	_, _ = s.w.Write(rec[:])
	s.tLast = t
	s.n++
}

func f32(b []byte, off int) float32 {
	return math.Float32frombits(binary.LittleEndian.Uint32(b[off:]))
}

// ReadWindow returns all samples with from <= t <= to. It seeks to the index
// floor before from, then scans forward until past to.
func (s *Store) ReadWindow(from, to float64) ([]float64, []frame.Sample) {
	s.mu.RLock()
	_ = s.w.Flush()
	startOff, ok := s.ix.floorOffset(from)
	total := s.n
	s.mu.RUnlock()
	if !ok {
		startOff = 0
	}
	rd, err := os.Open(s.path)
	if err != nil {
		return nil, nil
	}
	defer rd.Close()
	if _, err := rd.Seek(startOff, os.SEEK_SET); err != nil {
		return nil, nil
	}
	var ts []float64
	var ss []frame.Sample
	br := bufio.NewReaderSize(rd, 1<<20)
	buf := make([]byte, recBytes)
	read := int64(0)
	maxRead := total * 2
	for read < maxRead {
		if _, err := readFull(br, buf); err != nil {
			break
		}
		read++
		t := math.Float64frombits(binary.LittleEndian.Uint64(buf[0:]))
		if t < from {
			continue
		}
		if t > to {
			break
		}
		ts = append(ts, t)
		ss = append(ss, frame.Sample{
			Ia: f32(buf, 8), Ib: f32(buf, 12),
			FluxA: f32(buf, 16), FluxB: f32(buf, 20), Speed: f32(buf, 24),
		})
	}
	return ts, ss
}

func readFull(br *bufio.Reader, buf []byte) (int, error) {
	got := 0
	for got < len(buf) {
		n, err := br.Read(buf[got:])
		got += n
		if err != nil {
			return got, err
		}
	}
	return got, nil
}

// Count returns the number of samples written.
func (s *Store) Count() int64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.n
}

// Span returns the first and last sample times.
func (s *Store) Span() (float64, float64) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.tFirst, s.tLast
}

// Close flushes and closes the file.
func (s *Store) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.w != nil {
		_ = s.w.Flush()
	}
	if s.f != nil {
		return s.f.Close()
	}
	return nil
}

// SetMaxSamples sets the guardrail cap (0 = unlimited). When exceeded, OverCap
// reports true so the caller can warn/rotate.
func (s *Store) SetMaxSamples(n int64) {
	s.mu.Lock()
	s.maxSamples = n
	s.mu.Unlock()
}

// OverCap reports whether the session exceeded the configured sample cap.
func (s *Store) OverCap() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.maxSamples > 0 && s.n > s.maxSamples
}
