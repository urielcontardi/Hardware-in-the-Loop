package overview

import (
	"testing"

	"hil.local/daemon/internal/derive"
)

func TestBucketingAndExtrema(t *testing.T) {
	ov := New(0.050)
	ov.Push(0.000, [derive.NumChannels]float64{1, 0, 0, 0, 0, 0, 0, 0})
	ov.Push(0.010, [derive.NumChannels]float64{5, 0, 0, 0, 0, 0, 0, 0})
	ov.Push(0.020, [derive.NumChannels]float64{-3, 0, 0, 0, 0, 0, 0, 0})
	ov.Push(0.070, [derive.NumChannels]float64{2, 0, 0, 0, 0, 0, 0, 0})

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
	cols := ov.Query(0.100, 0.250)
	if len(cols) != 3 {
		t.Fatalf("got %d want 3", len(cols))
	}
	if cols[0].TStart < 0.0999 || cols[0].TStart > 0.1001 {
		t.Errorf("first bucket TStart=%v want ~0.10", cols[0].TStart)
	}
}
