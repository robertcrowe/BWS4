# Built with Spec4 AI - https://spec4.ai
"""Shared text-representation (embedding) service used at index and query time."""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from backend.app.core.config import get_settings

EMBEDDING_DIMENSIONS = 384


@lru_cache
def _get_model() -> SentenceTransformer:
    """Load and cache the sentence-transformers embedding model.

    Google-style docstring per project convention.

    Returns:
        The process-wide SentenceTransformer instance, loaded once per
        process since model load is the expensive part of embedding.
    """
    settings = get_settings()
    # The constructor is typed to return Any in the installed release, so the
    # declared local is what carries the real type to the return.
    model: SentenceTransformer = SentenceTransformer(settings.embedding_model_name)
    return model


def embed_text(text: str) -> list[float]:
    """Produce a compact vector representation (TextRepresentation) of text.

    This is the single embedding entry point shared by index time (embedding
    dataset passages) and query time (embedding a visitor's question), so
    retrieval always compares vectors from the same representation space.

    Google-style docstring per project convention.

    Args:
        text: The text to represent, e.g. a passage excerpt or a question.

    Returns:
        A 384-dimensional embedding vector (all-MiniLM-L6-v2 dimension),
        L2-normalized so cosine similarity reduces to a dot product.
    """
    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()
