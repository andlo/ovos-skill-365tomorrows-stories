"""365tomorrows.com sits behind Cloudflare, which answers python-requests'
default User-Agent with 403 - every request must say who is asking. And
the words on either side of an inline tag must not run together."""
from conftest import _module, TomorrowsStories


def test_every_request_sends_a_descriptive_user_agent(skill, monkeypatch):
    seen = []

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"id": 1, "title": {"rendered": "T"}, "content": {"rendered": "<p>Author: A</p><p>Hi.</p>"}}

    def fake_get(url, params=None, timeout=None, headers=None):
        seen.append(headers)
        return Resp()

    monkeypatch.setattr(_module.requests, "get", fake_get)
    skill.get_story_paragraphs(1)
    assert seen and all(h and h["User-Agent"].startswith("ovos-skill-365tomorrows-stories/") for h in seen)


def test_words_around_inline_tags_keep_their_spaces():
    html = "<p>Author: Jane</p><p>She <em>never</em> looked <a href='#'>back</a>, not once.</p>"
    author, paragraphs = TomorrowsStories._extract_author_and_paragraphs(html)
    assert author == "Jane"
    assert paragraphs == ["She never looked back, not once."]
