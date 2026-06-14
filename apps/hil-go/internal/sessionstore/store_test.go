package sessionstore

import (
	"path/filepath"
	"testing"

	"hil.local/daemon/internal/frame"
)

func TestAppendThenReadWindow(t *testing.T) {
	dir := t.TempDir()
	st, err := Open(filepath.Join(dir, "sess.bin"), 4)
	if err != nil {
		t.Fatal(err)
	}
	defer st.Close()
	for i := 0; i < 20; i++ {
		st.Append(float64(i)*0.001, frame.Sample{Ia: float32(i)})
	}
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
