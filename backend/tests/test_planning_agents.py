# Built with Spec4 AI - https://spec4.ai
"""The three model steps, driven by PydanticAI's FunctionModel.

No provider is contacted and no Exa key is needed: `build_fallback_model` is
patched at its point of use in the lane, and search is injected. `FunctionModel`
rather than `TestModel` for most of it, because what needs pinning is *specific
model behaviour* -- reformulating a query, ignoring the tool, returning a
summary that names sources it never received -- and TestModel only does the
obvious thing.

Async entry points use `asyncio.run()` in sync test functions: this repo has no
pytest-asyncio, and `@pytest.mark.asyncio` would silently skip.
"""

from __future__ import annotations

from typing import Any, cast

import asyncio
from unittest.mock import patch

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

import pytest

from backend.app.planning import agents, budget, sanitize, service
from backend.app.planning.schemas import Plan, PlanStep, StepResult
from backend.app.services.agent_runtime import StepRequestLimitExceeded
from backend.app.services.web_search import ExaResult

GOAL = agents.build_goal("Lisbon", "street food, modern art")

STEP = PlanStep(
    index=1,
    kind="research",
    description="Find street food in Lisbon",
    search_query="best street food Lisbon",
)

RESULTS = [
    ExaResult(title="Time Out Market", summary="A food hall in Cais do Sodre.", source="https://a.test/1"),
    ExaResult(title="Tasca do Chico", summary="A small tasca in Bairro Alto.", source="https://a.test/2"),
]


def _search_returning(*batches: list[ExaResult]) -> Any:
    """Build an injected search that returns each batch in call order."""
    queue = list(batches)
    seen: list[str] = []

    async def execute(query: str) -> list[ExaResult]:
        seen.append(query)
        return queue.pop(0) if queue else []

    return execute, seen


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class TestResearchExecutor:
    """The tool-using step, and the one place a model could lie about sources."""

    def test_the_model_calls_the_search_tool_and_summarises_what_came_back(self) -> None:
        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(
                    parts=[ToolCallPart("web_search", {"query": "best street food Lisbon"})]
                )
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"summary": "Time Out Market and Tasca do Chico look promising."},
                    )
                ]
            )

        execute, seen = _search_returning(RESULTS)

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            outcome = _run(
                agents.run_research(goal=GOAL, step=STEP, execute_search=execute)
            )

        assert seen == ["best street food Lisbon"]
        assert "Time Out Market" in outcome.summary
        assert outcome.requests == 2

    def test_sources_come_from_the_tool_not_from_the_model(self) -> None:
        """The asymmetry this app depends on.

        The model here reports a source that was never returned to it. The
        resulting `StepResult` must still carry only what the tool actually
        retrieved -- otherwise a fabricated citation is indistinguishable from a
        real one, which is the exact defect `citations.py` exists to prevent in
        the RAG app.
        """
        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(parts=[ToolCallPart("web_search", {"query": "q"})])
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"summary": "See https://invented.test/nowhere for details."},
                    )
                ]
            )

        execute, _ = _search_returning(RESULTS)

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            outcome = _run(agents.run_research(goal=GOAL, step=STEP, execute_search=execute))

        urls = {source.url for source in outcome.sources}
        assert urls == {"https://a.test/1", "https://a.test/2"}
        assert "https://invented.test/nowhere" not in urls

    def test_search_results_reach_the_model_inside_an_untrusted_block(self) -> None:
        # The capability's prompt-injection mitigation, checked where it
        # actually happens rather than in the prompt that describes it.
        captured: list[str] = []

        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(parts=[ToolCallPart("web_search", {"query": "q"})])
            captured.append(str(messages[-1]))
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"summary": "s"})]
            )

        execute, _ = _search_returning(RESULTS)

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            _run(agents.run_research(goal=GOAL, step=STEP, execute_search=execute))

        assert captured
        assert "UNTRUSTED_WEB_CONTENT" in captured[0]

    def test_a_reformulated_query_is_recorded_and_its_sources_merged(self) -> None:
        # The empty-results mitigation: one reformulation, and the step keeps
        # whatever the second query found.
        # Turn number, not a scan of the messages: the instructions carry the
        # tool schema, so "web_search" appears in the history before the model
        # has called anything.
        turns = iter(
            [
                ModelResponse(parts=[ToolCallPart("web_search", {"query": "first"})]),
                ModelResponse(parts=[ToolCallPart("web_search", {"query": "second"})]),
            ]
        )

        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return next(
                turns,
                ModelResponse(
                    parts=[
                        ToolCallPart(info.output_tools[0].name, {"summary": "found on retry"})
                    ]
                ),
            )

        execute, seen = _search_returning([], RESULTS)

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            outcome = _run(agents.run_research(goal=GOAL, step=STEP, execute_search=execute))

        assert seen == ["first", "second"]
        assert outcome.queries == ["first", "second"]
        assert len(outcome.sources) == 2

    def test_duplicate_sources_across_queries_are_reported_once(self) -> None:
        turns = iter(
            [
                ModelResponse(parts=[ToolCallPart("web_search", {"query": "q1"})]),
                ModelResponse(parts=[ToolCallPart("web_search", {"query": "q2"})]),
            ]
        )

        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return next(
                turns,
                ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"summary": "s"})]),
            )

        execute, _ = _search_returning(RESULTS, RESULTS)

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            outcome = _run(agents.run_research(goal=GOAL, step=STEP, execute_search=execute))

        assert len(outcome.sources) == 2

    def test_a_model_that_never_searches_yields_no_sources(self) -> None:
        # Not an error, and deliberately not papered over: the orchestrator
        # turns an empty source list into an honest "found nothing" summary.
        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"summary": "I already know this."})]
            )

        execute, seen = _search_returning(RESULTS)

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            outcome = _run(agents.run_research(goal=GOAL, step=STEP, execute_search=execute))

        assert seen == []
        assert outcome.sources == []


