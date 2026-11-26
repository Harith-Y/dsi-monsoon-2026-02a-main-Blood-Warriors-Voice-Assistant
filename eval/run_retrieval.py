"""Retrieval accuracy on eval/questions.json; save results/retrieval.json.

Usage: python eval/run_retrieval.py [--questions eval/questions.json] [--out results/retrieval.json]
In-scope items (expected_kb_id set): hit@1, hit@3, MRR, overall and per variant_type.
Out-of-scope/medical items: their top score, to set the first confidence threshold (#5; tuned in #14).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402


def _metrics(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0, "hit@1": None, "hit@3": None, "mrr": None}
    return {
        "n": n,
        "hit@1": round(sum(r["rank"] == 1 for r in rows) / n, 3),
        "hit@3": round(sum(r["rank"] is not None and r["rank"] <= 3 for r in rows) / n, 3),
        "mrr": round(sum(1 / r["rank"] for r in rows if r["rank"]) / n, 3),
    }


def run(questions: list[dict], retrieve_fn, k: int = 3) -> dict:
    rows = []
    for q in questions:
        text = q.get("question_te") or q["question_en"]
        t0 = time.perf_counter()
        hits = retrieve_fn(text, k=k)
        ms = round((time.perf_counter() - t0) * 1000)
        ids = [h["id"] for h in hits]
        expected = q.get("expected_kb_id")
        rows.append({
            "id": q["id"], "set": q.get("set", "main"), "variant_type": q.get("variant_type"), "question": text,
            "expected_kb_id": expected,
            "rank": ids.index(expected) + 1 if expected in ids else None,
            "top_score": round(hits[0]["score"], 3) if hits else None,
            "top_hits": [{"id": h["id"], "score": round(h["score"], 3)} for h in hits],
            "retrieve_ms": ms,
        })

    in_scope = [r for r in rows if r["expected_kb_id"]]
    no_answer = [r for r in rows if not r["expected_kb_id"]]
    by_variant = {}
    for r in in_scope:
        by_variant.setdefault(r["variant_type"], []).append(r)
    correct_top = [r["top_score"] for r in in_scope if r["rank"] == 1]

    by_set = {}
    for r in in_scope:
        by_set.setdefault(r["set"], []).append(r)

    summary = {
        "in_scope": _metrics(in_scope),
        "by_set": {s: _metrics(rs) for s, rs in sorted(by_set.items())},
        "by_variant": {v: _metrics(rs) for v, rs in sorted(by_variant.items())},
        "misses_at_1": [{"id": r["id"], "expected": r["expected_kb_id"], "got": r["top_hits"][0]["id"] if r["top_hits"] else None}
                        for r in in_scope if r["rank"] != 1],
        "scores": {
            "in_scope_correct_top1_min": min(correct_top) if correct_top else None,
            "in_scope_correct_top1_median": sorted(correct_top)[len(correct_top) // 2] if correct_top else None,
            "out_of_scope_or_medical_top_max": max((r["top_score"] for r in no_answer if r["top_score"] is not None), default=None),
            "out_of_scope_or_medical_top": {r["id"]: r["top_score"] for r in no_answer},
        },
        "answer_threshold": config.ANSWER_THRESHOLD,
    }
    return {"summary": summary, "results": rows}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--questions", default=str(ROOT / "eval" / "questions.json"))
    p.add_argument("--out", default=str(ROOT / "results" / "retrieval.json"))
    a = p.parse_args()
    from retrieval.index import load, retrieve

    load()  # model + index load is one-off; keep it out of the per-query timings
    questions = json.loads(Path(a.questions).read_text(encoding="utf-8"))
    out = run(questions, retrieve, k=config.RETRIEVAL_K)
    out["summary"]["model"] = config.EMBEDDING_MODEL
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    s = out["summary"]
    print(f"In-scope ({s['in_scope']['n']}): hit@1 {s['in_scope']['hit@1']}  hit@3 {s['in_scope']['hit@3']}  MRR {s['in_scope']['mrr']}")
    for name, m in s["by_set"].items():
        print(f"  set {name:9} n={m['n']:2}  hit@1 {m['hit@1']}  hit@3 {m['hit@3']}  MRR {m['mrr']}")
    for variant, m in s["by_variant"].items():
        print(f"  {variant:12} n={m['n']:2}  hit@1 {m['hit@1']}  hit@3 {m['hit@3']}  MRR {m['mrr']}")
    print("Misses at rank 1:", s["misses_at_1"] or "none")
    print("Scores:", json.dumps(s["scores"], ensure_ascii=False))
    print(f"Saved {a.out}")


if __name__ == "__main__":
    main()
