"""#10: pre-fill eval/grading.csv from results/generation.json for hand grading.

Usage: python eval/make_grading.py
One row per generated answer (fallbacks are not graded). Each row shows the question, the LLM's Telugu
answer, the KB entry it cites and that entry's own answers, so a grader can judge:
  correct   Y/N  the answer is right for the question
  grounded  Y/N  everything in the answer is in the cited KB entry (nothing added)
Two graders fill their own columns. Re-running keeps any grades already entered (matched by id).
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

OUT = ROOT / "eval" / "grading.csv"
GRADE_COLS = ["correct_1", "grounded_1", "grader_1", "correct_2", "grounded_2", "grader_2", "notes"]
COLS = ["id", "question", "answer", "source_id", "expected_kb_id", "kb_answer_te", "kb_answer_en"] + GRADE_COLS


def build_rows(generation: dict, kb: dict, existing: dict) -> list[dict]:
    rows = []
    for r in generation["results"]:
        if r["fallback"]:
            continue
        entry = kb.get(r["source_id"], {})
        row = {"id": r["id"], "question": r["question"], "answer": r["answer"], "source_id": r["source_id"],
               "expected_kb_id": r.get("expected_kb_id") or "", "kb_answer_te": entry.get("answer_te", ""),
               "kb_answer_en": entry.get("answer_en", "")}
        old = existing.get(r["id"], {})
        same_answer = old.get("answer") == r["answer"]
        row.update({c: (old.get(c, "") if same_answer else "") for c in GRADE_COLS})
        rows.append(row)
    return rows


def main() -> None:
    generation = json.loads((ROOT / "results" / "generation.json").read_text(encoding="utf-8"))
    kb = {e["id"]: e for e in json.loads(config.KB_PATH.read_text(encoding="utf-8"))}
    existing = {}
    if OUT.exists():
        with open(OUT, encoding="utf-8-sig", newline="") as f:
            existing = {r["id"]: r for r in csv.DictReader(f)}
    rows = build_rows(generation, kb, existing)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: Excel shows Telugu correctly
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    kept = sum(1 for r in rows if any(r[c] for c in GRADE_COLS))
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(rows)} answers to grade ({kept} keep earlier grades)")


if __name__ == "__main__":
    main()
