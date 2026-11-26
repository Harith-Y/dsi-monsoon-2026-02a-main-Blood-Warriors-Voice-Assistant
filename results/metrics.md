# Metrics sheet: Blood Warriors voice assistant

Generated 2026-10-14 by `python eval/make_metrics.py` from the files in the Source column.
KB: 41 entries. Answer threshold 0.73.

| Metric | Value | Target | Met? | Source |
|---|---|---|---|---|
| ASR WER (20 recorded clips, indicconformer) | 30.6% | < 30% | no | `results/asr.json` |
| ASR CER (same clips) | 13.5% | report |  | `results/asr.json` |
| ASR WER, code_mixed (5 clips) | 48.3% | report |  | `results/asr.json` |
| ASR WER, telugu (15 clips) | 24.4% | report |  | `results/asr.json` |
| ASR seconds per clip (mean) | 0.27 s | report |  | `results/asr.json` |
| Retrieval hit@1 on clip reference text (18 clips) | 94.4% | report |  | `results/asr.json` |
| Retrieval hit@1 on ASR transcripts (18 clips) | 94.4% | report the drop |  | `results/asr.json` |
| Retrieval hit@1 (58 typed in-scope questions) | 79.3% | ≥ 80% | no | `results/retrieval.json` |
| Retrieval hit@3 (same) | 87.9% | report |  | `results/retrieval.json` |
| Retrieval hit@1, questions not used for tuning (32) | 68.8% | ≥ 80% | no | `results/retrieval.json` |
| Answers traceable to a retrieved KB entry (50 answers) | 100.0% | 100% | yes | `results/generation.json` |
| Out-of-scope + medical questions sent to coordinator (13) | 100.0% | 100% | yes | `results/generation.json` |
| In-scope questions answered (58) | 86.2% | report |  | `results/generation.json` |
| In-scope answers citing the expected entry | 98.0% | report |  | `results/generation.json` |
| Hand grading, grader 1 | pending (0/50 graded) | 100% grounded |  | `eval/grading.csv` |
| Hand grading, grader 2 | pending (0/50 graded) | 100% grounded |  | `eval/grading.csv` |
| End-to-end latency p50 (40 requests) | 1.6 s | < 10 s | yes | `results/latency.json` |
| End-to-end latency p95 | 3.1 s | < 10 s | yes | `results/latency.json` |
|   asr p50 / p95 | 272 / 349 ms | report |  | `results/latency.json` |
|   retrieve p50 / p95 | 33 / 36 ms | report |  | `results/latency.json` |
|   generate p50 / p95 | 948 / 1826 ms | report |  | `results/latency.json` |
|   tts p50 / p95 | 385 / 1442 ms | report |  | `results/latency.json` |
| Answered, first time spoken (TTS not cached): total p50 / p95 | 2.4 / 3.1 s | report |  | `results/latency.json` |
| Demo journeys passing (clips c01, c02, c03) | 2/3 | 3/3 | no | `results/latency.json` |
| Clips with the expected outcome, end to end | 31/40 | report |  | `results/latency.json` |

## Failing examples

- **ASR, c01** (WER 67%): said “నెక్స్ట్ ట్రాన్స్ఫ్యూజన్ ఎప్పుడు” → heard “కన్ఫ్యూజన్ ఎప్పుడు”
- **ASR, t08** (WER 60%): said “నాకు ఏదైనా రక్తదాన అభ్యర్థన వచ్చిందా” → heard “నాకు ఎవరైనా రక్తదాన్ అభివృద్ధి వచ్చిందా”
- **ASR, c02** (WER 56%): said “నేను బ్లడ్ డొనేట్ చేయొచ్చా లాస్ట్ టైమ్ జూలై లో ఇచ్చాను” → heard “డొనేట్ చేయొచ్చా లాస్ట్ టైం జూలైలో ఇచ్చాను”
- **Retrieval, q11**: “నాకు 17 ఏళ్ళు, నేను రక్తదానం చేయొచ్చా?” → `elig-19` instead of `elig-03`
- **Retrieval, q22**: “Thalassemia ante enti?” → `gen-07` instead of `gen-01`
- **Retrieval, q37**: “ట్రాన్స్‌ఫ్యూజన్ ఎంత తరచుగా అవసరం?” → `sched-01` instead of `sched-03`
- **Generation, q11**: “నాకు 17 ఏళ్ళు, నేను రక్తదానం చేయొచ్చా?” went to the coordinator but the KB covers it
- **Generation, q25**: “Coordinator number enti?” went to the coordinator but the KB covers it

## What these numbers do not show

- **Real users.** The clips are team members reading prepared questions in normal rooms, not caregivers or
  donors asking in their own words, under stress, with children or traffic in the background.
- **Real dialects.** A few team voices do not cover rural Telangana and Andhra speech or older speakers.
- **Phone audio.** Clips are 16 kHz recordings; a feature phone or IVR call is 8 kHz and noisier.
- **Independent test questions.** The KB, its phrasings and the typed test questions were written by the
  same people (and Claude), so retrieval numbers are likely optimistic.
- **Medical correctness.** Grounding is checked against the KB; the KB itself comes from public sources and
  has not yet been reviewed by Blood Warriors or a doctor.
- **Trust and usefulness.** Whether people would rely on a machine voice for this is untested.