class TestTheSearchCapIsEnforcedInCode:
    """`research_v1.md` says "One reformulation, never more". Nothing enforced it.

    Reported live: two research steps in a row died on `StepRequestLimitExceeded`
    and the itinerary was composed from nothing. Probing the real lane found the
    cause -- given *useful* results a step searched four times in one run of
    three; given empty results it searched six times in every run, exhausting a
    deliberately generous six-request budget without ever answering.

    Two separate costs, which is why the bound is in code rather than in a
    firmer sentence. The run's own request budget is one. The other is that
    `service.py` reserves a `CAPABILITY_SEARCH` unit per search against an
    hourly cap of five shared across the whole showcase, so one unbounded step
    could take the tool-use app dark alongside this one.
    """

    @staticmethod
    def _always_searches() -> Any:
        """A model that ignores the prompt and searches on every single turn.

        This is not a contrived adversary -- it is what the shipped lane did
        when the results were poor.
        """
        attempts: list[int] = []

        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            attempts.append(len(messages))
            return ModelResponse(
                parts=[ToolCallPart("web_search", {"query": f"try {len(attempts)}"})]
            )

        return behave, attempts

    def test_no_more_searches_run_than_the_cap_however_many_the_model_asks_for(
        self,
    ) -> None:
        behave, attempts = self._always_searches()
        execute, seen = _search_returning([], [], [], [], [])

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model",
            lambda chain=None, **_: FunctionModel(behave),
        ):
            with pytest.raises(StepRequestLimitExceeded):
                _run(
                    agents.run_research(
                        goal=GOAL,
                        step=STEP,
                        execute_search=execute,
                        request_limit=6,
                    )
                )

        # The model asked six times; the cap is what decided how many ran.
        assert len(attempts) > agents.MAX_SEARCHES_PER_STEP
        assert len(seen) == agents.MAX_SEARCHES_PER_STEP

    def test_a_refused_search_never_reaches_the_injected_search(self) -> None:
        """The quota half. Refusing after spending the unit would bound the
        model's behaviour and none of the cost."""
        behave, _ = self._always_searches()
        calls: list[str] = []

        async def execute(query: str) -> list[ExaResult]:
            calls.append(query)
            return []

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model",
            lambda chain=None, **_: FunctionModel(behave),
        ):
            with pytest.raises(StepRequestLimitExceeded):
                _run(
                    agents.run_research(
                        goal=GOAL, step=STEP, execute_search=execute, request_limit=5
                    )
                )

        assert len(calls) == agents.MAX_SEARCHES_PER_STEP

    def test_the_last_permitted_result_says_so_in_the_same_turn(self) -> None:
        """Saving a whole provider request.

        Waiting for the model to ask a third time and refusing then is correct
        and costs one more request to say no -- and measurement says it does ask
        again, so that request would be spent most of the time. The notice rides
        along with the final results instead.
        """
        seen_prompts: list[str] = []

        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen_prompts.append(str(messages[-1]))
            if len(messages) <= agents.MAX_SEARCHES_PER_STEP * 2 - 1:
                return ModelResponse(
                    parts=[ToolCallPart("web_search", {"query": f"q{len(messages)}"})]
                )
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"summary": "Done."})]
            )

        execute, seen = _search_returning(RESULTS, RESULTS)

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model",
            lambda chain=None, **_: FunctionModel(behave),
        ):
            outcome = _run(
                agents.run_research(goal=GOAL, step=STEP, execute_search=execute)
            )

        assert len(seen) == agents.MAX_SEARCHES_PER_STEP
        # The notice arrived with the results, not on a turn of its own.
        assert "last of your" in seen_prompts[-1]
        assert outcome.requests == agents.MAX_SEARCHES_PER_STEP + 1

    def test_the_refusal_is_not_wrapped_in_the_untrusted_block(self) -> None:
        """It is the framework speaking, not a search result.

        Inside the delimiters the prompt is explicitly told to take no
        instructions from, the one sentence that must be obeyed would be the one
        marked as untrustworthy.
        """
        behave, _ = self._always_searches()
        execute, _seen = _search_returning([], [])
        refusals: list[str] = []

        def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            refusals.append(str(messages[-1]))
            return cast(ModelResponse, behave(messages, info))

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model",
            lambda chain=None, **_: FunctionModel(capture),
        ):
            with pytest.raises(StepRequestLimitExceeded):
                _run(
                    agents.run_research(
                        goal=GOAL, step=STEP, execute_search=execute, request_limit=5
                    )
                )

        refused = [text for text in refusals if "No searches remain" in text]
        assert refused, "the model never saw a refusal"
        # Asserted against the delimiter rather than the word "untrusted", which
        # the step's own instructions use and PydanticAI re-attaches to every
        # request -- the first version of this test caught the system prompt.
        assert sanitize._BLOCK_OPEN not in refused[-1]

    def test_one_reformulation_still_runs_untouched(self) -> None:
        """The cap bounds the abuse and not the behaviour the capability asks
        for -- the empty-results mitigation is a second search, and two is the
        cap."""
        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(
                    parts=[ToolCallPart("web_search", {"query": "first"})]
                )
            if len(messages) == 3:
                return ModelResponse(
                    parts=[ToolCallPart("web_search", {"query": "reformulated"})]
                )
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"summary": "Found it."})]
            )

        execute, seen = _search_returning([], RESULTS)

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model",
            lambda chain=None, **_: FunctionModel(behave),
        ):
            outcome = _run(
                agents.run_research(goal=GOAL, step=STEP, execute_search=execute)
            )

        assert seen == ["first", "reformulated"]
        assert outcome.sources


