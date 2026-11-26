import json

import pytest

from generation import answer as ans
from generation.answer import FALLBACK_EN, FALLBACK_TE, generate_answer

PASSAGES = [
    {"id": "sched-01", "score": 0.8, "passage": "[sched-01] తదుపరి రక్త మార్పిడి శనివారం ఉదయం 9:30కి."},
    {"id": "elig-01", "score": 0.5, "passage": "[elig-01] మీ కోఆర్డినేటర్‌ను అడగండి."},
]


@pytest.fixture(autouse=True)
def fake_kb_caption(monkeypatch):
    """Keep unit tests independent of kb/entries.json wording."""
    monkeypatch.setattr(ans, "_lookup_answer_en", lambda sid: f"EN {sid}")


@pytest.fixture
def llm(monkeypatch):
    """Mock the LLM: llm(reply) sets the raw reply; llm.calls counts calls."""
    state = {"reply": "", "calls": 0}

    def fake(messages):
        state["calls"] += 1
        if isinstance(state["reply"], Exception):
            raise state["reply"]
        return state["reply"]

    monkeypatch.setattr(ans, "_call_llm", fake)

    class H:
        calls = property(lambda self: state["calls"])

        def set(self, reply):
            state["reply"] = json.dumps(reply) if isinstance(reply, dict) else reply

    return H()


def test_valid_answer(llm):
    llm.set({"answer": "శనివారం ఉదయం 9:30కి.", "source_id": "sched-01"})
    r = generate_answer("Next transfusion eppudu?", PASSAGES)
    assert r == {"answer": "శనివారం ఉదయం 9:30కి.", "answer_en": "EN sched-01", "source_id": "sched-01",
                 "fallback": False, "reason": None}


def test_no_answer_sentinel(llm):
    llm.set({"answer": "NO_ANSWER", "source_id": None})
    r = generate_answer("Who won the cricket match?", PASSAGES)
    assert r["fallback"] and r["answer"] == FALLBACK_TE and r["source_id"] is None
    assert r["answer_en"] == FALLBACK_EN
    assert r["reason"] == "not_covered"


@pytest.mark.parametrize("reply", [
    {"answer": "ఏదో సమాధానం", "source_id": None},          # no id
    {"answer": "ఏదో సమాధానం", "source_id": "made-up-99"},  # id not among passages
    {"answer": "ఏదో సమాధానం", "source_id": ["sched-01"]},  # wrong type
    {"answer": "", "source_id": "sched-01"},                # empty answer
])
def test_bad_source_is_fallback(llm, reply):
    llm.set(reply)
    assert generate_answer("q", PASSAGES)["fallback"]


@pytest.mark.parametrize("reply", ["not json at all", "[1, 2]", ""])
def test_malformed_output_is_fallback(llm, reply):
    llm.set(reply)
    r = generate_answer("q", PASSAGES)
    assert r["fallback"] and r["reason"] == "llm_error"


def test_api_error_or_timeout_is_fallback(llm):
    llm.set(TimeoutError("timed out"))
    r = generate_answer("q", PASSAGES)
    assert r["fallback"] and r["reason"] == "llm_error"


def test_missing_api_key_is_fallback(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = generate_answer("q", PASSAGES)  # real _call_llm -> KeyError -> fallback
    assert r["fallback"] and r["reason"] == "llm_error"


def test_fever_question_never_reaches_llm(llm):
    llm.set({"answer": "అవును చేయవచ్చు", "source_id": "sched-01"})
    r = generate_answer("Naa child ki fever undi, transfusion cheyacha?", PASSAGES)
    assert r["fallback"] and r["reason"] == "urgent"
    assert llm.calls == 0


def test_no_passages_skips_llm(llm):
    r = generate_answer("Next transfusion eppudu?", [])
    assert r["fallback"] and r["reason"] == "not_covered"
    assert llm.calls == 0


def test_prompt_contains_passages_and_question(monkeypatch):
    seen = {}
    monkeypatch.setattr(ans, "_call_llm", lambda m: seen.setdefault("m", m) and '{"answer":"NO_ANSWER","source_id":null}')
    generate_answer("Next transfusion eppudu?", PASSAGES)
    user = seen["m"][1]["content"]
    assert "[sched-01]" in user and "Next transfusion eppudu?" in user


def test_caption_comes_from_real_kb(monkeypatch):
    import config
    monkeypatch.undo()  # drop the autouse fake: use the real lookup
    ans._kb_answer_en.cache_clear()
    entries = {e["id"]: e for e in json.loads(config.KB_PATH.read_text(encoding="utf-8"))}
    assert ans._lookup_answer_en("sched-01") == entries["sched-01"]["answer_en"]
    assert ans._lookup_answer_en("no-such-id") is None


def test_caption_lookup_never_raises(monkeypatch, tmp_path):
    import config
    monkeypatch.undo()
    monkeypatch.setattr(config, "KB_PATH", tmp_path / "missing.json")
    ans._kb_answer_en.cache_clear()
    assert ans._lookup_answer_en("sched-01") is None
    ans._kb_answer_en.cache_clear()


@pytest.mark.live
def test_live_groq():
    """Needs GROQ_API_KEY. Run: pytest -m live"""
    r = generate_answer("Next transfusion eppudu?", PASSAGES)
    assert r["fallback"] is False and r["source_id"] in {"sched-01", "elig-01"}
    r = generate_answer("Who won the cricket world cup?", PASSAGES)
    assert r["fallback"] is True
