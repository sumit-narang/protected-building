"""Stage 1 — download Dublin City Council's Record of Protected Structures.

We use the CSV, not the GeoJSON published alongside it: the GeoJSON's points
were reprojected as if the Irish Grid values were ITM, which puts every
structure in the Atlantic (around 48.8N, 11.9W). The CSV keeps the original
Irish Grid easting/northing, which we convert ourselves in normalize.
Uses only the Python standard library.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

CSV_URL = (
    "https://data.smartdublin.ie/dataset/f1dd00f0-5914-4b97-b66e-0dbb4bcb510c/resource/"
    "f0288278-32e4-4117-803e-9ac10b83a882/download/251218-rps-master-2022-2028_for-gis.csv"
)

RAW_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "rps.csv"


def run() -> None:
    print("Stage 1: downloading the Record of Protected Structures (DCC)")
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(CSV_URL, headers={"User-Agent": "protected-building/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        RAW_PATH.write_bytes(resp.read())
    print(f"  saved {RAW_PATH.stat().st_size:,} bytes to {RAW_PATH}")
