# Built with Spec4 AI - https://spec4.ai
"""The typed per-cycle step: the union, the cycle-1 constraint, the re-ask.

Three properties carry this file, and each guards a specific failure the
capability names.

**The union rejects a malformed action.** The backend branches on `kind` and
hands `query` to Exa unmodified, so a hallucinated shape or a prose action would
break the run rather than degrade it. There is no regex anywhere in the path,
and that is only safe because the shape is enforced.

**Cycle 1 structurally cannot answer.** The highest-likelihood failure is the
model answering from memory on the first cycle, leaving a trace where no
observation did any work. The mitigation is a *type*, not a sentence in the
prompt -- asking a model not to answer is a request, and not offering it the
answer variant is a fact. The test asserts the output type cannot express an
answer, which is a stronger claim than "the model did not answer this time".

**A malformed step is re-asked exactly once.** One re-ask with the validation
error appended; a second failure returns the disclosed-failure result rather
than raising, because the caller's response is to end the run candidly with the
malformed step visible, not to report a crash.

No model is called: `agent_runtime.run_typed_step` is patched at its point of
use, the same convention every other slice's tests follow.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from backend.app.react import schemas, service
from backend.app.services import agent_runtime


def _run(**kwargs: Any) -> service.CycleOutcome:
    """Drive one cycle step to completion."""
    params: dict[str, Any] = {"question": "who won?", "observations": [], "cycle": 1}
    params.update(kwargs)
    return asyncio.run(service.run_cycle_step(**params))


def _observation(index: int = 1) -> schemas.Observation:
    """One ordinary observation, so the answer branch becomes available."""
    return schemas.Observation(
        index=index,
        query="a query",
        results=[
            schemas.ObservationResult(
                idx=1, title="A page", url="https://example.org", snippet="A fact."
            )
        ],
        is_empty=False,
        status="ok",
    )


def _step_returning(output: Any, requests: int = 1) -> Any:
    """Patch the lane to return one canned typed output."""

    async def fake(**_kwargs: Any) -> agent_runtime.StepResult[Any]:
        return agent_runtime.StepResult(
            output=output, model="fake/model", requests=requests
        )

    return patch.object(agent_runtime, "run_typed_step", fake)


def _step_failing(*failures: Exception) -> tuple[Any, list[dict[str, Any]]]:
    """Patch the lane to raise each failure in turn, then succeed.

    Records the prompts it was given, so a test can assert the re-ask carried
    the validation error rather than repeating the first ask verbatim.
    """
    calls: list[dict[str, Any]] = []
    remaining = list(failures)

    async def fake(**kwargs: Any) -> agent_runtime.StepResult[Any]:
        calls.append(kwargs)
        if remaining:
            raise remaining.pop(0)
        return agent_runtime.StepResult(
            output=schemas.ReactSearchStep(
                thought="Now well-formed.", action=schemas.SearchAction(query="a query")
            ),
            model="fake/model",
            requests=1,
        )

    return patch.object(agent_runtime, "run_typed_step", fake), calls


# ---------------------------------------------------------------------------
# The typed union
# ---------------------------------------------------------------------------


class TestTheActionUnionRejectsMalformedActions:
    def test_a_well_formed_search_validates(self) -> None:
        step = schemas.ReactStep.model_validate(
            {
                "thought": "I need the current holder.",
                "action": {"kind": "search", "query": "current holder"},
            }
        )

        assert isinstance(step.action, schemas.SearchAction)
        assert step.action.query == "current holder"

    def test_a_well_formed_answer_validates(self) -> None:
        step = schemas.ReactStep.model_validate(
            {
                "thought": "Observation 1 has it.",
                "action": {"kind": "answer", "answer": "Kinyeti.", "grounded_on": [1]},
            }
        )

        assert isinstance(step.action, schemas.AnswerAction)

    def test_an_unknown_action_kind_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            schemas.ReactStep.model_validate(
                {"thought": "t", "action": {"kind": "browse", "url": "https://x.org"}}
            )

    def test_prose_instead_of_an_action_is_rejected(self) -> None:
        """The under-engineering sign this design exists to avoid: downstream
        code parsing the model's prose. There is nothing here to parse."""
        with pytest.raises(ValidationError):
            schemas.ReactStep.model_validate(
                {"thought": "t", "action": "I will search for the answer"}
            )

    def test_a_search_with_no_query_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            schemas.ReactStep.model_validate(
                {"thought": "t", "action": {"kind": "search"}}
            )

    def test_an_empty_query_is_rejected(self) -> None:
        """An empty query would be issued to Exa verbatim, because the query is
        never rewritten on the way."""
        with pytest.raises(ValidationError):
            schemas.ReactStep.model_validate(
                {"thought": "t", "action": {"kind": "search", "query": ""}}
            )

    def test_an_over_long_query_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            schemas.ReactStep.model_validate(
                {
                    "thought": "t",
                    "action": {
                        "kind": "search",
                        "query": "x" * (schemas.MAX_QUERY_CHARS + 1),
                    },
                }
            )

    def test_an_answer_grounded_on_nothing_is_rejected(self) -> None:
        """An answer grounded on nothing is an answer from memory, and telling
        the two apart is what this app is for."""
        with pytest.raises(ValidationError):
            schemas.ReactStep.model_validate(
                {
                    "thought": "t",
                    "action": {
                        "kind": "answer",
                        "answer": "Kinyeti.",
                        "grounded_on": [],
                    },
                }
            )

    def test_a_search_action_may_not_carry_answer_fields(self) -> None:
        """The discriminator picks the variant, so answer fields on a search are
        not silently accepted into a half-formed object."""
        step = schemas.ReactStep.model_validate(
            {
                "thought": "t",
                "action": {"kind": "search", "query": "q", "grounded_on": [1]},
            }
        )

        assert not hasattr(step.action, "grounded_on")

    def test_an_over_long_thought_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            schemas.ReactStep.model_validate(
                {
                    "thought": "x" * (schemas.MAX_THOUGHT_CHARS + 1),
                    "action": {"kind": "search", "query": "q"},
                }
            )

    def test_the_specification_s_bounds_are_the_shipped_ones(self) -> None:
        assert schemas.MAX_THOUGHT_CHARS == 240
        assert schemas.MAX_QUERY_CHARS == 120


