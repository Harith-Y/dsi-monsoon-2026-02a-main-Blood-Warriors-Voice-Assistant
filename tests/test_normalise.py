import pytest

from asr.normalise import normalise

# What IndicConformer actually returned for the code-mixed demo clip c02 (#13).
C02_ASR = "డొనేట్ చేయొచ్చా లాస్ట్ టైం జూలైలో ఇచ్చాను"


def test_maps_telugu_script_english_terms():
    assert normalise("హెచ్‌పీఎల్‌సీ టెస్ట్ అంటే ఏంటి") == "HPLC test అంటే ఏంటి"  # ZWNJ variant of the glossary key
    assert normalise("ట్రాన్స్ఫ్యూజన్ ఎప్పుడు") == "transfusion ఎప్పుడు"


def test_plain_telugu_unchanged():
    text = "నాకు మళ్ళీ రక్తం ఎక్కించేది ఎప్పుడు"
    assert normalise(text) == text


@pytest.mark.live  # loads LaBSE
def test_code_mixed_demo_question_retrieves_eligibility_entry():
    from retrieval.index import retrieve

    assert retrieve(normalise(C02_ASR), k=1)[0]["id"] == "elig-01"
