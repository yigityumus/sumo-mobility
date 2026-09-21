"""Detector preview-network caching and lane resolution for model editing."""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from sumo.scenario.detectors.lanes import resolve_detector_lanes
from sumo.scenario.network.build import build_network
from sumo.scenario.parking.lane_discovery import load_sumo_network


PREVIEW_LOCK = Lock()


def resolve_model_detector_lanes(model_directory: Path, longitude: float, latitude: float, radius_metres: float) -> dict:
    source_path = model_directory / "source.osm.xml"
    if not source_path.is_file():
        raise ValueError("Save the model with its source OSM map before placing detectors.")
    cache_directory = model_directory / ".cache" / "detectors"
    network_path = cache_directory / "model.net.xml.gz"
    compressed_osm_path = cache_directory / "source.osm.xml.gz"
    with PREVIEW_LOCK:
        stale = not network_path.is_file() or network_path.stat().st_mtime < source_path.stat().st_mtime
        if stale:
            cache_directory.mkdir(parents=True, exist_ok=True)
            build_network(
                source_path,
                force=True,
                with_polygons=False,
                poly_typemap=None,
                network_output=network_path,
                osm_output=compressed_osm_path,
                allow_passenger_on_delivery=True,
            )
    network = load_sumo_network(network_path)
    candidates = resolve_detector_lanes(
        network,
        longitude,
        latitude,
        radius_metres=radius_metres,
        allowed_classes=("passenger", "pedestrian"),
    )
    if not candidates:
        raise ValueError(
            f"No vehicle- or pedestrian-accessible SUMO lane was found within {radius_metres:g} m. "
            "Click closer to a road or increase the search radius."
        )
    return {"candidates": candidates, "network_cached": not stale}
