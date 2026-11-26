"""Schema checks for kb/entries.json (issue #2)."""

import json

import pytest

import config

REQUIRED_FIELDS = ("id", "category", "question_te", "question_en", "question_hi",
                   "answer_te", "answer_en", "answer_hi", "source")
CATEGORIES = {"transfusion_schedule", "donor_eligibility", "donation_request", "hplc_testing", "general"}
DEMO_SOURCE = "Fictional demo record"
# Details from the fictional demo record; any entry using them must say so in its source.
DEMO_MARKERS = ("Aarav", "Niloufer", "5 July 2026")


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    with open(config.KB_PATH, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    return data


def test_at_least_15_entries(entries):
    assert len(entries) >= 15


def test_required_fields_present_and_non_empty(entries):
    for entry in entries:
        for field in REQUIRED_FIELDS:
            value = entry.get(field)
            assert isinstance(value, str) and value.strip(), f"{entry.get('id')}: empty or missing {field}"


def test_ids_unique(entries):
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate ids"


def test_all_categories_present_and_known(entries):
    used = {e["category"] for e in entries}
    assert used == CATEGORIES, f"missing {CATEGORIES - used}, unknown {used - CATEGORIES}"


def test_authoritative_is_bool_when_present(entries):
    for entry in entries:
        if "authoritative" in entry:
            assert isinstance(entry["authoritative"], bool), entry["id"]


def test_demo_details_marked_as_fictional(entries):
    for entry in entries:
        if any(marker in entry["answer_en"] for marker in DEMO_MARKERS):
            assert entry["source"] == DEMO_SOURCE, entry["id"]
            assert entry.get("authoritative") is False, entry["id"]


def test_no_answer_tells_people_to_phone(entries):
    """Blood Warriors asked for no calls: answers point to the WhatsApp chat button instead."""
    import re
    for entry in entries:
        assert not re.search(r"\b(call|phone|dial)\b", entry["answer_en"], re.I), entry["id"]
        assert "ఫోన్ చేయ" not in entry["answer_te"] and "कॉल कर" not in entry["answer_hi"], entry["id"]
