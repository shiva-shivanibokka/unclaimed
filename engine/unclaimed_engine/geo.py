"""ZIP -> county from the HUD USPS crosswalk (data/zip_county.csv, built by
scripts/build_zip_county.py). Weighted by residential addresses."""

import csv
from collections import defaultdict
from functools import cache
from pathlib import Path

from policyengine_us.system import system
from policyengine_us.tools.geography.county_helpers import load_county_fips_dataset, map_county_string_to_enum

DATA = Path(__file__).resolve().parents[1] / "data" / "zip_county.csv"
# Use the top county without asking when it holds at least this share of the ZIP's
# residential addresses; otherwise the caller asks which county.
AUTO_ASSIGN = 0.95


@cache
def fips_to_county() -> dict[str, str]:
    """County FIPS -> PolicyEngine county name, from PolicyEngine's own county table (the
    same one its county formula uses), so the two can't disagree."""
    ds = load_county_fips_dataset()
    counties = list(system.variables["county"].possible_values)  # enum indices -> members
    indices = map_county_string_to_enum(ds["county_name"], ds["state"])
    return {fips: counties[i].name for fips, i in zip(ds["county_fips"], indices)}


@cache
def county_fips(county: str) -> str:
    return next(f for f, c in fips_to_county().items() if c == county)


@cache
def state_fips(state: str) -> int:
    """State FIPS code, from the same PolicyEngine county table."""
    return int(next(f for f, c in fips_to_county().items() if c.endswith(f"_{state}"))[:2])


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
