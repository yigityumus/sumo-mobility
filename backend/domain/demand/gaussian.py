"""Gaussian departure-time model."""
import numpy as np

try:
    from scipy.optimize import curve_fit
except Exception:
    curve_fit = None

def _gauss(t, A, mu, sig):
    return A * np.exp(-0.5 * ((t - mu) / sig) ** 2)

def _model_factory(n_peaks: int):
    # returns a callable f(t, *params) with params = [c, A1, mu1, sig1, A2, mu2, sig2, ...]
    def f(t, *params):
        c = params[0]
        y = c
        for i in range(n_peaks):
            A = params[1 + 3*i]
            mu = params[1 + 3*i + 1]
            sig = params[1 + 3*i + 2]
            y = y + _gauss(t, A, mu, sig)
        return y
    return f

def fit_predict(y: np.ndarray, t_seconds: np.ndarray, n_peaks: int = 3):
    """
    Fit baseline + n Gaussian peaks to (t, y).
    """
    if curve_fit is None:
        raise RuntimeError("scipy is required for gaussian peaks. Install: pip install scipy")

    y = np.asarray(y, dtype=float)
    t = np.asarray(t_seconds, dtype=float)

    n_peaks = int(n_peaks)
    if n_peaks < 1:
        raise ValueError("n_peaks must be >= 1")

    ymax = float(np.max(y))
    c0 = float(np.quantile(y, 0.1))

    # Initial peak centers spread over the day (heuristic)
    # Example: for 3 peaks -> ~8:30, 12:30, 17:30-ish
    centers = np.linspace(8.5*3600, 17.5*3600, n_peaks)

    # Initial widths ~ 1 hour
    sig0 = 1.0 * 3600.0

    # Initial amplitudes
    A0 = max(0.0, ymax - c0)
    amps = np.linspace(0.7, 0.4, n_peaks) * A0  # descending-ish

    p0 = [c0]
    lower = [0.0]
    upper = [max(1.0, ymax * 2)]

    for i in range(n_peaks):
        p0 += [float(max(0.0, amps[i])), float(centers[i]), float(sig0)]
        lower += [0.0, 0.0, 10*60]          # A>=0, mu>=0, sigma>=10min
        upper += [ymax*5, 24*3600, 6*3600]  # reasonable upper bounds

    f = _model_factory(n_peaks)
    popt, _ = curve_fit(f, t, y, p0=p0, bounds=(lower, upper), maxfev=50000)
    yhat = f(t, *popt)
    return np.clip(yhat, 0.0, None)
