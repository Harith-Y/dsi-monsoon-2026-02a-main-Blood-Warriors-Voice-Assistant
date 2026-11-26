"""Unit tests never call the real TTS (gTTS needs the network); tests that need audio patch it themselves.
Every test gets its own empty SQLite database and request-audio folder, so nothing touches data/runtime/."""
import sys

import pytest

import config


@pytest.fixture(autouse=True)
def _no_network_tts(monkeypatch, request):
    if "api.main" in sys.modules and "live" not in request.keywords:
        def _fail(text, lang="te"):
            raise RuntimeError("TTS disabled in unit tests")
        monkeypatch.setattr(sys.modules["api.main"], "synthesize", _fail)


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "runtime")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "runtime" / "bw.sqlite3")
    monkeypatch.setattr(config, "REQUEST_AUDIO_DIR", tmp_path / "runtime" / "request_audio")
    monkeypatch.setattr(config, "COORDINATOR_WHATSAPP", "919000000000")  # fictional test number
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "requests.jsonl")  # keep logs/ for real requests


@pytest.fixture(autouse=True)
def _coordinator_defaults(monkeypatch, request):
    """A known test passcode, a clean sign-in failure count, and no real LLM call for the queue summaries
    or teach drafts."""
    monkeypatch.setattr(config, "COORDINATOR_PASSCODE", "2468")
    from coordinator import auth, triage
    auth._failures.clear()
    if "live" not in request.keywords:
        def _no_llm(messages):
            raise RuntimeError("LLM disabled in unit tests")
        monkeypatch.setattr(triage, "_llm", _no_llm)
        from kb import teach
        monkeypatch.setattr(teach, "_call_llm", _no_llm)  # tests that teach patch it with a fixed reply
    if "api.coordinator_routes" in sys.modules:
        monkeypatch.setattr(sys.modules["api.coordinator_routes"], "_triage_retry_at", 0.0)
