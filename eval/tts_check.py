"""Synthesize 5 KB answers with gTTS; save audio, time/size to results/tts_compare.json, and write results/tts_check.md
for a Telugu speaker to fill in."""

import json
import shutil
import time
from pathlib import Path

import config
from tts import synthesize as tts

IDS_PER_CATEGORY = 1  # one answer per category -> 5 sentences
OUT = config.ROOT / "results" / "tts_audio"


def main() -> None:
    kb = json.loads(config.KB_PATH.read_text(encoding="utf-8"))
    picked, seen = [], set()
    for e in kb:
        if e["category"] not in seen:
            seen.add(e["category"])
            picked.append(e)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for e in picked[:5]:
        start = time.perf_counter()
        src = Path(tts.synthesize(e["answer_te"]))
        secs = time.perf_counter() - start
        dst = OUT / f"{e['id']}.mp3"
        shutil.copy(src, dst)
        rows.append({"id": e["id"], "text": e["answer_te"], "file": f"tts_audio/{dst.name}",
                     "seconds": round(secs, 2), "bytes": dst.stat().st_size, "provider": "gtts"})
    (config.ROOT / "results").mkdir(exist_ok=True)
    (config.ROOT / "results" / "tts_compare.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# TTS listening check (#4)", "",
             "A Telugu speaker plays each file and fills the last two columns.", "",
             "| id | sentence | audio | gen time (s) | size (KB) | understandable? (Y/N) | notes |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['text']} | [{Path(r['file']).name}]({r['file']}) | "
                     f"{r['seconds']} | {r['bytes'] // 1024} | | |")
    (config.ROOT / "results" / "tts_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for r in rows:
        print(r["id"], r["seconds"], "s", r["bytes"], "bytes")


if __name__ == "__main__":
    main()
