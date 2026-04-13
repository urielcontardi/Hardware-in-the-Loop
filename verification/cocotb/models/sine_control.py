"""Pure-sine 3-phase voltage stimulus — fixed frequency, fixed amplitude, no ramp.

Generates balanced 3-phase sinusoidal voltages at a fixed frequency from t=0.
Use this instead of VFControl when you want to apply an ideal sinusoidal
excitation directly (no PWM, no V/F ramp transient).

Usage:
    from models.sine_control import SineControl

    sine = SineControl(frequency_hz=60.0, v_peak=620.0, ts=100e-9)
    for step in range(N):
        va, vb, vc = sine.step()
        ...
"""

import math


class SineControl:
    """Fixed-frequency, fixed-amplitude 3-phase sine generator.

    Attributes:
        frequency_hz: Output frequency [Hz]
        v_peak:       Phase voltage peak amplitude [V]
        ts:           Sampling period [s]
        tload:        Mechanical load torque [N·m] (constant)
        f_ref:        Alias for frequency_hz (CSV compatibility with VFControl)
        theta:        Current phase angle [rad]
    """

    def __init__(
        self,
        frequency_hz: float = 60.0,
        v_peak: float = 620.0,
        ts: float = 100.0e-9,
        initial_theta: float = math.pi / 4,
        tload: float = 0.0,
    ) -> None:
        self.frequency_hz = frequency_hz
        self.v_peak = v_peak
        self.ts = ts
        self.theta = initial_theta
        self.tload = tload
        self.f_ref = frequency_hz  # constant — compatible with VFControl CSV field

    def step(self) -> tuple[float, float, float]:
        """Return (va, vb, vc) and advance the phase angle by one Ts."""
        va = self.v_peak * math.cos(self.theta)
        vb = self.v_peak * math.cos(self.theta - 2.0 * math.pi / 3.0)
        vc = self.v_peak * math.cos(self.theta + 2.0 * math.pi / 3.0)
        self.theta += 2.0 * math.pi * self.frequency_hz * self.ts
        return va, vb, vc
