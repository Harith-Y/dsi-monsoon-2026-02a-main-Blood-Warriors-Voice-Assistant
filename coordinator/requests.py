"""Hand-off requests: a question the assistant could not answer, waiting for a coordinator's reply."""

import re
import secrets

from coordinator.db import connect, now

STATUSES = ("open", "replied", "closed")


def _new_reference(conn) -> str:
    # Random, not sequential, so one caregiver's code does not reveal the next one.
    for digits in (4, 4, 4, 4, 4, 5, 5, 5, 6):
        ref = f"BW-{secrets.randbelow(9 * 10 ** (digits - 1)) + 10 ** (digits - 1)}"
        if not conn.execute("SELECT 1 FROM requests WHERE reference = ?", (ref,)).fetchone():
            return ref
    raise RuntimeError("could not allocate a reference code")


# Spoken digits: Telugu, Hindi and English words (and English said in Telugu/Devanagari script), so a
# caregiver can say their code in whatever language they speak. Written digits in any script also count.
_DIGIT_WORDS = {
    0: ["zero", "sunna", "sunnaa", "సున్నా", "సున్న", "జీరో", "शून्य", "ज़ीरो", "जीरो"],
    1: ["one", "okati", "ఒకటి", "వన్", "एक", "वन"],
    2: ["two", "rendu", "రెండు", "టూ", "दो", "टू"],
    3: ["three", "moodu", "మూడు", "త్రీ", "तीन", "थ्री"],
    4: ["four", "naalugu", "నాలుగు", "ఫోర్", "चार", "फोर", "फ़ोर"],
    5: ["five", "aidu", "ఐదు", "అయిదు", "ఫైవ్", "पांच", "पाँच", "फाइव"],
    6: ["six", "aaru", "ఆరు", "సిక్స్", "छह", "छः", "छे", "सिक्स"],
    7: ["seven", "edu", "ఏడు", "సెవెన్", "सात", "सेवन"],
    8: ["eight", "enimidi", "ఎనిమిది", "ఎయిట్", "आठ", "एट"],
    9: ["nine", "tommidi", "తొమ్మిది", "నైన్", "नौ", "नाइन"],
}
_WORD_TO_DIGIT = {w: str(d) for d, words in _DIGIT_WORDS.items() for w in words}


def digits_from_speech(text: str | None) -> str:
    """'B W one zero four two' / 'బి డబ్ల్యూ ఒకటి సున్నా నాలుగు రెండు' / 'BW-1042' -> '1042'."""
    import unicodedata
    out = []
    for token in re.findall(r"[\w\u0900-\u097F\u0C00-\u0C7F]+", re.sub("[\u200b-\u200d]", "", (text or "").lower())):
        if all(unicodedata.digit(ch, None) is not None for ch in token):
            out.append("".join(str(unicodedata.digit(ch)) for ch in token))  # ASCII, Telugu or Devanagari digits
        elif token in _WORD_TO_DIGIT:
            out.append(_WORD_TO_DIGIT[token])
        else:
            m = re.fullmatch(r"[a-z]*(\d+)", token)  # "bw1042"
            if m:
                out.append(m.group(1))
    return "".join(out)


def normalise_reference(text: str | None) -> str | None:
    """'bw 1042', 'BW-1042', '1042' -> 'BW-1042'. None when there are no digits."""
    digits = re.sub(r"\D", "", text or "")
    return f"BW-{digits}" if digits else None


def create(question_text: str | None, language: str, reason: str | None,
           question_audio_path: str | None = None) -> dict:
    with connect() as conn:
        ref = _new_reference(conn)
        conn.execute(
            "INSERT INTO requests (reference, question_text, question_audio_path, language, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (ref, question_text, question_audio_path, language, reason, now()),
        )
        return dict(conn.execute("SELECT * FROM requests WHERE reference = ?", (ref,)).fetchone())


def get(reference: str | None) -> dict | None:
    ref = normalise_reference(reference)
    if not ref:
        return None
    with connect() as conn:
        row = conn.execute("SELECT * FROM requests WHERE reference = ?", (ref,)).fetchone()
        return dict(row) if row else None


def list_requests(status: str | None = None) -> list[dict]:
    with connect() as conn:
        if status:
            rows = conn.execute("SELECT * FROM requests WHERE status = ? ORDER BY created_at DESC, id DESC",
                                (status,))
        else:
            rows = conn.execute("SELECT * FROM requests ORDER BY created_at DESC, id DESC")
        return [dict(r) for r in rows]


def update(reference: str, **fields) -> dict | None:
    """Set the given columns on one request; returns the updated row (None if not found)."""
    allowed = {"summary", "urgency", "status", "reply_source_text", "reply_text", "reply_audio_path", "replied_at"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot update {sorted(bad)}")
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"bad status {fields['status']!r}")
    ref = normalise_reference(reference)
    with connect() as conn:
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE requests SET {cols} WHERE reference = ?", (*fields.values(), ref))
        row = conn.execute("SELECT * FROM requests WHERE reference = ?", (ref,)).fetchone()
        return dict(row) if row else None


def save_reply(reference: str, reply_source_text: str, reply_text: str, reply_audio_path: str | None) -> dict | None:
    return update(reference, reply_source_text=reply_source_text, reply_text=reply_text,
                  reply_audio_path=reply_audio_path, status="replied", replied_at=now())


def counts() -> dict:
    """{"open": n, "replied": n, "closed": n}"""
    with connect() as conn:
        found = dict(conn.execute("SELECT status, COUNT(*) FROM requests GROUP BY status").fetchall())
    return {s: found.get(s, 0) for s in STATUSES}
