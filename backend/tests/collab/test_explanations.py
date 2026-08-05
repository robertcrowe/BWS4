# Built with Spec4 AI - https://spec4.ai
"""The two post-award explanations: the gate, the checks, and the fallback.

What this file is really guarding is **post-hoc rationalisation** — a model
asserting a concession was forced by a constraint that was not actually
binding. That falsehood is invisible without recomputing slack, the narrative
shape is entirely plausible, and it arrives last, framed as the explanation of
everything before it. So the checks are tested against deliberately wrong model
output rather than against happy paths.

Every test here substitutes `run_agent_step` at its point of use in
`explanations`, which is both the no-live-calls boundary and the seam for
driving a *specific* wrong answer.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from backend.app.collab import explanations, opacity, runtime
from backend.app.collab.counterfactual import compute_counterfactual
from backend.app.collab.explain_schemas import (
    AxisExplanation,
    PartyReveal,
    RevealExplanation,
    SensitivityExplanation,
    build_sensitivity_model,
)
from backend.app.collab.explain_templates import render_reveal, render_sensitivity
from backend.app.collab.explain_validator import (
    computed_stance,
    constraint_is_binding,
    no_invented_numbers,
    overclaiming_phrases,
)
from backend.app.collab.runtime import RunBudget
from backend.app.collab.scenarios import SCENARIOS_BY_ID, WEIGHTINGS_BY_ID, AxisId
from backend.app.collab.schemas import Award, Bid
from backend.app.collab.scoring import to_scored_bid
from backend.app.services.agent_runtime import StepResult

SCENARIO = SCENARIOS_BY_ID["refurbished_laptops_school"]
WEIGHTING = WEIGHTINGS_BY_ID["balanced"]
SELLERS = sorted(opacity.SELLER_IDS_SET)


def _bid(seller: str, price: float, qty: float, days: float, warranty: float) -> Bid:
    return Bid(
        seller_id=seller,
        unit_price=price,
        quantity=qty,
        delivery_days=days,
        warranty_months=warranty,
        notes=f"{seller} says something",
    )


# Northwind's sealed laptops position: floor 356, capacity 180, 14 days, 12 mo.
# Meridian's: floor 402, capacity 300, 25 days, 36 mo.
OPENING = [
    _bid("northwind", 380, 180, 16, 12),
    _bid("meridian", 430, 240, 28, 30),
]
FINAL = [
    # Northwind concedes to its floor on price and to its capability on delivery.
    _bid("northwind", 356, 180, 14, 12),
    _bid("meridian", 410, 240, 25, 30),
]
AWARD = Award(
    winner_id="northwind", rationale="Cheapest.", priority_references=["price"]
)


def _facts() -> Any:
    return explanations._facts_for_run(SCENARIO, OPENING, FINAL)


class TestTheAwardGate:
    def test_no_explanation_may_run_before_the_award_is_recorded(self) -> None:
        """The reveal payload *is* the sealed material. This is the single worst
        failure the example could have, so it raises rather than returning
        empty."""
        with pytest.raises(explanations.AwardNotRecordedError):
            asyncio.run(
                explanations.explain_run(
                    scenario=SCENARIO,
                    weighting=WEIGHTING,
                    award=None,
                    opening_bids=OPENING,
                    final_bids=FINAL,
                    counterfactual=None,
                    budget=RunBudget(),
                    run_id="run-1",
                )
            )

    def test_the_gate_is_server_side_on_the_record(self) -> None:
        """Not a flag a caller passes: the check is on `award`, which only the
        completed run can supply. A client-side gate would be no gate."""
        import inspect

        source = inspect.getsource(explanations.explain_run)
        assert "if award is None" in source
        assert "AwardNotRecordedError" in source


class TestTheDeterministicTemplates:
    def test_the_reveal_template_covers_every_party_and_every_axis(self) -> None:
        """It has to cover 100% of the shape, because it is what renders when
        the model's answer does not survive checking."""
        template = render_reveal(SCENARIO, _facts())

        assert {block.party_id for block in template.parties} == set(SELLERS)
        for block in template.parties:
            assert block.headline
            assert {entry.axis for entry in block.axes} == {a.value for a in AxisId}
            for entry in block.axes:
                assert entry.explanation
                assert entry.stance in {"conceded", "held_firm"}

    def test_the_template_invents_no_numbers(self) -> None:
        template = render_reveal(SCENARIO, _facts())
        allowed = explanations._allowed_numbers(_facts())

        for block in template.parties:
            for entry in block.axes:
                assert no_invented_numbers(entry.explanation, allowed) == set()

    def test_the_sensitivity_template_is_complete_and_carries_the_caveat(self) -> None:
        counterfactual = compute_counterfactual(
            SCENARIO, WEIGHTING, [to_scored_bid(bid) for bid in FINAL]
        )
        assert counterfactual is not None

        template = render_sensitivity(counterfactual)

        assert template.likely_winner
        assert template.decisive_dimensions
        assert template.narration
        assert template.confidence
        assert "projection" in template.caveat.lower()

    def test_the_template_never_overclaims(self) -> None:
        """Only a real re-run settles it, and the template must say so as
        carefully as the model is told to."""
        counterfactual = compute_counterfactual(
            SCENARIO, WEIGHTING, [to_scored_bid(bid) for bid in FINAL]
        )
        assert counterfactual is not None

        template = render_sensitivity(counterfactual)

        assert overclaiming_phrases(template.narration) == []


