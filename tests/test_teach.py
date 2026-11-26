"""Teach the assistant by voice (/teach, /kb/*): draft -> read back -> spoken or tapped yes -> translate, save,
live index update (no restart) -> version history with undo by voice. Also "Make this an FAQ"."""

import json
import zlib
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from coordinator import requests as requests_db
from generation import answer as ans
from kb import store, teach
from retrieval import index

WAV = ("a.wav", b"RIFF0000WAVE", "audio/wav")

KB = [
    {"id": "sched-01", "category": "transfusion_schedule", "question_te": "తర్వాతి ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడు?",
     "question_en": "When is my next transfusion?", "question_hi": "मेरा अगला ट्रांसफ़्यूजन कब है?",
     "answer_te": "శనివారం ఉదయం.", "answer_en": "On Saturday morning.", "answer_hi": "शनिवार सुबह।",
     "source": "Fictional demo record", "authoritative": False},
    {"id": "elig-01", "category": "donor_eligibility", "question_te": "డొనేషన్ల మధ్య ఎంత గ్యాప్?",
     "question_en": "How long between blood donations?", "question_hi": "रक्तदान के बीच कितना अंतर?",
     "answer_te": "90 రోజులు.", "answer_en": "90 days.", "answer_hi": "90 दिन।",
     "source": "G.S.R. 166(E)", "authoritative": False},
    {"id": "gen-01", "category": "general", "question_te": "తలసేమియా అంటే ఏమిటి?",
     "question_en": "What is thalassemia?", "question_hi": "थैलेसीमिया क्या है?",
     "answer_te": "ఒక రక్త వ్యాధి.", "answer_en": "A blood disorder.", "answer_hi": "एक रक्त विकार।",
     "source": "NHS", "authoritative": False},
]
VARIANTS = {"_note": "Extra ways people ask.", "sched-01": ["Transfusion eppudu?"]}

NEW_DRAFT = {
    "action": "new", "entry_id": None, "changed": [], "category": "general",
    "question": "బ్లడ్ వారియర్స్ ఆఫీస్ ఎప్పుడు తెరిచి ఉంటుంది?", "answer": "సోమవారం నుండి శనివారం వరకు.",
    "question_en": "When is the Blood Warriors office open?", "answer_en": "From Monday to Saturday.",
    "phrasings": ["బ్లడ్ వారియర్స్ ఆఫీస్ టైమింగ్స్?", "ब्लड वॉरियर्स ऑफिस कब खुला है?",
                  "Office eppudu open untundi?", "Office kab khulta hai?"],
}


def fake_embed(texts):
    """Bag of words hashed into 64 dims, L2-normalised (same as tests/test_retrieval.py)."""
    vecs = np.zeros((len(texts), 64), dtype="float32")
    for row, text in enumerate(texts):
        for word in text.lower().replace("?", "").split():
            vecs[row, zlib.crc32(word.encode()) % 64] += 1
    return vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)


def fake_translate(messages):
    """The translator's LLM: echo each value with a language tag, in the target script's words."""
    todo = json.loads(messages[1]["content"].split(":\n", 1)[1])
    target = "हिन्दी" if "Hindi" in messages[0]["content"] else "తెలుగు"
    return json.dumps({k: f"{target}: {v}" for k, v in todo.items()}, ensure_ascii=False)


@pytest.fixture
def kb(tmp_path, monkeypatch):
    kb_path, var_path = tmp_path / "entries.json", tmp_path / "question_variants.json"
    store._write_json(kb_path, KB)
    store._write_json(var_path, VARIANTS, compact_lists=True)
    monkeypatch.setattr(config, "KB_PATH", kb_path)
    monkeypatch.setattr(config, "KB_VARIANTS_PATH", var_path)
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    embedded = []
    monkeypatch.setattr(index, "embed", lambda texts: embedded.extend(texts) or fake_embed(texts))
    monkeypatch.setattr(index, "_get_model", lambda: None)
    monkeypatch.setattr(index, "_state", None)
    monkeypatch.setattr("generation.translate._call_llm", fake_translate)
    ans._kb_answer_en.cache_clear()
    index.load()
    embedded.clear()
    yield {"kb": kb_path, "variants": var_path, "embedded": embedded}
    ans._kb_answer_en.cache_clear()