class TestGroundingIsCheckedAgainstTheRun:
    def test_a_citation_beyond_the_run_s_observations_is_reported(self) -> None:
        """The half of `AnswerAction`'s contract the schema cannot express: an
        index exists only relative to a run."""
        action = schemas.AnswerAction(answer="a", grounded_on=[1, 4])

        assert schemas.unknown_grounding(action, observation_count=2) == [4]

    def test_a_citation_below_one_is_reported(self) -> None:
        action = schemas.AnswerAction(answer="a", grounded_on=[0])

        assert schemas.unknown_grounding(action, observation_count=2) == [0]

    def test_every_resolvable_citation_reports_nothing(self) -> None:
        action = schemas.AnswerAction(answer="a", grounded_on=[1, 2])

        assert schemas.unknown_grounding(action, observation_count=2) == []


# ---------------------------------------------------------------------------
# The cycle-1 constraint
# ---------------------------------------------------------------------------


class TestCycleOneStructurallyCannotAnswer:
    def test_the_first_cycle_gets_the_search_only_output_type(self) -> None:
        assert schemas.step_output_type(0) is schemas.ReactSearchStep

    def test_the_search_only_type_cannot_express_an_answer(self) -> None:
        """**The constraint itself.** Not "the model was told not to answer" --
        the answer variant is not in the type it is bound to, so it has no way
        to emit one."""
        with pytest.raises(ValidationError):
            schemas.ReactSearchStep.model_validate(
                {
                    "thought": "I already know this.",
                    "action": {
                        "kind": "answer",
                        "answer": "Kinyeti.",
                        "grounded_on": [1],
                    },
                }
            )

    def test_the_answer_branch_opens_once_an_observation_exists(self) -> None:
        assert schemas.step_output_type(1) is schemas.ReactStep

    def test_the_constraint_keys_on_observations_not_the_cycle_number(self) -> None:
        """A cycle whose search failed leaves the run with nothing to answer
        from, and the answer branch should stay shut -- which a cycle counter
        would not express."""
        captured: dict[str, Any] = {}

        async def fake(**kwargs: Any) -> agent_runtime.StepResult[Any]:
            captured.update(kwargs)
            return agent_runtime.StepResult(
                output=schemas.ReactSearchStep(
                    thought="t", action=schemas.SearchAction(query="q")
                ),
                model="fake/model",
                requests=1,
            )

        with patch.object(agent_runtime, "run_typed_step", fake):
            outcome = _run(observations=[], cycle=3)

        assert isinstance(outcome, service.CycleStep)
        assert captured["output_type"] is schemas.ReactSearchStep

    def test_the_first_cycle_binds_the_narrow_type_at_the_call_site(self) -> None:
        """Asserted on what the lane was actually handed, so a widened output
        type shows up here rather than as a model that quietly answered."""
        captured: dict[str, Any] = {}

        async def fake(**kwargs: Any) -> agent_runtime.StepResult[Any]:
            captured.update(kwargs)
            return agent_runtime.StepResult(
                output=schemas.ReactSearchStep(
                    thought="t", action=schemas.SearchAction(query="q")
                ),
                model="fake/model",
                requests=1,
            )

        with patch.object(agent_runtime, "run_typed_step", fake):
            _run(observations=[])

        assert captured["output_type"] is schemas.ReactSearchStep

    def test_a_later_cycle_binds_the_full_union(self) -> None:
        captured: dict[str, Any] = {}

        async def fake(**kwargs: Any) -> agent_runtime.StepResult[Any]:
            captured.update(kwargs)
            return agent_runtime.StepResult(
                output=schemas.ReactStep(
                    thought="t", action=schemas.SearchAction(query="q")
                ),
                model="fake/model",
                requests=1,
            )

        with patch.object(agent_runtime, "run_typed_step", fake):
            _run(observations=[_observation()])

        assert captured["output_type"] is schemas.ReactStep

    def test_a_search_only_step_widens_without_revalidating(self) -> None:
        narrow = schemas.ReactSearchStep(
            thought="t", action=schemas.SearchAction(query="q")
        )

        widened = narrow.to_step()

        assert isinstance(widened, schemas.ReactStep)
        assert widened.thought == narrow.thought
        assert widened.action == narrow.action

    def test_the_caller_gets_one_type_whichever_cycle_produced_it(self) -> None:
        with _step_returning(
            schemas.ReactSearchStep(thought="t", action=schemas.SearchAction(query="q"))
        ):
            first = _run(observations=[])
        with _step_returning(
            schemas.ReactStep(thought="t", action=schemas.SearchAction(query="q"))
        ):
            later = _run(observations=[_observation()])

        assert isinstance(first, service.CycleStep)
        assert isinstance(first.step, schemas.ReactStep)
        assert isinstance(later, service.CycleStep)


