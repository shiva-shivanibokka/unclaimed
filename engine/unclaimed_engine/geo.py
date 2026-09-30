"""ZIP -> county from the HUD USPS crosswalk (data/zip_county.csv, built by
scripts/build_zip_county.py). Weighted by residential addresses."""

import csv
from collections import defaultdict
from functools import cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "zip_county.csv"
# Use the top county without asking when it holds at least this share of the ZIP's
# residential addresses; otherwise the caller asks which county.
AUTO_ASSIGN = 0.95


@cache
def _table() -> dict[str, list[tuple[str, float]]]:
    table: dict[str, list[tuple[str, float]]] = defaultdict(list)
    with DATA.open() as f:
        for r in csv.DictReader(f):
            table[r["zip"]].append((r["county"], float(r["res_ratio"])))
    return {z: sorted(v, key=lambda c: -c[1]) for z, v in table.items()}


def counties_for_zip(zip_code: str, state: str) -> list[tuple[str, float]]:
    """Counties in `state` that contain residents of the ZIP, largest share first."""
    return [c for c in _table().get(zip_code, []) if c[0].endswith(f"_{state}")]


def resolve_county(zip_code: str, state: str) -> tuple[str | None, list[str]]:
    """(county, candidates). county is None when the ZIP is split and the person must be asked."""
    counties = counties_for_zip(zip_code, state)
    if not counties:
        raise ValueError(f"ZIP {zip_code} has no residential addresses in {state}")
    top, share = counties[0]
    if share >= AUTO_ASSIGN:
        return top, [top]
    return None, [c for c, _ in counties]
