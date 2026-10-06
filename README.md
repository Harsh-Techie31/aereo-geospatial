# Geospatial File Measurement API

A FastAPI backend that accepts a **KML** file or a **zipped Shapefile**, extracts every feature
(ID, geometry type, geometry, CRS, properties) and returns **area** (polygons) and **length**
(lines), calculated in a *projected* CRS, never in degrees.

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload          # http://localhost:8000
```

Interactive docs (Swagger UI): http://localhost:8000/docs

Run tests:

```bash
pytest -q
```

Config via env vars: `DATABASE_URL` (default `sqlite:///./geo_api.db`), `MAX_UPLOAD_BYTES`
(default 50 MB), `MAX_UNZIPPED_BYTES` (default 300 MB).

Try it with the bundled samples:

```bash
curl -F "file=@samples/sample.kml" http://localhost:8000/api/files/
curl -F "file=@samples/sample_shapefile.zip" http://localhost:8000/api/files/
```

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/files/` | Upload + process a `.kml` or `.zip` (Shapefile) |
| GET | `/api/files/{id}/` | File info / status |
| GET | `/api/files/{id}/features/` | Feature ID, geometry type, GeoJSON geometry, CRS, properties |
| GET | `/api/files/{id}/measurements/` | Per-feature measurements + file summary |

List endpoints take `?limit=` (1-1000, default 100) and `?offset=`.

### POST /api/files/

```bash
curl -F "file=@survey.kml" http://localhost:8000/api/files/
```

`201 Created`
```json
{
  "id": "d0e761f38ca44c15a99959c1b016800d",
  "filename": "survey.kml",
  "file_type": "kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error": null,
  "created_at": "2026-10-07T10:12:45Z"
}
```

Errors: `415` wrong extension, `413` too large, `422` unreadable / corrupt / zip without a `.shp`.
For `422` the body includes the `id` of the stored record with `status: "FAILED"`.

### GET /api/files/{id}/features/

```json
{
  "file_id": "d0e7...", "total": 3, "limit": 100, "offset": 0,
  "features": [
    {
      "index": 0,
      "layer": "sample",
      "geometry_type": "Polygon",
      "geometry": {"type": "Polygon", "coordinates": [[[85.1, 25.6], [85.2, 25.6], ...]]},
      "crs": "EPSG:4326",
      "properties": {"Name": "Plot A", "description": null}
    }
  ]
}
```

### GET /api/files/{id}/measurements/

```json
{
  "file_id": "d0e7...", "total": 3, "limit": 100, "offset": 0,
  "summary": {
    "measurable_features": 2,
    "unmeasurable_features": 1,
    "total_area_m2": 111245409.346,
    "total_length_m": 24989.004
  },
  "measurements": [
    {"feature_index": 0, "layer": "sample", "geometry_type": "Polygon",
     "measurement_supported": true, "area_m2": 111245409.346, "perimeter_m": 42240.13,
     "length_m": null, "projected_crs": "EPSG:32645", "warning": null},
    {"feature_index": 1, "layer": "sample", "geometry_type": "LineString",
     "measurement_supported": true, "area_m2": null, "perimeter_m": null,
     "length_m": 24989.004, "projected_crs": "EPSG:32645", "warning": null},
    {"feature_index": 2, "layer": "sample", "geometry_type": "Point",
     "measurement_supported": false, "area_m2": null, "perimeter_m": null,
     "length_m": null, "projected_crs": null, "warning": "No measurement defined for Point"}
  ]
}
```

All areas are in m², all lengths in metres.

## Architecture

```
app/
  main.py              app factory, error handler, table creation
  api/files.py         thin HTTP layer (validation, pagination, response shaping)
  services/
    processing.py      orchestration: save upload -> parse -> measure -> persist
    reader.py          KML + Shapefile-zip readers (via pyogrio/GDAL)
    crs.py             CRS labelling, UTM selection, reprojection
    measure.py         measurement rules per geometry type
  models.py / db.py    SQLAlchemy models (File, Feature), SQLite by default
  schemas.py           Pydantic response models