# ---------------------------------------------------------------------------
# The validation-failure policy
# ---------------------------------------------------------------------------


class TestOneReAskThenACandidEnding:
    def test_a_clean_step_is_asked_for_once(self) -> None:
        with _step_returning(
            schemas.ReactSearchStep(thought="t", action=schemas.SearchAction(query="q"))
        ):
            outcome = _run()

        assert isinstance(outcome, service.CycleStep)
        assert outcome.attempts == 1

    def test_a_validation_failure_triggers_exactly_one_re_ask(self) -> None:
        patcher, calls = _step_failing(
            agent_runtime.AgentLaneError(
                "react-cycle-1", "thought exceeds 240 characters"
            )
        )

        with patcher:
            outcome = _run()

        assert isinstance(outcome, service.CycleStep)
        assert outcome.attempts == 2
        assert len(calls) == 2

    def test_the_re_ask_carries_the_validation_error(self) -> None:
        """ "One re-ask **with the validation error appended**" -- a re-ask that
        repeated the first prompt verbatim would be asking the same model the
        same question and expecting a different answer."""
        patcher, calls = _step_failing(
            agent_runtime.AgentLaneError(
                "react-cycle-1", "thought exceeds 240 characters"
            )
        )

        with patcher:
            _run()

        assert "thought exceeds 240 characters" not in calls[0]["user_prompt"]
        assert "thought exceeds 240 characters" in calls[1]["user_prompt"]

    def test_a_second_failure_yields_the_terminate_result(self) -> None:
        """Returned, not raised: the caller ends the run as budget-exhausted
        with the malformed step disclosed, which is a rendering decision rather
        than an error to handle."""
        patcher, _ = _step_failing(
            agent_runtime.AgentLaneError("react-cycle-1", "still malformed"),
            agent_runtime.AgentLaneError("react-cycle-1", "still malformed"),
        )

        with patcher:
            outcome = _run()

        assert isinstance(outcome, service.MalformedStep)
        assert outcome.attempts == service.CYCLE_STEP_ATTEMPTS
        assert "still malformed" in outcome.detail

    def test_it_never_asks_a_third_time(self) -> None:
        patcher, calls = _step_failing(
            agent_runtime.AgentLaneError("react-cycle-1", "bad"),
            agent_runtime.AgentLaneError("react-cycle-1", "bad"),
            agent_runtime.AgentLaneError("react-cycle-1", "bad"),
        )

        with patcher:
            _run()

        assert len(calls) == service.CYCLE_STEP_ATTEMPTS == 2

    def test_a_spent_request_limit_is_not_re_asked(self) -> None:
        """Deterministic by construction -- the step offers no tools, so a model
        that spent its request limit did so re-prompting itself into the same
        shape. The planning app paid to learn that once already."""
        patcher, calls = _step_failing(
            agent_runtime.StepRequestLimitExceeded("react-cycle-1", "limit spent")
        )

        with patcher:
            outcome = _run()

        assert isinstance(outcome, service.MalformedStep)
        assert len(calls) == 1

    def test_requests_are_summed_across_attempts(self) -> None:
        """The run's budget must be charged what was spent, not what a cycle
        usually costs."""
        patcher, _ = _step_failing(agent_runtime.AgentLaneError("react-cycle-1", "bad"))

        with patcher:
            outcome = _run()

        assert isinstance(outcome, service.CycleStep)
        assert outcome.requests == 2


