"""Stage 2 — clean the RPS CSV into typed records.

- Decodes the CSV as Windows-1252 (it is not UTF-8).
- Repairs street numbers Excel turned into dates: "07-Aug" was "7-8" and
  "Dec-13" was "12-13" (Excel reads "d-m" as a day and month, and "m-yy" as a
  month and year when the second number can't be a day).
- Tidies postcodes ("Dublin 6w" -> "Dublin 6W", stray spaces).
- Converts Irish Grid easting/northing to WGS84 lat/lon.

One RPS_ID can span several rows (a complex such as Trinity College has one
row per building, each with its own point), so every row keeps its own record
and `part` numbers the rows within an RPS_ID.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

from .irish_grid import to_wgs84

DATA = Path(__file__).resolve().parent.parent / "data"
RAW_PATH = DATA / "raw" / "rps.csv"
OUT_PATH = DATA / "normalized.json"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
DAY_MONTH = re.compile(r"^(\d{1,2})-([A-Za-z]{3})$")    # "07-Aug" -> 7-8
MONTH_YEAR = re.compile(r"^([A-Za-z]{3})-(\d{2})$")      # "Dec-13" -> 12-13


def repair_number(raw: str) -> tuple[str, bool]:
    """Undo Excel's date conversion. Returns (number, was_repaired)."""
    s = raw.strip()
    m = DAY_MONTH.match(s)
    if m and m.group(2).lower() in MONTHS:
        return f"{int(m.group(1))}-{MONTHS[m.group(2).lower()]}", True
    m = MONTH_YEAR.match(s)
    if m and m.group(1).lower() in MONTHS:
        return f"{MONTHS[m.group(1).lower()]}-{int(m.group(2))}", True
    return s, False


def clean_postcode(raw: str) -> str:
    s = re.sub(r"\s+", " ", raw).strip()
    s = re.sub(r"(\d)w\b", r"\1W", s)
    return s if s.lower().startswith("dublin") else ""


def run() -> None:
    print("Stage 2: normalising RPS records")
    with RAW_PATH.open(encoding="cp1252", newline="") as f:
        rows = list(csv.DictReader(f))

    records = []
    parts: Counter[str] = Counter()
    repaired = 0
    for row in rows:
        rps_id = row["RPS_ID"].strip()
        parts[rps_id] += 1
        number, fixed = repair_number(row["STREET_NUMBER"])
        repaired += fixed
        easting, northing = float(row["IG_EASTING"]), float(row["IG_NORTHING"])
        lat, lon = to_wgs84(easting, northing)
        address = row["Address Full"].strip()
        records.append({
            "rps_id": rps_id,
            "part": parts[rps_id],
            "number": number,
            "number_raw": row["STREET_NUMBER"] if fixed else None,
            "address": address,
            "display_address": f"{number} {address}" if number else address,
            "postcode": clean_postcode(row["Post Code"]),
            "description": row["DESCRIPTION"].strip(),
            "secondary_description": row["SECONDARY_DESCRIPTION"].strip(),
            "ig_easting": easting,
            "ig_northing": northing,
            "lat": lat,
            "lon": lon,
        })

    OUT_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    multi = sum(1 for n in parts.values() if n > 1)
    print(f"  {len(records):,} rows, {len(parts):,} unique RPS IDs ({multi} spanning several rows)")
    print(f"  repaired {repaired} date-mangled street numbers")
    print(f"  wrote {OUT_PATH}")
