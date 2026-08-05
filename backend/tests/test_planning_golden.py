# Built with Spec4 AI - https://spec4.ai
"""The planning agent's offline golden suite.

Seven `(city, interests)` cases across the three classes the capability's eval
approach names — easy, niche, adversarial — each driven through the **real**
orchestrator with only the model and Exa replaced. Fixtures live in
`golden/planning_cases.json`; nothing here needs a key, a network, or a
database.

## What is asserted, and why these things

Everything below traces to a stated success criterion or failure mode rather
than to fixture prose, so the suite survives rewording of the prompts:

- the accepted plan passes the real schema **and** the real validator
- a run never exceeds the hard call ceiling
- step results arrive strictly in plan order
- the quota gate is consulted once per model call, no more and no fewer
- adversarial input degrades honestly instead of crashing

## Fixture drift is the risk this file is written against

Hand-authored model output that does not match the real `Plan` shape would make
the suite pass while the live system fails. So every fixture is validated
through the production schema and validator at collection time
(`test_every_fixture_matches_the_real_schema`), and the queue convention is
checked too: all but the last planner output must *fail* validation, because
their whole purpose is to exercise the replan. A fixture that quietly became
valid would stop testing what it claims to.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from backend.app.db.models import SearchQuery, ServiceLogEntry, UsageLimit
from backend.app.planning import agents, service, validator
from backend.app.planning.budget import MAX_MODEL_CALLS
from backend.app.planning.sanitize import MAX_INTERESTS_CHARS
from backend.app.planning.schemas import KIND_RESEARCH, KIND_SYNTHESIS, Plan
from backend.app.planning.validator import MAX_RESEARCH_STEPS, MAX_STEPS, MIN_STEPS
from backend.app.services import shared
from backend.app.services.web_search import ExaResult

CASES_PATH = Path(__file__).parent / "golden" / "planning_cases.json"
CASES: list[dict[str, Any]] = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
CASE_IDS = [case["id"] for case in CASES]


class _Result:
    def __init__(self, scalar: object = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar


class _Session:
    """Fake session whose usage rows persist, so gate checks can be counted."""

    def __init__(self, caps: dict[str, int] | None = None) -> None:
        self.added: list[object] = []
        self.limits: dict[str, UsageLimit] = {}
        self._caps = caps or {}

    async def execute(self, statement: Any, *_a: object, **_k: object) -> _Result:
        try:
            capability = next(iter(statement.compile().params.values()))
        except Exception:  # noqa: BLE001 - fake session, best effort
            capability = None
        return _Result(self.limits.get(capability))

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, UsageLimit):
            if obj.capability in self._caps:
                obj.cap = self._caps[obj.capability]
            self.limits[obj.capability] = obj

    async def commit(self) -> None:
        pass

    def used(self, capability: str) -> int:
        limit = self.limits.get(capability)
        return limit.used if limit else 0

    def rows(self, kind: type) -> list[object]:
        return [row for row in self.added if isinstance(row, kind)]


class GoldenRun:
    """Everything one golden case produced, for the assertions to read."""

    def __init__(self) -> None:
        self.outcome: Any = None
        self.events: list[service.ExecutionEvent] = []
        self.prompts: list[str] = []
        self.tool_returns: list[str] = []
        self.queries: list[str] = []
        self.model_calls = 0
        self.session: Any = _Session()

    @property
    def step_results(self) -> list[Any]:
        return [event.step_result for event in self.events if event.kind == "step_result"]

    @property
    def itinerary(self) -> Any:
        for event in self.events:
            if event.kind == "itinerary":
                return event.itinerary
        return None

    @property
    def halted(self) -> Any:
        for event in self.events:
            if event.kind == "halted":
                return event
        return None


def _which_agent(info: AgentInfo) -> str:
    """Identify the step from the output schema the agent is asking for.

    More robust than counting turns: the planner, the research executor and the
    synthesis step each bind a different output type, and that is what actually
    distinguishes them.
    """
    if any(tool.name == "web_search" for tool in info.function_tools):
        return "research"
    schema = json.dumps(info.output_tools[0].parameters_json_schema)
    if '"steps"' in schema:
        return "planner"
    if '"blocks"' in schema:
        return "synthesis"
    return "research"


def _model_for(case: dict[str, Any], run: GoldenRun) -> FunctionModel:
    """Build the fake model that serves every step of one golden case."""
    planner_queue = list(case["planner_outputs"])
    searched: set[int] = set()

    def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        run.model_calls += 1
        run.prompts.append(str(messages[-1]))
        role = _which_agent(info)
        output_tool = info.output_tools[0].name

        if role == "planner":
            payload = planner_queue.pop(0) if planner_queue else case["planner_outputs"][-1]
            return ModelResponse(parts=[ToolCallPart(output_tool, payload)])

        if role == "synthesis":
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        output_tool,
                        {
                            "city": case["city"],
                            "blocks": [
                                {
                                    "time_of_day": "morning",
                                    "activity": "Composed from the research above.",
                                    "why_it_matches": "Follows the stated interests.",
                                    "source_refs": [1],
                                }
                            ],
                        },
                    )
                ]
            )

        # Research: search once, then summarise on the following turn.
        turn = len(run.model_calls * [0])
        if id(info) not in searched and not any("web_search" in str(m) for m in messages[1:]):
            searched.add(id(info))
            query = _pending_query(run, case)
            return ModelResponse(parts=[ToolCallPart("web_search", {"query": query})])
        del turn
        return ModelResponse(
            parts=[ToolCallPart(output_tool, {"summary": "Summarised the results received."})]
        )

    return FunctionModel(behave)


def _pending_query(run: GoldenRun, case: dict[str, Any]) -> str:
    """The query for the research step currently executing."""
    plan = run.outcome.plan if run.outcome else Plan.model_validate(case["planner_outputs"][-1])
    research = [step for step in plan.steps if step.kind == KIND_RESEARCH]
    position = min(len(run.queries), len(research) - 1)
    return research[position].search_query or ""


def _search_for(case: dict[str, Any], run: GoldenRun) -> Any:
    """Serve recorded Exa results for a query, or the case's default."""

    async def fake_search(query: str) -> list[ExaResult]:
        run.queries.append(query)
        recorded = case["exa"].get(query, case["exa"].get("default", []))
        return [ExaResult(**item) for item in recorded]

    return fake_search


