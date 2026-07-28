# Built with Spec4 AI - https://spec4.ai
"""Tests for the citation audit that backs the grounded/unsupported status.

The distinction under test is the one the similarity threshold cannot make:
retrieval finding topically-similar passages is not the same event as the
model actually answering from them.
"""

from __future__ import annotations

from unittest.mock import patch

from backend.app.rag.citations import audit_citations
from backend.app.rag.retriever import SIMILARITY_THRESHOLD, RetrievedPassage
from backend.app.rag.service import build_answer


def _passage(passage_id: str) -> RetrievedPassage:
    return RetrievedPassage(
        passage_id=passage_id,
        source_title="Voyager 1",
        text_excerpt="Voyager 1 launched on September 5, 1977.",
        similarity_score=SIMILARITY_THRESHOLD + 0.2,
    )


def test_audit_finds_the_passages_an_answer_cites() -> None:
    audit = audit_citations("Voyager 1 launched in 1977 [1], and left the heliosphere [3].", 3)

    assert audit.cited == [1, 3]
    assert audit.unresolved == []
    assert audit.is_grounded is True


def test_audit_reports_no_citations_as_not_grounded() -> None:
    """The model declining to answer is the case this exists to catch."""
    audit = audit_citations("The passages provided do not answer this question.", 3)

    assert audit.cited == []
    assert audit.is_grounded is False


def test_audit_flags_a_citation_pointing_at_no_retrieved_passage() -> None:
    """Citing [7] when three passages were supplied is an invented source."""
    audit = audit_citations("Voyager 1 launched in 1977 [7].", 3)

    assert audit.cited == []
    assert audit.unresolved == [7]
    assert audit.is_grounded is False


def test_audit_keeps_valid_citations_alongside_invalid_ones() -> None:
    audit = audit_citations("Launched in 1977 [1], now interstellar [9].", 3)

    assert audit.cited == [1]
    assert audit.unresolved == [9]
    assert audit.is_grounded is True


def test_audit_handles_multi_passage_and_repeated_markers() -> None:
    audit = audit_citations("Both sources agree [1, 2]. The first says more [1].", 3)

    assert audit.cited == [1, 2]


def test_audit_treats_zero_as_unresolved() -> None:
    """Citations are 1-based, so [0] refers to nothing."""
    audit = audit_citations("Something [0].", 3)

    assert audit.cited == []
    assert audit.unresolved == [0]


def test_build_answer_marks_a_cited_answer_grounded() -> None:
    with patch(
        "backend.app.rag.service.generate_answer",
        return_value="Voyager 1 launched in 1977 [1].",
    ):
        result = build_answer("When did Voyager 1 launch?", [_passage("voyager-1-1")])

    assert result.status == "grounded"
    assert result.cited_passages == [1]
    assert result.unresolved_citations == []


def test_build_answer_marks_an_uncited_answer_unsupported_despite_clearing_the_threshold() -> None:
    """The regression this whole change exists to prevent: passages scored
    above the threshold, so the old code called the result grounded no matter
    what the model said."""
    with patch(
        "backend.app.rag.service.generate_answer",
        return_value="These passages do not say who the first woman in space was.",
    ):
        result = build_answer("Who was the first woman in space?", [_passage("yuri-gagarin-1")])

    assert result.status == "unsupported"
    assert result.cited_passages == []


def test_build_answer_surfaces_an_invented_citation() -> None:
    with patch(
        "backend.app.rag.service.generate_answer",
        return_value="It launched in 1977 [4].",
    ):
        result = build_answer("When did Voyager 1 launch?", [_passage("voyager-1-1")])

    assert result.status == "unsupported"
    assert result.unresolved_citations == [4]
