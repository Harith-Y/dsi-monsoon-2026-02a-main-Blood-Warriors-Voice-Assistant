"""Retrieval tests (#5). Unit tests use a fake embedder and a temporary KB; `-m live` uses real LaBSE."""
import json
import zlib

import numpy as np
import pytest

import config
from eval.run_retrieval import run
from retrieval import index

KB = [
    {"id": "sched-01", "category": "transfusion_schedule", "question_te": "తర్వాతి ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడు",
     "question_en": "when is my next transfusion", "answer_te": "శనివారం", "answer_en": "Saturday", "source": "Fictional demo record"},
    {"id": "elig-02", "category": "donor_eligibility", "question_te": "డొనేషన్ గ్యాప్ ఎంత",
     "question_en": "how long between blood donations", "answer_te": "90 రోజులు", "answer_en": "90 days", "source": "G.S.R. 166(E)"},
    {"id": "hplc-01", "category": "hplc_testing", "question_te": "హెచ్‌పీఎల్‌సీ టెస్ట్ అంటే ఏంటి",
     "question_en": "what is an hplc test", "answer_te": "బ్లడ్ టెస్ట్", "answer_en": "A blood test", "source": "The Blood Project"},
]


def fake_embed(texts):
    """Bag of words hashed into 64 dims, L2-normalised: same words -> same direction."""
    vecs = np.zeros((len(texts), 64), dtype="float32")
    for row, text in enumerate(texts):
        for word in text.lower().replace("?", "").split():
            vecs[row, zlib.crc32(word.encode()) % 64] += 1
    return vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)


@pytest.fixture
def kb(tmp_path, monkeypatch):
    kb_path = tmp_path / "entries.json"
    kb_path.write_text(json.dumps(KB, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "KB_PATH", kb_path)
    monkeypatch.setattr(config, "KB_VARIANTS_PATH", tmp_path / "question_variants.json")  # none by default
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(index, "embed", fake_embed)
    monkeypatch.setattr(index, "_get_model", lambda: None)
    monkeypatch.setattr(index, "_state", None)
    return kb_path


def test_builds_index_when_missing_and_returns_agreed_shape(kb):
    hits = index.retrieve("when is my next transfusion", k=3)
    assert (config.INDEX_DIR / index.INDEX_FILE).exists()
    assert hits[0]["id"] == "sched-01"
    assert hits[0]["cosine"] == pytest.approx(1.0, abs=1e-5)
    assert hits[0]["score"] >= hits[0]["cosine"]  # plus the TF-IDF part
    for hit in hits:
        assert {"id", "score", "passage"} <= hit.keys()
        assert hit["id"] in hit["passage"]
    assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)


def test_ids_are_unique_and_k_respected(kb):
    hits = index.retrieve("hplc test transfusion donations", k=2)
    assert len(hits) == 2
    assert len({h["id"] for h in hits}) == 2


def test_telugu_question_matches_its_entry(kb):
    assert index.retrieve("డొనేషన్ గ్యాప్ ఎంత", k=1)[0]["id"] == "elig-02"


def test_faiss_scores_match_numpy_cosine(kb):
    """Guards the macOS duplicate-OpenMP workaround in retrieval/index.py against silent wrong results."""
    query = "how long between two hplc donations"
    hits = {h["id"]: h["cosine"] for h in index.retrieve(query, k=3)}
    q = fake_embed([query])[0]
    for entry in KB:
        expected = max(float(fake_embed([entry[f]])[0] @ q) for f in index.EMBED_FIELDS if entry.get(f))
        assert hits[entry["id"]] == pytest.approx(expected, abs=1e-5)


def test_rare_topic_word_breaks_a_meaning_tie(kb, monkeypatch):
    """#15: when LaBSE scores entries alike ("can I donate after X?"), the TF-IDF part picks the right X."""
    entries = [dict(KB[1], id="elig-05", question_te="టాటూ తర్వాత డొనేట్ చేయొచ్చా", question_en="can I donate after a tattoo"),
               dict(KB[1], id="elig-12", question_te="మలేరియా తర్వాత డొనేట్ చేయొచ్చా", question_en="can I donate after malaria")]
    kb.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(index, "embed", lambda texts: np.ones((len(texts), 4), dtype="float32") / 2)  # all alike
    hits = index.retrieve("tattoo veyinchukunna, donate cheyocha?", k=2)
    assert [h["id"] for h in hits] == ["elig-05", "elig-12"]
    assert hits[0]["cosine"] == pytest.approx(hits[1]["cosine"])
    assert hits[0]["score"] > hits[1]["score"]


def test_empty_query_returns_nothing(kb):
    assert index.retrieve("   ") == []


def test_index_rebuilt_when_kb_changes(kb):
    index.retrieve("what is an hplc test")
    new_entry = dict(KB[0], id="gen-01", question_te="తలసేమియా అంటే ఏంటి", question_en="what is thalassemia")
    kb.write_text(json.dumps(KB + [new_entry], ensure_ascii=False), encoding="utf-8")
    index._state = None  # a new process
    assert index.retrieve("what is thalassemia", k=1)[0]["id"] == "gen-01"


def test_question_variants_map_to_their_entry(kb):
    config.KB_VARIANTS_PATH.write_text(json.dumps(
        {"_note": "ignored", "hplc-01": ["haemoglobin types blood check", "hplc report meaning"]}), encoding="utf-8")
    hits = index.retrieve("haemoglobin types blood check", k=3)
    assert hits[0]["id"] == "hplc-01"
    assert hits[0]["cosine"] == pytest.approx(1.0, abs=1e-5)
    assert len({h["id"] for h in hits}) == len(hits) == 3  # 4 vectors for hplc-01, still one hit


def test_run_retrieval_metrics():
    questions = [
        {"id": "q1", "question_te": "a", "expected_kb_id": "x", "variant_type": "telugu"},
        {"id": "q2", "question_te": "b", "expected_kb_id": "y", "variant_type": "code_mixed"},
        {"id": "q3", "question_te": "c", "expected_kb_id": None, "variant_type": "out_of_scope"},
    ]
    results = {"a": ["x", "y"], "b": ["x", "y"], "c": ["x"]}

    def fake_retrieve(text, k):
        return [{"id": i, "score": 0.9 - n * 0.1} for n, i in enumerate(results[text])]

    s = run(questions, fake_retrieve)["summary"]
    assert s["in_scope"] == {"n": 2, "hit@1": 0.5, "hit@3": 1.0, "mrr": 0.75}
    assert s["misses_at_1"] == [{"id": "q2", "expected": "y", "got": "x"}]
    assert s["scores"]["out_of_scope_or_medical_top"] == {"q3": 0.9}


@pytest.mark.live
@pytest.mark.parametrize("question, expected", [
    ("Next transfusion eppudu?", "sched-01"),
    ("Nenu blood donate cheyacha? Last time July lo ichanu.", "elig-01"),
    ("HPLC test ante enti?", "hplc-01"),
])
def test_demo_questions_with_labse(question, expected):
    index._state = None
    assert index.retrieve(question, k=3)[0]["id"] == expected
