"""Configuration shared by all backend services."""

from functools import lru_cache
from pathlib import Path
from tempfile import gettempdir

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "SUMO Area Builder API"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Keep multiple public instances because every public Overpass service can
    # temporarily reject, rate-limit, or time out. private.coffee is the
    # successor to the former overpass.kumi.systems endpoint.
    overpass_endpoints: str = (
        "https://overpass.private.coffee/api/interpreter,"
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter,"
        "https://overpass-api.de/api/interpreter"
    )
    osm_user_agent: str = (
        "sumo-area-builder/0.2 "
        "(local development; set OSM_USER_AGENT in backend/.env)"
    )
    osm_map_api_endpoint: str = "https://api.openstreetmap.org/api/0.6/map"
    osm_map_max_bbox_area_degrees: float = 0.01
    overpass_timeout_seconds: float = 90.0
    # Bound all POST/GET attempts against one replica so a slow endpoint cannot
    # consume the gateway's entire request window before backups are tried.
    overpass_endpoint_budget_seconds: float = 45.0
    cache_ttl_seconds: int = 600
    max_boundary_vertices: int = 500
    max_boundary_span_degrees: float = 0.25
    max_osm_upload_mb: int = 75
    # SUMO and a few export/analytics operations require local files while
    # they run. Persistent state belongs in PostgreSQL and object storage; this
    # directory is only an ephemeral per-container workspace.
    model_storage_dir: Path = Path(gettempdir()) / "campus-simulation" / "models"
    frontend_dist_dir: Path = BACKEND_ROOT.parent / "frontend" / "dist"
    database_url: str | None = None
    database_pool_min_size: int = 1
    database_pool_max_size: int = 5
    database_connect_timeout_seconds: int = 10
    rabbitmq_url: str | None = None
    simulation_queue_name: str = "simulation.jobs"
    simulation_worker_concurrency: int = Field(default=2, ge=1, le=8)
    analytics_queue_name: str = "analytics.jobs"
    object_storage_endpoint: str | None = None
    object_storage_access_key: str | None = None
    object_storage_secret_key: str | None = None
    object_storage_bucket: str = "campus-simulation"
    object_storage_secure: bool = False
    object_storage_prefix: str = "models"
    reference_data_bucket: str = "campus-reference-data"
    reference_data_prefix: str = "raw"
    max_reference_upload_mb: int = 100

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("model_storage_dir", "frontend_dist_dir", mode="after")
    @classmethod
    def resolve_backend_relative_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_ROOT / value).resolve()

    @property
    def origins(self) -> list[str]:
        return [value.strip() for value in self.allowed_origins.split(",") if value.strip()]

    @property
    def endpoints(self) -> list[str]:
        return [value.strip() for value in self.overpass_endpoints.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
