"""Confidence decision (#14): answer, ask one clarifying question, or hand off to the coordinator."""

import config
from i18n import t


def decide(hits: list[dict], session: dict | None = None) -> str:
    """Return "answer" | "clarify" | "fallback" from the top retrieval score.

    score >= ANSWER_THRESHOLD -> answer; CLARIFY_THRESHOLD <= score < ANSWER_THRESHOLD -> clarify,
    but only once per session (session["clarified"]); anything lower -> fallback.
    """
    if not hits:
        return "fallback"
    score = hits[0]["score"]
    if score >= config.ANSWER_THRESHOLD:
        return "answer"
    # No question text to ask back with -> nothing to clarify, hand off (never crash).
    if score >= config.CLARIFY_THRESHOLD and not (session or {}).get("clarified") and hits[0].get("question_te"):
        return "clarify"
    return "fallback"


def clarify_prompt(hit: dict, lang: str = "te") -> tuple[str, str]:
    """("did you mean" in lang, the same in English), built from the top hit's KB question."""
    def question(code: str) -> str:
        return (hit.get(f"question_{code}") or hit.get("question_en") or hit["question_te"]).rstrip("?？ ")
    return t("clarify.question", lang, question=question(lang)), t("clarify.question", "en", question=question("en"))
