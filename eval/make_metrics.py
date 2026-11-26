"""#10: build the one metrics sheet from the results files.

Usage: python eval/make_metrics.py  ->  results/metrics.csv and results/metrics.md
Reads results/asr.json, results/retrieval.json, results/generation.json, eval/grading.csv and
results/latency.json; a missing file gives "not run" rows rather than an error.
"""

import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

RESULTS = ROOT / "results"


def _load(name: str):
    path = ROOT / name
    if not path.exists():
        return None
    if path.suffix == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    return json.loads(path.read_text(encoding="utf-8"))


def pct(x) -> str:
    return "—" if x is None else f"{x:.1%}"


def row(metric, value, target, met, source):
    return {"metric": metric, "value": value, "target": target,
            "met": "" if met is None else ("yes" if met else "no"), "source": source}


def asr_rows(asr) -> list[dict]:
    src = "results/asr.json"
    if not asr:
        return [row("ASR WER (recorded clips)", "not run", "< 30%", None, src)]
    s = asr["summary"]
    rows = [
        row(f"ASR WER ({s['overall']['clips']} recorded clips, {s['model']})", pct(s["overall"]["wer"]), "< 30%",
            s["overall"]["wer"] < 0.30, src),
        row("ASR CER (same clips)", pct(s["overall"]["cer"]), "report", None, src),
    ]
    for v, m in s["by_variant"].items():
        rows.append(row(f"ASR WER, {v} ({m['clips']} clips)", pct(m["wer"]), "report", None, src))
    rows.append(row("ASR seconds per clip (mean)", f"{s['seconds_per_clip']['mean']} s", "report", None, src))
    ref, hyp = s["retrieval_on_reference_text"], s["retrieval_on_asr_transcript"]
    rows.append(row(f"Retrieval hit@1 on clip reference text ({ref['in_scope']} clips)", pct(ref["hit@1"]), "report", None, src))
    rows.append(row(f"Retrieval hit@1 on ASR transcripts ({hyp['in_scope']} clips)", pct(hyp["hit@1"]),
                    "report the drop", None, src))
    return rows


def retrieval_rows(ret) -> list[dict]:
    src = "results/retrieval.json"
    if not ret:
        return [row("Retrieval hit@1 (typed test questions)", "not run", "≥ 80%", None, src)]
    s = ret["summary"]
    rows = [
        row(f"Retrieval hit@1 ({s['in_scope']['n']} typed in-scope questions)", pct(s["in_scope"]["hit@1"]), "≥ 80%",
            s["in_scope"]["hit@1"] >= 0.8, src),
        row("Retrieval hit@3 (same)", pct(s["in_scope"]["hit@3"]), "report", None, src),
    ]
    unseen = [m for name, m in s.get("by_set", {}).items() if name != "main"]
    if unseen:
        n = sum(m["n"] for m in unseen)
        hit = sum(m["hit@1"] * m["n"] for m in unseen) / n
        rows.append(row(f"Retrieval hit@1, questions not used for tuning ({n})", pct(hit), "≥ 80%", hit >= 0.8, src))
    return rows


def generation_rows(gen, grades) -> list[dict]:
    src = "results/generation.json"
    if not gen:
        return [row("Answers traceable to a KB entry", "not run", "100%", None, src)]
    res = gen["results"]
    answered = [r for r in res if not r["fallback"]]
    traceable = [r for r in answered if r["source_id"] and r["source_id"] in {h["id"] for h in r["top_hits"]}]
    want_fb = [r for r in res if r["expects_fallback"]]
    in_scope = [r for r in res if not r["expects_fallback"]]
    llm_err = [r for r in res if r.get("reason") == "llm_error"]
    rows = [
        row(f"Answers traceable to a retrieved KB entry ({len(answered)} answers)",
            pct(len(traceable) / len(answered)) if answered else "—", "100%",
            len(traceable) == len(answered) if answered else None, src),
        row(f"Out-of-scope + medical questions sent to coordinator ({len(want_fb)})",
            pct(sum(r["fallback"] for r in want_fb) / len(want_fb)), "100%",
            all(r["fallback"] for r in want_fb), src),
        row(f"In-scope questions answered ({len(in_scope)})", pct(sum(not r["fallback"] for r in in_scope) / len(in_scope)),
            "report", None, src),
        row("In-scope answers citing the expected entry",
            pct(sum(r["source_id"] == r["expected_kb_id"] for r in in_scope if not r["fallback"])
                / max(1, sum(not r["fallback"] for r in in_scope))), "report", None, src),
    ]
    if llm_err:
        rows.append(row("Questions lost to LLM errors (rate limit)", str(len(llm_err)), "0", False, src))
    gsrc = "eval/grading.csv"
    if grades is None:
        rows.append(row("Hand grading: correct / grounded", "not started", "100% grounded", None, gsrc))
    else:
        for n in ("1", "2"):
            done = [g for g in grades if g.get(f"correct_{n}", "").strip() and g.get(f"grounded_{n}", "").strip()]
            if not done:
                rows.append(row(f"Hand grading, grader {n}", f"pending (0/{len(grades)} graded)", "100% grounded", None, gsrc))
                continue
            yes = lambda col: sum(g[col].strip().upper().startswith("Y") for g in done)
            grounded = yes(f"grounded_{n}") / len(done)
            rows.append(row(f"Hand grading, grader {n}: correct ({len(done)}/{len(grades)} graded)",
                            pct(yes(f"correct_{n}") / len(done)), "report", None, gsrc))
            rows.append(row(f"Hand grading, grader {n}: grounded in the cited entry", pct(grounded), "100%",
                            grounded == 1.0, gsrc))
    return rows


