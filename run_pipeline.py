#!/usr/bin/env python3
"""Dublin Protected Structures — data pipeline orchestrator.

Stages:
  1. fetch     — download DCC's Record of Protected Structures (CSV)
  2. normalize — repair street numbers, convert Irish Grid -> WGS84
  3. niah      — match rows to NIAH records (dates, description, photo)
  4. build     — emit data/structures.geojson + web/data/*.json

Usage:
  python3 run_pipeline.py                  # full run
  python3 run_pipeline.py --from normalize # reuse data/raw/rps.csv

Pure standard library — no pip install required.
"""

from __future__ import annotations

import sys

from pipeline import build, fetch, niah, normalize

STAGES = ["fetch", "normalize", "niah", "build"]


def main(argv: list[str]) -> int:
    start = "fetch"
    if "--from" in argv:
        start = argv[argv.index("--from") + 1]
        if start not in STAGES:
            print(f"Unknown stage '{start}'. Choose from: {', '.join(STAGES)}")
            return 1

    active = STAGES[STAGES.index(start) :]
    print(f"Running stages: {', '.join(active)}\n")

    if "fetch" in active:
        fetch.run()
    if "normalize" in active:
        normalize.run()
    if "niah" in active:
        niah.run()
    if "build" in active:
        build.run()

    print("\nDone. Outputs are in data/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
