"""Stage 4 — tag rows with the conservation zone they sit in.

The Dublin City Development Plan 2022-2028 zones some areas specifically for
conservation:
  Z2 — Residential Conservation Area ("to protect and/or improve the amenities
       of residential conservation areas")
  Z8 — Georgian Conservation Area
Being in one does not make a building protected, but the council expects
changes there to respect the area's character. The map shades the zones and
each building's card names the zone it sits in.

The GeoJSON is already WGS84 (unlike the RPS GeoJSON). We tag each row by
point-in-polygon and write a simplified copy (about 1 m tolerance) for the map.
"""

from __future__ import annotations

import json
import math
import urllib.request
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
IN_PATH = DATA / "enriched.json"
OUT_PATH = DATA / "zoned.json"
MAP_PATH = DATA / "zones_simplified.geojson"

BASE = "https://data.smartdublin.ie/dataset/6180e6ed-9e00-4554-bb65-39729fa319a7/resource"
ZONES = {
    "Z2": f"{BASE}/12b83d50-a40b-4146-a33b-a7824182e350/download/zone-z2-dev-plan-2022-2028.shp.geojson",
    "Z8": f"{BASE}/7f10fd59-ee20-4c07-b106-d7b31e90f406/download/zone-z8-dev-plan-2022-2028.shp.geojson",
}

M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = M_PER_DEG_LAT * math.cos(math.radians(53.34))
TOLERANCE_M = 1.0


def fetch(zone: str) -> list:
    """The zone's polygons (list of rings per polygon), downloaded once."""
    path = DATA / "raw" / f"{zone.lower()}.geojson"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(ZONES[zone], headers={"User-Agent": "protected-building/0.1"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            path.write_bytes(resp.read())
    polygons = []
    for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
        geom = feature["geometry"]
        parts = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in parts:
            polygons.append([[(p[0], p[1]) for p in ring] for ring in poly])
    return polygons


def in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


class Zone:
    def __init__(self, polygons: list):
        self.polygons = polygons
        self.boxes = []
        for poly in polygons:
            xs = [x for x, _ in poly[0]]
            ys = [y for _, y in poly[0]]
            self.boxes.append((min(xs), min(ys), max(xs), max(ys)))

    def contains(self, lon: float, lat: float) -> bool:
        for (x0, y0, x1, y1), poly in zip(self.boxes, self.polygons):
            if x0 <= lon <= x1 and y0 <= lat <= y1 and in_ring(lon, lat, poly[0]) \
                    and not any(in_ring(lon, lat, hole) for hole in poly[1:]):
                return True
        return False


def simplify(ring: list) -> list:
    """Douglas-Peucker in metres; keeps the ring closed."""
    pts = [(lon * M_PER_DEG_LON, lat * M_PER_DEG_LAT) for lon, lat in ring]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        best, best_i = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / length if length else math.hypot(px - ax, py - ay)
            if d > best:
                best, best_i = d, i
        if best > TOLERANCE_M:
            keep[best_i] = True
            stack += [(a, best_i), (best_i, b)]
    out = [[round(lon, 6), round(lat, 6)] for (lon, lat), k in zip(ring, keep) if k]
    return out if len(out) >= 4 else [[round(lon, 6), round(lat, 6)] for lon, lat in ring]


def run() -> None:
    print("Stage 4: tagging conservation zones (Z2, Z8)")
    zones = {name: Zone(fetch(name)) for name in ZONES}

    rows = json.loads(IN_PATH.read_text(encoding="utf-8"))
    counts: Counter[str] = Counter()
    for row in rows:
        # Z8 first: the Georgian zone is the more specific of the two.
        row["zone"] = next((name for name in ("Z8", "Z2") if zones[name].contains(row["lon"], row["lat"])), None)
        counts[row["zone"] or "none"] += 1
    OUT_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    features = [{
        "type": "Feature",
        "properties": {"zone": name},
        "geometry": {"type": "MultiPolygon",
                     "coordinates": [[simplify(ring) for ring in poly] for poly in zone.polygons]},
    } for name, zone in zones.items()]
    MAP_PATH.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                   separators=(",", ":")), encoding="utf-8")

    print(f"  rows in Z2: {counts['Z2']:,}, Z8: {counts['Z8']:,}, neither: {counts['none']:,}")
    print(f"  wrote {OUT_PATH} and {MAP_PATH} ({MAP_PATH.stat().st_size / 1e6:.1f} MB)")
