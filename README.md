# Blood Warriors Voice Assistant

Natural-language access: How might we enable people to access essential information and services
through the language and mode of interaction they are most comfortable with?

A voice-first website for the Blood Warriors Foundation (Hyderabad), which supports families of children with
thalassemia. A caregiver or donor taps one big mic and asks a question in **Telugu, Hindi, English or a mix**;
the assistant answers out loud (and on screen) **only from Blood Warriors' verified knowledge base**. If it is
not sure, or the question is medical, it does not guess: it saves the question for a coordinator, gives a
reference code (BW-1042 style) and offers a **Chat with coordinator on WhatsApp** link. Blood Warriors asked
for no phone calls, so there is no call button or `tel:` link anywhere.

Coordinators work by voice too: they reply to handed-off questions on the **dashboard** and add or correct
answers on the **teach** page. Everything is read back and saved only after they say "yes".

| Page | Who | What |
|---|---|---|
| `/` | Caregivers and donors | Ask by voice, hear the answer ("Say it again", "Say it simpler"), "Check my reply" with a reference code |
| `/dashboard` | Coordinators (passcode) | Queue of handed-off questions with an LLM summary and urgency tag, the caregiver's recording, reply by voice (translated into the caregiver's language), "Make this an FAQ", this week's numbers |
| `/teach` | Coordinators (passcode) | Teach a new answer, change one, or "undo the last change", all by voice |

All people, dates and hospitals in the sample answers are fictional and labelled **Sample data** in the UI.

## Quick start (for someone who just got this folder)

The easiest way is Docker: nothing else to install. Takes about 15 minutes the first time, mostly downloads.

**1. Install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/).** Wait until it says it
is running. Give it at least 6 GB of memory (Docker Desktop, Settings, Resources).

**2. Get two free keys:**
- **Groq API key**: sign in at <https://console.groq.com/keys> and create a key (starts with `gsk_`).
- **Hugging Face token**: sign in at <https://huggingface.co>, open
  <https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual> and accept its terms (needed for Telugu
  and Hindi speech), then create a "Read" token at <https://huggingface.co/settings/tokens> (starts with `hf_`).

**3. Create your settings file.** In a terminal, inside this folder:
```bash
cp .env.example .env          # Windows (PowerShell): copy .env.example .env
```
Open `.env` in any text editor and fill in:
```
GROQ_API_KEY=gsk_...
HF_TOKEN=hf_...
COORDINATOR_PASSCODE=2468            # any 4 or more digits, for /dashboard and /teach
COORDINATOR_WHATSAPP=91XXXXXXXXXX    # the coordinator's WhatsApp number, with country code
```
Never share or commit `.env`: it holds your keys.

**4. Start it:**
```bash
docker compose up --build
```
The first run builds the app (a few minutes) and downloads the speech and search models (about 4 GB). When the
log says `Application startup complete`, wait about one more minute for the speech model to load.

**5. Open <http://localhost:8000>** in Chrome, Edge or Safari, and allow the microphone.
- Use `localhost`, not `0.0.0.0` or your computer's IP: browsers only allow the microphone on `localhost`
  or `https`.
- Coordinators: <http://localhost:8000/dashboard> and <http://localhost:8000/teach> (sign in with the
  passcode from step 3, said one number at a time or tapped).

**6. Stop it** with `Ctrl+C` in that terminal (or `docker compose down`). Next time, `docker compose up` starts
in seconds: models and data are kept.

Prefer not to use Docker? See Setup and How to run below (Python 3.10+, about 2 GB of packages).

## Setup

