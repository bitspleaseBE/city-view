"""Local tangent-plane projection for Antwerp map tiles."""

from __future__ import annotations

import math

METERS_PER_DEG_LAT = 110540.0


def meters_per_deg_lon(lat: float) -> float:
    return 111320.0 * math.cos(math.radians(lat))


def project(lat: float, lon: float, origin_lat: float, origin_lon: float) -> tuple[float, float]:
    """Return local metres (east, north) relative to origin."""
    x = (lon - origin_lon) * meters_per_deg_lon(origin_lat)
    y = (lat - origin_lat) * METERS_PER_DEG_LAT
    return (x, y)
