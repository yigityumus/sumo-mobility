#!/usr/bin/env python3
"""Generate a detailed Markdown report and dependency-free SVG figures.

The report deliberately uses a response appropriate to each parameter family:

* Fourier peak amplitudes -> detector entries in that peak's nominal time window.
* Residential pedestrian count -> total pedestrian detector entries.
* Vehicle count, entry shares, and parking parameters -> total vehicle entries.

This makes the fitted Hill equation describe the direct response being tested,
rather than fitting every parameter to an unrelated aggregate.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def duration_label(seconds: float) -> str:
    seconds = max(int(round(seconds)), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    return f"{minutes} min {seconds:02d} s"


def fmt(value: float | None, digits: int = 3) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    if value == 0:
        return "0"
    if abs(value) >= 10000 or abs(value) < 0.001:
        return f"{value:.{digits}e}"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted((value, index) for index, value in enumerate(values))
    result = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][0] == ordered[cursor][0]:
            end += 1
        rank = (cursor + end - 1) / 2 + 1
        for _, index in ordered[cursor:end]:
            result[index] = rank
        cursor = end
    return result


def pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left)
        * sum((y - right_mean) ** 2 for y in right)
    )
    return numerator / denominator if denominator > 1e-12 else None


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    return pearson(ranks(left), ranks(right))


def regress_intercept_slope(basis: Sequence[float], values: Sequence[float]) -> tuple[float, float] | None:
    if len(basis) != len(values) or not basis:
        return None
    base_mean, value_mean = statistics.fmean(basis), statistics.fmean(values)
    denominator = sum((item - base_mean) ** 2 for item in basis)
    if denominator <= 1e-14:
        return None
    slope = sum(
        (basis[index] - base_mean) * (values[index] - value_mean)
        for index in range(len(values))
    ) / denominator
    return value_mean - slope * base_mean, slope


def hill_value(x: float, y0: float, vmax: float, k_half: float, exponent: float) -> float:
    if x <= 0:
        return y0
    ratio = (x / k_half) ** exponent
    return y0 + vmax * ratio / (1 + ratio)


def fit_hill(x: Sequence[float], y: Sequence[float]) -> dict[str, Any]:
    """Fit a bounded descriptive four-parameter Hill curve by grid search."""
    if len(x) != len(y) or len(set(x)) < 4:
        return {"status": "not identifiable", "reason": "fewer than four distinct input values"}
    output_range = max(y) - min(y)
    scale = max(abs(statistics.fmean(y)), 1.0)
    monotonicity = spearman(x, y)
    if output_range <= max(1e-9, scale * 1e-6):
        return {
            "status": "not identifiable",
            "reason": "the measured response is constant",
            "spearman": monotonicity,
            "equation": f"y = {fmt(statistics.fmean(y))} (constant response)",
        }
    positive = [value for value in x if value > 0]
    if not positive:
        return {"status": "not identifiable", "reason": "the input has no positive values"}
    low = min(positive) / 10
    high = max(positive) * 10
    log_low, log_high = math.log(low), math.log(high)
    margin = max(output_range * 2, scale * 0.25, 1.0)
    permitted_low, permitted_high = min(y) - margin, max(y) + margin
    best: dict[str, Any] | None = None
    for exponent_index in range(1, 25):
        exponent = exponent_index * 0.25
        for half_index in range(121):
            k_half = math.exp(log_low + (log_high - log_low) * half_index / 120)
            basis = []
            for value in x:
                if value <= 0:
                    basis.append(0.0)
                else:
                    ratio = (value / k_half) ** exponent
                    basis.append(ratio / (1 + ratio))
            coefficients = regress_intercept_slope(basis, y)
            if coefficients is None:
                continue
            y0, vmax = coefficients
            if not (
                permitted_low <= y0 <= permitted_high
                and permitted_low <= y0 + vmax <= permitted_high
            ):
                continue
            predictions = [y0 + vmax * item for item in basis]
            sse = sum((y[index] - predictions[index]) ** 2 for index in range(len(y)))
            if best is None or sse < best["sse"]:
                best = {
                    "y0": y0,
                    "vmax": vmax,
                    "k_half": k_half,
                    "n": exponent,
                    "sse": sse,
                }
    if best is None:
        return {"status": "not identifiable", "reason": "no bounded Hill curve could be fitted"}
    total = sum((value - statistics.fmean(y)) ** 2 for value in y)
    best["r_squared"] = 1 - best["sse"] / total if total > 0 else 0.0
    best["spearman"] = monotonicity
    best["equation"] = (
        f"y = {fmt(best['y0'])} + ({fmt(best['vmax'])}) × "
        f"x^{fmt(best['n'])} / ({fmt(best['k_half'])}^{fmt(best['n'])} + x^{fmt(best['n'])})"
    )
    absolute_monotonicity = abs(monotonicity) if monotonicity is not None else 0.0
    if best["r_squared"] >= 0.8 and absolute_monotonicity >= 0.75:
        best["status"] = "good descriptive fit"
    elif best["r_squared"] >= 0.6 and absolute_monotonicity >= 0.6:
        best["status"] = "moderate descriptive fit"
    else:
        best["status"] = "poor / non-monotonic fit"
    return best


def svg_text(value: Any) -> str:
    return html.escape(str(value), quote=True)


def tick_values(low: float, high: float, count: int = 5) -> list[float]:
    if math.isclose(low, high):
        return [low]
    return [low + (high - low) * index / count for index in range(count + 1)]


def line_chart_svg(
    path: Path,
    *,
    title: str,
    subtitle: str,
    x_label: str,
    y_label: str,
    series: Sequence[tuple[str, Sequence[tuple[float, float]], str]],
    fit: dict[str, Any] | None = None,
    baseline_x: float | None = None,
) -> None:
    width, height = 820, 510
    left, right, top, bottom = 82, 30, 90, 100
    plot_w, plot_h = width - left - right, height - top - bottom
    all_points = [point for _, points, _ in series for point in points]
    if fit and fit.get("y0") is not None and all_points:
        x_low, x_high = min(x for x, _ in all_points), max(x for x, _ in all_points)
        fit_points = [
            (
                x_low + (x_high - x_low) * index / 180,
                hill_value(
                    x_low + (x_high - x_low) * index / 180,
                    fit["y0"], fit["vmax"], fit["k_half"], fit["n"],
                ),
            )
            for index in range(181)
        ]
        series = [*series, ("Hill fit", fit_points, "#d97706")]
        all_points.extend(fit_points)
    x_min, x_max = min(x for x, _ in all_points), max(x for x, _ in all_points)
    y_min, y_max = min(y for _, y in all_points), max(y for _, y in all_points)
    x_pad = (x_max - x_min) * 0.04 or 1
    y_pad = (y_max - y_min) * 0.12 or 1
    x_min, x_max = x_min - x_pad, x_max + x_pad
    y_min, y_max = min(0.0, y_min - y_pad), y_max + y_pad

    def sx(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def sy(value: float) -> float:
        return top + plot_h - (value - y_min) / (y_max - y_min) * plot_h

    subtitle_parts = subtitle.split("; R²=", 1)
    subtitle_lines = (
        [subtitle_parts[0], "R²=" + subtitle_parts[1]]
        if len(subtitle_parts) == 2 else [subtitle]
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{svg_text(title)}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{left}" y="28" font-family="Arial,sans-serif" font-size="20" font-weight="600" fill="#111827">{svg_text(title)}</text>',
    ]
    for index, line in enumerate(subtitle_lines):
        parts.append(
            f'<text x="{left}" y="{50 + index * 16}" font-family="Arial,sans-serif" '
            f'font-size="12" fill="#4b5563">{svg_text(line)}</text>'
        )
    parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#ffffff" stroke="#9ca3af"/>')
    for value in tick_values(y_min, y_max):
        y_pos = sy(value)
        parts.append(f'<line x1="{left}" y1="{y_pos:.2f}" x2="{left + plot_w}" y2="{y_pos:.2f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{left - 10}" y="{y_pos + 4:.2f}" text-anchor="end" font-family="Arial,sans-serif" font-size="11" fill="#4b5563">{svg_text(fmt(value, 1))}</text>')
    for value in tick_values(x_min + x_pad, x_max - x_pad):
        x_pos = sx(value)
        parts.append(f'<line x1="{x_pos:.2f}" y1="{top}" x2="{x_pos:.2f}" y2="{top + plot_h}" stroke="#f3f4f6"/>')
        parts.append(f'<text x="{x_pos:.2f}" y="{top + plot_h + 22}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="#4b5563">{svg_text(fmt(value, 1))}</text>')
    if baseline_x is not None and x_min <= baseline_x <= x_max:
        x_pos = sx(baseline_x)
        parts.append(f'<line x1="{x_pos:.2f}" y1="{top}" x2="{x_pos:.2f}" y2="{top + plot_h}" stroke="#6b7280" stroke-dasharray="5 4"/>')
        parts.append(f'<text x="{x_pos + 5:.2f}" y="{top + 15}" font-family="Arial,sans-serif" font-size="11" fill="#4b5563">baseline</text>')
    for series_index, (name, points, color) in enumerate(series):
        ordered = sorted(points)
        path_data = " ".join(
            ("M" if index == 0 else "L") + f" {sx(x):.2f} {sy(y):.2f}"
            for index, (x, y) in enumerate(ordered)
        )
        dash = ' stroke-dasharray="7 5"' if name == "Hill fit" else ""
        parts.append(f'<path d="{path_data}" fill="none" stroke="{color}" stroke-width="2.5"{dash}/>')
        if name != "Hill fit":
            for x, y in ordered:
                parts.append(f'<circle cx="{sx(x):.2f}" cy="{sy(y):.2f}" r="4.3" fill="{color}" stroke="#ffffff" stroke-width="1.5"><title>{svg_text(name)}: x={fmt(x)}, y={fmt(y)}</title></circle>')
        legend_x = left + series_index * 175
        parts.append(f'<line x1="{legend_x}" y1="{height - 20}" x2="{legend_x + 24}" y2="{height - 20}" stroke="{color}" stroke-width="3"{dash}/>')
        parts.append(f'<text x="{legend_x + 31}" y="{height - 16}" font-family="Arial,sans-serif" font-size="11" fill="#374151">{svg_text(name)}</text>')
    parts.extend([
        f'<text x="{left + plot_w / 2}" y="{height - 42}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#111827">{svg_text(x_label)}</text>',
        f'<text x="18" y="{top + plot_h / 2}" text-anchor="middle" transform="rotate(-90 18 {top + plot_h / 2})" font-family="Arial,sans-serif" font-size="12" fill="#111827">{svg_text(y_label)}</text>',
        '</svg>',
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def horizontal_bar_svg(path: Path, title: str, rows: Sequence[tuple[str, float]]) -> None:
    width = 900
    row_height = 27
    top, left, right, bottom = 58, 330, 40, 42
    height = top + len(rows) * row_height + bottom
    maximum = max((max(value, 0) for _, value in rows), default=1) or 1
    plot_width = width - left - right
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{svg_text(title)}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="20" y="30" font-family="Arial,sans-serif" font-size="20" font-weight="600" fill="#111827">{svg_text(title)}</text>',
        f'<line x1="{left}" y1="{top - 12}" x2="{left}" y2="{height - bottom + 5}" stroke="#9ca3af"/>',
    ]
    for index, (label, value) in enumerate(rows):
        y = top + index * row_height
        length = max(value, 0) / maximum * plot_width
        parts.append(f'<text x="{left - 10}" y="{y + 14}" text-anchor="end" font-family="Arial,sans-serif" font-size="11" fill="#374151">{svg_text(label)}</text>')
        parts.append(f'<rect x="{left}" y="{y + 3}" width="{length:.2f}" height="15" fill="#2563eb" opacity="0.82"/>')
        parts.append(f'<text x="{left + length + 6:.2f}" y="{y + 15}" font-family="Arial,sans-serif" font-size="11" fill="#111827">{fmt(value, 2)}</text>')
    parts.append('</svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def metric_index(metrics: Sequence[dict[str, str]]) -> dict[str, dict[tuple[str, str, str], float]]:
    result: dict[str, dict[tuple[str, str, str], float]] = defaultdict(dict)
    for row in metrics:
        result[row["payload_hash"]][(
            row["metric_scope"], row["metric_entity"], row["metric_name"]
        )] = float(row["metric_value"])
    return result


def parameter_response(
    parameter_id: str,
    points: Sequence[dict[str, str]],
    metrics: dict[str, dict[tuple[str, str, str], float]],
    detector_series: dict[str, dict[str, list[dict[str, str]]]],
    duration_seconds: int,
    peak_count: int,
) -> tuple[str, str, list[tuple[float, float]]]:
    values: dict[float, list[float]] = defaultdict(list)
    if parameter_id.startswith("vehicle_fourier_peak_"):
        subject = "vehicles"
        peak_index = int(parameter_id.rsplit("_", 1)[-1]) - 1
        window = duration_seconds / peak_count
        lower, upper = peak_index * window, (peak_index + 1) * window
        response_name = f"SUP vehicle entries in peak-{peak_index + 1} window"
        response_unit = "detector entries per 90-minute window"
        for point in points:
            rows = detector_series[point["payload_hash"]][subject]
            value = sum(
                float(row["interval_count"])
                for row in rows
                if lower <= float(row["begin_seconds"]) < upper
            )
            values[float(point["value"])].append(value)
    elif parameter_id.startswith("pedestrian_fourier_peak_"):
        subject = "pedestrians"
        peak_index = int(parameter_id.rsplit("_", 1)[-1]) - 1
        window = duration_seconds / peak_count
        lower, upper = peak_index * window, (peak_index + 1) * window
        response_name = f"SUP pedestrian entries in peak-{peak_index + 1} window"
        response_unit = "detector entries per 90-minute window"
        for point in points:
            rows = detector_series[point["payload_hash"]][subject]
            value = sum(
                float(row["interval_count"])
                for row in rows
                if lower <= float(row["begin_seconds"]) < upper
            )
            values[float(point["value"])].append(value)
    elif parameter_id == "residential_pedestrians":
        response_name = "SUP total pedestrian entries"
        response_unit = "detector entries over 12 hours"
        key = ("detector", "SUP Detector [pedestrians]", "total_entries")
        for point in points:
            values[float(point["value"])].append(metrics[point["payload_hash"]][key])
    else:
        response_name = "SUP total vehicle entries"
        response_unit = "detector entries over 12 hours"
        key = ("detector", "SUP Detector [vehicles]", "total_entries")
        for point in points:
            values[float(point["value"])].append(metrics[point["payload_hash"]][key])
    return response_name, response_unit, sorted(
        (value, statistics.fmean(observations)) for value, observations in values.items()
    )


def find_real_vehicle_series(project_root: Path, expected_mean: float) -> list[tuple[float, float]]:
    for path in sorted((project_root / "output" / "calibration").glob("*/best_fit_series.csv"), reverse=True):
        rows = read_csv(path)
        if not rows or "real_flow_agents_per_hour" not in rows[0]:
            continue
        series = [(float(row["time_seconds"]), float(row["real_flow_agents_per_hour"])) for row in rows]
        if math.isclose(statistics.fmean(value for _, value in series), expected_mean, rel_tol=0, abs_tol=1e-6):
            return series
    return []


def generate(output_dir: Path, project_root: Path) -> Path:
    plan = read_csv(output_dir / "plan.csv")
    metrics_rows = read_csv(output_dir / "metrics.csv")
    series_rows = read_csv(output_dir / "detector_timeseries.csv")
    state = json.loads((output_dir / "state.json").read_text(encoding="utf-8"))
    config = json.loads((output_dir / "config.snapshot.json").read_text(encoding="utf-8"))
    context = json.loads((output_dir / "model_context.json").read_text(encoding="utf-8"))
    metrics = metric_index(metrics_rows)
    detector_series: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for row in series_rows:
        if row["logical_name"] == "SUP Detector":
            detector_series[row["payload_hash"]][row["subject"]].append(row)

    parameter_points: dict[str, list[dict[str, str]]] = defaultdict(list)
    parameter_order: list[str] = []
    for row in plan:
        parameter = row["parameter_id"]
        if parameter == "baseline":
            continue
        if parameter not in parameter_points:
            parameter_order.append(parameter)
        parameter_points[parameter].append(row)
    baseline_hash = next(row["payload_hash"] for row in plan if row["parameter_id"] == "baseline")
    baseline_metrics = metrics[baseline_hash]
    vehicle_entity = "SUP Detector [vehicles]"
    pedestrian_entity = "SUP Detector [pedestrians]"
    real_vehicle_entity = "SUP Detector vs real [vehicles]"
    real_pedestrian_entity = "SUP Detector vs real [pedestrians]"
    vehicle_entries = baseline_metrics[("detector", vehicle_entity, "total_entries")]
    vehicle_sim_mean = baseline_metrics[("detector", vehicle_entity, "mean_flow_per_hour")]
    vehicle_real_mean = baseline_metrics[("real_world_comparison", real_vehicle_entity, "real_mean_flow_per_hour")]
    vehicle_rmse = baseline_metrics[("real_world_comparison", real_vehicle_entity, "rmse_flow_per_hour")]
    vehicle_corr = baseline_metrics[("real_world_comparison", real_vehicle_entity, "pearson_correlation")]
    vehicle_shape = baseline_metrics[("real_world_comparison", real_vehicle_entity, "shape_rmse")]
    pedestrian_entries = baseline_metrics[("detector", pedestrian_entity, "total_entries")]
    pedestrian_real_mean = baseline_metrics[("real_world_comparison", real_pedestrian_entity, "real_mean_flow_per_hour")]
    pedestrian_rmse = baseline_metrics[("real_world_comparison", real_pedestrian_entity, "rmse_flow_per_hour")]

    assets = output_dir / "report_assets"
    hill_dir = assets / "hill"
    hill_dir.mkdir(parents=True, exist_ok=True)
    duration_seconds = int(config["baseline"]["duration_hours"]) * 3600
    peak_count = int(config["baseline"]["vehicle_fourier"]["peak_count"])
    fit_rows: list[dict[str, Any]] = []

    rmse_key = ("real_world_comparison", real_vehicle_entity, "rmse_flow_per_hour")
    corr_key = ("real_world_comparison", real_vehicle_entity, "pearson_correlation")
    for parameter in parameter_order:
        points = parameter_points[parameter]
        label = points[0]["parameter_label"]
        unit = points[0]["unit"]
        baseline_value = float(points[0]["baseline_value"])
        response_name, response_unit, curve = parameter_response(
            parameter, points, metrics, detector_series, duration_seconds, peak_count
        )
        x = [item[0] for item in curve]
        y = [item[1] for item in curve]
        fitted = fit_hill(x, y)
        rmse_curve = [
            (float(point["value"]), metrics[point["payload_hash"]][rmse_key])
            for point in points
            if rmse_key in metrics[point["payload_hash"]]
        ]
        corr_curve = [
            (float(point["value"]), metrics[point["payload_hash"]].get(corr_key)) for point in points
            if metrics[point["payload_hash"]].get(corr_key) is not None
        ]
        if not rmse_curve:
            raise RuntimeError(f"No vehicle comparison metrics are available for {parameter}")
        best_rmse_value, best_rmse = min(rmse_curve, key=lambda item: item[1])
        best_corr_value, best_corr = max(corr_curve, key=lambda item: item[1]) if corr_curve else (None, None)
        plot_name = f"{len(fit_rows) + 1:02d}-{slug(parameter)}.svg"
        subtitle = (
            f"{fitted.get('equation', fitted.get('reason', 'Hill fit unavailable'))}; "
            f"R²={fmt(fitted.get('r_squared'))}; ρ={fmt(fitted.get('spearman'))}; {fitted['status']}"
        )
        line_chart_svg(
            hill_dir / plot_name,
            title=label,
            subtitle=subtitle,
            x_label=f"{label} ({unit})",
            y_label=response_unit,
            series=[("Observed simulation output", curve, "#2563eb")],
            fit=fitted if fitted.get("y0") is not None else None,
            baseline_x=baseline_value,
        )
        fit_rows.append({
            "parameter_id": parameter,
            "parameter_label": label,
            "input_unit": unit,
            "input_min": min(x),
            "input_max": max(x),
            "baseline_input": baseline_value,
            "response": response_name,
            "response_unit": response_unit,
            "response_min": min(y),
            "response_max": max(y),
            "equation": fitted.get("equation") or "not identifiable",
            "y0": fitted.get("y0"),
            "vmax": fitted.get("vmax"),
            "k_half": fitted.get("k_half"),
            "n": fitted.get("n"),
            "r_squared": fitted.get("r_squared"),
            "spearman": fitted.get("spearman"),
            "fit_status": fitted["status"],
            "fit_reason": fitted.get("reason"),
            "best_vehicle_rmse_input": best_rmse_value,
            "best_vehicle_rmse": best_rmse,
            "best_vehicle_correlation_input": best_corr_value,
            "best_vehicle_correlation": best_corr,
            "graph": f"report_assets/hill/{plot_name}",
        })

    write_csv(
        output_dir / "hill_fits.csv",
        fit_rows,
        [
            "parameter_id", "parameter_label", "input_unit", "input_min", "input_max",
            "baseline_input", "response", "response_unit", "response_min", "response_max",
            "equation", "y0", "vmax", "k_half", "n", "r_squared", "spearman",
            "fit_status", "fit_reason", "best_vehicle_rmse_input", "best_vehicle_rmse",
            "best_vehicle_correlation_input", "best_vehicle_correlation", "graph",
        ],
    )

    baseline_sim_series = [
        (float(row["begin_seconds"]), float(row["flow_per_hour"]))
        for row in detector_series[baseline_hash]["vehicles"]
    ]
    real_vehicle_series = find_real_vehicle_series(project_root, vehicle_real_mean)
    overview_series = [("Simulation", baseline_sim_series, "#2563eb")]
    if real_vehicle_series:
        overview_series.append(("Avenue Paul Langevin weekly average", real_vehicle_series, "#ea580c"))
    line_chart_svg(
        assets / "baseline-vehicle-profile.svg",
        title="Baseline vehicle flow: simulation versus real sensor",
        subtitle=f"RMSE={fmt(vehicle_rmse)} agents/hour; Pearson r={fmt(vehicle_corr)}; mean bias={fmt(vehicle_sim_mean - vehicle_real_mean)} agents/hour",
        x_label="Seconds after 07:00",
        y_label="Flow (agents/hour)",
        series=overview_series,
    )

    improvements = sorted(
        [
            (row["parameter_label"], vehicle_rmse - float(row["best_vehicle_rmse"]))
            for row in fit_rows
        ],
        key=lambda item: item[1],
        reverse=True,
    )[:15]
    horizontal_bar_svg(
        assets / "best-rmse-improvement.svg",
        "Best single-parameter reduction in vehicle-flow RMSE (agents/hour)",
        improvements,
    )

    run_durations = [
        float(item["execution_seconds"])
        for item in state["runs"].values()
        if item.get("execution_seconds") is not None
    ]
    created = min(
        (value for item in state["runs"].values() if (value := parse_time(item.get("created_at"))) is not None),
        default=parse_time(state.get("created_at")),
    )
    completed = max(
        (value for item in state["runs"].values() if (value := parse_time(item.get("completed_at"))) is not None),
        default=parse_time(state.get("updated_at")),
    )
    wall_seconds = (completed - created).total_seconds() if created and completed else 0
    best_overall = min(fit_rows, key=lambda row: float(row["best_vehicle_rmse"]))
    best_correlation = max(
        (row for row in fit_rows if row["best_vehicle_correlation"] is not None),
        key=lambda row: float(row["best_vehicle_correlation"]),
    )
    baseline_parking = {
        key[2]: value for key, value in baseline_metrics.items() if key[0] == "parking_summary"
    }
    baseline_search = {
        key[2]: value for key, value in baseline_metrics.items() if key[0] == "search_time"
    }
    baseline_attempts = {
        key[2]: value for key, value in baseline_metrics.items() if key[0] == "parking_attempts"
    }

    report: list[str] = [
        "# Sensitivity analysis and Hill-response report",
        "",
        f"**Model:** {context['model_name']}  ",
        f"**Study:** {state['study_name']}  ",
        f"**Simulation period:** 19 January 2026, 07:00–19:00  ",
        f"**Real-world reference:** {context['real_world_sensor']['name']}, Monday weekly average  ",
        f"**Comparison detector:** {context['comparison_detector']['name']}  ",
        "",
        "## Executive summary",
        "",
        "The purpose of this study was to learn how individual simulation inputs affect the flow measured at the campus detector, and then use that knowledge to move the simulation closer to the Avenue Paul Langevin weekly-average profile. A one-factor-at-a-time (OFAT) design was used: one parameter was varied while all other settings were restored to the same baseline. This isolates first-order effects and provides response curves that can be tested for saturation with a Hill function.",
        "",
        f"All **{len(state['runs'])} unique simulations completed successfully**, with no failed analytics collections. The baseline vehicle simulation produced **{fmt(vehicle_entries, 0)} detector entries**, a mean of **{fmt(vehicle_sim_mean)} agents/hour**, compared with **{fmt(vehicle_real_mean)} agents/hour** in the real sensor. The baseline underestimates the mean by **{fmt((vehicle_sim_mean / vehicle_real_mean - 1) * 100, 1)}%**, has RMSE **{fmt(vehicle_rmse)} agents/hour**, and has Pearson correlation **{fmt(vehicle_corr)}**. The low correlation means the temporal shape is not reproduced, even apart from the low flow level.",
        "",
        f"The pedestrian detector reported **{fmt(pedestrian_entries, 0)} simulated entries in every tested configuration**, while the real sensor mean is **{fmt(pedestrian_real_mean)} pedestrians/hour.** Consequently, pedestrian sensitivity and pedestrian Hill parameters cannot be identified from this experiment. This is a detector coverage/configuration or route-intersection problem that must be corrected before pedestrian calibration.",
        "",
        f"The best vehicle RMSE seen in any one-parameter experiment was **{fmt(best_overall['best_vehicle_rmse'])} agents/hour**, obtained at **{best_overall['parameter_label']} = {fmt(float(best_overall['best_vehicle_rmse_input']))} {best_overall['input_unit']}**. This is only a **{fmt((vehicle_rmse - float(best_overall['best_vehicle_rmse'])) / vehicle_rmse * 100, 1)}%** improvement over baseline. The highest observed vehicle-profile correlation was **{fmt(float(best_correlation['best_vehicle_correlation']))}**, obtained at **{best_correlation['parameter_label']} = {fmt(float(best_correlation['best_vehicle_correlation_input']))} {best_correlation['input_unit']}**. No individual parameter produced a close real-world match; multivariable calibration and route/detector corrections are required.",
        "",
        "![Baseline vehicle comparison](report_assets/baseline-vehicle-profile.svg)",
        "",
        "![Best RMSE improvements](report_assets/best-rmse-improvement.svg)",
        "",
        "## 1. Calibration objective",
        "",
        "The intended calibration target has two components:",
        "",
        "1. **Flow level:** the number of agents passing the detector should be close to the physical sensor.",
        "2. **Temporal shape:** peaks and valleys should occur at similar times and with similar relative amplitudes.",
        "",
        "Increasing total demand alone can reduce a level error while leaving the daily shape wrong. Conversely, changing Fourier peaks can improve correlation while keeping the mean flow too low. For that reason, this report keeps RMSE, mean bias, and correlation separate instead of reducing everything to one number.",
        "",
        "## 2. Experimental design",
        "",
        "### 2.1 Fixed baseline",
        "",
        f"- Total independent pedestrians: **{config['baseline']['pedestrian_count']:,}**",
        f"- Vehicles: **{config['baseline']['vehicle_count']:,}**",
        f"- Residential pedestrians: **{config['baseline']['residential_pedestrian_count']:,}**",
        f"- Vehicle origins: **{len(context['vehicle_origins'])}**, equally allocated at baseline",
        f"- Building classification: **{context['classification']['name']}**",
        f"- Vehicle and pedestrian profiles: **{peak_count} Fourier peaks**, 100% baseline amplitude, width {config['baseline']['vehicle_fourier']['peak_width_hours']} hours, {config['baseline']['vehicle_fourier']['harmonics']} harmonics",
        f"- Pedestrian behavior: **Fast / {config['baseline']['pedestrian_model']}**",
        f"- Execution mode: **{config['baseline']['mode']}**",
        f"- Random seed: **{config['baseline']['random_seed']}**",
        "- Parking choice baseline: driving 0.8; walking 1.0; capacity 0.8; absolute free space 1.3; relative free space 1.5; knowledge 0.5; expected occupancy 0.6; perception error 0.15; frustration 0.35; randomness 0.",
        "",
        "With eight peaks over twelve hours, nominal peak centers occur every 90 minutes: 07:45, 09:15, 10:45, 12:15, 13:45, 15:15, 16:45, and 18:15.",
        "",
        "### 2.2 Parameters and run count",
        "",
        f"The plan contained **{len(plan)} design points** across **{len(parameter_order)} parameters**. Identical baseline payloads were reused, leaving **{len(state['runs'])} actual simulations**. This avoids rerunning the same baseline separately for every sensitivity curve.",
        "",
        "| Parameter family | Parameters | Tested ranges |",
        "|---|---:|---|",
        "| Vehicle Fourier amplitudes | 8 | 0–300%, step 50% |",
        "| Pedestrian Fourier amplitudes | 8 | 0–300%, step 50% |",
        f"| Residential pedestrians | 1 | {int(min(float(p['value']) for p in parameter_points['residential_pedestrians'])):,}–{int(max(float(p['value']) for p in parameter_points['residential_pedestrians'])):,} |",
        f"| Vehicle count | 1 | {int(min(float(p['value']) for p in parameter_points['vehicle_count'])):,}–{int(max(float(p['value']) for p in parameter_points['vehicle_count'])):,} |",
        "| Vehicle-entry shares | 4 | 0, 20, 25, 40, 60, 80, 100% |",
        "| Parking-choice parameters | 10 | Parameter-specific grids shown in the Hill table |",
        "",
        "### 2.3 Computational execution",
        "",
        f"- Completed simulations: **{len(run_durations)}**",
        f"- Mean execution time: **{duration_label(statistics.fmean(run_durations))}**",
        f"- Median execution time: **{duration_label(statistics.median(run_durations))}**",
        f"- Minimum / maximum execution time: **{duration_label(min(run_durations))} / {duration_label(max(run_durations))}**",
        f"- Sum of individual simulation execution times: **{duration_label(sum(run_durations))}**",
        f"- Study wall-clock span with four workers: approximately **{duration_label(wall_seconds)}**",
        "",
        "## 3. Metrics",
        "",
        "For aligned 15-minute intervals, with simulated flow `sᵢ`, observed flow `rᵢ`, and `N` intervals:",
        "",
        "- **MAE:** `mean(|sᵢ − rᵢ|)`",
        "- **RMSE:** `sqrt(mean((sᵢ − rᵢ)²))`; large errors receive more weight.",
        "- **Mean bias:** `mean(sᵢ) − mean(rᵢ)`; negative values indicate underestimation.",
        "- **Pearson correlation:** measures similarity of temporal shape, independent of much of the absolute scale.",
        "- **Shape RMSE:** compares each series after division by its own mean.",
        "- **Spearman ρ:** measures whether a parameter response is monotonically increasing or decreasing, which is important for judging whether a Hill curve is appropriate.",
        "",
        "## 4. Baseline results",
        "",
        "| Quantity | Simulation | Real reference | Interpretation |",
        "|---|---:|---:|---|",
        f"| Vehicle mean flow | {fmt(vehicle_sim_mean)} /h | {fmt(vehicle_real_mean)} /h | {fmt((vehicle_sim_mean / vehicle_real_mean - 1) * 100, 1)}% mean underestimation |",
        f"| Vehicle total detector entries | {fmt(vehicle_entries, 0)} | — | Only {fmt(vehicle_entries / config['baseline']['vehicle_count'] * 100, 1)}% of generated vehicles cross the detector |",
        f"| Vehicle RMSE | {fmt(vehicle_rmse)} /h | 0 ideal | Large level/time error |",
        f"| Vehicle correlation | {fmt(vehicle_corr)} | 1 ideal | Very weak shape agreement |",
        f"| Vehicle shape RMSE | {fmt(vehicle_shape)} | 0 ideal | Shape mismatch remains after scaling |",
        f"| Pedestrian mean flow | 0 /h | {fmt(pedestrian_real_mean)} /h | Detector observes no simulated pedestrians |",
        f"| Pedestrian RMSE | {fmt(pedestrian_rmse)} /h | 0 ideal | Cannot calibrate until detector issue is corrected |",
        "",
        "Baseline parking outcomes also reveal structural constraints:",
        "",
        f"- Parked people: **{int(baseline_parking.get('parked_people', 0)):,} / {int(baseline_parking.get('planned_vehicle_people', 0)):,}**",
        f"- Unserved people: **{int(baseline_parking.get('unserved_people', 0)):,}**",
        f"- Unused parking areas: **{int(baseline_parking.get('unused_parking_areas', 0)):,}**",
        f"- Buildings receiving drivers: **{int(baseline_parking.get('buildings_receiving_drivers', 0)):,} / {int(baseline_parking.get('destination_buildings', 0)):,}**",
        f"- Vehicles using fallback: **{int(baseline_attempts.get('vehicles_using_fallback', 0)):,} ({fmt(baseline_attempts.get('fallback_percentage'))}%)**",
        f"- Mean search time among recorded vehicles: **{fmt(baseline_search.get('average_seconds'))} seconds**",
        "",
        "These parking/access constraints can alter which routes cross Avenue Paul Langevin. Flow calibration therefore cannot be treated purely as Fourier-amplitude fitting.",
        "",
        "## 5. Hill-function method",
        "",
        "The four-parameter Hill equation fitted to each selected response was:",
        "",
        "`y(x) = y₀ + Vmax × xⁿ / (Khalfⁿ + xⁿ)`",
        "",
        "where:",
        "",
        "- `y₀` is the response near zero input.",
        "- `Vmax` is the change between the lower and upper asymptotes. It may be negative for a decreasing response.",
        "- `Khalf` is the input at half of the fitted asymptotic change.",
        "- `n` controls steepness.",
        "",
        "For Fourier amplitudes, `y` is the detector count in that peak's nominal 90-minute window. For residential pedestrians, it is total pedestrian detector entries. For vehicle count, entry allocation, and parking-choice parameters, it is total vehicle detector entries over twelve hours.",
        "",
        "A Hill curve assumes a mostly monotonic, saturating relationship. A high R² alone is not enough: fits are classified using both R² and Spearman monotonicity. Constant pedestrian responses are reported as **not identifiable**, not as perfect Hill fits. Poor fits should not be used as calibration equations.",
        "",
        "## 6. Hill equations and graphs",
        "",
        "The table below provides one response equation for every tested parameter. Full numerical coefficients are also available in `hill_fits.csv`.",
        "",
        "| Parameter | Range | Response | Hill equation | R² | ρ | Assessment |",
        "|---|---:|---|---|---:|---:|---|",
    ]
    for row in fit_rows:
        report.append(
            f"| [{row['parameter_label']}]({row['graph']}) | {fmt(float(row['input_min']))}–{fmt(float(row['input_max']))} {row['input_unit']} | "
            f"{row['response']} | `{row['equation']}` | {fmt(row['r_squared'])} | {fmt(row['spearman'])} | {row['fit_status']} |"
        )

    report += [
        "",
        "### 6.1 Individual response plots",
        "",
        "The blue points are completed simulations. The orange dashed line is the fitted Hill curve. The vertical dashed line marks the baseline input.",
        "",
    ]
    for index, row in enumerate(fit_rows, start=1):
        report += [
            f"#### {index}. {row['parameter_label']}",
            "",
            f"- Response: {row['response']} ({row['response_unit']})",
            f"- Equation: `{row['equation']}`",
            f"- Fit assessment: **{row['fit_status']}**; R² = {fmt(row['r_squared'])}; Spearman ρ = {fmt(row['spearman'])}",
            f"- Best vehicle RMSE within this parameter sweep: {fmt(float(row['best_vehicle_rmse']))} agents/hour at {fmt(float(row['best_vehicle_rmse_input']))} {row['input_unit']}",
            "",
            f"![{row['parameter_label']}]({row['graph']})",
            "",
        ]

    report += [
        "## 7. Interpretation by parameter family",
        "",
        "### 7.1 Vehicle Fourier peaks",
        "",
        "Changing one Fourier amplitude mainly redistributes a fixed total of 3,000 vehicle departures across time. It therefore has a much larger effect on its local 90-minute window than on the twelve-hour detector total. Several peak curves are approximately monotonic, but discontinuities were observed in some sweeps. These can result from Fourier approximation behavior, congestion thresholds, route switching, or failed/late trips. Peak 4 offered the largest observed improvement in temporal correlation, but even its best correlation remained far below a satisfactory match.",
        "",
        "### 7.2 Pedestrian Fourier peaks and residential pedestrians",
        "",
        "Every simulated pedestrian response at the SUP detector was zero. Therefore, all pedestrian Hill curves are structurally unidentifiable. Increasing pedestrian demand cannot fix this: routes must cross a correctly configured pedestrian detector first. The next action should be to inspect the detector's pedestrian zones/cross-sections and visualize representative pedestrian routes.",
        "",
        "### 7.3 Vehicle count",
        "",
        "Vehicle count produced the strongest overall change in detector throughput and the best single-parameter RMSE. However, the response was not sufficient to reproduce the real temporal shape, and increasing demand also increases unserved parking demand. Vehicle count should be calibrated jointly with route-entry allocation and parking/accessibility, not used alone as a scale factor.",
        "",
        "### 7.4 Vehicle entry allocation",
        "",
        "Entry allocation can materially change which vehicles cross the SUP detector without changing total campus demand. Avenue Jean Perrin and Avenue Henri Poincaré produced the largest throughput ranges among the entry sweeps. This confirms that route topology and origin placement are important calibration variables. Because changing one entry share redistributes the remainder across the other three entries, each curve represents a coupled allocation change rather than an isolated origin count.",
        "",
        "### 7.5 Parking-search choice parameters",
        "",
        "Parking-choice weights generally changed detector throughput less than vehicle count or major entry reallocations. Their effects are mediated through parking eligibility, route choice, rerouting, occupancy knowledge, and fallback behavior. Some responses are non-monotonic, so forcing a Hill curve would hide route-switch thresholds. These parameters should be calibrated against observed parking outcomes first, and only then used as secondary traffic-flow calibration variables.",
        "",
        "## 8. Recommended calibration strategy",
        "",
        "1. **Repair pedestrian observability.** Confirm that the pedestrian detector geometry intersects pedestrian routes in both directions. Do not calibrate pedestrian amplitudes while every simulated observation is zero.",
        "2. **Verify the vehicle detector and Avenue Paul Langevin routes.** The baseline detector sees about 36% of generated vehicles and has very weak temporal correlation. Inspect route counts by entry and destination to determine whether the simulated network sends vehicles through the same corridor as reality.",
        "3. **Use time-window response models for Fourier peaks.** A separate local response for each peak is more appropriate than a single total-flow Hill equation because total demand is fixed.",
        "4. **Run a targeted multivariable experiment.** Combine the most promising vehicle count, entry allocation, and peak-4/peak-7 settings. OFAT cannot estimate their interactions.",
        "5. **Optimize a multi-objective loss.** A practical objective is `J = 0.45 × normalized RMSE + 0.35 × (1 − correlation) + 0.20 × absolute volume error`. Reject configurations with excessive unserved parking demand.",
        "6. **Replicate stochastic cases.** The current study uses one fixed seed. For non-zero choice randomness, run at least three seeds per setting and fit the mean with uncertainty intervals.",
        "7. **Validate on another day or sensor.** After selecting parameters, test them on data not used during calibration to avoid fitting one Monday-average profile too closely.",
        "",
        "## 9. Limitations",
        "",
        "- OFAT captures first-order responses but not interactions.",
        "- Only one random seed was used for each design point.",
        "- A Hill equation is descriptive, not a physical law for traffic assignment.",
        "- Discontinuous route changes and capacity limits can violate Hill assumptions.",
        "- The Avenue Paul Langevin comparison is mediated by detector placement and directionality.",
        "- Pedestrian results are currently invalid for calibration because simulated detector flow is zero.",
        "- Changing one vehicle-entry share necessarily changes the other shares, so those effects are compositional.",
        "- The current model has accessibility limitations for some buildings and parking areas; future network corrections require a new sensitivity study because the response surface will change.",
        "",
        "## 10. Reproducibility and generated files",
        "",
        "- `config.snapshot.json`: exact baseline and parameter ranges.",
        "- `model_context.json`: model, origin, detector, and sensor identities.",
        "- `plan.csv`: design-point to simulation mapping.",
        "- `runs.csv`: run identifiers and timings.",
        "- `detector_timeseries.csv`: 15-minute simulated detector output.",
        "- `metrics.csv`: detector, real-world comparison, parking, and building metrics.",
        "- `hill_fits.csv`: report-specific Hill equations and fit diagnostics.",
        "- `report_assets/hill/`: one SVG response graph per parameter.",
        "",
        f"Report generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} from the completed local sensitivity dataset.",
        "",
    ]
    report_path = output_dir / "detailed_report.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the detailed sensitivity/Hill report.")
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("sensitivity_analysis/results/cite_test_2_ofat_v1"),
    )
    args = parser.parse_args()
    output_dir = args.output_directory.resolve()
    project_root = Path(__file__).resolve().parents[1]
    required = ["plan.csv", "metrics.csv", "detector_timeseries.csv", "state.json"]
    missing = [name for name in required if not (output_dir / name).is_file()]
    if missing:
        raise SystemExit("Missing report inputs: " + ", ".join(missing))
    report = generate(output_dir, project_root)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
