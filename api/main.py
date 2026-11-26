"""FastAPI orchestration: transcribe -> normalise -> is_urgent? -> retrieve -> decide ->
generate_answer -> synthesize -> log. Every stage fails safe into the coordinator hand-off, which saves a
request (reference code BW-1042 style) and offers a WhatsApp chat link to the coordinator. No phone calls."""

import logging
import re
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from api.log import log_request
from asr.normalise import normalise
from asr.transcribe import transcribe
from coordinator import requests as requests_db
from coordinator.whatsapp import whatsapp_url
from generation.answer import generate_answer, simplify_answer
from generation.confidence import clarify_prompt, decide
from generation.intent import yes_no
from generation.safety import is_urgent
from i18n import STRINGS_PATH, _data as _i18n_data, t
from retrieval.index import get_entry, load as load_retrieval, passage, retrieve
from tts.synthesize import synthesize

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # LaBSE takes longer to load than RETRIEVE_TIMEOUT_S, so load it before the first request (#5).
    try:
        load_retrieval()
    except Exception as e:  # server still starts; retrieve() retries the load and falls back if it fails
        log.warning("Retrieval warm-up failed: %s: %s", type(e).__name__, e)
    if config.ASR_WARMUP:
        # The first IndicConformer call loads the model (~6 s); do it now, in the background, not on a caregiver.
        _executor.submit(_warm_asr)
    yield


def _warm_asr() -> None:
    wav = None
    try:
        import numpy as np
        import soundfile as sf
        with NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav = Path(tmp.name)
        sf.write(str(wav), np.zeros(16000, dtype="float32"), 16000)
        transcribe(str(wav), None, "te")
        log.info("ASR warmed up")
    except Exception as e:
        log.warning("ASR warm-up failed: %s: %s", type(e).__name__, e)
    finally:
        if wav:
            wav.unlink(missing_ok=True)


app = FastAPI(lifespan=lifespan)
_executor = ThreadPoolExecutor(max_workers=4)
# session_id -> {"clarified": bool}; in memory, demo only (#14). Lost on restart, which just allows one more clarify.
_sessions: dict[str, dict] = {}

# Fallback reasons that mean "a person should look at this question": each one saves a request.
HANDOFF_REASONS = {"urgent", "low_confidence", "not_covered", "llm_error"}
# Fallback reasons that mean "we never understood the question": the UI offers a retry, no request.
ERROR_KEYS = {"asr_error": "error.asr", "no_speech": "error.no_speech"}


class AskResponse(BaseModel):
    lang: str = config.DEFAULT_LANG
    transcript: Optional[str] = None
    answer: Optional[str] = None      # shown and spoken, in `lang`
    answer_en: Optional[str] = None   # English version (caption under the answer when lang is not English)
    answer_te: Optional[str] = None   # Telugu answer when lang == "te" (used by the evaluation scripts)
    audio_url: Optional[str] = None
    source_id: Optional[str] = None
    source: Optional[str] = None      # where the KB entry comes from, shown under the answer
    fallback: bool
    clarify: bool = False  # True: answer/answer_en hold a "did you mean ...?" question (#14)
    clarify_question: Optional[str] = None  # the KB question to ask if the person says "yes"
    sample: bool = False   # the answer uses fictional sample data (the UI labels it "Sample data")
    fallback_reason: Optional[str] = None
    reference: Optional[str] = None   # BW-1042 style, set when the question was handed to a coordinator
    whatsapp_url: Optional[str] = None
    score: Optional[float] = None
    latency_ms: dict


def _run_stage(func, timeout_s: float, *args):
    """Run func(*args) with a timeout; elapsed ms is always returned, errors re-raised."""
    t0 = time.monotonic()
    try:
        result = _executor.submit(func, *args).result(timeout=timeout_s)
        return result, int((time.monotonic() - t0) * 1000)
    except Exception:
        raise StageError(int((time.monotonic() - t0) * 1000))


class StageError(Exception):
    def __init__(self, elapsed_ms: int):
        self.elapsed_ms = elapsed_ms


def is_sample(source: Optional[str]) -> bool:
    """KB entries built on the fictional demo family are labelled "Sample data" in the UI."""
    return bool(source) and any(w in source.lower() for w in ("fictional", "demo", "sample"))


def spoken_reference(reference: str) -> str:
    """'BW-1042' -> 'B W 1 0 4 2', so TTS reads it letter by letter and digit by digit."""
    return " ".join(ch for ch in reference if ch.isalnum())


def _handoff_text(reason: str, reference: Optional[str], lang: str) -> str:
    if not reference:  # the request could not be saved: still point them to WhatsApp
        return t("fallback.unsent", lang)
    head = t("fallback.urgent" if reason == "urgent" else "fallback.sent", lang)
    return f"{head} {t('fallback.reference', lang, ref=reference)}"


