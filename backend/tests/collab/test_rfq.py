# Built with Spec4 AI - https://spec4.ai
"""The RFQ composer: deterministic, free, and blind to the buyer's position.

Three properties, and the third is the one that would be a real defect. The
buyer's ceiling and BATNA live on the `Scenario` this function is handed, so
"does not leak them" is a claim about the code rather than about the type --
and a seller that knew the ceiling would price straight to it.
"""

from __future__ import annotations

import inspect

import pytest

from backend.app.collab import rfq as rfq_module
from backend.app.collab.rfq import compose_rfq
from backend.app.collab.scenarios import (
    PRIORITY_WEIGHTINGS,
    SCENARIOS,
    AxisId,
)

SCENARIO_IDS = [s.id for s in SCENARIOS]
WEIGHTING_IDS = [w.id for w in PRIORITY_WEIGHTINGS]


def _scenario(scenario_id: str):
    return next(s for s in SCENARIOS if s.id == scenario_id)


def _weighting(weighting_id: str):
    return next(w for w in PRIORITY_WEIGHTINGS if w.id == weighting_id)


class TestItIsDeterministic:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    @pytest.mark.parametrize("weighting_id", WEIGHTING_IDS)
    def test_the_same_inputs_produce_an_identical_request(
        self, scenario_id: str, weighting_id: str
    ) -> None:
        scenario, weighting = _scenario(scenario_id), _weighting(weighting_id)

        first = compose_rfq(scenario, weighting)
        second = compose_rfq(scenario, weighting)

        assert first == second
        assert first.text == second.text
        assert first.as_payload() == second.as_payload()

    def test_different_weightings_produce_different_requests(self) -> None:
        """Determinism must not mean insensitivity: the stated priorities are
        published to the sellers, so changing them has to change the ask."""
        scenario = SCENARIOS[0]

        cheap = compose_rfq(scenario, _weighting("lowest_price"))
        fast = compose_rfq(scenario, _weighting("fastest_delivery"))

        assert cheap.text != fast.text

    def test_the_composed_text_carries_no_timestamp_or_identifier(self) -> None:
        """A clock or a uuid in the output would make it non-reproducible while
        every equality test above still passed within one process."""
        source = inspect.getsource(rfq_module)

        for forbidden in ("datetime", "uuid", "random", "time."):
            assert forbidden not in source, f"{forbidden} would break determinism"


class TestItConsumesNoModelCall:
    def test_the_module_reaches_no_provider(self) -> None:
        """Parsed from the imports rather than grepped from the prose -- the
        word "model" appears in this module's docstring on purpose."""
        import ast

        tree = ast.parse(inspect.getsource(rfq_module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        forbidden = ("pydantic_ai", "litellm", "httpx", "openai")
        for module in imported:
            assert not module.startswith(forbidden), f"{module} reaches a provider"

    def test_composing_touches_no_database_session(self) -> None:
        """It takes no session, so there is nothing to stub -- which is the
        point: stage 1 is free and offline."""
        params = set(inspect.signature(compose_rfq).parameters)
        assert params == {"scenario", "weighting"}


class TestItNeverCarriesTheBuyersSealedPosition:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    @pytest.mark.parametrize("weighting_id", WEIGHTING_IDS)
    def test_the_batna_appears_nowhere_in_the_request(
        self, scenario_id: str, weighting_id: str
    ) -> None:
        scenario = _scenario(scenario_id)
        request = compose_rfq(scenario, _weighting(weighting_id))

        rendered = request.text + repr(request.as_payload())
        assert scenario.buyer_position.batna not in rendered
        assert scenario.buyer_position.reveal_headline not in rendered
        assert scenario.buyer_position.explanation_seed not in rendered

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_the_budget_ceiling_appears_nowhere_in_the_request(
        self, scenario_id: str
    ) -> None:
        from backend.app.collab.opacity import value_appears

        scenario = _scenario(scenario_id)
        request = compose_rfq(scenario, PRIORITY_WEIGHTINGS[0])

        ceiling = str(int(scenario.buyer_position.budget_ceiling))
        assert not value_appears(ceiling, request.text)

    def test_it_builds_from_an_allowlist_rather_than_serialising_the_scenario(
        self,
    ) -> None:
        """An allowlist fails closed when a sealed field is added later; a
        denylist fails open. Asserted structurally: nothing here reads
        `buyer_position`."""
        source = inspect.getsource(rfq_module)
        assert "buyer_position" not in source.split('"""')[-1]


class TestWhatTheRequestDoesSay:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_it_states_all_four_axes_with_their_weights(self, scenario_id: str) -> None:
        scenario = _scenario(scenario_id)
        weighting = _weighting("balanced")

        request = compose_rfq(scenario, weighting)

        assert {term.axis for term in request.terms} == set(AxisId)
        for term in request.terms:
            assert term.weight == weighting.weights[term.axis]
            assert term.label in request.text

    def test_it_tells_a_seller_it_will_never_see_the_rival(self) -> None:
        """Instruction is not the enforcement -- the bus is -- but a seller
        that is told plainly does not waste a turn asking."""
        request = compose_rfq(SCENARIOS[0], PRIORITY_WEIGHTINGS[0])

        assert "will not be shown" in request.text

    def test_both_sellers_would_receive_a_byte_identical_request(self) -> None:
        """Any difference between the two bids has to come from the sellers'
        own sealed constraints, not from having been asked different things."""
        request = compose_rfq(SCENARIOS[0], PRIORITY_WEIGHTINGS[0])
        again = compose_rfq(SCENARIOS[0], PRIORITY_WEIGHTINGS[0])

        assert request.text == again.text