def signed_in() -> TestClient:
    c = TestClient(app)
    assert c.post("/coord/login", data={"code": "2468"}).status_code == 200
    return c


def draft(c, llm_reply, said="New question: office timings. Answer: Monday to Saturday.", lang="te", **form):
    with patch("api.main.transcribe", return_value=said), \
            patch("kb.teach._call_llm", return_value=json.dumps(llm_reply, ensure_ascii=False)) as llm:
        r = c.post("/kb/draft", files={"audio": WAV}, data={"lang": lang, **form})
    return r, llm


# --- the page and access ----------------------------------------------------------------------------------

def test_teach_page_is_served():
    r = TestClient(app).get("/teach")
    assert r.status_code == 200 and 'id="t-main"' in r.text and "/js/teach.js" in r.text and 'id="teachMic"' in r.text


def test_teach_needs_sign_in(kb):
    c = TestClient(app)
    assert c.post("/kb/draft", data={"text": "x"}).status_code == 401
    assert c.post("/kb/confirm", data={"draft_id": "x", "decision": "yes"}).status_code == 401
    assert c.get("/kb/history").status_code == 401


# --- new entry ------------------------------------------------------------------------------------------

def test_new_entry_is_read_back_and_nothing_is_saved(kb):
    c = signed_in()
    before = kb["kb"].read_bytes()
    with patch("api.main.synthesize", return_value="/tmp/readback.mp3") as tts:
        r, llm = draft(c, NEW_DRAFT)
    d = r.json()
    assert r.status_code == 200 and d["kind"] == "new" and d["category"] == "general"
    assert d["question"] == NEW_DRAFT["question"] and d["answer"] == NEW_DRAFT["answer"]
    assert NEW_DRAFT["question"] in d["readback_text"] and NEW_DRAFT["answer"] in d["readback_text"]
    assert d["readback_text"].endswith("దీన్ని సేవ్ చేయమంటారా?") and d["audio_url"] == "/audio/readback.mp3"
    assert tts.call_args.args == (d["readback_text"], "te")
    assert len(d["phrasings"]) == 4 and d["to_coordinator"] is False
    # the LLM saw the transcript and the closest existing entries
    prompt = llm.call_args.args[0][1]["content"]
    assert "office timings" in prompt and "[gen-01]" in prompt
    assert kb["kb"].read_bytes() == before and store.history() == []


def test_yes_saves_in_every_language_and_updates_the_live_index(kb):
    c = signed_in()
    d = draft(c, NEW_DRAFT)[0].json()
    assert index.retrieve("When is the Blood Warriors office open?", k=1)[0]["id"] != "gen-02"

    kb["embedded"].clear()
    r = c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes", "lang": "te"})
    embedded_on_save = list(kb["embedded"])
    body = r.json()
    assert r.status_code == 200 and body["decision"] == "yes" and body["kind"] == "new" and body["entry_id"] == "gen-02"
    assert body["count"] == 4

    saved = store.get("gen-02")
    assert saved["question_te"] == NEW_DRAFT["question"] and saved["answer_te"] == NEW_DRAFT["answer"]  # their words
    assert saved["question_en"] == NEW_DRAFT["question_en"] and saved["answer_en"] == NEW_DRAFT["answer_en"]
    assert saved["question_hi"] == "हिन्दी: " + NEW_DRAFT["question_en"]   # translated from the English
    assert saved["authoritative"] is True and saved["source"].startswith("Blood Warriors coordinator, taught by voice")
    assert list(saved)[:3] == ["id", "category", "question_te"]
    assert store.variants("gen-02") == NEW_DRAFT["phrasings"]

    # same process, no restart: the new entry is searchable, by its question and by a code-mixed phrasing
    assert index.retrieve("When is the Blood Warriors office open?", k=1)[0]["id"] == "gen-02"
    assert index.retrieve("Office kab khulta hai?", k=1)[0]["id"] == "gen-02"
    assert index.get_entry("gen-02")["answer_en"] == NEW_DRAFT["answer_en"]
    assert ans._lookup_answer_en("gen-02") == NEW_DRAFT["answer_en"]
    # only the new phrasings were embedded; the existing vectors were reused
    assert sorted(embedded_on_save) == sorted([saved[f"question_{l}"] for l in ("te", "en", "hi")] + NEW_DRAFT["phrasings"])

    assert kb["kb"].stat().st_mode & 0o777 == 0o644          # saving keeps the file readable as before
    (row,) = store.history()
    assert row["action"] == "create" and row["entry_id"] == "gen-02" and row["before"] is None
    assert row["language"] == "te" and "office timings" in row["said"]
    # the draft is used up
    assert c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes"}).status_code == 404


