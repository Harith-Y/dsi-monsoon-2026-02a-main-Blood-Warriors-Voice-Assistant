# Decisions log

Dated log of choices made while building the POC: decision, reason, alternative rejected, issue number.

## 2026-10-14 — Issue #1

- **Decision:** Target Python 3.10+ as CLAUDE.md requires, installed via `py -3.10` (the system default
  `python` is 3.9 32-bit). **Reason:** faiss-cpu/sentence-transformers wheels and the pinned
  requirements assume 3.10+. **Alternative rejected:** none, this is a hard version requirement.
- **Decision:** `.gitignore` ignores `tts/cache/` (synthesized-audio cache) rather than all `*.wav`.
  **Reason:** `data/audio/*.wav` is the real recorded test corpus from #11 and must be committed;
  only the TTS output cache is disposable. **Alternative rejected:** a blanket `*.wav` ignore, which
  would silently drop the test corpus.
- **Decision:** `kb/`, `data/` get an `__init__.py` with a docstring like the code packages, even
  though they mostly hold JSON/audio, to follow issue #1's "each" literally. No functional effect.
- GROQ_MODEL and ASR_MODEL left blank in `config.py` — set once #3 and #6 confirm current model ids
  from the provider docs, per CLAUDE.md's "check model ids before coding against them" rule.

## 2026-10-14 — Issue #6

