"""Telugu / Hindi / English through the pipeline: ASR routing, answer language, clarify, safety, translation."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from asr import transcribe as asr
from generation import answer as ans
from generation import translate as tr
from generation.confidence import clarify_prompt
from generation.safety import is_urgent
from i18n import _data, t

client = TestClient(app)
HIT = {"id": "sched-01", "score": 0.9, "passage": "[sched-01] ...", "question_te": "ఎప్పుడు?",
       "question_en": "When is my next transfusion?", "question_hi": "मेरा अगला ट्रांसफ़्यूजन कब है?",
       "answer_en": "Saturday.", "source": "Fictional demo record"}


def test_every_string_has_every_language_and_no_em_dash():
    for key, entry in _data()["strings"].items():
        for lang in config.LANGUAGES:
            assert entry.get(lang, "").strip(), f"{key} missing {lang}"
            assert "—" not in entry[lang], f"{key}/{lang} has an em dash"
    assert list(_data()["languages"]) == list(config.LANGUAGES)


def test_english_speech_goes_to_groq_whisper():
    with patch.object(asr, "_groq_whisper", return_value="when is my transfusion") as whisper, \
         patch.object(asr, "_load") as local:
        assert asr.transcribe("x.wav", lang="en") == "when is my transfusion"
    whisper.assert_called_once_with("x.wav", "en")
    local.assert_not_called()


def test_hindi_speech_uses_indicconformer_with_hindi_code(monkeypatch):
    seen = {}
    monkeypatch.setattr(asr, "load_audio", lambda p: __import__("numpy").zeros(1600, dtype="float32"))
    monkeypatch.setattr(asr, "_load", lambda name: seen.setdefault("name", name) and
                        (lambda audio, lang, dec: seen.setdefault("lang", lang) and "नमस्ते"))
    assert asr.transcribe("x.wav", "indicwhisper", lang="hi") == "नमस्ते"
    assert seen == {"name": "indicconformer", "lang": "hi"}


@pytest.mark.parametrize("lang", ["hi", "en"])
def test_ask_passes_language_to_generation_and_tts(lang):
    result = {"answer": "ANSWER", "source_id": "sched-01", "fallback": False, "reason": None, "answer_en": "Saturday."}
    with patch("api.main.retrieve", return_value=[HIT]), \
         patch("api.main.generate_answer", return_value=result) as gen, \
         patch("api.main.synthesize", return_value="/tmp/a.mp3") as tts:
        body = client.post("/ask", data={"text": "next transfusion", "lang": lang}).json()
    assert gen.call_args.args[2] == lang and tts.call_args.args == ("ANSWER", lang)
    assert body["answer"] == "ANSWER" and body["lang"] == lang and body["answer_te"] is None
    assert body["answer_en"] == ("ANSWER" if lang == "en" else "Saturday.")


def test_unknown_language_falls_back_to_default():
    body = client.post("/ask", data={"text": "fever", "lang": "fr"}).json()
    assert body["lang"] == config.DEFAULT_LANG


def test_clarify_in_hindi_uses_hindi_question():
    hi, en = clarify_prompt(HIT, "hi")
    assert hi == "क्या आप यह पूछ रहे हैं: मेरा अगला ट्रांसफ़्यूजन कब है?"
    assert en == "Did you mean: When is my next transfusion?"


def test_system_prompt_names_the_language(monkeypatch):
    seen = {}
    monkeypatch.setattr(ans, "_call_llm", lambda m: seen.setdefault("m", m) and '{"answer":"NO_ANSWER","source_id":null}')
    r = ans.generate_answer("agla transfusion kab hai", [HIT], "hi")
    assert "Hindi sentences" in seen["m"][0]["content"]
    assert r["fallback"] and r["answer"] == ans.FALLBACK["hi"]


@pytest.mark.parametrize("text", ["मेरे बच्चे को बुखार है", "bachche ko bukhar hai", "उसे सांस लेने में तकलीफ़ है",
                                  "ulti ho rahi hai"])
def test_hindi_urgent_terms(text):
    assert is_urgent(text)


@pytest.mark.parametrize("text", ["Ultimately, can I donate blood?", "रक्तदान कब कर सकते हैं?", "Bharat mein HPLC test"])
def test_hindi_terms_do_not_over_trigger(text):
    assert not is_urgent(text)


def test_simplify_answer(monkeypatch):
    monkeypatch.setattr(ans, "_call_llm", lambda m: json.dumps({"answer": "శనివారం రండి."}))
    assert ans.simplify_answer("long answer", "[sched-01] ...", "te") == "శనివారం రండి."
    monkeypatch.setattr(ans, "_call_llm", lambda m: (_ for _ in ()).throw(TimeoutError()))
    assert ans.simplify_answer("long answer", "[sched-01] ...", "te") is None


def test_translate_checks_keys(monkeypatch):
    monkeypatch.setattr(tr, "_call_llm", lambda m: json.dumps({"q": "प्रश्न", "a": "उत्तर"}))
    assert tr.translate({"q": "question", "a": "answer", "empty": ""}, "hi") == {"q": "प्रश्न", "a": "उत्तर", "empty": ""}
    monkeypatch.setattr(tr, "_call_llm", lambda m: json.dumps({"q": "प्रश्न"}))
    with pytest.raises(ValueError):
        tr.translate({"q": "question", "a": "answer"}, "hi")


def test_t_formats_fields():
    assert t("fallback.reference", "en", ref="BW-1042") == "Your reference code is BW-1042."


def test_translate_retries_words_left_in_english_letters(monkeypatch):
    replies = iter(['{"r": "इस Saturday को blood report लाएँ, HPLC भी"}', '{"r": "इस सैटरडे को ब्लड रिपोर्ट लाएँ, HPLC भी"}'])
    seen = []
    monkeypatch.setattr(tr, "_call_llm", lambda messages: seen.append(messages[-1]["content"]) or next(replies))
    assert tr.translate({"r": "Bring the blood report this Saturday, HPLC too"}, "hi") == {"r": "इस सैटरडे को ब्लड रिपोर्ट लाएँ, HPLC भी"}
    assert "Saturday, blood, report" in seen[1] and "HPLC" not in seen[1]   # test names may stay


def test_translate_keeps_first_answer_if_retry_fails(monkeypatch):
    replies = iter(['{"r": "इस Saturday को आएँ"}'])

    def llm(messages):
        try:
            return next(replies)
        except StopIteration:
            raise RuntimeError("rate limited")
    monkeypatch.setattr(tr, "_call_llm", llm)
    assert tr.translate({"r": "Come this Saturday"}, "hi") == {"r": "इस Saturday को आएँ"}
    assert tr.latin_words("BW-1042 HPLC CBC") == []
