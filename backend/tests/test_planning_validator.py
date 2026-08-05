# Built with Spec4 AI - https://spec4.ai
"""The deterministic plan checker.

This is the module that decides whether a model's plan is allowed to run, so it
is the one place where "the model usually gets it right" is not an argument.
Every rule the capability states is exercised here, including the ones a
well-behaved model would never break -- those are precisely the ones that go
unnoticed when they regress.

The distinction the whole file turns on: a **wrong** plan is rejected and
replanned, a **too big** plan is trimmed in code. Spending a model call to fix a
budget problem would be the wrong instrument.
"""

from __future__ import annotations

from backend.app.planning.schemas import Plan, PlanStep
from backend.app.planning.validator import (
    MAX_RESEARCH_STEPS,
    check_plan,
    trim_plan,
    validate_plan,
)


def _research(index: int, query: str = "a query") -> PlanStep:
    return PlanStep(
        index=index, kind="research", description=f"Research step {index}", search_query=query
    )


def _synthesis(index: int) -> PlanStep:
    return PlanStep(
        index=index, kind="synthesis", description="Compose the itinerary", search_query=None
    )


def _plan(*steps: PlanStep, goal: str = "One day in Lisbon") -> Plan:
    return Plan(goal=goal, steps=list(steps))


class TestAcceptance:
    def test_a_well_formed_plan_passes_untouched(self) -> None:
        plan = _plan(_research(1), _research(2), _synthesis(3))

        check = check_plan(plan)

        assert check.ok
        assert check.errors == []
        assert check.trimmed_note is None
        assert check.plan == plan

    def test_the_minimum_plan_is_one_research_step_plus_synthesis(self) -> None:
        check = check_plan(_plan(_research(1), _synthesis(2)))

        assert check.ok


class TestRejection:
    """Each of these produces errors, which the orchestrator sends to a replan."""

    def test_a_plan_with_no_synthesis_step_is_rejected(self) -> None:
        errors = validate_plan(_plan(_research(1), _research(2)))

        assert any("no `synthesis` step" in error for error in errors)

    def test_a_synthesis_step_that_is_not_last_is_rejected(self) -> None:
        # The executor composes the itinerary from research that has already
        # run. A synthesis step in the middle would compose from nothing.
        errors = validate_plan(_plan(_synthesis(1), _research(2), _research(3)))

        assert any("must be the last step" in error for error in errors)

    def test_two_synthesis_steps_are_rejected(self) -> None:
        errors = validate_plan(_plan(_research(1), _synthesis(2), _synthesis(3)))

        assert any("exactly one" in error for error in errors)

    def test_a_research_step_without_a_query_is_rejected(self) -> None:
        naked = PlanStep(index=1, kind="research", description="Look into it", search_query=None)

        errors = validate_plan(_plan(naked, _synthesis(2)))

        assert any("no `search_query`" in error for error in errors)

    def test_a_research_step_with_a_blank_query_is_rejected(self) -> None:
        # Distinct from None: a whitespace query passes a null check and returns
        # nothing useful from a search engine.
        blank = PlanStep(index=1, kind="research", description="d", search_query="   ")

        errors = validate_plan(_plan(blank, _synthesis(2)))

        assert any("no `search_query`" in error for error in errors)

    def test_a_synthesis_step_carrying_a_query_is_rejected(self) -> None:
        # It runs no search, so a query on it means the planner misunderstood
        # what the step does -- worth a replan rather than silent ignoring.
        querying = PlanStep(
            index=2, kind="synthesis", description="d", search_query="something"
        )

        errors = validate_plan(_plan(_research(1), querying))

        assert any("runs no search" in error for error in errors)

    def test_a_single_step_plan_is_rejected(self) -> None:
        errors = validate_plan(_plan(_synthesis(1)))

        assert any("between 2 and 5" in error for error in errors)

    def test_a_plan_longer_than_the_specification_allows_is_rejected(self) -> None:
        steps = [_research(i) for i in range(1, 6)] + [_synthesis(6)]

        errors = validate_plan(_plan(*steps))

        assert any("between 2 and 5" in error for error in errors)

    def test_an_empty_description_is_rejected(self) -> None:
        # Descriptions are shown to the visitor before the plan runs; a blank
        # one defeats the review the whole pattern is built around.
        mute = PlanStep(index=1, kind="research", description="  ", search_query="q")

        errors = validate_plan(_plan(mute, _synthesis(2)))

        assert any("empty `description`" in error for error in errors)

    def test_an_empty_goal_is_rejected(self) -> None:
        errors = validate_plan(_plan(_research(1), _synthesis(2), goal="   "))

        assert any("`goal` field was empty" in error for error in errors)

    def test_a_rejected_plan_yields_no_executable_plan(self) -> None:
        check = check_plan(_plan(_research(1), _research(2)))

        assert not check.ok
        assert check.plan is None
        assert check.errors

    def test_every_error_names_what_to_do_about_it(self) -> None:
        # These strings are injected into the replan prompt, so an error the
        # model cannot act on wastes the one retry it gets.
        errors = validate_plan(_plan(_synthesis(1), _research(2), _research(3)))

        assert errors
        for error in errors:
            assert len(error) > 40, f"too terse to act on: {error!r}"


