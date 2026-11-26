"""#3: compare IndicConformer vs IndicWhisper on CPU (WER, CER, seconds per clip).

Usage: python eval/compare_asr.py [transcripts.json]  ->  results/asr_compare.json
Clips: data/audio/<clip_id>.<any ext>. References default to data/audio/transcripts.json (#11 corpus);
the #3 pilot run used data/audio/pilot_transcripts.json.
"""

import json
import sys
import time
from pathlib import Path

import jiwer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from asr.transcribe import _load, transcribe  # noqa: E402

MODELS = ["indicconformer", "indicwhisper"]
PUNCT = str.maketrans("", "", "?.,!।\u200c\u200d")  # punctuation + zero-width (non-)joiners


def clean(text: str) -> str:
    return " ".join(text.translate(PUNCT).split())


def main() -> None:
    refs_path = Path(sys.argv[1]) if len(sys.argv) > 1 else config.AUDIO_DIR / "transcripts.json"
    refs = json.loads(refs_path.read_text(encoding="utf-8"))
    clips = []
    for r in refs:
        found = sorted(config.AUDIO_DIR.glob(f"{r['clip_id']}.*"))
        if found:
            clips.append((r, found[0]))
    print(f"{len(clips)} clips found")

    out = {"references": refs_path.name, "clips": len(clips), "models": {}}
    for name in MODELS:
        t0 = time.perf_counter()
        _load(name)
        transcribe(clips[0][1], name)  # warm-up: first inference initialises the runtime
        load_s = time.perf_counter() - t0
        rows = []
        for r, path in clips:
            t0 = time.perf_counter()
            hyp = transcribe(path, name)
            secs = time.perf_counter() - t0
            ref = clean(r["reference_text"])
            rows.append({
                "clip_id": r["clip_id"], "variant": r["variant"], "seconds": round(secs, 2),
                "reference": ref, "hypothesis": hyp,
                "wer": round(jiwer.wer(ref, clean(hyp)), 3), "cer": round(jiwer.cer(ref, clean(hyp)), 3),
            })
            print(f"{name:15} {r['clip_id']} {secs:5.1f}s  {hyp}")
        all_ref = [x["reference"] for x in rows]
        all_hyp = [clean(x["hypothesis"]) for x in rows]
        out["models"][name] = {
            "load_seconds": round(load_s, 1),
            "wer": round(jiwer.wer(all_ref, all_hyp), 3),
            "cer": round(jiwer.cer(all_ref, all_hyp), 3),
            "mean_seconds_per_clip": round(sum(x["seconds"] for x in rows) / len(rows), 2),
            "per_clip": rows,
        }

    results = config.ROOT / "results"
    results.mkdir(exist_ok=True)
    (results / "asr_compare.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, m in out["models"].items():
        print(f"{name:15} WER {m['wer']:.1%}  CER {m['cer']:.1%}  {m['mean_seconds_per_clip']}s/clip  load {m['load_seconds']}s")


if __name__ == "__main__":
    main()