def _fallback(reason: str, transcript: Optional[str], lang: str, latency_ms: dict,
              score: Optional[float] = None, audio_tmp: Optional[Path] = None) -> AskResponse:
    """Coordinator hand-off (saves a request) or, for asr_error / no_speech, a please-try-again message."""
    reference = None
    if reason in ERROR_KEYS:
        answer, answer_en = t(ERROR_KEYS[reason], lang), t(ERROR_KEYS[reason], "en")
    else:
        try:
            audio_name = None
            if audio_tmp and audio_tmp.exists():
                config.REQUEST_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                audio_name = f"{uuid.uuid4().hex}{audio_tmp.suffix or '.wav'}"
                shutil.move(str(audio_tmp), config.REQUEST_AUDIO_DIR / audio_name)
            reference = requests_db.create(transcript, lang, reason, audio_name)["reference"]
        except Exception as e:  # never lose the hand-off message because the database failed
            log.warning("Could not save coordinator request: %s: %s", type(e).__name__, e)
        answer, answer_en = _handoff_text(reason, reference, lang), _handoff_text(reason, reference, "en")
    return AskResponse(
        lang=lang, transcript=transcript, answer=answer, answer_en=answer_en,
        answer_te=answer if lang == "te" else None,
        fallback=True, fallback_reason=reason, reference=reference, score=score, latency_ms=latency_ms,
        whatsapp_url=whatsapp_url(transcript if reason not in ERROR_KEYS else None, reference, lang),
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(audio: UploadFile = File(None), text: str = Form(None), session_id: str = Form(None),
        lang: str = Form(config.DEFAULT_LANG)):
    lang = lang if lang in config.LANGUAGES else config.DEFAULT_LANG
    latency_ms = {"asr": 0, "retrieve": 0, "generate": 0, "tts": 0, "total": 0}
    t_total_start = time.monotonic()
    audio_tmp: Optional[Path] = None  # the caregiver's recording; kept only if the question is handed off

    def done(response: AskResponse, outcome: str, source_id=None, score=None, reason=None):
        # The hand-off message and the "did you mean...?" question are spoken too. The reference code is
        # spelled out so TTS reads it letter by letter.
        if (response.fallback or response.clarify) and response.audio_url is None and response.answer:
            spoken = response.answer
            if response.reference:
                spoken = spoken.replace(response.reference, spoken_reference(response.reference))
            try:
                audio_path, latency_ms["tts"] = _run_stage(synthesize, config.TTS_TIMEOUT_S, spoken, lang)
                response.audio_url = f"/audio/{Path(audio_path).name}"
            except StageError as e:  # no audio; the text and the WhatsApp button are still shown
                latency_ms["tts"] = e.elapsed_ms
        if response.whatsapp_url is None:
            response.whatsapp_url = whatsapp_url(response.transcript, response.reference, lang)
        latency_ms["total"] = int((time.monotonic() - t_total_start) * 1000)
        response.latency_ms = latency_ms
        log_request(response.transcript, source_id, score, outcome, reason, latency_ms,
                    lang=lang, reference=response.reference)
        return response

    def handoff(reason: str, transcript: Optional[str], score: Optional[float] = None):
        outcome = "error" if reason in ERROR_KEYS else "escalated"
        return done(_fallback(reason, transcript, lang, latency_ms, score, audio_tmp), outcome,
                    score=score, reason=reason)

    try:
        # --- ASR ---
        if text is not None:
            transcript = text
        else:
            if audio is None:
                return handoff("no_speech", None)
            suffix = Path(audio.filename or "clip.wav").suffix or ".wav"
            with NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio.file.read())
                audio_tmp = Path(tmp.name)
            try:
                transcript, latency_ms["asr"] = _run_stage(transcribe, config.ASR_TIMEOUT_S, str(audio_tmp), None, lang)
            except StageError as e:
                latency_ms["asr"] = e.elapsed_ms
                return handoff("asr_error", None)

        transcript = normalise(transcript or "").strip()
        if not transcript:
            return handoff("no_speech", None)

        # --- Safety gate (no retrieval, no LLM, if urgent) ---
        if is_urgent(transcript):
            return handoff("urgent", transcript)

        # --- Retrieve ---
        try:
            hits, latency_ms["retrieve"] = _run_stage(
                retrieve, config.RETRIEVE_TIMEOUT_S, transcript, config.RETRIEVAL_K
            )
        except StageError as e:
            latency_ms["retrieve"] = e.elapsed_ms
            return handoff("not_covered", transcript)

        top_score = hits[0]["score"] if hits else 0.0

        # --- Confidence: answer / ask once to clarify / coordinator (#14) ---
        session = _sessions.setdefault(session_id, {"clarified": False}) if session_id else None
        decision = decide(hits, session)
        if decision == "clarify":
            if session is not None:
                session["clarified"] = True
            question, question_en = clarify_prompt(hits[0], lang)
            top = hits[0]
            response = AskResponse(lang=lang, transcript=transcript, answer=question, answer_en=question_en,
                                   answer_te=question if lang == "te" else None, fallback=False, clarify=True,
                                   clarify_question=top.get(f"question_{lang}") or top.get("question_en"),
                                   score=top_score, latency_ms=latency_ms)
            return done(response, "clarify", source_id=hits[0]["id"], score=top_score)
        if decision == "fallback":
            return handoff("low_confidence", transcript, top_score)

        # --- Generate ---
        try:
            result, latency_ms["generate"] = _run_stage(
                generate_answer, config.GENERATE_TIMEOUT_S, transcript, hits, lang
            )
        except StageError as e:
            latency_ms["generate"] = e.elapsed_ms
            return handoff("llm_error", transcript, top_score)

        if result.get("fallback") or not result.get("source_id"):
            # generate_answer never raises; it says why it fell back (llm_error, not_covered, urgent).
            return handoff(result.get("reason") or "not_covered", transcript, top_score)

        answer = result["answer"]
        source_id = result["source_id"]
        cited = next((h for h in hits if h["id"] == source_id), {})
        # English version: the cited KB entry's own reviewed English answer (unless the answer is English).
        answer_en = answer if lang == "en" else (result.get("answer_en") or cited.get("answer_en"))

        # --- TTS (failure keeps the text answer, per #7) ---
        audio_url = None
        tts_failed_reason = None
        try:
            audio_path, latency_ms["tts"] = _run_stage(synthesize, config.TTS_TIMEOUT_S, answer, lang)
            audio_url = f"/audio/{Path(audio_path).name}"
        except StageError as e:
            latency_ms["tts"] = e.elapsed_ms
            tts_failed_reason = "tts_error"

        response = AskResponse(
            lang=lang,
            transcript=transcript,
            answer=answer,
            answer_en=answer_en,
            answer_te=answer if lang == "te" else None,
            audio_url=audio_url,
            source_id=source_id,
            source=cited.get("source"),
            sample=is_sample(cited.get("source")),
            fallback=False,
            fallback_reason=tts_failed_reason,
            score=top_score,
            latency_ms=latency_ms,
        )
        return done(response, "answered", source_id=source_id, score=top_score, reason=tts_failed_reason)
    finally:
        if audio_tmp:
            audio_tmp.unlink(missing_ok=True)  # already moved away if the question was handed off


