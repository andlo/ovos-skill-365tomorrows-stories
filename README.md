# <img src='book-512.png' card_color='#40DBB0' width='50' height='50' style='vertical-align:bottom'/> 365tomorrows Stories (provider)

A *provider* skill for [ovos-common-reading-pipeline-plugin](https://github.com/andlo/ovos-common-reading-pipeline-plugin),
reading flash science fiction from [365tomorrows.com](https://365tomorrows.com/)
aloud - the **full archive** (~7600 stories at time of writing), not
just the latest few.

A new short story (≤600 words) every day since 2005, licensed
[CC BY-NC-ND 3.0](http://creativecommons.org/licenses/by-nc-nd/3.0/) -
attribution required, non-commercial, no derivatives (reading the text
aloud unmodified is a straightforward reproduction, not a derivative
work).

[![Tests](https://github.com/andlo/ovos-skill-365tomorrows-stories/actions/workflows/test.yml/badge.svg)](https://github.com/andlo/ovos-skill-365tomorrows-stories/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/ovos-skill-365tomorrows-stories.svg)](https://pypi.org/project/ovos-skill-365tomorrows-stories/)

> **This skill has no standalone voice interface.** It registers no
> intents and never speaks. It only answers
> [ovos.common_reading.* bus messages](https://github.com/andlo/ovos-common-reading-pipeline-plugin#the-ovoscommon_reading-bus-protocol),
> so you also need **ovos-common-reading-pipeline-plugin** installed and
> added to your pipeline config for it to be useful at all.

## Install
```bash
pip install ovos-skill-365tomorrows-stories ovos-common-reading-pipeline-plugin
```

## Source

Indexes the **full archive**, not just recent stories: paginates
through WordPress's REST API (`wp-json/wp/v2/posts`, filtered to the
"Story" category - excludes the site's separate "Voices of Tomorrow"
audio posts and "Fragments"), ~7600 stories at time of writing across
~76 pages of 100. Refreshed at most once every 24 hours (the archive is
mostly static - only ~1 new story/day).

Each listing page already includes full post content, so the index
captures each story's author (parsed from its first paragraph, always
`Author: <name>`) without a second request per story - only reading a
specific chosen story needs one more request, to that story's own
`wp-json/wp/v2/posts/<id>` endpoint.

(An earlier version of this skill used the RSS feed instead, which only
exposes the ~10 most recent stories - the REST API change was made
specifically to reach the full archive.)

## Translation

Unlike the Gutenberg-sourced fairy-tale providers in this family
(`ovos-skill-andersen-tales`, `ovos-skill-grimm-tales`,
`ovos-skill-bechstein-tales`, `ovos-skill-cosquin-tales`,
`ovos-skill-andrew-lang-tales`), this provider **does** machine-translate
for non-English devices - same approach as `ovos-skill-ovosblog`/
`ovos-skill-arxiv-papers`. These are short (≤600 word), self-contained
stories, a much smaller translation-quality risk than a full fairy
tale's literary prose (see the reasoning in
[ovos-common-reading-pipeline-plugin#5](https://github.com/andlo/ovos-common-reading-pipeline-plugin/issues/5)).

Matches search phrases against *translated* titles and discloses via
`"machine_translated": true/false` in the search response. If no
translation plugin is available, this provider does not respond to
searches at all for a non-English device, rather than silently offering
English content the user didn't ask for.

## Collection hints

Responds to `collection_hint` values in the *device's own language* -
e.g. "365 tomorrows"/"tomorrows" on English, "science fiction noveller"
on Danish, "racconti di fantascienza" on Italian - matched fuzzily
against that language's own alias list (see
`locale/<lang>/collection.voc`). Like `ovos-skill-ovosblog`/
`ovos-skill-arxiv-papers`, this provider works on *any* device language,
so aliases fall back to English for any language we haven't bothered
translating - see [ovos-common-reading-pipeline-plugin#26](https://github.com/andlo/ovos-common-reading-pipeline-plugin/issues/26).
The collection name itself ("365tomorrows") stays untranslated - it's a
proper noun.

## Content type

Identifies as `content_type: "story"` or `"tale"`. A search with a
`content_type` hint for anything else gets no response from this
provider.

## "Surprise me"

A search with no specific `phrase` but a matching `collection_hint`
returns the **most recent** story, by publish date.

## Credits

Content from [365tomorrows.com](https://365tomorrows.com/), licensed
[CC BY-NC-ND 3.0](http://creativecommons.org/licenses/by-nc-nd/3.0/).
Author credited per-story via the `author` field in every search
response.

## Category
**Entertainment**

## Tags
#stories #scifi #flashfiction #creativecommons #provider
