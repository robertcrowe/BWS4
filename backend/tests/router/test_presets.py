# Built with Spec4 AI - https://spec4.ai
"""The Router preset catalogue and the endpoint that publishes it.

The catalogue stores requests only, never answers -- asserted structurally by
walking the dataclass fields and the serialised payload, because the failure
mode is a well-meant convenience field, not a deliberate one. The curation
rules (exact route ids, both control/near-miss pairs) are asserted too, since a
preset edited without them would weaken the agreement history silently.
"""

from __future__ import annotations

import dataclasses
import json

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.router.constants import (
    DECISION_MARGIN,
    DETERMINISTIC_EVALUATOR,
    RETRIEVAL,
    ROUTE_COST_ORDER,
    SEARCH_GENERATION,
    SINGLE_CALL,
)
from backend.app.router.presets import (
    PRESET_IDS,
    PRESETS,
    PairMembership,
    PairName,
    PairRole,
    RouterPreset,
    get_preset,
)
from backend.app.router.schemas import public_presets
from backend.app.router.state import RouteDescriptions

client = TestClient(app)


def _pairing(preset_id: str) -> PairMembership | None:
    preset = get_preset(preset_id)
    assert preset is not None
    return preset.pairing


#: Any field name containing one of these is somewhere an answer could be parked.
_ANSWER_WORDS = ("answer", "solution", "result", "expected_value", "response")


class TestRouteIds:
    def test_route_ids_are_spelled_exactly(self) -> None:
        assert DETERMINISTIC_EVALUATOR == "deterministic_evaluator"
        assert SINGLE_CALL == "single_call"
        assert RETRIEVAL == "retrieval"
        assert SEARCH_GENERATION == "search_generation"

    def test_cost_order_is_cheapest_first(self) -> None:
        assert ROUTE_COST_ORDER == (
            "deterministic_evaluator",
            "single_call",
            "retrieval",
            "search_generation",
        )


class TestTheCatalogue:
    def test_there_are_exactly_six_presets(self) -> None:
        assert len(PRESETS) == 6

    def test_ids_are_p1_through_p6_and_distinct(self) -> None:
        assert [preset.id for preset in PRESETS] == [f"p{i}" for i in range(1, 7)]
        assert len(PRESET_IDS) == 6

    def test_expected_routes_use_the_route_ids(self) -> None:
        expected = {
            "p1": "deterministic_evaluator",
            "p2": "single_call",
            "p3": "retrieval",
            "p4": "search_generation",
            "p5": "search_generation",
            "p6": "single_call",
        }
        assert {p.id: p.expected_route for p in PRESETS} == expected
        for preset in PRESETS:
            assert preset.expected_route in ROUTE_COST_ORDER

    def test_request_texts_are_verbatim(self) -> None:
        assert [p.request for p in PRESETS] == [
            "Convert 72 km/h to metres per second.",
            'Rewrite "hey, can u send me the report asap" so it sounds professional.',
            "How long did Apollo 11 spend on the lunar surface, and who stayed "
            "in orbit?",
            "Who won the most recent Formula 1 race?",
            "When is the next crewed launch to the International Space Station?",
            "Explain why 1 mile is about 1.609 kilometres.",
        ]

    def test_every_preset_has_a_one_line_reason(self) -> None:
        for preset in PRESETS:
            assert preset.reason.strip()
            assert "\n" not in preset.reason

    def test_conversion_pair_is_p1_control_and_p6_near_miss(self) -> None:
        assert _pairing("p1") == PairMembership(PairName.CONVERSION, PairRole.CONTROL)
        assert _pairing("p6") == PairMembership(PairName.CONVERSION, PairRole.NEAR_MISS)

    def test_space_pair_is_p3_control_and_p5_near_miss(self) -> None:
        assert _pairing("p3") == PairMembership(PairName.SPACE, PairRole.CONTROL)
        assert _pairing("p5") == PairMembership(PairName.SPACE, PairRole.NEAR_MISS)

    def test_each_pair_splits_across_two_routes(self) -> None:
        """A pair only teaches anything if its two members belong apart."""
        for name in PairName:
            members = [p for p in PRESETS if p.pairing and p.pairing.pair is name]
            assert len(members) == 2
            assert {m.pairing.role for m in members if m.pairing} == set(PairRole)
            assert members[0].expected_route != members[1].expected_route

    def test_unknown_id_is_none(self) -> None:
        assert get_preset("p7") is None


class TestNoAnswersAreStored:
    def test_no_dataclass_field_is_named_for_an_answer(self) -> None:
        names = [field.name for field in dataclasses.fields(RouterPreset)]
        for name in names:
            for word in _ANSWER_WORDS:
                assert word not in name.lower(), f"{name} could hold an answer"

    def test_no_published_field_is_named_for_an_answer(
        self, route_descriptions: RouteDescriptions
    ) -> None:
        payload = json.loads(public_presets(route_descriptions).model_dump_json())
        for preset in payload["presets"]:
            for key in preset:
                for word in _ANSWER_WORDS:
                    assert word not in key.lower(), f"{key} is published"


class TestPresetsEndpoint:
    def test_returns_200_with_six_presets_margin_and_cost_order(self) -> None:
        response = client.get("/api/router/presets")

        assert response.status_code == 200
        body = response.json()
        assert len(body["presets"]) == 6
        assert body["decision_margin"] == DECISION_MARGIN
        assert body["cost_order"] == list(ROUTE_COST_ORDER)

    def test_each_preset_carries_id_request_expected_route_and_reason(self) -> None:
        body = client.get("/api/router/presets").json()

        for wire, preset in zip(body["presets"], PRESETS, strict=True):
            assert wire["id"] == preset.id
            assert wire["request"] == preset.request
            assert wire["expected_route"] == preset.expected_route
            assert wire["reason"] == preset.reason
