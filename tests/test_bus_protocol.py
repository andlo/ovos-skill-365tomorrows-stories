"""Tests for translation fallback, bus protocol handlers, and matching -
mirrors ovos-skill-ovosblog/ovos-skill-arxiv-papers's test suite (same
design, third real-world test of the pattern)."""
from unittest.mock import MagicMock

from conftest import COMMON_READING_SEARCH_RESPONSE, COMMON_READING_FETCH_CONTENT_RESPONSE


def make_message(data=None):
    m = MagicMock()
    m.data = data or {}
    m.reply = MagicMock(side_effect=lambda mtype, d: MagicMock(msg_type=mtype, data=d))
    return m


def _sample_index():
    return {
        "https://365tomorrows.com/older": {"title": "Older Story", "author": "Alice",
                                            "pubdate": "Mon, 01 Jan 2024 00:00:00 +0000"},
        "https://365tomorrows.com/newer": {"title": "Newer Story", "author": "Bob",
                                            "pubdate": "Wed, 01 Jan 2025 00:00:00 +0000"},
    }


def test_handle_search_matches_by_phrase(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": "older story"}))
    sent = skill.bus.emit.call_args[0][0]
    assert sent.msg_type == COMMON_READING_SEARCH_RESPONSE
    assert sent.data["content_id"] == "https://365tomorrows.com/older"
    assert sent.data["author"] == "Alice"
    assert sent.data["source"] == "365tomorrows.com"
    assert sent.data["machine_translated"] is False


def test_handle_search_surprise_me_picks_latest(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": None, "collection_hint": "365 tomorrows"}))
    sent = skill.bus.emit.call_args[0][0]
    assert sent.data["content_id"] == "https://365tomorrows.com/newer"


def test_handle_search_stays_silent_for_unmatched_collection(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": "older story", "collection_hint": "grimm"}))
    skill.bus.emit.assert_not_called()


def test_handle_search_stays_silent_for_mismatched_content_type(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": "older story", "content_type": "paper"}))
    skill.bus.emit.assert_not_called()


def test_handle_search_responds_for_matching_content_type(skill):
    skill.index = _sample_index()
    for content_type in ["story", "tale"]:
        skill.bus.emit.reset_mock()
        skill.handle_search(make_message({"phrase": "older story", "content_type": content_type}))
        skill.bus.emit.assert_called_once()


def test_handle_fetch_content_returns_paragraphs(skill):
    skill.index = _sample_index()
    skill.get_story_paragraphs = MagicMock(return_value=["Once upon a time.", "The end."])

    skill.handle_fetch_content(make_message({"content_id": "https://365tomorrows.com/older"}))

    sent = skill.bus.emit.call_args[0][0]
    assert sent.msg_type == COMMON_READING_FETCH_CONTENT_RESPONSE
    assert sent.data["paragraphs"] == ["Once upon a time.", "The end."]


def test_handle_fetch_content_unknown_id_returns_empty(skill):
    skill.index = {}
    skill.handle_fetch_content(make_message({"content_id": "nonexistent"}))
    sent = skill.bus.emit.call_args[0][0]
    assert sent.data["paragraphs"] == []


def test_non_english_matches_against_translated_titles(skill, monkeypatch):
    from conftest import TomorrowsStories
    monkeypatch.setattr(TomorrowsStories, "lang", "da-dk", raising=False)
    skill.index = _sample_index()
    fake_translator = MagicMock()
    translations = {"Older Story": "Ældre historie", "Newer Story": "Nyere historie"}
    fake_translator.translate.side_effect = lambda text, target, source: translations[text]
    skill._get_translator = MagicMock(return_value=fake_translator)

    skill.handle_search(make_message({"phrase": "ældre historie"}))

    sent = skill.bus.emit.call_args[0][0]
    assert sent.data["content_id"] == "https://365tomorrows.com/older"
    assert sent.data["machine_translated"] is True


def test_non_english_without_translator_stays_silent(skill, monkeypatch):
    from conftest import TomorrowsStories
    monkeypatch.setattr(TomorrowsStories, "lang", "da-dk", raising=False)
    skill.index = _sample_index()
    skill._get_translator = MagicMock(return_value=None)

    skill.handle_search(make_message({"phrase": "ældre historie"}))

    skill.bus.emit.assert_not_called()
