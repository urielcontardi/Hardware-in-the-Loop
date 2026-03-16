"""Open-loop V/F (Volt/Hertz) speed control.

Generates balanced 3-phase sinusoidal voltages while ramping frequency
from 0 to f_nominal at a constant rate, keeping V/f constant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class VFControl:
    """Scalar V/F controller with linear frequency ramp.

    Parameters
    ----------
    f_nominal : float
        Nominal electrical frequency [Hz].
    v_peak_nominal : float
        Phase-voltage peak at nominal frequency [V].
    acc_ramp_hz_s : float
        Frequency ramp rate [Hz/s].  e.g. 30 → reaches 60 Hz in 2 s.
    ts : float
        Discretisation step [s].
    tload : float
        Constant load torque [N·m] (can be changed between steps).
    """

    f_nominal: float
    v_peak_nominal: float
    acc_ramp_hz_s: float
    ts: float
    tload: float = 0.0
    initial_theta: float = 0.0  # Starting phase angle [rad]; use e.g. math.pi/4 for balanced excitation

    # Internal state — not set by caller
    _theta: float = field(default=0.0, init=False, repr=False)
    _f_ref: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._theta = self.initial_theta

    @property
    def vf_ratio(self) -> float:
        """V/Hz ratio [V/Hz]."""
        return self.v_peak_nominal / self.f_nominal

    @property
    def f_ref(self) -> float:
        return self._f_ref

    @property
    def v_ref(self) -> float:
        """Current voltage reference amplitude [V]."""
        return self.vf_ratio * self._f_ref

    @property
    def theta(self) -> float:
        return self._theta

    def step(self) -> tuple[float, float, float]:
        """Advance one Ts and return (va, vb, vc) in Volts."""
        # Ramp frequency up to nominal
        self._f_ref = min(self._f_ref + self.acc_ramp_hz_s * self.ts, self.f_nominal)

        v_amp = self.vf_ratio * self._f_ref

        # Advance angle
        self._theta += 2.0 * math.pi * self._f_ref * self.ts

        va = v_amp * math.cos(self._theta)
        vb = v_amp * math.cos(self._theta - 2.0 * math.pi / 3.0)
        vc = v_amp * math.cos(self._theta + 2.0 * math.pi / 3.0)

        return va, vb, vc
