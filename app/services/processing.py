"""Upload -> parse -> measure -> persist."""
import json
import tempfile
from pathlib import Path

import shapely
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import MAX_UPLOAD_BYTES
from app.errors import FileTooLargeError, GeoFileError
from app.models import Feature, UploadedFile
from app.services.crs import crs_label
from app.services.geocode import geocode_feature
from app.services.measure import measure_geometry
from app.services.reader import detect_type, parse_file

CHUNK = 1024 * 1024


def _save_upload(upload: UploadFile, dest: Path) -> None:
    size = 0
    with open(dest, "wb") as out:
        while chunk := upload.file.read(CHUNK):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise FileTooLargeError(f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
            out.write(chunk)
    if size == 0:
        raise GeoFileError("Uploaded file is empty")


def process_upload(db: Session, upload: UploadFile, geocode: bool = False) -> UploadedFile:
    filename = Path(upload.filename or "upload").name
    file_type = detect_type(filename)  # raises 415 before anything is stored

    record = UploadedFile(filename=filename, file_type=file_type, status="PROCESSING")
    db.add(record)
    db.commit()

    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ("upload.kml" if file_type == "kml" else "upload.zip")
            _save_upload(upload, path)
            parsed = parse_file(path, file_type)

        rows = []
        for f in parsed.features:
            m = measure_geometry(f.geometry, f.crs)
            has_geom = f.geometry is not None and not f.geometry.is_empty
            location = geocode_feature(f.geometry, f.crs) if (geocode and has_geom) else None
            rows.append(
                Feature(
                    file_id=record.id,
                    index=f.index,
                    layer=f.layer,
                    geometry_type=f.geometry.geom_type if f.geometry is not None else None,
                    geometry=_to_geojson(f.geometry) if has_geom else None,
                    crs=crs_label(f.crs),
                    properties=f.properties,
                    location=location,
                    measurement_supported=m.supported,
                    area_m2=m.area_m2,
                    perimeter_m=m.perimeter_m,
                    length_m=m.length_m,
                    projected_crs=m.projected_crs,
                    warning=m.warning,
                )
            )
        db.add_all(rows)
        record.crs = parsed.crs_label
        record.feature_count = len(rows)
        record.status = "COMPLETED"
        db.commit()
    except GeoFileError as exc:
        db.rollback()
        record.status = "FAILED"
        record.error = str(exc)
        db.commit()
        exc.file_id = record.id  # type: ignore[attr-defined]
        raise
    except Exception as exc:  # unexpected: persist the failure, surface as 500
        db.rollback()
        record.status = "FAILED"
        record.error = f"Unexpected error: {exc}"
        db.commit()
        raise
    return record


def _to_geojson(geom) -> dict:
    return json.loads(shapely.to_geojson(geom))
