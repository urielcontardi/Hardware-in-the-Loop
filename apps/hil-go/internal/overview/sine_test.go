package overview

import (
	"math"
	"testing"

	"hil.local/daemon/internal/derive"
)

func TestSineAmplitudePreserved(t *testing.T) {
	ov := New(0.050)
	const fs, fe, amp = 100000.0, 58.0, 7.0
	n := int(0.5 * fs)
	for i := 0; i < n; i++ {
		tt := float64(i) / fs
		val := amp * math.Sin(2*math.Pi*fe*tt)
		ov.Push(tt, [derive.NumChannels]float64{val})
	}
	for _, c := range ov.Query(0, 0.5) {
		if c.Max[0] < amp*0.98 || c.Min[0] > -amp*0.98 {
			t.Errorf("bucket @%.3fs lost amplitude: min=%.3f max=%.3f want ~±%.1f",
				c.TStart, c.Min[0], c.Max[0], amp)
		}
	}
}
