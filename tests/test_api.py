import geopandas as gpd
import pytest
from pyproj import Geod
from shapely.geometry import Polygon

from tests.conftest import PATNA_LINE, PATNA_POLY, zip_shapefile

GEOD = Geod(ellps="WGS84")


def upload(client, path, filename=None, content_type="application/octet-stream"):
    with open(path, "rb") as fh:
        return client.post("/api/files/", files={"file": (filename or path.name, fh, content_type)})


def test_kml_upload_and_measurements(client, tmp, mixed_gdf):
    kml = tmp / "survey.kml"
    mixed_gdf.to_file(kml, driver="KML")

    r = upload(client, kml)
    assert r.status_code == 201
    info = r.json()
    assert info["status"] == "COMPLETED"
    assert info["crs"] == "EPSG:4326"
    assert info["feature_count"] == 3

    assert client.get(f"/api/files/{info['id']}/").json()["filename"] == "survey.kml"

    m = client.get(f"/api/files/{info['id']}/measurements/").json()
    by_type = {x["geometry_type"]: x for x in m["measurements"]}

    # projected result must match true geodesic numbers (not degree maths)
    true_area = abs(GEOD.geometry_area_perimeter(PATNA_POLY)[0])
    true_len = GEOD.geometry_length(PATNA_LINE)
    assert by_type["Polygon"]["area_m2"] == pytest.approx(true_area, rel=0.005)
    assert by_type["LineString"]["length_m"] == pytest.approx(true_len, rel=0.005)
    assert by_type["Polygon"]["projected_crs"] == "EPSG:32645"  # UTM 45N
    assert by_type["Point"]["measurement_supported"] is False
    assert "No measurement" in by_type["Point"]["warning"]
    assert m["summary"]["unmeasurable_features"] == 1


def test_features_endpoint_has_geometry_crs_properties(client, tmp, mixed_gdf):
    kml = tmp / "a.kml"
    mixed_gdf.to_file(kml, driver="KML")
    fid = upload(client, kml).json()["id"]
    feats = client.get(f"/api/files/{fid}/features/").json()["features"]
    assert [f["index"] for f in feats] == [0, 1, 2]
    assert feats[0]["geometry"]["type"] == "Polygon"
    assert feats[0]["crs"] == "EPSG:4326"
    assert feats[0]["properties"]["Name"] == "plot"


def test_shapefile_geographic(client, tmp, mixed_gdf):
    z = zip_shapefile(mixed_gdf, tmp)
    r = upload(client, z)
    assert r.status_code == 201 and r.json()["crs"] == "EPSG:4326"
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    poly = next(x for x in m["measurements"] if x["geometry_type"] == "Polygon")
    assert poly["area_m2"] == pytest.approx(abs(GEOD.geometry_area_perimeter(PATNA_POLY)[0]), rel=0.005)


def test_shapefile_already_metric_is_not_reprojected(client, tmp):
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Polygon([(0, 0), (100, 0), (100, 50), (0, 50)])], crs="EPSG:32645")
    r = upload(client, zip_shapefile(gdf, tmp))
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["measurements"][0]
    assert m["area_m2"] == 5000.0 and m["perimeter_m"] == 300.0
    assert m["projected_crs"] == "EPSG:32645"


def test_missing_prj_degrades_gracefully(client, tmp, mixed_gdf):
    r = upload(client, zip_shapefile(mixed_gdf, tmp, drop_prj=True))
    assert r.status_code == 201
    assert r.json()["crs"] is None
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["measurements"]
    assert all(not x["measurement_supported"] for x in m)
    assert all("CRS" in x["warning"] for x in m if x["geometry_type"] != "Point")


def test_invalid_bowtie_polygon_does_not_crash(client, tmp):
    bowtie = Polygon([(85.1, 25.6), (85.2, 25.7), (85.2, 25.6), (85.1, 25.7)])
    gdf = gpd.GeoDataFrame({"n": ["bad"]}, geometry=[bowtie], crs="EPSG:4326")
    r = upload(client, zip_shapefile(gdf, tmp))
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["measurements"][0]
    assert m["measurement_supported"] and "invalid" in m["warning"].lower()


def test_multiple_utm_zones_in_one_file(client, tmp):
    # one polygon in UTM 45N, one in UTM 30N -> each measured in its own zone
    a = Polygon([(85.1, 25.6), (85.2, 25.6), (85.2, 25.7), (85.1, 25.7)])
    b = Polygon([(-3.7, 40.4), (-3.6, 40.4), (-3.6, 40.5), (-3.7, 40.5)])
    gdf = gpd.GeoDataFrame({"n": ["a", "b"]}, geometry=[a, b], crs="EPSG:4326")
    r = upload(client, zip_shapefile(gdf, tmp))
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["measurements"]
    assert {x["projected_crs"] for x in m} == {"EPSG:32645", "EPSG:32630"}


def test_pagination(client, tmp, mixed_gdf):
    fid = upload(client, zip_shapefile(mixed_gdf, tmp)).json()["id"]
    page = client.get(f"/api/files/{fid}/measurements/?limit=1&offset=1").json()
    assert page["total"] == 3 and len(page["measurements"]) == 1
    assert page["measurements"][0]["feature_index"] == 1


# ------------------------------------------------------------ error paths
def test_unsupported_extension(client, tmp):
    p = tmp / "x.geojson"
    p.write_text("{}")
    assert upload(client, p).status_code == 415


def test_corrupt_kml_is_422_and_recorded_as_failed(client, tmp):
    p = tmp / "bad.kml"
    p.write_text("this is not xml")
    r = upload(client, p)
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "FAILED"
    assert client.get(f"/api/files/{body['id']}/").json()["status"] == "FAILED"


def test_zip_without_shp(client, tmp):
    import zipfile
    z = tmp / "empty.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", "hi")
    assert upload(client, z).status_code == 422


def test_not_a_zip(client, tmp):
    p = tmp / "fake.zip"
    p.write_bytes(b"nope")
    assert upload(client, p).status_code == 422


def test_unknown_id_404(client):
    assert client.get("/api/files/doesnotexist/").status_code == 404
    assert client.get("/api/files/doesnotexist/measurements/").status_code == 404
