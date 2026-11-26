from pathlib import Path

import pytest

import config
from tts import synthesize as tts


def test_cache_hit_skips_network(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TTS_CACHE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(tts, "_gtts", lambda t, o, lang="te": (calls.append((t, lang)), Path(o).write_bytes(b"mp3")))
    p1 = tts.synthesize("నమస్కారం")
    p2 = tts.synthesize("నమస్కారం")
    assert p1 == p2 and Path(p1).exists() and len(calls) == 1


def test_languages_cached_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TTS_CACHE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(tts, "_gtts", lambda t, o, lang="te": (calls.append(lang), Path(o).write_bytes(b"mp3")))
    paths = {lang: tts.synthesize("BW", lang) for lang in ("te", "hi", "en")}
    assert len(set(paths.values())) == 3 and calls == ["te", "hi", "en"]


def test_telugu_cache_key_unchanged():
    """Telugu keeps the pre-multilingual cache key, so the prewarmed demo audio is still a cache hit."""
    import hashlib
    old = hashlib.sha256(f"{config.TTS_PROVIDER}:నమస్కారం".encode()).hexdigest()[:16]
    assert tts._cache_path("నమస్కారం").name == f"{old}.mp3"


def test_unsupported_language_rejected():
    with pytest.raises(ValueError):
        tts.synthesize("hello", "fr")


def test_empty_text_rejected():
    with pytest.raises(ValueError):
        tts.synthesize("  ")


@pytest.mark.live
def test_live_gtts_decodes(tmp_path, monkeypatch):
    import librosa

    monkeypatch.setattr(config, "TTS_CACHE_DIR", tmp_path)
    path = tts.synthesize("మీ తదుపరి ట్రాన్స్‌ఫ్యూజన్ శనివారం ఉదయం తొమ్మిదిన్నరకు.")
    y, sr = librosa.load(path, sr=None)
    assert len(y) / sr > 1
