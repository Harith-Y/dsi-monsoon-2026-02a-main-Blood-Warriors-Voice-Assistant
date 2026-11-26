"""Teach the assistant by voice (coordinators only, behind the same passcode as the dashboard).

    POST /kb/draft    coordinator audio (or "Make this an FAQ" from a replied request, or the Undo button)
                      -> a draft (new entry, change to an entry, or undo) and its spoken read back.
                      Nothing is saved.
    POST /kb/confirm  a short spoken "yes" / "no" / "change" (or the Approve button). On yes: translate into
                      every language, save, record the version, and update the live index (no restart).
    GET  /kb/history  the latest changes, for the /teach page.

Helpers (_transcribe_upload, _speak, _run_stage) are looked up on api.main at call time so test patches apply.
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

import api.main as core
import config
from api.coordinator_routes import require_coordinator
from asr.normalise import normalise
from coordinator import requests as requests_db
from generation.intent import yes_no
from i18n import t
from kb import store, teach

log = logging.getLogger(__name__)

router = APIRouter(prefix="/kb", dependencies=[Depends(require_coordinator)])


def _say(key: str, lang: str, status: int = 200, **extra) -> JSONResponse:
    text = t(key, lang)
    return JSONResponse(status_code=status, content={"text": text, "audio_url": core._speak(text, lang), **extra})


def _in(entry: dict | None, part: str, lang: str) -> Optional[str]:
    if not entry:
        return None
    return entry.get(f"{part}_{lang}") or entry.get(f"{part}_en")


# --- draft ------------------------------------------------------------------------------------------------

def _undo_draft(lang: str, said: Optional[str]) -> JSONResponse | dict:
    change = store.last_change()
    if not change:
        return _say("teach.nothing_to_undo", lang, kind="nothing")
    entry = (change["after"] or change["before"] or {}).get("entry")
    question = teach.sentence(_in(entry, "question", lang) or change["entry_id"])
    readback = t("teach.readback_undo_new" if change["action"] == "create" else "teach.readback_undo_edit",
                 lang, question=question)
    draft_id = uuid.uuid4().hex
    store.put_draft(draft_id, {"kind": "undo", "version_id": change["id"], "said": said, "lang": lang})
    return {"draft_id": draft_id, "kind": "undo", "said": said, "undo_action": change["action"],
            "entry_id": change["entry_id"], "question": _in(entry, "question", lang),
            "answer": _in(entry, "answer", lang),
            "before_answer": _in((change["before"] or {}).get("entry"), "answer", lang),
            "created_at": change["created_at"], "readback_text": readback, "audio_url": core._speak(readback, lang)}


@router.post("/draft")
def kb_draft(audio: UploadFile = File(None), text: str = Form(None), from_ref: str = Form(None),
             action: str = Form(None), lang: str = Form(config.DEFAULT_LANG)):
    lang = core._lang(lang)
    if action == "undo":  # the "Undo last change" button: same read back, same spoken yes
        return _undo_draft(lang, None)

    request = None
    if from_ref:
        row = requests_db.get(from_ref)
        if not row:
            raise HTTPException(404, "No request with that reference code")
        if not row["reply_text"]:
            return _say("teach.no_reply", lang, status=409, error="no_reply")
        request = {"question": row["question_text"] or "", "question_lang": row["language"],
                   "reply": row["reply_source_text"] or row["reply_text"]}
        said, from_ref = f"{request['question']}\n{request['reply']}", row["reference"]
    elif text is not None:
        said = normalise(text).strip()
    elif audio is not None:
        said = core._transcribe_upload(audio, lang, config.TEACH_ASR_TIMEOUT_S)
    else:
        said = ""
    if not said:
        raise HTTPException(422, "no_speech")
    if not request and teach.is_undo(said):
        return _undo_draft(lang, said)

    try:
        candidates, _ = core._run_stage(core.retrieve, config.RETRIEVE_TIMEOUT_S + 25, request["question"] if request else said, 3)
    except core.StageError:
        candidates = []
    try:
        d, _ = core._run_stage(teach.draft, config.LLM_TIMEOUT_S + 10, said, lang, candidates, request)
    except core.StageError as e:
        cause = e.__context__
        if isinstance(cause, teach.TeachError):
            return _say(cause.key, lang, status=422, error=cause.key, said=said)
        log.warning("Teach draft failed: %s", type(cause).__name__ if cause else "timeout")
        raise HTTPException(502, "teach_error")

    if d["action"] == "undo":
        return _undo_draft(lang, said)
    if d["action"] == "unclear":
        return _say("teach.faq_unclear" if request else "teach.unclear", lang, kind="unclear", said=said)

    kind = "new" if d["action"] == "new" else "edit"
    old = store.get(d["entry_id"]) if kind == "edit" else None
    readback = t(f"teach.readback_{kind}", lang, question=teach.sentence(d["question"]),
                 answer=teach.sentence(d["answer"]))
    draft_id = uuid.uuid4().hex
    store.put_draft(draft_id, {**{k: d[k] for k in ("entry_id", "changed", "category", "question", "answer",
                                                     "question_en", "answer_en", "phrasings")},
                               "kind": kind, "said": said, "lang": lang, "from_ref": from_ref})
    return {
        "draft_id": draft_id, "kind": kind, "said": said, "from_ref": from_ref, "entry_id": d["entry_id"],
        "changed": d["changed"], "category": d["category"], "question": d["question"], "answer": d["answer"],
        "before_question": _in(old, "question", lang), "before_answer": _in(old, "answer", lang),
        "phrasings": d["phrasings"], "to_coordinator": teach.goes_to_coordinator(d),
        "readback_text": readback, "audio_url": core._speak(readback, lang),
    }


# --- confirm ----------------------------------------------------------------------------------------------

@router.post("/confirm")
def kb_confirm(draft_id: str = Form(...), decision: str = Form(None), audio: UploadFile = File(None),
               lang: str = Form(config.DEFAULT_LANG)):
    """Spoken "yes" / "no" / "change" (or decision=yes from the Approve button). Saves only on yes."""
    lang = core._lang(lang)
    d = store.get_draft(draft_id)
    if not d:
        return _say("teach.draft_gone", lang, status=404, error="draft_gone")
    heard = None
    if decision not in ("yes", "no", "change"):
        heard = core._transcribe_upload(audio, lang) if audio is not None else ""
        decision = yes_no(heard, allow_change=True)
    if decision is None:
        return _say("reply.say_again", lang, decision=None, heard=heard)
    if decision == "change":
        store.drop_draft(draft_id)
        return {"decision": "change", "heard": heard}
    if decision == "no":
        store.drop_draft(draft_id)
        return _say("teach.not_saved" if d["kind"] != "undo" else "teach.not_undone", lang, decision="no", heard=heard)

    if d["kind"] == "undo":
        try:
            done = store.undo(d["version_id"], d.get("said"), lang)
        except Exception as e:
            log.warning("Undo failed: %s: %s", type(e).__name__, e)
            raise HTTPException(502, "save_error")
        if not done:
            store.drop_draft(draft_id)
            return _say("teach.stale", lang, status=409, error="stale")
        store.drop_draft(draft_id)
        return _say("teach.undone", lang, decision="yes", heard=heard, kind="undo", entry_id=done["entry_id"],
                    count=len(store.entries()))

    try:
        (entry, phrasings), _ = core._run_stage(teach.build_entry, config.TEACH_TRANSLATE_TIMEOUT_S, d, d["lang"])
    except core.StageError as e:
        if isinstance(e.__context__, LookupError):
            store.drop_draft(draft_id)
            return _say("teach.stale", lang, status=409, error="stale")
        log.warning("Teach translation failed: %s", type(e.__context__).__name__ if e.__context__ else "timeout")
        raise HTTPException(502, "translate_error")  # the draft stays, so Approve can be tried again
    try:
        version = store.save(entry, phrasings, d.get("said"), d["lang"], d.get("from_ref"))
    except Exception as e:
        log.warning("Teach save failed: %s: %s", type(e).__name__, e)
        raise HTTPException(502, "save_error")
    store.drop_draft(draft_id)
    return _say("teach.saved" if d["kind"] == "new" else "teach.updated", lang, decision="yes", heard=heard, kind=d["kind"],
                entry_id=entry["id"], version_id=version["id"], question=_in(entry, "question", lang),
                answer=_in(entry, "answer", lang), count=len(store.entries()))


# --- history ----------------------------------------------------------------------------------------------

@router.get("/history")
def kb_history(lang: str = config.DEFAULT_LANG, limit: int = 8):
    lang = core._lang(lang)
    changes = []
    for row in store.history(max(1, min(limit, 30))):
        entry = (row["after"] or row["before"] or {}).get("entry")
        undone = None
        if row["action"] == "undo" and row["undo_of"]:
            undone = store.get_version(row["undo_of"])
        changes.append({
            "id": row["id"], "action": row["action"], "entry_id": row["entry_id"],
            "question": _in(entry, "question", lang), "answer": _in(entry, "answer", lang),
            "undone": bool(row["undone_at"]), "undo_of_action": undone["action"] if undone else None,
            "from_ref": row["from_ref"], "created_at": row["created_at"],
        })
    last = store.last_change()
    return {"changes": changes, "count": len(store.entries()), "can_undo": last is not None}
