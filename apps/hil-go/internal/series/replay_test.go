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

// readHilbinRecords decodes the record `.hilbin` layout. Skips if absent.
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
