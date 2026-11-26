"""#10: ASR accuracy on the recorded corpus, and retrieval on reference text vs ASR transcripts.

Usage: python eval/run_asr.py  ->  results/asr.json
Clips and references: data/audio/transcripts.json (#11). WER and CER per clip, overall and per variant
(telugu / code_mixed), using the same text cleaning as eval/compare_asr.py (#3). Each clip is then sent to
retrieval twice, with its reference text and with the ASR transcript, to show how much ASR errors cost.
Clips whose expected_kb_id is "fallback" pass if the safety gate fires or the top score is below the
answer threshold.
"""

import json
import sys
import time
from pathlib import Path

import jiwer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from asr.transcribe import _load, transcribe  # noqa: E402
from eval.compare_asr import clean  # noqa: E402
from generation.safety import is_urgent  # noqa: E402

TARGET_WER = 0.30


def _route(text: str, expected: str, retrieve_fn) -> dict:
    """What the pipeline would do with this text: safety gate, then retrieval and the answer threshold."""
    if is_urgent(text):
        return {"urgent": True, "top": None, "score": None, "rank": None, "ok": expected == "fallback"}
    hits = retrieve_fn(text, k=config.RETRIEVAL_K)
    ids = [h["id"] for h in hits]
    score = round(hits[0]["score"], 3) if hits else None
    if expected == "fallback":
        ok = not hits or hits[0]["score"] < config.ANSWER_THRESHOLD
        rank = None
    else:
        rank = ids.index(expected) + 1 if expected in ids else None
        ok = rank == 1
    return {"urgent": False, "top": ids[0] if ids else None, "score": score, "rank": rank, "ok": ok}


def _retrieval_summary(rows: list[dict], key: str) -> dict:
    in_scope = [r for r in rows if r["expected_kb_id"] != "fallback"]
    fallback = [r for r in rows if r["expected_kb_id"] == "fallback"]
    n = len(in_scope)
    return {
        "in_scope": n,
        "hit@1": round(sum(r[key]["rank"] == 1 for r in in_scope) / n, 3) if n else None,
        "hit@3": round(sum(r[key]["rank"] is not None and r[key]["rank"] <= 3 for r in in_scope) / n, 3) if n else None,
        "fallback_clips_routed_to_coordinator": f"{sum(r[key]['ok'] for r in fallback)}/{len(fallback)}",
    }


def run(refs: list[dict], transcribe_fn, retrieve_fn) -> dict:
    rows = []
    for r in refs:
        path = config.AUDIO_DIR / r["file"]
        t0 = time.perf_counter()
        hyp = transcribe_fn(path)
        secs = time.perf_counter() - t0
        ref, hyp_clean = clean(r["reference_text"]), clean(hyp)
        rows.append({
            "clip_id": r["clip_id"], "variant": r["variant"], "speaker": r.get("speaker"),
            "expected_kb_id": r["expected_kb_id"], "seconds": round(secs, 2),
            "reference": ref, "hypothesis": hyp,
            "wer": round(jiwer.wer(ref, hyp_clean), 3), "cer": round(jiwer.cer(ref, hyp_clean), 3),
            "retrieval_reference": _route(ref, r["expected_kb_id"], retrieve_fn),
            "retrieval_asr": _route(hyp_clean, r["expected_kb_id"], retrieve_fn),
        })

    def corpus(subset: list[dict]) -> dict:
        refs_, hyps = [x["reference"] for x in subset], [clean(x["hypothesis"]) for x in subset]
        return {"clips": len(subset), "wer": round(jiwer.wer(refs_, hyps), 3), "cer": round(jiwer.cer(refs_, hyps), 3)}

    secs = sorted(x["seconds"] for x in rows)
    summary = {
        "model": config.ASR_MODEL,
        "overall": corpus(rows),
        "by_variant": {v: corpus([x for x in rows if x["variant"] == v]) for v in sorted({x["variant"] for x in rows})},
        "target_wer": TARGET_WER,
        "seconds_per_clip": {"mean": round(sum(secs) / len(secs), 2), "max": secs[-1]},
        "retrieval_on_reference_text": _retrieval_summary(rows, "retrieval_reference"),
        "retrieval_on_asr_transcript": _retrieval_summary(rows, "retrieval_asr"),
        "worst_clips": [{"clip_id": x["clip_id"], "wer": x["wer"], "reference": x["reference"], "hypothesis": x["hypothesis"]}
                        for x in sorted(rows, key=lambda x: -x["wer"])[:5]],
    }
    summary["overall"]["target_met"] = summary["overall"]["wer"] < TARGET_WER
    return {"summary": summary, "results": rows}


def main() -> None:
    from retrieval.index import load, retrieve

    refs = json.loads((config.AUDIO_DIR / "transcripts.json").read_text(encoding="utf-8"))
    load()
    t0 = time.perf_counter()
    _load(config.ASR_MODEL)
    transcribe(config.AUDIO_DIR / refs[0]["file"])  # warm-up: the first inference initialises the runtime
    load_s = round(time.perf_counter() - t0, 1)

    out = run(refs, transcribe, retrieve)
    out["summary"]["model_load_seconds"] = load_s
    results = config.ROOT / "results"
    results.mkdir(exist_ok=True)
    (results / "asr.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    s = out["summary"]
    print(f"ASR {s['model']} on {s['overall']['clips']} clips: WER {s['overall']['wer']:.1%}  CER {s['overall']['cer']:.1%}"
          f"  (target WER < {TARGET_WER:.0%}: {'met' if s['overall']['target_met'] else 'NOT met'})")
    for v, m in s["by_variant"].items():
        print(f"  {v:10} n={m['clips']:2}  WER {m['wer']:.1%}  CER {m['cer']:.1%}")
    print(f"  {s['seconds_per_clip']['mean']} s/clip (max {s['seconds_per_clip']['max']}), model load {load_s} s")
    print("Retrieval on reference text:", s["retrieval_on_reference_text"])
    print("Retrieval on ASR transcript:", s["retrieval_on_asr_transcript"])
    print("Saved results/asr.json")


if __name__ == "__main__":
    main()
