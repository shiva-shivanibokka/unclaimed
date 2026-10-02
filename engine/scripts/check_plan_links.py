"""Open every link in the plan cards (ways to apply, handoffs, sources) and list the ones
that don't load. Run before re-verifying cards; a page that moved means the card needs a
fresh read, not just a new URL.

Run: uv run python scripts/check_plan_links.py   (exit 1 if any page is gone)
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unclaimed_engine import plans  # noqa: E402

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; unclaimed-link-check)"}
# Some agency sites (SSA, the FCC's Lifeline site, the IRS site locator) refuse scripts but
# open in a browser: these answers mean "open it by hand", not "gone".
REFUSED = {"401", "403", "429", "ConnectError", "ConnectTimeout", "ReadTimeout"}


def links() -> dict[str, set[str]]:
    """url -> where it's used."""
    channels, cards = plans.load()
    used: dict[str, set[str]] = {}
    for cid, ch in channels.items():
        for url in (ch["url"], ch["source"]):
            used.setdefault(url, set()).add(f"channels.yaml:{cid}")
    for (state, cid), card in cards.items():
        for url in (card["handoff"], *card["sources"]):
            used.setdefault(url, set()).add(f"{state}/{cid}")
    return used


def status(url: str) -> str | None:
    """None if the page loads, else what went wrong."""
    try:
        r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
    except httpx.HTTPError as e:
        return type(e).__name__
    return None if r.status_code < 400 else str(r.status_code)


def main() -> int:
    used = links()
    with ThreadPoolExecutor(8) as pool:
        results = dict(zip(used, pool.map(status, used)))
    gone = {u: s for u, s in results.items() if s and s not in REFUSED}
    refused = {u: s for u, s in results.items() if s in REFUSED}
    for title, found in (("Gone (fix the card)", gone), ("Refused the checker (open by hand)", refused)):
        if found:
            print(title)
        for url, problem in sorted(found.items()):
            print(f"  {problem:>14}  {url}  ({', '.join(sorted(used[url]))})")
    print(f"{len(used) - len(gone) - len(refused)} of {len(used)} links load; {len(gone)} gone; {len(refused)} to open by hand")
    return 1 if gone else 0


if __name__ == "__main__":
    sys.exit(main())
