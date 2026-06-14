package series

import (
	"encoding/binary"
	"math"
	"testing"

	"hil.local/daemon/internal/derive"
)

func TestEncodeRoundtripHeader(t *testing.T) {
	cols := []Column{
		{T: 1.5, Min: [derive.NumChannels]float64{1}, Max: [derive.NumChannels]float64{2}},
	}
	b := Encode(cols)
	if got := binary.LittleEndian.Uint32(b[0:4]); got != 1 {
		t.Errorf("column count = %d want 1", got)
	}
	if got := b[4]; got != derive.NumChannels {
		t.Errorf("channel count = %d want %d", got, derive.NumChannels)
	}
	tVal := math.Float32frombits(binary.LittleEndian.Uint32(b[5:9]))
	if math.Abs(float64(tVal)-1.5) > 1e-6 {
		t.Errorf("t = %v want 1.5", tVal)
	}
}
