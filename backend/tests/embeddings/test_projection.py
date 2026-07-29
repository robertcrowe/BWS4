# Built with Spec4 AI - https://spec4.ai
"""Tests for the preset embedding + PCA projection and its in-process cache.

These use the real sentence-transformers model rather than a stub, following
test_embedding_pipeline.py and test_dataset_embeddings.py: the properties
under test here -- that categories separate, that coordinates are stable --
are properties of the *actual* representation, and a stubbed vector would
assert nothing about them.
"""

from __future__ import annotations

import math
from itertools import combinations

import pytest

from backend.app.core.config import get_settings
from backend.app.embeddings import service
from backend.app.embeddings.presets import PRESET_TEXT_EXAMPLES
from backend.app.services import embedding as shared_embedding
from backend.app.services.embedding import EMBEDDING_DIMENSIONS, embed_text


@pytest.fixture(autouse=True)
def _clean_cache():
    """Give every test a process-local cache it fully controls.

    The cache is module-level state; without this a test that resets it
    would change the fit count observed by whichever test ran next.
    """
    service.reset_cache()
    yield
    service.reset_cache()


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.dist(a, b)


def _points_by_category() -> dict[str, list[tuple[float, float]]]:
    grouped: dict[str, list[tuple[float, float]]] = {}
    for point in service.get_preset_points():
        grouped.setdefault(point.category, []).append((point.x, point.y))
    return grouped


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(x for x, _ in points) / len(points),
        sum(y for _, y in points) / len(points),
    )


# --- the projection is fit once, and only once -----------------------------


def test_projection_is_fit_exactly_once_per_process() -> None:
    """Repeated reads must not refit the PCA.

    A refit is not merely wasted work: PCA fit over a different input set
    yields a different basis, so every preset would move. This is the
    guarantee Phase 3's transform-only placement depends on.
    """
    assert service.fit_count() == 0

    service.get_preset_points()
    service.get_preset_points()
    service.get_preset_embeddings()
    service.get_projection()
    service.get_preset_examples()

    assert service.fit_count() == 1


def test_projection_coordinates_are_identical_across_repeated_calls() -> None:
    """A given preset yields the same (x, y) every time it is read."""
    first = {p.label: (p.x, p.y) for p in service.get_preset_points()}
    second = {p.label: (p.x, p.y) for p in service.get_preset_points()}

    assert first == second


def test_projection_cache_rebuilds_from_the_bundled_asset_after_a_restart() -> None:
    """A fresh process reconstructs the identical projection with no datastore.

    reset_cache() stands in for a process restart: the cache is ephemeral
    derived state, so the bundled presets alone must be enough to rebuild it,
    and the rebuild must land in the same place or a restart would silently
    move every point on the plot.
    """
    before = [(p.label, p.x, p.y) for p in service.get_preset_points()]

    service.reset_cache()
    assert service.fit_count() == 0

    after = [(p.label, p.x, p.y) for p in service.get_preset_points()]

    assert after == before


def test_projection_mutating_the_returned_points_cannot_corrupt_the_cache() -> None:
    """Readers get copies; the cached list is not handed out by reference."""
    points = service.get_preset_points()
    points.clear()

    assert len(service.get_preset_points()) == len(PRESET_TEXT_EXAMPLES)


# --- the projection is legible: categories cluster --------------------------


def test_projection_groups_same_category_presets_closer_than_cross_category() -> None:
    """The success criterion the whole demo rests on, measured in 2D.

    Measured in the *projected* space rather than the raw embedding space
    because that is what a visitor actually sees. (In the raw 384 dimensions
    this comparison is far less dramatic -- everything is roughly equidistant
    from everything, which is precisely why the plot needs a projection.)
    """
    grouped = _points_by_category()

    same_category = [
        _distance(a, b) for points in grouped.values() for a, b in combinations(points, 2)
    ]
    cross_category = [
        _distance(a, b)
        for left, right in combinations(grouped, 2)
        for a in grouped[left]
        for b in grouped[right]
    ]

    mean_same = sum(same_category) / len(same_category)
    mean_cross = sum(cross_category) / len(cross_category)

    assert mean_same < mean_cross, f"same={mean_same:.4f} cross={mean_cross:.4f}"


def test_projection_separates_every_pair_of_category_centroids() -> None:
    """Stronger than the means test: no two clusters visually swallow each other.

    For each pair, the centroid separation must exceed the two clusters'
    average radius. A pass on means alone can still look like one smear on
    screen if a single pair overlaps.
    """
    grouped = _points_by_category()
    centroids = {name: _centroid(points) for name, points in grouped.items()}
    radii = {
        name: sum(_distance(p, centroids[name]) for p in points) / len(points)
        for name, points in grouped.items()
    }

    for left, right in combinations(sorted(grouped), 2):
        separation = _distance(centroids[left], centroids[right])
        mean_radius = (radii[left] + radii[right]) / 2
        assert separation > mean_radius, (
            f"{left} and {right} overlap: centroid distance {separation:.4f} "
            f"does not clear mean radius {mean_radius:.4f}"
        )


def test_projection_places_every_preset_nearest_its_own_category_centroid() -> None:
    """No individual point lands in the wrong cluster.

    This is the assertion that caught the original curation: 'chocolate'
    landed among the Emotions and a server-crash sentence landed among the
    Food. See presets.py for the full record. If this fails after an edit to
    the preset list, the edit is the cause.
    """
    grouped = _points_by_category()
    centroids = {name: _centroid(points) for name, points in grouped.items()}

    misplaced = [
        (point.label, point.category, nearest)
        for point in service.get_preset_points()
        if (
            nearest := min(centroids, key=lambda c: _distance((point.x, point.y), centroids[c]))
        )
        != point.category
    ]

    assert not misplaced, f"presets landed in the wrong cluster: {misplaced}"


# --- one shared representation, not a second private model ------------------


def test_projection_uses_the_same_shared_embedding_service_as_the_rag_pipeline() -> None:
    """The embeddings app must not stand up its own model.

    Identity, not equality: `service.embed_text` is asserted to be the very
    function object the RAG pipeline calls, which is the only way to be sure
    no second SentenceTransformer was instantiated alongside it.
    """
    assert service.embed_text is shared_embedding.embed_text


def test_projection_embeddings_match_the_shared_model_vector_exactly() -> None:
    """The cached vectors are what the shared model produces, unmodified.

    Guards the feature's 'app ends up using a different embedding
    representation' failure mode at the level of the numbers themselves --
    a wrapper that normalized or truncated differently would show up here.
    """
    embeddings = service.get_preset_embeddings()
    examples = service.get_preset_examples()

    assert embeddings.shape == (len(PRESET_TEXT_EXAMPLES), EMBEDDING_DIMENSIONS)

    expected = embed_text(examples[0].label)
    assert embeddings[0].tolist() == pytest.approx(expected)


def test_projection_reports_the_configured_shared_model_name() -> None:
    """The model recorded against the cache is the shared configured one."""
    assert service.get_embedding_model_name() == get_settings().embedding_model_name
