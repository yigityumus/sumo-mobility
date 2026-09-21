#!/usr/bin/env python3
"""Start and monitor a locked, sequential Fourier flow calibration.

The server snapshots the complete simulation configuration. After each run it
compares equal-width peak windows against the selected weekly-average sensor
series and changes only ``peak_heights`` for the next run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_VEHICLE_FOURIER = {
    "peak_count": 2,
    "peak_width_hours": 1.5,
    "harmonics": 6,
    "peak_heights": [1.0, 1.0],
}
DEFAULT_PEDESTRIAN_FOURIER = {
    "peak_count": 16,
    "peak_width_hours": 0.3,
    "harmonics": 10,
    "peak_heights": [
        0.2, 0.75, 0.1, 0.15, 1.0, 0.1, 0.4, 1.0,
        0.1, 0.15, 0.75, 0.1, 0.65, 0.4, 0.15, 0.1,
    ],
}
DEFAULT_PARKING_CHOICE = {
    "knowledge_probability": 0.5,
    "uninformed_occupancy_mean": 0.6,
    "uninformed_occupancy_stddev": 0.15,
    "frustration_step": 0.35,
    "stochastic_scale": 0.0,
    "weights": {
        "drive_time": 0.8,
        "walk_time": 1.0,
        "capacity": 0.8,
        "absolute_free_space": 1.3,
        "relative_free_space": 1.5,
    },
}
TERMINAL_STATUSES = {"completed", "failed"}


class CalibrationError(RuntimeError):
    """A user-facing calibration failure."""


class ApiError(CalibrationError):
    """An application API request failed."""


@dataclass(frozen=True)
class CalibrationConfig:
    api_url: str = "http://localhost:8000"
    calibration_name: str = "Avenue Paul Langevin weekly flow"
    model_name: str = "Cite Scientifique Test 2"
    classification_name: str = "Usage Policy"
    sensor_name: str = "Avenue Paul Langevin"
    detector_name: str | None = None
    subjects: tuple[str, ...] = ("vehicles",)
    iterations: int = 10
    step_percentage: float = 1.0
    total_people: int = 16_000
    vehicle_count: int = 3_000
    residential_pedestrian_count: int = 4_000
    duration_hours: int = 12
    simulation_start_at: str = "2026-01-19T07:00:00"
    simulation_timezone: str = "Europe/Paris"
    simulation_seed: int = 20260119
    poll_seconds: float = 15.0
    timeout_seconds: float = 24 * 60 * 60
    vehicle_fourier_file: Path | None = None
    pedestrian_fourier_file: Path | None = None
    output_file: Path | None = None
    dry_run: bool = False

    @property
    def pedestrian_count(self) -> int:
        return self.total_people - self.vehicle_count

    @property
    def public_transport_pedestrian_count(self) -> int:
        return self.pedestrian_count - self.residential_pedestrian_count

    def validate(self) -> None:
        if not 1 <= self.iterations <= 100:
            raise CalibrationError("iterations must be between 1 and 100")
        if not 0.1 <= self.step_percentage <= 100:
            raise CalibrationError("step percentage must be between 0.1 and 100")
        if not self.subjects or any(
            item not in {"vehicles", "pedestrians"} for item in self.subjects
        ):
            raise CalibrationError("subjects must contain vehicles and/or pedestrians")
        if len(set(self.subjects)) != len(self.subjects):
            raise CalibrationError("subjects must not contain duplicates")
        if not 0 <= self.vehicle_count < self.total_people:
            raise CalibrationError("vehicle count must fit within total people")
        if not 0 <= self.residential_pedestrian_count <= self.pedestrian_count:
            raise CalibrationError("residential pedestrian count is out of range")
        if not 1 <= self.simulation_seed <= 2_147_483_646:
            raise CalibrationError("simulation seed is out of range")


class ApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                detail = str(json.loads(detail).get("detail") or detail)
            except json.JSONDecodeError:
                pass
            raise ApiError(f"{method} {path} returned {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ApiError(f"Could not reach {self.base_url}: {exc}") from exc
        if not content:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ApiError(f"{method} {path} returned invalid JSON") from exc


def normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.casefold().split())


def resolve_named(
    items: Iterable[dict[str, Any]],
    query: str,
    *,
    label: str,
    fields: tuple[str, ...] = ("name",),
) -> dict[str, Any]:
    candidates = list(items)
    needle = normalized_text(query)
    exact = [
        item for item in candidates
        if any(normalized_text(item.get(field)) == needle for field in fields)
    ]
    matches = exact or [
        item for item in candidates
        if any(needle in normalized_text(item.get(field)) for field in fields)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        available = ", ".join(
            str(item.get("name") or item.get("id")) for item in candidates
        )
        raise CalibrationError(
            f"No {label} matched '{query}'. Available: {available or 'none'}"
        )
    names = ", ".join(str(item.get("name") or item.get("id")) for item in matches)
    raise CalibrationError(f"'{query}' matched multiple {label}s: {names}")


def load_fourier_profile(path: Path | None, default: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8")) if path else dict(default)
    count = int(value.get("peak_count") or 0)
    heights = value.get("peak_heights") or []
    if not 1 <= count <= 16 or len(heights) != count:
        raise CalibrationError(
            "A Fourier profile needs 1–16 peaks and exactly one peak_heights value per peak."
        )
    if any(not 0 <= float(item) <= 3 for item in heights):
        raise CalibrationError("Fourier peak heights must be between 0 and 3.")
    return {
        "peak_count": count,
        "peak_width_hours": float(value["peak_width_hours"]),
        "harmonics": int(value["harmonics"]),
        "peak_heights": [float(item) for item in heights],
    }


class FlowCalibration:
    def __init__(self, config: CalibrationConfig) -> None:
        config.validate()
        self.config = config
        self.api = ApiClient(config.api_url)
        self.model: dict[str, Any] = {}
        self.classification: dict[str, Any] = {}
        self.sensor: dict[str, Any] = {}
        self.detector: dict[str, Any] = {}

    def prepare(self) -> None:
        health = self.api.request("/api/health")
        if health.get("status") != "ok":
            raise CalibrationError(f"Application services are not healthy: {health}")
        summary = resolve_named(
            self.api.request("/api/models"), self.config.model_name, label="model"
        )
        self.model = self.api.request(f"/api/models/{summary['id']}")
        self.classification = resolve_named(
            self.model.get("buildingClassifications") or [],
            self.config.classification_name,
            label="building classification",
        )
        self.sensor = resolve_named(
            self.api.request("/api/analytics/real-world/sources"),
            self.config.sensor_name,
            label="real-world sensor",
            fields=("name", "street", "segment_id"),
        )
        detectors = [
            item for item in self.model.get("detectors") or []
            if item.get("type") == "e3"
            and set(self.config.subjects).issubset(
                set(item.get("detects") or ["vehicles"])
            )
        ]
        if self.config.detector_name:
            self.detector = resolve_named(
                detectors,
                self.config.detector_name,
                label="E3 detector",
                fields=("name", "id"),
            )
        elif len(detectors) == 1:
            self.detector = detectors[0]
        else:
            names = ", ".join(
                str(item.get("name") or item.get("id")) for item in detectors
            )
            raise CalibrationError(
                "Pass --detector-name when there is not exactly one compatible E3 detector. "
                f"Available: {names or 'none'}"
            )

    def simulation_payload(self) -> dict[str, Any]:
        return {
            "vehicle_count": self.config.vehicle_count,
            "pedestrian_count": self.config.pedestrian_count,
            "total_people": self.config.total_people,
            "vehicle_percentage": round(
                self.config.vehicle_count / self.config.total_people * 100
            ),
            "building_classification_id": self.classification["id"],
            "residential_pedestrian_count": self.config.residential_pedestrian_count,
            "public_transport_pedestrian_count": self.config.public_transport_pedestrian_count,
            "duration_hours": self.config.duration_hours,
            "simulation_start_at": self.config.simulation_start_at,
            "simulation_timezone": self.config.simulation_timezone,
            "mode": "sumo",
            "pedestrian_model": "nonInteracting",
            "diagnostic_tracing": False,
            "random_seed": self.config.simulation_seed,
            "vehicle_traffic_model": "fourier",
            "pedestrian_traffic_model": "fourier",
            "vehicle_fourier_parameters": load_fourier_profile(
                self.config.vehicle_fourier_file, DEFAULT_VEHICLE_FOURIER
            ),
            "pedestrian_fourier_parameters": load_fourier_profile(
                self.config.pedestrian_fourier_file, DEFAULT_PEDESTRIAN_FOURIER
            ),
            "parking_choice": DEFAULT_PARKING_CHOICE,
        }

    def calibration_payload(self) -> dict[str, Any]:
        return {
            "name": self.config.calibration_name,
            "real_world_source_id": self.sensor["id"],
            "detector_logical_id": self.detector["id"],
            "subjects": list(self.config.subjects),
            "iterations": self.config.iterations,
            "step_percentage": self.config.step_percentage,
            "simulation": self.simulation_payload(),
        }

    def run(self) -> dict[str, Any] | None:
        self.prepare()
        payload = self.calibration_payload()
        if self.config.dry_run:
            print(json.dumps(payload, indent=2))
            return None
        session = self.api.request(
            f"/api/models/{self.model['id']}/flow-calibrations",
            method="POST",
            payload=payload,
        )
        calibration_id = str(session["id"])
        print(f"Started calibration {calibration_id}", flush=True)
        deadline = time.monotonic() + self.config.timeout_seconds
        last_completed = -1
        while session.get("status") not in TERMINAL_STATUSES:
            if time.monotonic() >= deadline:
                raise CalibrationError(f"Timed out waiting for calibration {calibration_id}")
            sessions = self.api.request(
                f"/api/models/{self.model['id']}/flow-calibrations"
            )
            session = next(
                (item for item in sessions if str(item.get("id")) == calibration_id),
                session,
            )
            completed = int(session.get("completed_iterations") or 0)
            if completed != last_completed:
                print(
                    f"Completed {completed}/{session['total_iterations']} iterations",
                    flush=True,
                )
                last_completed = completed
            if session.get("status") not in TERMINAL_STATUSES:
                time.sleep(self.config.poll_seconds)
        if self.config.output_file:
            self.config.output_file.parent.mkdir(parents=True, exist_ok=True)
            self.config.output_file.write_text(
                json.dumps(session, indent=2), encoding="utf-8"
            )
        if session.get("status") == "failed":
            raise CalibrationError(
                str(session.get("failure_reason") or "Calibration failed")
            )
        return session


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start a locked Fourier percentage calibration."
    )
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--name", default="Avenue Paul Langevin weekly flow")
    parser.add_argument("--model-name", default="Cite Scientifique Test 2")
    parser.add_argument("--classification-name", default="Usage Policy")
    parser.add_argument("--sensor-name", default="Avenue Paul Langevin")
    parser.add_argument("--detector-name")
    parser.add_argument(
        "--subject", choices=("vehicles", "pedestrians", "both"), default="vehicles"
    )
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--step-percentage", type=float, default=1.0)
    parser.add_argument("--simulation-seed", type=int, default=20260119)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--timeout-hours", type=float, default=24.0)
    parser.add_argument("--vehicle-fourier-file", type=Path)
    parser.add_argument("--pedestrian-fourier-file", type=Path)
    parser.add_argument("--output-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    subjects = (
        ("vehicles", "pedestrians") if args.subject == "both" else (args.subject,)
    )
    config = CalibrationConfig(
        api_url=args.api_url,
        calibration_name=args.name,
        model_name=args.model_name,
        classification_name=args.classification_name,
        sensor_name=args.sensor_name,
        detector_name=args.detector_name,
        subjects=subjects,
        iterations=args.iterations,
        step_percentage=args.step_percentage,
        simulation_seed=args.simulation_seed,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_hours * 3600,
        vehicle_fourier_file=args.vehicle_fourier_file,
        pedestrian_fourier_file=args.pedestrian_fourier_file,
        output_file=args.output_file,
        dry_run=args.dry_run,
    )
    try:
        session = FlowCalibration(config).run()
    except (CalibrationError, KeyboardInterrupt) as exc:
        print(f"Calibration stopped: {exc}", file=sys.stderr)
        return 1
    if session:
        print(
            f"Calibration {session['id']} completed all "
            f"{session['completed_iterations']} iterations.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