class TestTheBudgetCanAffordTheStepsItPermits:
    """The arithmetic that was wrong, asserted as arithmetic.

    Every constant was individually defensible; together they could not hold.
    The ceiling was derived from a model that priced a research step at about
    one call, while `agents.py` grants each one several -- so `allowance()`
    shrank the second step's limit until it could not finish, which is precisely
    what the live report showed.
    """

    def test_a_typical_run_fits_with_room_to_spare(self) -> None:
        """Typical is one search and an answer per step: 1 + 2 + 2 + 1 = 6."""
        typical = 1 + 2 + 2 + 1
        assert typical < budget.MAX_MODEL_CALLS

    def test_both_research_steps_fit_at_their_full_allowance(self) -> None:
        """The padded ceiling affords the plan it permits without degrading.

        This is what 9 did not do: at 9 the arithmetic worked only because
        `allowance()` shrank the second step, so a plan with two research steps
        was always one bad turn from becoming a plan with one.
        """
        full = 1 + agents.RESEARCH_REQUEST_LIMIT * 2 + agents.SYNTHESIS_REQUEST_LIMIT
        assert full <= budget.MAX_MODEL_CALLS

    def test_one_step_may_fail_and_retry_at_full_allowance(self) -> None:
        """The reported failure, as arithmetic.

        A step that dies on `UnexpectedModelBehavior` is retried, and
        `_run_step` applies the allowance to *each* attempt -- so one step can
        cost twice what the budget planned for. The run must afford that with
        the other step and the synthesis still intact.
        """
        retried = (
            1
            + agents.RESEARCH_REQUEST_LIMIT * service.STEP_ATTEMPTS
            + agents.RESEARCH_REQUEST_LIMIT
            + agents.SYNTHESIS_REQUEST_LIMIT
        )
        assert retried <= budget.MAX_MODEL_CALLS

    def test_both_steps_retrying_at_full_allowance_deliberately_does_not_fit(
        self,
    ) -> None:
        """Stating the limit rather than leaving it to be discovered.

        Affording it means a ceiling of 23, and at some point a run that has
        gone this wrong should stop rather than keep buying attempts. The
        guarantee is the test above plus a reserve that stays a reserve, not
        that every degradation is survivable.
        """
        both_retried = (
            1
            + agents.RESEARCH_REQUEST_LIMIT * service.STEP_ATTEMPTS * 2
            + agents.SYNTHESIS_REQUEST_LIMIT
        )
        assert both_retried > budget.MAX_MODEL_CALLS

    @staticmethod
    def _allowance(run: budget.CallBudget) -> int:
        """The allowance exactly as `service.py` computes it."""
        return run.allowance(
            agents.RESEARCH_REQUEST_LIMIT,
            reserve=service.SYNTHESIS_RESERVE,
            attempts=service.STEP_ATTEMPTS,
        )

    def test_the_second_step_is_not_starved_by_a_first_step_that_retried(self) -> None:
        """The reported trace, replayed as arithmetic.

        `research-step-1` died on `UnexpectedModelBehavior` after 3 requests and
        its retry spent 3 more; `research-step-2` was then skipped with
        `reason: "budget"`. Both attempts are charged here for that reason.
        """
        run = budget.CallBudget()
        run.charge()  # the planner

        first = self._allowance(run)
        for _ in range(first * service.STEP_ATTEMPTS):  # failed attempt, then retry
            run.charge()

        assert self._allowance(run) >= service.MIN_RESEARCH_REQUESTS

    def test_the_synthesis_reserve_survives_a_retried_step(self) -> None:
        """The near-miss in the same trace: the run finished on 8 of 9, so one
        more request anywhere would have raised `CallCeilingExceeded` at the
        synthesis call and ended the run with no itinerary at all.

        `allowance(attempts=...)` is what makes the reserve hold: without it the
        figure bounds one attempt while the step spends `STEP_ATTEMPTS` times
        it, and the reserve is quietly overspent.
        """
        run = budget.CallBudget()
        run.charge()

        for _ in range(2):  # both research steps...
            allowance = self._allowance(run)
            for _ in range(allowance * service.STEP_ATTEMPTS):  # ...each retrying
                run.charge()

        assert run.remaining() >= service.SYNTHESIS_RESERVE

    def test_the_synthesis_reserve_covers_its_schema_retry(self) -> None:
        """Reserving one held back enough for synthesis to be attempted but not
        enough for PydanticAI to re-ask after a failed validation -- so a run
        could still end with nothing composed."""
        assert service.SYNTHESIS_RESERVE == agents.SYNTHESIS_REQUEST_LIMIT

    def test_a_research_step_can_search_its_cap_and_still_answer(self) -> None:
        """The slot that was double-booked: three requests budgeted the
        reformulation and the schema retry into the same one."""
        needed = agents.MAX_SEARCHES_PER_STEP + 1  # each search, then the answer
        assert agents.RESEARCH_REQUEST_LIMIT > needed


