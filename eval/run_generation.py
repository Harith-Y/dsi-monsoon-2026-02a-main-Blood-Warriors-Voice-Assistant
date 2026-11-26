"""Run every eval question through retrieve + generate_answer; save results/generation.json.

Usage: python eval/run_generation.py [--questions eval/questions.json] [--out results/generation.json]
Needs #2 (kb/entries.json), #5 (retrieval.index) and GROQ_API_KEY. Prefill source for eval/grading.csv (#10).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

EXPECT_FALLBACK_TYPES = {"out_of_scope", "medical"}


def expects_fallback(q: dict) -> bool:
    return q.get("expected_kb_id") is None or q.get("variant_type") in EXPECT_FALLBACK_TYPES


def run(questions: list[dict], retrieve_fn, generate_fn, llm_retries: int = 0, retry_wait_s: float = 20) -> dict:
    """llm_retries: retry a question whose answer came back as llm_error (e.g. Groq's free-tier tokens-per-minute
    limit), waiting retry_wait_s first. Eval only: the API never retries. generate_ms times the last attempt."""
    rows = []
    for q in questions:
        text = q.get("question_te") or q["question_en"]
        hits = retrieve_fn(text, k=config.RETRIEVAL_K)
        for attempt in range(llm_retries + 1):
            t0 = time.perf_counter()
            r = generate_fn(text, hits)
            ms = round((time.perf_counter() - t0) * 1000)
            if r.get("reason") != "llm_error" or attempt == llm_retries:
                break
            time.sleep(retry_wait_s)
        want_fb = expects_fallback(q)
        ids = {h["id"] for h in hits}
        ok = r["fallback"] if want_fb else (not r["fallback"] and r["source_id"] in ids)
        rows.append({
            "id": q["id"], "variant_type": q.get("variant_type"), "question": text,
            "expected_kb_id": q.get("expected_kb_id"), "expects_fallback": want_fb,
            "top_hits": [{"id": h["id"], "score": round(h["score"], 3)} for h in hits],
            "answer": r["answer"], "source_id": r["source_id"], "fallback": r["fallback"],
            "reason": r.get("reason"), "generate_ms": ms, "llm_attempts": attempt + 1, "ok": ok,
        })
    answered = [r for r in rows if not r["fallback"]]
    summary = {
        "total": len(rows),
        "answers_without_valid_source": sum(1 for r in answered if not r["source_id"]),
        "fallback_expected_but_answered": [r["id"] for r in rows if r["expects_fallback"] and not r["fallback"]],
        "answer_expected_but_fallback": [r["id"] for r in rows if not r["expects_fallback"] and r["fallback"]],
        "wrong_source": [r["id"] for r in answered if not r["expects_fallback"] and r["source_id"] != r["expected_kb_id"]],
        "llm_errors": [r["id"] for r in rows if r["reason"] == "llm_error"],
        "passed": sum(r["ok"] for r in rows),
    }
    return {"summary": summary, "results": rows}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--questions", default=str(ROOT / "eval" / "questions.json"))
    p.add_argument("--out", default=str(ROOT / "results" / "generation.json"))
    p.add_argument("--llm-retries", type=int, default=6, help="retries per question after an llm_error (rate limit)")
    p.add_argument("--retry-wait", type=float, default=20, help="seconds to wait before each retry")
    a = p.parse_args()
    from generation.answer import generate_answer
    from retrieval.index import retrieve  # built in #5

    questions = json.loads(Path(a.questions).read_text(encoding="utf-8"))
    out = run(questions, retrieve, generate_answer, a.llm_retries, a.retry_wait)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
