# Geo Measure API

A FastAPI service that takes a geospatial file — KML or a zipped Shapefile — and tells you what's in it: the features, their geometries, and actual real-world measurements (area in m², length in metres). Not degrees. Actual distances.

Built as part of a geospatial backend assignment.

---

## What it does

Upload a `.kml` or `.zip` (Shapefile) and the API processes it end to end:

- Reads every feature across all layers in the file
- Identifies geometry type — Point, LineString, Polygon, and multi-variants
- Extracts the CRS and all properties/attributes attached to each feature
- Calculates area (m²) for polygons and length (m) for lines, after reprojecting to the correct UTM zone — never raw degrees
- Points are returned as-is with a note that no measurement applies
- Invalid or unsupported geometries never crash the request — they get a `warning` field instead

---

## Bonus features

Three extra capabilities built on top of the core requirements:

**1. Reverse Geocoding**
Every feature can be enriched with a human-readable location label — city, district, state, country — derived from its coordinates using OpenStreetMap's Nominatim API (no API key needed).

This is opt-in because Nominatim allows only 1 request per second, so a file with many features would be slow by default. Enable it by passing `?geocode=true` on upload:
```bash
curl -X POST "http://localhost:8000/api/files/?geocode=true" -F "file=@survey.kml"
```
Each feature in the response will then include a `location` field like `"Koramangala, Bengaluru, Karnataka, IN"`.

**2. Bounding Box**
Every uploaded file gets a `bbox` field on its info response — four coordinates representing the rectangular envelope that wraps all features in the file: `[min_lon, min_lat, max_lon, max_lat]`. Useful for map viewport fitting, spatial filtering, or just knowing at a glance where in the world the file is.

```bash
GET http://localhost:8000/api/files/{id}/
# "bbox": [77.506, 12.964, 77.713, 13.051]
```

**3. GeoJSON Download**
Fetch all features as a valid GeoJSON FeatureCollection, with measurements (area, length, perimeter) and location baked into each feature's properties. The file can be dropped straight into QGIS, Google Maps, or [geojson.io](https://geojson.io) without any transformation.

```bash
GET http://localhost:8000/api/files/{id}/geojson/
```

---

## Frontend

A minimal browser UI is included in the `frontend/` folder — a single `index.html` with no build step or dependencies. It lets you interact with every endpoint without opening Postman or writing curl commands.

**To use it locally**, just open `frontend/index.html` in a browser while the backend is running. The API base URL defaults to `http://localhost:8000` and can be changed in the input at the top.

**What it supports:**
- Drag-and-drop file upload with the geocode toggle
- Inline feature and measurement viewer with pagination
- One-click GeoJSON download
- Recent uploads history (stored in browser)
- Lookup by file ID

**To deploy the frontend on Vercel**, point the root directory to `frontend/` — it's a static site and deploys as-is. Update the API base URL in the UI to point to wherever your backend is hosted.

---

## Running locally

Requires Python 3.10+.

```bash
python -m venv .venv

# Mac/Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Server runs at `http://localhost:8000`. Interactive API docs (Swagger UI) at `http://localhost:8000/docs`.

**Run tests:**
```bash
pytest -q
```

There are sample files in the `samples/` folder if you want to test straight away:
```bash
curl -F "file=@samples/sample.kml" http://localhost:8000/api/files/
curl -F "file=@samples/sample_shapefile.zip" http://localhost:8000/api/files/
```

---

## API

### Upload a file
`POST /api/files/`

