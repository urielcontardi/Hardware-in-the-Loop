import numpy as np

import publication_figures as pub


def test_moving_rms_constant_signal():
    t = np.linspace(0.0, 0.2, 2001)
    y = np.full_like(t, 3.0)
    rms = pub.moving_rms(t, y)
    assert np.allclose(rms[200:-200], 3.0, atol=1e-12)


def test_clip_uses_physical_window():
    data = {"t": np.linspace(0.0, 1.0, 11), "x": np.arange(11)}
    clipped = pub._clip(data, 0.2, 0.5)
    assert clipped["t"].tolist() == [0.2, 0.30000000000000004, 0.4, 0.5]
    assert clipped["x"].tolist() == [2, 3, 4, 5]
