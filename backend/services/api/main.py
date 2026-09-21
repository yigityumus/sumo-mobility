"""HTTP API service entry point."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from domain.analytics.service import (
    AnalyticsError,
    get_analytics,
    list_available_analytics_runs,
)
from domain.calibration.service import (
    FlowCalibrationError,
    create_flow_calibration,
    list_flow_calibration_sessions,
)
from domain.models.detectors import resolve_model_detector_lanes
from domain.models.exports import create_model_zip, sanitize_export_name
from domain.models.osm import OsmXmlError, parse_osm_xml_to_area_feature_collections
from domain.models.overpass import (
    OverpassError,
    TTLCache,
    fetch_area_features,
    fetch_buildings,
    fetch_osm_extract,
    normalize_ring,
)
from domain.models.parking_capacity import (
    estimate_model_parking,
    estimate_model_unknown_parkings,
)
from domain.models.store import (
    ModelStoreError,
    _model_dir,
    delete_model,
    list_models,
    read_model,
    read_source_osm,
    save_model,
    source_osm_filename,
    write_source_osm,
)
from domain.reference_data.ingestion import (
    ReferenceDataError,
    list_reference_datasets,
    sync_reference_data,
    upload_reference_dataset,
)
from domain.reference_data.series import (
    RealWorldDataError,
    get_real_world_series,
    list_real_world_sources,
)
from domain.simulations.service import (
    SimulationRunActiveError,
    SimulationRunNotFoundError,
    SimulationRunStopError,
    create_simulation_run,
    delete_simulation_run,
    execute_simulation_run,
    list_simulation_runs,
    mark_simulation_queue_failure,
    request_simulation_stop,
)
from shared.config import get_settings
from shared.database import (
    close_database,
    configure_database,
    database_status,
    initialize_database,
    persist_object_artifacts,
    read_all_simulation_runs,
    sync_existing_storage,
)
from shared.message_broker import MessageBrokerError, broker_status, publish_message
from shared.object_storage import (
    configure_object_storage,
    configure_reference_object_storage,
    get_object_storage,
    initialize_object_storage,
    initialize_reference_object_storage,
    object_storage_status,
    reference_object_storage_status,
    run_object_path,
)
from .schemas import (
    BoundaryRequest,
    DetectorResolveRequest,
    FlowCalibrationRequest,
    OverpassResponse,
    ParkingEstimateRequest,
    SimulationRunRequest,
)

settings = get_settings()
cache = TTLCache(settings.cache_ttl_seconds)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.model_storage_dir.mkdir(parents=True, exist_ok=True)
    configure_object_storage(
        settings.object_storage_endpoint,
        settings.object_storage_access_key,
        settings.object_storage_secret_key,
        settings.object_storage_bucket,
        secure=settings.object_storage_secure,
        prefix=settings.object_storage_prefix,
    )
    configure_reference_object_storage(
        settings.object_storage_endpoint,
        settings.object_storage_access_key,
        settings.object_storage_secret_key,
        settings.reference_data_bucket,
        secure=settings.object_storage_secure,
        prefix=settings.reference_data_prefix,
    )
    await asyncio.to_thread(initialize_object_storage)
    await asyncio.to_thread(initialize_reference_object_storage)
    configure_database(
        settings.database_url,
        minimum_pool_size=settings.database_pool_min_size,
        maximum_pool_size=settings.database_pool_max_size,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    await asyncio.to_thread(initialize_database)
    storage = get_object_storage()
    if storage is not None:
        await asyncio.to_thread(storage.download_metadata, settings.model_storage_dir)
    sync_counts = await asyncio.to_thread(
        sync_existing_storage,
        settings.model_storage_dir,
    )
    if settings.database_url:
        logger.info(
            "PostgreSQL storage sync completed: %s models, %s runs, %s artifacts",
            sync_counts["models"],
            sync_counts["runs"],
            sync_counts["artifacts"],
        )
    if storage is not None:
        indexed_objects = 0
        for record in read_all_simulation_runs() or []:
            model_id = str(record.get("model_id") or "")
            run_id = str(record.get("id") or "")
            objects = await asyncio.to_thread(
                storage.list_prefix,
                run_object_path(model_id, run_id),
            )
            indexed_objects += await asyncio.to_thread(
                persist_object_artifacts,
                run_id,
                [item.__dict__ for item in objects],
            )
        logger.info("MinIO artifact index synchronized: %s objects", indexed_objects)
    reference_sync = await asyncio.to_thread(sync_reference_data)
    logger.info(
        "Reference-data sync completed: %s discovered, %s ingested, %s skipped, %s failed",
        reference_sync["discovered"],
        reference_sync["ingested"],
        reference_sync["skipped"],
        reference_sync["failed"],
    )
    try:
        yield
    finally:
        await asyncio.to_thread(close_database)


app = FastAPI(
    title=settings.app_name,
    version="0.12.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "database": await asyncio.to_thread(database_status),
        "message_broker": await asyncio.to_thread(
            broker_status,
            settings.rabbitmq_url,
        ),
        "object_storage": await asyncio.to_thread(object_storage_status),
        "reference_data_storage": await asyncio.to_thread(
            reference_object_storage_status
        ),
    }


@app.get("/api/analytics")
async def api_list_analytics_runs() -> list[dict]:
    return list_available_analytics_runs(settings.model_storage_dir)


@app.get("/api/simulations/queue")
async def api_simulation_queue_status() -> dict:
    records = read_all_simulation_runs() or []
    running_count = sum(record.get("status") == "running" for record in records)
    waiting_count = sum(
        record.get("status") == "queued" and not record.get("stop_requested_at")
        for record in records
    )
    return {
        "concurrency": settings.simulation_worker_concurrency,
        "running_count": running_count,
        "waiting_count": waiting_count,
        "available_slots": max(
            settings.simulation_worker_concurrency - running_count,
            0,
        ),
    }


@app.get("/api/analytics/real-world/sources")
async def api_list_real_world_sources() -> list[dict]:
    try:
        return await asyncio.to_thread(list_real_world_sources)
    except RealWorldDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/analytics/real-world/datasets")
async def api_list_real_world_datasets() -> list[dict]:
    try:
        return await asyncio.to_thread(list_reference_datasets)
    except ReferenceDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/analytics/real-world/datasets", status_code=201)
async def api_upload_real_world_dataset(file: UploadFile = File(...)) -> dict:
    maximum_bytes = settings.max_reference_upload_mb * 1024 * 1024
    content = await file.read(maximum_bytes + 1)
    try:
        return await asyncio.to_thread(
            upload_reference_dataset,
            content,
            file.filename or "dataset.xlsx",
            maximum_bytes=maximum_bytes,
        )
    except (RealWorldDataError, ReferenceDataError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/analytics/real-world/series")
async def api_get_real_world_series(
    source_id: str,
    mode: str = Query(default="raw", pattern="^(raw|weekly_average)$"),
    subject: str = Query(default="vehicles", pattern="^(vehicles|pedestrians)$"),
    duration_seconds: int = Query(ge=900, le=604800),
    start_at: datetime | None = None,
    start_weekday: int = Query(default=0, ge=0, le=6),
    start_time_seconds: int = Query(default=0, ge=0, le=86399),
) -> dict:
    try:
        return await asyncio.to_thread(
            get_real_world_series,
            source_id=source_id,
            mode=mode,
            subject=subject,
            duration_seconds=duration_seconds,
            start_at=start_at,
            start_weekday=start_weekday,
            start_time_seconds=start_time_seconds,
        )
    except RealWorldDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/analytics/{run_id}")
async def api_get_analytics(run_id: str) -> dict:
    try:
        return get_analytics(settings.model_storage_dir, run_id)
    except AnalyticsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/features", response_model=OverpassResponse)
async def area_features(request: BoundaryRequest) -> OverpassResponse:
    """Return OSM building and amenity=parking polygons inside the boundary."""
    try:
        ring = normalize_ring(request.coordinates, settings)
        payload, endpoint, cache_hit = await fetch_area_features(ring, settings, cache)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OverpassError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return OverpassResponse(
        cache_hit=cache_hit,
        endpoint=endpoint,
        osm=payload,
    )


@app.post("/api/buildings", response_model=OverpassResponse)
async def buildings(request: BoundaryRequest) -> OverpassResponse:
    """Backward-compatible building-only endpoint."""
    try:
        ring = normalize_ring(request.coordinates, settings)
        payload, endpoint, cache_hit = await fetch_buildings(ring, settings, cache)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OverpassError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return OverpassResponse(
        cache_hit=cache_hit,
        endpoint=endpoint,
        osm=payload,
    )


@app.post("/api/osm-upload", response_model=OverpassResponse)
async def osm_upload(file: UploadFile = File(...)) -> OverpassResponse:
    """Parse an uploaded .osm/.osm.xml/.osm.xml.gz file into Overpass-like JSON."""
    content = await file.read()
    max_bytes = settings.max_osm_upload_mb * 1024 * 1024

    if not content:
        raise HTTPException(status_code=400, detail="The uploaded OSM file is empty.")

    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"The uploaded file is larger than {settings.max_osm_upload_mb} MB.",
        )

    try:
        payload = parse_osm_xml_to_area_feature_collections(content)
    except OsmXmlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return OverpassResponse(
        cache_hit=False,
        endpoint=f"uploaded-file:{file.filename or 'unnamed.osm'}",
        features={
            "buildings": payload["buildings"],
            "parking_areas": payload["parking_areas"],
        },
        boundary=payload.get("boundary"),
        stats=payload["stats"],
    )


@app.post("/api/osm-extract")
async def osm_extract(request: BoundaryRequest) -> Response:
    """Download a reusable OSM XML extract for the selected area boundary."""
    try:
        ring = normalize_ring(request.coordinates, settings)
        xml_text, endpoint = await fetch_osm_extract(ring, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OverpassError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    filename = "area_osm_extract.osm.xml"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Overpass-Endpoint": endpoint,
    }

    return Response(
        content=xml_text,
        media_type="application/xml; charset=utf-8",
        headers=headers,
    )


def _parse_model_json(model_json: str) -> dict:
    try:
        model = json.loads(model_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="model_json is not valid JSON.") from exc
    if not isinstance(model, dict):
        raise HTTPException(status_code=400, detail="model_json must contain a JSON object.")
    if not str(model.get("id") or "").strip():
        raise HTTPException(status_code=400, detail="Model id is required.")
    return model


def _boundary_coordinates_from_model(model: dict) -> list | None:
    geometry = (model.get("boundaryFeature") or {}).get("geometry") or {}
    if geometry.get("type") != "Polygon":
        return None
    coordinates = geometry.get("coordinates") or []
    if not coordinates or not isinstance(coordinates[0], list):
        return None
    return coordinates[0]


async def _ensure_model_source_osm(model: dict) -> bytes:
    model_id = str(model.get("id"))
    cached = read_source_osm(settings.model_storage_dir, model_id)
    if cached is not None:
        return cached

    coordinates = _boundary_coordinates_from_model(model)
    if not coordinates:
        raise HTTPException(
            status_code=400,
            detail="No source OSM is cached and this model does not have a valid boundary to fetch one.",
        )

    try:
        ring = normalize_ring(coordinates, settings)
        xml_text, _endpoint = await fetch_osm_extract(ring, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OverpassError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    content = xml_text.encode("utf-8")
    write_source_osm(settings.model_storage_dir, model_id, content)
    model["sourceOsmCached"] = True
    save_model(settings.model_storage_dir, model)
    return content


@app.get("/api/models")
async def api_list_models() -> list[dict]:
    return list_models(settings.model_storage_dir)


@app.post("/api/models")
async def api_save_model(
    model_json: str = Form(...),
    source_osm_file: UploadFile | None = File(None),
) -> dict:
    model = _parse_model_json(model_json)
    source_bytes = await source_osm_file.read() if source_osm_file is not None else None
    try:
        saved_model = save_model(
            settings.model_storage_dir,
            model,
            source_osm_bytes=source_bytes,
            source_osm_filename=source_osm_file.filename if source_osm_file is not None else None,
        )
    except ModelStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return saved_model


@app.get("/api/models/{model_id}")
async def api_get_model(model_id: str) -> dict:
    model = read_model(settings.model_storage_dir, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    return model


@app.delete("/api/models/{model_id}", status_code=204)
async def api_delete_model(model_id: str) -> Response:
    delete_model(settings.model_storage_dir, model_id)
    return Response(status_code=204)


@app.get("/api/models/{model_id}/source-osm")
async def api_get_model_source_osm(model_id: str) -> Response:
    model = read_model(settings.model_storage_dir, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    content = await _ensure_model_source_osm(model)
    filename = source_osm_filename(model)
    return Response(
        content=content,
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/models/{model_id}/export")
async def api_export_model(
    model_id: str,
    osm: bool = True,
    buildings: bool = False,
    parking_areas: bool = False,
    model_config: bool = False,
) -> Response:
    model = read_model(settings.model_storage_dir, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    if not any((osm, buildings, parking_areas, model_config)):
        raise HTTPException(status_code=400, detail="Select at least one file to export.")
    source_osm = await _ensure_model_source_osm(model) if osm else None
    filename = source_osm_filename(model)
    zip_bytes = create_model_zip(
        model,
        source_osm,
        filename,
        include_osm=osm,
        include_buildings=buildings,
        include_parking_areas=parking_areas,
        include_model_config=model_config,
    )
    export_name = f"{sanitize_export_name(model.get('name'))}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{export_name}"'},
    )


@app.post("/api/models/{model_id}/parking/estimate-capacity")
async def api_estimate_parking_capacity(model_id: str, request: ParkingEstimateRequest) -> dict:
    model = read_model(settings.model_storage_dir, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    source_osm = await _ensure_model_source_osm(model)
    try:
        updated_model, result = estimate_model_parking(model, request.parking_id, source_osm)
    except (ValueError, OsmXmlError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_model(settings.model_storage_dir, updated_model)
    return {"model": updated_model, "result": result}


@app.post("/api/models/{model_id}/parking/estimate-all-unknown")
async def api_estimate_all_unknown_parking_capacities(model_id: str) -> dict:
    model = read_model(settings.model_storage_dir, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    source_osm = await _ensure_model_source_osm(model)
    try:
        updated_model, summary = estimate_model_unknown_parkings(model, source_osm)
    except OsmXmlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_model(settings.model_storage_dir, updated_model)
    return {"model": updated_model, "summary": summary}


@app.post("/api/models/{model_id}/detectors/resolve")
async def api_resolve_detector_lanes(model_id: str, request: DetectorResolveRequest) -> dict:
    model = read_model(settings.model_storage_dir, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    await _ensure_model_source_osm(model)
    try:
        return await asyncio.to_thread(
            resolve_model_detector_lanes,
            _model_dir(settings.model_storage_dir, model_id),
            request.longitude,
            request.latitude,
            request.radius_metres,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/models/{model_id}/simulations")
async def api_list_simulation_runs(model_id: str) -> list[dict]:
    if read_model(settings.model_storage_dir, model_id) is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    return list_simulation_runs(settings.model_storage_dir, model_id)


@app.get("/api/models/{model_id}/flow-calibrations")
async def api_list_flow_calibrations(model_id: str) -> list[dict]:
    if read_model(settings.model_storage_dir, model_id) is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    return await asyncio.to_thread(list_flow_calibration_sessions, model_id)


@app.post("/api/models/{model_id}/flow-calibrations", status_code=202)
async def api_start_flow_calibration(
    model_id: str,
    request: FlowCalibrationRequest,
) -> dict:
    model = read_model(settings.model_storage_dir, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    await _ensure_model_source_osm(model)
    source_ids = {str(item.get("id")) for item in await asyncio.to_thread(list_real_world_sources)}
    if request.real_world_source_id not in source_ids:
        raise HTTPException(status_code=400, detail="The selected real-world sensor was not found.")
    detector = next((
        item for item in model.get("detectors") or []
        if str(item.get("id")) == request.detector_logical_id
    ), None)
    if detector is None or str(detector.get("type")) != "e3":
        raise HTTPException(status_code=400, detail="Select a saved E3 detector.")
    detected_subjects = set(detector.get("detects") or ["vehicles"])
    missing_subjects = set(request.subjects) - detected_subjects
    if missing_subjects:
        raise HTTPException(
            status_code=400,
            detail="The selected detector does not measure: " + ", ".join(sorted(missing_subjects)),
        )
    try:
        return await asyncio.to_thread(
            create_flow_calibration,
            settings.model_storage_dir,
            model,
            name=request.name,
            source_id=request.real_world_source_id,
            detector_logical_id=request.detector_logical_id,
            subjects=list(request.subjects),
            total_iterations=request.iterations,
            step_percentage=request.step_percentage,
            simulation_request=request.simulation.model_dump(),
            rabbitmq_url=settings.rabbitmq_url or "",
            simulation_queue_name=settings.simulation_queue_name,
        )
    except (FlowCalibrationError, ModelStoreError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/models/{model_id}/simulations", status_code=202)
async def api_start_simulation_run(
    model_id: str,
    request: SimulationRunRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    model = read_model(settings.model_storage_dir, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found.")

    # A simulation is reproducible only when its exact source map can be
    # snapshotted with the run. Boundary-based models are fetched here if the
    # OSM extract was not already cached when the model was saved.
    await _ensure_model_source_osm(model)

    try:
        record = create_simulation_run(
            settings.model_storage_dir,
            model,
            vehicle_count=request.vehicle_count,
            pedestrian_count=request.pedestrian_count,
            duration_hours=request.duration_hours,
            mode=request.mode,
            vehicle_traffic_model=request.vehicle_traffic_model,
            pedestrian_traffic_model=request.pedestrian_traffic_model,
            vehicle_fourier_parameters=request.vehicle_fourier_parameters.model_dump(),
            pedestrian_fourier_parameters=request.pedestrian_fourier_parameters.model_dump(),
            parking_choice=request.parking_choice.model_dump(),
            total_people=request.total_people,
            vehicle_percentage=request.vehicle_percentage,
            building_classification_id=request.building_classification_id,
            residential_pedestrian_count=request.residential_pedestrian_count or 0,
            public_transport_pedestrian_count=(
                request.public_transport_pedestrian_count or 0
            ),
            simulation_start_at=request.simulation_start_at,
            simulation_timezone=request.simulation_timezone,
            pedestrian_model=request.pedestrian_model,
            diagnostic_tracing=request.diagnostic_tracing,
            random_seed=request.random_seed,
            vehicle_origin_allocations=[
                item.model_dump() for item in request.vehicle_origin_allocations
            ] if request.vehicle_origin_allocations is not None else None,
        )
    except ModelStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if settings.rabbitmq_url:
        try:
            await asyncio.to_thread(
                publish_message,
                settings.rabbitmq_url,
                settings.simulation_queue_name,
                {
                    "type": "simulation.run.requested",
                    "model_id": model_id,
                    "run_id": record["id"],
                },
            )
        except MessageBrokerError as exc:
            reason = "The simulation could not be queued because RabbitMQ is unavailable."
            await asyncio.to_thread(
                mark_simulation_queue_failure,
                settings.model_storage_dir,
                model_id,
                record["id"],
                reason,
            )
            raise HTTPException(status_code=503, detail=reason) from exc
    else:
        # Preserve the simple local-development mode. Container deployments set
        # RABBITMQ_URL and therefore never execute a long SUMO job in the API.
        background_tasks.add_task(
            execute_simulation_run,
            settings.model_storage_dir,
            model_id,
            record["id"],
        )
    # Queue position is derived across every model, so return the same enriched
    # representation that the history endpoint uses.
    queued_record = next(
        (
            item
            for item in list_simulation_runs(settings.model_storage_dir, model_id)
            if item.get("id") == record["id"]
        ),
        record,
    )
    return queued_record


@app.delete("/api/models/{model_id}/simulations/{run_id}", status_code=204)
async def api_delete_simulation_run(model_id: str, run_id: str) -> Response:
    if read_model(settings.model_storage_dir, model_id) is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    try:
        delete_simulation_run(settings.model_storage_dir, model_id, run_id)
    except SimulationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SimulationRunActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


@app.post("/api/models/{model_id}/simulations/{run_id}/stop", status_code=202)
async def api_stop_simulation_run(model_id: str, run_id: str) -> dict:
    if read_model(settings.model_storage_dir, model_id) is None:
        raise HTTPException(status_code=404, detail="Model not found.")
    try:
        return request_simulation_stop(
            settings.model_storage_dir,
            model_id,
            run_id,
        )
    except SimulationRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SimulationRunStopError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _safe_frontend_file(frontend_root: Path, requested_path: str) -> Path | None:
    """Return a requested compiled frontend file without allowing traversal."""
    candidate = (frontend_root / requested_path).resolve()
    if not candidate.is_relative_to(frontend_root) or not candidate.is_file():
        return None
    return candidate


if settings.frontend_dist_dir.is_dir():
    _frontend_root = settings.frontend_dist_dir.resolve()
    _frontend_index = _frontend_root / "index.html"

    @app.get("/{frontend_path:path}", include_in_schema=False)
    async def frontend_spa(frontend_path: str) -> FileResponse:
        """Serve compiled assets and fall back to React for client-side routes."""
        if frontend_path == "api" or frontend_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found.")

        requested_file = _safe_frontend_file(_frontend_root, frontend_path)
        if requested_file is not None:
            return FileResponse(requested_file)
        if not _frontend_index.is_file():
            raise HTTPException(status_code=404, detail="Frontend build not found.")
        return FileResponse(_frontend_index)
