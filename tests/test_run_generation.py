from eval.run_generation import run

QS = [
    {"id": "q1", "question_te": "a", "expected_kb_id": "sched-01", "variant_type": "telugu"},
    {"id": "q2", "question_te": "b", "expected_kb_id": None, "variant_type": "out_of_scope"},
    {"id": "q3", "question_te": "c", "expected_kb_id": None, "variant_type": "medical"},
]
HITS = [{"id": "sched-01", "score": 0.7, "passage": "p"}]


def gen_ok(text, hits):
    if text == "a":
        return {"answer": "x", "source_id": "sched-01", "fallback": False, "reason": None}
    return {"answer": "fb", "source_id": None, "fallback": True, "reason": "not_covered"}


def test_all_pass():
    out = run(QS, lambda t, k: HITS, gen_ok)
    assert out["summary"]["passed"] == 3
    assert out["summary"]["fallback_expected_but_answered"] == []
    assert out["summary"]["answers_without_valid_source"] == 0


def test_flags_guessed_answer_on_out_of_scope():
    bad = lambda t, h: {"answer": "x", "source_id": "sched-01", "fallback": False, "reason": None}
    out = run(QS, lambda t, k: HITS, bad)
    assert out["summary"]["fallback_expected_but_answered"] == ["q2", "q3"]


def test_llm_error_is_retried_and_only_last_attempt_counts():
    calls = []

    def flaky(text, hits):
        calls.append(text)
        if len(calls) == 1:
            return {"answer": "fb", "source_id": None, "fallback": True, "reason": "llm_error"}
        return gen_ok(text, hits)

    out = run(QS[:1], lambda t, k: HITS, flaky, llm_retries=2, retry_wait_s=0)
    row = out["results"][0]
    assert row["llm_attempts"] == 2 and row["reason"] is None and row["ok"]
    assert out["summary"]["llm_errors"] == []
