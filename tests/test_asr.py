"""#3: transcribe() returns Telugu text within the latency budget. Skipped if no model or clip is available."""

import time

import pytest

import config

pytest.importorskip("transformers")
clips = sorted(config.AUDIO_DIR.glob("asr01.*"))
if not clips:
    pytest.skip("no sample clip in data/audio/", allow_module_level=True)

from asr.transcribe import _load, transcribe  # noqa: E402


def test_transcribe_returns_telugu_in_budget():
    try:
        _load(config.ASR_MODEL)
    except Exception as e:  # model not downloaded / no HF access
        pytest.skip(f"ASR model not available: {e}")
    t0 = time.perf_counter()
    text = transcribe(clips[0])
    secs = time.perf_counter() - t0
    assert any("ఀ" <= ch <= "౿" for ch in text), f"no Telugu script in: {text!r}"
    assert secs < config.E2E_LATENCY_BUDGET_S


def test_model_is_loaded_once_even_when_questions_arrive_together(monkeypatch):
    """Questions that arrive while the model is loading wait for that one load (a first start once loaded
    the 600M model in five threads at once and the server died)."""
    import threading
    import time

    from asr import transcribe as tr

    monkeypatch.setattr(tr, "_models", {})
    loads = []

    def slow_load(name):
        loads.append(name)
        time.sleep(0.2)
        return object()

    monkeypatch.setattr(tr, "_load_model", slow_load)
    got = []
    threads = [threading.Thread(target=lambda: got.append(tr._load("indicconformer"))) for _ in range(5)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert loads == ["indicconformer"] and len({id(m) for m in got}) == 1