def _lang(lang: Optional[str]) -> str:
    return lang if lang in config.LANGUAGES else config.DEFAULT_LANG


def _speak(text: str, lang: str) -> Optional[str]:
    """Audio URL for text, or None if TTS fails (the text is always shown anyway)."""
    try:
        path, _ = _run_stage(synthesize, config.TTS_TIMEOUT_S, text, lang)
        return f"/audio/{Path(path).name}"
    except StageError:
        return None


def _transcribe_upload(audio: UploadFile, lang: str, timeout_s: float = config.ASR_TIMEOUT_S) -> str:
    """Transcribe an uploaded clip (temp file removed afterwards). Raises HTTPException 422/502."""
    suffix = Path(audio.filename or "clip.wav").suffix or ".wav"
    with NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio.file.read())
        tmp_path = Path(tmp.name)
    try:
        text, _ = _run_stage(transcribe, timeout_s, str(tmp_path), None, lang)
    except StageError:
        raise HTTPException(502, "asr_error")
    finally:
        tmp_path.unlink(missing_ok=True)
    return normalise(text or "").strip()


@app.post("/simplify")
def simplify(source_id: str = Form(...), answer: str = Form(...), lang: str = Form(config.DEFAULT_LANG)):
    """'Say it simpler': the same answer in fewer, plainer words, grounded in the same KB entry."""
    lang = _lang(lang)
    entry = get_entry(source_id)
    if not entry:
        raise HTTPException(404, "Unknown source")
    try:
        simpler, _ = _run_stage(simplify_answer, config.GENERATE_TIMEOUT_S, answer, passage(entry), lang)
    except StageError:
        simpler = None
    if not simpler:
        raise HTTPException(502, "Could not simplify right now")
    return {"answer": simpler, "audio_url": _speak(simpler, lang)}


