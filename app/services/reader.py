"""Read KML / zipped-Shapefile uploads into plain Python feature dicts."""
import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import geopandas  # noqa: F401  (registers pandas geometry dtype used by pyogrio)
import pyogrio
import shapely
from pyproj import CRS

from app.config import MAX_UNZIPPED_BYTES
from app.errors import InvalidFileError, UnsupportedFileError
from app.services.crs import WGS84, crs_label

SHAPEFILE_PARTS = {".shp", ".shx", ".dbf", ".prj", ".cpg"}


@dataclass
class ParsedFeature:
    index: int
    layer: str | None
    geometry: shapely.Geometry | None
    crs: CRS | None
    properties: dict


@dataclass
class ParsedFile:
    file_type: str
    crs_label: str | None
    features: list[ParsedFeature] = field(default_factory=list)


def detect_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".kml":
        return "kml"
    if suffix == ".zip":
        return "shapefile"
    if suffix == ".kmz":
        raise UnsupportedFileError("KMZ is not supported yet; unzip it and upload the .kml")
    raise UnsupportedFileError("Unsupported file type. Upload a .kml or a .zip containing a Shapefile")


def parse_file(path: Path, file_type: str) -> ParsedFile:
    if file_type == "kml":
        return _parse_kml(path)
    return _parse_shapefile_zip(path)


# ---------------------------------------------------------------- KML
def _parse_kml(path: Path) -> ParsedFile:
    try:
        layers = pyogrio.list_layers(path)
    except Exception as exc:
        raise InvalidFileError(f"Could not read KML: {exc}") from exc

    parsed = ParsedFile(file_type="kml", crs_label=crs_label(WGS84))
    for layer_name, _ in layers:  # every <Folder>/<Document> is a layer
        _read_layer(path, str(layer_name), WGS84, parsed)  # KML is always WGS84 by spec
    return parsed


# ---------------------------------------------------------------- Shapefile
def _parse_shapefile_zip(path: Path) -> ParsedFile:
    if not zipfile.is_zipfile(path):
        raise InvalidFileError("File is not a valid zip archive")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        _safe_extract(path, tmp_dir)
        shp_files = sorted(tmp_dir.rglob("*.shp"))
        if not shp_files:
            raise InvalidFileError("Zip does not contain any .shp file")

        parsed = ParsedFile(file_type="shapefile", crs_label=None)
        labels: set[str | None] = set()
        for shp in shp_files:
            try:
                info = pyogrio.read_info(shp)
            except Exception as exc:
                raise InvalidFileError(f"Could not read {shp.name}: {exc}") from exc
            crs = CRS.from_user_input(info["crs"]) if info.get("crs") else None
            labels.add(crs_label(crs))
            _read_layer(shp, shp.stem, crs, parsed)

        parsed.crs_label = labels.pop() if len(labels) == 1 else "MIXED"
        return parsed


def _safe_extract(zip_path: Path, dest: Path) -> None:
    """Extract shapefile parts only, guarding against zip-slip and zip bombs."""
    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > MAX_UNZIPPED_BYTES:
            raise InvalidFileError("Archive is too large when uncompressed")
        for info in infos:
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or "__MACOSX" in name.parts:
                continue
            if name.suffix.lower() not in SHAPEFILE_PARTS:
                continue
            target = dest / Path(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())


# ---------------------------------------------------------------- shared
def _read_layer(path: Path, layer: str, crs: CRS | None, parsed: ParsedFile) -> None:
    try:
        df = pyogrio.read_dataframe(path, layer=layer)
    except Exception as exc:
        raise InvalidFileError(f"Could not read layer '{layer}': {exc}") from exc
    if df.empty:
        return

    props = json.loads(df.drop(columns=df.geometry.name).to_json(orient="records", date_format="iso"))
    for geom, p in zip(df.geometry.values, props):
        parsed.features.append(
            ParsedFeature(
                index=len(parsed.features),
                layer=layer,
                geometry=geom,
                crs=crs,
                properties=p,
            )
        )
