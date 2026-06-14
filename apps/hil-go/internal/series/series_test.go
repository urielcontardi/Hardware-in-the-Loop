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
	ts, ss := buildSine(100000, 58, 7, 0.001)
	cols := ReduceWindow(derive.DefaultMotor, ts, ss, 600)
	if len(cols) != len(ts) {
		t.Errorf("narrow window should return raw: got %d want %d", len(cols), len(ts))
	}
	if cols[0].Min[0] != cols[0].Max[0] {
		t.Errorf("raw column min should equal max")
	}
}
