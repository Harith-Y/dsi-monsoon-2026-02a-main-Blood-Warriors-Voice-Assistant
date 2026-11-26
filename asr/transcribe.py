"""Speech-to-text: transcribe(audio_path, lang="te") -> str.

Telugu and Hindi: two local CPU backends (AI4Bharat IndicConformer, IndicWhisper for Telugu only);
config.ASR_MODEL picks the one the pipeline uses. Each model is loaded once per process.
English: IndicConformer has no English, so it goes to Whisper on Groq (config.ASR_GROQ_MODEL).
"""

import os
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
import soundfile as sf
from dotenv import load_dotenv

import config

SAMPLE_RATE = 16000
_models: dict = {}
_load_lock = threading.Lock()


def load_audio(audio_path: str | Path) -> np.ndarray:
    """Return 16 kHz mono float32 audio. Formats soundfile can't read (m4a, webm, mp3...) go through ffmpeg."""
    try:
        audio, sr = sf.read(str(audio_path), dtype="float32", always_2d=True)
    except Exception:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "audio.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio_path),
                 "-ac", "1", "-ar", str(SAMPLE_RATE), str(wav)],
                check=True, timeout=30,
            )
            audio, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if sr != SAMPLE_RATE:
        import librosa
        audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)
    return audio


def _load(model_name: str):
    if model_name in _models:
        return _models[model_name]
    # One load at a time: questions that arrive while the model is still loading (or, on a first start,
    # downloading) wait for that load instead of each loading their own 600M-parameter copy.
    with _load_lock:
        if model_name not in _models:
            _models[model_name] = _load_model(model_name)
    return _models[model_name]


def _load_model(model_name: str):
    if model_name == "indicconformer":
        from transformers import AutoModel
        load_dotenv(config.ROOT / ".env")
        model = AutoModel.from_pretrained(
            config.ASR_CONFORMER_ID, trust_remote_code=True, token=os.getenv("HF_TOKEN") or None
        )
    elif model_name == "indicwhisper":
        from transformers import pipeline
        model = pipeline("automatic-speech-recognition", model=str(config.ASR_WHISPER_PATH), device="cpu")
    else:
        raise ValueError(f"unknown ASR model: {model_name}")
    return model


def _groq_whisper(audio_path: str | Path, lang: str) -> str:
    from groq import Groq  # lazy: unit tests mock this function and need no key

    load_dotenv(config.ROOT / ".env")
    client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=config.ASR_TIMEOUT_S, max_retries=0)
    path = Path(audio_path)
    resp = client.audio.transcriptions.create(
        file=(path.name, path.read_bytes()), model=config.ASR_GROQ_MODEL, language=lang, temperature=0,
    )
    return str(resp.text).strip()


def transcribe(audio_path: str | Path, model_name: str | None = None, lang: str = "te") -> str:
    """Transcribe a clip to text in lang's script. Code-mixed speech (Telugu-English, Hindi-English) comes
    back in the Telugu or Devanagari script."""
    if lang == "en":
        return _groq_whisper(audio_path, "en")
    model_name = model_name or config.ASR_MODEL
    if lang != "te":
        model_name = "indicconformer"  # the IndicWhisper checkpoint is Telugu-only
    audio = load_audio(audio_path)
    model = _load(model_name)
    if model_name == "indicconformer":
        import torch
        text = model(torch.from_numpy(audio).unsqueeze(0), lang, config.ASR_CONFORMER_DECODING)
    else:
        result = model(
            {"raw": audio, "sampling_rate": SAMPLE_RATE},
            generate_kwargs={"language": "te", "task": "transcribe"},
        )
        text = result["text"]
    return str(text).strip()
