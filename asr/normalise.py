"""Code-mix normalisation (#13): map Telugu-script spellings of English words to one canonical form."""

import json
import re

import config

_ZW = re.compile("[‌‍]")  # ASR output and the glossary differ only by these joiners


def _load() -> list[tuple[str, str]]:
    glossary = json.loads((config.ROOT / "data" / "glossary.json").read_text(encoding="utf-8"))
    return sorted(glossary.items(), key=lambda kv: len(kv[0]), reverse=True)  # longest match first


_PAIRS = _load()


def normalise(text: str) -> str:
    text = _ZW.sub("", text)
    for variant, canonical in _PAIRS:
        text = text.replace(variant, canonical)
    return text