def latency_rows(lat) -> list[dict]:
    src = "results/latency.json"
    if not lat:
        return [row("End-to-end latency p95", "not run", "< 10 s", None, src)]
    s = lat["summary"]
    allp = s["latency_ms_all"]
    budget = config.E2E_LATENCY_BUDGET_S * 1000
    rows = [
        row(f"End-to-end latency p50 ({s['requests'] - s['llm_errors_excluded']} requests)", f"{allp['total']['p50'] / 1000:.1f} s",
            "< 10 s", allp["total"]["p50"] < budget, src),
        row("End-to-end latency p95", f"{allp['total']['p95'] / 1000:.1f} s", "< 10 s", allp["total"]["p95"] < budget, src),
    ]
    for stage in ("asr", "retrieve", "generate", "tts"):
        rows.append(row(f"  {stage} p50 / p95", f"{allp[stage]['p50']} / {allp[stage]['p95']} ms", "report", None, src))
    cold = s.get("latency_ms_answered_cold_tts")
    if cold:
        rows.append(row("Answered, first time spoken (TTS not cached): total p50 / p95",
                        f"{cold['total']['p50'] / 1000:.1f} / {cold['total']['p95'] / 1000:.1f} s", "report", None, src))
    passed = sum(int(v["passed_runs"].split("/")[0]) == int(v["passed_runs"].split("/")[1]) for v in s["demo_journeys"].values())
    rows.append(row("Demo journeys passing (clips c01, c02, c03)", f"{passed}/{len(s['demo_journeys'])}", "3/3",
                    passed == len(s["demo_journeys"]), src))
    rows.append(row("Clips with the expected outcome, end to end", s["outcome_correct"], "report", None, src))
    if s["llm_errors_excluded"]:
        rows.append(row("Requests lost to LLM errors (rate limit), excluded", str(s["llm_errors_excluded"]), "0", False, src))
    return rows


def failing_examples(asr, ret, gen) -> list[str]:
    out = []
    if asr:
        for c in asr["summary"]["worst_clips"][:3]:
            out.append(f"- **ASR, {c['clip_id']}** (WER {c['wer']:.0%}): said “{c['reference']}” → heard “{c['hypothesis']}”")
    if ret:
        qtext = {r["id"]: r["question"] for r in ret["results"]}
        for m in ret["summary"]["misses_at_1"][:3]:
            out.append(f"- **Retrieval, {m['id']}**: “{qtext[m['id']]}” → `{m['got']}` instead of `{m['expected']}`")
    if gen:
        s = gen["summary"]
        qtext = {r["id"]: r["question"] for r in gen["results"]}
        for qid in s["fallback_expected_but_answered"][:2]:
            out.append(f"- **Generation, {qid}**: “{qtext[qid]}” was answered but should have gone to the coordinator")
        for qid in s["answer_expected_but_fallback"][:2]:
            out.append(f"- **Generation, {qid}**: “{qtext[qid]}” went to the coordinator but the KB covers it")
    return out


def main() -> None:
    asr, ret, gen = _load("results/asr.json"), _load("results/retrieval.json"), _load("results/generation.json")
    grades, lat = _load("eval/grading.csv"), _load("results/latency.json")
    rows = asr_rows(asr) + retrieval_rows(ret) + generation_rows(gen, grades) + latency_rows(lat)

    with open(RESULTS / "metrics.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["metric", "value", "target", "met", "source"])
        w.writeheader()
        w.writerows(rows)

    table = ["| Metric | Value | Target | Met? | Source |", "|---|---|---|---|---|"]
    table += [f"| {r['metric']} | {r['value']} | {r['target']} | {r['met']} | `{r['source']}` |" for r in rows]
    md = f"""# Metrics sheet: Blood Warriors voice assistant

Generated {date.today().isoformat()} by `python eval/make_metrics.py` from the files in the Source column.
KB: {len(json.loads(config.KB_PATH.read_text(encoding='utf-8')))} entries. Answer threshold {config.ANSWER_THRESHOLD}.

{chr(10).join(table)}

## Failing examples

{chr(10).join(failing_examples(asr, ret, gen)) or "- none recorded"}

## What these numbers do not show

- **Real users.** The clips are team members reading prepared questions in normal rooms, not caregivers or
  donors asking in their own words, under stress, with children or traffic in the background.
- **Real dialects.** A few team voices do not cover rural Telangana and Andhra speech or older speakers.
- **Phone audio.** Clips are 16 kHz recordings; a feature phone or IVR call is 8 kHz and noisier.
- **Independent test questions.** The KB, its phrasings and the typed test questions were written by the
  same people (and Claude), so retrieval numbers are likely optimistic.
- **Medical correctness.** Grounding is checked against the KB; the KB itself comes from public sources and
  has not yet been reviewed by Blood Warriors or a doctor.
- **Trust and usefulness.** Whether people would rely on a machine voice for this is untested.
"""
    (RESULTS / "metrics.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
