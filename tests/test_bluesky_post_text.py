"""Tests for ``BlueskySharer._build_post_text`` packing behavior.

Locks the fix for the "many posts ending in '...'" regression observed
on production Bluesky shares from the Intel/Curator pipeline. The
previous implementation chopped commentary mid-sentence with a hard
ellipsis when the assembled text overflowed 300 chars; the new one
sentence-packs the commentary so the post ends on a clean boundary.

Contract:

  * len(text) <= 300 always (Bluesky's grapheme cap)
  * No trailing "..." or "…" in any path (mid-sentence chops are
    replaced by dropping the next sentence entirely)
  * Title + hashtags always present; commentary is optional
  * If even title + hashtags overflows, the title is word-wrapped at
    the last whitespace boundary that fits — no ellipsis there either
"""

from __future__ import annotations

import pytest

from quantum_curator.bluesky import BlueskySharer
from quantum_curator.models import ContentTopic, CuratedPost


def _make_sharer() -> BlueskySharer:
    """Construct without invoking credential-bound login."""
    sharer = BlueskySharer.__new__(BlueskySharer)
    sharer._handle = "test.bsky.social"
    sharer._app_password = "test-pass"
    sharer._session = None
    return sharer


_DEFAULT_TOPICS = [ContentTopic.HARDWARE]


def _post(
    *,
    title: str = "IBM ships new 1000-qubit chip with improved coherence",
    commentary: str = "",
    topics: list[ContentTopic] | None = None,
) -> CuratedPost:
    # Empty list is a meaningful caller intent (test "no topics" path);
    # only fall back to the default when topics is None (omitted).
    effective_topics = _DEFAULT_TOPICS if topics is None else topics
    return CuratedPost(
        article_id="art-1",
        title=title,
        original_url="https://example.com/article",
        summary="",
        source_name="Test Source",
        curator_commentary=commentary,
        topics=effective_topics,
    )


# ---------- 300-char invariant ----------


def test_short_post_fits_without_truncation():
    sharer = _make_sharer()
    post = _post(
        title="Short title",
        commentary="One short sentence about the development.",
    )
    text = sharer._build_post_text(post)
    assert len(text) <= 300
    assert "..." not in text
    assert "…" not in text
    assert "Short title" in text
    assert "One short sentence" in text
    assert "#QuantumHardware" in text


def test_long_commentary_packs_sentences_without_ellipsis():
    """Long commentary should pack as many full sentences as fit."""
    sharer = _make_sharer()
    commentary = (
        "First sentence is informative and stands alone. "
        "Second sentence adds important context. "
        "Third sentence ties it back to broader implications. "
        "Fourth sentence adds even more elaboration on the topic. "
        "Fifth sentence keeps going because the curator was verbose. "
        "Sixth sentence finally brings the whole thing home with a strong close."
    )
    post = _post(title="Some title", commentary=commentary)
    text = sharer._build_post_text(post)

    assert len(text) <= 300
    assert "..." not in text
    assert "…" not in text
    # First sentence must always make it in if there is any budget at all.
    assert "First sentence" in text


def test_post_never_ends_in_ellipsis():
    """Many edge cases — none should produce trailing '...' or '…'."""
    sharer = _make_sharer()
    cases = [
        ("Short", "Tiny commentary."),
        ("Medium title here", "A " * 80 + "."),  # one massive run-on sentence
        ("Title", "Yes. No. Maybe. Definitely. Probably not. Who knows."),
        ("A " * 50, "Some commentary."),  # very long title
        ("Title", ""),  # no commentary at all
        ("Title", "One sentence with no terminator"),  # no period
    ]
    for title, commentary in cases:
        post = _post(title=title.strip(), commentary=commentary)
        text = sharer._build_post_text(post)
        assert len(text) <= 300, f"overflow for title={title!r}"
        assert not text.endswith("..."), f"trailing ... for title={title!r}"
        assert not text.endswith("…"), f"trailing … for title={title!r}"


