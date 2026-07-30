# Built with Spec4 AI - https://spec4.ai
"""A lightweight signal for whether the critique actually read the story.

The capability names "generic/templated critique" as a likely failure: a
critique that would have been written the same way about any story at all.
This module is the cheap automated check for it, mirroring `rag/citations.py`
in both purpose and in the limits it accepts.

**What it measures, precisely.** Whether the critic's `quoted_detail` -- the
phrase it claims to have taken from the story -- actually appears in the story,
either verbatim or as a strong word-level match. Nothing more.

**What it does not measure.** Whether the critique is *right*, whether the
detail it quoted is the interesting one, or whether the surrounding judgement
follows from it. Establishing any of that would take a third model call, which
the chain deliberately does not make. So this is reported as a quality signal
and never as a verdict, and no surface is allowed to render it as one -- the
same rule that stops the RAG app stamping "grounded" on a similarity score.

Kept in its own module, beside the components that use it, because it is pure
logic: it is testable without a model, a database, or a session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Word-level match ratio at which a paraphrase counts as anchored in the
#: story. Set high on purpose: this signal exists to catch critiques that never
#: touched the text, and a low bar would pass a generic sentence that happens
#: to share ordinary English words with the story.
STRONG_MATCH_RATIO = 0.6

#: Tokens too common to carry evidence of having read anything.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "the", "of", "to", "in", "is", "it", "its", "that",
        "this", "was", "were", "be", "been", "with", "for", "on", "at", "as", "by",
        "but", "or", "not", "his", "her", "their", "they", "he", "she", "you",
        "from", "had", "has", "have", "into", "than", "then", "there", "which",
    }
)

_WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class OverlapSignal:
    """How strongly the critique's quoted detail is anchored in the story.

    Attributes:
        quoted_detail_found: True when the quoted detail appears in the story
            verbatim, ignoring case, punctuation, and whitespace runs.
        match_ratio: The share of the quoted detail's content words that appear
            in the story, 0.0 to 1.0. 0.0 when the detail carries no content
            words at all, which is itself a finding.
        references_story: The headline signal -- a verbatim hit, or a word-level
            match at or above STRONG_MATCH_RATIO. False means the critique
            failed to anchor itself, not that the critique is wrong.
    """

    quoted_detail_found: bool
    match_ratio: float
    references_story: bool


def _normalize(text: str) -> str:
    """Reduce text to lowercase words separated by single spaces.

    Args:
        text: Any text.

    Returns:
        The text lowercased, with every run of non-word characters collapsed to
        one space and the ends trimmed -- so a verbatim comparison is not
        defeated by a curly quote or a line wrap.
    """
    return " ".join(_WORD_RE.findall(text.lower()))


def _content_words(text: str) -> set[str]:
    """Extract the words that could evidence having read a specific text.

    Args:
        text: Any text.

    Returns:
        The lowercased words of length two or more, minus stopwords.
    """
    return {word for word in _WORD_RE.findall(text.lower()) if len(word) > 1 and word not in _STOPWORDS}


def measure(story: str, quoted_detail: str) -> OverlapSignal:
    """Measure how well a quoted detail is anchored in the story it came from.

    Google-style docstring per project convention.

    Args:
        story: The intermediate output's text, as produced by call 1.
        quoted_detail: The phrase call 2 claims to have taken from it.

    Returns:
        The signal. A blank quoted detail scores zero on every field rather
        than raising: the critic returning nothing to check is a result, and
        the caller logs it like any other.
    """
    normalized_detail = _normalize(quoted_detail)
    if not normalized_detail:
        return OverlapSignal(quoted_detail_found=False, match_ratio=0.0, references_story=False)

    found = normalized_detail in _normalize(story)

    detail_words = _content_words(quoted_detail)
    story_words = _content_words(story)
    ratio = len(detail_words & story_words) / len(detail_words) if detail_words else 0.0

    return OverlapSignal(
        quoted_detail_found=found,
        match_ratio=round(ratio, 3),
        references_story=found or ratio >= STRONG_MATCH_RATIO,
    )
