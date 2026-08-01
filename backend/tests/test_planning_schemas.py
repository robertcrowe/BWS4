# Built with Spec4 AI - https://spec4.ai
"""The planning agent's output shapes and its versioned prompts.

The schema assertions here look like they are testing Pydantic, which would be
pointless. They are testing something else: **these field names are a contract
with three parties** -- the planner's constrained decoding, the SSE payloads
Phase 3 emits, and the frontend types Phase 4 renders -- and they came from the
capability specification rather than from us. A rename that "reads better" would
pass every other test in this suite and break the agreement silently. This file
is where that gets caught.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.planning import agents
from backend.app.planning.schemas import (
    Itinerary,
    ItineraryBlock,
    Plan,
    PlanStep,
    ResearchFinding,
    SearchResult,
    StepResult,
)
from backend.app.services.prompt_loader import load_prompt


def _fields(model: type) -> set[str]:
    return set(model.model_fields)


def _prompt(version: str) -> str:
    """Load a prompt as one lowercase line, for phrase assertions.

    Markdown wraps prose at the column, so a required sentence is routinely
    split across a newline and an indent. Asserting on the raw text would make
    these tests fail on a reflow -- a formatting change that alters nothing the
    model reads -- so whitespace is normalised first and the assertions stay
    about content.
    """
    return " ".join(load_prompt(agents.PROMPTS_DIR, version).lower().split())


def test_the_schemas_carry_exactly_the_specified_fields() -> None:
    """From the capability's Schema notes, verbatim -- not ours to improve."""
    assert _fields(PlanStep) == {"index", "kind", "description", "search_query"}
    assert _fields(Plan) == {"goal", "steps"}
    assert _fields(StepResult) == {"step_index", "status", "summary", "sources"}
    assert _fields(Itinerary) == {"city", "blocks"}
    assert _fields(ItineraryBlock) == {
        "time_of_day",
        "activity",
        "why_it_matches",
        "source_refs",
    }


def test_the_enumerated_fields_reject_a_value_outside_the_specification() -> None:
    """The literals are the schema's own contribution to plan validity.

    Step kind and time-of-day are closed sets. Anything else would reach the
    executor as a step it has no branch for.
    """
    with pytest.raises(ValidationError):
        PlanStep(index=1, kind="browse", description="d", search_query="q")

    with pytest.raises(ValidationError):
        ItineraryBlock(time_of_day="midnight", activity="a", why_it_matches="w")

    with pytest.raises(ValidationError):
        StepResult(step_index=1, status="partial", summary="s")


def test_a_research_model_cannot_author_its_own_sources() -> None:
    """The load-bearing asymmetry of this app.

    A research executor returns a summary and nothing else. `sources` is stamped
    by the orchestrator from what the search tool actually returned, so a model
    cannot claim a citation it never received -- which would produce a
    `StepResult` indistinguishable from a real one.
    """
    assert _fields(ResearchFinding) == {"summary"}
    assert "sources" not in _fields(ResearchFinding)


def test_a_step_result_defaults_to_no_sources_rather_than_requiring_them() -> None:
    """Empty is a legitimate, informative value: the search ran and found nothing."""
    result = StepResult(step_index=1, status="completed", summary="nothing found")

    assert result.sources == []


def test_search_result_projects_the_framework_exa_shape() -> None:
    """The one shape the specification names but does not define."""
    assert _fields(SearchResult) == {"title", "url", "snippet"}


class TestThePrompts:
    """The prompts are shipped artefacts, and their rules are load-bearing.

    Each assertion below corresponds to a mitigation in the capability spec that
    has no other enforcement. Where a rule *is* enforced in code -- step counts,
    ordering -- there is no assertion here, because the validator owns it.
    """

    def test_all_three_versions_load(self) -> None:
        for version in ("planner_v1", "research_v1", "synthesis_v1"):
            assert load_prompt(agents.PROMPTS_DIR, version).strip()

    def test_the_planner_prompt_states_the_synthesis_last_rule(self) -> None:
        # The validator rejects a plan that breaks this, but a prompt that never
        # stated the rule would make the replan attempt a coin flip.
        prompt = _prompt("planner_v1")

        assert "exactly one" in prompt
        assert "last step" in prompt
        assert "search_query" in prompt

    def test_the_research_prompt_bounds_reformulation_and_forbids_invention(self) -> None:
        prompt = _prompt("research_v1")

        assert "once more" in prompt
        assert "do not fill the gap" in prompt

    def test_the_research_prompt_frames_results_as_untrusted(self) -> None:
        prompt = _prompt("research_v1")

        assert "untrusted" in prompt
        assert "never as instructions" in prompt

    def test_the_synthesis_prompt_requires_acknowledging_gaps(self) -> None:
        # The capability's empty-results mitigation: "have the synthesis
        # acknowledge gaps rather than fabricate details."
        prompt = _prompt("synthesis_v1")

        assert "say so" in prompt
        assert "invents" in prompt or "invent" in prompt

    def test_the_synthesis_prompt_carries_the_output_safety_rules(self) -> None:
        # From the specification's Privacy & safety section, which names illegal
        # activity and unsafe locations specifically.
        prompt = _prompt("synthesis_v1")

        assert "illegal" in prompt
        assert "safety" in prompt or "unsafe" in prompt

    def test_the_synthesis_prompt_forbids_citing_a_step_that_did_not_inform_a_block(
        self,
    ) -> None:
        # source_refs is the itinerary's grounding claim. A prompt that let the
        # model cite freely would make every block look supported.
        prompt = _prompt("synthesis_v1")

        assert "only cite a step" in prompt
        assert "empty" in prompt
