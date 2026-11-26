"""Threshold sweep (#14): what each ANSWER_THRESHOLD would answer, clarify or hand off on eval/questions.json.

Reads the top scores already in results/retrieval.json (run eval/run_retrieval.py first), so no model is
needed. Medical items are counted only if they get past the safety gate (is_urgent runs before retrieval).

    python eval/sweep_threshold.py   ->  results/threshold_sweep.csv
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from generation.safety import is_urgent  # noqa: E402

OUT = config.ROOT / "results" / "threshold_sweep.csv"


def _question_text(q: dict) -> str:
    return q.get("question_te") or q.get("question_en") or ""


def sweep(results: list[dict], questions: dict[str, dict], clarify_t: float,
          thresholds: list[float]) -> list[dict]:
    rows = []
    for t in thresholds:
        row = {"answer_threshold": t, "clarify_threshold": clarify_t,
               "in_scope_answered": 0, "in_scope_answered_wrong_top1": 0, "in_scope_clarified": 0,
               "in_scope_fallback": 0, "out_of_scope_answered": 0, "out_of_scope_clarified": 0,
               "out_of_scope_fallback": 0, "out_of_scope_answered_ids": []}
        for r in results:
            q = questions[r["id"]]
            out_of_scope = q["expected_behaviour"] == "fallback"
            if out_of_scope and is_urgent(_question_text(q)):
                row["out_of_scope_fallback"] += 1  # safety gate: never reaches retrieval
                continue
            score = r["top_score"]
            decision = "answer" if score >= t else "clarify" if score >= clarify_t else "fallback"
            prefix = "out_of_scope" if out_of_scope else "in_scope"
            key = {"answer": "answered", "clarify": "clarified", "fallback": "fallback"}[decision]
            row[f"{prefix}_{key}"] += 1
            if decision == "answer" and out_of_scope:
                row["out_of_scope_answered_ids"].append(r["id"])
            if decision == "answer" and not out_of_scope and r["rank"] != 1:
                row["in_scope_answered_wrong_top1"] += 1
        row["out_of_scope_answered_ids"] = " ".join(row["out_of_scope_answered_ids"])
        rows.append(row)
    return rows


def main() -> None:
    results = json.loads((config.ROOT / "results" / "retrieval.json").read_text(encoding="utf-8"))["results"]
    questions = {q["id"]: q for q in json.loads((config.ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))}
    thresholds = [round(0.50 + 0.01 * i, 2) for i in range(51)]
    rows = sweep(results, questions, config.CLARIFY_THRESHOLD, thresholds)
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        if row["answer_threshold"] in (0.66, 0.70, 0.73, 0.75, 0.80, 0.81, 0.85):
            print({k: row[k] for k in ("answer_threshold", "in_scope_answered", "in_scope_clarified",
                                       "in_scope_fallback", "out_of_scope_answered_ids")})
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
