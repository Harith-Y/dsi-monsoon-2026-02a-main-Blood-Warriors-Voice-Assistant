import pytest

from generation.safety import is_urgent

URGENT = [
    "Naa child ki fever undi, transfusion cheyacha?",
    "my son has fever",
    "bleeding aagatledu",
    "he is unconscious",
    "chest pain vastundi",
    "this is an emergency",
    "hospital lo admit chesaru",
    "jvaram vachindi",
    "మా బాబుకి జ్వరం ఉంది",
    "రక్తస్రావం అవుతోంది",
    "ఊపిరి ఆడటం లేదు",
    "నా బిడ్డకు శ్వాస తీసుకోవడం కష్టంగా ఉంది",  # breathing trouble, formal Telugu word
    "baby ki swasa ibbandi ga undi",
    "ఎమర్జెన్సీ",
    "స్పృహ తప్పి పడిపోయాడు",
    "మా బిడ్డకి ఐరన్ తగ్గించే మందు డోస్ ఎంత ఇవ్వాలి?",  # medicine dose (eval q35)
    "What dose of deferasirox should I give?",
    "Iron mandu eppudu veyali?",
    "హెచ్‌పీఎల్‌సీ" + "\u200c" + " జ్వ\u200cరం",  # zero-width char inside a word
]
NOT_URGENT = [
    "Next transfusion eppudu?",
    "Nenu blood donate cheyacha? Last time July lo ichanu.",
    "What are the benefits of donating blood?",  # 'fits' inside 'benefits'
    "HPLC test ante enti?",
    "తదుపరి రక్త మార్పిడి ఎప్పుడు?",
    "Donation mundu emi tinali?",  # 'mundu' (before) is not 'mandu' (medicine)
    "నేను మాత్రమే వస్తాను",  # 'మాత్రమే' (only) is not 'మాత్రలు' (tablets)
    "",
]


@pytest.mark.parametrize("text", URGENT)
def test_urgent(text):
    assert is_urgent(text)


@pytest.mark.parametrize("text", NOT_URGENT)
def test_not_urgent(text):
    assert not is_urgent(text)
