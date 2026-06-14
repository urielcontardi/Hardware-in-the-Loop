package derive

import (
	"math"
	"testing"

	"hil.local/daemon/internal/frame"
)

func approx(t *testing.T, name string, got, want float64) {
	t.Helper()
	if math.Abs(got-want) > 1e-4 {
		t.Errorf("%s = %.6f, want %.6f", name, got, want)
	}
}

func TestComputeBalanced(t *testing.T) {
	d := DefaultMotor.Compute(frame.Sample{Ia: 10, Ib: 0, FluxA: 1, FluxB: 0, Speed: 3})
	approx(t, "Ia", d.Ia, 10)
	approx(t, "Ib", d.Ib, -5)
	approx(t, "Ic", d.Ic, -5)
	approx(t, "FluxA", d.FluxA, 1)
	approx(t, "FluxB", d.FluxB, -0.5)
	approx(t, "FluxC", d.FluxC, -0.5)
	approx(t, "Speed", d.Speed, 3)
	approx(t, "Te", d.Te, 0)
}

func TestComputeTorqueSign(t *testing.T) {
	d := DefaultMotor.Compute(frame.Sample{Ia: 1, Ib: 0, FluxA: 0, FluxB: 1})
	k := 1.5 * 2 * (DefaultMotor.Lm / DefaultMotor.LrTotal)
	approx(t, "Te", d.Te, -k)
}
