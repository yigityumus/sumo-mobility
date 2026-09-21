"""Spline-based departure-time model."""

import numpy as np

try:
    from scipy.interpolate import UnivariateSpline
except Exception as e:
    UnivariateSpline = None

def fit_predict(y: np.ndarray, t_seconds: np.ndarray, smooth_factor: float = 1.0) -> np.ndarray:
    """
    Fit a smoothing spline to (t, y).
    smooth_factor controls smoothness; larger -> smoother.

    If scipy is missing, raises an error.
    """
    if UnivariateSpline is None:
        raise RuntimeError("scipy is required for spline. Install: pip install scipy")

    y = np.asarray(y, dtype=float)
    t = np.asarray(t_seconds, dtype=float)

    # Normalize t to [0, 1] for stability
    x = (t - t.min()) / (t.max() - t.min() + 1e-12)

    # s parameter: roughly smooth_factor * N * variance
    # This is heuristic; you can tune in the UI.
    s = float(smooth_factor) * len(x) * np.var(y)

    spl = UnivariateSpline(x, y, s=s, k=3)
    yhat = spl(x)
    return np.clip(yhat, 0.0, None)