class TestTheRecomputedFacts:
    def test_stance_is_recomputed_from_the_bid_delta_not_claimed(self) -> None:
        # Price is lower-is-better: 380 -> 356 is a concession.
        assert computed_stance(SCENARIO, AxisId.PRICE, 380, 356).value == "conceded"
        # Warranty is higher-is-better: 12 -> 12 held firm.
        assert computed_stance(SCENARIO, AxisId.WARRANTY, 12, 12).value == "held_firm"
        # And a *higher* price is not a concession, however it is described.
        assert computed_stance(SCENARIO, AxisId.PRICE, 356, 380).value == "held_firm"

    def test_a_constraint_is_binding_only_when_the_bid_sits_against_it(self) -> None:
        # Northwind finished at its 356 floor.
        assert constraint_is_binding(SCENARIO, AxisId.PRICE, 356, 356)
        # Meridian finished at 410 with a floor of 402: clear of it.
        assert not constraint_is_binding(SCENARIO, AxisId.PRICE, 440, 402)


class TestTheChecksCatchRationalisation:
    def _run_reveal(
        self, produced: RevealExplanation, budget: RunBudget | None = None
    ) -> Any:
        calls: list[str] = []

        async def _step(**kwargs: Any) -> StepResult[RevealExplanation]:
            calls.append(str(kwargs.get("user_prompt", "")))
            return StepResult(output=produced, model="fake/model")

        with patch.object(explanations, "run_agent_step", _step):
            result = asyncio.run(
                explanations.explain_reveal(
                    scenario=SCENARIO,
                    weighting=WEIGHTING,
                    award=AWARD,
                    facts_by_party=_facts(),
                    notes={},
                    budget=budget or RunBudget(),
                    run_id="run-1",
                )
            )
        return result, calls

    def _block(self, **overrides: Any) -> RevealExplanation:
        """A northwind block that is correct unless an override breaks it."""
        facts = _facts()["northwind"]
        axes = [
            AxisExplanation(
                axis=axis.value,
                stance=facts[axis].stance.value,
                opening_value=facts[axis].opening,
                final_value=facts[axis].final,
                binding_constraint=facts[axis].binding,
                explanation="It did what it did.",
            )
            for axis in AxisId
        ]
        for index, entry in enumerate(axes):
            if entry.axis in overrides:
                axes[index] = entry.model_copy(update=overrides[entry.axis])

        meridian_facts = _facts()["meridian"]
        return RevealExplanation(
            parties=[
                PartyReveal(
                    party_id="northwind", headline="Held its floor.", axes=axes
                ),
                PartyReveal(
                    party_id="meridian",
                    headline="Had room.",
                    axes=[
                        AxisExplanation(
                            axis=axis.value,
                            stance=meridian_facts[axis].stance.value,
                            opening_value=meridian_facts[axis].opening,
                            final_value=meridian_facts[axis].final,
                            binding_constraint=meridian_facts[axis].binding,
                            explanation="It did what it did.",
                        )
                        for axis in AxisId
                    ],
                ),
            ]
        )

    def test_a_correct_reveal_is_kept_as_written(self) -> None:
        result, calls = self._run_reveal(self._block())

        assert result.fallback is False
        assert result.violations == []
        assert len(calls) == 1

    def test_a_stance_contradicting_the_bid_delta_repairs_then_falls_back(self) -> None:
        """The signature failure. Northwind cut its price; claiming it held firm
        is checkable and is checked."""
        result, calls = self._run_reveal(self._block(price={"stance": "held_firm"}))

        assert len(calls) == 2, "one repair attempt, and only one"
        # The repair names the *specific* violation with the actual numbers,
        # rather than saying something generic the model has to guess at.
        assert "held_firm on price" in calls[1]
        assert "380.0 to 356.0" in calls[1]
        assert "conceded" in calls[1]
        assert result.fallback is True
        assert "stance_mismatch" in result.violations

    def test_an_invented_number_repairs_then_falls_back(self) -> None:
        result, _ = self._run_reveal(
            self._block(price={"explanation": "It came down by about 6.3 per cent."})
        )

        assert result.fallback is True
        assert "invented_number" in result.violations

    def test_a_constraint_cited_with_slack_is_rejected(self) -> None:
        """ "Held firm because of my cost floor" when the bid is well clear of
        the floor is the rationalisation this panel exists to catch."""
        result, _ = self._run_reveal(
            self._block(warranty={"binding_constraint": "cost_floor"})
        )

        assert result.fallback is True
        assert (
            "constraint_not_binding" in result.violations
            or "stance_mismatch" in result.violations
        )

    def test_a_block_naming_the_rival_is_rejected(self) -> None:
        produced = self._block()
        produced.parties[0].headline = "It beat meridian on price."

        result, _ = self._run_reveal(produced)

        assert result.fallback is True
        assert "rival_mentioned" in result.violations

    def test_the_fallback_still_renders_a_complete_panel(self) -> None:
        """Never blank, never spinning. The visitor has waited through six
        stages by this point."""
        result, _ = self._run_reveal(self._block(price={"stance": "held_firm"}))

        assert result.fallback is True
        assert len(result.payload["parties"]) == 2
        for block in result.payload["parties"]:
            assert block["headline"]
            assert len(block["axes"]) == len(AxisId)