def test_saved_answer_is_used_by_ask(kb):
    c = signed_in()
    d = draft(c, NEW_DRAFT, lang="en")[0].json()
    c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes", "lang": "en"})
    reply = json.dumps({"answer": "From Monday to Saturday.", "source_id": "gen-02"})
    with patch("generation.answer._call_llm", return_value=reply):
        r = c.post("/ask", data={"text": "When is the Blood Warriors office open?", "lang": "en"}).json()
    assert not r["fallback"] and r["source_id"] == "gen-02" and r["source"].startswith("Blood Warriors coordinator")


@pytest.mark.parametrize("spoken,decision", [("అవును", "yes"), ("हाँ, सेव करो", "yes"), ("yes please", "yes"),
                                             ("వద్దు", "no"), ("change it", "change"), ("hmm", None)])
def test_spoken_reply_to_the_read_back(kb, spoken, decision):
    c = signed_in()
    d = draft(c, NEW_DRAFT)[0].json()
    with patch("api.main.transcribe", return_value=spoken):
        r = c.post("/kb/confirm", files={"audio": WAV}, data={"draft_id": d["draft_id"], "lang": "te"}).json()
    assert r["decision"] == decision and r["heard"] == spoken
    assert (store.get("gen-02") is not None) == (decision == "yes")
    still_there = store.get_draft(d["draft_id"]) is not None
    assert still_there == (decision is None)   # "say again" keeps the draft; yes / no / change use it up


def test_english_coordinator_needs_no_separate_english_text(kb):
    c = signed_in()
    reply = {**NEW_DRAFT, "question": "When is the office open?", "answer": "Monday to Saturday.",
             "question_en": "", "answer_en": ""}
    d = draft(c, reply, lang="en")[0].json()
    assert d["kind"] == "new" and d["readback_text"].startswith("I understood a new question.")
    c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes", "lang": "en"})
    saved = store.get("gen-02")
    assert saved["question_en"] == "When is the office open?" and saved["question_te"].startswith("తెలుగు: ")


# --- edit -------------------------------------------------------------------------------------------------

EDIT = {"action": "edit", "entry_id": "elig-01", "changed": ["answer"], "category": "donor_eligibility",
        "question": "ignored", "answer": "మూడు నెలలు, అంటే 90 రోజులు.", "question_en": "ignored",
        "answer_en": "Three months, that is 90 days.", "phrasings": ["Donation gap entha?"]}


def test_edit_changes_only_what_was_said(kb):
    c = signed_in()
    old = store.get("elig-01")
    d = draft(c, EDIT, said="Change the donation gap answer to three months, that is 90 days")[0].json()
    assert d["kind"] == "edit" and d["entry_id"] == "elig-01" and d["changed"] == ["answer"]
    assert d["question"] == old["question_te"]          # the unchanged question is read back as it is
    assert d["before_answer"] == old["answer_te"] and d["answer"] == EDIT["answer"]
    assert d["readback_text"].startswith("జవాబులో మార్పు అర్థమైంది.")

    c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes", "lang": "te"})
    new = store.get("elig-01")
    assert all(new[f"question_{l}"] == old[f"question_{l}"] for l in ("te", "en", "hi"))
    assert new["answer_te"] == EDIT["answer"] and new["answer_en"] == EDIT["answer_en"]
    assert new["answer_hi"] == "हिन्दी: " + EDIT["answer_en"]          # re-translated, not the stale Hindi
    assert new["source"].startswith("Blood Warriors coordinator, updated by voice") and new["authoritative"] is True
    assert store.variants("elig-01") == ["Donation gap entha?"]
    assert [e["id"] for e in store.entries()] == ["sched-01", "elig-01", "gen-01"]  # replaced in place
    (row,) = store.history()
    assert row["action"] == "edit" and row["before"]["entry"] == old and row["after"]["entry"] == new
    assert index.get_entry("elig-01")["answer_en"] == EDIT["answer_en"]


