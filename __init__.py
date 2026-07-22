"""
skill OVOS 365 Tomorrows Stories
Copyright (C) 2026  Andreas Lorensen

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

---

Provider skill for ovos-common-reading-pipeline-plugin: reads flash
science fiction from 365tomorrows.com aloud (content_type:
"story"/"tale"). Content is licensed CC BY-NC-ND 3.0 - short (<=600
words), general-audience flash fiction, updated daily since 2005.

Indexes the FULL archive (~7600 stories at time of writing, category
"Story" only - excludes "Voices of Tomorrow" audio posts and
"Fragments"), not just the latest handful - via WordPress's REST API
(wp-json/wp/v2/posts), which is paginated and also returns full post
content directly (no separate per-story HTML scrape needed, unlike the
RSS feed which only carries a truncated excerpt).

Like ovos-skill-ovosblog/ovos-skill-arxiv-papers - and unlike the
Gutenberg-sourced providers (ovos-skill-andersen-tales,
ovos-skill-grimm-tales, ovos-skill-bechstein-tales,
ovos-skill-cosquin-tales, ovos-skill-andrew-lang-tales) - this provider
DOES machine-translate for non-English devices: these are short,
self-contained stories (the same order of length as a blog post or a
paper abstract), a much smaller translation-quality risk than a full
fairy tale's literary prose. Always loads regardless of device language;
declines per-search (not per-load) if no translator is available.
"""

from ovos_workshop.skills import OVOSSkill
from ovos_utils.parse import match_one
from ovos_utils import classproperty
from ovos_utils.process_utils import RuntimeRequirements

import requests
from bs4 import BeautifulSoup
import re
import time
import json

API_BASE = "https://365tomorrows.com/wp-json/wp/v2"
STORY_CATEGORY_ID = 3  # confirmed via GET {API_BASE}/categories - "Story" (7593 posts at time of writing)
POSTS_PER_PAGE = 100


class StoryFetchError(Exception):
    """Raised when the archive index or a story's text could not be
    fetched or parsed."""


COMMON_READING_SEARCH = "ovos.common_reading.search"
COMMON_READING_SEARCH_RESPONSE = "ovos.common_reading.search.response"
COMMON_READING_FETCH_CONTENT = "ovos.common_reading.fetch_content"  # + ".{this_skill_id}"
COMMON_READING_FETCH_CONTENT_RESPONSE = "ovos.common_reading.fetch_content.response"
COMMON_READING_PING = "ovos.common_reading.ping"
COMMON_READING_PONG = "ovos.common_reading.pong"

# this provider translates and works on ANY device language (unlike
# andersen-tales/grimm-tales's fixed SUPPORTED_LANGUAGES set) - so
# collection_hint aliases are loaded per-language from
# locale/<lang>/collection.voc where we've bothered to translate them
# (the pipeline's own 8 supported languages), falling back to this
# English list for anything else. COLLECTION_NAME stays an untranslated
# proper noun ("365tomorrows") - only the ALIASES need localizing. See
# ovos-common-reading-pipeline-plugin#26.
FALLBACK_COLLECTION_ALIASES = ["365 tomorrows", "three sixty five tomorrows", "tomorrows"]
CONTENT_TYPES = ["story", "tale"]
COLLECTION_HINT_THRESHOLD = 0.85
COLLECTION_NAME = "365tomorrows"
SOURCE_NAME = "365tomorrows.com"
LICENSE_NOTICE = "Creative Commons Attribution-NonCommercial-NoDerivs 3.0"