class TestTheSensitivityIsNarratedNotDerived:
    def _counterfactual(self) -> Any:
        return compute_counterfactual(
            SCENARIO, WEIGHTING, [to_scored_bid(bid) for bid in FINAL]
        )

    def _run(self, produced: SensitivityExplanation) -> Any:
        calls: list[str] = []

        async def _step(**kwargs: Any) -> StepResult[SensitivityExplanation]:
            calls.append(str(kwargs.get("user_prompt", "")))
            return StepResult(output=produced, model="fake/model")

        with patch.object(explanations, "run_agent_step", _step):
            result = asyncio.run(
                explanations.explain_sensitivity(
                    counterfactual=self._counterfactual(),
                    scenario=SCENARIO,
                    budget=RunBudget(),
                    run_id="run-1",
                )
            )
        return result, calls

    def _good(self) -> SensitivityExplanation:
        counterfactual = self._counterfactual()
        assert counterfactual is not None
        template = render_sensitivity(counterfactual)
        return template

    def test_the_computed_result_is_handed_to_the_prompt_as_a_fact(self) -> None:
        _, calls = self._run(self._good())

        assert "already been computed" in calls[0]
        assert "do not re-derive" in calls[0].lower()

    def test_a_narration_contradicting_the_computation_is_rejected(self) -> None:
        counterfactual = self._counterfactual()
        assert counterfactual is not None
        wrong = self._good().model_copy(
            update={
                "likely_winner": (
                    "northwind"
                    if counterfactual.alternative_winner != "northwind"
                    else "meridian"
                )
            }
        )

        result, _ = self._run(wrong)

        assert result.fallback is True
        assert "contradicts_computation" in result.violations

    def test_overclaiming_prose_is_rejected(self) -> None:
        result, _ = self._run(
            self._good().model_copy(
                update={"narration": "Meridian would have won, definitely."}
            )
        )

        assert result.fallback is True
        assert "overclaims" in result.violations

    def test_the_schema_makes_an_off_roster_supplier_unrepresentable(self) -> None:
        """Structural, not merely validated: the model has no way to name one."""
        import pydantic

        model = build_sensitivity_model(
            seller_ids=SELLERS, axis_ids=[a.id.value for a in SCENARIO.axes]
        )
        with pytest.raises(pydantic.ValidationError):
            model(
                likely_winner="acme_supplies",
                decisive_dimensions=["price"],
                narration="x",
                confidence="low",
                caveat="y",
            )
        with pytest.raises(pydantic.ValidationError):
            model(
                likely_winner=SELLERS[0],
                decisive_dimensions=["colour"],
                narration="x",
                confidence="low",
                caveat="y",
            )

    def test_too_close_is_a_first_class_outcome(self) -> None:
        model = build_sensitivity_model(
            seller_ids=SELLERS, axis_ids=[a.id.value for a in SCENARIO.axes]
        )
        built = model(
            likely_winner="too_close",
            decisive_dimensions=[],
            narration="The projection does not separate them.",
            confidence="low",
            caveat="A projection, not a re-run.",
        )
        assert built.likely_winner == "too_close"