def test_editing_a_sample_record_keeps_the_sample_label(kb):
    c = signed_in()
    reply = {**EDIT, "entry_id": "sched-01", "answer_en": "On Sunday morning.", "answer": "ఆదివారం ఉదయం."}
    d = draft(c, reply, said="Change next transfusion to Sunday morning")[0].json()
    c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes", "lang": "te"})
    new = store.get("sched-01")
    assert new["source"] == "Fictional demo record" and new["authoritative"] is False


def test_edit_of_an_entry_retrieval_did_not_find_is_unclear(kb):
    c = signed_in()
    r, _ = draft(c, {**EDIT, "entry_id": "made-up-99"})
    assert r.status_code == 200 and r.json()["kind"] == "unclear"
    assert r.json()["text"].startswith("నాకు ప్రశ్న, జవాబు రెండూ దొరకలేదు")


def test_incomplete_draft_is_unclear_not_half_saved(kb):
    c = signed_in()
    r, _ = draft(c, {**NEW_DRAFT, "answer": "", "answer_en": ""})
    assert r.json()["kind"] == "unclear" and "draft_id" not in r.json()


def test_answer_that_asks_people_to_call_is_refused(kb):
    c = signed_in()
    r, _ = draft(c, {**NEW_DRAFT, "answer_en": "Please call the office on Monday."}, lang="en")
    assert r.status_code == 422 and r.json()["error"] == "teach.no_calls"
    assert "no phone calls" in r.json()["text"] and store.history() == []


def test_question_the_safety_gate_catches_is_flagged(kb):
    c = signed_in()
    reply = {**NEW_DRAFT, "question_en": "What if my child has chest pain after transfusion?"}
    assert draft(c, reply)[0].json()["to_coordinator"] is True


def test_draft_errors(kb):
    c = signed_in()
    with patch("api.main.transcribe", return_value="  "):
        assert c.post("/kb/draft", files={"audio": WAV}).json()["detail"] == "no_speech"
    with patch("kb.teach._call_llm", side_effect=TimeoutError()):
        r = c.post("/kb/draft", data={"text": "New question about camps", "lang": "en"})
    assert r.status_code == 502 and r.json()["detail"] == "teach_error"
    with patch("kb.teach._call_llm", return_value="not json"):
        assert c.post("/kb/draft", data={"text": "New question", "lang": "en"}).status_code == 502


def test_long_teaching_clip_gets_the_longer_asr_timeout(kb):
    c = signed_in()
    import api.main as core
    seen, real = [], core._run_stage

    def spy(func, timeout_s, *args):
        seen.append(timeout_s)
        return real(func, timeout_s, *args)
    with patch("api.main._run_stage", side_effect=spy):
        draft(c, NEW_DRAFT)
    assert seen[0] == config.TEACH_ASR_TIMEOUT_S   # the first stage is the transcription


# --- failures never leave a half change --------------------------------------------------------------------

def test_translation_failure_keeps_the_draft_and_saves_nothing(kb, monkeypatch):
    c = signed_in()
    d = draft(c, NEW_DRAFT)[0].json()
    before = kb["kb"].read_bytes()
    monkeypatch.setattr("generation.translate._call_llm", lambda m: (_ for _ in ()).throw(TimeoutError()))
    r = c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes"})
    assert r.status_code == 502 and r.json()["detail"] == "translate_error"
    assert kb["kb"].read_bytes() == before and store.history() == []
    monkeypatch.setattr("generation.translate._call_llm", fake_translate)   # Approve again works
    assert c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes"}).json()["entry_id"] == "gen-02"


def test_index_failure_rolls_the_files_back(kb, monkeypatch):
    c = signed_in()
    d = draft(c, NEW_DRAFT)[0].json()
    kb_before, var_before = kb["kb"].read_bytes(), kb["variants"].read_bytes()
    monkeypatch.setattr(index, "embed", lambda texts: (_ for _ in ()).throw(RuntimeError("model gone")))
    r = c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes"})
    assert r.status_code == 502 and r.json()["detail"] == "save_error"
    assert kb["kb"].read_bytes() == kb_before and kb["variants"].read_bytes() == var_before
    assert store.history() == [] and store.get_draft(d["draft_id"])