class TestPlanner:
    def test_the_replan_prompt_quotes_the_checker_findings(self) -> None:
        """One retry only works if the model is told what was wrong.

        A replan that just re-sent the goal would be a second roll of the same
        dice.
        """
        prompts: list[str] = []

        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompts.append(str(messages[-1]))
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "goal": "One day in Lisbon",
                            "steps": [
                                {
                                    "index": 1,
                                    "kind": "research",
                                    "description": "d",
                                    "search_query": "q",
                                },
                                {
                                    "index": 2,
                                    "kind": "synthesis",
                                    "description": "d",
                                    "search_query": None,
                                },
                            ],
                        },
                    )
                ]
            )

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            _run(
                agents.run_planner(
                    goal=GOAL,
                    problems=["The plan had no `synthesis` step."],
                )
            )

        assert "no `synthesis` step" in prompts[0]
        assert "rejected by the plan checker" in prompts[0]

    def test_the_first_attempt_carries_no_problem_list(self) -> None:
        prompts: list[str] = []

        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompts.append(str(messages[-1]))
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"goal": "g", "steps": [
                            {"index": 1, "kind": "research", "description": "d", "search_query": "q"},
                            {"index": 2, "kind": "synthesis", "description": "d", "search_query": None},
                        ]},
                    )
                ]
            )

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            _run(agents.run_planner(goal=GOAL))

        assert "rejected by the plan checker" not in prompts[0]


