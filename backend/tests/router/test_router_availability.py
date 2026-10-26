# Built with Spec4 AI - https://spec4.ai
"""The Router's ready/unavailable state: best-effort warm-up, flag and retry.

Route-description preparation is an optional startup step. If it fails, the
API still boots, the presets report `available: false`, runs and re-runs are
refused before moderation and before any hold, and `POST /retry` restores the
Router without a restart. The other apps never notice.

No placeholder credentials: the failure is injected by patching the warm-up or
the indexed-title read, and the suite's fake store stands in for the database.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from backend.app import main
from backend.app.main import app
from backend.app.router import classifier, state
from backend.app.router.state import RouteDescriptions
from backend.app.services.moderation import (
    ModerationCategory,
    ModerationVerdict,
    get_stateless_moderator,
)


async def _titles_unreachable(*_args: object) -> list[str]:
    raise ConnectionError("database unreachable")


def _titles_readable(titles: list[str]) -> Callable[..., Any]:
    async def read(*_args: object) -> list[str]:
        return titles

    return read


@pytest.fixture
def unavailable() -> None:
    """Start the test with the holder empty, as after a failed warm-up."""
    state.reset_route_descriptions()


@pytest.fixture
def moderation_calls() -> Iterator[list[str]]:
    """Override the gate with one that allows everything and records calls.

    Yields:
        The texts the gate was asked about.
    """
    calls: list[str] = []

    async def moderate(text: str, _context: str) -> ModerationVerdict:
        calls.append(text)
        return ModerationVerdict(
            allowed=True, category=ModerationCategory.OK, visitor_message=""
        )

    async def provider() -> object:
        return moderate

    app.dependency_overrides[get_stateless_moderator] = provider
    yield calls
    app.dependency_overrides.pop(get_stateless_moderator, None)


@pytest.fixture
def refuse_classify() -> Iterator[None]:
    """Fail loudly if a refused run ever reaches the router call.

    Yields:
        None.
    """

    async def classify(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("an unavailable Router reached the router call")

    with patch.object(classifier, "classify", classify):
        yield


class TestBestEffortWarmUp:
    def test_api_boots_when_warm_up_raises(self, unavailable: None) -> None:
        async def boom() -> RouteDescriptions:
            raise RuntimeError("route descriptions failed")

        with (
            patch.object(main, "warm_route_descriptions", boom),
            capture_logs() as logs,
            TestClient(app) as booted,
        ):
            presets = booted.get("/api/router/presets")

        assert presets.status_code == 200
        assert presets.json()["available"] is False
        failures = [e for e in logs if e["event"] == "router_warmup_failed"]
        assert len(failures) == 1
        assert failures[0]["log_level"] == "error"

    def test_a_failed_boot_reports_unavailable_until_a_retry_succeeds(
        self, unavailable: None, stub_titles: list[str]
    ) -> None:
        with patch.object(state, "load_indexed_document_titles", _titles_unreachable):
            with TestClient(app) as booted:
                assert booted.get("/api/router/presets").json()["available"] is False

                with patch.object(
                    state, "load_indexed_document_titles", _titles_readable(stub_titles)
                ):
                    retried = booted.post("/api/router/retry")

                body = booted.get("/api/router/presets").json()

        assert retried.status_code == 200
        assert retried.json() == {"available": True}
        assert body["available"] is True
        assert len(body["route_descriptions"]) == 4
        assert body["route_descriptions_block"] == state.current_route_block()

    def test_other_apps_work_while_the_router_is_unavailable(
        self, unavailable: None
    ) -> None:
        with patch.object(state, "load_indexed_document_titles", _titles_unreachable):
            with TestClient(app) as booted:
                embeddings = booted.get("/api/embeddings/presets")
                router_presets = booted.get("/api/router/presets")

        assert router_presets.json()["available"] is False
        assert embeddings.status_code == 200
        assert embeddings.json()["presets"]


class TestRefusedWhileUnavailable:
    def test_run_is_an_ordinary_error_before_moderation_and_hold(
        self,
        unavailable: None,
        router_store: Any,
        moderation_calls: list[str],
        refuse_classify: None,
    ) -> None:
        store = router_store()
        with TestClient(app) as booted:
            response = booted.post(
                "/api/router/run",
                json={"request": "What is the speed of light?", "visit_id": "v1"},
            )

        assert response.status_code == 503
        assert response.headers["content-type"].startswith("application/json")
        detail = response.json()["detail"]
        assert detail["code"] == "descriptions_not_ready"
        assert "temporarily unavailable" in detail["message"]
        assert moderation_calls == []
        assert store.holds == {}
        assert store.used() == 0
        assert store.agreement_rows == []
        assert store.latency_rows == []

    def test_rerun_is_refused_before_anything_is_held(
        self, unavailable: None, router_store: Any
    ) -> None:
        store = router_store()
        response = TestClient(app).post(
            "/api/router/rerun",
            json={
                "preset_id": "p1",
                "original_run_id": str(uuid.uuid4()),
                "visit_id": "v1",
            },
        )

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "descriptions_not_ready"
        assert store.holds == {}
        assert store.used() == 0


class TestRetry:
    def test_a_failed_retry_keeps_the_router_unavailable(
        self, unavailable: None, router_store: Any
    ) -> None:
        store = router_store()
        client = TestClient(app)
        with patch.object(state, "load_indexed_document_titles", _titles_unreachable):
            response = client.post("/api/router/retry")

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "descriptions_not_ready"
        assert state.get_route_descriptions() is None
        assert client.get("/api/router/presets").json()["available"] is False
        # The retry is free: no usage reserved, no hold written.
        assert store.added == []

    def test_retry_when_already_available_reads_nothing(
        self, route_descriptions: RouteDescriptions
    ) -> None:
        async def titles(*_args: object) -> list[str]:
            raise AssertionError("an available Router re-read the titles")

        with patch.object(state, "load_indexed_document_titles", titles):
            response = TestClient(app).post("/api/router/retry")

        assert response.status_code == 200
        assert state.get_route_descriptions() is route_descriptions


class TestHolderState:
    def test_unavailable_reports_not_ready(self, unavailable: None) -> None:
        assert state.is_ready() is False
        assert state.current_route_block() is None

    def test_a_failed_warm_up_raises_and_stores_nothing(
        self, unavailable: None
    ) -> None:
        with patch.object(state, "load_indexed_document_titles", _titles_unreachable):
            with pytest.raises(ConnectionError):
                asyncio.run(state.warm_route_descriptions())

        assert state.is_ready() is False

    def test_a_failure_while_building_leaves_no_partial_state(
        self, unavailable: None, stub_titles: list[str]
    ) -> None:
        def broken(*_args: object) -> Any:
            raise ValueError("bad title")

        with (
            patch.object(
                state, "load_indexed_document_titles", _titles_readable(stub_titles)
            ),
            patch.object(state, "build_route_descriptions", broken),
        ):
            with pytest.raises(ValueError):
                asyncio.run(state.warm_route_descriptions())

        assert state.get_route_descriptions() is None

    def test_a_successful_warm_up_makes_it_ready(
        self, unavailable: None, stub_titles: list[str]
    ) -> None:
        with patch.object(
            state, "load_indexed_document_titles", _titles_readable(stub_titles)
        ):
            descriptions = asyncio.run(state.warm_route_descriptions())

        assert state.is_ready() is True
        assert state.get_route_descriptions() is descriptions
