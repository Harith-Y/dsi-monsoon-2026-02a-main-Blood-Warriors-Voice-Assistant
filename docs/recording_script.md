# Recording script (#11)

20 questions: 15 Telugu, 5 code-mixed. Every clip has an id, the exact words to say, and the KB id
(from `kb/entries.json`) it should retrieve, or `fallback`. Clips marked **backup** are the 5 safe
clips for the live demo; c01, c02, c03 are the three demo journeys.

## How to record

- Phone or laptop mic, in a normal room. Some background noise (fan, street) is good, not a problem.
- One question per file, **2–15 s**. Leave about 1 s of silence before and after. Speak naturally.
- Any format works (m4a, ogg, mp3, wav). Name each file with the clip id: `t01.m4a`, `c02.ogg`.
- Drop the files in `data/audio/raw/`, then run `python eval/prepare_audio.py` (converts to 16 kHz mono WAV in `data/audio/`).
- Real voices only. Do **not** use TTS-generated audio; it is never the ASR test set.
- If you say it differently from the script, edit that clip's `reference_text` in `data/audio/transcripts.json`
  so it matches what you actually said (WER is computed against it).
- Fill `speaker` and `device` for each clip in `transcripts.json` (e.g. `"speaker": "S1", "device": "Pixel 7"`). Nothing else personal.
- Two speakers, 10 clips each: S1 records t01–t07 and c01–c03, S2 records t08–t15 and c04–c05. `speaker` is already set in `transcripts.json`; fill `device`.

## Consent

Each speaker initials once: I agree that my voice recordings are used for testing this project only.

| Speaker id | Initials | Date |
|---|---|---|
|  |  |  |
|  |  |  |
|  |  |  |
|  |  |  |

## Clips

For code-mixed clips, say the Latin text; the reference is the same words in Telugu script (what the ASR models output).

### Speaker S1

| id | variant | say this | reference_text | expected KB id | backup |
|---|---|---|---|---|---|
| t01 | telugu | నాకు మళ్ళీ రక్తం ఎక్కించేది ఎప్పుడు? | నాకు మళ్ళీ రక్తం ఎక్కించేది ఎప్పుడు | sched-01 | yes |
| t02 | telugu | రక్తం ఎక్కించే తేదీని మార్చుకోవచ్చా? | రక్తం ఎక్కించే తేదీని మార్చుకోవచ్చా | sched-02 |  |
| t03 | telugu | తలసేమియా ఉన్న పిల్లలకి ఎన్ని రోజులకి ఒకసారి రక్తం ఎక్కించాలి? | తలసేమియా ఉన్న పిల్లలకి ఎన్ని రోజులకి ఒకసారి రక్తం ఎక్కించాలి | sched-03 |  |
| t04 | telugu | రక్తం ఎక్కించే రోజు మేము ఏమేం తీసుకురావాలి? | రక్తం ఎక్కించే రోజు మేము ఏమేం తీసుకురావాలి | sched-04 |  |
| t05 | telugu | రెండు సార్లు రక్తదానం చేయడానికి మధ్య ఎన్ని రోజులు ఆగాలి? | రెండు సార్లు రక్తదానం చేయడానికి మధ్య ఎన్ని రోజులు ఆగాలి | elig-02 |  |
| t06 | telugu | ఎవరెవరు రక్తదానం చేయొచ్చు? వయసు, బరువు ఎంత ఉండాలి? | ఎవరెవరు రక్తదానం చేయొచ్చు వయసు బరువు ఎంత ఉండాలి | elig-03 |  |
| t07 | telugu | నాకు తలసేమియా ట్రెయిట్ ఉంది, నేను రక్తదానం చేయొచ్చా? | నాకు తలసేమియా ట్రెయిట్ ఉంది నేను రక్తదానం చేయొచ్చా | elig-04 | yes |
| c01 | code_mixed | Next transfusion eppudu? | నెక్స్ట్ ట్రాన్స్‌ఫ్యూజన్ ఎప్పుడు | sched-01 | yes |
| c02 | code_mixed | Nenu blood donate cheyacha? Last time July lo ichanu. | నేను బ్లడ్ డొనేట్ చేయొచ్చా లాస్ట్ టైమ్ జూలై లో ఇచ్చాను | elig-01 | yes |
| c03 | code_mixed | Naa child ki fever undi, transfusion cheyacha? | నా చైల్డ్ కి ఫీవర్ ఉంది ట్రాన్స్‌ఫ్యూజన్ చేయొచ్చా | fallback | yes |

### Speaker S2

| id | variant | say this | reference_text | expected KB id | backup |
|---|---|---|---|---|---|
| t08 | telugu | నాకు ఏదైనా రక్తదాన అభ్యర్థన వచ్చిందా? | నాకు ఏదైనా రక్తదాన అభ్యర్థన వచ్చిందా | req-01 |  |
| t09 | telugu | రక్తదాన అభ్యర్థనకి ఒప్పుకోవాలంటే ఏం చేయాలి? | రక్తదాన అభ్యర్థనకి ఒప్పుకోవాలంటే ఏం చేయాలి | req-02 |  |
| t10 | telugu | హెచ్‌పీఎల్‌సీ పరీక్ష అంటే ఏమిటి? | హెచ్‌పీఎల్‌సీ పరీక్ష అంటే ఏమిటి | hplc-01 |  |
| t11 | telugu | తలసేమియా క్యారియర్ టెస్ట్ ఎవరు చేయించుకోవాలి? | తలసేమియా క్యారియర్ టెస్ట్ ఎవరు చేయించుకోవాలి | hplc-02 |  |
| t12 | telugu | తలసేమియా అంటే ఏమిటి? | తలసేమియా అంటే ఏమిటి | gen-01 |  |
| t13 | telugu | మా పిల్లలకి ఎందుకు ఎప్పుడూ రక్తం ఎక్కించాలి? | మా పిల్లలకి ఎందుకు ఎప్పుడూ రక్తం ఎక్కించాలి | gen-03 |  |
| t14 | telugu | నా కోఆర్డినేటర్‌ని ఎలా సంప్రదించాలి? | నా కోఆర్డినేటర్‌ని ఎలా సంప్రదించాలి | gen-04 |  |
| t15 | telugu | ఈ మందు ఎంత మోతాదులో వేసుకోవాలి? | ఈ మందు ఎంత మోతాదులో వేసుకోవాలి | fallback |  |
| c04 | code_mixed | HPLC test ante enti? | హెచ్‌పీఎల్‌సీ టెస్ట్ అంటే ఏంటి | hplc-01 |  |
| c05 | code_mixed | Donation request ki yes ela cheppali? | డొనేషన్ రిక్వెస్ట్ కి యెస్ ఎలా చెప్పాలి | req-02 |  |
