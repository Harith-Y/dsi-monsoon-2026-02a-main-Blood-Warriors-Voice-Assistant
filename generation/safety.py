"""Safety gate: urgent / medical language goes straight to the coordinator."""
import json
import re
from functools import lru_cache
from pathlib import Path

TERMS_PATH = Path(__file__).resolve().parents[1] / "data" / "safety_terms.json"
_ZERO_WIDTH = dict.fromkeys([0x200B, 0x200C, 0x200D, 0xFEFF])  # ASR often emits these


def _clean(text: str) -> str:
    return text.translate(_ZERO_WIDTH).lower()


@lru_cache(maxsize=1)
def _load() -> tuple[re.Pattern, tuple[str, ...]]:
    data = json.loads(TERMS_PATH.read_text(encoding="utf-8"))
    latin = [_clean(t) for t in data["english"] + data["romanised"]]
    # Telugu and Hindi (Devanagari): substring match, since suffixes attach to the word.
    telugu = tuple(_clean(t) for t in data["telugu"] + data.get("hindi", []))
    # Latin: match at a word start, so "fits" does not fire on "benefits".
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in latin) + ")")
    return pattern, telugu


def is_urgent(text: str) -> bool:
    """True if the text mentions a symptom or emergency. Runs before retrieval and the LLM."""
    pattern, telugu = _load()
    t = _clean(text or "")
    return bool(pattern.search(t)) or any(term in t for term in telugu)
