"""#10: end-to-end latency and outcome of every recorded clip through a running API.

Usage (API running: uvicorn api.main:app --port 8000):
    python eval/run_latency.py [--rounds 2] [--pause 8]  ->  results/latency.json

Sends each clip in data/audio/transcripts.json to POST /ask as audio, `rounds` times, and records the
per-stage latency_ms the API returns plus the client-side wall time. Round 1 is "cold" for TTS (each answer
is synthesised for the first time); later rounds hit the TTS cache, so both are reported. `pause` spaces
requests out so Groq's free-tier tokens-per-minute limit doesn't turn requests into llm_error; requests that
still fail with llm_error are counted but left out of the latency percentiles.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

STAGES = ["asr", "retrieve", "generate", "tts", "total"]
# The three demo journeys (CLAUDE.md #9): clip -> expected source id, or "urgent" for the safety hand-off.
DEMO_JOURNEYS = {"c01": "sched-01", "c02": "elig-01", "c03": "urgent"}


def _outcome_ok(expected: str, body: dict) -> bool:
    if expected == "fallback":
        return bool(body.get("fallback"))
    return not body.get("fallback") and body.get("source_id") == expected


def _percentiles(rows: list[dict]) -> dict:
    out = {}
    for stage in STAGES + ["wall"]:
        vals = [r["latency_ms"][stage] if stage != "wall" else r["wall_ms"] for r in rows]
        out[stage] = {"p50": round(float(np.percentile(vals, 50))), "p95": round(float(np.percentile(vals, 95)))} if vals else None
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=config.API_URL)
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--pause", type=float, default=8, help="seconds between requests (Groq rate limit)")
    a = p.parse_args()

    refs = json.loads((config.AUDIO_DIR / "transcripts.json").read_text(encoding="utf-8"))
    requests.get(f"{a.url}/health", timeout=10).raise_for_status()
    # Warm-up: the API loads the ASR model on its first audio request; time it separately.
    with open(config.AUDIO_DIR / refs[0]["file"], "rb") as f:
        t0 = time.perf_counter()
        requests.post(f"{a.url}/ask", files={"audio": (refs[0]["file"], f, "audio/wav")}, timeout=120)
        warmup_ms = round((time.perf_counter() - t0) * 1000)
    print(f"warm-up request (loads ASR model): {warmup_ms} ms")
    time.sleep(a.pause)
    rows = []
    for rnd in range(1, a.rounds + 1):
        for r in refs:
            path = config.AUDIO_DIR / r["file"]
            t0 = time.perf_counter()
            with open(path, "rb") as f:
                resp = requests.post(f"{a.url}/ask", files={"audio": (path.name, f, "audio/wav")}, timeout=60)
            wall = round((time.perf_counter() - t0) * 1000)
            body = resp.json()
            rows.append({
                "round": rnd, "clip_id": r["clip_id"], "variant": r["variant"], "expected": r["expected_kb_id"],
                "transcript": body.get("transcript"), "fallback": body.get("fallback"),
                "fallback_reason": body.get("fallback_reason"), "source_id": body.get("source_id"),
                "score": body.get("score"), "audio_url": body.get("audio_url"),
                "latency_ms": body["latency_ms"], "wall_ms": wall, "ok": _outcome_ok(r["expected_kb_id"], body),
            })
            x = rows[-1]
            print(f"r{rnd} {x['clip_id']} {x['latency_ms']['total']:5d} ms  "
                  f"{'fallback:' + str(x['fallback_reason']) if x['fallback'] else 'answer:' + str(x['source_id'])}"
                  f"  {'OK' if x['ok'] else 'expected ' + str(x['expected'])}")
            time.sleep(a.pause)

    timed = [r for r in rows if r["fallback_reason"] != "llm_error"]
    answered = [r for r in timed if not r["fallback"]]
    demo = {}
    for clip, want in DEMO_JOURNEYS.items():
        runs = [r for r in rows if r["clip_id"] == clip]
        ok = [(r["fallback"] and r["fallback_reason"] == "urgent") if want == "urgent"
              else (not r["fallback"] and r["source_id"] == want) for r in runs]
        demo[clip] = {"expected": want, "passed_runs": f"{sum(ok)}/{len(ok)}"}

    summary = {
        "requests": len(rows), "rounds": a.rounds, "clips": len(refs), "warmup_first_request_ms": warmup_ms,
        "llm_errors_excluded": len(rows) - len(timed),
        "latency_ms_all": _percentiles(timed),
        "latency_ms_answered_cold_tts": _percentiles([r for r in answered if r["round"] == 1]),
        "latency_ms_answered_cached_tts": _percentiles([r for r in answered if r["round"] > 1]),
        "under_budget_p95": bool(timed) and _percentiles(timed)["total"]["p95"] < config.E2E_LATENCY_BUDGET_S * 1000,
        "outcome_correct": f"{sum(r['ok'] for r in rows)}/{len(rows)}",
        "fallback_reasons": {k: sum(r["fallback_reason"] == k for r in rows) for k in sorted({str(r["fallback_reason"]) for r in rows})},
        "demo_journeys": demo,
    }
    out_path = config.ROOT / "results" / "latency.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
