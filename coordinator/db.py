"""SQLite store (config.DB_PATH). One short-lived connection per call, so it is safe across threads."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    reference           TEXT NOT NULL UNIQUE,          -- BW-1042 style, what the caregiver quotes
    question_text       TEXT,
    question_audio_path TEXT,                          -- file name inside config.REQUEST_AUDIO_DIR
    language            TEXT NOT NULL,                 -- caregiver's language: te | hi | en
    reason              TEXT,                          -- urgent | low_confidence | not_covered | llm_error
    status              TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'replied', 'closed')),
    summary             TEXT,                          -- one line, for the coordinator queue
    urgency             TEXT,                          -- high | medium | low
    reply_source_text   TEXT,                          -- what the coordinator said, as transcribed
    reply_text          TEXT,                          -- the reply in the caregiver's language
    reply_audio_path    TEXT,                          -- spoken reply_text (file name in the TTS cache)
    created_at          TEXT NOT NULL,
    replied_at          TEXT
);
CREATE INDEX IF NOT EXISTS requests_status ON requests (status);

-- Knowledge base changes made by voice on /teach: one row per saved change, so the last one can be undone.
CREATE TABLE IF NOT EXISTS kb_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('create', 'edit', 'undo')),
    before      TEXT,                                  -- JSON {"entry", "variants"} or null (entry did not exist)
    after       TEXT,                                  -- JSON {"entry", "variants"} or null (entry removed)
    said        TEXT,                                  -- what the coordinator said, as transcribed
    language    TEXT,                                  -- the coordinator's language
    from_ref    TEXT,                                  -- request reference when made from "Make this an FAQ"
    undo_of     INTEGER REFERENCES kb_versions (id),   -- for action = 'undo': the change it took back
    undone_at   TEXT,                                  -- set on a change once it has been undone
    created_at  TEXT NOT NULL
);

-- What the coordinator heard read back, kept until they say yes or no: only this exact draft is saved.
CREATE TABLE IF NOT EXISTS kb_drafts (
    id          TEXT PRIMARY KEY,
    data        TEXT NOT NULL,                         -- JSON
    created_at  TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    """Yield a connection with the schema in place; commits on success, rolls back on error."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
