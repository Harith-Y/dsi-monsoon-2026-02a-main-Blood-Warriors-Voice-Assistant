"""WhatsApp link, hand-off requests (SQLite) and the 'Check my reply' lookup. conftest gives every test its
own empty database and a fictional coordinator number (919000000000)."""

import re
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from coordinator import requests as requests_db
from coordinator.whatsapp import coordinator_number, whatsapp_url

client = TestClient(app)
LOW = [{"id": "x", "score": config.CLARIFY_THRESHOLD - 0.1, "passage": "...", "question_te": "q"}]


# --- WhatsApp link --------------------------------------------------------------------------------------

def _text(url: str) -> str:
    return parse_qs(urlparse(url).query)["text"][0]


def test_whatsapp_link_format():
    url = whatsapp_url("When is my next transfusion?", "BW-1042")
    assert url.startswith("https://wa.me/919000000000?text=")
    assert " " not in url and "?" not in url.split("?text=")[1]  # fully URL-encoded
    assert _text(url) == "Hello, I asked the Blood Warriors assistant: When is my next transfusion. Reference: BW-1042"


def test_whatsapp_text_round_trips_telugu_and_symbols():
    q = "నా తర్వాతి ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడు & ఎక్కడ #2"
    url = whatsapp_url(q, "BW-77", lang="te")
    encoded = url.split("?text=")[1]
    assert re.fullmatch(r"[A-Za-z0-9%._~-]+", encoded)
    assert q in unquote(encoded) and "BW-77" in unquote(encoded)


def test_whatsapp_number_comes_from_config(monkeypatch):
    monkeypatch.setattr(config, "COORDINATOR_WHATSAPP", "+91 93915-51999")
    assert coordinator_number() == "919391551999"
    assert whatsapp_url().startswith("https://wa.me/919391551999?text=")


def test_whatsapp_without_question_is_generic():
    assert _text(whatsapp_url()) == "Hello, I have a question for the Blood Warriors coordinator."


def test_no_number_configured_means_no_link(monkeypatch):
    monkeypatch.setattr(config, "COORDINATOR_WHATSAPP", "")
    assert whatsapp_url("q", "BW-1") is None


def test_no_tel_links_anywhere():
    """Blood Warriors asked for no phone calls: no tel: link in any code, page, data or translation file."""
    pattern = re.compile("te" + r"l:\s*\+?\d|href=[\"']te" + "l:")
    skip = {".venv", ".git", "node_modules", "__pycache__", ".pytest_cache", "cache"}
    hits = []
    for path in config.ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".js", ".css", ".py", ".json"} \
                and not skip & set(path.relative_to(config.ROOT).parts):
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(path.relative_to(config.ROOT)))
    assert hits == []


# --- requests table --------------------------------------------------------------------------------------

def test_create_and_get_request():
    row = requests_db.create("fever question", "te", "urgent", None)
    assert re.fullmatch(r"BW-\d{4,6}", row["reference"])
    assert row["status"] == "open" and row["language"] == "te" and row["created_at"]
    digits = row["reference"][3:]
    for spoken in (row["reference"], f"bw {digits}", digits, row["reference"].lower()):
        assert requests_db.get(spoken)["id"] == row["id"]
    assert requests_db.get("no digits here") is None


def test_references_are_unique():
    refs = {requests_db.create(f"q{i}", "en", "not_covered")["reference"] for i in range(50)}
    assert len(refs) == 50


def test_reply_and_status_rules():
    ref = requests_db.create("q", "hi", "low_confidence")["reference"]
    row = requests_db.save_reply(ref, "Come on Monday", "सोमवार को आइए", "abc.mp3")
    assert row["status"] == "replied" and row["reply_text"] == "सोमवार को आइए" and row["replied_at"]
    with pytest.raises(ValueError):
        requests_db.update(ref, status="lost")
    with pytest.raises(ValueError):
        requests_db.update(ref, question_text="rewrite history")


# --- /ask hand-off creates a request ---------------------------------------------------------------------

def test_medical_question_creates_request_with_whatsapp_link():
    q = "Naa child ki fever undi, transfusion cheyacha?"
    body = client.post("/ask", data={"text": q}).json()
    assert body["fallback"] and body["fallback_reason"] == "urgent"
    row = requests_db.get(body["reference"])
    assert row["question_text"] == q and row["reason"] == "urgent" and row["status"] == "open"
    assert body["reference"] in body["answer"] and body["reference"] in body["answer_en"]
    assert body["whatsapp_url"].startswith("https://wa.me/919000000000?text=")
    assert body["reference"] in _text(body["whatsapp_url"]) and "fever" in _text(body["whatsapp_url"])


