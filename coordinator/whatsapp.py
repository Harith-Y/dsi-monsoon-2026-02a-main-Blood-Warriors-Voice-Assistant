"""WhatsApp click-to-chat link to the coordinator (a plain wa.me link: no bot, no WhatsApp API).

Blood Warriors asked for no phone calls, so this link is the only way the UI offers to reach a person.
The message is pre-filled with the caregiver's question and reference code so they never repeat it.
"""

import re
from urllib.parse import quote

import config
from i18n import t


def coordinator_number(number: str | None = None) -> str:
    """Digits only, as wa.me wants them ('+91 93915-51999' -> '919391551999')."""
    return re.sub(r"\D", "", config.COORDINATOR_WHATSAPP if number is None else number)


def message(question: str | None = None, reference: str | None = None, lang: str = "en") -> str:
    question = (question or "").strip().rstrip(".?!। ")
    if question and reference:
        return t("whatsapp.with_ref", lang, question=question, ref=reference)
    if question:
        return t("whatsapp.question", lang, question=question)
    return t("whatsapp.generic", lang)


def whatsapp_url(question: str | None = None, reference: str | None = None, lang: str = "en",
                 number: str | None = None) -> str | None:
    """https://wa.me/<number>?text=<url-encoded message>, or None if no coordinator number is configured."""
    digits = coordinator_number(number)
    if not digits:
        return None
    return f"https://wa.me/{digits}?text={quote(message(question, reference, lang), safe='')}"