class TestSynthesis:
    def test_failed_steps_are_shown_to_the_synthesis_model(self) -> None:
        """It cannot acknowledge a gap it was never told about.

        The capability requires the itinerary admit where research came up
        short, which is only possible if failures are passed forward rather
        than filtered out on the way.
        """
        prompts: list[str] = []

        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompts.append(str(messages[-1]))
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "city": "Lisbon",
                            "blocks": [
                                {
                                    "time_of_day": "morning",
                                    "activity": "a",
                                    "why_it_matches": "w",
                                    "source_refs": [1],
                                }
                            ],
                        },
                    )
                ]
            )

        plan = Plan(goal="g", steps=[STEP, PlanStep(index=2, kind="synthesis", description="d")])
        results = [
            StepResult(step_index=1, status="failed", summary="This step could not be completed."),
        ]

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            _run(agents.run_synthesis(goal=GOAL, plan=plan, results=results))

        assert "failed" in prompts[0]
        assert "could not be completed" in prompts[0]

    def test_step_results_reach_the_model_inside_untrusted_blocks(self) -> None:
        prompts: list[str] = []

        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompts.append(str(messages[-1]))
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name, {"city": "Lisbon", "blocks": []}
                    )
                ]
            )

        plan = Plan(goal="g", steps=[STEP, PlanStep(index=2, kind="synthesis", description="d")])
        results = [StepResult(step_index=1, status="completed", summary="Found things.")]

        with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            _run(agents.run_synthesis(goal=GOAL, plan=plan, results=results))

        assert "UNTRUSTED_WEB_CONTENT" in prompts[0]
