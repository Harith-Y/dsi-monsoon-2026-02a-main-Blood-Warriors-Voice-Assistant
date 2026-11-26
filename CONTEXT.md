# CONTEXT.md — Background spec for the Blood Warriors Telugu Voice Assistant (Project 02A)

> **Read CLAUDE.md first.** This file is background: the why, the data schemas, the safety rules and
> the evaluation targets. Where it disagrees with CLAUDE.md (folder names, function names, issue
> numbers, the ASR model, the separate demo-record path, donor confirm/decline logging),
> **CLAUDE.md and the GitHub issues win.**

You are helping build **POC v0.1** of a Telugu voice question-answering assistant for the
Blood Warriors Foundation (Hyderabad). Read this whole file before writing code.

**Sprint 2 checkpoint:** a first working technical POC exists, even if crude or incomplete.
**Sprint 2 deliverables:** (1) a technical design doc with spec/architecture, initial implementation
and a baseline result (what worked, what didn't); (2) POC v0.1 foundations ready before the Hack 1 demo.
Your job is (2), plus producing the numbers and notes that fill section 5 of (1).

---

## 1. What we are building (one paragraph)

A caregiver of a thalassemia patient, or a Blood Bridge donor, speaks a question in Telugu or
Telugu–English code-mix ("Next transfusion eppudu?"). The system transcribes it, works out the
intent, answers **only** from a curated Blood Warriors knowledge base (or a fictional demo record),
and speaks a short Telugu answer back with the source shown. If it is not confident, or the
question is medical/urgent, it says so plainly and points the user to the coordinator.
It informs; it never diagnoses, triages, or writes to any Blood Warriors system.

## 2. Non-negotiable rules

1. **No invented medical or eligibility information.** Every answer must trace to a KB entry id
   or a demo-record field. If it can't, return the fallback. Zero hallucinated medical info is a pass/fail criterion.
2. **Safety check runs before retrieval.** Symptom/urgency language (fever, bleeding, breathlessness,
   unconscious, emergency, chest pain, "hospital lo admit", and Telugu equivalents) → immediate
   coordinator hand-off. Do not retrieve, do not let the LLM answer.
3. **No real personal data.** All names, blood groups, hospitals, dates in demo records are fictional.
   Only team members' voices (with consent) in the audio test set.
4. **Synthetic (TTS-generated) speech is never the primary ASR evaluation set.** It may be used as
   marked augmentation only.
5. **Secrets live in `.env`** (`SARVAM_API_KEY`, `GROQ_API_KEY`). Never commit `.env`; keep `.env.example` updated.
6. **Scope guard.** No auth, accounts, dashboards, WhatsApp/IVR integration, or scheduling logic.
   If a task drifts into these, stop and say so.
7. **Verify external APIs before coding against them.** Model ids and endpoints change. Check current
   Sarvam and Groq docs for: the Sarvam STT model that returns a **Telugu transcript** (not an English
   translation — Sarvam's speech-*translate* models output English), its audio length/format limits,
   and the current Groq Llama model id. Record what you used in `docs/decisions.md`.

## 3. Architecture

```
mic / audio file (16 kHz mono WAV)
  └─► [1] ASR            providers/asr_*.py   → Telugu (code-mixed) transcript + ASR latency
  └─► [2] Normalise      pipeline/normalise.py → lexicon maps Telugu-script English terms
                                                 (హెచ్‌పీఎల్‌సీ→HPLC, ట్రాన్స్‌ఫ్యూజన్→transfusion, ...)
  └─► [3] Safety gate    pipeline/safety.py    → if urgent/medical: FALLBACK(reason="safety")
  └─► [4] Intent         pipeline/intent.py    → schedule | eligibility | donation_request | general | unknown
  └─► [5a] Personal intents → pipeline/records.py  lookup in data/mock_records.json, fill a fixed template
      [5b] general         → pipeline/retrieve.py LaBSE embeddings + FAISS top-k with cosine scores
  └─► [6] Confidence     pipeline/confidence.py → answer | clarify (once per session) | fallback
  └─► [7] Answer gen     providers/llm_groq.py  constrained prompt, retrieved passages only,
                                                 must output NO_ANSWER sentinel if not covered
  └─► [8] TTS            providers/tts_*.py     Telugu audio
  └─► [9] Log            pipeline/log.py        JSONL: every turn, unanswered Qs, donor confirm/decline
```

**Provider interfaces** (so we can swap without touching the pipeline):

| Stage | Interface | Primary (Hack 1) | Alternative / baseline comparison |
|---|---|---|---|
| ASR | `transcribe(wav_path) -> {text, lang, latency_ms}` | Sarvam STT API | AI4Bharat IndicConformer (local), only if a GPU is available and time permits |
| Embeddings | `embed(list[str]) -> np.ndarray` (L2-normalised) | LaBSE via sentence-transformers | MuRIL-based encoder; `paraphrase-multilingual-MiniLM-L12-v2` if LaBSE download is too heavy |
| LLM | `generate(question, passages) -> {text, used_ids}` | Groq, Llama 70B-class | none for Hack 1 |
| TTS | `speak(text, lang="te") -> wav/mp3 path` | gTTS | Sarvam TTS or AI4Bharat Indic-TTS if gTTS quality is poor |

Note: LaBSE is a large download (well over the ~100 MB assumed in the prep doc). Check disk and
download it once into `models/` (git-ignored).

## 4. Repo layout

```
bw-voice/
├── CLAUDE.md
├── README.md                 setup + run + demo steps
├── .env.example
├── requirements.txt          fastapi uvicorn gradio requests faiss-cpu sentence-transformers gTTS
│                             jiwer python-dotenv pydantic soundfile numpy
├── app/
│   ├── main.py               FastAPI: POST /ask (audio or text), GET /health
│   ├── ui.py                 Gradio demo: mic, transcript, answer card, audio, source, fallback card
│   ├── config.py             thresholds, model ids, paths (all tunables here)
│   ├── providers/            asr_sarvam.py, asr_indicconformer.py, llm_groq.py, tts_gtts.py, embed.py
│   └── pipeline/             normalise.py, safety.py, intent.py, records.py, retrieve.py,
│                             confidence.py, orchestrate.py, log.py
├── data/
│   ├── kb.json               knowledge base (schema §5)
│   ├── mock_records.json     fictional demo caregiver + donor
│   ├── lexicon.json          code-mix normalisation map
│   ├── safety_terms.json     Telugu + English + romanised urgent/medical terms
│   └── index/                FAISS index + id map (generated)
├── eval/
│   ├── questions.json        test set (schema §5)
│   ├── audio/                self-recorded WAVs + transcripts.json (reference transcripts)
│   ├── run_asr.py            WER + CER per clip and per variant type
│   ├── run_retrieval.py      hit@1, hit@3, MRR on text questions
│   ├── run_fallback.py       fallback precision/recall on in-scope vs out-of-scope/medical
│   ├── run_e2e.py            audio → answer, per-stage latency
│   └── grade_answers.csv     manual groundedness/correctness grading sheet
├── results/                  baseline.md + raw JSON outputs (feeds design doc §5)
├── logs/                     turns.jsonl, unanswered.jsonl, donor_responses.jsonl (git-ignored)
├── docs/decisions.md         dated log of choices + what was tried
└── tests/                    pytest: safety gate, confidence logic, records lookup, schema checks
```

## 5. Data schemas

**`data/kb.json`** — list of entries, 15–20 for Hack 1 (target 40–50 later):
```json
{"id": "elig-01", "category": "donor_eligibility",
 "question_te": "...", "question_en": "When can I donate blood again?",
 "answer_te": "...", "answer_en": "...",
 "source": "Blood Warriors donor FAQ | NBTC guideline | team-authored (non-authoritative)",
 "authoritative": true}
```
Categories and counts: `transfusion_schedule` 3–4, `donor_eligibility` 3–4, `donation_request` 2–3,
`hplc_testing` 2–3, `general` 4–5. Telugu must be conversational, not clinical.
Index both `question_te` and `question_en` (and optionally `answer_*`) → each vector maps back to the entry id.
Eligibility facts (e.g. whole-blood donation gap) must be copied from a cited guideline, not from memory;
if no source is at hand, mark the entry `authoritative: false` and flag it in `docs/decisions.md`.

**`data/mock_records.json`** — fictional, matches the clickable prototype so the demo is coherent:
caregiver "Aarav's family", next transfusion Sat 3 Oct 2026, 9:30 AM, Niloufer Hospital, B+, 1 unit;
donor last donated 5 Jul 2026, eligible again 3 Oct 2026, one open donation request for Aarav.
The demo has a single hard-coded "current user" switch (caregiver | donor). No auth.

**`eval/questions.json`**:
```json
{"id": "q07", "base_id": "q07", "question_te": "...", "question_en": "...",
 "expected_kb_id": "elig-01" , "expected_behaviour": "answer | clarify | fallback",
 "category": "donor_eligibility",
 "variant_type": "telugu | rephrase | code_mixed | informal | out_of_scope | medical"}
```
At least 20 items: per base question 2–3 Telugu rephrasings, 1 code-mixed, 1 informal;
plus ≥5 out-of-scope and ≥3 medical/urgent items that must hit fallback.

**Audio test set:** 10–15 self-recorded clips (5–15 s, 16 kHz mono WAV) + 5 code-mixed clips,
recorded on phones in normal rooms (some background noise is good). `transcripts.json` holds the
human reference transcript for each. Record speaker id (team member) and device, nothing else.

## 6. Decision logic (implement exactly, tune numbers only via `config.py`)

```
transcript = normalise(asr(audio))
if safety.match(transcript):                      → FALLBACK("safety")   # no retrieval, no LLM
intent, intent_conf = intent.classify(transcript)  # keyword + embedding-to-intent-prototype similarity
if intent in {schedule, eligibility, donation_request} and intent_conf >= INTENT_T:
    → answer from mock record via fixed Telugu template (no LLM needed), source = "demo record"
hits = retrieve(transcript, k=3)
if hits[0].score >= ANSWER_T:                     → LLM(answer from hits) ; if NO_ANSWER → FALLBACK("not_covered")
elif hits[0].score >= CLARIFY_T and not session.clarified:
                                                  → CLARIFY: "Did you mean <hits[0].question_te>?" ; session.clarified = True
else:                                             → FALLBACK("low_confidence") ; log to unanswered.jsonl
```
- Thresholds are **calibrated on the eval set**, not guessed: sweep `ANSWER_T`/`CLARIFY_T`, pick the
  point that keeps medical/out-of-scope false-answers at 0 while maximising in-scope answers. Save the sweep plot/table to `results/`.
- LLM prompt: system message says answer in 1–3 short Telugu sentences using only the given passages,
  cite passage ids, otherwise output exactly `NO_ANSWER`. Temperature 0. Post-check that the
  output cites at least one supplied id; if not, treat as `NO_ANSWER`.
- Donation-request intent: the user can say yes/no ("avunu, istanu" / "ivvalenu"). Write
  `{timestamp, request_id, reply}` to `logs/donor_responses.jsonl` and speak a confirmation.
  This is the only "action", and it only writes a local log.
- Fallback message (Telugu + English caption): "This sounds like a medical question / I don't have a
  verified answer. Please contact your coordinator." Include the coordinator call button in the UI.

## 7. API contract

`POST /ask` — multipart `audio` (wav) **or** JSON `{"text": "..."}`, optional `session_id`, `user_role`.
Response:
```json
{"transcript": "...", "normalised": "...", "intent": "schedule",
 "outcome": "answer | clarify | fallback", "fallback_reason": null,
 "answer_te": "...", "answer_en": "...", "sources": ["elig-01"],
 "top_hits": [{"id": "elig-01", "score": 0.71}],
 "audio_url": "/audio/<id>.mp3",
 "latency_ms": {"asr": 0, "retrieve": 0, "llm": 0, "tts": 0, "total": 0}}
```
The Gradio UI calls the pipeline in-process (or this endpoint) and shows the four states from the
design: Idle (mic + example questions), Listening/transcript, Answer (text, replay audio, source),
Fallback (message + coordinator call). English captions under Telugu text for reviewers.

## 8. Build order

See CLAUDE.md. The build order and issue mapping there follow the real GitHub issues #1–#15.

## 9. Demo journeys (must all work)

1. **Caregiver, happy path:** "Next transfusion eppudu?" → schedule answer from mock record, spoken, source shown.
2. **Donor, code-mixed:** "Nenu blood donate cheyacha? Last time July lo ichanu." → eligibility answer, source shown.
3. **Medical fallback:** "Naa child ki fever undi, transfusion cheyacha?" → safety gate, no answer, coordinator hand-off, logged.

## 10. Evaluation targets (from the Hack 1 plan) and what to report

| Metric | Target | How |
|---|---|---|
| ASR WER (self-recorded Telugu, 10–15 clips) | < 30% | `jiwer`; also report **CER** (Telugu is agglutinative, so WER over-penalises) and split by variant type |
| Retrieval hit rate | ≥ 80% correct entry (hit@1; also report hit@3) | text questions, then ASR transcripts of the same questions |
| Groundedness | 100% of answers traceable; 0 hallucinated medical info | manual grading, two team members, disagreements noted |
| Fallback | all out-of-scope/medical items → fallback | precision/recall of the fallback decision |
| Latency | < 10 s end to end (stretch: 5–8 s) | p50 and p95 per stage over ≥ 10 runs |

`results/baseline.md` must contain: the numbers table, a "what worked" list, a "what didn't" list
with concrete failing examples (transcript vs reference), the thresholds chosen and why, and
what you would try next. Say plainly what the baseline does **not** establish (field viability,
real dialects, feature-phone/8 kHz audio, real users' trust).

## 11. Working conventions

- Python 3.10+, type hints, small pure functions in `pipeline/`; side effects only in providers and `log.py`.
- Every network call has a timeout and a clear error that ends in a fallback, never a crash in the demo.
- Cache TTS output by text hash; cache embeddings index on disk.
- Tests for: safety gate (each medical eval item triggers it), confidence branches, records lookup, JSON schemas.
- Keep `docs/decisions.md` updated: date, decision, reason, alternative rejected. The design doc is written from it.
- Don't add features outside §8 without asking. Prefer finishing the baseline over polishing the UI.

## 12. Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add SARVAM_API_KEY, GROQ_API_KEY
python -m app.pipeline.retrieve --build-index
uvicorn app.main:app --reload --port 8000
python -m app.ui                # Gradio demo
python eval/run_asr.py && python eval/run_retrieval.py && python eval/run_fallback.py && python eval/run_e2e.py
pytest -q
```
