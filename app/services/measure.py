"""Measurement calculation. Never raises for bad geometry; returns a warning instead."""
from dataclasses import dataclass

import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from app.services.crs import crs_label, choose_projected_crs, reproject

POLYGONAL = {"Polygon", "MultiPolygon"}
LINEAR = {"LineString", "MultiLineString", "LinearRing"}
NO_MEASURE = {"Point", "MultiPoint"}


@dataclass
class Measurement:
    supported: bool = False
    area_m2: float | None = None
    perimeter_m: float | None = None
    length_m: float | None = None
    projected_crs: str | None = None
    warning: str | None = None


def measure_geometry(geom: BaseGeometry | None, src_crs: CRS | None) -> Measurement:
    if geom is None or geom.is_empty:
        return Measurement(warning="Geometry is empty or missing")

    gtype = geom.geom_type
    if gtype in NO_MEASURE:
        return Measurement(warning=f"No measurement defined for {gtype}")
    if gtype not in POLYGONAL | LINEAR:
        return Measurement(warning=f"Measurement not supported for geometry type {gtype}")
    if src_crs is None:
        return Measurement(warning="Source CRS is unknown (e.g. missing .prj); cannot measure safely")

    try:
        warning = None
        g = shapely.force_2d(geom)  # drop Z (KML often has altitude)
        if gtype in POLYGONAL and not g.is_valid:
            g = shapely.make_valid(g)
            warning = "Geometry was invalid (e.g. self-intersecting); repaired before measuring"

        target = choose_projected_crs(g, src_crs)
        projected = g if target.equals(src_crs) else reproject(g, src_crs, target)

        if gtype in POLYGONAL:
            return Measurement(
                supported=True,
                area_m2=round(projected.area, 3),
                perimeter_m=round(projected.length, 3),
                projected_crs=crs_label(target),
                warning=warning,
            )
        return Measurement(
            supported=True,
            length_m=round(projected.length, 3),
            projected_crs=crs_label(target),
            warning=warning,
        )
    except Exception as exc:  # last-resort guard: one bad feature must not fail the file
        return Measurement(warning=f"Measurement failed: {exc}")
