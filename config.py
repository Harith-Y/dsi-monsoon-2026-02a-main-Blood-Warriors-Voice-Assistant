"""Single place for every tunable: model ids, retrieval K, thresholds, timeouts, paths."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")  # secrets and per-deployment values; never committed

# Languages the whole pipeline supports (speech in, answer, speech out). Order = the UI picker order.
LANGUAGES = ("te", "hi", "en")
DEFAULT_LANG = "te"

# Retrieval
EMBEDDING_MODEL = "sentence-transformers/LaBSE"
RETRIEVAL_K = 3
# Hybrid ranking (#15): score = LaBSE cosine + LEXICAL_WEIGHT * TF-IDF (char n-gram) similarity, so rare
# topic words (tattoo, malaria) count more than words every question shares (blood, donate).
# Chosen on the original 26 test questions only.
LEXICAL_WEIGHT = 0.2
# Answer threshold on the hybrid score, from results/retrieval.json (#5, re-set in #15 for 41 entries): the
# lowest value that keeps every unrelated out-of-scope test question out of the answer path (up to 0.723).
# Near-paraphrases of an entry (q70 0.999, q71 0.809) still pass; the LLM's NO_ANSWER guard stops those.
ANSWER_THRESHOLD = 0.73  # kept by the threshold sweep (results/threshold_sweep.csv)
# Between CLARIFY and ANSWER: ask once "did you mean ...?" (#14). Just below the lowest in-scope top score
# (0.584), so every in-scope question gets at least a clarify; unrelated questions below it go straight
# to the coordinator.
CLARIFY_THRESHOLD = 0.55

# Generation
GROQ_MODEL = "openai/gpt-oss-120b"
LLM_TEMPERATURE = 0
LLM_TIMEOUT_S = 10

# ASR / TTS
ASR_MODEL = "indicconformer"  # "indicconformer" | "indicwhisper"; compared in results/asr_compare.json
ASR_CONFORMER_ID = "ai4bharat/indic-conformer-600m-multilingual"  # gated: needs HF_TOKEN in .env
ASR_CONFORMER_DECODING = "ctc"  # "ctc" | "rnnt"
ASR_WHISPER_PATH = ROOT / "models" / "telugu_models" / "whisper-medium-te_alldata_multigpu"
# IndicConformer has no English, so English speech goes to Whisper on Groq (same GROQ_API_KEY as the LLM).
ASR_GROQ_MODEL = "whisper-large-v3"
# Load the local ASR model at server start so the first caregiver does not wait for it (BW_ASR_WARMUP=0 skips).
ASR_WARMUP = os.getenv("BW_ASR_WARMUP", "1") == "1"
TTS_PROVIDER = "gtts"
TTS_CACHE_DIR = Path(os.getenv("BW_TTS_CACHE_DIR") or ROOT / "tts" / "cache")  # spoken answers and replies
TTS_TIMEOUT_S = 10

# Per-stage timeouts for the /ask pipeline (#7)
ASR_TIMEOUT_S = 10
# A coordinator teaching the assistant speaks a question and its answer: a longer clip than a caregiver's
# question, so its transcription gets more time (the /teach page records up to 60 s).
TEACH_ASR_TIMEOUT_S = 30
# Saving a taught answer translates it into the other languages (one LLM call each).
TEACH_TRANSLATE_TIMEOUT_S = 40
RETRIEVE_TIMEOUT_S = 5
GENERATE_TIMEOUT_S = LLM_TIMEOUT_S
TTS_TIMEOUT_S = 10

# Paths. The KB files change when a coordinator teaches the assistant by voice (/teach); Docker points
# BW_KB_PATH, BW_KB_VARIANTS_PATH and BW_INDEX_DIR at its data volume so those changes survive a rebuild.
KB_PATH = Path(os.getenv("BW_KB_PATH") or ROOT / "kb" / "entries.json")
KB_VARIANTS_PATH = Path(os.getenv("BW_KB_VARIANTS_PATH") or ROOT / "kb" / "question_variants.json")  # extra phrasings (#5)
INDEX_DIR = Path(os.getenv("BW_INDEX_DIR") or ROOT / "data" / "index")
AUDIO_DIR = ROOT / "data" / "audio"
LOG_PATH = Path(os.getenv("BW_LOG_PATH") or ROOT / "logs" / "requests.jsonl")  # also feeds "This week"
# Coordinator requests, KB version history (SQLite) and the caregiver audio kept with each request.
# Both git-ignored; override with BW_DATA_DIR (Docker mounts a volume there).
DATA_DIR = Path(os.getenv("BW_DATA_DIR") or ROOT / "data" / "runtime")
DB_PATH = DATA_DIR / "bw.sqlite3"
REQUEST_AUDIO_DIR = DATA_DIR / "request_audio"

# End-to-end budget (#9)
E2E_LATENCY_BUDGET_S = 10

# Where eval/run_latency.py sends its requests by default
API_URL = "http://127.0.0.1:8000"

# Coordinator hand-off. Blood Warriors asked for no phone calls: the UI only offers a WhatsApp
# click-to-chat link (wa.me) to this number, digits with country code (e.g. 91XXXXXXXXXX), from .env.
COORDINATOR_WHATSAPP = os.getenv("COORDINATOR_WHATSAPP", "")
# Shared passcode for /dashboard and /teach (demo-level access control), from .env.
COORDINATOR_PASSCODE = os.getenv("COORDINATOR_PASSCODE", "")

# Generic coordinator hand-off message. Telugu needs a native speaker's check.
FALLBACK_TE = "ఇది నేను ఖచ్చితంగా చెప్పలేను. దయచేసి మీ కోఆర్డినేటర్‌ను సంప్రదించండి."
FALLBACK_EN = "I don't have a verified answer. Please contact your coordinator."
