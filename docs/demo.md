# Demo script: Blood Warriors Voice Assistant

Slot assumed: **5 minutes**. Change the times if your slot differs. Cells marked `____` are for the team to fill.
Everything on screen is a **fictional demo record**: no real patient or donor data.

## Roles

| Role | Who | Notes |
|---|---|---|
| Speaker (asks the questions in Telugu) | ____ | A Telugu speaker, with consent. Practise the 3 lines out loud. |
| Driver (runs the laptop, clicks) | ____ | Keeps the app running (`uvicorn` or `docker compose up`). |
| Narrator (explains what to look at) | ____ | Can be the same person as the driver. |
| Backup / watches the clock | ____ | Switches to the backup plan if something fails. |

## Before you start (2 minutes, not part of the slot)

1. `uvicorn api.main:app --port 8000` (or `docker compose up`) is running, and `http://localhost:8000` shows the Blood Warriors page.
   Open `http://localhost:8000/dashboard` in a second tab and sign in with the passcode from `.env`.
2. `curl localhost:8000/health` returns `{"status":"ok"}`.
3. `.env` has a working `GROQ_API_KEY`, `HF_TOKEN`, `COORDINATOR_PASSCODE` and `COORDINATOR_WHATSAPP`. Wi-Fi is on. Microphone permission is allowed in the browser.
4. Do one throw-away question first, so models are loaded and the first demo answer is fast.
5. Open `results/metrics.md` and the architecture diagram (render `docs/architecture.dot`, see its first line) in other tabs.

## 0:00 – 0:30 Intro (say this)

"Blood Warriors links each thalassemia patient to 8 to 10 donors who give blood every 15 to 20 days.
Today, coordination runs on WhatsApp and English-first apps, but most families speak Telugu and are
more comfortable listening than reading. So they wait for a coordinator to get back to them, and a transfusion
can be delayed or missed. We built the core of a fix: ask a question out loud in Telugu, and get a
short spoken Telugu answer taken only from a verified knowledge base. If it is not sure, or the question
is medical, it sends you to the coordinator instead of guessing."

Show the architecture diagram for 10 seconds. Point to the red **Safety gate** box and the red **Coordinator** box.

## 0:30 – 1:45 Journey 1: Caregiver asks about the next transfusion

| | |
|---|---|
| Do | Caregiver view. Click the mic and say: **"Next transfusion eppudu?"** (Telugu form: *నా తర్వాతి ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడు ఉంది?*) |
| Appears | "Listening…", then the transcript. Then the Answer card: Telugu answer (Saturday 3 October 2026, 9:30 AM, Niloufer Hospital, one unit of B+), English caption in grey below, a replay button, and **Source: sched-01**. The Telugu audio plays. |
| Point out | 1) The answer comes from a knowledge-base entry and the source id is shown, so anyone can check it. 2) The user did not read, type or open a menu. 3) The time it took: ____ s (from `results/e2e.json`, target under 10 s). |
| If it goes wrong | Click the example question "When is my next transfusion?" (text path, same pipeline). Say: "the microphone step failed, the rest is identical." |

## 1:45 – 3:00 Journey 2: Donor asks in mixed Telugu and English

| | |
|---|---|
| Do | Donor view. Say: **"Nenu blood donate cheyacha? Last time July lo ichanu."** (Telugu form: *నేను మళ్ళీ బ్లడ్ ఎప్పుడు డొనేట్ చేయొచ్చు? లాస్ట్ టైం జూలైలో ఇచ్చాను.*) |
| Appears | Transcript (it may mix scripts), then the Answer card: last donation 5 July 2026, can donate again from 3 October 2026, with caption and **Source: elig-01**. |
| Point out | 1) Real people mix Telugu and English; the English words ("blood", "donate") are normalised before search. 2) Still the same rule: answer only from a source entry. |
| If it goes wrong | Use the example button "When can I donate blood next?". If the answer is wrong, say so plainly and show the next journey: the system is built to escalate, not to cover mistakes. |

## 3:00 – 4:00 Journey 3: Medical question, the system refuses to answer

| | |
|---|---|
| Do | Say: **"Naa child ki fever undi, transfusion cheyacha?"** (Telugu form: *నా బిడ్డకి జ్వరం ఉంది, ట్రాన్స్‌ఫ్యూజన్ చేయొచ్చా?*) |
| Appears | The Fallback screen: "I've sent your question to a coordinator", spoken in Telugu, a reference code (BW-1042 style), and a **Chat with coordinator on WhatsApp** button that opens WhatsApp with the question and code already typed. No source, no call button. |
| Point out | 1) The safety check runs **before** retrieval and before the language model, so the model never sees this question. 2) No medical advice is given, ever. 3) The log records it: show the last line of `logs/requests.jsonl` (outcome `escalated`, reason `urgent`). |
| If it goes wrong | Tap the example question for the fever question. The WhatsApp button uses the number in `COORDINATOR_WHATSAPP`; say whose number it is if asked. |

## 4:00 – 5:00 Results and what's next

Show `results/metrics.md` (fill in only numbers that are in the file):

- Speech recognition error rate (WER / CER): ____
- Retrieval hit@1 / hit@3: ____
- Answers grounded in a source: ____ of ____ ; out-of-scope and medical questions that fell back: ____ of ____
- Latency p50 / p95: ____ / ____ s

Say what the numbers do **not** show: real users, real Telugu dialects, noisy rooms, 8 kHz phone audio, whether
people trust a machine voice for health information.

Closing line: "Next we validate with Blood Warriors caregivers, donors and coordinators; replace our team-written
entries with Blood Warriors' own FAQs, taught by coordinators by voice; and have native speakers review every
Telugu and Hindi string."

## Extended demo: the coordinator side (about 3 more minutes)

| | |
|---|---|
| Do | Second tab, `/dashboard`. Sign in by saying the passcode one number at a time (or tap it). |
| Appears | "This week" numbers, then the queue: the fever question from Journey 3 at the top, tagged **Urgent**, with a one-line summary in the coordinator's language and the caregiver's own recording. |
| Do | Tap **Reply by voice** and say a short reply in English. |
| Appears | "I understood: ... Should I send this to the caregiver?" is read back, with the Telugu translation shown. Say **"yes"** (or tap Approve). |
| Point out | Nothing is sent before the spoken yes. On the caregiver tab, **Check my reply** with the reference code plays the reply in Telugu. |
| Do | Tap **Teach** at the top, tap the mic and say a new question and its answer. |
| Appears | The draft card (question, answer, topic, 4 other ways people ask, including code-mixed ones) while it is read back. Say **"yes"**. |
| Point out | It is translated, saved and searchable straight away, with no restart: ask it on the caregiver tab. Then say **"undo the last change"** and "yes": it is gone again. |

## Backup plan

| What fails | Do this |
|---|---|
| Microphone | Tap an example question on the home screen (same pipeline, no speech step). |
| ASR gives garbage | Click the example button for the same question. Show the transcript and say it is a known weakness (see `results/metrics.md`). |
| Wi-Fi / Groq / TTS down | The live pipeline needs the internet (Groq and gTTS are online). Play the **pre-recorded screen video** of the three journeys, then show `results/metrics.md`. |
| Everything fails | Open `blood-warriors-prototype.html` (the design prototype, hard-coded answers). Say clearly that it is the design, not the working system. |

Human step before the demo: record a 2 to 3 minute screen video of the three journeys working and keep it on the laptop.

## Rehearsal log (fill in)

| # | Date | Time taken (m:ss) | Who ran it | Problems seen | Fixed? |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

The demo is ready when the last rehearsal fits the slot with no unfixed problem, and the backup plan was tried once.
