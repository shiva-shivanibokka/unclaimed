"""Build data/zip_county.csv (CA + IL) from the HUD USPS ZIP-county crosswalk.

HUD weights each ZIP by the share of residential addresses in each county, which is
what we need: a ZIP that is 99% one town and 1% farmland across a county line should
not trigger a county question. Needs a free token (https://www.huduser.gov/hudapi/public/register,
dataset "USPS Crosswalk") in HUD_API_TOKEN.

Run: uv run python scripts/build_zip_county.py
"""

import csv
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unclaimed_engine.programs import SUPPORTED_STATES as STATES  # noqa: E402

from unclaimed_engine.geo import fips_to_county  # noqa: E402  (PolicyEngine's own FIPS table)

HUD = "https://www.huduser.gov/hudapi/public/usps?type=2&query={state}"
OUT = Path(__file__).resolve().parents[1] / "data" / "zip_county.csv"


def get(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "unclaimed-build", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> None:
    token = os.environ.get("HUD_API_TOKEN")
    if not token:
        sys.exit("HUD_API_TOKEN is not set")

    counties = fips_to_county()
    out, meta = [], None
    for state in STATES:
        data = json.loads(get(HUD.format(state=state), {"Authorization": f"Bearer {token}"}))["data"]
        meta = meta or f"{data['year']}Q{data['quarter']}"
        for r in data["results"]:
            if r["res_ratio"] > 0:
                out.append((r["zip"], counties[r["geoid"]], round(r["res_ratio"], 4)))

    out.sort()
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["zip", "county", "res_ratio"])
        w.writerows(out)
    zips = {z for z, *_ in out}
    print(f"HUD {meta}: {len(zips)} ZIPs with residents, {len(out)} rows -> {OUT}")


if __name__ == "__main__":
    main()
