from unittest.mock import patch

from fastapi.testclient import TestClient

import config
from api.main import app
from i18n import t

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_answer_path():
    hits = [{"id": "sched-01", "score": 0.9, "passage": "sched-01: ..."}]
    result = {"answer": "Telugu answer", "answer_en": "English answer",
              "source_id": "sched-01", "fallback": False}
    with patch("api.main.retrieve", return_value=hits) as mock_retrieve, \
         patch("api.main.generate_answer", return_value=result) as mock_generate, \
         patch("api.main.synthesize", return_value="/tmp/sched-01.mp3"):
        resp = client.post("/ask", data={"text": "Next transfusion eppudu?"})

    body = resp.json()
    assert resp.status_code == 200
    assert body["fallback"] is False
    assert body["source_id"] == "sched-01"
    assert body["answer_te"] == "Telugu answer"
    assert body["audio_url"] == "/audio/sched-01.mp3"
    mock_retrieve.assert_called_once()
    mock_generate.assert_called_once()


def test_urgent_path_skips_retrieval():
    with patch("api.main.retrieve") as mock_retrieve, \
         patch("api.main.generate_answer") as mock_generate:
        resp = client.post("/ask", data={"text": "Naa child ki fever undi, transfusion cheyacha?"})

    body = resp.json()
    assert body["fallback"] is True
    assert body["fallback_reason"] == "urgent"
    assert body["answer_te"].startswith(t("fallback.urgent", "te"))
    assert body["reference"] and body["reference"] in body["answer_te"]
    mock_retrieve.assert_not_called()
    mock_generate.assert_not_called()


def test_low_score_path():
    hits = [{"id": "x", "score": config.CLARIFY_THRESHOLD - 0.1, "passage": "..."}]  # below the #14 clarify band
    with patch("api.main.retrieve", return_value=hits), \
         patch("api.main.generate_answer") as mock_generate:
        resp = client.post("/ask", data={"text": "random unrelated question"})

    body = resp.json()
    assert body["fallback"] is True
    assert body["fallback_reason"] == "low_confidence"
    mock_generate.assert_not_called()


def test_asr_error_path():
    with patch("api.main.transcribe", side_effect=RuntimeError("boom")):
        resp = client.post("/ask", files={"audio": ("clip.wav", b"RIFF....", "audio/wav")})

    body = resp.json()
    assert body["fallback"] is True
    assert body["fallback_reason"] == "asr_error"


def test_generate_fallback_reason_is_passed_through():
    hits = [{"id": "sched-01", "score": 0.9, "passage": "..."}]
    result = {"answer": config.FALLBACK_TE, "source_id": None, "fallback": True, "reason": "llm_error"}
    with patch("api.main.retrieve", return_value=hits), \
         patch("api.main.generate_answer", return_value=result):
        body = client.post("/ask", data={"text": "Next transfusion eppudu?"}).json()

    assert body["fallback"] is True
    assert body["fallback_reason"] == "llm_error"
    assert body["score"] == 0.9


def test_answer_en_comes_from_cited_entry():
    hits = [{"id": "elig-01", "score": 0.8, "passage": "...", "answer_en": "You can donate again from 3 October 2026."},
            {"id": "elig-02", "score": 0.7, "passage": "...", "answer_en": "Men every 90 days."}]
    result = {"answer": "Telugu answer", "source_id": "elig-01", "fallback": False, "reason": None}
    with patch("api.main.retrieve", return_value=hits), \
         patch("api.main.generate_answer", return_value=result), \
         patch("api.main.synthesize", return_value="/tmp/x.mp3"):
        body = client.post("/ask", data={"text": "Nenu blood donate cheyacha?"}).json()

    assert body["answer_en"] == "You can donate again from 3 October 2026."


def test_coordinator_message_is_spoken_too():
    with patch("api.main.retrieve") as mock_retrieve, \
         patch("api.main.synthesize", return_value="/tmp/fallback.mp3") as mock_tts:
        body = client.post("/ask", data={"text": "Naa child ki fever undi, transfusion cheyacha?"}).json()

    assert body["fallback_reason"] == "urgent"
    assert body["audio_url"] == "/audio/fallback.mp3"
    spoken, lang = mock_tts.call_args.args
    assert lang == "te" and spoken.startswith(t("fallback.urgent", "te"))
    # the reference code is spelled out for TTS: BW-1042 -> "B W 1 0 4 2"
    assert " ".join(body["reference"].replace("-", "")) in spoken
    mock_retrieve.assert_not_called()