def test_low_confidence_creates_request():
    with patch("api.main.retrieve", return_value=LOW):
        body = client.post("/ask", data={"text": "cricket score?", "lang": "en"}).json()
    assert body["fallback_reason"] == "low_confidence" and body["lang"] == "en"
    assert requests_db.get(body["reference"])["language"] == "en"


def test_answer_does_not_create_request():
    hits = [{"id": "sched-01", "score": 0.9, "passage": "...", "answer_en": "Saturday", "source": "Fictional demo record"}]
    result = {"answer": "శనివారం", "source_id": "sched-01", "fallback": False, "reason": None}
    with patch("api.main.retrieve", return_value=hits), patch("api.main.generate_answer", return_value=result):
        body = client.post("/ask", data={"text": "Next transfusion eppudu?"}).json()
    assert not body["fallback"] and body["reference"] is None
    assert body["source"] == "Fictional demo record"
    assert body["whatsapp_url"] and "Reference" not in _text(body["whatsapp_url"])
    assert requests_db.list_requests() == []


def test_asr_error_and_silence_do_not_create_requests():
    with patch("api.main.transcribe", side_effect=RuntimeError("boom")):
        err = client.post("/ask", files={"audio": ("clip.wav", b"RIFF", "audio/wav")}).json()
    with patch("api.main.transcribe", return_value="   "):
        quiet = client.post("/ask", files={"audio": ("clip.wav", b"RIFF", "audio/wav")}, data={"lang": "hi"}).json()
    assert err["fallback_reason"] == "asr_error" and err["reference"] is None
    assert quiet["fallback_reason"] == "no_speech" and quiet["reference"] is None
    assert "माइक" in quiet["answer"]
    assert requests_db.list_requests() == []


def test_handoff_keeps_question_audio():
    with patch("api.main.transcribe", return_value="నాకు జ్వరం ఉంది"):
        body = client.post("/ask", files={"audio": ("q.wav", b"RIFF-audio", "audio/wav")}).json()
    row = requests_db.get(body["reference"])
    saved = config.REQUEST_AUDIO_DIR / row["question_audio_path"]
    assert saved.read_bytes() == b"RIFF-audio"


def test_answered_question_audio_is_not_kept():
    hits = [{"id": "sched-01", "score": 0.9, "passage": "...", "answer_en": "Saturday"}]
    result = {"answer": "శనివారం", "source_id": "sched-01", "fallback": False, "reason": None}
    with patch("api.main.transcribe", return_value="next transfusion"), \
         patch("api.main.retrieve", return_value=hits), patch("api.main.generate_answer", return_value=result):
        client.post("/ask", files={"audio": ("q.wav", b"RIFF-audio", "audio/wav")})
    assert not config.REQUEST_AUDIO_DIR.exists() or not any(config.REQUEST_AUDIO_DIR.iterdir())


def test_database_failure_still_hands_off():
    with patch("api.main.requests_db.create", side_effect=RuntimeError("disk full")):
        body = client.post("/ask", data={"text": "fever undi", "lang": "en"}).json()
    assert body["fallback"] and body["reference"] is None
    assert "WhatsApp" in body["answer"] and body["whatsapp_url"]


# --- Check my reply --------------------------------------------------------------------------------------

def test_check_reply_lookup():
    ref = requests_db.create("q", "te", "not_covered")["reference"]
    open_body = client.get(f"/requests/{ref.lower()}").json()
    assert open_body["status"] == "open" and open_body["reply_text"] is None
    requests_db.save_reply(ref, "Come Monday", "సోమవారం రండి", None)
    with patch("api.main.synthesize", return_value="/tmp/reply.mp3") as tts:
        body = client.get(f"/requests/{ref[3:]}").json()
    assert body["status"] == "replied" and body["reply_text"] == "సోమవారం రండి"
    assert body["reply_audio_url"] == "/audio/reply.mp3"
    tts.assert_called_once_with("సోమవారం రండి", "te")
    assert client.get("/requests/BW-0").status_code == 404


def test_audio_route_rejects_missing_and_traversal():
    assert client.get("/audio/nope.mp3").status_code == 404
    assert client.get("/audio/..%2Fconfig.py").status_code == 404
