# Built with Spec4 AI - https://spec4.ai
"""Endpoint tests for the embeddings_example_app router.

Lives in backend/tests/embeddings/ rather than flat in backend/tests/ because
Phase 2 and Phase 3 both verify with `uv run pytest backend/tests/embeddings`.

Phase 1's temporary GET /api/embeddings/health probe is gone -- Phase 2
replaced it with the presets endpoint, so the reachability it proved is now
covered by a route that also returns real data.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.app.embeddings.presets import PRESET_TEXT_EXAMPLES
from backend.app.main import app
import pytest


@pytest.fixture(autouse=True)
def _gate_allows_everything(allow_all_moderation: Any) -> None:
    """Every request here carries free text, which the shared gate now checks.

    The gate is not this file's subject, and with no `OPENAI_API_KEY` in the
    test environment it fails closed and would refuse all of them. Overridden
    per module rather than globally, so a test that *should* exercise the gate
    cannot pass by accident.
    """



def test_presets_endpoint_returns_every_curated_example() -> None:
    """One entry per preset, each carrying label, category, and coordinates."""
    with TestClient(app) as client:
        response = client.get("/api/embeddings/presets")

    assert response.status_code == 200
    presets = response.json()["presets"]

    assert len(presets) == len(PRESET_TEXT_EXAMPLES)
    assert {p["label"] for p in presets} == {e.label for e in PRESET_TEXT_EXAMPLES}

    for entry in presets:
        assert set(entry) == {"label", "category", "x", "y"}
        assert isinstance(entry["x"], float)
        assert isinstance(entry["y"], float)


def test_presets_endpoint_is_stable_across_requests() -> None:
    """Two requests return byte-identical coordinates.

    The endpoint reads a cache rather than recomputing, and Phase 4's plot
    would jitter on every poll if that ever stopped being true.
    """
    with TestClient(app) as client:
        first = client.get("/api/embeddings/presets").json()
        second = client.get("/api/embeddings/presets").json()

    assert first == second


def test_startup_warms_the_projection_cache_before_any_request() -> None:
    """The lifespan event pays the embed-and-fit cost at boot, not on a click.

    This is the free-tier cold-start mitigation: entering the TestClient
    context runs the same lifespan Uvicorn does, so a built cache here means
    a visitor's first request finds one already built.
    """
    from backend.app.embeddings import service

    service.reset_cache()
    try:
        with TestClient(app):
            assert service.fit_count() == 1
    finally:
        service.reset_cache()


def test_embeddings_router_does_not_displace_the_existing_routes() -> None:
    """Mounting a fourth router leaves the established surface addressable.

    Registration order is the failure this guards: a router added to
    main.py can shadow an existing path prefix, and the RAG dataset route is
    the cheapest existing endpoint to prove it did not (it touches no DB).
    """
    with TestClient(app) as client:
        response = client.get("/api/rag/dataset")

    assert response.status_code == 200
    assert response.json()["documents"]