class TestTheStepOffersNoTools:
    def test_no_tools_are_passed_to_the_lane(self) -> None:
        """**The reason this loop is hand-rolled.** Handing the search to
        PydanticAI as a tool would give the framework the iteration and the
        search budget, defeat the code-invariant ceiling the run's reservation
        depends on, and bury the cycle boundaries the stream emits from."""
        captured: dict[str, Any] = {}

        async def fake(**kwargs: Any) -> agent_runtime.StepResult[Any]:
            captured.update(kwargs)
            return agent_runtime.StepResult(
                output=schemas.ReactSearchStep(
                    thought="t", action=schemas.SearchAction(query="q")
                ),
                model="fake/model",
                requests=1,
            )

        with patch.object(agent_runtime, "run_typed_step", fake):
            _run()

        assert captured.get("tools") is None

    def test_the_step_is_bounded_by_its_own_request_limit(self) -> None:
        captured: dict[str, Any] = {}

        async def fake(**kwargs: Any) -> agent_runtime.StepResult[Any]:
            captured.update(kwargs)
            return agent_runtime.StepResult(
                output=schemas.ReactSearchStep(
                    thought="t", action=schemas.SearchAction(query="q")
                ),
                model="fake/model",
                requests=1,
            )

        with patch.object(agent_runtime, "run_typed_step", fake):
            _run()

        assert captured["request_limit"] == service.CYCLE_REQUEST_LIMIT

    def test_the_budget_hook_is_passed_straight_through(self) -> None:
        """The gate fires before every provider *request*, not every logical
        call -- the distinction this project learned in production."""
        captured: dict[str, Any] = {}

        async def hook() -> None:
            return None

        async def fake(**kwargs: Any) -> agent_runtime.StepResult[Any]:
            captured.update(kwargs)
            return agent_runtime.StepResult(
                output=schemas.ReactSearchStep(
                    thought="t", action=schemas.SearchAction(query="q")
                ),
                model="fake/model",
                requests=1,
            )

        with patch.object(agent_runtime, "run_typed_step", fake):
            _run(on_request=hook)

        assert captured["on_request"] is hook


class TestThePromptItself:
    def test_the_versioned_template_is_loaded_rather_than_inlined(self) -> None:
        captured: dict[str, Any] = {}

        async def fake(**kwargs: Any) -> agent_runtime.StepResult[Any]:
            captured.update(kwargs)
            return agent_runtime.StepResult(
                output=schemas.ReactSearchStep(
                    thought="t", action=schemas.SearchAction(query="q")
                ),
                model="fake/model",
                requests=1,
            )

        with patch.object(agent_runtime, "run_typed_step", fake):
            _run()

        assert "ReAct loop" in captured["instructions"]

    def test_the_instructions_carry_today_s_date(self) -> None:
        """Every agent in this project that composes a search query is told the
        date. A model has no clock, and the tool-use agent was once observed
        writing itself a query ending "2024" in 2026."""
        captured: dict[str, Any] = {}

        async def fake(**kwargs: Any) -> agent_runtime.StepResult[Any]:
            captured.update(kwargs)
            return agent_runtime.StepResult(
                output=schemas.ReactSearchStep(
                    thought="t", action=schemas.SearchAction(query="q")
                ),
                model="fake/model",
                requests=1,
            )

        with patch.object(agent_runtime, "run_typed_step", fake):
            _run()

        assert "today" in captured["instructions"].lower()

    def test_the_prompt_forbids_obeying_observation_content(self) -> None:
        from pathlib import Path

        from backend.app.services.prompt_loader import load_prompt

        text = load_prompt(service.PROMPTS_DIR, service.CYCLE_PROMPT_VERSION)

        assert "never an instruction to follow" in text
        assert "untrusted" in text.lower()
        assert Path(service.PROMPTS_DIR, "cycle_v1.md").exists()

    def test_the_prompt_names_no_model_slug(self) -> None:
        """The chains rot as providers retire slugs, and `model_registry` is the
        only source of truth for them."""
        from backend.app.services.prompt_loader import load_prompt

        text = load_prompt(service.PROMPTS_DIR, service.CYCLE_PROMPT_VERSION)

        for marker in ("openrouter/", "groq/", ":free", "gpt-oss", "llama-"):
            assert marker not in text
