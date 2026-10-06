from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    feature_count: int
    crs: str | None
    status: str
    error: str | None = None
    bbox: list[float] | None = None
    created_at: datetime


class FeatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index: int
    layer: str | None
    geometry_type: str | None
    geometry: dict[str, Any] | None
    crs: str | None
    properties: dict[str, Any]
    location: str | None = None


class MeasurementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feature_index: int
    layer: str | None
    geometry_type: str | None
    measurement_supported: bool
    area_m2: float | None = None
    perimeter_m: float | None = None
    length_m: float | None = None
    projected_crs: str | None = None
    warning: str | None = None


class MeasurementSummary(BaseModel):
    measurable_features: int
    unmeasurable_features: int
    total_area_m2: float
    total_length_m: float


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class FeaturesResponse(Page):
    file_id: str
    features: list[FeatureOut]


class MeasurementsResponse(Page):
    file_id: str
    summary: MeasurementSummary
    measurements: list[MeasurementOut]
