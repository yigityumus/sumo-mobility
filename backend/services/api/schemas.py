"""HTTP request and response schemas for the API service."""

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


Longitude = Annotated[float, Field(ge=-180, le=180)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
PeakHeight = Annotated[float, Field(ge=0, le=3)]


class BoundaryRequest(BaseModel):
    """A single outer polygon ring using GeoJSON coordinate order: [longitude, latitude]."""

    coordinates: list[tuple[Longitude, Latitude]] = Field(min_length=3)


class OverpassResponse(BaseModel):
    cache_hit: bool
    endpoint: str
    # Overpass fetches still return raw Overpass JSON. Uploaded OSM files use
    # the faster direct GeoJSON collections below.
    osm: dict | None = None
    features: dict | None = None
    boundary: dict | None = None
    stats: dict | None = None


class ParkingEstimateRequest(BaseModel):
    parking_id: str


class DetectorResolveRequest(BaseModel):
    longitude: Longitude
    latitude: Latitude
    radius_metres: float = Field(default=30, ge=5, le=250)


class FourierTrafficParameters(BaseModel):
    """User-facing controls for a periodic, multi-peak arrival profile."""

    peak_count: int = Field(default=2, ge=1, le=16)
    peak_width_hours: float = Field(default=1.5, ge=0.01, le=168)
    harmonics: int = Field(default=6, ge=1, le=16)
    peak_heights: list[PeakHeight] | None = None

    @model_validator(mode="after")
    def normalize_peak_heights(self) -> "FourierTrafficParameters":
        if self.peak_heights is None:
            self.peak_heights = [1.0] * self.peak_count
        elif len(self.peak_heights) != self.peak_count:
            raise ValueError("peak_heights must contain one value per peak")
        return self


class ParkingChoiceWeights(BaseModel):
    drive_time: float = Field(default=0.8, ge=0, le=10)
    walk_time: float = Field(default=1.0, ge=0, le=10)
    capacity: float = Field(default=0.8, ge=0, le=10)
    absolute_free_space: float = Field(default=1.3, ge=0, le=10)
    relative_free_space: float = Field(default=1.5, ge=0, le=10)


class ParkingChoiceParameters(BaseModel):
    """Editable assumptions for the behavioral parking-search model."""

    knowledge_probability: float = Field(default=0.50, ge=0, le=1)
    uninformed_occupancy_mean: float = Field(default=0.60, ge=0, le=1)
    uninformed_occupancy_stddev: float = Field(default=0.15, ge=0, le=1)
    frustration_step: float = Field(default=0.35, ge=0, le=2)
    stochastic_scale: float = Field(default=0.00, ge=0, le=5)
    weights: ParkingChoiceWeights = Field(default_factory=ParkingChoiceWeights)


class VehicleOriginAllocation(BaseModel):
    origin_id: str = Field(min_length=1, max_length=200)
    vehicle_count: int = Field(ge=0, le=1_000_000)


class SimulationRunRequest(BaseModel):
    vehicle_count: int = Field(ge=0, le=1_000_000)
    pedestrian_count: int = Field(ge=0, le=1_000_000)
    total_people: int | None = Field(default=None, ge=1, le=1_000_000)
    vehicle_percentage: int | None = Field(default=None, ge=0, le=100)
    building_classification_id: str | None = None
    residential_pedestrian_count: int | None = Field(default=None, ge=0, le=1_000_000)
    public_transport_pedestrian_count: int | None = Field(default=None, ge=0, le=1_000_000)
    duration_hours: int = Field(ge=1, le=168)
    simulation_start_at: datetime | None = None
    simulation_timezone: str = Field(default="Europe/Paris", min_length=1, max_length=64)
    mode: Literal["sumo", "sumo-gui"] = "sumo"
    pedestrian_model: Literal["striping", "nonInteracting"] = "striping"
    diagnostic_tracing: bool = False
    random_seed: int | None = Field(default=None, ge=1, le=2_147_483_646)
    vehicle_traffic_model: Literal["constant", "linear", "normal", "fourier"] = "normal"
    pedestrian_traffic_model: Literal["constant", "linear", "normal", "fourier"] = "linear"
    vehicle_fourier_parameters: FourierTrafficParameters = Field(default_factory=FourierTrafficParameters)
    pedestrian_fourier_parameters: FourierTrafficParameters = Field(default_factory=FourierTrafficParameters)
    parking_choice: ParkingChoiceParameters = Field(default_factory=ParkingChoiceParameters)
    vehicle_origin_allocations: list[VehicleOriginAllocation] | None = None

    @field_validator("simulation_timezone")
    @classmethod
    def validate_simulation_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown simulation timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def require_demand(self) -> "SimulationRunRequest":
        if self.vehicle_count == 0 and self.pedestrian_count == 0:
            raise ValueError("At least one vehicle or pedestrian is required.")
        calculated_total = self.vehicle_count + self.pedestrian_count
        if self.total_people is None:
            self.total_people = calculated_total
        elif self.total_people != calculated_total:
            raise ValueError("total_people must equal vehicle_count + pedestrian_count")
        calculated_percentage = round(self.vehicle_count / calculated_total * 100)
        if self.vehicle_percentage is not None and self.vehicle_percentage != calculated_percentage:
            raise ValueError("vehicle_percentage must match vehicle_count / total_people")
        self.vehicle_percentage = calculated_percentage
        if (
            self.residential_pedestrian_count is None
            and self.public_transport_pedestrian_count is None
        ):
            # Backward-compatible default for clients created before source
            # allocation was exposed on the simulation form.
            self.residential_pedestrian_count = 0
            self.public_transport_pedestrian_count = self.pedestrian_count
        else:
            self.residential_pedestrian_count = int(
                self.residential_pedestrian_count or 0
            )
            self.public_transport_pedestrian_count = int(
                self.public_transport_pedestrian_count or 0
            )
        if (
            self.residential_pedestrian_count
            + self.public_transport_pedestrian_count
            != self.pedestrian_count
        ):
            raise ValueError(
                "Residential and public-transport pedestrian counts must add up "
                "to pedestrian_count. Parked-car drivers are derived from vehicle_count."
            )
        if self.vehicle_origin_allocations is not None:
            origin_ids = [item.origin_id for item in self.vehicle_origin_allocations]
            if len(origin_ids) != len(set(origin_ids)):
                raise ValueError("Vehicle origin allocations must use unique origin IDs")
            allocated_vehicles = sum(
                item.vehicle_count for item in self.vehicle_origin_allocations
            )
            if allocated_vehicles != self.vehicle_count:
                raise ValueError(
                    "Vehicle origin allocation counts must add up to vehicle_count "
                    f"({allocated_vehicles} != {self.vehicle_count})"
                )
        return self


class FlowCalibrationRequest(BaseModel):
    """A frozen simulation setup whose Fourier percentages evolve sequentially."""

    name: str = Field(default="Flow calibration", min_length=1, max_length=120)
    real_world_source_id: str = Field(min_length=1, max_length=120)
    detector_logical_id: str = Field(min_length=1, max_length=200)
    subjects: list[Literal["vehicles", "pedestrians"]] = Field(
        default_factory=lambda: ["vehicles"], min_length=1, max_length=2
    )
    iterations: int = Field(default=10, ge=1, le=100)
    step_percentage: float = Field(default=1.0, ge=0.1, le=100)
    simulation: SimulationRunRequest

    @model_validator(mode="after")
    def require_locked_fourier_profiles(self) -> "FlowCalibrationRequest":
        if len(set(self.subjects)) != len(self.subjects):
            raise ValueError("subjects must not contain duplicates")
        if self.simulation.mode != "sumo":
            raise ValueError("Flow calibration requires background SUMO mode")
        if self.simulation.simulation_start_at is None:
            raise ValueError("Flow calibration requires a fixed simulation start date and time")
        if (
            self.simulation.vehicle_traffic_model != "fourier"
            or self.simulation.pedestrian_traffic_model != "fourier"
        ):
            raise ValueError("Both traffic models must be Fourier for flow calibration")
        return self
