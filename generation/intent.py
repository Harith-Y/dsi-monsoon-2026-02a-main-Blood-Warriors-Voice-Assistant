"""Short spoken replies: did the person say yes or no? Keyword match in Telugu, Hindi and English
(romanised too), earliest match wins, so "no, not that" is no and "yes, correct" is yes."""

import re

YES = {
    "yes", "yeah", "yep", "yup", "ya", "correct", "right", "ok", "okay", "sure", "haan", "han", "ha", "haa",
    "ji", "avunu", "avnu", "aunu", "sare", "saree", "sari",
    "అవును", "ఔను", "అవునండి", "హా", "హాఁ", "సరే", "సరి", "కరెక్ట్", "ఎస్", "ఓకే",
    "हाँ", "हां", "हा", "जी", "सही", "ठीक", "बिल्कुल", "यस", "ओके",
}
NO = {
    "no", "nope", "not", "wrong", "nahi", "nahin", "nai", "na", "kaadu", "kadu", "ledu", "vaddu",
    "కాదు", "కాదండి", "లేదు", "వద్దు", "నో",
    "नहीं", "नही", "ना", "गलत", "ग़लत", "नो", "मत",
}
CHANGE = {"change", "edit", "badlo", "badal", "maarchu", "marchu", "మార్చు", "మార్చండి", "बदलो", "बदलें", "बदल"}


def yes_no(text: str | None, allow_change: bool = False) -> str | None:
    """'yes' | 'no' | 'change' (only if allow_change) | None when the reply is neither."""
    text = re.sub("[​-‍]", "", (text or "").lower())  # zero-width joiners split no words
    for token in re.findall(r"[\wऀ-ॿఀ-౿]+", text):
        if token in YES:
            return "yes"
        if token in NO:
            return "no"
        if allow_change and token in CHANGE:
            return "change"
    return None