Requires Python 3.10+ (3.12 used) and `ffmpeg` on PATH (for audio that is not WAV), or just Docker (below).

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then fill it in (see the table)
```

| Variable in `.env` | Needed for |
|---|---|
| `GROQ_API_KEY` | Answers (LLM), translation, queue summaries, teach drafts, and English speech-to-text (Whisper) |
| `HF_TOKEN` | Telugu and Hindi speech-to-text: a Hugging Face account that accepted the terms of `ai4bharat/indic-conformer-600m-multilingual` (gated, ~2.6 GB, downloads on first use) |
| `COORDINATOR_WHATSAPP` | The "Chat with coordinator on WhatsApp" link: digits with country code, e.g. `91XXXXXXXXXX` |
| `COORDINATOR_PASSCODE` | Sign in to `/dashboard` and `/teach`: digits only, at least 4, so it can be said aloud or tapped. Empty switches coordinator sign in off |
| `BW_DATA_DIR` (optional) | Where SQLite (requests, KB history) and request audio live. Default `data/runtime/` |
| `BW_KB_PATH`, `BW_KB_VARIANTS_PATH`, `BW_INDEX_DIR`, `BW_TTS_CACHE_DIR`, `BW_LOG_PATH` (optional) | Move the live knowledge base, search index, audio cache and request log (Docker puts them all in `/data`) |
| `BW_ASR_WARMUP` (optional) | `0` skips loading the speech model at start-up |

Secrets stay in `.env` (git-ignored, and never copied into the Docker image).

## How to run

```bash
uvicorn api.main:app --port 8000        # then open http://localhost:8000 (and /dashboard, /teach)
```

The first start downloads LaBSE (~1.8 GB) and builds the search index from `kb/entries.json`. Run a single
worker: the live index, the sign-in rate limit and the "did you mean" sessions live in the process.

### With Docker

```bash
cp .env.example .env                     # fill it in
docker compose up --build                # http://localhost:8000
```

- The image has CPU-only PyTorch and no secrets; `.env` is read when the container starts.
- Volume `models` (`/models`) keeps the downloaded models, so only the first start is slow (a few GB).
- Volume `data` (`/data`) keeps the live knowledge base, its version history, coordinator requests, caregiver
  recordings, spoken audio and the request log. On first start the knowledge base is copied from `kb/`; after
  that the volume's copy is the live one, so coordinators' changes survive a rebuild. To start again from the
  repository's knowledge base, delete `/data/kb` and `/data/index` (or the whole `data` volume) and restart.

### Demo walkthrough

`docs/demo.md` has the timed script. In short:

1. **Caregiver** (`/`): tap the mic, ask "Next transfusion eppudu?". Hear the answer, see the source and the
   Sample data label; try "Say it simpler".
2. **Hand-off**: ask "Naa child ki fever undi, transfusion cheyacha?". It is not answered: you get a reference
   code and the WhatsApp chat button, with the question already typed.
3. **Coordinator** (`/dashboard`): say the passcode, open the fever question (tagged Urgent), tap **Reply by
   voice**, speak, hear it read back, say "yes". On the caregiver page, **Check my reply** plays it in Telugu.
4. **Teach** (`/teach`): tap the mic, say a question and its answer, hear it read back, say "yes". Ask it on
   the caregiver page straight away. Then say "undo the last change" and "yes".

## Teach by voice (`/teach`)

1. `POST /kb/draft`: the coordinator's audio is transcribed (up to 60 s), the closest entries are found with
   the normal retrieval, and the LLM (strict JSON, `kb/teach.py`) decides: a **new** entry (question, answer,
   topic, and 4 other phrasings: Telugu, Hindi, Telugu-English and Hindi-English), an **edit** of one of those
   entries (only the parts they changed), **undo**, or **unclear**. It may only restate what was said, never add
   facts, and an answer that tells people to phone anyone is refused. The draft is shown as a card and read
   back: "I understood a new question. Question: ... Answer: ... Should I save this?". Nothing is saved.
2. `POST /kb/confirm`: a short spoken "yes" / "no" / "change" (Telugu, Hindi or English), or the big Approve
   button. On yes the entry is translated into every language (the coordinator's own words are kept for their
   language), saved to `kb/entries.json` and `kb/question_variants.json`, and the FAISS index is updated in
   place: only the new phrasings are embedded, and the server is not restarted. If any step fails, nothing
   changes.
3. Every change is a row in SQLite (`kb_versions`: before, after, what was said, language). "Undo the last
   change" (said, or the Undo button) reads back what it will undo and, on yes, puts the entry back exactly as
   it was; saying it again steps further back. `GET /kb/history` feeds the Recent changes list.
4. **Make this an FAQ** on a replied request in the dashboard opens Teach with a draft made from the caregiver's
   question and the coordinator's reply, with anything about that one family left out.

Answers taught this way are marked `"source": "Blood Warriors coordinator, taught by voice on <date>"` and
`"authoritative": true`; editing a fictional sample record keeps its Sample data label.

## Coordinator dashboard (`/dashboard`)

- **Sign in** by saying the passcode (one number at a time, any language) or on the keypad. Five wrong tries in
  a minute locks sign in for a minute. The session is an HttpOnly, SameSite=strict cookie. This is demo-level
  access control.
- **Queue**: requests (`requests` table) with the LLM's one-line summary in te / hi / en and an urgency tag
  (Urgent, Reply today, Routine; safety-gate questions are always Urgent), the caregiver's recording, and why it
  was handed off. Tabs for Waiting, Replied and Closed.
- **Reply by voice**: transcribe, translate into the caregiver's language, read back, then yes / no / change.
  The caregiver hears it under "Check my reply".
- **This week** (since Monday, India time): answered by the assistant, sent to coordinators, replies sent,
  average reply time, languages used.

## Troubleshooting

| What you see | Why, and what to do |
|---|---|
| "This browser can't record" or "The microphone needs a safe link" | The page is open on `0.0.0.0`, an IP address or plain `http`. Open <http://localhost:8000> instead. |
| "I can't use the microphone" | Allow the microphone for localhost (the lock or camera icon in the address bar), then tap Try again. |
| "I couldn't understand that" right after starting | The speech model is still loading (about a minute after start-up). Wait and try again. |
| Every question goes to a coordinator | `GROQ_API_KEY` is missing or wrong in `.env`. Fix it, then `docker compose up -d` to restart. |
| Telugu or Hindi speech never works | `HF_TOKEN` is missing, or the account did not accept the model's terms (Quick start, step 2). |
| `docker compose` says it cannot connect | Docker Desktop is not running. Start it and wait until it is ready. |
| The container stops while loading | Docker has too little memory. Give it at least 6 GB in Docker Desktop, Settings, Resources. |
| Port 8000 is already in use | Something else uses it. Stop that, or change `"8000:8000"` to `"8080:8000"` in `docker-compose.yml` and open <http://localhost:8080>. |
| Start again with the original answers | `docker compose down -v` (deletes taught answers, requests and the downloaded models), then `docker compose up --build`. |

## How an answer stays safe

`api/main.py` runs every question through the same steps; any failure goes to a coordinator, never to a guess.

1. **Speech to text** (`asr/transcribe.py`): Telugu and Hindi with AI4Bharat IndicConformer 600M on the
   server's CPU; English with Whisper on Groq.
2. **Safety gate** (`generation/safety.py`, terms in `data/safety_terms.json`): medical or urgent questions
   (fever, breathing trouble, bleeding...) go straight to a coordinator, before search or the LLM.
3. **Search** (`retrieval/index.py`): LaBSE embeddings in FAISS, plus character n-gram TF-IDF so a rare topic
   word (tattoo, malaria) decides between similar questions. Every question and extra phrasing of every entry
   is one vector, in all three languages.
4. **Confidence**: a best score of `ANSWER_THRESHOLD` (0.73) or more is answered; from `CLARIFY_THRESHOLD`
   (0.55) up to 0.73 the assistant asks once "Did you mean ...?"; below that, a coordinator gets it.
5. **Answer** (`generation/answer.py`): the LLM may use only the retrieved entries, must cite one, and replies
   `NO_ANSWER` otherwise; anything else is checked in code and handed off.
6. **Speech** (`tts/synthesize.py`): gTTS in the caregiver's language. If it fails, the text is still shown.

Every on-screen and spoken message comes from one translations file, `i18n/strings.json` (Telugu and Hindi
need a native speaker's review).

## Tests and evaluation

```bash
pytest -q                               # unit tests, no network (add -m live for real models and APIs)

