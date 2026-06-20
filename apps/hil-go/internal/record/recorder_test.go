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
	copied, err := r.CopyLatest(dst)
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
	if math.Abs(float64(pwmTime)-5.0/clockHz) > 1e-12 {
		t.Fatalf("pwm time=%g", pwmTime)
	}
	if data[pwmOff+8] != 1 || data[pwmOff+9] != 2 || data[pwmOff+10] != 3 {
		t.Fatal("bad PWM levels")
	}
	if copied, err := r.CopyLatest(filepath.Join(dir, "again.hilbin")); err != nil || copied {
		t.Fatalf("capture reused: copied=%v err=%v", copied, err)
	}
}