- **Decision:** `GROQ_MODEL = "llama-3.3-70b-versatile"`. **Reason:** listed under Production Models in Groq's supported-models docs (console.groq.com/docs/models) when checked; 128k context, JSON mode. **Alternative rejected:** `llama-3.1-8b-instant` (weaker Telugu, more risk of ungrounded answers); preview models (may be withdrawn). Re-check with `groq.models.list()` before the demo.
- **Decision:** `generate_answer` calls `is_urgent` itself as well as the API doing so (#7). **Reason:** the gate cannot be skipped by a caller; costs one regex. **Alternative rejected:** relying on the API wiring only.
- **Decision:** returns an extra `reason` key beyond the issue's three. **Reason:** #7 needs `fallback_reason` (`urgent`, `not_covered`, `llm_error`). **Alternative rejected:** API guessing the reason from the answer text.
- **Decision:** safety matching: Latin/romanised terms match at a word start, Telugu terms as substrings, zero-width characters removed first. **Reason:** "fits" must not fire on "benefits"; Telugu suffixes attach to words; ASR emits ZWNJ. **Alternative rejected:** plain substring for everything (false alarms), whole-word for Telugu (misses inflected forms).
- **Decision:** the LLM must return JSON `{answer, source_id}`; `source_id` must be one of the passage ids. **Reason:** this is what makes every answer traceable. **Alternative rejected:** asking the model to cite in free text.
- **Open:** safety terms and the Telugu fallback sentence not yet reviewed by a Telugu speaker.
## 2026-10-14 — Issue #2

- **Decision:** No Blood Warriors material was available, so the KB is self-curated from public sources;
  every entry is `authoritative: false`. **Reason:** CLAUDE.md marks public-reference entries
  non-authoritative; `true` is reserved for Blood Warriors' own material (#15). **Alternative rejected:**
  marking the Gazette-sourced entries authoritative, since the field is about Blood Warriors sign-off,
  not legal standing.
- **Decision:** Donor eligibility facts (age, weight, interval, haemoglobin, thalassemia trait, meal, alcohol)
  come from the Drugs and Cosmetics (Second Amendment) Rules, 2020, G.S.R. 166(E), Gazette of India,
  11 March 2020, "H. Criteria for Blood Donation" (read from the gazette PDF hosted at
  drugscontrol.py.gov.in). **Reason:** it is the legally binding text of the donor criteria. **Alternative
  rejected:** the NBTC "Guidelines for Blood Donor Selection & Blood Donor Referral" (2017). Its server
  (nbtc.naco.gov.in) timed out, and summaries of it found online were second-hand, so it was not cited.
- **Decision:** Thalassaemia, carrier and inheritance facts come from NHS pages ("Thalassaemia",
  "Thalassaemia – Causes"); the HPLC definition comes from The Blood Project, "Diagnosis of Thalassemia".
  **Reason:** the NHS gives the 1-in-4 / 1-in-2 / 1-in-4 inheritance odds and the carrier wording verbatim,
  and it does not name HPLC. **Alternative rejected:** WHO pages (none found with this content) and
  MedlinePlus (describes haemoglobin electrophoresis, does not mention HPLC).
- **Decision:** The demo schedule, eligibility and request answers are KB entries (`sched-01`, `elig-01`,
  `req-01`) with `source: "Fictional demo record"`, not a separate `data/mock_records.json`.
  **Reason:** CLAUDE.md and the design doc route every answer through the same grounded path.
  **Alternative rejected:** CONTEXT.md's separate records lookup with templates. The mock UI's source
  labels ("Blood Warriors Transfusion Registry", "Blood Bridge donation requests") were also dropped,
  because they read as real Blood Warriors data.
- **Decision:** The fictional donor is treated as male: last donation 5 July 2026 + 90 days =
  Saturday 3 October 2026, matching the prototype. `elig-01` only states the record's dates; the
  general 90/120-day rule lives in `elig-02`. **Reason:** the gazette interval differs by sex
  (90 days men, 120 days women), so `elig-01` must not state one rule as if it applied to everyone.
- **Flagged, no source (answer is "please ask your coordinator"):** `sched-02` (changing a date),
  `sched-04` (what to bring), `req-02` (accept/decline), `gen-04` (contacting the coordinator).
  `gen-05` (what the assistant can do) is team-authored scope text. Replace these with Blood Warriors
  material in #15.
- **Left out for lack of a source:** "is thalassemia contagious?", "what is Blood Bridge?", and
  "can I donate while on medicine?". Such questions get the coordinator fallback.
- **Decision:** Category keys are `transfusion_schedule`, `donor_eligibility`, `donation_request`,
  `hplc_testing`, `general` (as in CONTEXT.md §5). Ids are `sched-`, `elig-`, `req-`, `hplc-`, `gen-` + two digits.
- **Telugu was drafted by Claude, not a native speaker.** It is pending a teammate's review in `docs/kb_review.md`.

## 2026-10-14 — Issue #3 (Telugu ASR)

- **Issue text:** `gh` not installed and the repo is private, so #3 was worked from CLAUDE.md §4 #3.
- **Model ids checked:**
  - IndicConformer: `ai4bharat/indic-conformer-600m-multilingual` (Hugging Face, gated → `HF_TOKEN` in `.env`),
    loaded with `transformers.AutoModel(..., trust_remote_code=True)`, ONNX runtime, called as
    `model(wav, "te", "ctc")`. Model card pins `onnxruntime==1.20.1`, `onnx==1.20.1`.
  - IndicWhisper: AI4Bharat Vistaar Telugu checkpoint `whisper-medium-te_alldata_multigpu`, from
    `https://indicwhisper.objectstore.e2enetworks.net/telugu_models.zip` (not on the HF hub), unzipped to `models/`.
- **Comparison** (`eval/compare_asr.py data/audio/pilot_transcripts.json` → `results/asr_compare.json`):
  5 real-voice pilot clips (asr01–05, one speaker, 3 code-mixed + 2 Telugu, 2.6–5.7 s, 48 kHz stereo mp3),
  laptop CPU, no GPU, one warm-up call per model before timing. Punctuation and zero-width joiners stripped before scoring.

  | Model | WER | CER | s/clip | load |
  |---|---|---|---|---|
  | IndicConformer 600M (CTC) | 33.3% | 14.8% | 0.61 | 19 s |
  | IndicWhisper medium (te) | 36.4% | 19.7% | 103.5 | 88 s |

- **Decision:** IndicConformer (CTC) is the `transcribe()` backend (`config.ASR_MODEL`).
  **Reason:** slightly more accurate and ~170× faster on CPU; it fits the 10 s budget with room to spare,
  IndicWhisper does not fit at all. **Alternative rejected:** IndicWhisper (kept selectable in config for re-runs);
  a hosted API (Sarvam) is not needed since the open-source model is fast enough.
- **Observation:** both models drop the first 1–2 words on asr02–04 (e.g. "నేను బ్లడ్" missing), which inflates WER.
  Same failure in two different models points at clipped recording starts, not the models. CER (14.8%) is the
  fairer number for agglutinative Telugu. Re-run on the #11 corpus (`python eval/compare_asr.py`) once recorded.
- **Decision:** pilot references live in `data/audio/pilot_transcripts.json`, separate from the #11 corpus
  file `transcripts.json`, so the two don't overwrite each other.
- **Decision:** non-WAV input (mp3/m4a/ogg/webm) goes through ffmpeg to 16 kHz mono; WAV/FLAC read with soundfile
  and resampled with librosa if needed. ffmpeg must be on PATH.

## 2026-10-14 — Issue #5

- **Decision:** Embedding model `sentence-transformers/LaBSE` (checked on its Hugging Face model card:
  768-dim, normalised output, 0.5B params, ~1.8 GB). Each entry's `question_te` and `question_en` is one
  vector (38 vectors for 19 entries) in a FAISS `IndexFlatIP`, so scores are cosine similarity.
  **Reason:** LaBSE is trained to put sentences with the same meaning close together across languages
  (it scored "test" vs "పరీక్ష" at 0.97). **Alternative rejected:** MuRIL. It is a plain encoder, not
  trained for sentence similarity, so it would need extra pooling and fine-tuning.
- **Decision:** Embed questions only, not answers. **Reason:** adding `answer_te`/`answer_en` vectors left
  hit@1 at 76.9% and moved hit@3 only from 84.6% to 88.5%. **Alternative rejected:** question + answer
  vectors (twice the index for no hit@1 gain).
- **First result, questions only (26 in-scope questions):** hit@1 76.9%, hit@3 84.6%, MRR 0.801; rephrasings
  were weakest (hit@1 50%). Misses at rank 1 (expected → retrieved): q01 sched-01 → gen-03, q10 elig-02 →
  elig-03, q11 elig-03 → req-01, q16 req-02 → elig-01, q17 req-03 → sched-04, q20 hplc-02 → hplc-01.
- **Decision:** Add `kb/question_variants.json`: 3–4 extra phrasings per entry (Telugu script and romanised
  code-mix), each embedded as one more vector for its entry (102 vectors). Kept in its own file so
  `kb/entries.json` keeps exactly the fields issue #2 specifies. **Reason:** the misses were phrasings the
  single stored question didn't cover. **Alternative rejected:** fine-tuning the embedding model (needs
  far more data than a 19-entry KB).
