import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_db
from app.models import Feature, UploadedFile
from app.services.processing import process_upload

router = APIRouter(prefix="/api/files", tags=["files"])


def _get_file_or_404(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(404, "File not found")
    return record


@router.post("/", response_model=schemas.FileOut, status_code=201)
def upload_file(
    file: UploadFile = File(...),
    geocode: bool = Query(False, description="Reverse-geocode each feature (slower, ~1 s per feature)"),
    db: Session = Depends(get_db),
):
    """Upload a .kml or a .zip containing a Shapefile; processed synchronously."""
    return process_upload(db, file, geocode=geocode)


@router.get("/{file_id}/", response_model=schemas.FileOut)
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _get_file_or_404(db, file_id)


@router.get("/{file_id}/features/", response_model=schemas.FeaturesResponse)
def get_features(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    _get_file_or_404(db, file_id)
    q = select(Feature).where(Feature.file_id == file_id).order_by(Feature.index)
    total = db.scalar(select(func.count()).select_from(Feature).where(Feature.file_id == file_id))
    rows = db.scalars(q.limit(limit).offset(offset)).all()
    return {"file_id": file_id, "total": total, "limit": limit, "offset": offset, "features": rows}


@router.get("/{file_id}/geojson/")
def get_geojson(file_id: str, db: Session = Depends(get_db)):
    """Download all features as a GeoJSON FeatureCollection with measurements in properties."""
    record = _get_file_or_404(db, file_id)
    rows = db.scalars(
        select(Feature).where(Feature.file_id == file_id).order_by(Feature.index)
    ).all()

    features = []
    for r in rows:
        props = {**(r.properties or {})}
        props["_index"] = r.index
        props["_layer"] = r.layer
        props["_geometry_type"] = r.geometry_type
        props["_location"] = r.location
        props["_area_m2"] = r.area_m2
        props["_perimeter_m"] = r.perimeter_m
        props["_length_m"] = r.length_m
        props["_projected_crs"] = r.projected_crs
        props["_warning"] = r.warning
        features.append({"type": "Feature", "geometry": r.geometry, "properties": props})

    collection = {"type": "FeatureCollection", "features": features}
    if record.bbox:
        collection["bbox"] = record.bbox

    return Response(
        content=json.dumps(collection),
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{record.filename}.geojson"'},
    )


@router.get("/{file_id}/measurements/", response_model=schemas.MeasurementsResponse)
def get_measurements(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    _get_file_or_404(db, file_id)
    base = Feature.file_id == file_id

    total = db.scalar(select(func.count()).select_from(Feature).where(base))
    agg = db.execute(
        select(
            func.count().filter(Feature.measurement_supported.is_(True)),
            func.coalesce(func.sum(Feature.area_m2), 0.0),
            func.coalesce(func.sum(Feature.length_m), 0.0),
        ).where(base)
    ).one()
    rows = db.scalars(
        select(Feature).where(base).order_by(Feature.index).limit(limit).offset(offset)
    ).all()

    return {
        "file_id": file_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": {
            "measurable_features": agg[0],
            "unmeasurable_features": total - agg[0],
            "total_area_m2": round(agg[1], 3),
            "total_length_m": round(agg[2], 3),
        },
        "measurements": [
            schemas.MeasurementOut(
                feature_index=r.index,
                layer=r.layer,
                geometry_type=r.geometry_type,
                measurement_supported=r.measurement_supported,
                area_m2=r.area_m2,
                perimeter_m=r.perimeter_m,
                length_m=r.length_m,
                projected_crs=r.projected_crs,
                warning=r.warning,
            )
            for r in rows
        ],
    }
