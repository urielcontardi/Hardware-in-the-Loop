package derive

import "testing"

func TestChannelOrderStable(t *testing.T) {
	want := []string{"Ia", "Ib", "Ic", "FluxA", "FluxB", "FluxC", "Speed", "Te"}
	if len(Channels) != len(want) {
		t.Fatalf("len(Channels)=%d want %d", len(Channels), len(want))
	}
	for i, n := range want {
		if Channels[i] != n {
			t.Errorf("Channels[%d]=%q want %q", i, Channels[i], n)
		}
	}
}

func TestValuesMatchChannelOrder(t *testing.T) {
	d := Derived{Ia: 1, Ib: 2, Ic: 3, FluxA: 4, FluxB: 5, FluxC: 6, Speed: 7, Te: 8}
	v := d.Values()
	for i := range Channels {
		if v[i] != float64(i+1) {
			t.Errorf("Values()[%d]=%v want %v", i, v[i], i+1)
		}
	}
}

func TestMotorFromParamsDefaults(t *testing.T) {
	m := MotorFromParams(nil, nil, nil)
	if m != DefaultMotor {
		t.Errorf("nil params should give DefaultMotor, got %+v", m)
	}
}
