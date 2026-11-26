"""Confidence + clarify tests (#14). `-m live` runs every out-of-scope/medical question through the real
pipeline (LaBSE + Groq) and checks none gets an answer."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import config
from api import main as api_main
from generation.confidence import clarify_prompt, decide

client = TestClient(api_main.app)
HIT = {"id": "sched-01", "question_te": "తదుపరి ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడు?", "question_en": "When is the next transfusion?",
       "passage": "[sched-01] ..."}


def _hits(score: float) -> list[dict]:
    return [dict(HIT, score=score)]


def test_decide_branches():
    assert decide(_hits(config.ANSWER_THRESHOLD)) == "answer"
    assert decide(_hits(config.ANSWER_THRESHOLD - 0.01)) == "clarify"
    assert decide(_hits(config.CLARIFY_THRESHOLD)) == "clarify"
    assert decide(_hits(config.CLARIFY_THRESHOLD - 0.01)) == "fallback"
    assert decide([]) == "fallback"
    no_question = [{"id": "x", "score": config.ANSWER_THRESHOLD - 0.01, "passage": "..."}]
    assert decide(no_question) == "fallback"


def test_decide_clarifies_only_once_per_session():
    mid = _hits((config.ANSWER_THRESHOLD + config.CLARIFY_THRESHOLD) / 2)
    assert decide(mid, {"clarified": False}) == "clarify"
    assert decide(mid, {"clarified": True}) == "fallback"
    assert decide(_hits(0.95), {"clarified": True}) == "answer"


def test_clarify_prompt_uses_top_entry_question():
    te, en = clarify_prompt(HIT)
    assert te == "మీరు అడిగింది ఇదేనా: తదుపరి ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడు?"
    assert en == "Did you mean: When is the next transfusion?"


def _read_log(tmp_path):
    return [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()]


def test_api_clarifies_once_then_hands_off(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "requests.jsonl")
    mid = _hits((config.ANSWER_THRESHOLD + config.CLARIFY_THRESHOLD) / 2)
    with patch("api.main.retrieve", return_value=mid), patch("api.main.generate_answer") as mock_generate:
        first = client.post("/ask", data={"text": "transfusion eppudu", "session_id": "s-test"}).json()
        second = client.post("/ask", data={"text": "transfusion eppudu", "session_id": "s-test"}).json()

    assert first["clarify"] is True and first["fallback"] is False
    assert first["answer_te"].startswith("మీరు అడిగింది ఇదేనా:")
    assert second["clarify"] is False and second["fallback"] is True
    assert second["fallback_reason"] == "low_confidence"
    mock_generate.assert_not_called()
    lines = _read_log(tmp_path)
    assert [line["outcome"] for line in lines] == ["clarify", "escalated"]
    assert lines[1]["fallback_reason"] == "low_confidence"


def test_api_low_score_goes_straight_to_coordinator(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "requests.jsonl")
    with patch("api.main.retrieve", return_value=_hits(config.CLARIFY_THRESHOLD - 0.1)):
        body = client.post("/ask", data={"text": "cricket score enti", "session_id": "s-low"}).json()
    assert body["fallback"] is True and body["fallback_reason"] == "low_confidence"
    assert _read_log(tmp_path)[0]["outcome"] == "escalated"


def _out_of_scope_questions() -> list[dict]:
    questions = json.loads((config.ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    return [q for q in questions if q["expected_behaviour"] == "fallback"]


@pytest.mark.live
@pytest.mark.parametrize("question", _out_of_scope_questions(), ids=lambda q: q["id"])
def test_no_out_of_scope_question_gets_an_answer(question, monkeypatch, tmp_path):
    """Done-when for #14: real retrieval + real LLM; every out-of-scope/medical item ends in fallback or clarify."""
    monkeypatch.setattr(config, "LOG_PATH", tmp_path / "requests.jsonl")
    text = question["question_te"] or question["question_en"]
    with patch("api.main.synthesize", return_value="/tmp/unused.mp3"):
        body = client.post("/ask", data={"text": text, "session_id": f"live-{question['id']}"}).json()
    assert body["fallback"] or body["clarify"], (question["id"], body["source_id"], body["answer_te"])
    # An LLM error (e.g. Groq rate limit) also ends in fallback; it must not count as "the guard worked".
    assert body.get("fallback_reason") != "llm_error", (question["id"], "LLM error, re-run when the rate limit resets")