def test_overflow_drops_next_sentence_rather_than_chopping():
    """Mid-sentence chop is forbidden — pack stops at the last full sentence."""
    sharer = _make_sharer()
    # Two sentences: first fits, second overflows the budget.
    short_first = "Quick observation."
    huge_second = "X" * 400
    post = _post(
        title="Title",
        commentary=f"{short_first} {huge_second}",
    )
    text = sharer._build_post_text(post)
    assert len(text) <= 300
    # First sentence is intact.
    assert short_first in text
    # Second sentence is not chopped — it's dropped entirely.
    assert "XXX" not in text


# ---------- Title-overflow path ----------


def test_oversized_title_word_wraps_no_ellipsis():
    """If title + hashtags alone overflows, word-wrap title at boundary."""
    sharer = _make_sharer()
    # 350-char title, all word breaks.
    long_title = " ".join(["word"] * 70)  # ~350 chars
    post = _post(title=long_title, commentary="should be dropped")
    text = sharer._build_post_text(post)
    assert len(text) <= 300
    assert "..." not in text
    assert "…" not in text
    # Title was wrapped at a word boundary — "word" appears multiple times
    # and the final word is whole.
    assert "word" in text
    # No commentary in this path.
    assert "should be dropped" not in text


def test_oversized_title_word_break_does_not_split_word():
    sharer = _make_sharer()
    title = " ".join(["alpha", "beta", "gamma", "delta"] * 20)  # ~440 chars
    post = _post(title=title, commentary="")
    text = sharer._build_post_text(post)
    assert len(text) <= 300
    # Last visible word in the title portion is one of the four full tokens.
    title_portion = text.split("\n\n")[0]
    last_word = title_portion.rsplit(" ", 1)[-1] if " " in title_portion else title_portion
    assert last_word in {"alpha", "beta", "gamma", "delta"}


# ---------- Hashtag handling ----------


def test_no_topics_uses_default_hashtag():
    sharer = _make_sharer()
    post = _post(title="Generic title", commentary="Brief.", topics=[])
    text = sharer._build_post_text(post)
    assert "#QuantumComputing" in text
    assert len(text) <= 300


def test_multiple_topics_yield_multiple_hashtags():
    sharer = _make_sharer()
    post = _post(
        title="Crypto + algos news",
        commentary="Brief.",
        topics=[ContentTopic.CRYPTOGRAPHY, ContentTopic.ALGORITHMS],
    )
    text = sharer._build_post_text(post)
    assert "#QuantumCryptography" in text
    assert "#QuantumAlgorithms" in text
    assert len(text) <= 300


# ---------- Commentary-only edge cases ----------


def test_empty_commentary_still_renders():
    sharer = _make_sharer()
    post = _post(title="Title only", commentary="")
    text = sharer._build_post_text(post)
    assert "Title only" in text
    assert "#QuantumHardware" in text
    assert len(text) <= 300
    assert "..." not in text


def test_commentary_with_newlines_and_whitespace_normalizes():
    """Multi-paragraph commentary collapses to a single-line sentence stream."""
    sharer = _make_sharer()
    commentary = "First line.\n\n  Second   line  with   extra   spaces.\n\nThird sentence."
    post = _post(title="Title", commentary=commentary)
    text = sharer._build_post_text(post)
    assert len(text) <= 300
    # Whitespace collapse should have absorbed the doubled spaces.
    assert "extra   spaces" not in text
    assert "First line" in text


def test_commentary_questions_and_exclamations_split_correctly():
    """? and ! count as sentence terminators."""
    sharer = _make_sharer()
    commentary = "Big news! Was it expected? Probably not. Either way it matters."
    post = _post(title="T", commentary=commentary)
    text = sharer._build_post_text(post)
    assert len(text) <= 300
    assert "Big news!" in text
