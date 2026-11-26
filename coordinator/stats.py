"""'This week' numbers for the coordinator dashboard, from the /ask log and the requests table.

The week starts on Monday 00:00 India time. Every number is counted from real records; nothing is estimated.
"""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import config
from coordinator.db import connect

IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving time


def week_start(now: datetime | None = None) -> datetime:
    local = (now or datetime.now(timezone.utc)).astimezone(IST)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday


def _when(value: str | None) -> datetime | None:
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def this_week(now: datetime | None = None) -> dict:
    start = week_start(now)
    answered, languages = 0, Counter()
    if config.LOG_PATH.exists():
        with open(config.LOG_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ts = _when(rec.get("timestamp"))
                if not ts or ts < start or rec.get("outcome") not in ("answered", "escalated"):
                    continue
                answered += rec["outcome"] == "answered"
                if rec.get("lang"):
                    languages[rec["lang"]] += 1

    handed_off = replied = still_open = 0
    waits = []
    with connect() as conn:
        for row in conn.execute("SELECT status, created_at, replied_at FROM requests"):
            created, done = _when(row["created_at"]), _when(row["replied_at"])
            still_open += row["status"] == "open"
            if created and created >= start:
                handed_off += 1
            if done and done >= start:
                replied += 1
                if created:
                    waits.append((done - created).total_seconds() / 60)

    return {
        "since": start.isoformat(),
        "answered": answered,            # questions the assistant answered itself
        "handed_off": handed_off,        # questions sent to coordinators
        "replied": replied,              # coordinator replies sent this week
        "open": still_open,              # waiting now, from any week
        "languages": {lang: languages[lang] for lang in config.LANGUAGES if languages[lang]},
        "avg_response_minutes": round(sum(waits) / len(waits), 1) if waits else None,
    }
