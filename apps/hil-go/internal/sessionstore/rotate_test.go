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