# --- undo -------------------------------------------------------------------------------------------------

def save_new(c):
    d = draft(c, NEW_DRAFT)[0].json()
    assert c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes"}).json()["decision"] == "yes"


@pytest.mark.parametrize("said", ["undo the last change", "చివరి మార్పు వెనక్కి తీసుకో", "पिछला बदलाव वापस लो"])
def test_undo_by_voice_removes_a_new_entry(kb, said):
    c = signed_in()
    original = kb["kb"].read_bytes(), kb["variants"].read_bytes()
    save_new(c)
    with patch("api.main.transcribe", return_value=said), patch("kb.teach._call_llm") as llm:
        d = c.post("/kb/draft", files={"audio": WAV}, data={"lang": "te"}).json()
    llm.assert_not_called()                     # recognised without the LLM
    assert d["kind"] == "undo" and d["undo_action"] == "create" and d["question"] == NEW_DRAFT["question"]
    assert d["readback_text"] == f"చివరి మార్పులో ఈ ప్రశ్న జోడించారు: {NEW_DRAFT['question']} దాన్ని వెనక్కి తీసుకోమంటారా?"
    assert store.get("gen-02")                  # nothing undone until yes

    with patch("api.main.transcribe", return_value="అవును"):
        r = c.post("/kb/confirm", files={"audio": WAV}, data={"draft_id": d["draft_id"], "lang": "te"}).json()
    assert r["decision"] == "yes" and r["kind"] == "undo" and r["count"] == 3
    assert store.get("gen-02") is None
    assert (kb["kb"].read_bytes(), kb["variants"].read_bytes()) == original   # byte for byte
    assert index.retrieve("When is the Blood Warriors office open?", k=1)[0]["id"] != "gen-02"
    assert index.get_entry("gen-02") is None

    undo_row, create_row = store.history()
    assert undo_row["action"] == "undo" and undo_row["undo_of"] == create_row["id"] and create_row["undone_at"]
    # nothing left to undo
    r = c.post("/kb/draft", data={"action": "undo", "lang": "en"}).json()
    assert r["kind"] == "nothing" and r["text"] == "There is no change to undo."


def test_undo_button_puts_back_the_old_answer(kb):
    c = signed_in()
    old = store.get("elig-01")
    d = draft(c, EDIT)[0].json()
    c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes"})
    u = c.post("/kb/draft", data={"action": "undo", "lang": "en"}).json()
    assert u["kind"] == "undo" and u["undo_action"] == "edit" and u["before_answer"] == old["answer_en"]
    assert "put back the earlier answer" in u["readback_text"]
    c.post("/kb/confirm", data={"draft_id": u["draft_id"], "decision": "yes"})
    assert store.get("elig-01") == old and store.variants("elig-01") == []
    assert index.get_entry("elig-01")["answer_en"] == "90 days."


def test_undo_twice_steps_further_back(kb):
    c = signed_in()
    save_new(c)
    d = draft(c, EDIT)[0].json()
    c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes"})
    for expected in ("elig-01", "gen-02"):
        u = c.post("/kb/draft", data={"action": "undo"}).json()
        assert u["entry_id"] == expected
        c.post("/kb/confirm", data={"draft_id": u["draft_id"], "decision": "yes"})
    assert [e["id"] for e in store.entries()] == ["sched-01", "elig-01", "gen-01"]
    assert store.get("elig-01") == KB[1]


def test_undo_draft_goes_stale_if_something_else_changed(kb):
    c = signed_in()
    save_new(c)
    u = c.post("/kb/draft", data={"action": "undo"}).json()
    d = draft(c, EDIT)[0].json()
    c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes"})
    r = c.post("/kb/confirm", data={"draft_id": u["draft_id"], "decision": "yes", "lang": "en"})
    assert r.status_code == 409 and r.json()["error"] == "stale" and store.get("gen-02")