class TestTrimming:
    def test_an_oversized_but_valid_plan_is_trimmed_not_rejected(self) -> None:
        # Four research steps is a legal plan this deployment cannot afford.
        # Trimming spends nothing; a replan would spend a model call.
        steps = [_research(i) for i in range(1, 5)] + [_synthesis(5)]

        check = check_plan(_plan(*steps))

        assert check.ok
        assert check.errors == []
        assert check.trimmed_note is not None
        assert check.plan is not None
        assert len(check.plan.steps) == MAX_RESEARCH_STEPS + 1

    def test_trimming_keeps_the_synthesis_step_last(self) -> None:
        steps = [_research(i) for i in range(1, 5)] + [_synthesis(5)]

        trimmed, _ = trim_plan(_plan(*steps))

        assert trimmed.steps[-1].kind == "synthesis"
        assert [step.kind for step in trimmed.steps] == ["research", "research", "synthesis"]

    def test_trimming_renumbers_the_surviving_steps_contiguously(self) -> None:
        # step_index and source_refs both point at these numbers. A gap would
        # leave the itinerary citing a step the visitor never saw run.
        steps = [_research(i) for i in range(1, 5)] + [_synthesis(5)]

        trimmed, _ = trim_plan(_plan(*steps))

        assert [step.index for step in trimmed.steps] == [1, 2, 3]

    def test_trimming_keeps_the_earliest_research_steps(self) -> None:
        # The planner is told to order steps as they will run, so the earlier
        # ones are the ones it treated as foundational.
        steps = [_research(i, query=f"query {i}") for i in range(1, 5)] + [_synthesis(5)]

        trimmed, _ = trim_plan(_plan(*steps))

        assert [step.search_query for step in trimmed.steps[:2]] == ["query 1", "query 2"]

    def test_the_trim_note_says_it_is_a_budget_limit_not_a_pattern_limit(self) -> None:
        # The app's whole teaching claim is that the pattern is unbounded and
        # this demo is not. A note that blamed the pattern would teach the
        # opposite of the truth.
        steps = [_research(i) for i in range(1, 5)] + [_synthesis(5)]

        _, note = trim_plan(_plan(*steps))

        assert note is not None
        assert "not of the planning-agent pattern" in note

    def test_a_plan_within_budget_is_returned_unchanged_with_no_note(self) -> None:
        plan = _plan(_research(1), _research(2), _synthesis(3))

        trimmed, note = trim_plan(plan)

        assert trimmed == plan
        assert note is None
