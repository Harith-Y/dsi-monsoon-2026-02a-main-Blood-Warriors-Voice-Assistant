"""Coordinator endpoints behind the shared passcode: sign in, the request queue (with LLM summary and urgency),
the caregiver's question audio, voice replies (transcribe -> translate into the caregiver's language -> read
back -> save only after a spoken or tapped "yes"), close / reopen, and the "This week" numbers.

Included by api.main; the shared helpers (_transcribe_upload, _speak, _run_stage, synthesize) are looked up
on api.main at call time so the tests' patches apply here too.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import api.main as core
import config
from asr.normalise import normalise
from coordinator import auth, stats
from coordinator import requests as requests_db
from coordinator.triage import triage
from generation.intent import yes_no
from generation.translate import translate
from i18n import t

log = logging.getLogger(__name__)

URGENCY_RANK = {"high": 0, "medium": 1, None: 1, "low": 2}
TRIAGE_BATCH = 12
TRIAGE_RETRY_S = 120
_triage_retry_at = 0.0  # after a failed LLM call, wait before trying again (the dashboard refreshes often)


def require_coordinator(request: Request) -> None:
    if not auth.valid_session(request.cookies.get(auth.COOKIE)):
        raise HTTPException(401, "sign_in")


public = APIRouter(prefix="/coord")
router = APIRouter(prefix="/coord", dependencies=[Depends(require_coordinator)])


def _message(status: int, key: str, lang: str) -> JSONResponse:
    text = t(key, lang)
    return JSONResponse(status_code=status, content={"error": key, "text": text, "audio_url": core._speak(text, lang)})


# --- sign in ----------------------------------------------------------------------------------------------

@public.get("/me")
def me(request: Request):
    return {"configured": auth.passcode() is not None,
            "signed_in": auth.valid_session(request.cookies.get(auth.COOKIE))}


@public.post("/login")
def login(request: Request, audio: UploadFile = File(None), code: str = Form(None),
          lang: str = Form(config.DEFAULT_LANG)):
    """Say the passcode (any language, one number at a time) or tap it on the keypad."""
    lang = core._lang(lang)
    client = request.client.host if request.client else "unknown"
    if auth.passcode() is None:
        return _message(503, "login.not_set", lang)
    if auth.locked(client):
        return _message(429, "login.locked", lang)
    if code is not None:
        digits = requests_db.digits_from_speech(code)
    elif audio is not None:
        digits = requests_db.digits_from_speech(core._transcribe_upload(audio, lang))
        if not digits and lang != "en":  # numbers are often said in English
            audio.file.seek(0)
            digits = requests_db.digits_from_speech(core._transcribe_upload(audio, "en"))
        if not digits:
            return _message(422, "login.no_digits", lang)
    else:
        raise HTTPException(422, "Say or tap the passcode")
    if not auth.check(digits):
        auth.record_failure(client)
        return _message(401, "login.wrong", lang)
    auth.clear_failures(client)
    text = t("login.ok", lang)
    response = JSONResponse({"ok": True, "text": text, "audio_url": core._speak(text, lang)})
    response.set_cookie(auth.COOKIE, auth.session_token(), max_age=auth.COOKIE_MAX_AGE_S, httponly=True,
                        samesite="strict", secure=request.url.scheme == "https", path="/")
    return response


@public.post("/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.COOKIE, path="/")
    return response


# --- queue ------------------------------------------------------------------------------------------------

def _summary(row: dict) -> Optional[dict]:
    if not row.get("summary"):
        return None
    try:
        value = json.loads(row["summary"])
    except ValueError:
        value = row["summary"]
    return value if isinstance(value, dict) else {"en": str(value)}


def _coord_view(row: dict) -> dict:
    reply_audio = None
    if row.get("reply_audio_path") and (config.TTS_CACHE_DIR / Path(row["reply_audio_path"]).name).is_file():
        reply_audio = f"/audio/{Path(row['reply_audio_path']).name}"
    return {
        "reference": row["reference"], "status": row["status"], "language": row["language"],
        "reason": row["reason"], "question_text": row["question_text"],
        "summary": _summary(row),
        "urgency": row["urgency"] or ("high" if row["reason"] == "urgent" else None),
        "question_recorded": bool(row["question_audio_path"]),
        "question_audio_url": f"/coord/requests/{row['reference']}/audio"
                              if row["question_audio_path"] or row["question_text"] else None,
        "reply_source_text": row["reply_source_text"], "reply_text": row["reply_text"],
        "reply_audio_url": reply_audio, "created_at": row["created_at"], "replied_at": row["replied_at"],
    }


def _fill_triage(rows: list[dict]) -> None:
    """Add the LLM summary and urgency to requests that have none (stored, so each is done once)."""
    global _triage_retry_at
    todo = [r for r in rows if not r["summary"] and r["question_text"]][:TRIAGE_BATCH]
    if not todo or time.monotonic() < _triage_retry_at:
        return
    items = {r["reference"]: {"question": r["question_text"], "reason": r["reason"], "language": r["language"]}
             for r in todo}
    try:
        result, _ = core._run_stage(triage, config.LLM_TIMEOUT_S + 5, items)
    except core.StageError:
        log.warning("Request triage failed; showing the caregiver's own words for now")
        _triage_retry_at = time.monotonic() + TRIAGE_RETRY_S
        return
    for row in todo:
        got = result.get(row["reference"])
        if got:
            summary = json.dumps(got["summary"], ensure_ascii=False)
            requests_db.update(row["reference"], summary=summary, urgency=got["urgency"])
            row.update(summary=summary, urgency=got["urgency"])


@router.get("/requests")
def list_requests(status: str = "open"):
    if status not in (*requests_db.STATUSES, "all"):
        raise HTTPException(422, "Unknown status")
    rows = requests_db.list_requests(None if status == "all" else status)
    _fill_triage(rows)
    views = [_coord_view(r) for r in rows]
    if status == "open":  # most urgent first, then whoever has waited longest
        views.sort(key=lambda v: (URGENCY_RANK.get(v["urgency"], 1), v["created_at"]))
    return {"requests": views, "counts": requests_db.counts()}


def _row(reference: str) -> dict:
    row = requests_db.get(reference)
    if not row:
        raise HTTPException(404, "No request with that reference code")
    return row


@router.get("/requests/{reference}/audio")
def question_audio(reference: str):
    """The caregiver's own recording; for a tapped or typed question, the question read out by TTS."""
    row = _row(reference)
    if row["question_audio_path"]:
        path = config.REQUEST_AUDIO_DIR / Path(row["question_audio_path"]).name
        if path.is_file():
            return FileResponse(path)
    if row["question_text"]:
        try:
            path, _ = core._run_stage(core.synthesize, config.TTS_TIMEOUT_S, row["question_text"], row["language"])
            return FileResponse(path)
        except core.StageError:
            pass
    raise HTTPException(404, "No audio for this request")


