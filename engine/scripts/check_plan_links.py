"""Open every link in the plan cards (ways to apply, handoffs, sources) and list the ones
that don't load. Run before re-verifying cards; a page that moved means the card needs a
fresh read, not just a new URL.

Run: uv run python scripts/check_plan_links.py   (exit 1 if any page is gone)
"""

import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unclaimed_engine import plans  # noqa: E402

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; unclaimed-link-check)"}
# Some agency sites (SSA, the FCC's Lifeline site, the IRS site locator) refuse scripts but
# open in a browser: these answers mean "open it by hand", not "gone".
REFUSED = {"401", "403", "429", "ConnectError", "ConnectTimeout", "ReadTimeout"}
MOVED = "moved"  # redirected to another page: may be the agency's home page or a "not found" page


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
    """None if the page loads where the card says, else what went wrong."""
    try:
        socket.getaddrinfo(urlsplit(url).hostname, 443)
    except socket.gaierror:
        return "no such host"  # the domain is gone: broken for people too
    for attempt in range(2):  # a server error gets one retry
        try:
            r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
        except httpx.HTTPError as e:
            return type(e).__name__
        if r.status_code < 500:
            break
    if r.status_code >= 400:
        return str(r.status_code)
    final, cited = urlsplit(str(r.url)), urlsplit(url)
    same = (final.hostname.removeprefix("www.") == cited.hostname.removeprefix("www.")
            and final.path.rstrip("/").lower() == cited.path.rstrip("/").lower())
    return None if same else MOVED


def main() -> int:
    used = links()
    with ThreadPoolExecutor(8) as pool:
        results = dict(zip(used, pool.map(status, used)))
    gone = {u: s for u, s in results.items() if s and s not in REFUSED and s != MOVED}
    refused = {u: s for u, s in results.items() if s in REFUSED}
    moved = {u: s for u, s in results.items() if s == MOVED}
    for title, found in (("Gone (fix the card)", gone), ("Refused the checker (open by hand)", refused),
                         ("Redirected elsewhere (check the page still says what the card cites)", moved)):
        if found:
            print(title)
        for url, problem in sorted(found.items()):
            print(f"  {problem:>14}  {url}  ({', '.join(sorted(used[url]))})")
    print(f"{len(used) - len(gone) - len(refused) - len(moved)} of {len(used)} links load where cited; {len(gone)} gone; "
          f"{len(refused)} to open by hand; {len(moved)} redirected")
    return 1 if gone else 0


if __name__ == "__main__":
    sys.exit(main())