@app.get("/speak")
def speak(key: str, lang: str = config.DEFAULT_LANG, ref: Optional[str] = None):
    """A fixed UI message from i18n/strings.json, spoken (only known keys, so this cannot speak arbitrary text)."""
    lang = _lang(lang)
    if key not in _i18n_data()["strings"]:
        raise HTTPException(404, "Unknown message")
    fields = {"ref": requests_db.normalise_reference(ref) or ""} if ref is not None else {}
    template = t(key, lang)
    if "{ref}" in template and not fields.get("ref"):
        raise HTTPException(422, "Message needs a reference code")
    if re.search(r"\{(?!ref\})[a-z_]+\}", template):
        raise HTTPException(422, "This message is spoken by its own endpoint")
    text = t(key, lang, **fields)
    spoken = text.replace(fields["ref"], spoken_reference(fields["ref"])) if fields.get("ref") else text
    return {"text": text, "audio_url": _speak(spoken, lang)}


@app.post("/intent")
def intent(audio: UploadFile = File(None), text: str = Form(None), lang: str = Form(config.DEFAULT_LANG)):
    """Short spoken reply on a yes/no screen: {"intent": "yes" | "no" | null, "transcript"}."""
    lang = _lang(lang)
    transcript = normalise(text).strip() if text is not None else _transcribe_upload(audio, lang)
    return {"intent": yes_no(transcript), "transcript": transcript}


@app.get("/config")
def ui_config(lang: str = config.DEFAULT_LANG):
    """What the web UI needs at start-up: languages and the general WhatsApp chat link."""
    return {"languages": list(config.LANGUAGES), "default_lang": config.DEFAULT_LANG,
            "whatsapp_url": whatsapp_url(None, None, _lang(lang))}


@app.get("/i18n/strings.json")
def i18n_strings():
    return FileResponse(STRINGS_PATH, media_type="application/json")


def _request_view(row: dict) -> dict:
    audio_url = None
    if row["reply_text"]:
        try:
            audio_url = f"/audio/{Path(synthesize(row['reply_text'], row['language'])).name}"
        except Exception as e:
            log.warning("Reply TTS failed: %s: %s", type(e).__name__, e)
    return {
        "reference": row["reference"], "status": row["status"], "language": row["language"],
        "question_text": row["question_text"], "reply_text": row["reply_text"], "reply_audio_url": audio_url,
        "created_at": row["created_at"], "replied_at": row["replied_at"],
        "whatsapp_url": whatsapp_url(row["question_text"], row["reference"], row["language"]),
    }


@app.post("/requests/lookup")
def lookup_request(audio: UploadFile = File(None), text: str = Form(None), lang: str = Form(config.DEFAULT_LANG)):
    """'Check my reply' by voice: the caregiver says their reference code in any language.
    {"found": bool, "heard": transcript, "request": {...} | None}"""
    lang = _lang(lang)
    heard = text if text is not None else _transcribe_upload(audio, lang)
    digits = requests_db.digits_from_speech(heard)
    if not digits and audio is not None and lang != "en":
        # Codes are often said in English ("B W one zero four two") even by Telugu/Hindi speakers.
        audio.file.seek(0)
        heard_en = _transcribe_upload(audio, "en")
        digits = requests_db.digits_from_speech(heard_en)
        heard = heard_en if digits else heard
    row = requests_db.get(digits) if digits else None
    return {"found": bool(row), "heard": heard, "request": _request_view(row) if row else None}


@app.get("/requests/{reference}")
def get_request(reference: str):
    """'Check my reply': status of a hand-off and, once a coordinator replied, the reply in the caregiver's
    language with spoken audio."""
    row = requests_db.get(reference)
    if not row:
        raise HTTPException(404, "No question with that reference code")
    return _request_view(row)


@app.get("/audio/{filename}")
def get_audio(filename: str):
    path = config.TTS_CACHE_DIR / Path(filename).name
    if not path.is_file():
        raise HTTPException(404, "Audio not found")
    return FileResponse(path)


# Coordinator pages (passcode-protected data; the pages themselves are static).
from api import coordinator_routes, teach_routes  # noqa: E402  (needs the helpers above)

app.include_router(coordinator_routes.public)
app.include_router(coordinator_routes.router)
app.include_router(teach_routes.router)


# /dashboard (the queue) and /teach (teach by voice) are two views of one coordinator page: one sign in.
@app.get("/dashboard", include_in_schema=False)
@app.get("/teach", include_in_schema=False)
def coordinator_page():
    return FileResponse(config.ROOT / "web" / "dashboard.html", headers={"Cache-Control": "no-cache"})


# The Blood Warriors web UI (web/): mounted last so every API route above takes precedence.
WEB_DIR = config.ROOT / "web"
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
