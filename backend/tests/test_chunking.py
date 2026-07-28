# Built with Spec4 AI - https://spec4.ai
from backend.app.rag.chunking import DEFAULT_WINDOW_CHARS, chunk_document
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
    """Every word from the source text must appear in some passage, and
    passages must be produced in the order the words occur, so no window of
    the original text larger than the configured size is skipped."""
    text = "\n\n".join(
        [
            "Alpha bravo charlie delta echo foxtrot golf hotel.",
            "India juliet kilo lima mike november oscar papa.",
            "Quebec romeo sierra tango uniform victor whiskey.",
        ]
    )

    passages = chunk_document("Coverage Doc", text, window_chars=40)

    expected_words = text.replace("\n\n", " ").split()
    actual_words = " ".join(p.text_excerpt for p in passages).split()
    assert actual_words == expected_words


def test_every_reference_dataset_document_chunks_into_non_empty_passages() -> None:
    documents = load_dataset_documents()

    assert len(documents) >= 8

    for document in documents:
        passages = chunk_document(document.title, document.text, DEFAULT_WINDOW_CHARS)

        assert len(passages) > 0, f"{document.title} produced no passages"
        for passage in passages:
            assert len(passage.text_excerpt) <= DEFAULT_WINDOW_CHARS
            assert passage.text_excerpt.strip() != ""