- **Held-out check:** the variants were written after seeing the misses, so the original 26 questions now
  overstate accuracy. 12 new questions (q36–q47, `"set": "holdout"`) were written before re-running.
  **Result now (`results/retrieval.json`):** all 36 in-scope hit@1 88.9%, hit@3 94.4%, MRR 0.912;
  original set hit@1 92.3% (optimistic); **held-out hit@1 80.0%, hit@3 80.0% (n=10)**, which is the
  number to quote. Remaining misses: q05 sched-03 → elig-04, q11 elig-03 → elig-01, q39 elig-03 → req-01,
  q43 hplc-03 → elig-02. Caveat: Claude wrote the KB, the variants and both question sets; a teammate
  should add their own questions before these numbers go into the design doc.
- **Decision:** Medicine/dose words added to `data/safety_terms.json` ("dose", "medicine", "tablet",
  "injection", "mandu", "మందు", "డోస్", "మాత్రలు", "టాబ్లెట్", "ఇంజెక్షన్"). **Reason:** the dose question
  q35 got past the safety gate and scored 0.622–0.64, above any usable threshold; dosing is medical advice.
  Look-alikes are guarded in `tests/test_safety.py` ("mundu" = before, "మాత్రమే" = only, so bare
  "మాత్ర" was not added). All 4 medical test questions are now caught; no KB or in-scope question is.
- **Decision:** `ANSWER_THRESHOLD = 0.66` (first tried 0.63 before the variants; was the 0.5 placeholder).
  **Reason:** in-scope and out-of-scope scores overlap (correct in-scope top scores 0.515–0.97;
  out-of-scope items that pass the safety gate up to 0.655, q46 "Blood bank timings enti?"). 0.66 is the
  lowest value that keeps all of them out of the answer path, and still answers 30/36 in-scope questions
  correctly with 1 wrong top match reaching the LLM (which must then say NO_ANSWER). The margin over q46
  is only 0.005, so #14 should re-tune on more questions. `CLARIFY_THRESHOLD` (0.35) is unused until #14.
- **Decision:** On macOS, `retrieval/index.py` sets `KMP_DUPLICATE_LIB_OK=TRUE` and imports torch before
  faiss. **Reason:** faiss-cpu, torch and scikit-learn each bundle libomp. Without it the process
  segfaults (faiss imported first) or aborts with "OMP: Error #15" (faiss search before any torch work).
  OpenMP calls the flag unsafe, so `tests/test_retrieval.py::test_faiss_scores_match_numpy_cosine`
  checks faiss's scores against numpy. **Alternative rejected:** relying on import order alone (still
  aborted in the unit tests).
