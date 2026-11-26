"""Append one JSONL line per /ask request. No audio, no personal data."""

import json
from datetime import datetime, timezone

import config


def log_request(transcript: str, source_id: str | None, score: float | None,
                 outcome: str, fallback_reason: str | None, latency_ms: dict,
                 lang: str | None = None, reference: str | None = None) -> None:
    line = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "transcript": transcript,
        "source_id": source_id,
        "score": score,
        "outcome": outcome,  # "answered" | "clarify" | "escalated" | "error"
        "lang": lang,
        "reference": reference,  # coordinator request code when escalated
        "fallback_reason": fallback_reason,
        "latency_ms": latency_ms,
    }
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
