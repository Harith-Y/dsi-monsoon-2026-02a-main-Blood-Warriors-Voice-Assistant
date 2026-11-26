"""Convert raw recordings to 16 kHz mono WAV and check the corpus (#11).

  python eval/prepare_audio.py          # convert data/audio/raw/* -> data/audio/<id>.wav, then check
  python eval/prepare_audio.py --check  # only check
Needs ffmpeg on PATH for m4a/ogg/mp3 (librosa falls back to it).
"""
import argparse
import json
import sys
from pathlib import Path

import librosa
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

SR = 16000
MIN_S, MAX_S = 2, 15
RAW_DIR = config.AUDIO_DIR / "raw"


def convert_all() -> None:
    for src in sorted(RAW_DIR.glob("*.*")) if RAW_DIR.exists() else []:
        y, _ = librosa.load(src, sr=SR, mono=True)
        sf.write(config.AUDIO_DIR / f"{src.name.split('.')[0]}.wav", y, SR, subtype="PCM_16")
        print(f"converted {src.name}")


def check() -> bool:
    clips = json.loads((config.AUDIO_DIR / "transcripts.json").read_text(encoding="utf-8"))
    ok, found, durs = True, 0, []
    for c in clips:
        p = config.AUDIO_DIR / c["file"]
        if not p.exists():
            print(f"MISSING  {c['clip_id']}")
            ok = False
            continue
        info = sf.info(p)
        found += 1
        durs.append(info.duration)
        bad = []
        if info.samplerate != SR or info.channels != 1:
            bad.append(f"{info.samplerate} Hz/{info.channels}ch")
        if not MIN_S <= info.duration <= MAX_S:
            bad.append("length outside 2-15 s")
        if not c["speaker"] or not c["device"]:
            bad.append("speaker/device empty")
        print(f"{'BAD ' if bad else 'ok  '} {c['clip_id']}  {info.duration:5.1f}s  {info.samplerate} Hz  {', '.join(bad)}")
        ok &= not bad
    by = lambda k: sum(1 for c in clips if c["variant"] == k)
    print(f"\nclips listed {len(clips)} (telugu {by('telugu')}, code_mixed {by('code_mixed')}), "
          f"recorded {found}, backup {sum(1 for c in clips if c.get('backup'))}")
    if durs:
        print(f"duration min/mean/max {min(durs):.1f}/{sum(durs)/len(durs):.1f}/{max(durs):.1f} s")
    return ok and found >= 15 and sum(1 for c in clips if c.get("backup")) >= 5


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    if not ap.parse_args().check:
        convert_all()
    sys.exit(0 if check() else 1)
