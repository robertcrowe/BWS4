# Built with Spec4 AI - https://spec4.ai
"""Tests for custom_text_semantic_placement.

Split deliberately: the validation and wiring tests inject a fake embedder so
they run without the model, while the semantic plausibility tests use the real
one -- "a kitten lands near the animals" is a claim about the actual
representation, and a fake vector would assert nothing about it.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api.embeddings import get_embedder
from backend.app.embeddings import placement, service
from backend.app.embeddings.presets import CATEGORY_ANIMALS, PRESET_TEXT_EXAMPLES
from backend.app.main import app

pytestmark = pytest.mark.usefixtures("_warm_cache")


@pytest.fixture(scope="module")
def _warm_cache():
    """Build the projection once for the whole module.

    Placement reads the Phase 2 cache; building it per test would pay the
    model load repeatedly for no added coverage.
    """
    service.ensure_built()
    yield


def _fake_embedder(dimensions: int = 384):
    """Return a deterministic stand-in for the embedding model.

    Deterministic rather than random so a test asserting stability is
    measuring placement, not the fake.
    """

    def embed(text: str) -> list[float]:
        seed = sum(ord(c) for c in text)
        return [((seed + i) % 97) / 97.0 for i in range(dimensions)]

    return embed


# --- validation -------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t\n  ", " "])
def test_placement_rejects_empty_or_whitespace_only_text(blank: str) -> None:
    """422 before any embedding happens, per the capability's failure modes."""
    with pytest.raises(placement.InvalidCustomTextError):
        placement.normalize_custom_text(blank)


def test_placement_rejects_text_over_the_maximum_length() -> None:
    """Over-long input is refused rather than silently truncated by the model."""
    too_long = "a" * (placement.MAX_CUSTOM_TEXT_CHARS + 1)

    with pytest.raises(placement.InvalidCustomTextError, match="too long"):
        placement.normalize_custom_text(too_long)


def test_placement_accepts_text_at_exactly_the_maximum_length() -> None:
    """The bound is inclusive -- an off-by-one here rejects valid input."""
    at_limit = "a" * placement.MAX_CUSTOM_TEXT_CHARS

    assert placement.normalize_custom_text(at_limit) == at_limit


def test_placement_strips_surrounding_whitespace_from_the_echoed_text() -> None:
    """The echoed text is the normalized one the plot should label the point with."""
    result = placement.place_custom_text("  kitten  ", embed=_fake_embedder())

    assert result.text == "kitten"


# --- the endpoint -----------------------------------------------------------


def _client_with_fake_embedder() -> TestClient:
    app.dependency_overrides[get_embedder] = lambda: _fake_embedder()
    return TestClient(app)


