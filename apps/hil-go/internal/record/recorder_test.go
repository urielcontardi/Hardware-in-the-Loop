package record

import (
	"encoding/binary"
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pwmrecv"
)

func TestRecorderWritesCompatibleHilbinAcrossTimestampWrap(t *testing.T) {
	dir := t.TempDir()
	r := New(dir)
	defer r.Close()
	if _, err := r.Start("test"); err != nil {
		t.Fatal(err)
	}
	samples := []frame.Sample{
		{TCycles: 123, Epoch: 6, Ia: 99},
		{TCycles: ^uint32(0) - 10, Epoch: 7, Ia: 1, Ib: 2, FluxA: 3, FluxB: 4, Speed: 5},
		{TCycles: 5, Epoch: 7, Ia: 6, Ib: 7, FluxA: 8, FluxB: 9, Speed: 10},
		{TCycles: 25, Epoch: 7, Ia: 11, Ib: 12, FluxA: 13, FluxB: 14, Speed: 15},
	}
	r.Submit(samples[:3])
	r.Submit(samples[3:])
	r.SubmitPWM(clockHz, []pwmrecv.Event{{TCycles: 5, Epoch: 7, A: 1, B: 2, C: 3}})
	if err := r.Stop(); err != nil {
		t.Fatal(err)
	}
	dst := filepath.Join(dir, "saved.hilbin")
	copied, err := r.CopyLatest(dst, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !copied {
		t.Fatal("expected completed raw capture")
	}
	data, err := os.ReadFile(dst)
	if err != nil {
		t.Fatal(err)
	}
	if string(data[:7]) != "HILDATA" {
		t.Fatalf("bad magic %q", data[:7])
	}
	metaLen := int(binary.LittleEndian.Uint32(data[8:12]))
	var meta map[string]any
	if err := json.Unmarshal(data[12:12+metaLen], &meta); err != nil {
		t.Fatal(err)
	}
	if raw, _ := meta["raw"].(bool); !raw {
		t.Fatalf("metadata does not mark raw capture: %#v", meta)
	}
	off := (12 + metaLen + 7) &^ 7
	count := binary.LittleEndian.Uint32(data[off:])
	if count != 3 {
		t.Fatalf("count=%d want 3", count)
	}
	off += 4
	readTime := func(index int) float32 {
		pos := off + index*sampleBytes
		return math.Float32frombits(binary.LittleEndian.Uint32(data[pos:]))
	}
	wantTimes := []float64{
		0,
		16.0 / clockHz,
		36.0 / clockHz,
	}
	for i, want := range wantTimes {
		if got := float64(readTime(i)); math.Abs(got-want) > 1e-5 {
			t.Fatalf("time[%d]=%g want %g", i, got, want)
		}
	}
	thirdIaOff := off + 2*sampleBytes + 4
	if got := math.Float32frombits(binary.LittleEndian.Uint32(data[thirdIaOff:])); got != 11 {
		t.Fatalf("third Ia=%g want 11", got)
	}
	pwmOff := off + int(count)*sampleBytes
	if got := binary.LittleEndian.Uint32(data[pwmOff:]); got != 1 {
		t.Fatalf("pwm count=%d", got)
	}
	pwmTime := math.Float32frombits(binary.LittleEndian.Uint32(data[pwmOff+4:]))
	if math.Abs(float64(pwmTime)-16.0/clockHz) > 1e-12 {
		t.Fatalf("pwm time=%g", pwmTime)
	}
	if data[pwmOff+8] != 1 || data[pwmOff+9] != 2 || data[pwmOff+10] != 3 {
		t.Fatal("bad PWM levels")
	}
	if copied, err := r.CopyLatest(filepath.Join(dir, "again.hilbin"), nil); err != nil || copied {
		t.Fatalf("capture reused: copied=%v err=%v", copied, err)
	}
}

func TestCopyLatestMergesExtraMetadata(t *testing.T) {
	dir := t.TempDir()
	r := New(dir)
	defer r.Close()
	if _, err := r.Start("test"); err != nil {
		t.Fatal(err)
	}
	r.Submit([]frame.Sample{{TCycles: 10, Epoch: 1, Ia: 1}})
	if err := r.Stop(); err != nil {
		t.Fatal(err)
	}

	extra := map[string]any{
		"name":     "batch_01_scenario1",
		"batch":    map[string]any{"name": "mybatch", "index": float64(1), "count": float64(2)},
		"scenario": map[string]any{"name": "scenario1"},
		// these must be ignored (recorder owns them)
		"sample_count": float64(999),
		"raw":          false,
		"clock_hz":     float64(1),
	}
	dst := filepath.Join(dir, "merged.hilbin")
	copied, err := r.CopyLatest(dst, extra)
	if err != nil {
		t.Fatal(err)
	}
	if !copied {
		t.Fatal("expected copy")
	}

	data, err := os.ReadFile(dst)
	if err != nil {
		t.Fatal(err)
	}
	jsonSize := int(binary.LittleEndian.Uint32(data[8:12]))
	var meta map[string]any
	if err := json.Unmarshal(data[12:12+jsonSize], &meta); err != nil {
		t.Fatal(err)
	}

	// batch and scenario must be merged in
	batch, ok := meta["batch"].(map[string]any)
	if !ok {
		t.Fatalf("missing batch in meta: %#v", meta)
	}
	if batch["name"] != "mybatch" {
		t.Fatalf("batch.name=%v want mybatch", batch["name"])
	}
	sc, ok := meta["scenario"].(map[string]any)
	if !ok {
		t.Fatalf("missing scenario in meta: %#v", meta)
	}
	if sc["name"] != "scenario1" {
		t.Fatalf("scenario.name=%v want scenario1", sc["name"])
	}

	// recorder-owned fields must be preserved
	if raw, _ := meta["raw"].(bool); !raw {
		t.Fatalf("raw must stay true, got %v", meta["raw"])
	}
	if ch, _ := meta["clock_hz"].(float64); ch != clockHz {
		t.Fatalf("clock_hz=%v want %v", meta["clock_hz"], clockHz)
	}
	if sc, _ := meta["sample_count"].(float64); sc == 999 {
		t.Fatal("sample_count must not be overwritten by extra")
	}

	// binary body must still be valid (sample count matches)
	off := (12 + jsonSize + 7) &^ 7
	count := binary.LittleEndian.Uint32(data[off:])
	if count == 0 {
		t.Fatal("no samples in merged file")
	}
}

func TestRecorderSortsPWMEventsByTimestamp(t *testing.T) {
	dir := t.TempDir()
	r := New(dir)
	defer r.Close()
	if _, err := r.Start("sort_test"); err != nil {
		t.Fatal(err)
	}
	// Establish epoch via one FPGA sample
	r.Submit([]frame.Sample{{TCycles: 10, Epoch: 1, Ia: 1}})
	// Submit PWM events out of order (simulates UDP packet reordering):
	// second batch arrives first with a later timestamp, then first batch catches up.
	r.SubmitPWM(clockHz, []pwmrecv.Event{{TCycles: 200, Epoch: 1, A: 1, B: 1, C: 1}})
	r.SubmitPWM(clockHz, []pwmrecv.Event{{TCycles: 100, Epoch: 1, A: 2, B: 2, C: 2}})
	r.SubmitPWM(clockHz, []pwmrecv.Event{{TCycles: 300, Epoch: 1, A: 3, B: 3, C: 3}})
	if err := r.Stop(); err != nil {
		t.Fatal(err)
	}
	dst := filepath.Join(dir, "sorted.hilbin")
	if copied, err := r.CopyLatest(dst, nil); err != nil || !copied {
		t.Fatalf("CopyLatest: copied=%v err=%v", copied, err)
	}
	data, err := os.ReadFile(dst)
	if err != nil {
		t.Fatal(err)
	}

	// Skip header and FPGA samples to reach PWM section
	metaLen := int(binary.LittleEndian.Uint32(data[8:12]))
	off := (12 + metaLen + 7) &^ 7
	fpgaCount := binary.LittleEndian.Uint32(data[off:])
	off += 4 + int(fpgaCount)*sampleBytes

	pwmCount := binary.LittleEndian.Uint32(data[off:])
	if pwmCount != 3 {
		t.Fatalf("pwm count=%d want 3", pwmCount)
	}
	off += 4

	// Each PWM record: 4 bytes f32 time + 4 bytes (a,b,c,pad)
	const pwmRecBytes = 8
	readPWM := func(i int) (float32, uint8, uint8, uint8) {
		base := off + i*pwmRecBytes
		ts := math.Float32frombits(binary.LittleEndian.Uint32(data[base:]))
		return ts, data[base+4], data[base+5], data[base+6]
	}

	t0, a0, _, _ := readPWM(0)
	t1, a1, _, _ := readPWM(1)
	t2, a2, _, _ := readPWM(2)

	// After sort: order by TCycles → 100 (A=2), 200 (A=1), 300 (A=3)
	if !(t0 < t1 && t1 < t2) {
		t.Fatalf("PWM events not sorted by time: %v %v %v", t0, t1, t2)
	}
	if a0 != 2 {
		t.Fatalf("first event (TCycles=100) should have A=2, got %d", a0)
	}
	if a1 != 1 {
		t.Fatalf("second event (TCycles=200) should have A=1, got %d", a1)
	}
	if a2 != 3 {
		t.Fatalf("third event (TCycles=300) should have A=3, got %d", a2)
	}
}
