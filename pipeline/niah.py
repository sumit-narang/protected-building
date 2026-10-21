"""Stage 3 — enrich RPS rows from the National Inventory of Architectural Heritage.

NIAH (buildingsofireland.ie) publishes its records as an open ArcGIS feature
service: dates, a written description and appraisal, a rating and a photo per
building. Text is CC-BY 4.0; photos are shown (hotlinked, never stored) with a
credit, which NIAH allows for non-commercial use.

Matching an RPS row to a NIAH record, in order of confidence:
  1. street+number — within 40 m, a shared street word and an overlapping number
  2. street        — within 25 m, a shared street word, no numbers to compare
  3. location      — nearest record within 6 m
Neighbouring protected houses are a median 7.5 m apart, so location alone is
only trusted when it is very close.

Coverage is uneven: the NIAH survey of Dublin 4 and Dublin 6 is not published,
so almost no rows there match.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
IN_PATH = DATA / "normalized.json"
CACHE_PATH = DATA / "cache" / "niah_dcc.json"
OUT_PATH = DATA / "enriched.json"

SERVICE = (
    "https://services-eu1.arcgis.com/HyjXgkV6KGMSF3jt/ArcGIS/rest/services/"
    "NIAHBuildingsOpenData/FeatureServer/0/query"
)
PAGE = 2000
FIELDS = [
    "REG_NO", "NAME", "NUMBER", "STREET1", "STREET2", "ORIGINAL_TYPE", "IN_USE_AS_TYPE",
    "DESCRIPTION", "APPRAISAL", "DATEFROM", "DATETO", "RATING", "LATITUDE", "LONGITUDE",
    "IMAGE_LINK", "WEBSITE_LINK",
]

# Words that say what kind of street it is, not which street.
STREET_STOP = {
    "street", "road", "dublin", "the", "st", "rd", "avenue", "ave", "square", "sq",
    "terrace", "place", "lower", "upper", "north", "south", "east", "west", "great",
    "little", "of", "and", "co", "county", "park", "lane", "quay", "parade", "row",
    "hill", "crescent", "gardens",
}
M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = M_PER_DEG_LAT * math.cos(math.radians(53.34))
CELL = 40.0


def fetch() -> list[dict]:
    """All Dublin City Council records from the NIAH service, cached."""
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    records: list[dict] = []
    offset = 0
    while True:
        params = urllib.parse.urlencode({
            "where": "LOCAL_AUTHORITY_='Dublin City Council'",
            "outFields": ",".join(FIELDS),
            "returnGeometry": "false",
            "orderByFields": "OBJECTID_1",
            "resultOffset": offset,
            "resultRecordCount": PAGE,
            "f": "json",
        })
        req = urllib.request.Request(f"{SERVICE}?{params}", headers={"User-Agent": "protected-building/0.1"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            page = json.load(resp)
        batch = [f["attributes"] for f in page.get("features", [])]
        records += batch
        if len(batch) < PAGE:
            break
        offset += PAGE
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return records


def street_words(text: str) -> set[str]:
    text = (text or "").lower().replace("'", "").replace("’", "").replace("saint", "st")
    return {w for w in re.findall(r"[a-z]+", text) if w not in STREET_STOP and len(w) > 1}


def house_numbers(text: str) -> set[int]:
    """'7-8' -> {7, 8}; '9-9A' -> {9}; '1, 3 & 5' -> {1, 3, 5};
    '1-13 (odd)' -> {1, 3, ..., 13}. Mirrors houseNumbers() in web/app.js."""
    text = text or ""
    out = {int(n) for n in re.findall(r"\d+", text)}
    parity = 1 if re.search(r"\bodd\b", text, re.I) else 0 if re.search(r"\beven\b", text, re.I) else None
    sep = r"(\d+)\s*-\s*(\d+)" if parity is None else r"(\d+)\s*[-/]\s*(\d+)"
    for a, b in re.findall(sep, text):
        a, b = int(a), int(b)
        if 0 < b - a < 60:
            out |= {n for n in range(a, b + 1) if parity is None or n % 2 == parity}
    return out


def xy(lat: float, lon: float) -> tuple[float, float]:
    return lon * M_PER_DEG_LON, lat * M_PER_DEG_LAT


def clean(value) -> str:
    return "" if value in (None, "None") else str(value).strip()


def card(rec: dict, match: str, dist: float) -> dict:
    date_from, date_to = clean(rec["DATEFROM"]), clean(rec["DATETO"])
    return {
        "reg_no": rec["REG_NO"],
        "match": match,
        "distance_m": round(dist, 1),
        "name": clean(rec["NAME"]),
        "address": " ".join(filter(None, [clean(rec["NUMBER"]), clean(rec["STREET1"])])),
        "original_type": clean(rec["ORIGINAL_TYPE"]),
        "in_use_as": clean(rec["IN_USE_AS_TYPE"]),
        "date_from": int(date_from) if date_from.isdigit() else None,
        "date_to": int(date_to) if date_to.isdigit() else None,
        "rating": clean(rec["RATING"]),
        "description": clean(rec["DESCRIPTION"]),
        "appraisal": clean(rec["APPRAISAL"]),
        "image": clean(rec["IMAGE_LINK"]),
        "url": clean(rec["WEBSITE_LINK"]),
    }


def run() -> None:
    print("Stage 3: matching RPS rows to the NIAH inventory")
    niah = [r for r in fetch() if clean(r["LATITUDE"])]
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, rec in enumerate(niah):
        rec["_xy"] = xy(float(rec["LATITUDE"]), float(rec["LONGITUDE"]))
        rec["_words"] = street_words(f"{rec['STREET1']} {rec['STREET2']} {rec['NAME']}")
        rec["_nums"] = house_numbers(clean(rec["NUMBER"]))
        grid[(int(rec["_xy"][0] // CELL), int(rec["_xy"][1] // CELL))].append(i)

    rows = json.loads(IN_PATH.read_text(encoding="utf-8"))
    stats: Counter[str] = Counter()
    for row in rows:
        x, y = xy(row["lat"], row["lon"])
        words = street_words(f"{row['address']} {row['description']}")
        nums = house_numbers(row["number"])
        near = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in grid[(int(x // CELL) + dx, int(y // CELL) + dy)]:
                    d = math.hypot(x - niah[i]["_xy"][0], y - niah[i]["_xy"][1])
                    if d < 40:
                        near.append((d, i))
        near.sort()

        found = None
        for d, i in near:
            rec = niah[i]
            if words & rec["_words"] and nums and rec["_nums"] and nums & rec["_nums"]:
                found = card(rec, "street+number", d)
                break
        if not found:
            for d, i in near:
                rec = niah[i]
                if d < 25 and words & rec["_words"] and not (nums and rec["_nums"]):
                    found = card(rec, "street", d)
                    break
        if not found and near and near[0][0] < 6:
            found = card(niah[near[0][1]], "location", near[0][0])

        row["niah"] = found
        stats[found["match"] if found else "none"] += 1

    OUT_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    matched = len(rows) - stats["none"]
    print(f"  {len(niah):,} NIAH records; matched {matched:,} of {len(rows):,} rows ({matched / len(rows):.0%})")
    for kind in ("street+number", "street", "location", "none"):
        print(f"    {kind:14s} {stats[kind]:5,}")
    print(f"  wrote {OUT_PATH}")
