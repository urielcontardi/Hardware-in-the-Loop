package pyramid

import (
	"encoding/binary"
	"math"
	"testing"

	"hil.local/daemon/internal/derive"
)

func TestEncodeTileRoundtripHeader(t *testing.T) {
	bs := []Bucket{
		{TStart: 0.0, Min: ch(-3), Max: ch(5), Mean: ch(1), Count: 3},
		{TStart: 0.001, Min: ch(2), Max: ch(2), Mean: ch(2), Count: 1},
	}
	b := EncodeTile(0, 0.001, 0.0, bs)

	if got := b[0]; got != 0 {
		t.Errorf("tier byte = %d, want 0", got)
	}
	if got := binary.LittleEndian.Uint16(b[1:3]); got != 2 {
		t.Errorf("count = %d, want 2", got)
	}
	if got := b[3]; got != derive.NumChannels {
		t.Errorf("nch = %d, want %d", got, derive.NumChannels)
	}
	if got := math.Float32frombits(binary.LittleEndian.Uint32(b[4:8])); got != 0.001 {
		t.Errorf("bucketSec = %v, want 0.001", got)
	}
	// First bucket: tStart at offset 13, then channel 0 min at 17.
	const hdr = 13
	if got := math.Float32frombits(binary.LittleEndian.Uint32(b[hdr : hdr+4])); got != 0 {
		t.Errorf("bucket0 tStart = %v, want 0", got)
	}
	min0 := math.Float32frombits(binary.LittleEndian.Uint32(b[hdr+4 : hdr+8]))
	max0 := math.Float32frombits(binary.LittleEndian.Uint32(b[hdr+8 : hdr+12]))
	if min0 != -3 || max0 != 5 {
		t.Errorf("bucket0 ch0 min/max = %v/%v, want -3/5", min0, max0)
	}
}

func TestEncodeTileLength(t *testing.T) {
	bs := []Bucket{{TStart: 0}}
	b := EncodeTile(1, 0.02, 0, bs)
	want := 13 + 1*(4+derive.NumChannels*12)
	if len(b) != want {
		t.Fatalf("len = %d, want %d", len(b), want)
	}
}
