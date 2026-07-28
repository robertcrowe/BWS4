# Built with Spec4 AI - https://spec4.ai
import pytest

from backend.app.rag.chunking import DEFAULT_WINDOW_CHARS, chunk_document, embedding_text
from backend.app.rag.dataset_loader import load_dataset_documents


def test_chunk_document_produces_non_empty_passages() -> None:
    passages = chunk_document("Sample Title", "First paragraph.\n\nSecond paragraph.")

    assert len(passages) > 0
    for passage in passages:
        assert passage.text_excerpt.strip() != ""
        assert passage.source_title == "Sample Title"
        assert passage.passage_id


def test_chunk_document_passage_ids_are_unique_within_a_document() -> None:
    text = "\n\n".join(f"Paragraph number {i} with some content." for i in range(10))

    passages = chunk_document("Unique Ids", text)

    ids = [p.passage_id for p in passages]
    assert len(ids) == len(set(ids))


def test_chunk_document_windows_stay_within_the_configured_size() -> None:
    long_paragraph = " ".join(f"word{i}" for i in range(500))

    passages = chunk_document("Long Doc", long_paragraph, window_chars=100)

    assert len(passages) > 1
    for passage in passages:
        assert len(passage.text_excerpt) <= 100


def test_chunk_document_covers_the_full_text_with_no_gaps_larger_than_the_window() -> None:
    """No part of the source text may be dropped by chunking.

    Asserted as adjacent-pair coverage rather than as equality between the
    source words and the concatenated passages: windows now overlap, so the
    concatenation repeats words by design. Every consecutive pair of words
    appearing together inside some passage is the stronger property anyway --
    it rules out a gap at a window boundary, which plain word coverage would
    not catch.
    """
    text = "\n\n".join(
        [
            "Alpha bravo charlie delta echo foxtrot golf hotel.",
            "India juliet kilo lima mike november oscar papa.",
            "Quebec romeo sierra tango uniform victor whiskey.",
        ]
    )

    passages = chunk_document("Coverage Doc", text, window_chars=40)

    passage_word_lists = [p.text_excerpt.split() for p in passages]
    for paragraph in text.split("\n\n"):
        words = paragraph.split()
        for first, second in zip(words, words[1:]):
            assert any(
                any(
                    candidate[i] == first and candidate[i + 1] == second
                    for i in range(len(candidate) - 1)
                )
                for candidate in passage_word_lists
            ), f"no passage contains the adjacent pair {first!r} {second!r}"


def test_chunk_document_overlaps_consecutive_windows() -> None:
    """Consecutive windows must share trailing context, so a fact split across
    a boundary is still retrievable in full from one side of it."""
    text = " ".join(f"Sentence number {i} carries some filler content." for i in range(30))

    passages = chunk_document("Overlap Doc", text, window_chars=200, overlap_chars=60)

    assert len(passages) > 2
    for earlier, later in zip(passages, passages[1:]):
        shared = set(earlier.text_excerpt.split()) & set(later.text_excerpt.split())
        assert shared, "consecutive windows share no text at all"


def test_chunk_document_rejects_an_overlap_that_does_not_fit_the_window() -> None:
    with pytest.raises(ValueError):
        chunk_document("Bad Config", "some text", window_chars=100, overlap_chars=100)


def test_chunk_document_does_not_split_mid_sentence_when_a_boundary_exists() -> None:
    """The visitor reads every retrieved passage, so a passage beginning
    "and Gemini programs." reads as a bug even when retrieval is unaffected."""
    text = " ".join(
        f"This is sentence {i} and it runs on for a while to fill the window." for i in range(12)
    )

    passages = chunk_document("Sentence Doc", text, window_chars=200)

    for passage in passages:
        first_word = passage.text_excerpt.split()[0]
        assert first_word[0].isupper(), f"passage starts mid-sentence: {passage.text_excerpt[:60]!r}"


def test_chunk_document_keeps_abbreviations_inside_one_sentence() -> None:
    """A period after a known abbreviation is not a sentence boundary."""
    text = "The U.S. Air Force ran the program. NASA took over later on."

    passages = chunk_document("Abbrev Doc", text, window_chars=40, overlap_chars=0)

    assert any("U.S. Air Force" in p.text_excerpt for p in passages)


def test_embedding_text_prepends_the_source_title() -> None:
    """Retrieval embeds the title with the excerpt; the excerpt itself, which
    the visitor reads and the prompt quotes, stays untouched."""
    passage = chunk_document("Voyager 1", "It was launched in 1977.")[0]

    assert passage.text_excerpt == "It was launched in 1977."
    assert embedding_text(passage) == "Voyager 1: It was launched in 1977."


def test_every_reference_dataset_document_chunks_into_non_empty_passages() -> None:
    documents = load_dataset_documents()

    assert len(documents) >= 8

    for document in documents:
        passages = chunk_document(document.title, document.text, DEFAULT_WINDOW_CHARS)

        assert len(passages) > 0, f"{document.title} produced no passages"
        for passage in passages:
            assert len(passage.text_excerpt) <= DEFAULT_WINDOW_CHARS
            assert passage.text_excerpt.strip() != ""
