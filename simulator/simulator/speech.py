"""Alexa's voice: Amazon Polly reads each reply aloud in a generative voice (natural and
expressive, unlike the browser's built-in voices). Polly returns a clip only once it
has made all of it, so a reply is said sentence by sentence, all made at the same time: the
wait is one sentence's, not the whole reply's. If Polly fails, the page falls back to the
browser's voice, so a turn never fails for want of audio."""

import base64
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import boto3

from .agent import REGION
from .settings import setting

log = logging.getLogger("unclaimed.simulator")

VOICE = setting("POLLY_VOICE")
ENGINE = setting("POLLY_ENGINE")
# Polly bills per character and the demo is public: a spoken reply is a few sentences, so a
# longer one (a prompt pushing for long answers) gets the browser's voice instead.
MAX_SPOKEN = 600
SHORT = 40  # a sentence shorter than this ("Got it!") is said with the next one

_polly = None
_pool = ThreadPoolExecutor(max_workers=4)


def plain(text: str) -> str:
    """Spoken, not read: drop any markdown a model slips in (bullets, bold, headings)."""
    text = re.sub(r"^\s*([-•]|\d+\.)\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", re.sub(r"[*_#`>]+", "", text)).strip()


def sentences(text: str) -> list[str]:
    """The reply in sentences, short ones joined to the next."""
    out = []
    for s in re.split(r"(?<=[.!?])\s+", text):
        if out and len(out[-1]) < SHORT:
            out[-1] += " " + s
        else:
            out.append(s)
    return [s for s in out if s]


def _say(text: str) -> str:
    r = _polly.synthesize_speech(Text=text, VoiceId=VOICE, Engine=ENGINE, OutputFormat="mp3")
    return base64.b64encode(r["AudioStream"].read()).decode()


def audio(text: str) -> list[str] | None:
    """The reply as base64 MP3 clips, one per sentence, in order; or None (too long, or
    Polly couldn't say it)."""
    global _polly
    if len(text) > MAX_SPOKEN:
        return None
    try:
        _polly = _polly or boto3.client("polly", region_name=REGION)
        return list(_pool.map(_say, sentences(text)))
    except Exception as e:
        log.error("polly failed: %s", type(e).__name__)
        return None
