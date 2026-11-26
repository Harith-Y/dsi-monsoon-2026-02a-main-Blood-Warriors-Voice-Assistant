"""Fill the TTS cache with every KB answer and the fallback message, so the demo never waits on gTTS."""

import json
import time

import config
from tts.synthesize import synthesize


def main() -> None:
    kb = json.loads(config.KB_PATH.read_text(encoding="utf-8"))
    texts = [config.FALLBACK_TE] + [e["answer_te"] for e in kb]
    for i, text in enumerate(texts, 1):
        start = time.perf_counter()
        try:
            synthesize(text)
            status = "ok"
        except Exception as e:  # keep going; re-run to retry the failures
            status = f"FAILED ({e})"
        print(f"{i}/{len(texts)} {time.perf_counter() - start:.1f}s {status}")


if __name__ == "__main__":
    main()
