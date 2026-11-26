"""#10: evaluation scripts with fake models (no ASR, LLM or embeddings needed)."""
import pytest

pytest.importorskip("jiwer")

import config  # noqa: E402
from eval import make_metrics  # noqa: E402
from eval.make_grading import build_rows  # noqa: E402
from eval.run_asr import run as run_asr  # noqa: E402

REFS = [
    {"clip_id": "t01", "file": "t01.wav", "variant": "telugu", "reference_text": "తర్వాతి ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడు", "expected_kb_id": "sched-01"},
    {"clip_id": "c03", "file": "c03.wav", "variant": "code_mixed", "reference_text": "నా చైల్డ్ కి ఫీవర్ ఉంది", "expected_kb_id": "fallback"},
]
HEARD = {"t01.wav": "తర్వాతి ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడో", "c03.wav": "నా చైల్డ్ కి ఫీవర్ ఉంది"}


def fake_retrieve(text, k):
    return [{"id": "sched-01", "score": 0.9}, {"id": "elig-01", "score": 0.5}]


def test_run_asr_scores_and_routes():
    out = run_asr(REFS, lambda path: HEARD[path.name], fake_retrieve)
    s = out["summary"]
    by_clip = {r["clip_id"]: r for r in out["results"]}
    assert by_clip["c03"]["wer"] == 0.0
    assert by_clip["t01"]["wer"] == pytest.approx(1 / 3, abs=1e-3)  # one of three words wrong
    assert by_clip["c03"]["retrieval_asr"]["urgent"] is True  # "ఫీవర్" hits the safety gate
    assert s["retrieval_on_asr_transcript"] == {"in_scope": 1, "hit@1": 1.0, "hit@3": 1.0,
                                                "fallback_clips_routed_to_coordinator": "1/1"}
    assert s["by_variant"]["code_mixed"]["wer"] == 0.0


def test_grading_rows_skip_fallbacks_and_keep_grades():
    gen = {"results": [
        {"id": "q02", "question": "Next transfusion eppudu?", "answer": "శనివారం", "source_id": "sched-01",
         "expected_kb_id": "sched-01", "fallback": False},
        {"id": "q28", "question": "Cricket?", "answer": "fb", "source_id": None, "expected_kb_id": None, "fallback": True},
    ]}
    kb = {"sched-01": {"answer_te": "శనివారం ఉదయం", "answer_en": "Saturday"}}
    existing = {"q02": {"answer": "శనివారం", "correct_1": "Y", "grounded_1": "Y", "grader_1": "A"}}
    rows = build_rows(gen, kb, existing)
    assert [r["id"] for r in rows] == ["q02"]
    assert rows[0]["kb_answer_en"] == "Saturday" and rows[0]["correct_1"] == "Y"
    existing["q02"]["answer"] = "changed answer"  # answer changed since grading: old grade dropped
    assert build_rows(gen, kb, existing)[0]["correct_1"] == ""


def test_metrics_rows_handle_missing_files_and_grades():
    assert make_metrics.asr_rows(None)[0]["value"] == "not run"
    gen = {"results": [
        {"id": "q02", "fallback": False, "source_id": "sched-01", "expected_kb_id": "sched-01", "expects_fallback": False,
         "top_hits": [{"id": "sched-01"}], "reason": None},
        {"id": "q28", "fallback": True, "source_id": None, "expected_kb_id": None, "expects_fallback": True,
         "top_hits": [], "reason": "not_covered"},
    ]}
    rows = {r["metric"]: r for r in make_metrics.generation_rows(gen, [{"correct_1": "Y", "grounded_1": "N"}])}
    assert rows["Answers traceable to a retrieved KB entry (1 answers)"]["met"] == "yes"
    assert rows["Out-of-scope + medical questions sent to coordinator (1)"]["value"] == "100.0%"
    assert rows["Hand grading, grader 1: grounded in the cited entry"]["met"] == "no"
    assert rows["Hand grading, grader 2"]["value"].startswith("pending")
    assert config.E2E_LATENCY_BUDGET_S == 10