def run_case(case: dict[str, Any], *, caps: dict[str, int] | None = None) -> GoldenRun:
    """Drive one golden case through the real orchestrator, end to end."""
    run = GoldenRun()
    if caps:
        run.session = _Session(caps=caps)

    model = _model_for(case, run)

    async def drive() -> None:
        run.outcome = await service.create_plan(
            run.session, city=case["city"], interests=case["interests"]
        )
        async for event in service.execute_plan(
            run.session,
            goal=run.outcome.goal,
            plan=run.outcome.plan,
            calls_used=run.outcome.calls_used,
        ):
            run.events.append(event)

    original_block = agents.sanitize.untrusted_block  # type: ignore[attr-defined]  # reaching the module's own import on purpose -- patch/identity at point of use

    def recording_block(label: str, content: str) -> str:
        wrapped: str = original_block(label, content)
        run.tool_returns.append(wrapped)
        return wrapped

    with (
        patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: model),
        patch.object(service, "search", _search_for(case, run)),
        patch("backend.app.planning.agents.sanitize.untrusted_block", recording_block),
    ):
        asyncio.run(drive())

    return run


# ---------------------------------------------------------------------------
# Fixture integrity: the anti-drift check the phase's risk assessment demands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_every_fixture_matches_the_real_schema(case: dict[str, Any]) -> None:
    """Hand-authored model output is validated by the production schema.

    Without this, a fixture that drifted from `Plan` would make the whole suite
    pass against a shape the live planner never produces.
    """
    for payload in case["planner_outputs"]:
        plan = Plan.model_validate(payload)
        assert MIN_STEPS <= len(plan.steps) <= MAX_STEPS


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_the_planner_queue_means_what_it_claims(case: dict[str, Any]) -> None:
    """All but the last output must fail validation; the last must pass.

    That is the queue's entire convention. A malformed fixture that quietly
    became valid would silently stop exercising the replan path while still
    looking like it did.
    """
    outputs = case["planner_outputs"]

    for payload in outputs[:-1]:
        errors = validator.validate_plan(Plan.model_validate(payload))
        assert errors, "a non-final planner output is supposed to be rejected"

    assert validator.validate_plan(Plan.model_validate(outputs[-1])) == []


