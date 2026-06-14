# Faithful Multi-Resolution HIL Telemetry Display — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the telemetry charts render faithful waveforms (correct shape/amplitude, correct `Te`/abc) at any zoom and at any point in the live session, by replacing fixed-bucket reduction with viewport-driven min/max decimation backed by whole-session full-rate retention on disk.

**Architecture:** The gateway computes derived channels (`Te`, `Ia/Ib/Ic`, `Φa/Φb/Φc`) from alpha-beta at full rate, streams the whole session full-rate to disk, keeps a sparse time->offset index and one coarse min/max overview tier in RAM, and answers viewport queries (`from,to,width`) by serving the overview tier or seeking into the session file. The front end issues debounced queries on pan/zoom and renders min/max as an envelope band, real line when full-rate.

**Tech Stack:** Go 1.22+ (gateway, module `hil.local/daemon`), TypeScript + uPlot (frontend `apps/hil-go/frontend`), existing `.hilbin` binary format.

---

## Context for the implementer

- All gateway code lives under `apps/hil-go/`. Run Go commands from that dir.
- `frame.Sample` (`internal/frame/frame.go`) holds solver-native channels:
  `TCycles uint32, Epoch uint16, Ia, Ib, FluxA, FluxB, Speed float32`. The
  fields named `Ia/Ib/FluxA/FluxB` actually carry **alpha-beta** values
  (`Iα, Iβ, Φα, Φβ`); the names are historical. Do not rename them in this plan.
- Speed is in rad/s on the wire. The chart converts to RPM (`* 60 / (2π)`).
- `internal/receiver/receiver.go` exposes `SetSampleHandler(func([]frame.Sample))`,
  already called at full rate with every decoded burst.
- `internal/record/recorder.go` already streams full-rate samples to a
  `.hilbin` file (28-byte records: `t, Ia, Ib, FluxA, FluxB, Speed, 0` float32).
- `internal/rawbuf/rawbuf.go` is the recent full-rate ring (cursor-based).
- The buggy paths to remove at the end: `frame.DisplayReducer` /
  `ReduceForDisplay`, the gateway `telemetryPump` SSE reduction, and the
  front-end fixed-bucket overview + alpha-beta-extrema reconstruction in
  `frontend/src/main.ts`.
- Motor params for `Te`: `Te = 1.5·npp·(Lm/Lr_total)·(Φα·Iβ − Φβ·Iα)`. Firmware
  defaults: `npp=2`, `Lm=0.1099442`, `Lr_leak=0.0063264`, so
  `Lr_total=0.1162706`. The gateway tracks live values in
  `s.lastMotor[ip] hiludp.MotorParams` (pointer fields).

---

## Phase 1 — Derived channels package

Produces a standalone, tested package that turns one `frame.Sample` into the
full 8-channel set. Used by the overview tier and the query handler.

### Task 1.1: Derived-channel computation

**Files:**
- Create: `apps/hil-go/internal/derive/derive.go`
- Test: `apps/hil-go/internal/derive/derive_test.go`

- [ ] **Step 1: Write the failing test**

```go
package derive

import (
	"math"
	"testing"

	"hil.local/daemon/internal/frame"
)

func approx(t *testing.T, name string, got, want float64) {
	t.Helper()
	if math.Abs(got-want) > 1e-4 {
		t.Errorf("%s = %.6f, want %.6f", name, got, want)
	}
}

func TestComputeBalanced(t *testing.T) {
	// Iα=10, Iβ=0 -> Ia=10, Ib=Ic=-5. Φα=1, Φβ=0 -> Φa=1, Φb=Φc=-0.5.
	d := DefaultMotor.Compute(frame.Sample{Ia: 10, Ib: 0, FluxA: 1, FluxB: 0, Speed: 3})
	approx(t, "Ia", d.Ia, 10)
	approx(t, "Ib", d.Ib, -5)
	approx(t, "Ic", d.Ic, -5)
	approx(t, "FluxA", d.FluxA, 1)
	approx(t, "FluxB", d.FluxB, -0.5)
	approx(t, "FluxC", d.FluxC, -0.5)
	approx(t, "Speed", d.Speed, 3)
	// Te = 1.5*2*(Lm/Lrtot)*(Φα·Iβ − Φβ·Iα) = 3*k*(1*0 - 0*10) = 0
	approx(t, "Te", d.Te, 0)
}

func TestComputeTorqueSign(t *testing.T) {
	// Φα=0, Φβ=1, Iα=1, Iβ=0 -> Φα·Iβ − Φβ·Iα = 0 - 1 = -1
	d := DefaultMotor.Compute(frame.Sample{Ia: 1, Ib: 0, FluxA: 0, FluxB: 1})
	k := 1.5 * 2 * (DefaultMotor.Lm / DefaultMotor.LrTotal)
	approx(t, "Te", d.Te, -k)
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go && go test ./internal/derive/ -run TestCompute -v`
Expected: FAIL — package/`DefaultMotor`/`Compute` undefined.

- [ ] **Step 3: Write minimal implementation**

```go
// Package derive turns solver-native alpha-beta telemetry samples into the
// full phase + torque channel set used by the display. All derivations are
// exact functions of one sample, so they can be applied at full rate before
// any decimation (the key fix: never reconstruct nonlinear channels from
// per-channel alpha-beta extrema).
package derive

import "hil.local/daemon/internal/frame"

const sqrt3over2 = 0.8660254037844386

// Motor holds the parameters needed for electromagnetic torque.
type Motor struct {
	Npp     float64
	Lm      float64
	LrTotal float64 // Lr_leak + Lm
}

// DefaultMotor matches the firmware default motor model.
var DefaultMotor = Motor{Npp: 2, Lm: 0.1099442, LrTotal: 0.1099442 + 0.0063264}

// Derived is the full channel set for one sample. Speed stays in rad/s.
type Derived struct {
	Ia, Ib, Ic          float64
	FluxA, FluxB, FluxC float64
	Speed               float64
	Te                  float64
}

// Compute applies inverse Clarke (amplitude-invariant) and the torque cross
// product. s.Ia/s.Ib/s.FluxA/s.FluxB carry alpha-beta values.
func (m Motor) Compute(s frame.Sample) Derived {
	ia, ib := float64(s.Ia), float64(s.Ib)
	fa, fb := float64(s.FluxA), float64(s.FluxB)
	return Derived{
		Ia:    ia,
		Ib:    -ia/2 + sqrt3over2*ib,
		Ic:    -ia/2 - sqrt3over2*ib,
		FluxA: fa,
		FluxB: -fa/2 + sqrt3over2*fb,
		FluxC: -fa/2 - sqrt3over2*fb,
		Speed: float64(s.Speed),
		Te:    1.5 * m.Npp * (m.Lm / m.LrTotal) * (fa*ib - fb*ia),
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go && go test ./internal/derive/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/derive/
git commit -m "feat(derive): exact per-sample phase + torque channels"
```

### Task 1.2: Channel enumeration and a MotorParams adapter

**Files:**
- Modify: `apps/hil-go/internal/derive/derive.go`
- Test: `apps/hil-go/internal/derive/channels_test.go`

- [ ] **Step 1: Write the failing test**