@router.post("/requests/{reference}/status")
def set_status(reference: str, status: str = Form(...)):
    """Close a request, or reopen it (back to "replied" if it has a reply, else "open")."""
    row = _row(reference)
    if status == "closed":
        new = "closed"
    elif status == "open":
        new = "replied" if row["reply_text"] else "open"
    else:
        raise HTTPException(422, "status must be open or closed")
    return _coord_view(requests_db.update(row["reference"], status=new))


# --- voice reply: draft, read back, confirm ---------------------------------------------------------------

@router.post("/requests/{reference}/reply/draft")
def reply_draft(reference: str, audio: UploadFile = File(None), text: str = Form(None),
                lang: str = Form(config.DEFAULT_LANG)):
    """Transcribe the coordinator's spoken reply and put it into the caregiver's language. Nothing is saved:
    the reply is read back and only /reply/confirm saves it."""
    row = _row(reference)
    if row["status"] == "closed":
        raise HTTPException(409, "This request is closed")
    lang = core._lang(lang)
    if text is not None:
        source = normalise(text).strip()
    elif audio is not None:
        source = core._transcribe_upload(audio, lang)
    else:
        raise HTTPException(422, "no_speech")
    if not source:
        raise HTTPException(422, "no_speech")
    target = row["language"] if row["language"] in config.LANGUAGES else config.DEFAULT_LANG
    if target == lang:
        reply = source
    else:
        try:
            result, _ = core._run_stage(translate, config.LLM_TIMEOUT_S + 5, {"reply": source}, target, lang)
            reply = result["reply"]
        except core.StageError:
            raise HTTPException(502, "translate_error")
    readback = t("reply.readback", lang, reply=source)
    return {"reference": row["reference"], "source_text": source, "source_lang": lang,
            "reply_text": reply, "reply_lang": target, "readback_text": readback,
            "audio_url": core._speak(readback, lang)}


@router.post("/requests/{reference}/reply/confirm")
def reply_confirm(reference: str, source_text: str = Form(...), reply_text: str = Form(...),
                  decision: str = Form(None), audio: UploadFile = File(None),
                  lang: str = Form(config.DEFAULT_LANG)):
    """Spoken "yes" / "no" / "change" (or the Approve button: decision=yes). Saves only on yes."""
    lang = core._lang(lang)
    heard = None
    if decision not in ("yes", "no", "change"):
        heard = core._transcribe_upload(audio, lang) if audio is not None else ""
        decision = yes_no(heard, allow_change=True)
    if decision is None:
        text = t("reply.say_again", lang)
        return {"decision": None, "heard": heard, "text": text, "audio_url": core._speak(text, lang)}
    if decision == "change":
        return {"decision": "change", "heard": heard}
    if decision == "no":
        text = t("reply.not_sent", lang)
        return {"decision": "no", "heard": heard, "text": text, "audio_url": core._speak(text, lang)}

    row = _row(reference)
    if row["status"] == "closed":
        raise HTTPException(409, "This request is closed")
    reply_text, source_text = reply_text.strip(), source_text.strip()
    if not reply_text:
        raise HTTPException(422, "Empty reply")
    audio_name = None
    try:
        path, _ = core._run_stage(core.synthesize, config.TTS_TIMEOUT_S, reply_text, row["language"])
        audio_name = Path(path).name
    except core.StageError:  # "Check my reply" makes the audio when the caregiver asks
        log.warning("Reply TTS failed for %s; it will be made on request", row["reference"])
    saved = requests_db.save_reply(row["reference"], source_text, reply_text, audio_name)
    text = t("reply.sent", lang, ref=row["reference"])
    spoken = text.replace(row["reference"], core.spoken_reference(row["reference"]))
    return {"decision": "yes", "heard": heard, "request": _coord_view(saved), "text": text,
            "audio_url": core._speak(spoken, lang)}


# --- this week --------------------------------------------------------------------------------------------

@router.get("/stats")
def week_stats():
    return stats.this_week()