def test_the_suite_covers_all_three_case_classes() -> None:
    """The capability's eval approach names easy, niche and adversarial."""
    assert {case["case_class"] for case in CASES} == {"easy", "niche", "adversarial"}


# ---------------------------------------------------------------------------
# The golden runs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_the_accepted_plan_satisfies_every_validator_constraint(case: dict[str, Any]) -> None:
    """Schema shape plus the rules the schema cannot express."""
    run = run_case(case)
    plan = run.outcome.plan

    assert validator.validate_plan(plan) == []
    assert [step.kind for step in plan.steps][-1] == KIND_SYNTHESIS
    assert [step.kind for step in plan.steps].count(KIND_SYNTHESIS) == 1
    assert all(
        (step.search_query or "").strip()
        for step in plan.steps
        if step.kind == KIND_RESEARCH
    )
    assert [step.index for step in plan.steps] == list(range(1, len(plan.steps) + 1))


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_the_executed_plan_is_within_this_deployment_budget(case: dict[str, Any]) -> None:
    """At most two research steps plus the single synthesis step."""
    run = run_case(case)
    plan = run.outcome.plan
    research = [step for step in plan.steps if step.kind == KIND_RESEARCH]

    assert len(research) <= MAX_RESEARCH_STEPS
    assert len(plan.steps) == case["expect"]["total_steps"]
    assert len(research) == case["expect"]["research_steps"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_no_run_exceeds_the_hard_call_ceiling(case: dict[str, Any]) -> None:
    """100% of runs stay within the ceiling — the capability's own wording."""
    run = run_case(case)

    assert run.model_calls <= MAX_MODEL_CALLS


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_step_results_arrive_strictly_in_plan_order(case: dict[str, Any]) -> None:
    """Sequential execution, observed at the event stream rather than assumed."""
    run = run_case(case)
    reported = [result.step_index for result in run.step_results]
    research = [
        step.index for step in run.outcome.plan.steps if step.kind == KIND_RESEARCH
    ]

    assert reported == research
    assert reported == sorted(reported)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_the_quota_gate_is_consulted_once_per_model_call(case: dict[str, Any]) -> None:
    """Exactly as many gate checks as calls: no unmetered call, no double charge.

    Counted against the model's own invocation count rather than a fixed number,
    so cases that replan or reformulate are held to the same rule.
    """
    run = run_case(case)

    assert run.session.used(shared.CAPABILITY_GENERATION) == run.model_calls


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_one_planning_unit_is_reserved_per_run(case: dict[str, Any]) -> None:
    """The cap that bounds this app's share of a pool five apps draw on."""
    run = run_case(case)

    assert run.session.used(shared.CAPABILITY_PLANNING) == 1


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_every_search_is_metered_and_persisted(case: dict[str, Any]) -> None:
    run = run_case(case)

    assert run.session.used(shared.CAPABILITY_SEARCH) == len(run.queries)
    assert len(run.session.rows(SearchQuery)) == len(run.queries)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_the_run_produces_an_itinerary_and_logs_no_authored_text(
    case: dict[str, Any],
) -> None:
    """Honest degradation still ends in an itinerary, and never in stored content."""
    run = run_case(case)

    assert (run.itinerary is not None) is case["expect"]["itinerary"]

    summaries = [row.summary for row in run.session.rows(ServiceLogEntry)]
    assert summaries, "a run must still be observable"
    for summary in summaries:
        assert case["city"] not in summary
        assert case["interests"][:20] not in summary


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_the_expected_replan_and_trim_paths_fire(case: dict[str, Any]) -> None:
    """Pins which mitigation each fixture is actually exercising."""
    run = run_case(case)

    assert run.outcome.replanned is case["expect"]["replanned"]
    assert (run.outcome.trimmed_note is not None) is case["expect"]["trimmed"]


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["expect"].get("expect_a_step_with_no_sources")],
    ids=[case["id"] for case in CASES if case["expect"].get("expect_a_step_with_no_sources")],
)
def test_an_empty_search_is_reported_completed_and_honest(case: dict[str, Any]) -> None:
    """The search ran and the web had little to say — a finding, not a fault.

    Marking it failed would tell the visitor the machinery broke. The
    capability requires the opposite: `completed`, with an explicit
    'no useful results' summary.
    """
    run = run_case(case)
    empty = [result for result in run.step_results if not result.sources]

    assert empty, "this fixture is supposed to produce a step with no sources"
    for result in empty:
        assert result.status == "completed"
        assert "no usable results" in result.summary