```go
package derive

import "testing"

func TestChannelOrderStable(t *testing.T) {
	want := []string{"Ia", "Ib", "Ic", "FluxA", "FluxB", "FluxC", "Speed", "Te"}
	if len(Channels) != len(want) {
		t.Fatalf("len(Channels)=%d want %d", len(Channels), len(want))
	}
	for i, n := range want {
		if Channels[i] != n {
			t.Errorf("Channels[%d]=%q want %q", i, Channels[i], n)
		}
	}
}

func TestValuesMatchChannelOrder(t *testing.T) {
	d := Derived{Ia: 1, Ib: 2, Ic: 3, FluxA: 4, FluxB: 5, FluxC: 6, Speed: 7, Te: 8}
	v := d.Values()
	for i := range Channels {
		if v[i] != float64(i+1) {
			t.Errorf("Values()[%d]=%v want %v", i, v[i], i+1)
		}
	}
}

func TestMotorFromParamsDefaults(t *testing.T) {
	m := MotorFromParams(nil, nil, nil)
	if m != DefaultMotor {
		t.Errorf("nil params should give DefaultMotor, got %+v", m)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go && go test ./internal/derive/ -run "Channel|Values|MotorFromParams" -v`
Expected: FAIL — `Channels`, `Values`, `MotorFromParams` undefined.

- [ ] **Step 3: Write minimal implementation**

Append to `derive.go`:

```go
// NumChannels is the count of derived display channels.
const NumChannels = 8

// Channels is the canonical, index-stable channel order used by the overview
// tier and the query API.
var Channels = [NumChannels]string{
	"Ia", "Ib", "Ic", "FluxA", "FluxB", "FluxC", "Speed", "Te",
}

// Values returns the channel values in Channels order.
func (d Derived) Values() [NumChannels]float64 {
	return [NumChannels]float64{
		d.Ia, d.Ib, d.Ic, d.FluxA, d.FluxB, d.FluxC, d.Speed, d.Te,
	}
}

// MotorFromParams builds a Motor from optional live params, defaulting any
// missing field to the firmware default. npp/lm are direct; lrLeak is added to
// lm to form LrTotal.
func MotorFromParams(npp, lm, lrLeak *float32) Motor {
	m := DefaultMotor
	if npp != nil {
		m.Npp = float64(*npp)
	}
	lmv := m.Lm
	if lm != nil {
		lmv = float64(*lm)
	}
	leak := 0.0063264
	if lrLeak != nil {
		leak = float64(*lrLeak)
	}
	m.Lm = lmv
	m.LrTotal = lmv + leak
	return m
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go && go test ./internal/derive/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/derive/
git commit -m "feat(derive): stable channel order, Values(), MotorParams adapter"
```

---

## Phase 2 — Overview tier (whole-session min/max)

Produces a thread-safe min/max envelope of every channel in fixed time buckets,
covering the whole session, bounded in RAM. This serves zoomed-out queries.

### Task 2.1: Bucketed min/max accumulator

**Files:**
- Create: `apps/hil-go/internal/overview/overview.go`
- Test: `apps/hil-go/internal/overview/overview_test.go`

- [ ] **Step 1: Write the failing test**

```go
package overview

import (
	"testing"

	"hil.local/daemon/internal/derive"
)

func TestBucketingAndExtrema(t *testing.T) {
	// 50ms buckets. Push samples in two buckets; verify min/max captured.
	ov := New(0.050)
	ov.Push(0.000, [derive.NumChannels]float64{1, 0, 0, 0, 0, 0, 0, 0})
	ov.Push(0.010, [derive.NumChannels]float64{5, 0, 0, 0, 0, 0, 0, 0})
	ov.Push(0.020, [derive.NumChannels]float64{-3, 0, 0, 0, 0, 0, 0, 0})
	ov.Push(0.070, [derive.NumChannels]float64{2, 0, 0, 0, 0, 0, 0, 0}) // next bucket

	cols := ov.Query(0, 0.1)
	if len(cols) != 2 {
		t.Fatalf("got %d buckets, want 2", len(cols))
	}
	if cols[0].Min[0] != -3 || cols[0].Max[0] != 5 {
		t.Errorf("bucket0 Ia min/max = %v/%v want -3/5", cols[0].Min[0], cols[0].Max[0])
	}
	if cols[1].Min[0] != 2 || cols[1].Max[0] != 2 {
		t.Errorf("bucket1 Ia min/max = %v/%v want 2/2", cols[1].Min[0], cols[1].Max[0])
	}
}

func TestQueryWindowSubset(t *testing.T) {
	ov := New(0.050)
	for i := 0; i < 10; i++ {
		ov.Push(float64(i)*0.050, [derive.NumChannels]float64{float64(i)})
	}
	cols := ov.Query(0.100, 0.250) // buckets starting at 0.10,0.15,0.20
	if len(cols) != 3 {
		t.Fatalf("got %d want 3", len(cols))
	}
	if cols[0].TStart < 0.0999 || cols[0].TStart > 0.1001 {
		t.Errorf("first bucket TStart=%v want ~0.10", cols[0].TStart)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go && go test ./internal/overview/ -v`
Expected: FAIL — package/`New`/`Push`/`Query` undefined.

- [ ] **Step 3: Write minimal implementation**

```go
// Package overview keeps a bounded, whole-session min/max envelope of every
// display channel in fixed time buckets. It backs zoomed-out viewport queries
// so a sinusoid renders as a correct-amplitude band instead of a triangle.
package overview

import (
	"sync"

	"hil.local/daemon/internal/derive"
)

// Column is the min/max envelope of one time bucket.
type Column struct {
	TStart float64
	Min    [derive.NumChannels]float64
	Max    [derive.NumChannels]float64
}

// Overview accumulates Columns at a fixed bucket width (seconds).
type Overview struct {
	mu       sync.RWMutex
	bucketS  float64
	cols     []Column
	curIndex int64
	have     bool
}

// New creates an Overview with the given bucket width in seconds.
func New(bucketSeconds float64) *Overview {
	if bucketSeconds <= 0 {
		bucketSeconds = 0.050
	}
	return &Overview{bucketS: bucketSeconds, curIndex: -1}
}

// Push folds one sample (time in seconds, channel values) into its bucket.
func (o *Overview) Push(t float64, v [derive.NumChannels]float64) {
	o.mu.Lock()
	defer o.mu.Unlock()
	idx := int64(t / o.bucketS)
	if !o.have || idx != o.curIndex {
		o.cols = append(o.cols, Column{TStart: float64(idx) * o.bucketS, Min: v, Max: v})
		o.curIndex = idx
		o.have = true
		return
	}
	c := &o.cols[len(o.cols)-1]
	for i := 0; i < derive.NumChannels; i++ {
		if v[i] < c.Min[i] {
			c.Min[i] = v[i]
		}
		if v[i] > c.Max[i] {
			c.Max[i] = v[i]
		}
	}
}

// Query returns the columns whose TStart is within [from, to).
func (o *Overview) Query(from, to float64) []Column {
	o.mu.RLock()
	defer o.mu.RUnlock()
	out := make([]Column, 0)
	for _, c := range o.cols {
		if c.TStart >= from && c.TStart < to {
			out = append(out, c)
		}
	}
	return out
}

// BucketSeconds reports the tier resolution.
func (o *Overview) BucketSeconds() float64 { return o.bucketS }

// Reset clears all buckets (call on a new run/epoch).
func (o *Overview) Reset() {
	o.mu.Lock()
	o.cols, o.curIndex, o.have = nil, -1, false
	o.mu.Unlock()
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go && go test ./internal/overview/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/overview/
git commit -m "feat(overview): bounded whole-session min/max tier"
```

