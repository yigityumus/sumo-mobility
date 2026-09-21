"""Parse uploaded sensor workbooks and query normalized observations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Literal
from xml.etree.ElementTree import iterparse
from zipfile import BadZipFile, ZipFile

from shared.database import (
    read_real_world_observations,
    read_real_world_source_metadata,
)


XLSX_NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DEFAULT_INTERVAL_SECONDS = 15 * 60
RealWorldMode = Literal["raw", "weekly_average"]
RealWorldSubject = Literal["vehicles", "pedestrians"]


class RealWorldDataError(ValueError):
    pass


@dataclass(frozen=True)
class SensorObservation:
    segment_id: str
    street: str
    city: str
    observed_at: datetime
    pedestrian_count: float
    vehicle_count: float


def _column_name(reference: str) -> str:
    return "".join(character for character in reference if character.isalpha())


def _shared_strings(workbook: ZipFile) -> list[str]:
    try:
        stream = workbook.open("xl/sharedStrings.xml")
    except KeyError:
        return []
    values: list[str] = []
    with stream:
        for _event, element in iterparse(stream, events=("end",)):
            if element.tag != f"{XLSX_NAMESPACE}si":
                continue
            values.append(
                "".join(
                    text_node.text or ""
                    for text_node in element.iter(f"{XLSX_NAMESPACE}t")
                )
            )
            element.clear()
    return values


def _cell_value(cell, shared_strings: list[str]) -> str:
    value_node = cell.find(f"{XLSX_NAMESPACE}v")
    if value_node is None:
        inline_node = cell.find(f"{XLSX_NAMESPACE}is")
        if inline_node is None:
            return ""
        return "".join(
            text_node.text or ""
            for text_node in inline_node.iter(f"{XLSX_NAMESPACE}t")
        )
    value = value_node.text or ""
    if cell.attrib.get("t") == "s" and value:
        try:
            return shared_strings[int(value)]
        except (IndexError, ValueError):
            return ""
    return value


def _number(value: str) -> float:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def parse_workbook_bytes(
    content: bytes,
    filename: str,
) -> tuple[SensorObservation, ...]:
    """Parse one immutable workbook object into normalized observations."""
    observations: list[SensorObservation] = []
    try:
        with ZipFile(BytesIO(content)) as workbook:
            shared_strings = _shared_strings(workbook)
            with workbook.open("xl/worksheets/sheet1.xml") as sheet:
                for _event, row in iterparse(sheet, events=("end",)):
                    if row.tag != f"{XLSX_NAMESPACE}row":
                        continue
                    if row.attrib.get("r") == "1":
                        row.clear()
                        continue
                    values = {
                        _column_name(cell.attrib.get("r", "")): _cell_value(
                            cell, shared_strings
                        )
                        for cell in row.findall(f"{XLSX_NAMESPACE}c")
                    }
                    row.clear()
                    try:
                        observed_at = datetime.strptime(
                            values.get("D", ""), "%Y-%m-%d %H:%M"
                        )
                    except ValueError:
                        continue
                    segment_id = str(values.get("A") or "").strip()
                    if not segment_id:
                        continue
                    observations.append(
                        SensorObservation(
                            segment_id=segment_id,
                            street=str(values.get("B") or "Unknown street").strip(),
                            city=str(values.get("C") or "Unknown city").strip(),
                            observed_at=observed_at,
                            pedestrian_count=_number(values.get("E", "")),
                            # The physical sensor separates cars and large vehicles.
                            # Both are motor vehicles for comparison with SUMO traffic.
                            vehicle_count=(
                                _number(values.get("G", ""))
                                + _number(values.get("H", ""))
                            ),
                        )
                    )
    except (BadZipFile, KeyError, OSError) as exc:
        raise RealWorldDataError(f"Could not read sensor workbook '{filename}'.") from exc
    return tuple(observations)


def _interval_seconds(observations: list[SensorObservation]) -> int:
    differences = [
        int((second.observed_at - first.observed_at).total_seconds())
        for first, second in zip(observations, observations[1:])
        if second.observed_at > first.observed_at
    ]
    valid = [difference for difference in differences if 0 < difference <= 3600]
    return min(valid) if valid else DEFAULT_INTERVAL_SECONDS


def list_real_world_sources() -> list[dict[str, Any]]:
    sources = read_real_world_source_metadata()
    if sources is None:
        raise RealWorldDataError(
            "PostgreSQL is required to query real-world sensor observations."
        )
    return sources


def _value(observation: SensorObservation, subject: RealWorldSubject) -> float:
    return (
        observation.pedestrian_count
        if subject == "pedestrians"
        else observation.vehicle_count
    )


def _raw_points(
    observations: list[SensorObservation],
    *,
    subject: RealWorldSubject,
    start_at: datetime,
    duration_seconds: int,
    interval_seconds: int,
) -> list[dict[str, Any]]:
    end_at = start_at + timedelta(seconds=duration_seconds)
    return [
        {
            "time_seconds": (observation.observed_at - start_at).total_seconds(),
            "flow_per_hour": _value(observation, subject) * 3600 / interval_seconds,
            "interval_count": _value(observation, subject),
            "sample_count": 1,
            "observed_at": observation.observed_at.isoformat(timespec="minutes"),
        }
        for observation in observations
        if start_at <= observation.observed_at < end_at
    ]


def _weekly_average_points(
    observations: list[SensorObservation],
    *,
    subject: RealWorldSubject,
    duration_seconds: int,
    interval_seconds: int,
    start_weekday: int,
    start_time_seconds: int,
) -> list[dict[str, Any]]:
    samples: dict[tuple[int, int], list[float]] = defaultdict(list)
    for observation in observations:
        seconds_of_day = (
            observation.observed_at.hour * 3600
            + observation.observed_at.minute * 60
            + observation.observed_at.second
        )
        samples[(observation.observed_at.weekday(), seconds_of_day)].append(
            _value(observation, subject)
        )

    points = []
    for offset in range(0, duration_seconds, interval_seconds):
        absolute_seconds = start_time_seconds + offset
        day_offset, seconds_of_day = divmod(absolute_seconds, 24 * 3600)
        weekday = (start_weekday + day_offset) % 7
        values = samples.get((weekday, seconds_of_day), [])
        if not values:
            continue
        average_count = sum(values) / len(values)
        points.append({
            "time_seconds": float(offset),
            "flow_per_hour": average_count * 3600 / interval_seconds,
            "interval_count": average_count,
            "sample_count": len(values),
            "weekday": weekday,
            "time_of_day_seconds": seconds_of_day,
        })
    return points


def get_real_world_series(
    *,
    source_id: str,
    mode: RealWorldMode,
    subject: RealWorldSubject,
    duration_seconds: int,
    start_at: datetime | None = None,
    start_weekday: int = 0,
    start_time_seconds: int = 0,
) -> dict[str, Any]:
    database_sources = read_real_world_source_metadata()
    if database_sources is None:
        raise RealWorldDataError(
            "PostgreSQL is required to query real-world sensor observations."
        )
    source = next(
        (item for item in database_sources if item.get("id") == source_id),
        None,
    )
    database_observations = read_real_world_observations(source_id)
    observations = [
        SensorObservation(
            segment_id=str(item["segment_id"]),
            street=str(item["street"]),
            city=str(item["city"]),
            observed_at=item["observed_at"],
            pedestrian_count=float(item["pedestrian_count"]),
            vehicle_count=float(item["vehicle_count"]),
        )
        for item in (database_observations or [])
    ]
    sensor = (
        {
            **source,
            "observations": observations,
        }
        if source is not None
        else None
    )
    if sensor is None:
        raise RealWorldDataError("The selected real-world sensor was not found.")
    observations: list[SensorObservation] = sensor["observations"]
    if not observations:
        raise RealWorldDataError("The selected sensor has no readable observations.")
    interval_seconds = _interval_seconds(observations)
    if mode == "raw":
        effective_start = start_at or observations[0].observed_at
        if effective_start.tzinfo is not None:
            # Workbooks explicitly contain local wall-clock time without a
            # timezone. Treat an API offset as presentation metadata only.
            effective_start = effective_start.replace(tzinfo=None)
        points = _raw_points(
            observations,
            subject=subject,
            start_at=effective_start,
            duration_seconds=duration_seconds,
            interval_seconds=interval_seconds,
        )
        start_label = effective_start.isoformat(timespec="minutes")
    else:
        points = _weekly_average_points(
            observations,
            subject=subject,
            duration_seconds=duration_seconds,
            interval_seconds=interval_seconds,
            start_weekday=start_weekday,
            start_time_seconds=start_time_seconds,
        )
        start_label = None
    return {
        "source": {
            "id": sensor["id"],
            "segment_id": sensor["segment_id"],
            "name": f"{sensor['street']} · Sensor {sensor['segment_id']}",
            "street": sensor["street"],
            "city": sensor["city"],
            "files": sorted(sensor["files"]),
        },
        "mode": mode,
        "subject": subject,
        "duration_seconds": duration_seconds,
        "interval_seconds": interval_seconds,
        "start_at": start_label,
        "start_weekday": start_weekday if mode == "weekly_average" else None,
        "start_time_seconds": start_time_seconds if mode == "weekly_average" else None,
        "units": "agents_per_hour",
        "points": points,
    }
