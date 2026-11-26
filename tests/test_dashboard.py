"""Coordinator dashboard (/dashboard, /coord/*): passcode sign-in by voice or keypad, the queue with LLM
summary and urgency, question audio, voice reply (draft -> read back -> confirm), close/reopen, this week."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from coordinator import auth, stats, triage
from coordinator import requests as requests_db

WAV = ("a.wav", b"RIFF0000WAVE", "audio/wav")


def signed_in() -> TestClient:
    c = TestClient(app)
    assert c.post("/coord/login", data={"code": "2468"}).status_code == 200
    return c


# --- sign in ---------------------------------------------------------------------------------------------

def test_dashboard_page_is_served():
    r = TestClient(app).get("/dashboard")
    assert r.status_code == 200 and 'id="d-login"' in r.text and "/js/dashboard.js" in r.text


def test_coordinator_data_needs_sign_in():
    c = TestClient(app)
    for path in ("/coord/requests", "/coord/stats"):
        assert c.get(path).status_code == 401
    assert c.post("/coord/requests/BW-1/status", data={"status": "closed"}).status_code == 401
    assert c.get("/coord/me").json() == {"configured": True, "signed_in": False}


def test_keypad_sign_in_sets_http_only_cookie():
    c = TestClient(app)
    r = c.post("/coord/login", data={"code": "2468", "lang": "en"})
    assert r.status_code == 200 and r.json()["ok"]
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "2468" not in cookie
    assert c.get("/coord/me").json()["signed_in"] and c.get("/coord/stats").status_code == 200
    c.post("/coord/logout")
    assert c.get("/coord/stats").status_code == 401


@pytest.mark.parametrize("spoken,lang", [("two four six eight", "en"), ("రెండు నాలుగు ఆరు ఎనిమిది", "te"),
                                         ("दो चार छह आठ", "hi"), ("2 4 6 8", "en")])
def test_spoken_passcode(spoken, lang):
    c = TestClient(app)
    with patch("api.main.transcribe", return_value=spoken):
        r = c.post("/coord/login", files={"audio": WAV}, data={"lang": lang})
    assert r.status_code == 200 and c.get("/coord/me").json()["signed_in"]


def test_spoken_passcode_retries_in_english():
    calls = []

    def fake(path, model, lang):
        calls.append(lang)
        return "పాస్‌కోడ్" if lang == "te" else "two four six eight"
    with patch("api.main.transcribe", side_effect=fake):
        r = TestClient(app).post("/coord/login", files={"audio": WAV}, data={"lang": "te"})
    assert r.status_code == 200 and calls == ["te", "en"]


def test_wrong_passcode_is_spoken_and_locks_after_five_tries():
    c = TestClient(app)
    r = c.post("/coord/login", data={"code": "1111", "lang": "hi"})
    assert r.status_code == 401 and r.json()["error"] == "login.wrong" and "पासकोड" in r.json()["text"]
    for _ in range(4):
        c.post("/coord/login", data={"code": "1111"})
    locked = c.post("/coord/login", data={"code": "2468"})
    assert locked.status_code == 429 and locked.json()["error"] == "login.locked"


def test_no_digits_heard():
    with patch("api.main.transcribe", return_value="hello"):
        r = TestClient(app).post("/coord/login", files={"audio": WAV}, data={"lang": "en"})
    assert r.status_code == 422 and r.json()["error"] == "login.no_digits"


@pytest.mark.parametrize("value", ["", "12", "bw-demo"])
def test_sign_in_off_without_a_digit_passcode(monkeypatch, value):
    monkeypatch.setattr(config, "COORDINATOR_PASSCODE", value)
    c = TestClient(app)
    assert c.get("/coord/me").json()["configured"] is False
    assert c.post("/coord/login", data={"code": "12"}).status_code == 503
    assert not auth.valid_session("anything") and not auth.valid_session(None)


def test_changing_the_passcode_signs_everyone_out(monkeypatch):
    c = signed_in()
    monkeypatch.setattr(config, "COORDINATOR_PASSCODE", "9753")
    assert c.get("/coord/stats").status_code == 401


# --- queue -----------------------------------------------------------------------------------------------

def test_queue_lists_open_requests_with_llm_summary_and_urgency():
    a = requests_db.create("Next transfusion date?", "te", "low_confidence")["reference"]
    b = requests_db.create("My child has high fever", "hi", "urgent")["reference"]
    reply = {a: {"summary": {"en": "Asks for next transfusion date", "te": "తదుపరి తేదీ", "hi": "अगली तारीख"},
                 "urgency": "medium"},
             b: {"summary": {"en": "Child has fever", "te": "జ్వరం", "hi": "बुखार"}, "urgency": "low"}}
    with patch.object(triage, "_llm", return_value=json.dumps(reply)) as llm:
        body = signed_in().get("/coord/requests?status=open").json()
        again = signed_in().get("/coord/requests?status=open").json()
    assert llm.call_count == 1                      # stored after the first call
    refs = [r["reference"] for r in body["requests"]]
    assert refs == [b, a]                           # urgent first
    first = body["requests"][0]
    assert first["urgency"] == "high"               # safety flag beats the LLM's "low"
    assert first["summary"]["en"] == "Child has fever" and first["language"] == "hi"
    assert again["requests"][1]["summary"]["te"] == "తదుపరి తేదీ"
    assert body["counts"] == {"open": 2, "replied": 0, "closed": 0}


def test_queue_still_works_when_the_llm_fails():
    ref = requests_db.create("Where is the camp?", "en", "not_covered")["reference"]
    body = signed_in().get("/coord/requests").json()   # conftest makes the LLM raise
    item = body["requests"][0]
    assert item["reference"] == ref and item["summary"] is None and item["question_text"] == "Where is the camp?"
    assert requests_db.get(ref)["summary"] is None     # nothing half-made is stored


def test_triage_rejects_malformed_items():
    items = {"BW-1": {"question": "q", "reason": "urgent"}, "BW-2": {"question": "q"}, "BW-3": {"question": "q"}}
    reply = {"BW-1": {"summary": {"en": "Fever"}, "urgency": "low"}, "BW-2": {"summary": 5}, "BW-3": {"urgency": "x",
             "summary": "Camp location"}}
    with patch.object(triage, "_llm", return_value=json.dumps(reply)):
        out = triage.triage(items)
    assert out == {"BW-1": {"summary": {"en": "Fever"}, "urgency": "high"},
                   "BW-3": {"summary": {"en": "Camp location"}, "urgency": "medium"}}


def test_unknown_status_filter():
    assert signed_in().get("/coord/requests?status=deleted").status_code == 422


def test_question_audio_is_the_caregiver_recording(tmp_path):
    config.REQUEST_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    (config.REQUEST_AUDIO_DIR / "abc.wav").write_bytes(b"RIFFvoice")
    ref = requests_db.create("q", "te", "urgent", "abc.wav")["reference"]
    c = signed_in()
    item = c.get("/coord/requests").json()["requests"][0]
    assert item["question_recorded"] and item["question_audio_url"] == f"/coord/requests/{ref}/audio"
    assert c.get(item["question_audio_url"]).content == b"RIFFvoice"
    assert TestClient(app).get(item["question_audio_url"]).status_code == 401


def test_tapped_question_is_read_aloud(tmp_path):
    spoken = tmp_path / "q.mp3"
    spoken.write_bytes(b"ID3tts")
    ref = requests_db.create("When is the camp?", "en", "not_covered")["reference"]
    with patch("api.main.synthesize", return_value=str(spoken)) as tts:
        r = signed_in().get(f"/coord/requests/{ref}/audio")
    assert r.content == b"ID3tts" and tts.call_args.args == ("When is the camp?", "en")


def test_close_and_reopen():
    ref = requests_db.create("q", "te", "urgent")["reference"]
    c = signed_in()
    assert c.post(f"/coord/requests/{ref}/status", data={"status": "closed"}).json()["status"] == "closed"
    assert c.get("/coord/requests?status=closed").json()["requests"][0]["reference"] == ref
    assert c.post(f"/coord/requests/{ref}/status", data={"status": "open"}).json()["status"] == "open"
    requests_db.save_reply(ref, "src", "reply", None)
    c.post(f"/coord/requests/{ref}/status", data={"status": "closed"})
    assert c.post(f"/coord/requests/{ref}/status", data={"status": "open"}).json()["status"] == "replied"
    assert c.post(f"/coord/requests/{ref}/status", data={"status": "gone"}).status_code == 422
    assert c.post("/coord/requests/BW-0000/status", data={"status": "closed"}).status_code == 404


# --- voice reply -----------------------------------------------------------------------------------------

def test_reply_draft_translates_and_reads_back_without_saving(tmp_path):
    ref = requests_db.create("ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడు?", "te", "low_confidence")["reference"]
    with patch("api.main.transcribe", return_value="Come on Saturday at 10 am") as asr, \
         patch("api.coordinator_routes.translate", return_value={"reply": "శనివారం ఉదయం 10 గంటలకు రండి"}) as tr, \
         patch("api.main.synthesize", return_value=str(tmp_path / "rb.mp3")) as tts:
        d = signed_in().post(f"/coord/requests/{ref}/reply/draft", files={"audio": WAV}, data={"lang": "en"}).json()
    assert asr.call_args.args[2] == "en"                            # coordinator speaks English
    assert tr.call_args.args == ({"reply": "Come on Saturday at 10 am"}, "te", "en")
    assert d["reply_text"] == "శనివారం ఉదయం 10 గంటలకు రండి" and d["reply_lang"] == "te"
    assert d["readback_text"] == "I understood: Come on Saturday at 10 am. Should I send this to the caregiver?"
    assert tts.call_args.args == (d["readback_text"], "en") and d["audio_url"] == "/audio/rb.mp3"
    assert requests_db.get(ref)["status"] == "open" and requests_db.get(ref)["reply_text"] is None


def test_reply_draft_same_language_skips_translation():
    ref = requests_db.create("q", "hi", "urgent")["reference"]
    with patch("api.main.transcribe", return_value="कल आइए"), patch("api.coordinator_routes.translate") as tr:
        d = signed_in().post(f"/coord/requests/{ref}/reply/draft", files={"audio": WAV}, data={"lang": "hi"}).json()
    assert d["reply_text"] == d["source_text"] == "कल आइए" and not tr.called
    assert d["readback_text"].startswith("मैंने समझा: कल आइए")


def test_reply_draft_errors():
    ref = requests_db.create("q", "te", "urgent")["reference"]
    c = signed_in()
    with patch("api.main.transcribe", return_value="  "):
        assert c.post(f"/coord/requests/{ref}/reply/draft", files={"audio": WAV}).json()["detail"] == "no_speech"
    with patch("api.coordinator_routes.translate", side_effect=ValueError("bad")):
        r = c.post(f"/coord/requests/{ref}/reply/draft", data={"text": "come tomorrow", "lang": "en"})
    assert r.status_code == 502 and r.json()["detail"] == "translate_error"
    requests_db.update(ref, status="closed")
    assert c.post(f"/coord/requests/{ref}/reply/draft", data={"text": "x"}).status_code == 409


@pytest.mark.parametrize("said,decision", [("yes", "yes"), ("అవును, పంపండి", "yes"), ("हाँ", "yes"),
                                           ("no", "no"), ("వద్దు", "no"), ("change it", "change"),
                                           ("hmm", None)])
def test_reply_confirm_by_voice(said, decision, tmp_path):
    ref = requests_db.create("q", "te", "urgent")["reference"]
    form = {"source_text": "Come on Saturday", "reply_text": "శనివారం రండి", "lang": "en"}
    with patch("api.main.transcribe", return_value=said), \
         patch("api.main.synthesize", return_value=str(tmp_path / "x.mp3")):
        r = signed_in().post(f"/coord/requests/{ref}/reply/confirm", files={"audio": WAV}, data=form).json()
    assert r["decision"] == decision
    row = requests_db.get(ref)
    if decision == "yes":
        assert row["status"] == "replied" and row["reply_text"] == "శనివారం రండి"
        assert row["reply_source_text"] == "Come on Saturday" and row["reply_audio_path"] == "x.mp3"
        assert "B W" not in r["text"] and ref in r["text"]
    else:
        assert row["status"] == "open" and row["reply_text"] is None


def test_approve_button_saves_and_caregiver_hears_reply(tmp_path):
    ref = requests_db.create("ఎప్పుడు?", "te", "urgent")["reference"]
    c = signed_in()
    with patch("api.main.synthesize", return_value=str(tmp_path / "r.mp3")) as tts:
        r = c.post(f"/coord/requests/{ref}/reply/confirm",
                   data={"decision": "yes", "source_text": "Saturday", "reply_text": "శనివారం", "lang": "en"}).json()
        assert r["decision"] == "yes" and r["request"]["status"] == "replied"
        assert ("శనివారం", "te") in [call.args for call in tts.call_args_list]   # spoken in the caregiver's language
        assert any("B W " in call.args[0] for call in tts.call_args_list)       # code read out letter by letter
        caregiver = TestClient(app).get(f"/requests/{ref}").json()               # "Check my reply"
    assert caregiver["reply_text"] == "శనివారం" and caregiver["status"] == "replied"


def test_confirm_saves_even_if_tts_fails():
    ref = requests_db.create("q", "te", "urgent")["reference"]   # conftest makes TTS fail
    r = signed_in().post(f"/coord/requests/{ref}/reply/confirm",
                         data={"decision": "yes", "source_text": "s", "reply_text": "r"}).json()
    assert r["decision"] == "yes" and requests_db.get(ref)["reply_audio_path"] is None


def test_reply_needs_sign_in():
    ref = requests_db.create("q", "te", "urgent")["reference"]
    c = TestClient(app)
    assert c.post(f"/coord/requests/{ref}/reply/draft", data={"text": "x"}).status_code == 401
    assert c.post(f"/coord/requests/{ref}/reply/confirm",
                  data={"decision": "yes", "source_text": "s", "reply_text": "r"}).status_code == 401
    assert requests_db.get(ref)["status"] == "open"


def test_readback_cannot_be_spoken_through_speak():
    assert TestClient(app).get("/speak?key=reply.readback&lang=en").status_code == 422


# --- this week -------------------------------------------------------------------------------------------

def test_week_starts_monday_india_time():
    # Sunday 20:00 UTC is Monday 01:30 in India.
    sunday_night = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)
    assert stats.week_start(sunday_night).isoformat() == "2026-11-16T00:00:00+05:30"


def test_this_week_numbers():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=30)).isoformat()
    config.LOG_PATH.write_text("\n".join(json.dumps(x) for x in [
        {"timestamp": now.isoformat(), "outcome": "answered", "lang": "te"},
        {"timestamp": now.isoformat(), "outcome": "answered", "lang": "hi"},
        {"timestamp": now.isoformat(), "outcome": "escalated", "lang": "te"},
        {"timestamp": now.isoformat(), "outcome": "clarify", "lang": "en"},
        {"timestamp": old, "outcome": "answered", "lang": "en"},
    ]) + "\nnot json\n", encoding="utf-8")
    a = requests_db.create("q1", "te", "urgent")["reference"]
    requests_db.create("q2", "hi", "urgent")
    requests_db.save_reply(a, "s", "r", None)
    with requests_db.connect() as conn:  # replied 90 minutes after it was asked
        conn.execute("UPDATE requests SET created_at = ?, replied_at = ? WHERE reference = ?",
                     ((now - timedelta(minutes=90)).isoformat(), now.isoformat(), a))
    s = signed_in().get("/coord/stats").json()
    assert s["answered"] == 2 and s["handed_off"] == 2 and s["replied"] == 1 and s["open"] == 1
    assert s["languages"] == {"te": 2, "hi": 1}
    assert s["avg_response_minutes"] == 90.0


def test_this_week_empty():
    s = signed_in().get("/coord/stats").json()
    assert s["answered"] == 0 and s["handed_off"] == 0 and s["avg_response_minutes"] is None and s["languages"] == {}