- **Decision:** `retrieve()` adds `question_te`, `answer_en` and `source` to each hit beyond the agreed
  `{id, score, passage}`. **Reason:** #14's clarify prompt needs the top entry's `question_te`, the API's
  English caption uses the cited entry's `answer_en`, and the UI (#8) shows the source.
- **Fixes in `api/main.py` found by running `/ask` end to end:** (1) a fallback from `generate_answer`
  was always reported as `not_covered`; it now passes through its `reason` (e.g. `llm_error`).
  (2) `answer_en` was always empty, because `generate_answer` returns Telugu only; it now uses the cited
  entry's English answer. (3) fallback responses now include the retrieval `score` (the log already had
  it). Tests added in `tests/test_api.py`.
- **Decision:** The API loads LaBSE and the index at startup (FastAPI lifespan in `api/main.py`).
  **Reason:** loading takes longer than `RETRIEVE_TIMEOUT_S` (5 s), so the first `/ask` would
  otherwise time out into a fallback.
- **Environment:** Python 3.12 (Homebrew). `requirements.txt` pins `numpy<2.0`, which has no build for
  Python 3.14. Verified with numpy 1.26.4, faiss-cpu 1.15.1, sentence-transformers 2.7.0, torch 2.14.1.

## 2026-10-14 — Issue #14 (confidence + clarify)
- **Decision:** keep `ANSWER_THRESHOLD = 0.73`; add `CLARIFY_THRESHOLD = 0.55` (was an unused 0.35).
  **Reason:** the sweep over the 71 questions in `eval/questions.json` (`results/threshold_sweep.csv`,
  from the top scores in `results/retrieval.json`) shows 0.73 is the lowest value with no unrelated
  out-of-scope question in the answer band; 50/58 in-scope questions are answered and the other 8 are
  clarified. All 4 medical items are stopped by the safety gate before retrieval. The lowest in-scope top
  score is 0.584, so 0.55 gives every in-scope question at least a clarify; q28 (0.451) goes straight to
  the coordinator. **Alternative rejected:** `ANSWER_THRESHOLD = 0.81`, which removes q71 from the answer
  band but moves 13 more in-scope questions from answer to clarify.
- **Known limit:** q70 "Donation tarvata emi tinali?" (0.999, a one-word change from a req-03 variant) and
  q71 "certificate istara?" (0.809) score above any usable threshold. The score cannot stop them; the
  LLM's `NO_ANSWER` guard (#6) must. `tests/test_confidence.py -m live` checks this on the real pipeline.
- **Decision:** clarify state is an in-memory dict keyed by the `session_id` form field of `/ask`.
  **Reason:** demo only, no accounts (scope rule). Without a `session_id` every mid-score question gets
  a clarify. **Alternative rejected:** storing sessions on disk (more than the issue needs).
- **Decision:** `/ask` returns `clarify: true` with the question in `answer_te`/`answer_en`, and logs it
  as `outcome: "clarify"`; escalations stay `outcome: "escalated"` with their `fallback_reason`.
  `retrieve()` hits now also carry `question_en` for the English caption.
## 2026-10-14 — Issue #15 (interim, public sources)

- **Decision:** No Blood Warriors material exists yet, so the team chose (Saanvi, 2026-10-14) to grow the KB
  to 41 entries from public sources now and swap in Blood Warriors' material when it arrives. All new
  entries are `authoritative: false`. **Reason:** the issue's "Done when" needs 40+ entries, and the
  assistant can answer many more donor questions. **Alternative rejected:** waiting with the KB at 19
  entries (the CLAUDE.md default when material is late). #15 stays open: the issue asks for Blood
  Warriors' real FAQs and a coordinator review, and neither has happened. Request drafted in
  `docs/bw_request.md`; review sheet extended in `docs/kb_review.md`.
