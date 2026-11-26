"""The live knowledge base: kb/entries.json and kb/question_variants.json, changed at run time only through
this module (the coordinator's /teach page). Every change is recorded in SQLite (kb_versions) with the entry
as it was before and after, so the last change can be undone by voice, and the search index is updated in
place, without restarting the server.

A change is all or nothing: if the index cannot be updated, the files and the history go back to how they were.
"""

import json
import logging
import os
import re
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from tempfile import NamedTemporaryFile

import config
from coordinator.db import connect, now
from kb.translate_kb import ordered

log = logging.getLogger(__name__)

_lock = threading.Lock()  # one change at a time: read, write, re-index


# --- files ------------------------------------------------------------------------------------------------

def entries() -> list[dict]:
    return json.loads(config.KB_PATH.read_text(encoding="utf-8"))


def _variants_file() -> dict:
    if not config.KB_VARIANTS_PATH.exists():
        return {}
    return json.loads(config.KB_VARIANTS_PATH.read_text(encoding="utf-8"))


def get(entry_id: str) -> dict | None:
    return next((e for e in entries() if e["id"] == entry_id), None)


def variants(entry_id: str) -> list[str]:
    return list(_variants_file().get(entry_id) or [])


def _write_json(path, data, compact_lists: bool = False) -> None:
    """Write next to the target, then rename: a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact_lists:  # question_variants.json keeps one entry per line, as the team wrote it
        lines = [f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}" for k, v in data.items()]
        text = "{\n" + ",\n".join(lines) + "\n}\n"
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644  # keep the file's permissions
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as tmp:
        tmp.write(text)
    os.chmod(tmp.name, mode)
    os.replace(tmp.name, path)


def snapshot(entry_id: str) -> dict:
    """The entry and its extra phrasings as they are now ({"entry": None, ...} if there is no such entry)."""
    return {"entry": get(entry_id), "variants": variants(entry_id) or None}


def _apply(entry_id: str, snap: dict | None) -> None:
    """Make the files hold snap for entry_id: replace, add (after its category's last entry) or remove it."""
    snap = snap or {"entry": None, "variants": None}
    items = entries()
    pos = next((i for i, e in enumerate(items) if e["id"] == entry_id), None)
    entry = snap.get("entry")
    if entry is None:
        if pos is not None:
            items.pop(pos)
    elif pos is not None:
        items[pos] = ordered(entry)
    else:
        same = [i for i, e in enumerate(items) if e.get("category") == entry.get("category")]
        items.insert(same[-1] + 1 if same else len(items), ordered(entry))
    _write_json(config.KB_PATH, items)

    raw = _variants_file()
    if snap.get("variants"):
        raw[entry_id] = list(snap["variants"])
    else:
        raw.pop(entry_id, None)
    if raw or config.KB_VARIANTS_PATH.exists():
        _write_json(config.KB_VARIANTS_PATH, raw, compact_lists=True)


def _reindex() -> None:
    """Update the live search index and drop cached KB lookups."""
    from generation.answer import _kb_answer_en
    from retrieval.index import refresh

    refresh()
    _kb_answer_en.cache_clear()


# --- ids --------------------------------------------------------------------------------------------------

PREFIX = {"transfusion_schedule": "sched", "donor_eligibility": "elig", "donation_request": "req",
          "hplc_testing": "hplc", "general": "gen"}


def next_id(category: str) -> str:
    """'elig-23' style: the prefix the category already uses, and the next free number."""
    items = entries()
    prefixes = Counter(e["id"].rsplit("-", 1)[0] for e in items if e.get("category") == category and "-" in e["id"])
    prefix = prefixes.most_common(1)[0][0] if prefixes else PREFIX.get(category, "kb")
    numbers = [int(m.group(1)) for e in items if (m := re.fullmatch(re.escape(prefix) + r"-(\d+)", e["id"]))]
    return f"{prefix}-{max(numbers, default=0) + 1:02d}"


# --- history ----------------------------------------------------------------------------------------------

def _row(row) -> dict:
    out = dict(row)
    for key in ("before", "after"):
        out[key] = json.loads(out[key]) if out[key] else None
    return out


def _record(conn, entry_id: str, action: str, before: dict | None, after: dict | None, said: str | None,
            lang: str | None, from_ref: str | None = None, undo_of: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO kb_versions (entry_id, action, before, after, said, language, from_ref, undo_of, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (entry_id, action, json.dumps(before, ensure_ascii=False) if before and before.get("entry") else None,
         json.dumps(after, ensure_ascii=False) if after and after.get("entry") else None,
         said, lang, from_ref, undo_of, now()))
    return cur.lastrowid


def save(entry: dict, new_variants: list[str] | None, said: str | None, lang: str | None,
         from_ref: str | None = None) -> dict:
    """Add or replace entry (and set its extra phrasings), record it, update the live index.
    Returns the history row."""
    entry = ordered(entry)
    with _lock:
        before = snapshot(entry["id"])
        after = {"entry": entry, "variants": list(new_variants) if new_variants else None}
        action = "edit" if before["entry"] else "create"
        _apply(entry["id"], after)
        try:
            _reindex()
        except Exception:
            _apply(entry["id"], before)
            raise
        with connect() as conn:
            version_id = _record(conn, entry["id"], action, before, after, said, lang, from_ref)
        log.info("KB %s %s (version %d)", action, entry["id"], version_id)
        return get_version(version_id)


def last_change() -> dict | None:
    """The newest change that has not been undone yet (an undo itself is not undone again; saying undo
    twice steps further back)."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM kb_versions WHERE action != 'undo' AND undone_at IS NULL"
                           " ORDER BY id DESC LIMIT 1").fetchone()
    return _row(row) if row else None


def get_version(version_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM kb_versions WHERE id = ?", (version_id,)).fetchone()
    return _row(row) if row else None


def undo(version_id: int, said: str | None = None, lang: str | None = None) -> dict | None:
    """Put the entry back as it was before change version_id, if that is still the last change.
    Returns the undo's history row, or None if version_id is no longer the last change."""
    with _lock:
        change = last_change()
        if not change or change["id"] != version_id:
            return None
        entry_id = change["entry_id"]
        current = snapshot(entry_id)
        _apply(entry_id, change["before"])
        try:
            _reindex()
        except Exception:
            _apply(entry_id, current)
            raise
        with connect() as conn:
            undo_id = _record(conn, entry_id, "undo", current, change["before"], said, lang, undo_of=version_id)
            conn.execute("UPDATE kb_versions SET undone_at = ? WHERE id = ?", (now(), version_id))
        log.info("KB undo of version %d (%s)", version_id, entry_id)
        return get_version(undo_id)


def history(limit: int = 10) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM kb_versions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


# --- drafts: what was read back, kept until the coordinator says yes or no ---------------------------------

DRAFT_MAX_AGE_S = 24 * 3600


def put_draft(draft_id: str, data: dict) -> None:
    with connect() as conn:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=DRAFT_MAX_AGE_S)).isoformat(timespec="seconds")
        conn.execute("DELETE FROM kb_drafts WHERE created_at < ?", (cutoff,))
        conn.execute("INSERT INTO kb_drafts (id, data, created_at) VALUES (?, ?, ?)",
                     (draft_id, json.dumps(data, ensure_ascii=False), now()))


def get_draft(draft_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT data FROM kb_drafts WHERE id = ?", (draft_id,)).fetchone()
    return json.loads(row["data"]) if row else None


def drop_draft(draft_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM kb_drafts WHERE id = ?", (draft_id,))