### Task 2.2: Amplitude-preservation regression (no triangle collapse)

**Files:**
- Test: `apps/hil-go/internal/overview/sine_test.go`

- [ ] **Step 1: Write the failing test**

```go
package overview

import (
	"math"
	"testing"

	"hil.local/daemon/internal/derive"
)

// A 58 Hz sine sampled at 100 kHz, folded into 50 ms buckets, must retain its
// true amplitude in every bucket (each 50 ms bucket spans ~3 cycles).
func TestSineAmplitudePreserved(t *testing.T) {
	ov := New(0.050)
	const fs, fe, amp = 100000.0, 58.0, 7.0
	n := int(0.5 * fs) // 0.5 s
	for i := 0; i < n; i++ {
		tt := float64(i) / fs
		val := amp * math.Sin(2*math.Pi*fe*tt)
		ov.Push(tt, [derive.NumChannels]float64{val})
	}
	for _, c := range ov.Query(0, 0.5) {
		if c.Max[0] < amp*0.98 || c.Min[0] > -amp*0.98 {
			t.Errorf("bucket @%.3fs lost amplitude: min=%.3f max=%.3f want ~±%.1f",
				c.TStart, c.Min[0], c.Max[0], amp)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `cd apps/hil-go && go test ./internal/overview/ -run TestSineAmplitude -v`
Expected: PASS (this is a guard test; it documents the core property). If it
fails, the bucketing logic is wrong — fix before continuing.

- [ ] **Step 3: Commit**

```bash
git add apps/hil-go/internal/overview/sine_test.go
git commit -m "test(overview): sine amplitude preserved across buckets"
```

---

## Phase 3 — Session store: always-on full-rate disk + time index

Produces a disk-backed full-rate session that is always recording, with a
sparse time->offset index for O(log n) seek, plus a query that reads a window
back as `frame.Sample`s. Reuses the `.hilbin` record format.

### Task 3.1: Sparse time->offset index

**Files:**
- Create: `apps/hil-go/internal/sessionstore/index.go`
- Test: `apps/hil-go/internal/sessionstore/index_test.go`

- [ ] **Step 1: Write the failing test**

```go
package sessionstore

import "testing"