class TomorrowsStories(OVOSSkill):

    # the archive is large (~7600 stories) but mostly static - only ~1
    # new story/day - so this is refreshed far less often than
    # ovosblog/arxiv-papers's TTLs
    INDEX_CACHE_TTL = 60 * 60 * 24  # 24h

    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(
            internet_before_load=True,
            network_before_load=True,
            requires_internet=True,
            requires_network=True,
            no_internet_fallback=True,
            no_network_fallback=True,
        )

    def initialize(self):
        self.index = {}  # post_id (str) -> {title, author, pubdate, link}
        self._story_text_cache = {}  # post_id (str) -> full story text (paragraphs)
        self._translator = None
        self._translator_failed = False
        self._translated_titles_cache = {}
        self._load_collection_aliases()
        self.refresh_index()
        self.add_event(COMMON_READING_SEARCH, self.handle_search)
        self.add_event(f"{COMMON_READING_FETCH_CONTENT}.{self.skill_id}", self.handle_fetch_content)
        self.add_event(COMMON_READING_PING, self.handle_ping)

    def _load_collection_aliases(self):
        """Loads collection_hint aliases for the CURRENT device language
        via OVOS's own resource file resolution (self.resources), falling
        back to FALLBACK_COLLECTION_ALIASES (English) if this language
        hasn't been translated. See ovos-common-reading-pipeline-plugin#26."""
        aliases_raw = self.resources.load_vocabulary_file("collection")
        aliases = [phrase for line in aliases_raw for phrase in line]
        self._collection_aliases = aliases or FALLBACK_COLLECTION_ALIASES

    def _index_cache_filename(self):
        return "archive_index.json"

    def _read_index_cache(self):
        cache_file = self._index_cache_filename()
        if not self.file_system.exists(cache_file):
            return None
        try:
            with self.file_system.open(cache_file, "r") as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            self.log.warning(f"could not read index cache: {e}")
            return None

    def _write_index_cache(self):
        cache_file = self._index_cache_filename()
        try:
            with self.file_system.open(cache_file, "w") as f:
                json.dump({"timestamp": time.time(), "index": self.index}, f)
        except OSError as e:
            self.log.warning(f"could not write index cache: {e}")

    def refresh_index(self, force=False):
        cached = self._read_index_cache()
        if not force and cached and (time.time() - cached.get("timestamp", 0)) < self.INDEX_CACHE_TTL:
            self.index = cached.get("index", {})
            self._translated_titles_cache.clear()
            return
        try:
            self.index = self.fetch_archive_index()
            self._write_index_cache()
            self._translated_titles_cache.clear()
        except StoryFetchError as e:
            self.log.error(f"Could not refresh archive index: {e}")
            if cached:
                self.log.warning("Falling back to previously cached (possibly stale) archive index")
                self.index = cached.get("index", {})
                self._translated_titles_cache.clear()

    @staticmethod
    def _extract_author_and_paragraphs(html):
        """Shared by index-building (which needs just the author for
        each entry) and fetch_content (which needs the paragraphs) -
        both come from the same 'content.rendered' HTML the REST API
        returns, whose first paragraph is always 'Author: <name>'."""
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = []
        author = ""
        for p in soup.find_all("p"):
            text = re.sub(r"\s+", " ", p.get_text(strip=True)).strip()
            if not text:
                continue
            if text.lower().startswith("author:") and not author:
                author = text.split(":", 1)[1].strip()
                continue
            paragraphs.append(text)
        return author, paragraphs

    def fetch_archive_index(self):
        """Paginates through the FULL archive via WordPress's REST API
        (category=Story only, excludes 'Voices of Tomorrow' audio posts
        and 'Fragments') - not just the RSS feed's latest ~10 items.
        Each page's response already includes full post content, so the
        author (parsed from it) can be captured here without a second
        request per story later."""
        index = {}
        page = 1
        while True:
            try:
                r = requests.get(f"{API_BASE}/posts", params={
                    "categories": STORY_CATEGORY_ID,
                    "per_page": POSTS_PER_PAGE,
                    "page": page,
                }, timeout=15)
            except requests.RequestException as e:
                if index:
                    break  # keep whatever pages succeeded so far
                raise StoryFetchError(f"failed to fetch archive page {page}: {e}") from e
            if r.status_code == 400:
                break  # WordPress returns 400 once past the last page
            try:
                r.raise_for_status()
                posts = r.json()
            except (requests.RequestException, ValueError) as e:
                if index:
                    break
                raise StoryFetchError(f"failed to fetch/parse archive page {page}: {e}") from e
            if not posts:
                break

            for post in posts:
                post_id = str(post["id"])
                title = (post.get("title", {}).get("rendered") or "").strip()
                if not title:
                    continue
                author, _ = self._extract_author_and_paragraphs(post.get("content", {}).get("rendered", ""))
                index[post_id] = {
                    "title": title,
                    "author": author,
                    "pubdate": post.get("date_gmt", ""),
                    "link": post.get("link", ""),
                }
            page += 1

        if not index:
            raise StoryFetchError("archive parsed but contained no usable stories")
        return index

    def get_story_paragraphs(self, post_id):
        if post_id in self._story_text_cache:
            return self._story_text_cache[post_id]
        try:
            r = requests.get(f"{API_BASE}/posts/{post_id}", timeout=10)
            r.raise_for_status()
            post = r.json()
        except (requests.RequestException, ValueError) as e:
            raise StoryFetchError(f"failed to fetch post {post_id}: {e}") from e

        _, paragraphs = self._extract_author_and_paragraphs(post.get("content", {}).get("rendered", ""))
        if not paragraphs:
            raise StoryFetchError(f"no story text found for post {post_id}")
        self._story_text_cache[post_id] = paragraphs
        return paragraphs

    def _latest_post_id(self):
        from datetime import datetime
        best_id, best_date = None, None
        for post_id, entry in self.index.items():
            try:
                d = datetime.fromisoformat(entry["pubdate"])
            except (TypeError, ValueError):
                continue
            if best_date is None or d > best_date:
                best_date, best_id = d, post_id
        return best_id or (next(iter(self.index), None))

    def _get_translator(self):
        if self._translator is None and not self._translator_failed:
            try:
                from ovos_plugin_manager.language import OVOSLangTranslationFactory
                self._translator = OVOSLangTranslationFactory.create()
            except Exception as e:
                self.log.warning(f"no language translation plugin available: {e}")
                self._translator_failed = True
        return self._translator

    def _get_translated_titles(self, lang):
        """Match against *translated* titles, not English ones. Returns
        None if translation isn't possible - callers must treat that as
        'we cannot offer anything in this language' rather than falling
        back to English titles (see ovos-skill-ovosblog for the
        reasoning)."""
        target = lang.split("-")[0]
        if target == "en":
            return {post_id: entry["title"] for post_id, entry in self.index.items()}

        cached = self._translated_titles_cache.get(target)
        if cached is not None:
            return cached

        translator = self._get_translator()
        if translator is None:
            return None

        translated = {}
        try:
            for post_id, entry in self.index.items():
                translated[post_id] = translator.translate(entry["title"], target=target, source="en")
        except Exception as e:
            self.log.warning(f"failed to translate titles to '{target}': {e}")
            return None

        self._translated_titles_cache[target] = translated
        return translated

    def _maybe_translate_paragraphs(self, paragraphs, lang):
        target = lang.split("-")[0]
        if target == "en":
            return paragraphs, False
        translator = self._get_translator()
        if translator is None:
            return paragraphs, False
        try:
            translated = [translator.translate(p, target=target, source="en") for p in paragraphs]
            return translated, True
        except Exception as e:
            self.log.warning(f"translation failed, falling back to English: {e}")
            return paragraphs, False

    def _matches_collection_hint(self, hint):
        if not hint:
            return True
        _, score = match_one(hint.lower(), self._collection_aliases)
        return score >= COLLECTION_HINT_THRESHOLD

    def _matches_content_type(self, content_type):
        if not content_type:
            return True
        return content_type.lower() in CONTENT_TYPES

    def handle_search(self, message):
        if not self.index:
            return
        collection_hint = message.data.get("collection_hint")
        if not self._matches_collection_hint(collection_hint):
            return
        content_type = message.data.get("content_type")
        if not self._matches_content_type(content_type):
            return

        titles = self._get_translated_titles(self.lang)
        if titles is None:
            return  # can't offer this language without a translator

        phrase = message.data.get("phrase")
        if phrase:
            title, confidence = match_one(phrase, list(titles.values()))
            post_id = next(pid for pid, t in titles.items() if t == title)
        elif collection_hint:
            # 'read me something from 365tomorrows' with no specific
            # title - the most recent story
            post_id = self._latest_post_id()
            title = titles[post_id]
            confidence = 1.0
        else:
            return

        self.bus.emit(message.reply(COMMON_READING_SEARCH_RESPONSE, {
            "skill_id": self.skill_id,
            "content_id": post_id,
            "title": title,
            "author": self.index[post_id].get("author") or "",
            "collection": COLLECTION_NAME,
            "source": SOURCE_NAME,
            "confidence": confidence,
            "machine_translated": self.lang.split("-")[0] != "en",
        }))

    def handle_fetch_content(self, message):
        content_id = message.data.get("content_id")
        if content_id not in self.index:
            self.bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": []}))
            return
        try:
            paragraphs = self.get_story_paragraphs(content_id)
        except StoryFetchError as e:
            self.log.error(f"Could not fetch story '{content_id}': {e}")
            self.bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": []}))
            return
        paragraphs, _ = self._maybe_translate_paragraphs(paragraphs, self.lang)
        self.bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": paragraphs}))

    def handle_ping(self, message):
        """Cheap 'is anyone there?' reply - no index lookup, no
        translation. Only ever called by the pipeline plugin on its
        rare 0-candidates path (see
        ovos-common-reading-pipeline-plugin#2), never on every search."""
        self.bus.emit(message.reply(COMMON_READING_PONG, {
            "skill_id": self.skill_id,
            "collection": COLLECTION_NAME,
        }))
