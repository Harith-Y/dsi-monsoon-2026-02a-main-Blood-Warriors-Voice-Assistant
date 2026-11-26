"""Embedding + FAISS retrieval over the knowledge base (#5, hybrid ranking added in #15).

Each entry's question_te, question_en and question_hi (when present), plus any extra phrasings in kb/question_variants.json, is
embedded with LaBSE (one vector each, all mapping back to the entry id). Vectors are L2-normalised and
stored in an IndexFlatIP, so search scores are cosine similarity. The index and id map live in
data/index/ (git-ignored) and are rebuilt automatically when missing or when the KB files or the
embedding model change.

Ranking is hybrid: an entry's score is its best LaBSE cosine plus config.LEXICAL_WEIGHT times its best
TF-IDF similarity over character n-grams of the same texts. Many questions share "can I donate blood";
the TF-IDF part makes the rare topic word (tattoo, malaria) decide between them.

    python -m retrieval.index --build
    python -m retrieval.index --query "Next transfusion eppudu?"
"""
import argparse
import hashlib
import json
import logging
import os
import sys
import threading

# On macOS, faiss-cpu and torch (and scikit-learn) each bundle their own libomp; without this the process
# aborts ("OMP: Error #15") or segfaults when both run. tests/test_retrieval.py checks faiss's scores against
# numpy, so a wrong result from the duplicate runtimes would fail the tests. Linux wheels share libgomp.
if sys.platform == "darwin":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import torch  # noqa: E402,F401  (load torch's OpenMP before faiss's)
import faiss  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402

import config

log = logging.getLogger(__name__)

EMBED_FIELDS = ("question_te", "question_en", "question_hi")  # LaBSE is multilingual: one vector each
INDEX_FILE = "kb.faiss"
META_FILE = "kb_meta.json"

_model = None
_state = None  # {"index", "vector_ids", "texts", "entries", "tfidf", "tfidf_matrix"}, set by load() / refresh()
_lock = threading.Lock()


def _kb_entries() -> list[dict]:
    with open(config.KB_PATH, encoding="utf-8") as f:
        return json.load(f)


