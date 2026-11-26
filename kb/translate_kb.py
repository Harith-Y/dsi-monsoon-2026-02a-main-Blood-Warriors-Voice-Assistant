"""Fill missing language fields (question_<lang>, answer_<lang>) in kb/entries.json with the LLM translator.

    python -m kb.translate_kb            # every supported language, only fields that are missing
    python -m kb.translate_kb --dry-run  # show what would be translated

Translations are machine-made from the reviewed English text and need a native speaker's review
(docs/kb_review.md). Existing fields are never overwritten.
"""

import argparse
import json
import time

import config
from generation.translate import translate

FIELD_ORDER = ("id", "category", "question_te", "question_en", "question_hi",
               "answer_te", "answer_en", "answer_hi", "source", "authoritative")
BATCH = 6  # entries per LLM call: small enough for the free-tier token limit, big enough to be quick


def ordered(entry: dict) -> dict:
    """Same keys, in a stable reading order (unknown keys keep their place at the end)."""
    out = {k: entry[k] for k in FIELD_ORDER if k in entry}
    out.update({k: v for k, v in entry.items() if k not in out})
    return out


def missing(entry: dict, lang: str) -> dict[str, str]:
    """{field: English source text} for this entry's empty fields in lang."""
    return {f"{part}_{lang}": entry[f"{part}_en"] for part in ("question", "answer")
            if not (entry.get(f"{part}_{lang}") or "").strip()}


def fill_entry(entry: dict, langs=config.LANGUAGES) -> dict:
    """Return entry with every missing language field translated (one LLM call per language)."""
    entry = dict(entry)
    for lang in langs:
        todo = missing(entry, lang)
        if todo:
            entry.update(translate(todo, lang, source_lang="en"))
    return ordered(entry)


def save(entries: list[dict]) -> None:
    config.KB_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    entries = json.loads(config.KB_PATH.read_text(encoding="utf-8"))
    for lang in config.LANGUAGES:
        todo_idx = [i for i, e in enumerate(entries) if missing(e, lang)]
        print(f"{lang}: {len(todo_idx)} entries need translation")
        if args.dry_run:
            continue
        for start in range(0, len(todo_idx), BATCH):
            batch = todo_idx[start:start + BATCH]
            texts = {f"{entries[i]['id']}|{field}": src for i in batch for field, src in missing(entries[i], lang).items()}
            for attempt in range(4):  # Groq free tier: tokens-per-minute limit, so wait and retry
                try:
                    done = translate(texts, lang, source_lang="en")
                    break
                except Exception as e:
                    if attempt == 3:
                        raise
                    print(f"  retrying in 20 s ({type(e).__name__})")
                    time.sleep(20)
            for key, value in done.items():
                entry_id, field = key.split("|")
                i = next(i for i in batch if entries[i]["id"] == entry_id)
                entries[i][field] = value
            entries = [ordered(e) for e in entries]
            save(entries)  # after every batch, so a rate-limit stop loses nothing
            print(f"  {lang}: {min(start + BATCH, len(todo_idx))}/{len(todo_idx)}")
            time.sleep(2)


if __name__ == "__main__":
    main()
