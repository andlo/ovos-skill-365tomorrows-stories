"""Tests for feed fetching/parsing and story-page text extraction."""
from unittest.mock import MagicMock

import pytest
import requests
from conftest import StoryFetchError

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><channel>
<title>365tomorrows</title>
<item>
  <title>Older Story</title>
  <link>https://365tomorrows.com/2024/01/01/older-story/</link>
  <dc:creator>Alice</dc:creator>
  <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>
  <description><![CDATA[<p>Author: Alice An excerpt of the older story [&#8230;]</p>]]></description>
</item>
<item>
  <title>Newer Story</title>
  <link>https://365tomorrows.com/2025/01/01/newer-story/</link>
  <dc:creator>Bob</dc:creator>
  <pubDate>Wed, 01 Jan 2025 00:00:00 +0000</pubDate>
  <description><![CDATA[<p>Author: Bob An excerpt of the newer story [&#8230;]</p>]]></description>
</item>
</channel></rss>"""

SAMPLE_STORY_HTML = """
<html><body>
<article>
<div class="entry-content">
<p>Author: Alice</p>
<p>Once upon a time, in a
galaxy of little consequence.</p>
<p>The end.</p>
</div>
</article>
</body></html>
"""


def test_fetch_feed_index_parses_items(skill, monkeypatch):
    fake_response = MagicMock(content=SAMPLE_FEED.encode("utf-8"))
    fake_response.raise_for_status = MagicMock()
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)

    index = skill.fetch_feed_index()

    assert len(index) == 2
    link = "https://365tomorrows.com/2024/01/01/older-story/"
    assert index[link]["title"] == "Older Story"
    assert index[link]["author"] == "Alice"


def test_fetch_feed_index_network_error_raises(skill, monkeypatch):
    def fail(*a, **kw):
        raise requests.ConnectionError("boom")
    monkeypatch.setattr(requests, "get", fail)

    with pytest.raises(StoryFetchError):
        skill.fetch_feed_index()


def test_latest_link_picks_most_recent_pubdate(skill, monkeypatch):
    fake_response = MagicMock(content=SAMPLE_FEED.encode("utf-8"))
    fake_response.raise_for_status = MagicMock()
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)
    skill.index = skill.fetch_feed_index()

    assert skill._latest_link() == "https://365tomorrows.com/2025/01/01/newer-story/"


def test_get_story_paragraphs_excludes_author_line_and_fixes_linewrap(skill, monkeypatch):
    fake_response = MagicMock(text=SAMPLE_STORY_HTML)
    fake_response.raise_for_status = MagicMock()
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)

    paragraphs = skill.get_story_paragraphs("http://x/story")

    assert paragraphs == ["Once upon a time, in a galaxy of little consequence.", "The end."]
    assert not any("author" in p.lower() for p in paragraphs)


def test_get_story_paragraphs_caches(skill, monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return MagicMock(text=SAMPLE_STORY_HTML, raise_for_status=MagicMock())

    monkeypatch.setattr(requests, "get", fake_get)
    skill.get_story_paragraphs("http://x/story")
    skill.get_story_paragraphs("http://x/story")

    assert len(calls) == 1


def test_get_story_paragraphs_missing_content_raises(skill, monkeypatch):
    fake_response = MagicMock(text="<html><body>nothing here</body></html>")
    fake_response.raise_for_status = MagicMock()
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)

    with pytest.raises(StoryFetchError):
        skill.get_story_paragraphs("http://x/empty")


def test_get_story_paragraphs_network_error_raises(skill, monkeypatch):
    def fail(*a, **kw):
        raise requests.ConnectionError("boom")
    monkeypatch.setattr(requests, "get", fail)

    with pytest.raises(StoryFetchError):
        skill.get_story_paragraphs("http://x/story")