class TestBothRunConcurrentlyAndIndependently:
    def test_one_failing_still_delivers_the_other(self) -> None:
        """These are the run's last two calls. A failure in one must not take
        the other down with it."""
        counterfactual = compute_counterfactual(
            SCENARIO, WEIGHTING, [to_scored_bid(bid) for bid in FINAL]
        )

        assert counterfactual is not None

        assert counterfactual is not None

        async def _step(**kwargs: Any) -> StepResult[Any]:
            if "reveal" in str(kwargs.get("label", "")):
                raise RuntimeError("the reveal call broke")
            return StepResult(
                output=render_sensitivity(counterfactual), model="fake/model"
            )

        with patch.object(explanations, "run_agent_step", _step):
            reveal, sensitivity = asyncio.run(
                explanations.explain_run(
                    scenario=SCENARIO,
                    weighting=WEIGHTING,
                    award=AWARD,
                    opening_bids=OPENING,
                    final_bids=FINAL,
                    counterfactual=counterfactual,
                    budget=RunBudget(),
                    run_id="run-1",
                )
            )

        # The reveal degraded to its template rather than vanishing...
        assert reveal is not None
        assert reveal.fallback is True
        # ...and the sensitivity call was unaffected.
        assert sensitivity is not None
        assert sensitivity.fallback is False

    def test_they_overlap_in_time(self) -> None:
        """Sequential dispatch leaves every other assertion true while doubling
        the wait at the worst moment in the run."""
        counterfactual = compute_counterfactual(
            SCENARIO, WEIGHTING, [to_scored_bid(bid) for bid in FINAL]
        )
        windows: dict[str, tuple[float, float]] = {}

        assert counterfactual is not None

        async def _step(**kwargs: Any) -> StepResult[Any]:
            label = "reveal" if "reveal" in str(kwargs.get("label", "")) else "sens"
            start = asyncio.get_running_loop().time()
            await asyncio.sleep(0.05)
            windows[label] = (start, asyncio.get_running_loop().time())
            if label == "reveal":
                raise RuntimeError("degrade to template; timing is the point")
            return StepResult(
                output=render_sensitivity(counterfactual), model="fake/model"
            )

        with patch.object(explanations, "run_agent_step", _step):
            asyncio.run(
                explanations.explain_run(
                    scenario=SCENARIO,
                    weighting=WEIGHTING,
                    award=AWARD,
                    opening_bids=OPENING,
                    final_bids=FINAL,
                    counterfactual=counterfactual,
                    budget=RunBudget(),
                    run_id="run-1",
                )
            )

        first, second = windows["reveal"], windows["sens"]
        assert first[0] < second[1] and second[0] < first[1], "they did not overlap"


