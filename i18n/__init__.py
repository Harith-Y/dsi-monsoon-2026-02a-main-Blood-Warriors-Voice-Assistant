"""One translations file for every user-facing string: i18n/strings.json.

The server uses t(key, lang, **fields); the web UI fetches the same file from GET /i18n/strings.json.
"""

import json
from functools import lru_cache
from pathlib import Path

STRINGS_PATH = Path(__file__).resolve().parent / "strings.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(STRINGS_PATH.read_text(encoding="utf-8"))


def languages() -> dict:
    return _data()["languages"]


def t(key: str, lang: str = "en", **fields) -> str:
    """The string for key in lang (English if that language is missing), with {fields} filled in."""
    entry = _data()["strings"][key]
    text = entry.get(lang) or entry["en"]
    return text.format(**fields) if fields else text
