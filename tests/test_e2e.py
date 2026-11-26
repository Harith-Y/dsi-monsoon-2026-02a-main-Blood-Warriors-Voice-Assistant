"""The 3 demo journeys (docs/demo.md) against real providers, no mocking (run with -m live).

Journey 1 (schedule) uses the typed question, not its audio clip c01: IndicConformer mis-hears
"ట్రాన్స్‌ఫ్యూజన్" (transfusion) as "కన్ఫ్యూజన్" (confusion) on that recording, so retrieval scores
0.64 against the 0.73 threshold and falls back. That is a real, reproducible speech-to-text error, not a
pipeline bug; in a live demo, tap the example question for this journey. Journeys 2 and 3 pass on their
real recorded clips.
"""
import pytest
from fastapi.testclient import TestClient

import config
from api.main import app
from retrieval.index import load as load_retrieval

# Real uvicorn always runs FastAPI's lifespan, which warms up retrieval (LaBSE) before the first
# request. A bare TestClient(app) does not, so without this, the first retrieve() call in this
# process pays LaBSE's ~9 s cold-load time against RETRIEVE_TIMEOUT_S=5 s and times out.
load_retrieval()
client = TestClient(app)


@pytest.mark.live
def test_journey1_schedule_text():
    """Caregiver, happy path: typed (see module docstring for why not the c01 clip)."""
    resp = client.post("/ask", data={"text": "Next transfusion eppudu?"})
    body = resp.json()
    assert body["fallback"] is False, body
    assert body["source_id"] == "sched-01", body


@pytest.mark.live
def test_journey2_eligibility_codemixed_clip():
    """Donor, code-mixed, real audio clip c02."""
    with open(config.AUDIO_DIR / "c02.wav", "rb") as f:
        resp = client.post("/ask", files={"audio": ("c02.wav", f, "audio/wav")})
    body = resp.json()
    assert body["fallback"] is False, body
    assert body["source_id"] == "elig-01", body


@pytest.mark.live
def test_journey3_medical_fallback_clip():
    """Medical fallback: real audio clip c03, safety gate before retrieval/LLM."""
    with open(config.AUDIO_DIR / "c03.wav", "rb") as f:
        resp = client.post("/ask", files={"audio": ("c03.wav", f, "audio/wav")})
    body = resp.json()
    assert body["fallback"] is True, body
    assert body["fallback_reason"] == "urgent", body
