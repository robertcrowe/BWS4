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

import asyncio
from unittest.mock import patch

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from backend.app.planning import agents
from backend.app.planning.schemas import Plan, PlanStep, StepResult
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


def _search_returning(*batches: list[ExaResult]):
    """Build an injected search that returns each batch in call order."""
    queue = list(batches)
    seen: list[str] = []

    async def execute(query: str) -> list[ExaResult]:
        seen.append(query)
        return queue.pop(0) if queue else []

    return execute, seen


def _run(coro):
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

        with patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
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

        with patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
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

        with patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
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

        with patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
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

        with patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
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

        with patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            outcome = _run(agents.run_research(goal=GOAL, step=STEP, execute_search=execute))

        assert seen == []
        assert outcome.sources == []


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

        with patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
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

        with patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
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

        with patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
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

        with patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: FunctionModel(behave)):
            _run(agents.run_synthesis(goal=GOAL, plan=plan, results=results))

        assert "UNTRUSTED_WEB_CONTENT" in prompts[0]