# ---------------------------------------------------------------------------
# Event ordering: the zero-executor-calls-before-advance criterion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_planning_completes_before_any_step_executes(case: dict[str, Any]) -> None:
    """The human-in-the-loop checkpoint, as an ordering assertion.

    `create_plan` returns before `execute_plan` is entered — the plan is
    complete and reviewable at a point where no search has run and no step has
    reported. That is the API-level expression of "0 executor calls fire before
    the advance signal": the advance signal *is* the second call.
    """
    run = GoldenRun()
    model = _model_for(case, run)
    observed: dict[str, Any] = {}

    async def drive() -> None:
        run.outcome = await service.create_plan(
            run.session, city=case["city"], interests=case["interests"]
        )
        # Snapshot the world at the checkpoint, before the advance signal.
        observed["searches_at_checkpoint"] = len(run.queries)
        observed["steps_at_checkpoint"] = len(run.step_results)
        observed["calls_at_checkpoint"] = run.model_calls

        async for event in service.execute_plan(
            run.session,
            goal=run.outcome.goal,
            plan=run.outcome.plan,
            calls_used=run.outcome.calls_used,
        ):
            run.events.append(event)

    with (
        patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: model),
        patch.object(service, "search", _search_for(case, run)),
    ):
        asyncio.run(drive())

    assert observed["searches_at_checkpoint"] == 0
    assert observed["steps_at_checkpoint"] == 0
    # Only planner calls, and at most one replan on top of the first attempt.
    assert observed["calls_at_checkpoint"] <= 2
    # Execution genuinely happened afterwards, or the assertion above is vacuous.
    assert run.step_results


# ---------------------------------------------------------------------------
# Quota exhaustion
# ---------------------------------------------------------------------------


def test_a_spent_planning_budget_refuses_the_run_before_any_model_call() -> None:
    """No run proceeds once the per-UTC-day limit is exhausted."""
    case = CASES[0]
    run = GoldenRun()
    run.session = _Session(caps={shared.CAPABILITY_PLANNING: 0})
    model = _model_for(case, run)

    with patch("backend.app.planning.agents.agent_runtime.build_fallback_model", lambda chain=None, **_: model
    ):
        with pytest.raises(service.UsageLimitReachedError):
            asyncio.run(
                service.create_plan(
                    run.session, city=case["city"], interests=case["interests"]
                )
            )

    assert run.model_calls == 0


def test_a_spent_generation_budget_halts_the_run_with_a_categorised_code() -> None:
    """Mid-run exhaustion is reported, not swallowed, and keeps what completed."""
    case = CASES[0]
    run = run_case(case, caps={shared.CAPABILITY_GENERATION: 2})

    assert run.halted is not None
    assert run.halted.code == "usage_limit_reached"
    assert "resets at the top of the hour" in run.halted.notice


# ---------------------------------------------------------------------------
# Adversarial handling
# ---------------------------------------------------------------------------


def _adversarial(case_id: str) -> dict[str, Any]:
    return next(case for case in CASES if case["id"] == case_id)


