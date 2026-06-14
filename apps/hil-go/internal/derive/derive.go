// Package derive turns solver-native alpha-beta telemetry samples into the
// full phase + torque channel set used by the display. All derivations are
// exact functions of one sample, so they can be applied at full rate before
// any decimation (the key fix: never reconstruct nonlinear channels from
// per-channel alpha-beta extrema).
package derive

import "hil.local/daemon/internal/frame"

const sqrt3over2 = 0.8660254037844386

// Motor holds the parameters needed for electromagnetic torque.
type Motor struct {
	Npp     float64
	Lm      float64
	LrTotal float64 // Lr_leak + Lm
}

// DefaultMotor matches the firmware default motor model.
var DefaultMotor = Motor{Npp: 2, Lm: 0.1099442, LrTotal: 0.1099442 + 0.0063264}

// Derived is the full channel set for one sample. Speed stays in rad/s.
type Derived struct {
	Ia, Ib, Ic          float64
	FluxA, FluxB, FluxC float64
	Speed               float64
	Te                  float64
}

// Compute applies inverse Clarke (amplitude-invariant) and the torque cross
// product. s.Ia/s.Ib/s.FluxA/s.FluxB carry alpha-beta values.
func (m Motor) Compute(s frame.Sample) Derived {
	ia, ib := float64(s.Ia), float64(s.Ib)
	fa, fb := float64(s.FluxA), float64(s.FluxB)
	return Derived{
		Ia:    ia,
		Ib:    -ia/2 + sqrt3over2*ib,
		Ic:    -ia/2 - sqrt3over2*ib,
		FluxA: fa,
		FluxB: -fa/2 + sqrt3over2*fb,
		FluxC: -fa/2 - sqrt3over2*fb,
		Speed: float64(s.Speed),
		Te:    1.5 * m.Npp * (m.Lm / m.LrTotal) * (fa*ib - fb*ia),
	}
}

// NumChannels is the count of derived display channels.
const NumChannels = 8

// Channels is the canonical, index-stable channel order used by the overview
// tier and the query API.
var Channels = [NumChannels]string{
	"Ia", "Ib", "Ic", "FluxA", "FluxB", "FluxC", "Speed", "Te",
}

// Values returns the channel values in Channels order.
func (d Derived) Values() [NumChannels]float64 {
	return [NumChannels]float64{
		d.Ia, d.Ib, d.Ic, d.FluxA, d.FluxB, d.FluxC, d.Speed, d.Te,
	}
}

// MotorFromParams builds a Motor from optional live params, defaulting any
// missing field to the firmware default. npp/lm are direct; lrLeak is added to
// lm to form LrTotal.
func MotorFromParams(npp, lm, lrLeak *float32) Motor {
	m := DefaultMotor
	if npp != nil {
		m.Npp = float64(*npp)
	}
	lmv := m.Lm
	if lm != nil {
		lmv = float64(*lm)
	}
	leak := 0.0063264
	if lrLeak != nil {
		leak = float64(*lrLeak)
	}
	m.Lm = lmv
	m.LrTotal = lmv + leak
	return m
}
