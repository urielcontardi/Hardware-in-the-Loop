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

	got := p.TierBuckets(0) // T1 = 1 ms
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
	if len(p.TierBuckets(0)) != 0 {
		t.Fatalf("after Reset T1 not empty")
	}
}

func TestPushDropsOutOfOrder(t *testing.T) {
	p := New(10000) // 10 kHz
	p.Push(0.0000, ch(1))
	p.Push(0.0010, ch(2))
	// Out-of-order / stale sample: should be dropped, not folded or appended.
	p.Push(0.0000, ch(9))

	got := p.TierBuckets(0) // T1 = 1 ms
	if len(got) != 2 {
		t.Fatalf("T1 buckets = %d, want 2", len(got))
	}
	if got[0].Max[0] != 1 {
		t.Errorf("bucket0 Max[0] = %v, want 1 (unchanged by dropped sample)", got[0].Max[0])
	}
}

func TestSelectTierByZoom(t *testing.T) {
	p := New(10000)
	// bucketSec tiers: 0.001, 0.020, 0.500, 10.0
	if got := p.SelectTier(0.0001); got != -1 { // muito zoom: usa raw
		t.Errorf("SelectTier(0.0001)=%d, want -1", got)
	}
	if got := p.SelectTier(0.002); got != 0 { // 1ms cabe
		t.Errorf("SelectTier(0.002)=%d, want 0", got)
	}
	if got := p.SelectTier(0.6); got != 2 { // 500ms cabe, 10s nao
		t.Errorf("SelectTier(0.6)=%d, want 2", got)
	}
	if got := p.SelectTier(100); got != 3 { // coarsest
		t.Errorf("SelectTier(100)=%d, want 3", got)
	}
}

func TestTileWindowingAndSealed(t *testing.T) {
	p := New(10000)
	// T1 (1ms). Tile 0 covers buckets [0,1024) -> t in [0, 1.024).
	// Push samples up to t=1.5s so tile 0 is fully in the past (sealed).
	for i := 0; i < 1600; i++ {
		p.Push(float64(i)*0.001, ch(float64(i)))
	}
	buckets, sealed := p.Tile(0, 0)
	if !sealed {
		t.Errorf("tile 0 should be sealed once data passed its end")
	}
	if len(buckets) != 1024 {
		t.Fatalf("tile 0 buckets = %d, want 1024", len(buckets))
	}
	if buckets[0].TStart != 0 {
		t.Errorf("tile0 first TStart = %v, want 0", buckets[0].TStart)
	}
	// The trailing tile (index 1) is not sealed yet.
	_, sealed1 := p.Tile(0, 1)
	if sealed1 {
		t.Errorf("trailing tile 1 should not be sealed")
	}
}
