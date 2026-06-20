package pyramid

import (
	"testing"

	"hil.local/daemon/internal/derive"
)

func ch(v float64) [derive.NumChannels]float64 {
	var a [derive.NumChannels]float64
	a[0] = v
	return a
}

func TestPushFoldsMinMaxMeanPerTier(t *testing.T) {
	p := New(10000) // 10 kHz
	// Three samples inside the same T1 (1 ms) bucket: t in [0, 0.001).
	p.Push(0.0000, ch(1))
	p.Push(0.0003, ch(5))
	p.Push(0.0006, ch(-3))
	// One sample in the next T1 bucket.
	p.Push(0.0012, ch(2))

	t1 := p.Tier(0) // T1 = 1 ms
	got := t1.Buckets()
	if len(got) != 2 {
		t.Fatalf("T1 buckets = %d, want 2", len(got))
	}
	if got[0].Min[0] != -3 || got[0].Max[0] != 5 {
		t.Errorf("bucket0 min/max = %v/%v, want -3/5", got[0].Min[0], got[0].Max[0])
	}
	if got[0].Count != 3 || got[0].Mean[0] != 1 { // (1+5-3)/3 = 1
		t.Errorf("bucket0 count/mean = %d/%v, want 3/1", got[0].Count, got[0].Mean[0])
	}
	if got[1].Min[0] != 2 || got[1].Max[0] != 2 {
		t.Errorf("bucket1 min/max = %v/%v, want 2/2", got[1].Min[0], got[1].Max[0])
	}
}

func TestResetClearsAllTiers(t *testing.T) {
	p := New(10000)
	p.Push(0.0, ch(1))
	p.Reset()
	if len(p.Tier(0).Buckets()) != 0 {
		t.Fatalf("after Reset T1 not empty")
	}
}
