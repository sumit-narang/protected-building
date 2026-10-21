"""Irish Grid (TM65, EPSG:29902) -> WGS84 lat/lon, pure standard library.

The RPS CSV gives IG_EASTING / IG_NORTHING on the old Irish Grid: a transverse
Mercator projection of the Airy Modified ellipsoid (Ireland 1965 datum). We
invert the projection (Ordnance Survey formulas), then shift the datum to WGS84
with the 7-parameter Helmert transform PROJ uses for EPSG:29902. Accuracy is
about 1-2 m, which is the limit of a single Helmert shift for Ireland.
"""

from __future__ import annotations

import math

# Airy Modified ellipsoid + Irish Grid projection constants.
A_AIRY_MOD = 6377340.189
B_AIRY_MOD = 6356034.447
F0 = 1.000035
LAT0 = math.radians(53.5)
LON0 = math.radians(-8.0)
E0 = 200000.0
N0 = 250000.0

# WGS84 ellipsoid.
A_WGS84 = 6378137.0
B_WGS84 = 6356752.314245

# Ireland 1965 -> WGS84 (PROJ +towgs84, position-vector convention).
TX, TY, TZ = 482.5, -130.6, 564.6
RX, RY, RZ = (math.radians(s / 3600) for s in (-1.042, -0.214, -0.631))
S = 8.15e-6


def _meridional_arc(phi: float, a: float, b: float) -> float:
    n = (a - b) / (a + b)
    n2, n3 = n * n, n * n * n
    dp, sp = phi - LAT0, phi + LAT0
    return b * F0 * (
        (1 + n + 5 / 4 * n2 + 5 / 4 * n3) * dp
        - (3 * n + 3 * n2 + 21 / 8 * n3) * math.sin(dp) * math.cos(sp)
        + (15 / 8 * n2 + 15 / 8 * n3) * math.sin(2 * dp) * math.cos(2 * sp)
        - 35 / 24 * n3 * math.sin(3 * dp) * math.cos(3 * sp)
    )


def _grid_to_geodetic(e: float, n: float) -> tuple[float, float]:
    """Inverse transverse Mercator on Airy Modified -> (lat, lon) radians."""
    a, b = A_AIRY_MOD, B_AIRY_MOD
    e2 = 1 - (b * b) / (a * a)
    phi = LAT0
    m = 0.0
    while True:
        phi = (n - N0 - m) / (a * F0) + phi
        m = _meridional_arc(phi, a, b)
        if abs(n - N0 - m) < 1e-5:
            break

    sin_p, cos_p, tan_p = math.sin(phi), math.cos(phi), math.tan(phi)
    nu = a * F0 / math.sqrt(1 - e2 * sin_p**2)
    rho = a * F0 * (1 - e2) / (1 - e2 * sin_p**2) ** 1.5
    eta2 = nu / rho - 1
    t2, t4 = tan_p**2, tan_p**4
    sec_p = 1 / cos_p

    vii = tan_p / (2 * rho * nu)
    viii = tan_p / (24 * rho * nu**3) * (5 + 3 * t2 + eta2 - 9 * t2 * eta2)
    ix = tan_p / (720 * rho * nu**5) * (61 + 90 * t2 + 45 * t4)
    x = sec_p / nu
    xi = sec_p / (6 * nu**3) * (nu / rho + 2 * t2)
    xii = sec_p / (120 * nu**5) * (5 + 28 * t2 + 24 * t4)
    xiia = sec_p / (5040 * nu**7) * (61 + 662 * t2 + 1320 * t4 + 720 * tan_p**6)

    de = e - E0
    lat = phi - vii * de**2 + viii * de**4 - ix * de**6
    lon = LON0 + x * de - xi * de**3 + xii * de**5 - xiia * de**7
    return lat, lon


def _to_cartesian(lat: float, lon: float, a: float, b: float) -> tuple[float, float, float]:
    e2 = 1 - (b * b) / (a * a)
    nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return (
        nu * math.cos(lat) * math.cos(lon),
        nu * math.cos(lat) * math.sin(lon),
        (1 - e2) * nu * math.sin(lat),
    )


def _from_cartesian(x: float, y: float, z: float, a: float, b: float) -> tuple[float, float]:
    e2 = 1 - (b * b) / (a * a)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(10):
        nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z + e2 * nu * math.sin(lat), p)
    return lat, math.atan2(y, x)


def to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Irish Grid easting/northing (metres) -> (lat, lon) in WGS84 degrees."""
    lat, lon = _grid_to_geodetic(easting, northing)
    x, y, z = _to_cartesian(lat, lon, A_AIRY_MOD, B_AIRY_MOD)
    x2 = TX + (1 + S) * (x - RZ * y + RY * z)
    y2 = TY + (1 + S) * (RZ * x + y - RX * z)
    z2 = TZ + (1 + S) * (-RY * x + RX * y + z)
    lat, lon = _from_cartesian(x2, y2, z2, A_WGS84, B_WGS84)
    return round(math.degrees(lat), 6), round(math.degrees(lon), 6)
