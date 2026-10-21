"""Stage 4 — emit the frontend data.

- data/structures.geojson — every RPS row as a point with all its fields
  (full record, for reuse elsewhere).
- web/data/structures.json — slim rows for the map: short keys, no long text.
- web/data/details/<n>.json — the long NIAH text and photo, keyed by RPS row
  key and split into SHARDS files by RPS ID, so the map loads fast and opening
  a card fetches ~250 KB rather than all of it.

Each row's key is "<rps_id>" or "<rps_id>-<part>" when one RPS ID spans several
rows (e.g. the buildings of Trinity College).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IN_PATH = ROOT / "data" / "enriched.json"
GEOJSON_PATH = ROOT / "data" / "structures.geojson"
WEB_DIR = ROOT / "web" / "data"
SHARDS = 40


def run() -> None:
    print("Stage 4: building frontend data")
    rows = json.loads(IN_PATH.read_text(encoding="utf-8"))
    parts = Counter(r["rps_id"] for r in rows)

    features, slim, details = [], [], {}
    for r in rows:
        key = r["rps_id"] if parts[r["rps_id"]] == 1 else f"{r['rps_id']}-{r['part']}"
        n = r["niah"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {"key": key, **{k: v for k, v in r.items() if k not in ("lat", "lon")}},
        })
        slim.append({
            "k": key,
            "id": r["rps_id"],
            "a": r["display_address"],
            "n": r["number"],
            "pc": r["postcode"],
            "d": r["description"],
            "ll": [r["lon"], r["lat"]],
            **({"y": built_year(n), "t": n["original_type"], "r": n["rating"], "p": 1 if n["image"] else 0}
               if n else {}),
        })
        if n:
            details[key] = {k: n[k] for k in (
                "reg_no", "name", "date_from", "date_to", "original_type", "in_use_as",
                "rating", "description", "appraisal", "image", "url", "match")}

    GEOJSON_PATH.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                       ensure_ascii=False), encoding="utf-8")
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    compact = {"ensure_ascii": False, "separators": (",", ":")}
    (WEB_DIR / "structures.json").write_text(json.dumps(slim, **compact), encoding="utf-8")
    shards: dict[int, dict] = {}
    for key, d in details.items():
        shards.setdefault(shard_of(key), {})[key] = d
    shard_dir = WEB_DIR / "details"
    shard_dir.mkdir(exist_ok=True)
    for old in shard_dir.glob("*.json"):
        old.unlink()
    for n, part in shards.items():
        (shard_dir / f"{n}.json").write_text(json.dumps(part, **compact), encoding="utf-8")
    for p in (GEOJSON_PATH, WEB_DIR / "structures.json"):
        print(f"  {p.relative_to(ROOT)}  {p.stat().st_size / 1e6:.1f} MB")
    print(f"  {shard_dir.relative_to(ROOT)}/  {len(shards)} shards, "
          f"{sum(f.stat().st_size for f in shard_dir.glob('*.json')) / 1e6:.1f} MB total")


def built_year(n: dict) -> int | None:
    """NIAH dates are a range (1770-1790); show its middle, to the decade."""
    start, end = n["date_from"], n["date_to"]
    if not start:
        return None
    return int((start + end) / 20 + 0.5) * 10 if end else start


def shard_of(key: str) -> int:
    """Which details shard a row lives in; app.js computes the same thing."""
    return int(key.split("-")[0]) % SHARDS