python eval/run_retrieval.py            # retrieval hit@1 / hit@3       -> results/retrieval.json
python eval/run_asr.py                  # word error rate on clips      -> results/asr.json (clips in data/audio/)
python eval/run_generation.py           # groundedness and hand-offs    -> results/generation.json
python eval/run_latency.py              # end-to-end latency (server running) -> results/latency.json
python eval/make_metrics.py             # one sheet from all of them    -> results/metrics.md
```

- `tests/test_teach.py`: teach draft and confirm (spoken and tapped), the live index update, undo, rollback on
  failure, "Make this an FAQ".
- `tests/test_dashboard.py`, `tests/test_coordinator.py`: sign in, the queue, voice replies, request creation
  on hand-off, the WhatsApp link format, and that no `tel:` link exists anywhere.
- `tests/test_web.py`, `tests/test_languages.py`: the web pages (labels, no hard-coded text) and te / hi / en.

Latest measured numbers (`results/`, 41 entries): retrieval hit@1 81.0% and hit@3 87.9% on 58 typed in-scope
questions; every generated answer cites a retrieved entry, and every out-of-scope or medical test question went
to a coordinator. Teaching by voice changes the knowledge base, so rerun the scripts after a teaching session.

## Project layout

| Folder | What |
|---|---|
| `api/` | FastAPI app: `main.py` (caregiver pipeline, pages), `coordinator_routes.py` (`/coord/*`), `teach_routes.py` (`/kb/*`) |
| `web/` | The site: `index.html` (caregiver), `dashboard.html` (`/dashboard` and `/teach`), `css/`, `js/` |
| `asr/`, `retrieval/`, `generation/`, `tts/` | Speech to text, search, LLM answer / translation / safety, text to speech |
| `kb/` | `entries.json` (verified answers), `question_variants.json` (extra phrasings), `store.py` (live changes and history), `teach.py` (teach drafts) |
| `coordinator/` | SQLite requests, sign in, queue summaries, this week's numbers, WhatsApp link |
| `i18n/` | `strings.json`: every user-facing string in te / hi / en |
| `eval/`, `results/`, `data/audio/` | Evaluation scripts, their results, recorded test clips |
| `docs/` | `demo.md` (demo script), `kb_review.md` (native-speaker review sheet), `architecture.dot` |
| `docker/`, `Dockerfile`, `docker-compose.yml` | Container set-up |

## Working agreements

- Small commits with clear messages; secrets only in `.env`; update this README and `.env.example` with any new
  setting.
- No phone calls and no `tel:` links; no em dashes in any user-facing text; sample data is labelled as sample.