class TestTheBudget:
    def test_the_two_calls_come_out_of_the_reservation_already_held(self) -> None:
        """No new reservation and no per-call allowance check: the hold covers
        eight precisely so these cannot be refused mid-run."""
        import inspect

        source = inspect.getsource(explanations)
        assert "reserve_capability" not in source
        assert "allowance_holds" not in source

    def test_a_run_that_already_spent_its_ceiling_falls_back_rather_than_raising(
        self,
    ) -> None:
        """Six negotiation calls plus a repair leaves less than two spare. The
        panels degrade; they do not take the page down."""
        counterfactual = compute_counterfactual(
            SCENARIO, WEIGHTING, [to_scored_bid(bid) for bid in FINAL]
        )
        # Derived, not literal: the point is a budget with nothing left, and a
        # hardcoded 8 stopped meaning that the moment the ceiling was padded.
        spent = RunBudget(used=runtime.MAX_PROVIDER_REQUESTS)

        reveal, sensitivity = asyncio.run(
            explanations.explain_run(
                scenario=SCENARIO,
                weighting=WEIGHTING,
                award=AWARD,
                opening_bids=OPENING,
                final_bids=FINAL,
                counterfactual=counterfactual,
                budget=spent,
                run_id="run-1",
            )
        )

        assert reveal is not None and reveal.fallback is True
        assert sensitivity is not None and sensitivity.fallback is True
        assert spent.used == runtime.MAX_PROVIDER_REQUESTS, (
            "nothing was spent past the ceiling"
        )


class TestThePanelsAreProducedOncePerRun:
    def test_a_completed_run_asks_for_each_explanation_exactly_once(self) -> None:
        """ "Re-requesting a panel spends no additional call" holds by
        construction: the payloads are produced once during the run, persisted
        to `negotiation_runs`, and cached client-side. There is deliberately no
        endpoint to re-request one, so there is no path that could spend a
        second call — and this asserts the "once" half of that.
        """
        counterfactual = compute_counterfactual(
            SCENARIO, WEIGHTING, [to_scored_bid(bid) for bid in FINAL]
        )
        labels: list[str] = []

        assert counterfactual is not None

        async def _step(**kwargs: Any) -> StepResult[Any]:
            label = str(kwargs.get("label", ""))
            labels.append(label)
            if "reveal" in label:
                raise RuntimeError("degrade; the count is what matters")
            return StepResult(
                output=render_sensitivity(counterfactual), model="fake/model"
            )

        with patch.object(explanations, "run_agent_step", _step):
            asyncio.run(
                explanations.explain_run(
                    scenario=SCENARIO,
                    weighting=WEIGHTING,
                    award=AWARD,
                    opening_bids=OPENING,
                    final_bids=FINAL,
                    counterfactual=counterfactual,
                    budget=RunBudget(),
                    run_id="run-1",
                )
            )

        assert sum("reveal" in label for label in labels) == 1
        assert sum("sensitivity" in label for label in labels) == 1

    def test_the_slice_exposes_no_endpoint_to_re_request_a_panel(self) -> None:
        """A re-request route would be a second way to spend the budget, and
        the budget was reserved once before the RFQ."""
        import inspect

        from backend.app.api import collab as collab_api

        source = inspect.getsource(collab_api)
        for path in ('"/reveal"', '"/sensitivity"', '"/explain"'):
            assert path not in source
