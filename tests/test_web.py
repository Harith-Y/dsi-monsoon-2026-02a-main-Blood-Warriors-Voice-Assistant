"""The Blood Warriors web UI and the small endpoints it uses: /, /config, /i18n, /speak, /simplify, /intent,
/requests/lookup. Plus static checks on the pages: every string comes from i18n/strings.json, no em dashes,
icon-only buttons have labels, no tel: links."""

import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from coordinator import requests as requests_db
from coordinator.requests import digits_from_speech
from generation.intent import yes_no
from i18n import _data

client = TestClient(app)
WEB = config.ROOT / "web"
PAGES = sorted(WEB.glob("*.html"))
SCRIPTS = sorted((WEB / "js").glob("*.js"))


# --- serving -----------------------------------------------------------------------------------------------

def test_root_serves_blood_warriors_ui_not_gradio():
    r = client.get("/")
    assert r.status_code == 200 and 'id="s-idle"' in r.text and "gradio" not in r.text.lower()
    assert client.get("/css/bw.css").status_code == 200
    assert client.get("/js/app.js").status_code == 200


def test_strings_and_config():
    assert client.get("/i18n/strings.json").json()["strings"]["mic.tap"]["te"]
    c = client.get("/config?lang=hi").json()
    assert c["languages"] == list(config.LANGUAGES)
    assert c["whatsapp_url"].startswith("https://wa.me/919000000000?text=")


def test_api_routes_win_over_static_mount():
    assert client.get("/health").json() == {"status": "ok"}


# --- pages use the translations file ------------------------------------------------------------------------

def _keys_used() -> set[str]:
    keys = set()
    for page in PAGES:
        keys |= set(re.findall(r'data-i18n(?:-aria|-title|-doc)?="([^"]+)"', page.read_text(encoding="utf-8")))
    for js in SCRIPTS:
        src = js.read_text(encoding="utf-8")
        keys |= set(re.findall(r"\bt\('([a-z0-9_.]+)'\s*[,)]", src))
        keys |= set(re.findall(r"(?:title|msg): '([a-z0-9_.]+)'", src))
    return keys


def test_every_ui_key_exists_in_every_language():
    strings = _data()["strings"]
    missing = sorted(k for k in _keys_used() if k not in strings)
    assert missing == []
    for key in _keys_used():
        for lang in config.LANGUAGES:
            assert strings[key].get(lang), f"{key} has no {lang}"


def test_no_hard_coded_visible_text_in_pages():
    """Text between tags must come from data-i18n (the English placeholders are replaced at load)."""
    for page in PAGES:
        html = page.read_text(encoding="utf-8")
        body = re.sub(r"<svg.*?</svg>|<script.*?</script>|<style.*?</style>", "", html.split("<body>", 1)[1], flags=re.S)
        for m in re.finditer(r"<([a-z0-9]+)([^>]*)>([^<]*[A-Za-z][^<]*)<", body):
            tag, attrs, text = m.groups()
            assert "data-i18n" in attrs, f"{page.name}: hard-coded text {text.strip()!r} in <{tag}>"


def test_no_em_dashes_or_tel_links_in_web_files():
    for f in PAGES + SCRIPTS + [WEB / "css" / "bw.css"]:
        text = f.read_text(encoding="utf-8")
        assert "—" not in text, f.name
        assert not re.search(r"href=[\"']te" + "l:", text), f.name


def test_icon_only_buttons_have_labels():
    for page in PAGES:
        for m in re.finditer(r"<button([^>]*)>(.*?)</button>", page.read_text(encoding="utf-8"), flags=re.S):
            attrs, inner = m.groups()
            visible = re.sub(r"<svg.*?</svg>", "", inner, flags=re.S)
            if not re.search(r"data-i18n|[A-Za-z]", re.sub(r"<[^>]+>", "", visible)) and "data-i18n" not in visible:
                assert "aria-label" in attrs or "data-i18n-aria" in attrs, f"{page.name}: unlabeled button {attrs.strip()}"


def test_whatsapp_links_open_in_new_tab():
    for page in PAGES:
        for m in re.finditer(r"<a ([^>]*)>", page.read_text(encoding="utf-8")):
            attrs = m.group(1)
            if "wa" in attrs:
                assert 'target="_blank"' in attrs and 'rel="noopener"' in attrs


# --- endpoints ------------------------------------------------------------------------------------------------

def test_speak_known_keys_only():
    with patch("api.main.synthesize", return_value="/tmp/msg.mp3") as tts:
        ok = client.get("/speak?key=error.network&lang=hi").json()
        ref = client.get("/speak?key=check.open&lang=en&ref=bw 1042").json()
    assert ok["audio_url"] == "/audio/msg.mp3" and "इंटरनेट" in ok["text"]
    assert "BW-1042" in ref["text"] and "B W 1 0 4 2" in tts.call_args.args[0]
    assert client.get("/speak?key=not.a.key").status_code == 404
    assert client.get("/speak?key=check.open&lang=en").status_code == 422