Accepts a `.kml` file or a `.zip` containing a Shapefile. Pass `?geocode=true` to also get reverse-geocoded locations per feature (adds ~1 second per feature due to Nominatim rate limits, so it's off by default).

```bash
curl -X POST http://localhost:8000/api/files/ \
  -F "file=@survey.kml"
```

```json
{
  "id": "d0e761f38ca44c15a99959c1b016800d",
  "filename": "survey.kml",
  "file_type": "kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "bbox": [77.506, 12.964, 77.713, 13.051],
  "status": "COMPLETED",
  "created_at": "2026-10-07T10:12:45Z"
}
```

### Get file info
`GET /api/files/{id}/`

Returns the same shape as the upload response. Useful for polling status on large files.

### Get features
`GET /api/files/{id}/features/`

Returns each feature with its geometry (GeoJSON), CRS, properties, and location (if geocoding was requested). Supports `?limit` and `?offset` for pagination.

```json
{
  "total": 3,
  "features": [
    {
      "index": 0,
      "layer": "Untitled layer",
      "geometry_type": "Point",
      "geometry": { "type": "Point", "coordinates": [77.506, 12.988] },
      "crs": "EPSG:4326",
      "location": "Rajajinagar, Bengaluru, Karnataka, IN",
      "properties": { "Name": "Point 1" }
    }
  ]
}
```

### Get measurements
`GET /api/files/{id}/measurements/`

Returns per-feature measurements plus a summary. Polygons get area + perimeter, lines get length, points are skipped gracefully.

```json
{
  "summary": {
    "measurable_features": 2,
    "unmeasurable_features": 1,
    "total_area_m2": 111245409.346,
    "total_length_m": 24989.004
  },
  "measurements": [
    {
      "feature_index": 0,
      "geometry_type": "Polygon",
      "area_m2": 111245409.346,
      "perimeter_m": 42240.13,
      "projected_crs": "EPSG:32643"
    },
    {
      "feature_index": 1,
      "geometry_type": "Point",
      "measurement_supported": false,
      "warning": "No measurement defined for Point"
    }
  ]
}
```

### Download as GeoJSON
`GET /api/files/{id}/geojson/`

Downloads a `.geojson` file (FeatureCollection) with measurements attached as properties on each feature. You can drop this directly into QGIS, Google Maps, or [geojson.io](https://geojson.io).

---

## Architecture

```
app/
  main.py                 app setup, CORS, error handlers
  api/files.py            all endpoints
  services/
    processing.py         upload → parse → measure → persist
    reader.py             reads KML and Shapefile zips via GDAL/pyogrio
    crs.py                picks the right UTM zone, handles reprojection
    measure.py            area/length rules per geometry type
    geocode.py            reverse geocoding via Nominatim
  models.py               SQLAlchemy models (UploadedFile, Feature)
  schemas.py              Pydantic response shapes
tests/                    pytest suite against real generated files
frontend/                 single-file HTML UI
```

**How a file gets processed:**

1. Extension is checked first — wrong type gets a `415` before anything hits the DB
2. File is streamed to a temp directory with a size cap (default 50 MB)
3. For KML: every folder is treated as a layer and read fully. For Shapefile zips: the archive is extracted with zip-slip and zip-bomb guards, then every `.shp` file inside is read (a zip can have multiple since each shapefile only holds one geometry type)
4. Each feature is measured, optionally geocoded, then saved to the DB
5. A bounding box is computed from the union of all feature geometries
6. The temp file is deleted; the DB holds everything from here on

**How measurements work:**

The core rule is: never calculate area or distance using raw degrees. Before measuring, each feature is reprojected to the UTM zone that covers its representative point. A feature at lon 77°, lat 13° lands in UTM Zone 43N (EPSG:32643). Features near the poles use polar stereographic instead. If the source file is already in a metric projected CRS, it's used as-is. The projected CRS used is returned with every measurement so you can verify it.

---

## Design decisions

**FastAPI over Django:** Django + DRF made sense if there were auth, admin, or a lot of domain models. For four endpoints and no user layer, FastAPI's typed schemas and automatic Swagger docs were cleaner.

**pyogrio for file reading:** It's a GDAL wrapper that handles both KML and Shapefile in one interface, deals with encoding issues, and reads all layers — not just the first one. Alternatives like `fiona` are slower and hand-parsing KML XML misses edge cases like multi-layer files.

**Per-feature UTM:** Projecting each feature to its own best-fit UTM zone is more accurate than picking one CRS for the whole file (which breaks when features span multiple zones). Accuracy is within ~0.1–0.5% for typical survey-scale features.

**SQLite by default:** Zero setup for anyone running this locally. Swapping to Postgres only needs a `DATABASE_URL` env var change.

**Reverse geocoding as opt-in:** Nominatim (OpenStreetMap's free geocoding API) has a hard rate limit of 1 request per second. Making it opt-in via `?geocode=true` keeps normal uploads fast and doesn't surprise anyone uploading a 500-feature file.

**Measurements stored at upload time:** The `GET /measurements/` endpoint is just a DB read — no recomputation. This matters at scale.

---

## Learnings

Going into this I understood geospatial data conceptually but hadn't worked with it in code. A few things that weren't obvious until I hit them:

- A "Shapefile" is actually 4–6 files that must stay together (`.shp`, `.shx`, `.dbf`, `.prj`). The `.prj` holds the CRS — without it you can read the geometry but can't safely measure it.
- KML doesn't have a CRS field because it's always WGS84 by spec. But it does have layers (folders), and reading only the first one silently drops features — which is a quiet and confusing bug.
- A 0.1° × 0.1° box is not a fixed area. At the equator it's ~123 km², at 25°N it's ~111 km². This is why you can't measure in degrees.
- "Graceful handling" for bad geometries is most of the actual work. Self-intersecting polygons, empty geometries, missing CRS — each needs a distinct decision: repair it, skip it, or warn and move on.

---

## Future scope

- **Async processing** with Celery or RQ for large files — the `status` field is already set up for polling
- **KMZ support** (KMZ is just a zipped KML, so it's a small addition)
- **GeoJSON and GeoPackage** as additional input formats
- **Geodesic measurements** via `pyproj.Geod` as an alternative to UTM projection for very large polygons
- **PostGIS backend** for spatial queries — bounding box filters, feature intersection
- **File expiry** — uploaded files currently live forever in the DB
- **Docker + CI** — a Dockerfile and GitHub Actions pipeline for pytest + linting
