"""The simulator's settings: defaults.env (the one place they're defined), unless set in
the environment."""

import os
from pathlib import Path

_DEFAULTS = dict(
    line.split("=", 1) for line in (Path(__file__).parent / "defaults.env").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#"))


def setting(name: str) -> str:
    return os.environ.get(name) or _DEFAULTS[name]