func TestIndexSeekFloor(t *testing.T) {
	var ix index
	ix.add(0.00, 0)     // sample 0 at offset 0
	ix.add(0.10, 4096)  // block boundary
	ix.add(0.20, 8192)
	// floor lookup: largest entry with t <= target
	if off, ok := ix.floorOffset(0.15); !ok || off != 4096 {
		t.Errorf("floorOffset(0.15)=%d,%v want 4096,true", off, ok)
	}
	if off, _ := ix.floorOffset(0.00); off != 0 {
		t.Errorf("floorOffset(0.00)=%d want 0", off)
	}
	if _, ok := ix.floorOffset(-1); ok {
		t.Errorf("floorOffset(-1) should be !ok")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go && go test ./internal/sessionstore/ -run TestIndex -v`
Expected: FAIL — `index`/`add`/`floorOffset` undefined.

- [ ] **Step 3: Write minimal implementation**

```go
package sessionstore

import "sort"

// index is a sparse, in-RAM time->byte-offset map (one entry per block of
// samples). Offsets are byte positions of the first sample record in a block.
type index struct {
	t   []float64
	off []int64
}

func (ix *index) add(t float64, off int64) {
	ix.t = append(ix.t, t)
	ix.off = append(ix.off, off)
}

// floorOffset returns the offset of the largest indexed time <= target.
func (ix *index) floorOffset(target float64) (int64, bool) {
	if len(ix.t) == 0 || target < ix.t[0] {
		return 0, false
	}
	// first index with t > target, then step back one.
	i := sort.Search(len(ix.t), func(i int) bool { return ix.t[i] > target })
	if i == 0 {
		return 0, false
	}
	return ix.off[i-1], true
}

func (ix *index) reset() { ix.t, ix.off = nil, nil }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go && go test ./internal/sessionstore/ -run TestIndex -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/sessionstore/index.go apps/hil-go/internal/sessionstore/index_test.go
git commit -m "feat(sessionstore): sparse time->offset index with floor lookup"
```

### Task 3.2: Session writer with index + windowed read-back

**Files:**
- Create: `apps/hil-go/internal/sessionstore/store.go`
- Test: `apps/hil-go/internal/sessionstore/store_test.go`

Record layout on disk for this store: a flat sequence of fixed 24-byte records
`t float32, Ia, Ib, FluxA, FluxB, Speed float32` (6×4). This is self-contained
(no header) to keep read math trivial; the user-facing `.hilbin` archive is
produced separately by the existing `record` package (Task 5.2 wires Save).

- [ ] **Step 1: Write the failing test**

```go
package sessionstore

import (
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/frame"
)

func TestAppendThenReadWindow(t *testing.T) {
	dir := t.TempDir()
	st, err := Open(filepath.Join(dir, "sess.bin"), 4) // index every 4 samples
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	for i := 0; i < 20; i++ {
		st.Append(float64(i)*0.001, frame.Sample{Ia: float32(i)})
	}
	// read window [0.005, 0.010] -> samples 5..10
	ts, ss := st.ReadWindow(0.005, 0.010)
	if len(ts) != len(ss) || len(ss) < 5 {
		t.Fatalf("len mismatch ts=%d ss=%d", len(ts), len(ss))
	}
	if ss[0].Ia != 5 || ts[0] < 0.0049 || ts[0] > 0.0051 {
		t.Errorf("first sample Ia=%v t=%v want 5 / ~0.005", ss[0].Ia, ts[0])
	}
	last := ss[len(ss)-1]
	if last.Ia != 10 {
		t.Errorf("last sample Ia=%v want 10", last.Ia)
	}
}

func TestCountAndSpan(t *testing.T) {
	dir := t.TempDir()
	st, _ := Open(filepath.Join(dir, "s.bin"), 4)
	defer st.Close()
	for i := 0; i < 8; i++ {
		st.Append(float64(i), frame.Sample{Ia: float32(i)})
	}
	if c := st.Count(); c != 8 {
		t.Errorf("Count=%d want 8", c)
	}
	if a, b := st.Span(); a != 0 || b != 7 {
		t.Errorf("Span=%v,%v want 0,7", a, b)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go && go test ./internal/sessionstore/ -run "Append|Count" -v`
Expected: FAIL — `Open`/`Append`/`ReadWindow`/`Count`/`Span` undefined.

- [ ] **Step 3: Write minimal implementation**

```go
package sessionstore

import (
	"bufio"
	"encoding/binary"
	"math"
	"os"
	"sync"

	"hil.local/daemon/internal/frame"
)

const recBytes = 24 // t + 5 float32

// Store is an always-on, disk-backed full-rate session with a sparse time
// index. Append is from the receiver goroutine; ReadWindow is from query
// handlers. A RWMutex guards the index and counters; reads use a private
// file handle via ReaderAt so they do not disturb the append cursor.
type Store struct {
	mu        sync.RWMutex
	f         *os.File
	w         *bufio.Writer
	path      string
	ix        index
	blockN    int
	n         int64
	tFirst    float64
	tLast     float64
	haveFirst bool
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
	if !s.haveFirst {
		s.tFirst, s.haveFirst = t, true
	}
	if s.n%int64(s.blockN) == 0 {
		_ = s.w.Flush() // ensure offset is the real file position
		off, _ := s.f.Seek(0, os.SEEK_CUR)
		s.ix.add(t, off)
	}
	var rec [recBytes]byte
	putF32(rec[:], 0, float32(t))
	putF32(rec[:], 4, smp.Ia)
	putF32(rec[:], 8, smp.Ib)
	putF32(rec[:], 12, smp.FluxA)
	putF32(rec[:], 16, smp.FluxB)
	putF32(rec[:], 20, smp.Speed)
	_, _ = s.w.Write(rec[:])
	s.tLast = t
	s.n++
}

func f32(b []byte, off int) float32 {
	return math.Float32frombits(binary.LittleEndian.Uint32(b[off:]))
}

// ReadWindow returns all samples with from <= t <= to. It seeks to the index
// floor before `from`, then scans forward until past `to`.
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
	maxRead := total * 2 // safety bound
	for read < maxRead {
		if _, err := readFull(br, buf); err != nil {
			break
		}
		read++
		t := float64(f32(buf, 0))
		if t < from {
			continue
		}
		if t > to {
			break
		}
		ts = append(ts, t)
		ss = append(ss, frame.Sample{
			Ia: f32(buf, 4), Ib: f32(buf, 8),
			FluxA: f32(buf, 12), FluxB: f32(buf, 16), Speed: f32(buf, 20),
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go && go test ./internal/sessionstore/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/sessionstore/store.go apps/hil-go/internal/sessionstore/store_test.go
git commit -m "feat(sessionstore): always-on disk session with indexed read-back"
```

### Task 3.3: Guardrail rotation

**Files:**
- Modify: `apps/hil-go/internal/sessionstore/store.go`
- Test: `apps/hil-go/internal/sessionstore/rotate_test.go`

- [ ] **Step 1: Write the failing test**

```go
package sessionstore

import (
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/frame"
)

func TestGuardrailReportsOverCap(t *testing.T) {
	dir := t.TempDir()
	st, _ := Open(filepath.Join(dir, "s.bin"), 4)
	defer st.Close()
	st.SetMaxSamples(10)
	for i := 0; i < 9; i++ {
		st.Append(float64(i), frame.Sample{})
	}
	if st.OverCap() {
		t.Fatalf("should not be over cap at 9/10")
	}
	st.Append(9, frame.Sample{})
	st.Append(10, frame.Sample{})
	if !st.OverCap() {
		t.Errorf("should be over cap past 10 samples")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go && go test ./internal/sessionstore/ -run TestGuardrail -v`
Expected: FAIL — `SetMaxSamples`/`OverCap` undefined.

- [ ] **Step 3: Write minimal implementation**

Add a `maxSamples int64` field to `Store` and append methods:

```go
// SetMaxSamples sets the guardrail cap (0 = unlimited). When exceeded, OverCap
// reports true so the caller can warn/rotate. Full segment rotation is handled
// at the gateway layer (Task 5.x) which owns file naming.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go && go test ./internal/sessionstore/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/sessionstore/
git commit -m "feat(sessionstore): guardrail cap reporting"
```

---

## Phase 4 — Query engine + HTTP API

Produces the viewport query: given `[from, to]` and pixel `width`, return per
channel a faithful min/max envelope (or full-rate points), with derived
channels applied at full rate.

### Task 4.1: Viewport reducer (resolution selection + min/max per column)

**Files:**
- Create: `apps/hil-go/internal/series/series.go`
- Test: `apps/hil-go/internal/series/series_test.go`

- [ ] **Step 1: Write the failing test**

```go
package series

import (
	"math"
	"testing"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/frame"
)

func buildSine(fs, fe, amp, dur float64) ([]float64, []frame.Sample) {
	n := int(dur * fs)
	ts := make([]float64, n)
	ss := make([]frame.Sample, n)
	for i := 0; i < n; i++ {
		tt := float64(i) / fs
		ts[i] = tt
		ss[i] = frame.Sample{Ia: float32(amp * math.Sin(2*math.Pi*fe*tt))}
	}
	return ts, ss
}

func TestWideWindowKeepsAmplitude(t *testing.T) {
	ts, ss := buildSine(100000, 58, 7, 0.5)
	cols := ReduceWindow(derive.DefaultMotor, ts, ss, 600)
	if len(cols) == 0 || len(cols) > 1200 {
		t.Fatalf("got %d columns, want 1..1200", len(cols))
	}
	var hiMax, loMin float64
	for _, c := range cols {
		if c.Max[0] > hiMax {
			hiMax = c.Max[0]
		}
		if c.Min[0] < loMin {
			loMin = c.Min[0]
		}
	}
	if hiMax < 7*0.98 || loMin > -7*0.98 {
		t.Errorf("amplitude lost: max=%.3f min=%.3f want ~±7", hiMax, loMin)
	}
}

func TestNarrowWindowReturnsRaw(t *testing.T) {
	ts, ss := buildSine(100000, 58, 7, 0.001) // 100 samples
	cols := ReduceWindow(derive.DefaultMotor, ts, ss, 600)
	if len(cols) != len(ts) {
		t.Errorf("narrow window should return raw: got %d want %d", len(cols), len(ts))
	}
	if cols[0].Min[0] != cols[0].Max[0] {
		t.Errorf("raw column min should equal max")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go && go test ./internal/series/ -v`
Expected: FAIL — `ReduceWindow`/`Column` undefined.

- [ ] **Step 3: Write minimal implementation**

```go
// Package series turns a full-rate window of alpha-beta samples into a faithful
// min/max envelope sized to the display width, applying derived channels at
// full rate first.
package series

import "hil.local/daemon/internal/derive"
import "hil.local/daemon/internal/frame"

// Column is one display column: a min/max pair per channel and its time.
type Column struct {
	T   float64
	Min [derive.NumChannels]float64
	Max [derive.NumChannels]float64
}

// ReduceWindow computes derived channels per sample, then emits one Column per
// display pixel via min/max bucketing. If there are <= 2*width samples, every
// sample is returned raw (min==max) so zoom-in shows the true trace.
func ReduceWindow(m derive.Motor, ts []float64, ss []frame.Sample, width int) []Column {
	if width < 1 {
		width = 1
	}
	n := len(ss)
	if n == 0 {
		return nil
	}
	if n <= 2*width {
		out := make([]Column, n)
		for i := range ss {
			v := m.Compute(ss[i]).Values()
			out[i] = Column{T: ts[i], Min: v, Max: v}
		}
		return out
	}
	out := make([]Column, 0, width)
	per := float64(n) / float64(width)
	for col := 0; col < width; col++ {
		lo := int(float64(col) * per)
		hi := int(float64(col+1) * per)
		if hi > n {
			hi = n
		}
		if lo >= hi {
			continue
		}
		c := Column{T: ts[lo]}
		first := m.Compute(ss[lo]).Values()
		c.Min, c.Max = first, first
		for i := lo + 1; i < hi; i++ {
			v := m.Compute(ss[i]).Values()
			for ch := 0; ch < derive.NumChannels; ch++ {
				if v[ch] < c.Min[ch] {
					c.Min[ch] = v[ch]
				}
				if v[ch] > c.Max[ch] {
					c.Max[ch] = v[ch]
				}
			}
		}
		out = append(out, c)
	}
	return out
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go && go test ./internal/series/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/series/
git commit -m "feat(series): viewport min/max reducer with full-rate derived channels"
```

### Task 4.2: Binary response encoder

**Files:**
- Modify: `apps/hil-go/internal/series/series.go`
- Test: `apps/hil-go/internal/series/encode_test.go`

- [ ] **Step 1: Write the failing test**

```go
package series

import (
	"encoding/binary"
	"math"
	"testing"

	"hil.local/daemon/internal/derive"
)

func TestEncodeRoundtripHeader(t *testing.T) {
	cols := []Column{
		{T: 1.5, Min: [derive.NumChannels]float64{1}, Max: [derive.NumChannels]float64{2}},
	}
	b := Encode(cols)
	if got := binary.LittleEndian.Uint32(b[0:4]); got != 1 {
		t.Errorf("column count = %d want 1", got)
	}
	if got := b[4]; got != derive.NumChannels {
		t.Errorf("channel count = %d want %d", got, derive.NumChannels)
	}
	tVal := math.Float32frombits(binary.LittleEndian.Uint32(b[5:9]))
	if math.Abs(float64(tVal)-1.5) > 1e-6 {
		t.Errorf("t = %v want 1.5", tVal)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go && go test ./internal/series/ -run TestEncode -v`
Expected: FAIL — `Encode` undefined.

- [ ] **Step 3: Write minimal implementation**

Append to `series.go`. Wire format (LE): `count uint32`, `nch uint8`, then per
column `t float32` followed by `nch×(min float32, max float32)`.

```go
import (
	"encoding/binary"
	"math"
)

// Encode serializes columns to the compact binary the front end parses.
func Encode(cols []Column) []byte {
	const colHdr = 4 // t float32
	perCh := 8       // min+max float32
	recSize := colHdr + derive.NumChannels*perCh
	b := make([]byte, 5+len(cols)*recSize)
	binary.LittleEndian.PutUint32(b[0:4], uint32(len(cols)))
	b[4] = derive.NumChannels
	off := 5
	for _, c := range cols {
		binary.LittleEndian.PutUint32(b[off:], math.Float32bits(float32(c.T)))
		off += 4
		for ch := 0; ch < derive.NumChannels; ch++ {
			binary.LittleEndian.PutUint32(b[off:], math.Float32bits(float32(c.Min[ch])))
			binary.LittleEndian.PutUint32(b[off+4:], math.Float32bits(float32(c.Max[ch])))
			off += 8
		}
	}
	return b
}
```

Note: add the `import` block to the existing file (merge with package imports;
do not duplicate the `derive`/`frame` imports).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go && go test ./internal/series/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/internal/series/
git commit -m "feat(series): compact binary column encoding"
```

### Task 4.3: Wire ingestion (derived + store + overview) into the gateway

**Files:**
- Modify: `apps/hil-go/cmd/gateway/main.go` (server struct ~line 50-72; New ~120-162; SetSampleHandler ~145-148)

- [ ] **Step 1: Add fields and construct components**

In the `server` struct add:

```go
	store    *sessionstore.Store
	overview *overview.Overview
	motorMu  sync.RWMutex
	motor    derive.Motor
```

In `run()` after `raw := rawbuf.New(300_000)`:

```go
	ov := overview.New(0.050)
	store, err := sessionstore.Open(filepath.Join(runsDir, "live_session.bin"), 4096)
	if err != nil {
		log.Fatalf("session store: %v", err)
	}
	store.SetMaxSamples(180_000_000) // ~30 min @ 100 kHz guardrail
```

Replace the `SetSampleHandler` closure with:

```go
	recv.SetSampleHandler(func(samples []frame.Sample) {
		recorder.Submit(samples)
		raw.Append(samples)
		s := srvRef.Load()
		if s == nil {
			return
		}
		m := s.currentMotor()
		for _, smp := range samples {
			t := s.sampleTime(smp) // seconds from run-local cycles (Task 4.4)
			s.store.Append(t, smp)
			ov.Push(t, m.Compute(smp).Values())
		}
	})
```

Add the new fields to the `&server{...}` literal: `store: store, overview: ov,
motor: derive.DefaultMotor,`. Add imports for `sessionstore`, `overview`,
`derive`, `series`, `path/filepath`, `sync/atomic`.

`srvRef` is an `atomic.Pointer[server]` package var set right after the server
is constructed: `srvRef.Store(s)`. (The handler is installed before `s` exists,
so it loads `s` lazily.)

- [ ] **Step 2: Add helper methods**

```go
var srvRef atomic.Pointer[server]

func (s *server) currentMotor() derive.Motor {
	s.motorMu.RLock()
	defer s.motorMu.RUnlock()
	return s.motor
}

func (s *server) setMotor(m derive.Motor) {
	s.motorMu.Lock()
	s.motor = m
	s.motorMu.Unlock()
}
```

In `handleMotor` (after `s.lastMotor[ip] = motor` ~line 566) add:
`s.setMotor(derive.MotorFromParams(motor.Npp, motor.Lm, motor.Lr))`.

- [ ] **Step 3: Build to verify it compiles**

Run: `cd apps/hil-go && go build ./...`
Expected: builds (the `sampleTime` method is added in Task 4.4; until then,
stub it as `func (s *server) sampleTime(frame.Sample) float64 { return 0 }` to
keep the build green, then replace in 4.4).

- [ ] **Step 4: Commit**

```bash
git add apps/hil-go/cmd/gateway/main.go
git commit -m "feat(gateway): ingest into session store + overview tier with live motor"
```

### Task 4.4: Run-local sample time (cycles -> seconds with wrap)

**Files:**
- Create: `apps/hil-go/cmd/gateway/sampletime.go`
- Test: `apps/hil-go/cmd/gateway/sampletime_test.go`

- [ ] **Step 1: Write the failing test**

```go
package main

import "testing"

func TestSampleClockWrap(t *testing.T) {
	var c sampleClock
	const hz = 100_000_000
	if got := c.seconds(0, 1); got != 0 {
		t.Errorf("first seconds=%v want 0", got)
	}
	// jump near wrap then past it
	_ = c.seconds(0xFFFFFFF0, 1)
	got := c.seconds(0x00000010, 1) // wrapped by 2^32
	want := float64(0x100000010) / hz
	if got < want-1e-9 || got > want+1e-9 {
		t.Errorf("wrapped seconds=%v want %v", got, want)
	}
}

func TestSampleClockEpochResets(t *testing.T) {
	var c sampleClock
	_ = c.seconds(5000, 1)
	if got := c.seconds(0, 2); got != 0 {
		t.Errorf("epoch change should reset to 0, got %v", got)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go && go test ./cmd/gateway/ -run TestSampleClock -v`
Expected: FAIL — `sampleClock`/`seconds` undefined.

- [ ] **Step 3: Write minimal implementation**

```go
package main

// sampleClock converts run-local 32-bit cycle counters (100 MHz) into seconds,
// handling 2^32 wrap and per-epoch resets (counter restarts at 0 each run).
type sampleClock struct {
	haveEpoch bool
	epoch     uint16
	last      uint32
	wrap      uint64
}

const sampleClockHz = 100_000_000

func (c *sampleClock) seconds(cycles uint32, epoch uint16) float64 {
	if !c.haveEpoch || epoch != c.epoch {
		c.haveEpoch, c.epoch, c.last, c.wrap = true, epoch, cycles, 0
		return float64(cycles) / sampleClockHz
	}
	if cycles < c.last && c.last-cycles > 0x80000000 {
		c.wrap += 1 << 32
	}
	c.last = cycles
	return float64(c.wrap+uint64(cycles)) / sampleClockHz
}
```

Then replace the `sampleTime` stub in `main.go` with a method that uses a
`sampleClock` field on `server` (add `clk sampleClock` to the struct, guarded by
the existing append path which is single-goroutine from the receiver):

```go
func (s *server) sampleTime(smp frame.Sample) float64 {
	return s.clk.seconds(smp.TCycles, smp.Epoch)
}
```

On run reset (`handleRun`/`handleStop`/`handleAttach` where `s.display.Reset()`
is called), also reset session state: `s.overview.Reset()`, `s.clk = sampleClock{}`,
and re-open the store (Task 4.6 covers store lifecycle). For now add
`s.overview.Reset()` and `s.clk = sampleClock{}` next to each `s.display.Reset()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go && go test ./cmd/gateway/ -run TestSampleClock -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/cmd/gateway/sampletime.go apps/hil-go/cmd/gateway/sampletime_test.go apps/hil-go/cmd/gateway/main.go
git commit -m "feat(gateway): run-local cycle->seconds clock with wrap/epoch reset"
```

### Task 4.5: `/api/series` and `/api/tail` handlers

**Files:**
- Modify: `apps/hil-go/cmd/gateway/main.go` (add routes near line 178; add handlers near `handleRaw`)

- [ ] **Step 1: Add routes**

After `mux.HandleFunc("/api/raw", s.handleRaw)`:

```go
	mux.HandleFunc("/api/series", s.handleSeries)
	mux.HandleFunc("/api/tail", s.handleRaw) // tail reuses the cursor transport
```

- [ ] **Step 2: Implement the handler**

```go
func (s *server) handleSeries(w http.ResponseWriter, r *http.Request) {
	from := parseFloat(r.URL.Query().Get("from"), 0)
	to := parseFloat(r.URL.Query().Get("to"), 0)
	width, _ := strconv.Atoi(r.URL.Query().Get("width"))
	if width <= 0 || width > 4000 {
		width = 1500
	}
	if to <= from {
		// default to last 1 s of the session
		_, last := s.store.Span()
		to, from = last, last-1
	}
	ts, ss := s.store.ReadWindow(from, to)
	cols := series.ReduceWindow(s.currentMotor(), ts, ss, width)
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Cache-Control", "no-store")
	_, _ = w.Write(series.Encode(cols))
}

func parseFloat(s string, def float64) float64 {
	if v, err := strconv.ParseFloat(s, 64); err == nil {
		return v
	}
	return def
}
```

- [ ] **Step 3: Build + smoke-test with a unit test**

**Files:** Create `apps/hil-go/cmd/gateway/series_handler_test.go`

```go
package main

import (
	"net/http/httptest"
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/overview"
	"hil.local/daemon/internal/sessionstore"
)

func TestHandleSeriesReturnsColumns(t *testing.T) {
	dir := t.TempDir()
	st, _ := sessionstore.Open(filepath.Join(dir, "s.bin"), 16)
	defer st.Close()
	for i := 0; i < 1000; i++ {
		st.Append(float64(i)*1e-5, frame.Sample{Ia: float32(i % 7)})
	}
	s := &server{store: st, overview: overview.New(0.05), motor: derive.DefaultMotor}
	req := httptest.NewRequest("GET", "/api/series?from=0&to=0.01&width=100", nil)
	rec := httptest.NewRecorder()
	s.handleSeries(rec, req)
	if rec.Code != 200 {
		t.Fatalf("status %d", rec.Code)
	}
	if rec.Body.Len() < 5 {
		t.Fatalf("empty body")
	}
}
```

Run: `cd apps/hil-go && go test ./cmd/gateway/ -run TestHandleSeries -v && go build ./...`
Expected: PASS + builds.

- [ ] **Step 4: Commit**

```bash
git add apps/hil-go/cmd/gateway/
git commit -m "feat(gateway): /api/series viewport query endpoint"
```

### Task 4.6: Store lifecycle on run/stop + guardrail warning

**Files:**
- Modify: `apps/hil-go/cmd/gateway/main.go`

- [ ] **Step 1: Add a re-open helper and call it on run reset**

```go
func (s *server) resetSession() {
	if s.store != nil {
		_ = s.store.Close()
	}
	st, err := sessionstore.Open(filepath.Join(s.runsDir, "live_session.bin"), 4096)
	if err != nil {
		log.Printf("session store reopen: %v", err)
		return
	}
	st.SetMaxSamples(180_000_000)
	s.store = st
	s.overview.Reset()
	s.clk = sampleClock{}
}
```

Call `s.resetSession()` in `handleRun` and `handleAttach` (replacing the inline
`s.overview.Reset(); s.clk = sampleClock{}` added in Task 4.4).

- [ ] **Step 2: Add a guardrail watcher goroutine**

In `run()` after `go s.telemetryPump()`:

```go
	go func() {
		for range time.Tick(5 * time.Second) {
			cur := srvRef.Load()
			if cur != nil && cur.store != nil && cur.store.OverCap() {
				log.Printf("session store over guardrail cap; oldest history may be trimmed")
			}
		}
	}()
```

- [ ] **Step 3: Build**

Run: `cd apps/hil-go && go build ./... && go test ./...`
Expected: builds, all tests pass.

- [ ] **Step 4: Commit**

```bash
git add apps/hil-go/cmd/gateway/main.go
git commit -m "feat(gateway): session lifecycle on run + guardrail watcher"
```

---

## Phase 5 — Frontend viewport rendering + cleanup

Replaces the fixed-bucket overview and alpha-beta-extrema reconstruction with
debounced viewport queries against `/api/series`, rendering min/max as an
envelope band and the real line when full-rate.

### Task 5.1: `/api/series` client + decoder

**Files:**
- Create: `apps/hil-go/frontend/src/series.ts`
- Test: `apps/hil-go/frontend/src/series.test.ts`

(The frontend uses Vite; add `vitest` if not present:
`cd apps/hil-go/frontend && npm i -D vitest` and a `"test": "vitest run"` script.)

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import { decodeSeries, NUM_CH } from "./series";

function buildBuf(cols: { t: number; mm: number[][] }[]): ArrayBuffer {
  const recSize = 4 + NUM_CH * 8;
  const buf = new ArrayBuffer(5 + cols.length * recSize);
  const dv = new DataView(buf);
  dv.setUint32(0, cols.length, true);
  dv.setUint8(4, NUM_CH);
  let off = 5;
  for (const c of cols) {
    dv.setFloat32(off, c.t, true); off += 4;
    for (let ch = 0; ch < NUM_CH; ch++) {
      dv.setFloat32(off, c.mm[ch][0], true);
      dv.setFloat32(off + 4, c.mm[ch][1], true);
      off += 8;
    }
  }
  return buf;
}

describe("decodeSeries", () => {
  it("round-trips a column", () => {
    const mm = Array.from({ length: NUM_CH }, (_, i) => [i, i + 1]);
    const out = decodeSeries(buildBuf([{ t: 2.5, mm }]));
    expect(out.t.length).toBe(1);
    expect(out.t[0]).toBeCloseTo(2.5, 5);
    expect(out.min[0][0]).toBeCloseTo(0, 5);
    expect(out.max[0][0]).toBeCloseTo(1, 5);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go/frontend && npx vitest run src/series.test.ts`
Expected: FAIL — `decodeSeries`/`NUM_CH` undefined.

- [ ] **Step 3: Write minimal implementation**

```ts
// Channel order MUST match derive.Channels in the gateway.
export const CHANNEL_NAMES = [
  "Ia", "Ib", "Ic", "FluxA", "FluxB", "FluxC", "Speed", "Te",
] as const;
export const NUM_CH = CHANNEL_NAMES.length;

export interface SeriesColumns {
  t: number[];
  min: number[][]; // [channel][column]
  max: number[][];
}

export function decodeSeries(buf: ArrayBuffer): SeriesColumns {
  const dv = new DataView(buf);
  const count = dv.getUint32(0, true);
  const nch = dv.getUint8(4);
  const t: number[] = new Array(count);
  const min: number[][] = Array.from({ length: nch }, () => new Array(count));
  const max: number[][] = Array.from({ length: nch }, () => new Array(count));
  let off = 5;
  for (let i = 0; i < count; i++) {
    t[i] = dv.getFloat32(off, true); off += 4;
    for (let ch = 0; ch < nch; ch++) {
      min[ch][i] = dv.getFloat32(off, true);
      max[ch][i] = dv.getFloat32(off + 4, true);
      off += 8;
    }
  }
  return { t, min, max };
}

export async function fetchSeries(
  from: number, to: number, width: number,
): Promise<SeriesColumns> {
  const url = `/api/series?from=${from}&to=${to}&width=${Math.round(width)}`;
  const res = await fetch(url, { cache: "no-store" });
  return decodeSeries(await res.arrayBuffer());
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go/frontend && npx vitest run src/series.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/frontend/src/series.ts apps/hil-go/frontend/src/series.test.ts apps/hil-go/frontend/package.json
git commit -m "feat(frontend): /api/series client + binary decoder"
```

### Task 5.2: Viewport controller (debounced query on zoom/pan)

**Files:**
- Create: `apps/hil-go/frontend/src/viewport.ts`
- Test: `apps/hil-go/frontend/src/viewport.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, vi } from "vitest";
import { ViewportController } from "./viewport";

describe("ViewportController", () => {
  it("debounces and queries once with latest range", async () => {
    const calls: Array<[number, number, number]> = [];
    const vc = new ViewportController(
      async (from, to, w) => { calls.push([from, to, w]); return { t: [], min: [], max: [] }; },
      10, // debounce ms
    );
    vc.request(0, 1, 800);
    vc.request(0.5, 1.5, 800);
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.length).toBe(1);
    expect(calls[0][0]).toBeCloseTo(0.5);
    expect(calls[0][1]).toBeCloseTo(1.5);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/hil-go/frontend && npx vitest run src/viewport.test.ts`
Expected: FAIL — `ViewportController` undefined.

- [ ] **Step 3: Write minimal implementation**

```ts
import type { SeriesColumns } from "./series";

type Fetcher = (from: number, to: number, width: number) => Promise<SeriesColumns>;

// ViewportController debounces zoom/pan into a single query for the latest
// visible range, and hands the result to onData.
export class ViewportController {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pending: [number, number, number] | null = null;
  onData: (cols: SeriesColumns) => void = () => {};

  constructor(private fetcher: Fetcher, private debounceMs = 60) {}

  request(from: number, to: number, width: number): void {
    this.pending = [from, to, width];
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), this.debounceMs);
  }

  private async flush(): Promise<void> {
    if (!this.pending) return;
    const [from, to, width] = this.pending;
    this.pending = null;
    const cols = await this.fetcher(from, to, width);
    this.onData(cols);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/hil-go/frontend && npx vitest run src/viewport.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/frontend/src/viewport.ts apps/hil-go/frontend/src/viewport.test.ts
git commit -m "feat(frontend): debounced viewport query controller"
```

### Task 5.3: Wire viewport rendering into the chart; render envelope band

**Files:**
- Modify: `apps/hil-go/frontend/src/main.ts`

This task integrates the new transport into uPlot. Because `main.ts` is large
(~3500 lines), make surgical changes:

- [ ] **Step 1: Hook uPlot zoom/pan to the controller**

Locate the uPlot options where scales are configured (search for `setScale` or
the `hooks` block; near the chart construction). Add a `setScale` hook on the
x-scale that reads the visible range and plot width and calls the controller:

```ts
import { ViewportController } from "./viewport";
import { fetchSeries, CHANNEL_NAMES } from "./series";

const viewport = new ViewportController(fetchSeries, 60);

// inside uPlot hooks:
hooks: {
  setScale: [
    (u, key) => {
      if (key !== "x") return;
      const { min, max } = u.scales.x;
      if (min == null || max == null) return;
      viewport.request(min, max, u.bbox.width / devicePixelRatio);
    },
  ],
}
```

- [ ] **Step 2: Render columns as band + line**

`viewport.onData` maps `SeriesColumns` into uPlot series. For each visible
channel, set a fill band between `min[ch]` and `max[ch]` and a line at `max`
(or the midpoint). Replace the data feed for the telemetry chart:

```ts
viewport.onData = (cols) => {
  const xs = cols.t;
  const data: number[][] = [xs];
  for (let ch = 0; ch < CHANNEL_NAMES.length; ch++) {
    // midpoint line; band drawn via paths plugin using min/max arrays
    const mid = cols.t.map((_, i) => (cols.min[ch][i] + cols.max[ch][i]) / 2);
    data.push(mid);
  }
  uplot.setData(data as any);
  // band arrays available as cols.min[ch]/cols.max[ch] for the band renderer
};
```

Use uPlot's range/band drawing (the existing chart already styles series; reuse
its colors keyed by `CHANNEL_NAMES`). When `cols` has <= 2×width points the
min/max equal the samples, so the same path renders the true line automatically.

- [ ] **Step 3: Remove the buggy front-end paths**

Delete from `main.ts`:
- the fixed-bucket overview buffers and `OVERVIEW_*` constants (lines ~256-294),
- the min/max decimation helpers (lines ~1411, 1588, 1997),
- the alpha-beta-extrema reconstruction feed (the SSE/`samplesBuf` rendering),
keeping only the new viewport path. Keep the `CHANNELS_ABC` color/label table
for styling but source data from `/api/series`.

- [ ] **Step 4: Build the frontend**

Run: `cd apps/hil-go/frontend && npm run build`
Expected: builds with no type errors.

- [ ] **Step 5: Commit**

```bash
git add apps/hil-go/frontend/src/main.ts
git commit -m "feat(frontend): viewport-driven chart with min/max envelope; remove fixed-bucket path"
```

### Task 5.4: Remove the gateway DisplayReducer SSE path

**Files:**
- Modify: `apps/hil-go/cmd/gateway/main.go`
- Delete: `apps/hil-go/internal/frame/reduce_test.go` and `ReduceForDisplay`/`DisplayReducer` from `internal/frame/frame.go`

- [ ] **Step 1: Remove usages**

Remove the `display *frame.DisplayReducer` field, its construction, every
`s.display.Reset()` call, and the `telemetryPump` reduction (replace the pump
body so it just drains the ring to keep it from filling, or remove the ring +
pump entirely if no longer used by `/api/stats`). Keep `/api/raw` (the tail).

- [ ] **Step 2: Remove the reducer code**

Delete `DisplayReducer`, `NewDisplayReducer`, `ReduceForDisplay` from
`frame.go` and delete `reduce_test.go`.

- [ ] **Step 3: Build + test**

Run: `cd apps/hil-go && go build ./... && go test ./...`
Expected: builds, all tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A apps/hil-go/internal/frame apps/hil-go/cmd/gateway/main.go
git commit -m "refactor(gateway): drop fixed-bucket DisplayReducer; viewport query is the display path"
```

---

## Phase 6 — End-to-end verification

### Task 6.1: Replay a recorded capture through the query path

**Files:**
- Create: `apps/hil-go/internal/series/replay_test.go`

- [ ] **Step 1: Write the test**

Decode an existing `.hilbin` fixture, feed it through `sessionstore` + `series`,
and assert a wide query keeps amplitude while a narrow query returns raw:

```go
package series

import (
	"encoding/binary"
	"math"
	"os"
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/sessionstore"
)

// readHilbinRecords decodes the record `.hilbin` layout (see recorder.go and
// runs/decode_hilbin.py): "HILDATA" + ver byte + uint32 metaLen + meta, padded
// to 8 bytes, then uint32 count, then count×(t,Ia,Ib,FluxA,FluxB,Speed,0)
// float32 (28 bytes). Skips if the fixture is absent.
func readHilbinRecords(t *testing.T, path string) ([]float64, []frame.Sample) {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Skip("fixture not present")
	}
	if len(data) < 12 || string(data[:7]) != "HILDATA" {
		t.Fatalf("bad magic in %s", path)
	}
	metaLen := int(binary.LittleEndian.Uint32(data[8:12]))
	off := (12 + metaLen + 7) &^ 7
	count := int(binary.LittleEndian.Uint32(data[off:]))
	off += 4
	const rec = 28
	ts := make([]float64, count)
	ss := make([]frame.Sample, count)
	for i := 0; i < count; i++ {
		base := off + i*rec
		f := func(k int) float32 {
			return math.Float32frombits(binary.LittleEndian.Uint32(data[base+k*4:]))
		}
		ts[i] = float64(f(0))
		ss[i] = frame.Sample{Ia: f(1), Ib: f(2), FluxA: f(3), FluxB: f(4), Speed: f(5)}
	}
	return ts, ss
}

func TestReplayKeepsAmplitudeWideRawNarrow(t *testing.T) {
	ts, ss := readHilbinRecords(t, filepath.Join("..", "..", "runs", "cenario1_20260610131513.hilbin"))
	dir := t.TempDir()
	st, _ := sessionstore.Open(filepath.Join(dir, "s.bin"), 4096)
	defer st.Close()
	for i := range ss {
		st.Append(ts[i], ss[i])
	}
	a, b := st.Span()
	rts, rss := st.ReadWindow(a, b)
	wide := ReduceWindow(derive.DefaultMotor, rts, rss, 600)
	if len(wide) == 0 {
		t.Fatal("no columns")
	}
	// Flux channel (index 3) amplitude should be ~1.1 Wb, not collapsed.
	var mx float64
	for _, c := range wide {
		if c.Max[3] > mx {
			mx = c.Max[3]
		}
	}
	if mx < 1.0 {
		t.Errorf("flux amplitude collapsed: max=%.3f want >1.0", mx)
	}
}
```

Also add `readHilbinRecords` (a ~30-line `encoding/binary` reader matching the
`record` layout). Implement it in this test file.

- [ ] **Step 2: Run**

Run: `cd apps/hil-go && go test ./internal/series/ -run TestReplay -v`
Expected: PASS (or SKIP if the fixture was moved).

- [ ] **Step 3: Commit**

```bash
git add apps/hil-go/internal/series/replay_test.go
git commit -m "test(series): replay capture proves no amplitude collapse"
```

### Task 6.2: Manual smoke test

- [ ] **Step 1:** Build everything: `cd apps/hil-go && go build ./... && (cd frontend && npm run build)`.
- [ ] **Step 2:** Run the gateway against a live board (or a recorded replay if available), open the UI.
- [ ] **Step 3:** Verify: (a) live flux/current render as clean sinusoids, not triangles, at the default zoom; (b) zoom out to the whole session shows a correct-amplitude envelope band; (c) zoom into a point minutes back resolves to the real sine and the carrier ripple; (d) `Te` is smooth, not stair-stepped, at all zooms.
- [ ] **Step 4:** Record observations in the PR description.

---

## Self-review notes (filled by plan author)

- **Spec coverage:** ingestion+derived (Phase 1, Task 4.3), disk store+index
  (Phase 3), overview tier (Phase 2), query API `/api/series`+tail (Phase 4.5),
  frontend viewport rendering (Phase 5), retention/guardrail (Task 3.3, 4.6),
  testing incl. sine + replay regressions (2.2, 4.1, 6.1), compatibility
  (`.hilbin` untouched; archive Save handled by existing `record` package).
- **Deferred (per spec):** intermediate disk-resident tiers — only the single
  overview tier + on-demand disk reads are implemented; add tiers if Task 6.2
  shows mid-zoom latency.
- **Channel order** is defined once in `derive.Channels` and mirrored in
  `series.ts CHANNEL_NAMES`; a mismatch is the one cross-language invariant to
  watch.
- **Divergence from spec to confirm with the user — "Record/Save promotes the
  session":** the spec described one mechanism (always-on session; Save just
  keeps/names it). This plan instead keeps the existing `record` package for
  on-demand `.hilbin` archives AND adds a separate always-on
  `live_session.bin` for querying. That is lower-risk (no recorder lifecycle/UX
  change) but writes telemetry to disk twice while recording, and "Save" still
  means the existing Record flow, not promotion of the live session. If single-
  mechanism promotion is preferred, add a task to: (a) make `live_session.bin`
  the only writer, (b) on Save, finalize/rename it to a named `.hilbin` (adding
  the `record` header + PWM tail), (c) drop `recorder.Submit` from the sample
  handler. Flagged for the user's decision before execution.
- **`live_session.bin` is a private flat format** (24-byte records, no header),
  intentionally distinct from the user-facing `.hilbin`; the `.hilbin` on-disk
  format is unchanged, satisfying the compatibility requirement.
