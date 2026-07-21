"""Tests for the REST API archive index (pagination) and story-text
extraction (single-post fetch)."""
from unittest.mock import MagicMock

import pytest
import requests
from conftest import StoryFetchError

SAMPLE_CONTENT_HTML = "<p>Author: Alice</p><p>Once upon a time, in a\ngalaxy of little consequence.</p><p>The end.</p>"


def make_post(post_id, title, content_html, date_gmt="2026-01-01T00:00:00"):
    return {
        "id": post_id,
        "title": {"rendered": title},
        "content": {"rendered": content_html},
        "date_gmt": date_gmt,
        "link": f"https://365tomorrows.com/{post_id}/",
    }


def fake_pages_response(pages):
    """pages: list of lists of post dicts; page N (1-indexed) -> pages[N-1].
    Requesting beyond the list returns HTTP 400, like the real API."""
    def fake_get(url, params=None, timeout=None):
        page = (params or {}).get("page", 1)
        if page > len(pages):
            return MagicMock(status_code=400)
        resp = MagicMock(status_code=200)
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=pages[page - 1])
        return resp
    return fake_get


def test_fetch_archive_index_paginates_until_400(skill, monkeypatch):
    pages = [
        [make_post(1, "Older Story", SAMPLE_CONTENT_HTML)],
        [make_post(2, "Newer Story", SAMPLE_CONTENT_HTML)],
    ]
    monkeypatch.setattr(requests, "get", fake_pages_response(pages))

    index = skill.fetch_archive_index()

    assert len(index) == 2
    assert index["1"]["title"] == "Older Story"
    assert index["1"]["author"] == "Alice"
    assert index["2"]["title"] == "Newer Story"


def test_fetch_archive_index_captures_author_without_second_request(skill, monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        page = (params or {}).get("page", 1)
        if page > 1:
            return MagicMock(status_code=400)
        resp = MagicMock(status_code=200)
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=[make_post(1, "Story", SAMPLE_CONTENT_HTML)])
        return resp

    monkeypatch.setattr(requests, "get", fake_get)
    index = skill.fetch_archive_index()

    assert index["1"]["author"] == "Alice"
    # only the listing endpoint was hit - no per-story fetch needed for the index
    assert all("/posts/" not in c for c in calls)


def test_fetch_archive_index_network_error_raises(skill, monkeypatch):
    def fail(*a, **kw):
        raise requests.ConnectionError("boom")
    monkeypatch.setattr(requests, "get", fail)

    with pytest.raises(StoryFetchError):
        skill.fetch_archive_index()


def test_latest_post_id_picks_most_recent_pubdate(skill, monkeypatch):
    pages = [[
        make_post(1, "Older Story", SAMPLE_CONTENT_HTML, date_gmt="2024-01-01T00:00:00"),
        make_post(2, "Newer Story", SAMPLE_CONTENT_HTML, date_gmt="2025-01-01T00:00:00"),
    ]]
    monkeypatch.setattr(requests, "get", fake_pages_response(pages))
    skill.index = skill.fetch_archive_index()

    assert skill._latest_post_id() == "2"


def test_get_story_paragraphs_excludes_author_line_and_fixes_linewrap(skill, monkeypatch):
    fake_response = MagicMock(status_code=200)
    fake_response.raise_for_status = MagicMock()
    fake_response.json = MagicMock(return_value=make_post(1, "Story", SAMPLE_CONTENT_HTML))
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)

    paragraphs = skill.get_story_paragraphs("1")

    assert paragraphs == ["Once upon a time, in a galaxy of little consequence.", "The end."]
    assert not any("author" in p.lower() for p in paragraphs)


def test_get_story_paragraphs_caches(skill, monkeypatch):
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        resp = MagicMock(status_code=200)
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=make_post(1, "Story", SAMPLE_CONTENT_HTML))
        return resp

    monkeypatch.setattr(requests, "get", fake_get)
    skill.get_story_paragraphs("1")
    skill.get_story_paragraphs("1")

    assert len(calls) == 1


def test_get_story_paragraphs_missing_content_raises(skill, monkeypatch):
    fake_response = MagicMock(status_code=200)
    fake_response.raise_for_status = MagicMock()
    fake_response.json = MagicMock(return_value=make_post(1, "Empty", ""))
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)

    with pytest.raises(StoryFetchError):
        skill.get_story_paragraphs("1")


def test_get_story_paragraphs_network_error_raises(skill, monkeypatch):
    def fail(*a, **kw):
        raise requests.ConnectionError("boom")
    monkeypatch.setattr(requests, "get", fail)

    with pytest.raises(StoryFetchError):
        skill.get_story_paragraphs("1")
