"""Plan cards (plans/): what to do next for each program, per state.

One card per application, naming ways to apply from plans/channels.yaml. Process facts
only, cited to the agency and dated; names, amounts and eligibility rules come from the
engine (see plans/README.md). Checked on load, so a bad card stops the engine.
"""

import re
from datetime import date, timedelta
from functools import cache
from pathlib import Path

import yaml

from .dictionary import _StrictLoader
from .programs import PROGRAMS, SUPPORTED_STATES

PATH = Path(__file__).resolve().parents[2] / "plans"
CHANNELS = "channels.yaml"
EVERY_STATE = "US"  # a card whose process is the same in every state
# Agencies change phone lines, links and steps: a card not re-read within this long fails
# the tests (our decision, defined once).
MAX_AGE_DAYS = 120
HOW = {"online", "phone", "in_person", "mail", "tax_return", "automatic"}
CHANNEL_FIELDS = {"how", "where", "url", "source"}, {"phone"}  # required, optional
CARD_FIELDS = {"programs", "state", "what", "apply", "bring", "next", "watch_out", "handoff", "sources",
               "last_verified"}, {"not_calculated", "name"}
LISTS = ("bring", "next", "watch_out")
# Amounts and rules belong to the engine, never to a card.
NUMBERS = re.compile(r"\$\s?\d|\d\s?%|\bpercent\b", re.IGNORECASE)
CALCULATED = {p.id: p for p in PROGRAMS}


def _https(url) -> bool:
    return isinstance(url, str) and url.startswith("https://")


def _fields(item: dict, spec: tuple[set, set], where: str) -> None:
    required, optional = spec
    if not isinstance(item, dict) or required - set(item) or set(item) - required - optional:
        raise ValueError(f"{where}: fields must be {sorted(required)} (optional {sorted(optional)})")


def _check_channel(cid: str, ch: dict) -> None:
    where = f"{CHANNELS}:{cid}"
    _fields(ch, CHANNEL_FIELDS, where)
    if ch["how"] not in HOW or not _https(ch["url"]) or not _https(ch["source"]) or not isinstance(ch["where"], str):
        raise ValueError(f"{where}: how must be one of {sorted(HOW)}; url and source https")


def _check_card(card: dict, path: Path, channels: dict) -> None:
    where = f"{path.parent.name}/{path.name}"
    _fields(card, CARD_FIELDS, where)
    if card["state"] != path.parent.name:
        raise ValueError(f"{where}: state must match the folder")
    programs = card["programs"]
    if not programs or not all(isinstance(p, str) for p in programs):
        raise ValueError(f"{where}: programs must list program ids")
    outside = [p for p in programs if p not in CALCULATED]
    # A program the calculator doesn't model has a card of its own, with its own name.
    if outside and (len(programs) != 1 or not isinstance(card.get("name"), str)):
        raise ValueError(f"{where}: {outside} isn't a calculated program: give it a card of its own and a name")
    if not outside and "name" in card:
        raise ValueError(f"{where}: names of calculated programs come from the program list")
    for p in programs:
        states = CALCULATED[p].states if p in CALCULATED else SUPPORTED_STATES
        if card["state"] == EVERY_STATE and set(states) != set(SUPPORTED_STATES):
            raise ValueError(f"{where}: a {EVERY_STATE} card needs programs in every state ({p} isn't)")
        if card["state"] != EVERY_STATE and card["state"] not in states:
            raise ValueError(f"{where}: {p} isn't in {card['state']}")
    if not card["apply"] or not all(c in channels for c in card["apply"]):
        raise ValueError(f"{where}: apply must name channels in {CHANNELS}")
    if not card["sources"] or not all(_https(s) for s in card["sources"]):
        raise ValueError(f"{where}: sources must be https URLs")
    if card["handoff"] not in [channels[c]["url"] for c in card["apply"]] + card["sources"]:
        raise ValueError(f"{where}: handoff must be an apply url or a source")
    if not isinstance(card["last_verified"], date):
        raise ValueError(f"{where}: last_verified must be a date")
    lists = (*LISTS, *(["not_calculated"] if "not_calculated" in card else []))
    if not all(isinstance(card[f], list) and card[f] and all(isinstance(t, str) for t in card[f]) for f in lists):
        raise ValueError(f"{where}: {', '.join(lists)} must be non-empty lists of text")
    texts = [card["what"], *(t for f in lists for t in card[f])]
    if bad := [t for t in texts if not isinstance(t, str) or NUMBERS.search(t)]:
        raise ValueError(f"{where}: amounts and rules come from the engine, not a card: {bad[0]!r}")


def _read(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)


@cache
def load(path: Path = PATH) -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    """(channels, (state, card id) -> card), every one checked. A card's id is its file name."""
    channels = _read(path / CHANNELS) if (path / CHANNELS).exists() else {}
    for cid, ch in channels.items():
        _check_channel(cid, ch)
    cards: dict[tuple[str, str], dict] = {}
    covered: dict[tuple[str, str], str] = {}
    for f in sorted(path.glob("*/*.yaml")):
        card = _read(f)
        _check_card(card, f, channels)
        for p in card["programs"]:
            if (card["state"], p) in covered:
                raise ValueError(f"{card['state']}/{f.name}: {p} already has a card ({covered[card['state'], p]})")
            covered[card["state"], p] = f.name
        cards[(card["state"], f.stem)] = card
    return channels, cards


def stale(today: date | None = None) -> list[str]:
    """Cards not verified within MAX_AGE_DAYS."""
    limit = (today or date.today()) - timedelta(days=MAX_AGE_DAYS)
    return [f"{s}/{cid}" for (s, cid), c in load()[1].items() if c["last_verified"] < limit]


def for_state(state: str) -> dict[str, dict]:
    """card id -> card for one state (its own cards, else the every-state card for a
    program), with each way to apply spelled out from its channel and names from the
    program list."""
    channels, cards = load()
    own = {p for (s, _), c in cards.items() if s == state for p in c["programs"]}
    out = {}
    for (s, cid), c in cards.items():
        if s == state or (s == EVERY_STATE and not own & set(c["programs"])):
            out[cid] = {**c, "apply": [{k: v for k, v in channels[a].items() if k != "source"} for a in c["apply"]],
                        "sources": [*c["sources"], *dict.fromkeys(channels[a]["source"] for a in c["apply"])],
                        "names": {p: CALCULATED[p].name_in(state) if p in CALCULATED else c["name"] for p in c["programs"]}}
    return out
