"""Reverse geocoding via Nominatim (OpenStreetMap) — no API key required."""
import time

import httpx
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from app.services.crs import WGS84, reproject

_NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
_HEADERS = {"User-Agent": "geo-measure-api/1.0"}
_RATE_DELAY = 1.1  # Nominatim policy: max 1 req/sec


def _representative_wgs84(geom: BaseGeometry, src: CRS) -> tuple[float, float]:
    """Return (lon, lat) of the geometry's representative point in WGS84."""
    pt = geom.representative_point()
    if src.equals(WGS84):
        return pt.x, pt.y
    projected = reproject(pt, src, WGS84)
    return projected.x, projected.y


def reverse_geocode(lon: float, lat: float) -> str | None:
    """Call Nominatim and return a short human-readable location string, or None on failure."""
    try:
        resp = httpx.get(
            _NOMINATIM,
            params={"lat": lat, "lon": lon, "format": "json"},
            headers=_HEADERS,
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})

        parts = []
        # Most specific first: suburb/neighbourhood > city/town/village > state > country
        for key in ("suburb", "neighbourhood", "city", "town", "village", "county"):
            if addr.get(key):
                parts.append(addr[key])
                break
        for key in ("city", "town", "village", "state_district"):
            if addr.get(key) and addr[key] not in parts:
                parts.append(addr[key])
                break
        if addr.get("state"):
            parts.append(addr["state"])
        if addr.get("country_code"):
            parts.append(addr["country_code"].upper())

        return ", ".join(parts) if parts else data.get("display_name")
    except Exception:
        return None


def geocode_feature(geom: BaseGeometry, src: CRS) -> str | None:
    """Get location label for a geometry, respecting Nominatim's rate limit."""
    if geom is None or geom.is_empty:
        return None
    try:
        lon, lat = _representative_wgs84(geom, src)
        result = reverse_geocode(lon, lat)
        time.sleep(_RATE_DELAY)
        return result
    except Exception:
        return None