def test_placement_endpoint_returns_the_capability_schema() -> None:
    """The response matches the Outputs schema note field for field."""
    client = _client_with_fake_embedder()
    try:
        with client:
            response = client.post("/api/embeddings/place", json={"custom_text": "kitten"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    assert set(body) == {"point", "text", "nearest_neighbors", "embedding_model_version"}
    assert set(body["point"]) == {"x", "y"}
    assert isinstance(body["point"]["x"], float)
    assert body["text"] == "kitten"
    assert body["embedding_model_version"]
    for neighbor in body["nearest_neighbors"]:
        assert set(neighbor) == {"text", "distance"}


@pytest.mark.parametrize("blank", ["", "   "])
def test_placement_endpoint_answers_422_for_blank_text(blank: str) -> None:
    """The HTTP boundary rejects blanks, so no embedding is ever attempted."""
    client = _client_with_fake_embedder()
    try:
        with client:
            response = client.post("/api/embeddings/place", json={"custom_text": blank})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_placement_endpoint_answers_503_with_a_retryable_code_when_embedding_fails() -> None:
    """The escalation path: a machine-readable code the UI can offer a retry on."""

    def broken(_text: str) -> list[float]:
        raise RuntimeError("model went away")

    app.dependency_overrides[get_embedder] = lambda: broken
    try:
        with TestClient(app) as client:
            response = client.post("/api/embeddings/place", json={"custom_text": "kitten"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["code"] == "embedding_unavailable"


def test_placement_module_has_no_datastore_reach() -> None:
    """placement.py cannot persist, because it cannot see the database layer.

    A structural guarantee rather than an observation: the capability's
    Privacy & safety section forbids storing what a visitor types, and an
    import that isn't there can't be called by a later edit without the edit
    also adding the import.
    """
    source = Path(placement.__file__).read_text(encoding="utf-8")

    assert "backend.app.db" not in source
    assert "session" not in source.lower()


def test_placement_endpoint_serves_with_the_database_unavailable() -> None:
    """The behavioural half: placement answers 200 with no database at all.

    Any session opened during the request would hit the exploding factory and
    fail the test, so a pass means nothing was written or read.
    """

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("placement must not open a database session")

    app.dependency_overrides[get_embedder] = lambda: _fake_embedder()
    try:
        with patch("backend.app.db.session.async_session_factory", explode):
            with TestClient(app) as client:
                response = client.post("/api/embeddings/place", json={"custom_text": "kitten"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_placement_does_not_log_the_visitor_text_verbatim() -> None:
    """Log lines carry a hash and a length, never the text.

    The capability's Privacy & safety section allows debugging signal but not
    the raw value, so this pins the redaction rather than trusting review.
    """
    secret = "my private thoughts about sourdough"

    with patch.object(placement.logger, "info") as mocked_info:
        placement.place_custom_text(secret, embed=_fake_embedder())

    logged = repr(mocked_info.call_args)
    assert secret not in logged
    assert placement._redacted(secret) in logged
    assert str(len(secret)) in logged


# --- the risk this phase names: presets must not move -----------------------


def test_placement_leaves_preset_coordinates_byte_for_byte_unchanged() -> None:
    """The regression test the phase's mitigation strategy asks for.

    A `.fit()` or `.fit_transform()` slip in placement.py recomputes the PCA
    basis over a set including the visitor's point, silently moving every
    preset already on screen. Repeated placements with deliberately varied
    text make that visible here rather than in the UI.
    """
    before = [(p.label, p.x, p.y) for p in service.get_preset_points()]
    fit_count_before = service.fit_count()

    for text in ["kitten", "a thunderstorm", "quicksort", "espresso", "x" * 400]:
        placement.place_custom_text(text, embed=_fake_embedder())

    after = [(p.label, p.x, p.y) for p in service.get_preset_points()]

    assert after == before
    assert service.fit_count() == fit_count_before, "the projection was refit during placement"


def test_placement_is_stable_for_the_same_text_across_calls() -> None:
    """The same submission lands in the same place every time."""
    first = placement.place_custom_text("kitten", embed=_fake_embedder())
    second = placement.place_custom_text("kitten", embed=_fake_embedder())

    assert (first.point.x, first.point.y) == (second.point.x, second.point.y)


# --- semantic plausibility, against the real model --------------------------


def test_placement_neighbors_are_measured_in_the_unprojected_space() -> None:
    """Neighbour distances must not be 2D distances.

    Cosine distance over L2-normalized 384-dim vectors is bounded by 2 and,
    for related text, lands well below 1. The 2D coordinates span a much
    smaller numeric range, so a suspiciously tiny distance for unrelated text
    is the signature of ranking on the projection by mistake. This checks the
    reported distance against a recomputed cosine distance in the raw space.
    """
    import numpy as np

    result = placement.place_custom_text("a small kitten")

    presets = service.get_preset_embeddings()
    examples = service.get_preset_examples()
    vector = np.array(placement.embed_text("a small kitten"))

    for neighbor in result.nearest_neighbors:
        index = next(i for i, e in enumerate(examples) if e.label == neighbor.text)
        expected = 1.0 - float(presets[index] @ vector)
        assert neighbor.distance == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    ("text", "expected_category"),
    [
        ("a small kitten", CATEGORY_ANIMALS),
        ("a fox running through the woods", CATEGORY_ANIMALS),
    ],
)
def test_placement_puts_animal_text_next_to_animal_presets(
    text: str, expected_category: str
) -> None:
    """The capability's eval approach, on a small labeled set.

    This is the claim the whole tier rests on -- that meaning, not wording,
    decides position. None of these phrases share a word with the presets
    they should land beside.
    """
    result = placement.place_custom_text(text)

    categories = {
        example.category
        for neighbor in result.nearest_neighbors
        for example in PRESET_TEXT_EXAMPLES
        if example.label == neighbor.text
    }

    assert expected_category in categories, (
        f"'{text}' landed beside {[n.text for n in result.nearest_neighbors]}"
    )


def test_placement_reports_the_same_model_the_presets_were_embedded_with() -> None:
    """One representation across the app suite, asserted on the wire field."""
    result = placement.place_custom_text("kitten")

    assert result.embedding_model_version == service.get_embedding_model_name()