def test_no_to_undo_keeps_the_change(kb):
    c = signed_in()
    save_new(c)
    u = c.post("/kb/draft", data={"action": "undo"}).json()
    r = c.post("/kb/confirm", data={"draft_id": u["draft_id"], "decision": "no", "lang": "en"}).json()
    assert r["decision"] == "no" and r["text"] == "Okay, nothing was undone." and store.get("gen-02")


# --- "Make this an FAQ" from the dashboard -----------------------------------------------------------------

def test_make_this_an_faq_from_a_replied_request(kb):
    c = signed_in()
    ref = requests_db.create("ఆఫీస్ ఎప్పుడు తెరిచి ఉంటుంది?", "te", "not_covered")["reference"]
    assert c.post("/kb/draft", data={"from_ref": ref, "lang": "en"}).status_code == 409   # no reply yet
    requests_db.save_reply(ref, "Monday to Saturday, 10 to 5.", "సోమవారం నుండి శనివారం.", None)

    reply = {**NEW_DRAFT, "question": "When is the office open?", "answer": "Monday to Saturday, 10 to 5."}
    with patch("kb.teach._call_llm", return_value=json.dumps(reply)) as llm:
        d = c.post("/kb/draft", data={"from_ref": ref.lower(), "lang": "en"}).json()
    prompt = llm.call_args.args[0][1]["content"]
    assert "ఆఫీస్ ఎప్పుడు తెరిచి ఉంటుంది?" in prompt and "Monday to Saturday, 10 to 5." in prompt
    assert "without anything about this one family" in prompt
    assert d["kind"] == "new" and d["from_ref"] == ref
    c.post("/kb/confirm", data={"draft_id": d["draft_id"], "decision": "yes"})
    assert store.history()[0]["from_ref"] == ref
    assert c.get("/kb/history?lang=en").json()["changes"][0]["from_ref"] == ref
    assert c.post("/kb/draft", data={"from_ref": "BW-0000"}).status_code == 404
    with patch("kb.teach._call_llm", return_value=json.dumps({"action": "unclear"})):
        r = c.post("/kb/draft", data={"from_ref": ref, "lang": "en"}).json()
    assert r["kind"] == "unclear" and r["text"].startswith("I could not make a general FAQ from this reply.")


# --- history ----------------------------------------------------------------------------------------------

def test_history_lists_changes_in_the_coordinators_language(kb):
    c = signed_in()
    h = c.get("/kb/history").json()
    assert h == {"changes": [], "count": 3, "can_undo": False}
    save_new(c)
    u = c.post("/kb/draft", data={"action": "undo"}).json()
    c.post("/kb/confirm", data={"draft_id": u["draft_id"], "decision": "yes"})
    h = c.get("/kb/history?lang=hi").json()
    assert [x["action"] for x in h["changes"]] == ["undo", "create"]
    assert h["changes"][1]["undone"] and h["changes"][0]["undo_of_action"] == "create"
    assert h["changes"][1]["question"] == "हिन्दी: " + NEW_DRAFT["question_en"]
    assert h["count"] == 3 and h["can_undo"] is False


# --- unit: the draft checks ---------------------------------------------------------------------------------

def test_check_cleans_the_llm_draft(kb):
    d = teach.check({**NEW_DRAFT, "category": "parking", "phrasings": [
        "  a  ", "A", NEW_DRAFT["question_en"], "b", "c", "d", "e"]}, "te", set())
    assert d["category"] == "general" and d["phrasings"] == ["a", "b", "c", "d"]
    assert teach.check({"action": "dance"}, "en", set())["action"] == "unclear"
    en = teach.check({**NEW_DRAFT, "question": "Q?", "answer": "A.", "question_en": "", "answer_en": ""}, "en", set())
    assert (en["question_en"], en["answer_en"]) == ("Q?", "A.")


def test_is_undo_only_for_short_requests():
    assert teach.is_undo("Undo the last change") and teach.is_undo("अनडू करो")
    assert not teach.is_undo("New question: when is the camp? Answer: we will undo the booking if it rains, on Sunday")
    assert not teach.is_undo("New question about HPLC")


def test_next_id_follows_the_category_prefix(kb):
    assert store.next_id("donor_eligibility") == "elig-02"
    assert store.next_id("hplc_testing") == "hplc-01"
