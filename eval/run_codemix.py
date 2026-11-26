"""#13: compare retrieval and WER on the code-mixed clips with and without normalise().

Usage: python eval/run_codemix.py  ->  results/codemix.json
Hypotheses come from ASR on data/audio/c*.wav (the real pipeline input), references from transcripts.json.
"""
import json
import sys
from pathlib import Path

import jiwer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from asr.normalise import normalise  # noqa: E402
from asr.transcribe import transcribe  # noqa: E402
from eval.compare_asr import clean  # noqa: E402
from retrieval.index import retrieve  # noqa: E402


def main() -> None:
    refs = json.loads((config.AUDIO_DIR / "transcripts.json").read_text(encoding="utf-8"))
    rows = []
    for r in (r for r in refs if r["variant"] == "code_mixed"):
        raw = transcribe(config.AUDIO_DIR / r["file"])
        row = {"clip_id": r["clip_id"], "expected": r["expected_kb_id"], "reference": clean(r["reference_text"])}
        for label, hyp in (("raw", raw), ("normalised", normalise(raw))):
            hits = retrieve(hyp, k=1)
            row[label] = {"hypothesis": clean(hyp), "top_hit": hits[0]["id"], "score": round(hits[0]["score"], 3)}
        rows.append(row)

    out = {"clips": len(rows), "per_clip": rows}
    # WER: reference is the Telugu-script transcript, so score normalised text against normalised reference.
    for label, ref_fn in (("raw", lambda s: s), ("normalised", normalise)):
        refs_ = [clean(ref_fn(x["reference"])) for x in rows]
        hyps_ = [x[label]["hypothesis"] for x in rows]
        out[label] = {
            "wer": round(jiwer.wer(refs_, hyps_), 3),
            "hit@1": round(sum(x[label]["top_hit"] == x["expected"] for x in rows) / len(rows), 3),
        }
    (config.ROOT / "results" / "codemix.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for x in rows:
        print(x["clip_id"], x["expected"], "raw:", x["raw"]["top_hit"], x["raw"]["score"],
              "norm:", x["normalised"]["top_hit"], x["normalised"]["score"])
    print({k: out[k] for k in ("raw", "normalised")})


if __name__ == "__main__":
    main()