def _variants() -> dict[str, list[str]]:
    """Extra phrasings per entry id from kb/question_variants.json (optional file)."""
    if not config.KB_VARIANTS_PATH.exists():
        return {}
    data = json.loads(config.KB_VARIANTS_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _kb_sha256() -> str:
    h = hashlib.sha256(config.KB_PATH.read_bytes())
    if config.KB_VARIANTS_PATH.exists():
        h.update(config.KB_VARIANTS_PATH.read_bytes())
    return h.hexdigest()


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # heavy import, only when needed

        _model = SentenceTransformer(config.EMBEDDING_MODEL)
    return _model


def embed(texts: list[str]) -> np.ndarray:
    """L2-normalised float32 embeddings, shape (len(texts), dim)."""
    vecs = _get_model().encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    return np.asarray(vecs, dtype="float32")


def _phrasings(entries: list[dict], variants: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """(texts, vector_ids): every entry's questions and extra phrasings, one vector each."""
    texts, vector_ids = [], []
    for entry in entries:
        own = [entry[field] for field in EMBED_FIELDS if entry.get(field)]
        for text in own + variants.get(entry["id"], []):
            texts.append(text)
            vector_ids.append(entry["id"])
    return texts, vector_ids


def _build(reuse: dict[str, np.ndarray] | None = None) -> dict:
    """Embed the KB (reusing vectors already computed for unchanged texts), write the index and id map to
    data/index/ and return the ready-to-search state."""
    entries = _kb_entries()
    texts, vector_ids = _phrasings(entries, _variants())
    reuse = reuse or {}
    todo = [t for t in dict.fromkeys(texts) if t not in reuse]
    fresh = dict(zip(todo, embed(todo))) if todo else {}
    vecs = np.asarray([reuse.get(t, fresh.get(t)) for t in texts], dtype="float32")
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(config.INDEX_DIR / INDEX_FILE))
    meta = {"model": config.EMBEDDING_MODEL, "kb_sha256": _kb_sha256(), "vector_ids": vector_ids, "texts": texts}
    (config.INDEX_DIR / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Built index: %d vectors for %d entries (%d newly embedded)", index.ntotal, len(entries), len(todo))
    return _make_state(index, vector_ids, texts, entries)


def _make_state(index, vector_ids: list[str], texts: list[str], entries: list[dict]) -> dict:
    tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True, sublinear_tf=True)
    return {
        "index": index,
        "vector_ids": vector_ids,
        "texts": texts,
        "entries": {e["id"]: e for e in entries},
        "tfidf_matrix": tfidf.fit_transform(texts),  # rows L2-normalised: dot = cosine
        "tfidf": tfidf,
    }


def build_index() -> int:
    """Embed every entry's questions (and their variants), save the index and id map to data/index/.
    Returns the vector count."""
    global _state
    state = _build()
    _state = None  # next retrieve() reloads from disk
    return state["index"].ntotal


def refresh() -> int:
    """Bring the live index up to date after the KB files changed (a coordinator taught or undid an answer),
    without restarting the server. Only new or changed phrasings are embedded; searches running meanwhile
    keep using the old index until the new one is swapped in. Returns the vector count."""
    global _state
    with _lock:
        reuse = {}
        current = _state
        if current is None and _index_on_disk():
            meta = json.loads((config.INDEX_DIR / META_FILE).read_text(encoding="utf-8"))
            if meta.get("model") == config.EMBEDDING_MODEL and "texts" in meta:
                current = {"index": faiss.read_index(str(config.INDEX_DIR / INDEX_FILE)), "texts": meta["texts"]}
        if current is not None:
            vecs = current["index"].reconstruct_n(0, current["index"].ntotal)
            reuse = dict(zip(current["texts"], vecs))
        _state = _build(reuse)
        _get_model()
        return _state["index"].ntotal


def _index_on_disk() -> bool:
    return (config.INDEX_DIR / INDEX_FILE).exists() and (config.INDEX_DIR / META_FILE).exists()


def _index_is_current() -> bool:
    meta_path = config.INDEX_DIR / META_FILE
    if not _index_on_disk():
        return False
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return (meta.get("model") == config.EMBEDDING_MODEL and meta.get("kb_sha256") == _kb_sha256()
            and "texts" in meta)


def load() -> None:
    """Load the model and index once per process (building the index if stale). Call at API startup."""
    global _state
    with _lock:
        if _state is not None:
            return
        if not _index_is_current():
            _build()
        meta = json.loads((config.INDEX_DIR / META_FILE).read_text(encoding="utf-8"))
        _state = _make_state(faiss.read_index(str(config.INDEX_DIR / INDEX_FILE)), meta["vector_ids"],
                             meta["texts"], _kb_entries())
        _get_model()


def get_entry(entry_id: str) -> dict | None:
    """One KB entry by id (from the loaded index if there is one, else straight from kb/entries.json)."""
    state = _state
    if state is not None:
        return state["entries"].get(entry_id)
    return next((e for e in _kb_entries() if e["id"] == entry_id), None)


def passage(entry: dict) -> str:
    """The text the LLM is allowed to use for this entry."""
    return _passage(entry)


def _passage(entry: dict) -> str:
    hindi = f" (Hindi: {entry['answer_hi']})" if entry.get("answer_hi") else ""
    return f"[{entry['id']}] {entry['answer_te']} (English: {entry['answer_en']}){hindi}"


def retrieve(query: str, k: int = config.RETRIEVAL_K) -> list[dict]:
    """Top-k KB entries for the query, best first: [{id, score, passage, cosine, question_*, answer_*, source}].

    score = best LaBSE cosine + LEXICAL_WEIGHT * best TF-IDF similarity over the entry's phrasings (so it
    can exceed 1); cosine is the LaBSE part alone. An entry matched on several phrasings appears once.
    cosine, question_te / question_en (#14's clarify prompt), answer_en (the API's English caption) and source (the UI)
    are extras beyond the agreed {id, score, passage}.
    """
    if not query or not query.strip():
        return []
    load()
    state = _state  # one snapshot: refresh() may swap in a new index while this search runs
    index, vector_ids, entries = state["index"], state["vector_ids"], state["entries"]

    # The index is small (one vector per phrasing), so score every vector and keep each entry's best.
    scores, positions = index.search(embed([query]), index.ntotal)
    cosine: dict[str, float] = {}
    for score, pos in zip(scores[0], positions[0]):
        if pos >= 0:
            cosine[vector_ids[pos]] = max(cosine.get(vector_ids[pos], -1.0), float(score))

    lexical_rows = (state["tfidf_matrix"] @ state["tfidf"].transform([query]).T).toarray().ravel()
    lexical: dict[str, float] = {}
    for pos, sim in enumerate(lexical_rows):
        lexical[vector_ids[pos]] = max(lexical.get(vector_ids[pos], 0.0), float(sim))

    combined = {eid: cos + config.LEXICAL_WEIGHT * lexical.get(eid, 0.0) for eid, cos in cosine.items()}
    hits = []
    for entry_id in sorted(combined, key=combined.get, reverse=True)[:k]:
        entry = entries[entry_id]
        hits.append({
            "id": entry_id,
            "score": combined[entry_id],
            "cosine": cosine[entry_id],
            "passage": _passage(entry),
            "question_te": entry["question_te"],
            "question_en": entry["question_en"],
            "question_hi": entry.get("question_hi"),
            "answer_te": entry["answer_te"],
            "answer_en": entry["answer_en"],
            "answer_hi": entry.get("answer_hi"),
            "category": entry.get("category"),
            "source": entry["source"],
        })
    return hits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", action="store_true", help="(re)build the index from kb/entries.json")
    parser.add_argument("--query", help="print the top-k hits for a question")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.build:
        print(f"Indexed {build_index()} vectors into {config.INDEX_DIR}")
    if args.query:
        for hit in retrieve(args.query):
            print(f"{hit['score']:.3f}  {hit['id']:10}  {hit['question_te']}")
    if not (args.build or args.query):
        parser.print_help()


if __name__ == "__main__":
    main()
