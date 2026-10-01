"""Plan cards (plans/<STATE>/<program>.yaml): what to do next for each program, per state.

Process facts only, cited to the agency and dated; names, amounts and eligibility rules come
from the engine (see plans/README.md). Checked on load, so a bad card stops the engine.
"""

import re
from datetime import date
from functools import cache
from pathlib import Path

import yaml

from .dictionary import _StrictLoader
from .programs import PROGRAMS, SUPPORTED_STATES

PATH = Path(__file__).resolve().parents[2] / "plans"
EVERY_STATE = "US"  # a card whose process is the same in every state
HOW = {"online", "phone", "in_person", "mail", "tax_return", "automatic"}
FIELDS = {"program", "state", "what", "apply", "bring", "next", "watch_out", "handoff", "sources", "last_verified"}
# A program the calculator doesn't model has a card for information only, and its own name.
CARD_ONLY = {"name"}
LISTS = ("bring", "next", "watch_out")
# Amounts and rules belong to the engine, never to a card.
NUMBERS = re.compile(r"\$\s?\d|\d\s?%|\bpercent\b", re.IGNORECASE)


def _https(url) -> bool:
    return isinstance(url, str) and url.startswith("https://")


def _check(card: dict, path: Path) -> None:
    where = f"{path.parent.name}/{path.name}"
    program = next((p for p in PROGRAMS if p.id == card.get("program")), None)
    allowed = FIELDS | (CARD_ONLY if program is None else set())
    if set(card) - allowed or FIELDS - set(card):
        raise ValueError(f"{where}: fields must be {sorted(allowed)}; got {sorted(card)}")
    if (card["state"], card["program"]) != (path.parent.name, path.stem):
        raise ValueError(f"{where}: program/state must match the file's place")
    states = program.states if program else SUPPORTED_STATES
    if card["state"] != EVERY_STATE and card["state"] not in states:
        raise ValueError(f"{where}: {card['program']} isn't in {card['state']}")
    if card["state"] == EVERY_STATE and program and set(program.states) != set(SUPPORTED_STATES):
        raise ValueError(f"{where}: a {EVERY_STATE} card needs a program in every state")
    if not program and not card.get("name"):
        raise ValueError(f"{where}: {card['program']} isn't a calculated program: give it a name")
    if not card["apply"] or not all(a.get("how") in HOW and set(a) <= {"how", "where", "url", "phone"}
                                    and a.get("where") and _https(a.get("url")) for a in card["apply"]):
        raise ValueError(f"{where}: each apply entry needs how ({sorted(HOW)}), where and an https url")
    if not card["sources"] or not all(_https(s) for s in card["sources"]):
        raise ValueError(f"{where}: sources must be https URLs")
    if card["handoff"] not in [a["url"] for a in card["apply"]] + card["sources"]:
        raise ValueError(f"{where}: handoff must be an apply url or a source")
    if not isinstance(card["last_verified"], date):
        raise ValueError(f"{where}: last_verified must be a date")
    texts = [card["what"], *(a["where"] for a in card["apply"]), *(x for f in LISTS for x in card[f])]
    if not all(isinstance(card[f], list) and card[f] for f in LISTS) or not all(isinstance(t, str) for t in texts):
        raise ValueError(f"{where}: {', '.join(LISTS)} must be non-empty lists of text")
    if bad := [t for t in texts if NUMBERS.search(t)]:
        raise ValueError(f"{where}: amounts and rules come from the engine, not a card: {bad[0]!r}")


@cache
def load(path: Path = PATH) -> dict[tuple[str, str], dict]:
    """(state, program) -> card, every card checked."""
    cards = {}
    for f in sorted(path.glob("*/*.yaml")):
        card = yaml.load(f.read_text(encoding="utf-8"), Loader=_StrictLoader)
        _check(card, f)
        cards[(card["state"], card["program"])] = card
    return cards


def for_state(state: str) -> dict[str, dict]:
    """program -> card for one state: its own cards, else the every-state card."""
    cards = load()
    out = {p: c for (s, p), c in cards.items() if s == EVERY_STATE}
    out.update({p: c for (s, p), c in cards.items() if s == state})
    return out
