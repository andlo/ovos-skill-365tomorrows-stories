"""initialize() must not fetch the archive itself: OVOS loads skills one
at a time, and a first-run fetch (77 pages of ~1.7 MB) held up every
other skill for ~5 minutes. The cached index is used at once, even when
stale, and the fetch runs in a background thread."""
import json
import threading
import time
from unittest.mock import MagicMock

from conftest import StoryFetchError as _StoryFetchError

STALE = {"timestamp": 0, "index": {"1": {"title": "Old story", "author": "A", "pubdate": "", "link": ""}}}
FRESH = {"2": {"title": "New story", "author": "B", "pubdate": "", "link": ""}}


def _init(skill, monkeypatch, fetch):
    monkeypatch.setattr(skill, "_load_collection_aliases", lambda: None)
    monkeypatch.setattr(skill, "add_event", MagicMock(), raising=False)
    monkeypatch.setattr(skill, "fetch_archive_index", fetch)
    skill.initialize()


def test_initialize_returns_before_the_archive_is_fetched(skill, monkeypatch):
    release = threading.Event()

    def slow_fetch():
        release.wait(5)
        return dict(FRESH)

    start = time.monotonic()
    _init(skill, monkeypatch, slow_fetch)
    assert time.monotonic() - start < 1.0
    # events are registered even though the fetch is still running
    assert skill.add_event.call_count == 4  # search, fetch, ping, vocabulary.get
    release.set()
    skill._refresh_thread.join(5)
    assert skill.index == FRESH


def test_stale_cache_is_used_immediately_then_replaced(skill, monkeypatch, tmp_path):
    (tmp_path / skill._index_cache_filename()).write_text(json.dumps(STALE))
    release = threading.Event()

    def slow_fetch():
        release.wait(5)
        return dict(FRESH)

    _init(skill, monkeypatch, slow_fetch)
    assert skill.index == STALE["index"]          # usable straight away
    release.set()
    skill._refresh_thread.join(5)
    assert skill.index == FRESH
    cached = json.loads((tmp_path / skill._index_cache_filename()).read_text())
    assert cached["index"] == FRESH


def test_fresh_cache_is_not_refetched(skill, monkeypatch, tmp_path):
    (tmp_path / skill._index_cache_filename()).write_text(
        json.dumps({"timestamp": time.time(), "index": FRESH}))
    fetch = MagicMock(return_value={})
    _init(skill, monkeypatch, fetch)
    skill._refresh_thread.join(5)
    fetch.assert_not_called()
    assert skill.index == FRESH


def test_a_failing_fetch_keeps_the_cached_index_and_does_not_raise(skill, monkeypatch, tmp_path):
    (tmp_path / skill._index_cache_filename()).write_text(json.dumps(STALE))

    def broken():
        raise RuntimeError("network down")

    _init(skill, monkeypatch, broken)
    skill._refresh_thread.join(5)
    assert skill.index == STALE["index"]
    skill.log.error.assert_called()


def test_an_empty_index_is_retried_in_the_background(skill, monkeypatch):
    monkeypatch.setattr(type(skill), "REFRESH_RETRY_DELAY", 0)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _StoryFetchError("Read timed out")
        return dict(FRESH)

    _init(skill, monkeypatch, flaky)
    skill._refresh_thread.join(5)
    assert len(calls) == 3
    assert skill.index == FRESH


def test_gives_up_after_the_configured_attempts(skill, monkeypatch):
    monkeypatch.setattr(type(skill), "REFRESH_RETRY_DELAY", 0)
    fetch = MagicMock(side_effect=_StoryFetchError("down"))
    _init(skill, monkeypatch, fetch)
    skill._refresh_thread.join(5)
    assert fetch.call_count == type(skill).REFRESH_ATTEMPTS
    assert skill.index == {}
