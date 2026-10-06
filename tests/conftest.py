import os
import tempfile
import zipfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"

import geopandas as gpd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def tmp(tmp_path) -> Path:
    return tmp_path


def zip_shapefile(gdf, tmp: Path, name="data", drop_prj=False) -> Path:
    """Shapefiles hold one geometry type each, so write one .shp per type."""
    shp_dir = tmp / f"{name}_shp"
    shp_dir.mkdir()
    for gtype, part in gdf.groupby(gdf.geom_type):
        part.to_file(shp_dir / f"{name}_{gtype.lower()}.shp")
    zpath = tmp / f"{name}.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in shp_dir.iterdir():
            if drop_prj and f.suffix == ".prj":
                continue
            zf.write(f, f.name)
    return zpath


# ~0.1 deg box near Patna
PATNA_POLY = Polygon([(85.1, 25.6), (85.2, 25.6), (85.2, 25.7), (85.1, 25.7)])
PATNA_LINE = LineString([(85.1, 25.6), (85.2, 25.7), (85.3, 25.7)])


@pytest.fixture
def mixed_gdf():
    return gpd.GeoDataFrame(
        {"name": ["plot", "road", "well"]},
        geometry=[PATNA_POLY, PATNA_LINE, Point(85.15, 25.65)],
        crs="EPSG:4326",
    )