- **Entries added (22):** `elig-05`–`elig-22` (tattoo/piercing, delivery and breastfeeding, periods, cold and
  cough, tooth extraction, surgery, received transfusion, malaria, typhoid, dengue, vaccines, night shift and
  drivers, diabetes, blood pressure, hepatitis, antibiotics, platelet donation, chickenpox), each citing its
  item in G.S.R. 166(E) "H. Criteria for Blood Donation"; `gen-06` chelation, `gen-07` types,
  `gen-08` cure (NHS "Thalassaemia" and "Thalassaemia – Treatment"); `hplc-04` "what does my report mean"
  (refers to doctor/coordinator, no source). Categories: donor_eligibility 22, general 8,
  transfusion_schedule 4, hplc_testing 4, donation_request 3.
- **Left out:** asthma (the gazette row "Asthmatic attack – Permanently defer" can be read two ways);
  "thalassemia minor means trait" (terminology not in the NHS pages read); questions whose natural wording
  hits a safety term (jaundice, medicines), since the safety gate would send them to the coordinator anyway.
- **Known trade-off:** the #5 safety words "medicine"/"మందు" also catch harmless donor questions such as
  "BP ki medicines vadutunte blood donate cheyocha?", which go to the coordinator instead of `elig-18`.
  Kept, because it errs towards the coordinator.
- **Test questions:** 22 new in-scope questions (one per new entry) and 2 near-miss out-of-scope ones
  (q48–q71, `"set": "kb15"`), written after the entries and their phrasings and before any evaluation.
- **Finding:** with 41 entries, LaBSE alone dropped to hit@1 63.8% overall and 40.9% on the new-entry set.
  Most eligibility questions share "… can I donate blood?" and LaBSE matched on that, not on the topic word.
- **Decision:** Hybrid ranking: score = LaBSE cosine + `LEXICAL_WEIGHT` × TF-IDF similarity (scikit-learn,
  character 3–5-grams over the same phrasings), `LEXICAL_WEIGHT = 0.2`. The weight was chosen on the original
  26 questions only (0.2–0.7 all gave 92.3% there; 0.2 is the smallest), so the other 32 in-scope questions
  stay an unbiased check. **Alternative rejected:** hand-written keyword lists per entry (hard to keep up, and
  they would be tuned on the same test questions). `scikit-learn` added to `requirements.txt` (it was already
  installed as a sentence-transformers dependency).
- **Result (`results/retrieval.json`, 41 entries, 58 in-scope questions):** hit@1 79.3%, hit@3 87.9%,
  MRR 0.836. By set: original 26 hit@1 92.3% (tuning set), held-out 10 70.0%, new-entry 22 68.2%.
  This is below the 80% hit@1 target on unseen questions. Remaining confusions are mostly between eligibility
  entries (cold → received transfusion, tooth extraction → tattoo, dengue → donation gap). Demo questions
  still rank first and clear the threshold ("Next transfusion eppudu?" 0.907, the July donor question 0.824,
  "HPLC test ante enti?" 0.968).
