"""Fourier traffic profiles used by both fitted and configurable demand models."""

import numpy as np

T_DAY = 24 * 60 * 60  # seconds per day

def _fourier_design_matrix(
    t_seconds: np.ndarray,
    K: int,
    period_seconds: float = T_DAY,
) -> np.ndarray:
    """Build Fourier basis: [1, sin(2πkt/T), cos(2πkt/T)] for k=1..K."""
    t = t_seconds.astype(float)
    cols = [np.ones_like(t)]
    for k in range(1, K + 1):
        w = 2.0 * np.pi * k / period_seconds
        cols.append(np.sin(w * t))
        cols.append(np.cos(w * t))
    return np.column_stack(cols)

def fit_predict(
    y: np.ndarray,
    t_seconds: np.ndarray,
    K: int = 6,
    eps: float = 1e-6,
    period_seconds: float = T_DAY,
) -> np.ndarray:
    """
    Fit log-rate Fourier regression: log(y + eps) ~ Fourier(t)
    Predict y_hat = exp(X beta) - eps
    """
    y = np.asarray(y, dtype=float)
    t_seconds = np.asarray(t_seconds, dtype=float)

    if period_seconds <= 0:
        raise ValueError("period_seconds must be positive")
    X = _fourier_design_matrix(t_seconds, K=K, period_seconds=period_seconds)
    z = np.log(np.maximum(y, 0.0) + eps)

    # Least squares
    beta, *_ = np.linalg.lstsq(X, z, rcond=None)
    zhat = X @ beta
    yhat = np.exp(zhat) - eps
    return np.clip(yhat, 0.0, None)


def configurable_profile(
    t_seconds: np.ndarray,
    *,
    period_seconds: float,
    peak_count: int = 2,
    peak_width_seconds: float = 5400.0,
    harmonics: int = 6,
    peak_heights: list[float] | tuple[float, ...] | np.ndarray | None = None,
) -> np.ndarray:
    """Return a Fourier approximation of evenly spaced Gaussian-shaped peaks.

    The Gaussian peaks are an intuitive editing surface; ``harmonics`` controls
    how closely the periodic Fourier series can reproduce them.
    """
    if period_seconds <= 0:
        raise ValueError("period_seconds must be positive")
    peak_count = min(max(int(peak_count), 1), 16)
    harmonics = min(max(int(harmonics), 1), 16)
    width = min(max(float(peak_width_seconds), 1.0), period_seconds)
    heights = list(peak_heights) if peak_heights is not None else []
    heights = [min(max(float(value), 0.0), 3.0) for value in heights[:peak_count]]
    heights.extend([1.0] * (peak_count - len(heights)))
    reference_times = np.linspace(0.0, period_seconds, 512, endpoint=False)
    centers = [period_seconds * (index + 0.5) / peak_count for index in range(peak_count)]
    target = np.full_like(reference_times, 0.05)
    for center, height in zip(centers, heights, strict=True):
        target += height * np.exp(-0.5 * ((reference_times - center) / width) ** 2)

    design = _fourier_design_matrix(reference_times, harmonics, period_seconds)
    coefficients, *_ = np.linalg.lstsq(design, np.log(target), rcond=None)
    prediction_design = _fourier_design_matrix(
        np.asarray(t_seconds, dtype=float), harmonics, period_seconds
    )
    return np.exp(prediction_design @ coefficients)


def configurable_departure_times(
    total: int,
    begin: float,
    end: float,
    *,
    peak_count: int = 2,
    peak_width_hours: float = 1.5,
    harmonics: int = 6,
    peak_heights: list[float] | tuple[float, ...] | np.ndarray | None = None,
) -> list[float]:
    """Deterministically sample exact departure counts from a Fourier profile."""
    if total <= 0:
        return []
    duration = float(end) - float(begin)
    if duration <= 0:
        raise ValueError("simulation end must be greater than begin")

    grid = np.linspace(0.0, duration, 2049)
    density = configurable_profile(
        grid,
        period_seconds=duration,
        peak_count=peak_count,
        peak_width_seconds=float(peak_width_hours) * 3600.0,
        harmonics=harmonics,
        peak_heights=peak_heights,
    )
    increments = (density[:-1] + density[1:]) * 0.5 * np.diff(grid)
    cumulative = np.concatenate(([0.0], np.cumsum(increments)))
    mass = float(cumulative[-1])
    if not np.isfinite(mass) or mass <= 0:
        raise ValueError("Fourier traffic profile has no usable probability mass")
    cumulative /= mass
    quantiles = (np.arange(total, dtype=float) + 0.5) / total
    return (float(begin) + np.interp(quantiles, cumulative, grid)).tolist()