def test_a_nonsense_city_degrades_honestly_rather_than_crashing() -> None:
    """No results anywhere, and the run still ends in an itinerary.

    The capability's requirement is honest degradation: the step says it found
    nothing, and the synthesis composes from what remains rather than failing.
    """
    run = run_case(_adversarial("adversarial-nonsense-city"))

    assert run.itinerary is not None
    assert run.halted is None
    assert all(result.status == "completed" for result in run.step_results)
    assert all(not result.sources for result in run.step_results)


def test_control_and_bidi_characters_are_stripped_before_any_prompt() -> None:
    """Hygiene on the visitor's own field.

    The fixture's interests carry a right-to-left override, which can make a
    string display as something other than what it contains — a way to hide text
    from a human reviewing the input while the model still reads it.
    """
    case = _adversarial("adversarial-injection")
    assert "‮" in case["interests"], "fixture should carry a bidi override"

    run = run_case(case)

    assert run.prompts
    for prompt in run.prompts:
        assert "‮" not in prompt


def test_injection_text_from_the_web_stays_inside_the_delimited_block() -> None:
    """The actual security control, checked where it operates.

    A search result carrying a forged closing delimiter must not be able to end
    the untrusted region early — everything after it would then read as prompt.
    The delimiter is stripped from the content, so exactly one closing marker
    survives and it is the real one at the end.
    """
    run = run_case(_adversarial("adversarial-injection"))

    assert run.tool_returns, "the research step should have wrapped its results"
    for block in run.tool_returns:
        assert block.count("<<<END_UNTRUSTED_WEB_CONTENT>>>") == 1
        assert block.rstrip().endswith("<<<END_UNTRUSTED_WEB_CONTENT>>>")

    # The block carrying the raw snippet keeps the hostile text: it is data to
    # be summarised, not something to silently delete. Scoped to that block
    # because the later synthesis block carries the model's *summary* of these
    # results, which has no reason to repeat the instruction.
    carrier = [block for block in run.tool_returns if "Musee d'Orsay" in block]
    assert carrier, "the search results should have been wrapped"
    assert any("Ignore all previous instructions" in block for block in carrier)
    assert any("[delimiter removed]" in block for block in carrier)


def test_injection_in_the_interests_is_carried_as_data_not_as_structure() -> None:
    """The visitor's own field is sanitised, and deliberately not delimited.

    Worth stating plainly because it looks like an omission: interests are the
    visitor's stated goal and must reach the planner as text, so they are
    cleaned (control characters, length) rather than wrapped. What bounds the
    damage is the tool surface — the executor can search the web and nothing
    else — so the worst outcome of a persuasive instruction here is a bad
    itinerary, never an action taken in someone's name.

    The one structural thing checked is that the visitor cannot forge the
    delimiters that protect the *web* channel. The fixture's interests attempt
    exactly that, and the marker must not survive sanitisation.
    """
    case = _adversarial("adversarial-injection")
    assert "<<<END_UNTRUSTED_WEB_CONTENT>>>" in case["interests"], "fixture should try to forge"

    run = run_case(case)

    goal_prompts = [prompt for prompt in run.prompts if "Interests:" in prompt]
    assert goal_prompts, "the goal block should reach the model"

    for prompt in goal_prompts:
        # Carried through as data, because it is what the visitor said they want.
        assert "Ignore all previous instructions" in prompt

    # The planner prompt contains only the goal — no untrusted block exists at
    # that point — so any marker in it could only have come from the visitor.
    planner_prompt = run.prompts[0]
    assert "Interests:" in planner_prompt
    assert "<<<UNTRUSTED_WEB_CONTENT" not in planner_prompt
    assert "<<<END_UNTRUSTED_WEB_CONTENT>>>" not in planner_prompt
    assert "[delimiter removed]" in planner_prompt


def test_over_long_interests_are_refused_rather_than_truncated() -> None:
    """Silently planning a trip for the first 300 characters would be stranger."""
    run = GoldenRun()

    with pytest.raises(service.InvalidGoalError):
        asyncio.run(
            service.create_plan(
                run.session, city="Paris", interests="x" * (MAX_INTERESTS_CHARS + 1)
            )
        )

    assert run.model_calls == 0
