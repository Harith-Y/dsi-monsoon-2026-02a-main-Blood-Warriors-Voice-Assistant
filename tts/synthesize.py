"""Text-to-speech: Telugu, Hindi or English text -> playable mp3, cached by a hash of the text."""

import hashlib
import logging
from pathlib import Path

import config

log = logging.getLogger(__name__)


# gTTS language and accent per pipeline language; English uses the Indian-English voice.
_GTTS = {"te": {"lang": "te"}, "hi": {"lang": "hi"}, "en": {"lang": "en", "tld": "co.in"}}


def _cache_path(text: str, lang: str = "te") -> Path:
    # Telugu keeps the original key so the existing cache (and prewarmed demo audio) stays valid.
    key_src = f"{config.TTS_PROVIDER}:{text}" if lang == "te" else f"{config.TTS_PROVIDER}:{lang}:{text}"
    key = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:16]
    return config.TTS_CACHE_DIR / f"{key}.mp3"


def _gtts(text: str, out: Path, lang: str = "te") -> None:
    from gtts import gTTS

    gTTS(text=text, timeout=config.TTS_TIMEOUT_S, **_GTTS[lang]).save(str(out))


def synthesize(text: str, lang: str = "te") -> str:
    """Return the path to an mp3 of `text` spoken in lang. Raises on failure (caller handles)."""
    if not text.strip():
        raise ValueError("empty text")
    if lang not in _GTTS:
        raise ValueError(f"unsupported language {lang!r}")
    out = _cache_path(text, lang)
    if out.exists() and out.stat().st_size > 0:
        return str(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    try:
        _gtts(text, tmp, lang)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return str(out)