- **Decision:** `ANSWER_THRESHOLD = 0.73` on the hybrid score (replaces #5's 0.66 on plain cosine). It is the
  lowest value that keeps every unrelated out-of-scope question out (highest q46 "Blood bank timings enti?"
  0.723). Two near-miss questions cannot be separated by any threshold: q70 "Donation tarvata emi tinali?"
  (what to eat *after* donating) scores 0.999 against req-03's phrasing "Donation mundu emi tinali?"
  (*before*), and q71 "certificate" scores 0.809. They rely on the LLM answering `NO_ANSWER`, which has
  not been checked because no `GROQ_API_KEY` was set; run `eval/run_generation.py` with a key.
  At 0.73, 41/58 in-scope questions are answered with the right entry first.

## 2026-10-14 — Issue #11

- **Decision:** accept clips of 2–15 s instead of the issue's 5–15 s. **Reason:** the questions are short;
  15 of 20 real recordings are 2.2–6.5 s, and padding them would make them unnatural. The ASR models
  have no 5 s minimum. **Alternative rejected:** re-recording with padding.

- **Decision:** New `eval/run_asr.py` (WER/CER on the 20 #11 clips, plus retrieval on reference text vs ASR
  transcript), `eval/run_latency.py` (every clip through `POST /ask`, 2 rounds, per-stage p50/p95),
  `eval/make_grading.py` (pre-fills `eval/grading.csv`) and `eval/make_metrics.py` (`results/metrics.csv` and
  `results/metrics.md`). Latency is measured here because #9's `run_e2e.py` did not exist yet.
- **Decision:** `eval/run_generation.py` retries a question after `llm_error` (default 6 retries, 20 s apart).
  **Reason:** Groq's free tier allows 8,000 tokens/minute for `openai/gpt-oss-120b`; the first run lost 50 of
  71 questions to rate limiting. Eval only; the API still never retries. `run_latency.py` waits 8 s between
  requests for the same reason.
- **Decision:** no torchaudio. IndicConformer's remote code (`model_onnx.py`) imports only torch, onnxruntime,
  transformers and numpy, and no torchaudio build exists for torch 2.14.1.
- **Results:** WER 30.6% (Telugu 24.4%, code-mixed 48.3%), CER 13.5%, 0.27 s/clip. Much of the WER is
  spelling/spacing variants (కోఆర్డినేటర్ని vs కోఆర్డినేటర్ ని: WER 50%, CER 3%); left as measured, #13's
  normaliser is the place to fix them. Generation: 100% of 50 answers cite a retrieved entry; 13/13
  out-of-scope and medical questions handed off, including the two near-misses no threshold could stop.
  Latency p50 1.6 s, p95 3.1 s. Details in `results/metrics.md`.
- **Demo risk:** demo journey 1 fails on its recorded clip: c01 "నెక్స్ట్ ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడు" is heard as
  "కన్ఫ్యూజన్ ఎప్పుడు" and falls back (low_confidence). Clip t01 ("when do I get blood again") is answered
  from elig-01 instead of sched-01 (the LLM picked the wrong passage of the three). Both need a fix or a
  backup plan (#12) before the demo.
## 2026-10-14 — Issue #15 (interim, public sources)

- **Decision:** No Blood Warriors material exists yet, so the team chose (Saanvi, 2026-10-14) to grow the KB
  to 41 entries from public sources now and swap in Blood Warriors' material when it arrives. All new
  entries are `authoritative: false`. **Reason:** the issue's "Done when" needs 40+ entries, and the
  assistant can answer many more donor questions. **Alternative rejected:** waiting with the KB at 19
  entries (the CLAUDE.md default when material is late). #15 stays open: the issue asks for Blood
  Warriors' real FAQs and a coordinator review, and neither has happened. Request drafted in
  `docs/bw_request.md`; review sheet extended in `docs/kb_review.md`.
- **Entries added (22):** `elig-05`–`elig-22` (tattoo/piercing, delivery and breastfeeding, periods, cold and
  cough, tooth extraction, surgery, received transfusion, malaria, typhoid, dengue, vaccines, night shift and
  drivers, diabetes, blood pressure, hepatitis, antibiotics, platelet donation, chickenpox), each citing its
  item in G.S.R. 166(E) "H. Criteria for Blood Donation"; `gen-06` chelation, `gen-07` types,
  `gen-08` cure (NHS "Thalassaemia" and "Thalassaemia – Treatment"); `hplc-04` "what does my report mean"
  (refers to doctor/coordinator, no source). Categories: donor_eligibility 22, general 8,
  transfusion_schedule 4, hplc_testing 4, donation_request 3.
- **Left out:** asthma (the gazette row "Asthmatic attack – Permanently defer" can be read two ways);
  "thalassemia minor means trait" (terminology not in the NHS pages read); questions whose natural wording
  hits a safety term (jaundice, medicines), since the safety gate would send them to the coordinator anyway.
- **Known trade-off:** the #5 safety words "medicine"/"మందు" also catch harmless donor questions such as
  "BP ki medicines vadutunte blood donate cheyocha?", which go to the coordinator instead of `elig-18`.
  Kept, because it errs towards the coordinator.
- **Test questions:** 22 new in-scope questions (one per new entry) and 2 near-miss out-of-scope ones
  (q48–q71, `"set": "kb15"`), written after the entries and their phrasings and before any evaluation.
- **Finding:** with 41 entries, LaBSE alone dropped to hit@1 63.8% overall and 40.9% on the new-entry set.
  Most eligibility questions share "… can I donate blood?" and LaBSE matched on that, not on the topic word.
- **Decision:** Hybrid ranking: score = LaBSE cosine + `LEXICAL_WEIGHT` × TF-IDF similarity (scikit-learn,
  character 3–5-grams over the same phrasings), `LEXICAL_WEIGHT = 0.2`. The weight was chosen on the original
  26 questions only (0.2–0.7 all gave 92.3% there; 0.2 is the smallest), so the other 32 in-scope questions
  stay an unbiased check. **Alternative rejected:** hand-written keyword lists per entry (hard to keep up, and
  they would be tuned on the same test questions). `scikit-learn` added to `requirements.txt` (it was already
  installed as a sentence-transformers dependency).
- **Result (`results/retrieval.json`, 41 entries, 58 in-scope questions):** hit@1 79.3%, hit@3 87.9%,
  MRR 0.836. By set: original 26 hit@1 92.3% (tuning set), held-out 10 70.0%, new-entry 22 68.2%.
  This is below the 80% hit@1 target on unseen questions. Remaining confusions are mostly between eligibility
  entries (cold → received transfusion, tooth extraction → tattoo, dengue → donation gap). Demo questions
  still rank first and clear the threshold ("Next transfusion eppudu?" 0.907, the July donor question 0.824,
  "HPLC test ante enti?" 0.968).
- **Decision:** `ANSWER_THRESHOLD = 0.73` on the hybrid score (replaces #5's 0.66 on plain cosine). It is the
  lowest value that keeps every unrelated out-of-scope question out (highest q46 "Blood bank timings enti?"
  0.723). Two near-miss questions cannot be separated by any threshold: q70 "Donation tarvata emi tinali?"
  (what to eat *after* donating) scores 0.999 against req-03's phrasing "Donation mundu emi tinali?"
  (*before*), and q71 "certificate" scores 0.809. They rely on the LLM answering `NO_ANSWER`, which has
  not been checked because no `GROQ_API_KEY` was set; run `eval/run_generation.py` with a key.
  At 0.73, 41/58 in-scope questions are answered with the right entry first.

## 2026-10-14 — Issue #4 (Telugu TTS)

- **Decision (provisional):** gTTS (`lang="te"`) is the TTS provider (`config.TTS_PROVIDER`), cached by sha256 of provider+text in `tts/cache/`. **Reason:** pure pip install, no model download, works on CPU laptops. **Not yet done:** AI4Bharat Indic-TTS comparison (see progress.md, awaiting decision).
- **gTTS timings** (5 KB answers, `results/tts_compare.json`): 2.0 s, 2.5 s, then 20.9 s, 26.2 s, 31.9 s on three others — network-dependent and far over the 10 s budget when it stalls. Cache makes repeats instant; the demo answers should be pre-warmed.

- **Decision:** AI4Bharat Indic-TTS was not tried; gTTS is the only provider, so there is no second provider to fall back to.
  **Reason:** team chose to ship gTTS for the POC (needs no model download). **Consequence:** the issue's "try both, pick one,
  keep gTTS as fallback" is only partly met; the comparison box stays unticked and the issue gets a comment saying so.
  **Alternative rejected:** installing Indic-TTS (Coqui-based, heavy CPU dependencies) for a comparison.

## 2026-10-14 — Issue #13 (code-mixing)

- **Decision:** `data/glossary.json` (20 Telugu-script/misspelt forms → canonical English term) applied by
  `asr/normalise.py` as ZWNJ-stripping plus longest-first substring replace; already wired after `transcribe` in `/ask`.
  Entries come from real ASR output on the 5 code-mixed clips (e.g. ట్రాన్స్ఫ్యూజన్, టైం, హెచ్పి సిఎల్, రిక్వెస్ట్కి).
  **Alternative rejected:** a fuzzy/embedding-based matcher (overkill for 20 terms). Short keys like "ఎస్" (yes)
  left out: substring matching would corrupt ordinary Telugu words.
- **Result (`results/codemix.json`, 5 clips):** WER 48.3% → 37.9% (reference normalised the same way, so this
  measures spelling variants only). Retrieval hit@1 unchanged: 4/4 in-scope clips right before and after
  (c03 is the fallback clip, so the 80% in the file counts it as a miss). Top scores were mixed: c04 up, c03 up, but c02 0.847→0.742 and c05 0.801→0.751 **down**.
  So normalisation helps the transcript, not the retrieval score; it does not hurt the answer decision.
  c02 still clears `ANSWER_THRESHOLD` (0.73), narrowly.
- **Noticed, not an #13 problem:** c01 "Next transfusion eppudu?" is heard as "కన్ఫ్యూజన్ ఎప్పుడు" (score 0.644 < 0.73),
  so demo journey 1 falls back by voice. Needs a better ASR or a glossary pair for "కన్ఫ్యూజన్" (risky: a real word); user decision.
