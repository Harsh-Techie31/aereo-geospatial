"""CRS helpers: labelling CRSs and choosing a projected CRS for measurement."""
from functools import lru_cache

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

WGS84 = CRS.from_epsg(4326)
ARCTIC_POLAR = 3995   # WGS 84 / Arctic Polar Stereographic
ANTARCTIC_POLAR = 3031  # WGS 84 / Antarctic Polar Stereographic


def crs_label(crs: CRS | None) -> str | None:
    """'EPSG:4326' when an authority code is known, otherwise the CRS name."""
    if crs is None:
        return None
    auth = crs.to_authority(min_confidence=70)
    if auth:
        return f"{auth[0]}:{auth[1]}"
    return crs.name or crs.to_wkt()


@lru_cache(maxsize=256)
def _transformer(src_wkt: str, dst_wkt: str) -> Transformer:
    return Transformer.from_crs(CRS.from_wkt(src_wkt), CRS.from_wkt(dst_wkt), always_xy=True)


def reproject(geom: BaseGeometry, src: CRS, dst: CRS) -> BaseGeometry:
    t = _transformer(src.to_wkt(), dst.to_wkt())
    return transform(t.transform, geom)


def utm_epsg_for(lon: float, lat: float) -> int:
    """UTM zone for a lon/lat (polar stereographic beyond UTM's valid range)."""
    if lat >= 84:
        return ARCTIC_POLAR
    if lat <= -80:
        return ANTARCTIC_POLAR
    zone = int((lon + 180) // 6) + 1
    zone = max(1, min(60, zone))
    return (32600 if lat >= 0 else 32700) + zone


def is_metric_projected(crs: CRS) -> bool:
    if not crs.is_projected:
        return False
    return all(ax.unit_name in ("metre", "meter") for ax in crs.axis_info)


def choose_projected_crs(geom: BaseGeometry, src: CRS) -> CRS:
    """Pick the CRS to measure `geom` in.

    * Source already projected in metres -> use it as-is (no needless transform).
    * Otherwise -> UTM zone (or polar stereographic) of the geometry's
      representative point, so distortion is minimal for *that* feature.
    """
    if is_metric_projected(src):
        return src
    lon, lat = _representative_lonlat(geom, src)
    return CRS.from_epsg(utm_epsg_for(lon, lat))


def _representative_lonlat(geom: BaseGeometry, src: CRS) -> tuple[float, float]:
    p = geom.representative_point()
    if src.equals(WGS84):
        return p.x, p.y
    lon, lat = _transformer(src.to_wkt(), WGS84.to_wkt()).transform(p.x, p.y)
    return lon, lat
