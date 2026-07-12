package viewquery

import (
	"math"
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/derive"
	"hil.local/daemon/internal/frame"
	"hil.local/daemon/internal/pyramid"
	"hil.local/daemon/internal/sessionstore"
)

func newViewTestStore(t *testing.T, count int) (*sessionstore.Store, *pyramid.Pyramid) {
	t.Helper()
	st, err := sessionstore.Open(filepath.Join(t.TempDir(), "view.bin"), 32)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = st.Close() })
	pyr := pyramid.New(10000)
	for i := 0; i < count; i++ {
		ts := float64(i) / 10000
		sm := frame.Sample{Ia: float32(math.Sin(2 * math.Pi * 50 * ts)), Ib: float32(math.Cos(2 * math.Pi * 50 * ts))}
		st.Append(ts, sm)
		pyr.Push(ts, derive.DefaultMotor.Compute(sm).Values())
	}
	return st, pyr
}

func TestBuildViewUsesRawAtFineZoom(t *testing.T) {
	st, pyr := newViewTestStore(t, 1000)
	view, err := BuildView(pyr, st, derive.DefaultMotor, 0.01, 0.02, 1000)
	if err != nil {
		t.Fatalf("BuildView: %v", err)
	}
	if view.Source != "raw" {
		t.Fatalf("source=%q want raw", view.Source)
	}
	if view.Tier != 255 {
		t.Fatalf("tier=%d want 255", view.Tier)
	}
	if n := len(view.Buckets); n != 101 {
		t.Fatalf("columns=%d want 101 full-rate points", n)
	}
}

func TestBuildViewUsesTierAtWideZoomAndNeverReturnsEmptyTransition(t *testing.T) {
	st, pyr := newViewTestStore(t, 20000)
	for _, width := range []int{500, 1000, 2000, 4000} {
		view, err := BuildView(pyr, st, derive.DefaultMotor, 0, 1.9, width)
		if err != nil {
			t.Fatalf("width=%d BuildView: %v", width, err)
		}
		if len(view.Buckets) == 0 {
			t.Fatalf("width=%d returned empty view", width)
		}
	}
}

func TestBuildViewRejectsInvalidViewport(t *testing.T) {
	st, pyr := newViewTestStore(t, 1)
	cases := []struct {
		from, to float64
		width    int
	}{
		{2, 1, 800},
		{0, 1, 0},
		{0, 1, 20001},
	}
	for _, c := range cases {
		if _, err := BuildView(pyr, st, derive.DefaultMotor, c.from, c.to, c.width); err == nil {
			t.Fatalf("from=%v to=%v width=%d: want error", c.from, c.to, c.width)
		}
	}
}

func TestBuildViewEncodeRoundTripsThroughPyramidWireFormat(t *testing.T) {
	st, pyr := newViewTestStore(t, 1000)
	view, err := BuildView(pyr, st, derive.DefaultMotor, 0.01, 0.02, 1000)
	if err != nil {
		t.Fatalf("BuildView: %v", err)
	}
	encoded := Encode(view)
	if len(encoded) < 13 {
		t.Fatalf("short encoded view: %d bytes", len(encoded))
	}
	if got := encoded[0]; got != 255 {
		t.Fatalf("tier byte=%d want 255", got)
	}
}

func TestBuildTiersMetaReflectsStoreSpanAndPyramidTiers(t *testing.T) {
	st, pyr := newViewTestStore(t, 5000)
	meta := BuildTiersMeta(pyr, st)
	if meta.SampleCount != 5000 {
		t.Fatalf("sampleCount=%d want 5000", meta.SampleCount)
	}
	if meta.Tiers[0].Tier != 0 || len(meta.Tiers) != pyr.NumTiers() {
		t.Fatalf("tiers=%+v want %d entries starting at 0", meta.Tiers, pyr.NumTiers())
	}
	wantTLast := float64(4999) / 10000
	if math.Abs(meta.TLast-wantTLast) > 1e-9 {
		t.Fatalf("tLast=%v want %v", meta.TLast, wantTLast)
	}
}

func TestBuildTiersMetaWithNilStoreFallsBackToPyramid(t *testing.T) {
	_, pyr := newViewTestStore(t, 5000)
	meta := BuildTiersMeta(pyr, nil)
	if meta.SampleCount != 0 {
		t.Fatalf("sampleCount=%d want 0 with nil store", meta.SampleCount)
	}
	if meta.TLast == 0 {
		t.Fatalf("tLast=0, want fallback from finest tier's last bucket")
	}
}