tests/                 pytest, runs against real generated KML/Shapefiles
```

**File-processing flow**
1. Extension decides the type (`.kml` / `.zip`). Anything else is rejected with 415 before touching disk or DB.
2. Upload is streamed to a temp file with a size cap; a `File` row is created with `PROCESSING`.
3. KML: every layer (each `<Folder>`/`<Document>` is a GDAL layer) is read. Shapefile: the zip is
   extracted safely (zip-slip and zip-bomb guards, only `.shp/.shx/.dbf/.prj/.cpg` kept) and **every**
   `.shp` inside is read, because a shapefile can hold only one geometry type.
4. Each feature gets a global 0-based index, geometry type, GeoJSON geometry, CRS and properties.
5. Features are measured and stored; the file becomes `COMPLETED` (or `FAILED` with an error message).
   The uploaded file itself is deleted after processing; the results are what's stored.

**Measurement flow** (`measure.py`)
- Polygon / MultiPolygon -> area + perimeter. LineString / MultiLineString -> length.
- Point / MultiPoint -> no measurement, with an explanatory `warning`.
- Anything else (GeometryCollection, empty/null geometry, missing CRS) -> `measurement_supported: false`
  with a `warning`. No feature can fail the whole request: there is a per-feature guard.
- Z values (KML altitude) are dropped before measuring, so measurements are planar 2D.
- Invalid polygons (e.g. bow-ties) are repaired with `make_valid` and flagged in `warning`.

**CRS handling** (`crs.py`)
- KML is WGS84 (EPSG:4326) by specification. Shapefile CRS is read from the `.prj`.
- If the source CRS is already projected in metres, measure directly in it.
- Otherwise reproject **each feature** to the UTM zone of its representative point
  (EPSG:326xx north / 327xx south), or polar stereographic (EPSG:3995 / 3031) beyond UTM's range.
- The CRS used is returned per feature as `projected_crs`.

## Design Decisions

| Decision | Why | Alternatives considered |
|---|---|---|
| **FastAPI** | Typed request/response models, automatic OpenAPI docs, little boilerplate for a 4-endpoint service | Django + DRF: heavier than needed with no admin/auth requirement |
| **pyogrio (GDAL) for reading** | One reader for KML and Shapefile, handles encodings and layers, much faster than fiona | fiona (slower), hand-parsing KML XML (misses edge cases), `fastkml` (KML only) |
| **Per-feature UTM** | Simple, accurate to ~0.1-0.5% for typical features, and correct even when one file spans several zones | One CRS per file (wrong for multi-zone files); equal-area projection (better for huge polygons, awkward for lines); geodesic maths via `pyproj.Geod` (most accurate, but the brief asks for a projected approach) |
| **Synchronous processing** | Typical survey files process in well under a second; keeps the API simple and testable | Background worker (Celery/RQ) with `PROCESSING` polling; the `status` field already allows this |
| **SQLite + SQLAlchemy** | Zero setup for reviewers; swapping to Postgres is one env var | Postgres/PostGIS (overkill here), in-memory dict (loses data on restart) |
| **Store geometry as GeoJSON JSON** | Portable, easy to return as-is | PostGIS geometry columns |
| **Measurements computed at upload, stored** | `GET .../measurements/` is a cheap, paginated read | Compute on read (wasted CPU on every request) |
| **Graceful per-feature warnings, not errors** | Matches the brief: one odd feature must not break a 10,000-feature file | Fail the whole upload |

Known limits: very large polygons (country-sized) lose accuracy in a single UTM zone; KMZ is not
supported; Shapefile files with a missing `.prj` are read, but not measured, because guessing a CRS is unsafe.

## Learnings

- Shapefile is a *bundle* (`.shp/.shx/.dbf/.prj`) and holds one geometry type, so a "shapefile zip" can really be several layers.
- KML has no CRS field because it is always WGS84; its "layers" are folders, so reading only the first layer silently drops features.
- Degrees are not metres: a 0.1 deg x 0.1 deg box is ~111 km2 at 25 deg N but ~123 km2 at the equator. Tests compare against `pyproj.Geod` to prove the projected result is correct.
- Real files contain invalid and empty geometries; deciding what "graceful" means (warn, repair, skip) is most of the work.
- Untrusted zips need extraction guards (zip-slip, size limits).

## Future Scope

- Async processing (Celery/RQ + Redis) with progress polling for large files.
- KMZ, GeoJSON and GeoPackage support.
- Optional `method=geodesic` query param using `pyproj.Geod` to cross-check or replace the projected result.
- PostGIS storage plus spatial queries (bbox filter, intersects).
- Auth, per-user file ownership, file expiry / cleanup job.
- Docker image + CI (pytest, ruff, mypy).
- Per-layer filtering and unit options (ha, km2, ft) on the measurements endpoint.
