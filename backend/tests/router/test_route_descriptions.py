# Built with Spec4 AI - https://spec4.ai
"""The four route descriptions: generated, ordered, hashed, and served verbatim."""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.router import state
from backend.app.router.classifier import build_instructions
from backend.app.router.constants import (
    DECISION_MARGIN,
    ROUTE_COST_ORDER,
    SEARCH_GENERATION,
    SINGLE_CALL,
)
from backend.app.router.route_descriptions import (
    SINGLE_CALL_DESCRIPTION,
    block_sha256,
    build_route_descriptions,
    route_descriptions_block,
    search_tool_description,
    subject_from_title,
)
from backend.app.router.state import RouteDescriptions
from backend.app.router.unit_table import render_supported_operations_line
from backend.app.tools.agent import TOOL_SCHEMAS

client = TestClient(app)


def _build(titles: list[str]) -> dict[str, str]:
    routes = build_route_descriptions(render_supported_operations_line(), titles)
    return {route.id: route.description for route in routes}


class TestBuildRouteDescriptions:
    def test_four_routes_in_cost_order_with_ranks(self, stub_titles: list[str]) -> None:
        routes = build_route_descriptions("line", stub_titles)
        assert tuple(route.id for route in routes) == ROUTE_COST_ORDER
        assert [route.cost_rank for route in routes] == [0, 1, 2, 3]

    def test_deterministic_line_is_the_table_renderer_output(
        self, stub_titles: list[str]
    ) -> None:
        line = render_supported_operations_line()
        assert _build(stub_titles)["deterministic_evaluator"] == line

    def test_rag_line_names_every_subject(self, stub_titles: list[str]) -> None:
        line = _build(stub_titles)["retrieval"]
        for subject in [
            "Apollo 11",
            "Sputnik 1",
            "Space Shuttle",
            "International Space Station",
            "Hubble Space Telescope",
            "James Webb Space Telescope",
            "Curiosity",
            "SpaceX",
        ]:
            assert subject in line
        assert "(rover)" not in line

    def test_changing_the_titles_changes_the_rag_line(
        self, stub_titles: list[str]
    ) -> None:
        before = _build(stub_titles)
        after = _build([*stub_titles, "Voyager 1"])
        assert "Voyager 1" not in before["retrieval"]
        assert "Voyager 1" in after["retrieval"]
        assert before["deterministic_evaluator"] == after["deterministic_evaluator"]

    def test_title_order_does_not_change_the_line(self, stub_titles: list[str]) -> None:
        assert _build(stub_titles) == _build(list(reversed(stub_titles)))

    def test_search_line_carries_the_declared_tool_description(
        self, stub_titles: list[str]
    ) -> None:
        declared = TOOL_SCHEMAS[0]["function"]["description"]  # type: ignore[index]
        assert search_tool_description() == declared
        assert declared in _build(stub_titles)[SEARCH_GENERATION]

    def test_single_call_line(self, stub_titles: list[str]) -> None:
        assert _build(stub_titles)[SINGLE_CALL] == SINGLE_CALL_DESCRIPTION

    def test_every_line_is_one_line(self, stub_titles: list[str]) -> None:
        for description in _build(stub_titles).values():
            assert "\n" not in description

    def test_no_titles_is_an_error_not_an_empty_subject_list(self) -> None:
        with pytest.raises(ValueError):
            build_route_descriptions("line", [])

    @pytest.mark.parametrize(
        ("title", "subject"),
        [("Curiosity (rover)", "Curiosity"), ("Apollo 11", "Apollo 11")],
    )
    def test_subject_from_title(self, title: str, subject: str) -> None:
        assert subject_from_title(title) == subject


class TestBlock:
    def test_block_is_one_line_per_route_with_no_trailing_newline(
        self, stub_titles: list[str]
    ) -> None:
        routes = build_route_descriptions("line", stub_titles)
        block = route_descriptions_block(routes)
        lines = block.split("\n")
        assert len(lines) == 4
        assert not block.endswith("\n")
        for line, route in zip(lines, routes, strict=True):
            assert line == f"{route.id}: {route.description}"

    def test_current_route_block_is_the_held_block(
        self, route_descriptions: RouteDescriptions
    ) -> None:
        assert state.current_route_block() == route_descriptions.block


class TestPresetsPayload:
    def test_carries_descriptions_block_hash_margin_and_order(self) -> None:
        body = client.get("/api/router/presets").json()

        assert len(body["route_descriptions"]) == 4
        assert [r["id"] for r in body["route_descriptions"]] == list(ROUTE_COST_ORDER)
        assert body["decision_margin"] == DECISION_MARGIN
        assert body["cost_order"] == list(ROUTE_COST_ORDER)
        block = body["route_descriptions_block"]
        assert body["route_descriptions_sha256"] == (
            hashlib.sha256(block.encode("utf-8")).hexdigest()
        )
        assert body["route_descriptions_sha256"] == block_sha256(block)

    def test_block_matches_the_listed_descriptions(self) -> None:
        body = client.get("/api/router/presets").json()
        rebuilt = "\n".join(
            f"{r['id']}: {r['description']}" for r in body["route_descriptions"]
        )
        assert body["route_descriptions_block"] == rebuilt

    def test_not_ready_is_a_503_not_invented_text(self) -> None:
        state.reset_route_descriptions()

        async def unreachable(*_args: object) -> list[str]:
            raise ConnectionError("database unreachable")

        with patch.object(state, "load_indexed_document_titles", unreachable):
            response = client.get("/api/router/presets")

        assert response.status_code == 503
        assert "not ready" in response.json()["detail"]

    def test_not_ready_recovers_once_titles_are_readable(self) -> None:
        state.reset_route_descriptions()

        async def titles(*_args: object) -> list[str]:
            return ["Apollo 11"]

        with patch.object(state, "load_indexed_document_titles", titles):
            response = client.get("/api/router/presets")

        assert response.status_code == 200
        assert "Subjects: Apollo 11." in response.json()["route_descriptions_block"]


class TestPageMatchesPrompt:
    def test_served_block_is_the_block_in_the_router_prompt(self) -> None:
        body = client.get("/api/router/presets").json()
        block = body["route_descriptions_block"]

        instructions = build_instructions(state.current_route_block() or "")

        assert block in instructions
        assert (
            hashlib.sha256(block.encode("utf-8")).hexdigest()
            == (body["route_descriptions_sha256"])
        )
        assert (
            block_sha256(state.current_route_block() or "")
            == (body["route_descriptions_sha256"])
        )
