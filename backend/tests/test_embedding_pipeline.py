# Built with Spec4 AI - https://spec4.ai
import math

from backend.app.services.embedding import EMBEDDING_DIMENSIONS, embed_text


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def test_embed_text_returns_a_384_dimensional_vector() -> None:
    vector = embed_text("The Apollo 11 mission landed the first humans on the Moon.")

    assert len(vector) == EMBEDDING_DIMENSIONS == 384
    assert all(isinstance(component, float) for component in vector)


def test_similar_sentences_score_higher_cosine_similarity_than_unrelated_ones() -> None:
    reference = embed_text("The dog ran quickly through the park.")
    similar = embed_text("A canine sprinted across the field.")
    unrelated = embed_text("The stock market closed higher today.")

    similar_score = _cosine_similarity(reference, similar)
    unrelated_score = _cosine_similarity(reference, unrelated)

    assert similar_score > unrelated_score


def test_embed_text_is_deterministic_for_the_same_input() -> None:
    first = embed_text("Voyager 1 is the most distant human-made object from Earth.")
    second = embed_text("Voyager 1 is the most distant human-made object from Earth.")

    assert first == second