def test_simplify_uses_same_entry():
    with patch("api.main.simplify_answer", return_value="శనివారం రండి.") as simp, \
         patch("api.main.synthesize", return_value="/tmp/s.mp3"):
        body = client.post("/simplify", data={"source_id": "sched-01", "answer": "long", "lang": "te"}).json()
    assert body == {"answer": "శనివారం రండి.", "audio_url": "/audio/s.mp3"}
    assert "[sched-01]" in simp.call_args.args[1]
    assert client.post("/simplify", data={"source_id": "nope", "answer": "x"}).status_code == 404
    with patch("api.main.simplify_answer", return_value=None):
        assert client.post("/simplify", data={"source_id": "sched-01", "answer": "x"}).status_code == 502


def test_clarify_response_carries_question_to_ask():
    hit = {"id": "sched-01", "score": (config.ANSWER_THRESHOLD + config.CLARIFY_THRESHOLD) / 2, "passage": "...",
           "question_te": "తర్వాతి ట్రాన్స్‌ఫ్యూజన్?", "question_en": "When is my next transfusion?",
           "question_hi": "अगला ट्रांसफ़्यूजन कब?"}
    with patch("api.main.retrieve", return_value=[hit]):
        body = client.post("/ask", data={"text": "transfusion", "lang": "hi", "session_id": "web-1"}).json()
    assert body["clarify"] and body["clarify_question"] == "अगला ट्रांसफ़्यूजन कब?"


def test_sample_flag_on_fictional_answers():
    hits = [{"id": "sched-01", "score": 0.9, "passage": "...", "answer_en": "Sat", "source": "Fictional demo record"}]
    result = {"answer": "శనివారం", "source_id": "sched-01", "fallback": False, "reason": None}
    with patch("api.main.retrieve", return_value=hits), patch("api.main.generate_answer", return_value=result):
        assert client.post("/ask", data={"text": "q"}).json()["sample"] is True


@pytest.mark.parametrize("text,expected", [
    ("అవును", "yes"), ("అవునండి, అదే", "yes"), ("हाँ जी", "yes"), ("yes correct", "yes"), ("haan", "yes"),
    ("కాదు", "no"), ("नहीं", "no"), ("no, not that", "no"), ("ledu", "no"),
    ("what is hplc", None), ("", None),
])
def test_yes_no(text, expected):
    assert yes_no(text) == expected


def test_intent_endpoint():
    assert client.post("/intent", data={"text": "అవును", "lang": "te"}).json()["intent"] == "yes"
    with patch("api.main.transcribe", return_value="नहीं"):
        r = client.post("/intent", files={"audio": ("a.wav", b"RIFF", "audio/wav")}, data={"lang": "hi"}).json()
    assert r == {"intent": "no", "transcript": "नहीं"}


@pytest.mark.parametrize("spoken", ["B W one zero four two", "బి డబ్ల్యూ ఒకటి సున్నా నాలుగు రెండు",
                                    "बी डब्ल्यू एक शून्य चार दो", "BW-1042", "bw1042", "౧౦౪౨"])
def test_reference_digits_from_speech(spoken):
    assert digits_from_speech(spoken) == "1042"


def test_lookup_by_voice():
    ref = requests_db.create("q", "te", "urgent")["reference"]
    spoken = " ".join({"0": "సున్నా", "1": "ఒకటి", "2": "రెండు", "3": "మూడు", "4": "నాలుగు", "5": "ఐదు",
                       "6": "ఆరు", "7": "ఏడు", "8": "ఎనిమిది", "9": "తొమ్మిది"}[d] for d in ref[3:])
    with patch("api.main.transcribe", return_value=spoken):
        r = client.post("/requests/lookup", files={"audio": ("a.wav", b"RIFF", "audio/wav")}, data={"lang": "te"}).json()
    assert r["found"] and r["request"]["reference"] == ref and r["request"]["whatsapp_url"]


def test_lookup_retries_in_english_when_no_digits_heard():
    ref = requests_db.create("q", "hi", "urgent")["reference"]
    calls = []

    def fake(path, model, lang):
        calls.append(lang)
        return "कुछ नहीं" if lang == "hi" else f"B W {' '.join(ref[3:])}"
    with patch("api.main.transcribe", side_effect=fake):
        r = client.post("/requests/lookup", files={"audio": ("a.wav", b"RIFF", "audio/wav")}, data={"lang": "hi"}).json()
    assert calls == ["hi", "en"] and r["found"] and r["request"]["reference"] == ref


def test_lookup_not_found():
    r = client.post("/requests/lookup", data={"text": "B W 9 9 9 9", "lang": "en"}).json()
    assert r == {"found": False, "heard": "B W 9 9 9 9", "request": None}
