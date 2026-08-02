# Built with Spec4 AI - https://spec4.ai
"""The agent_loop_runtime: budget, gate, sequencing, and failure handling.

The four properties this file exists to pin, all of which are claims about
*code* rather than about model behaviour -- which is the point, since a planning
agent is the tier where trusting the model to police itself fails worst:

1. The quota gate is consulted before **every model call**, not every step.
2. The call ceiling is a deterministic counter that refuses the call over it.
3. A failed research step does not halt the run.
4. Nothing the visitor typed, and nothing a model wrote, is persisted.

The fake session follows the established convention -- ignore the SQL, return a
canned result -- with one addition: it holds a single `UsageLimit` per capability
so reservations *accumulate*, which is what makes counting them a real
measurement rather than a restatement of the code.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from backend.app.db.models import LanguageGenerationRequest, SearchQuery, ServiceLogEntry, UsageLimit
from backend.app.planning import agents, service
from backend.app.planning.budget import MAX_MODEL_CALLS, CallBudget, CallCeilingExceeded
from backend.app.planning.schemas import Plan, PlanStep, StepResult
from backend.app.services import shared
from backend.app.services.web_search import ExaResult

GOOD_PLAN = {
    "goal": "One day in Lisbon for street food and modern art",
    "steps": [
        {"index": 1, "kind": "research", "description": "Street food", "search_query": "street food Lisbon"},
        {"index": 2, "kind": "research", "description": "Modern art", "search_query": "modern art Lisbon"},
        {"index": 3, "kind": "synthesis", "description": "Compose the day", "search_query": None},
    ],
}

BAD_PLAN = {
    "goal": "One day in Lisbon",
    "steps": [
        {"index": 1, "kind": "synthesis", "description": "Compose first", "search_query": None},
        {"index": 2, "kind": "research", "description": "Then research", "search_query": "q"},
    ],
}

ITINERARY = {
    "city": "Lisbon",
    "blocks": [
        {"time_of_day": "morning", "activity": "Time Out Market", "why_it_matches": "food", "source_refs": [1]}
    ],
}

RESULTS = [ExaResult(title="Time Out Market", summary="A food hall.", source="https://a.test/1")]


class _Result:
    def __init__(self, scalar: object = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar


class _Session:
    """Fake session whose usage rows persist across reservations.

    The existing convention returns a fresh canned result per `execute()`, which
    would hand `reserve_capability` a new zeroed `UsageLimit` every time and make
    the counter untestable. Here one row per capability is kept and returned, so
    `used` accumulates exactly as it would in Postgres.
    """

    def __init__(self, caps: dict[str, int] | None = None) -> None:
        self.added: list[object] = []
        self.commit_count = 0
        self.limits: dict[str, UsageLimit] = {}
        self._caps = caps or {}
        self._pending: str | None = None

    async def execute(self, statement: object, *_args: object, **_kwargs: object) -> _Result:
        # The only select this code issues is usage_limits by capability, so the
        # capability is recovered from the compiled parameters rather than by
        # parsing SQL.
        capability = None
        try:
            params = statement.compile().params
            capability = next(iter(params.values()))
        except Exception:  # noqa: BLE001 - fake session, best effort
            capability = None

        if capability in self.limits:
            return _Result(self.limits[capability])
        return _Result(None)

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, UsageLimit):
            if obj.capability in self._caps:
                obj.cap = self._caps[obj.capability]
            self.limits[obj.capability] = obj

    async def commit(self) -> None:
        self.commit_count += 1

    def generation_used(self) -> int:
        limit = self.limits.get(shared.CAPABILITY_GENERATION)
        return limit.used if limit else 0

    def search_used(self) -> int:
        limit = self.limits.get(shared.CAPABILITY_SEARCH)
        return limit.used if limit else 0

    def summaries(self) -> list[str]:
        return [row.summary for row in self.added if isinstance(row, ServiceLogEntry)]


def _plan_model(*payloads: dict) -> FunctionModel:
    """A model that returns each plan payload in turn."""
    queue = list(payloads)

    def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, queue.pop(0))])

    return FunctionModel(behave)


def _execution_model(*, searches: bool = True, itinerary: dict | None = None) -> FunctionModel:
    """A model that searches once per research step, then composes an itinerary.

    Distinguishes the two step kinds by whether a `web_search` tool was offered
    on this request, which is what actually differs between them.
    """
    state = {"searched": False}

    def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool_names = {tool.name for tool in info.function_tools}
        output_tool = info.output_tools[0].name

        if "web_search" in tool_names:
            if searches and not state["searched"]:
                state["searched"] = True
                return ModelResponse(parts=[ToolCallPart("web_search", {"query": "a query"})])
            state["searched"] = False
            return ModelResponse(parts=[ToolCallPart(output_tool, {"summary": "Found a food hall."})])

        return ModelResponse(parts=[ToolCallPart(output_tool, itinerary or ITINERARY)])

    return FunctionModel(behave)


def _patch_model(model):
    return patch.object(agents.agent_runtime, "build_fallback_model", lambda chain=None, **_: model)


def _patch_search(results=RESULTS, error: Exception | None = None):
    async def fake_search(query: str):
        if error:
            raise error
        return results

    return patch.object(service, "search", fake_search)


def _collect(session, plan: Plan, *, calls_used: int = 0) -> list:
    async def run():
        return [
            event
            async for event in service.execute_plan(
                session, goal="goal", plan=plan, calls_used=calls_used
            )
        ]

    return asyncio.run(run())


def _plan_object() -> Plan:
    return Plan.model_validate(GOOD_PLAN)


class TestTheAllowanceAccountsForTheRetry:
    """The orchestrator must ask for a *per-attempt* figure it can afford twice.

    `_run_step` applies the allowance to each attempt, so a retried step spends
    up to `STEP_ATTEMPTS` times it. Reported live: a research step died on
    `UnexpectedModelBehavior` after 3 requests, its retry spent 3 more, the
    second step was skipped with `reason: "budget"`, and the run finished on 8
    of 9 -- one request from `CallCeilingExceeded` at the synthesis call, which
    would have ended it with no itinerary at all.

    Asserted at the **call site**, driving a real `execute_plan`. Checking the
    arithmetic through a helper that passes `attempts=` itself only proves
    `budget.py` can divide; it says nothing about whether `service.py` asks it
    to, and a first version of this suite passed with the argument deleted.
    """

    def test_the_orchestrator_asks_for_an_allowance_it_can_afford_twice(self) -> None:
        seen: list[dict] = []
        real = CallBudget.allowance

        def recording(self, step_limit, **kwargs):
            seen.append(kwargs)
            return real(self, step_limit, **kwargs)

        session = _Session()
        with (
            _patch_model(_execution_model()),
            _patch_search(),
            patch.object(CallBudget, "allowance", recording),
        ):
            _collect(session, _plan_object())

        assert seen, "no research step asked for an allowance"
        for kwargs in seen:
            assert kwargs.get("attempts") == service.STEP_ATTEMPTS, (
                "the allowance bounds one attempt but the step may make "
                f"{service.STEP_ATTEMPTS}"
            )

    def test_a_retried_step_cannot_spend_the_synthesis_reserve(self) -> None:
        """The near-miss, driven rather than computed: every research step
        fails once and retries, and synthesis must still have its reserve."""
        run = CallBudget()
        run.charge()  # the planner

        for _ in range(2):
            allowance = run.allowance(
                agents.RESEARCH_REQUEST_LIMIT,
                reserve=service.SYNTHESIS_RESERVE,
                attempts=service.STEP_ATTEMPTS,
            )
            for _ in range(allowance * service.STEP_ATTEMPTS):
                run.charge()

        assert run.remaining() >= service.SYNTHESIS_RESERVE


class TestCallBudget:
    def test_the_ceiling_diverges_from_the_capability_arithmetic_on_purpose(
        self,
    ) -> None:
        """The spec's runaway-loop mitigation says "the 8th model call is
        refused" -- 1 planner + 1 replan + 5 executor. This deployment refuses
        the 19th, and the divergence is recorded here rather than left to be
        rediscovered.

        The spec's figure counts *logical* calls and prices a research step at
        roughly one. A research step is tool-using: one request to emit each
        search, one to read the results, and possibly one more for PydanticAI's
        schema retry. At 7 the two research steps `MAX_RESEARCH_STEPS` permits
        could not both finish, so `allowance()` quietly shrank the second one
        below what it needed -- reported live, both steps dead on
        `StepRequestLimitExceeded` with the itinerary composed from nothing.

        What the mitigation actually protects -- a framework-level counter that
        an agent writing its own next steps cannot talk its way past -- is
        unchanged and is what the rest of this class tests.
        """
        assert MAX_MODEL_CALLS == 18

    def test_charging_up_to_the_ceiling_is_allowed(self) -> None:
        budget = CallBudget()
        for _ in range(MAX_MODEL_CALLS):
            budget.charge()

        assert budget.used == MAX_MODEL_CALLS
        assert budget.remaining() == 0

    def test_the_call_over_the_ceiling_is_refused(self) -> None:
        budget = CallBudget()
        for _ in range(MAX_MODEL_CALLS):
            budget.charge()

        with pytest.raises(CallCeilingExceeded):
            budget.charge()

    def test_a_refused_call_is_not_counted(self) -> None:
        # It never happened, so charging for it would make the counter lie to
        # whatever reports the run's cost.
        budget = CallBudget(ceiling=1)
        budget.charge()

        with pytest.raises(CallCeilingExceeded):
            budget.charge()

        assert budget.used == 1

    def test_a_step_allowance_never_exceeds_what_the_run_has_left(self) -> None:
        budget = CallBudget(ceiling=7, used=6)

        assert budget.allowance(step_limit=3) == 1


class TestPlanning:
    def test_a_good_plan_is_returned_with_the_calls_it_cost(self) -> None:
        session = _Session()

        with _patch_model(_plan_model(GOOD_PLAN)):
            outcome = asyncio.run(
                service.create_plan(session, city="Lisbon", interests="street food")
            )

        assert [step.kind for step in outcome.plan.steps] == ["research", "research", "synthesis"]
        assert outcome.replanned is False
        assert outcome.calls_used == 1

    def test_planning_executes_nothing(self) -> None:
        """The human-in-the-loop checkpoint, as an assertion.

        `create_plan` must spend exactly one model call and run no searches --
        the plan is for the visitor to review *before* anything happens.
        """
        session = _Session()

        with _patch_model(_plan_model(GOOD_PLAN)), _patch_search():
            asyncio.run(service.create_plan(session, city="Lisbon", interests="art"))

        assert session.generation_used() == 1
        assert session.search_used() == 0
        assert not [row for row in session.added if isinstance(row, SearchQuery)]

    def test_an_invalid_plan_triggers_exactly_one_replan(self) -> None:
        session = _Session()

        with _patch_model(_plan_model(BAD_PLAN, GOOD_PLAN)):
            outcome = asyncio.run(service.create_plan(session, city="Lisbon", interests="art"))

        assert outcome.replanned is True
        assert outcome.calls_used == 2

    def test_two_bad_plans_hard_fail_without_a_third_attempt(self) -> None:
        # The runaway this tier is most prone to: a validator/model loop that
        # never converges. Exactly one retry, then stop.
        session = _Session()

        with _patch_model(_plan_model(BAD_PLAN, BAD_PLAN)):
            with pytest.raises(service.PlanUnavailableError):
                asyncio.run(service.create_plan(session, city="Lisbon", interests="art"))

        assert session.generation_used() == 2

    def test_an_oversized_plan_is_trimmed_rather_than_replanned(self) -> None:
        oversized = {
            "goal": "One day in Lisbon",
            "steps": [
                {"index": i, "kind": "research", "description": f"r{i}", "search_query": f"q{i}"}
                for i in range(1, 5)
            ]
            + [{"index": 5, "kind": "synthesis", "description": "s", "search_query": None}],
        }
        session = _Session()

        with _patch_model(_plan_model(oversized)):
            outcome = asyncio.run(service.create_plan(session, city="Lisbon", interests="art"))

        assert outcome.calls_used == 1, "trimming is a code fix, not a model fix"
        assert outcome.trimmed_note is not None
        assert len(outcome.plan.steps) == 3

    def test_a_blank_city_is_rejected_before_any_model_call(self) -> None:
        session = _Session()

        with pytest.raises(service.InvalidGoalError):
            asyncio.run(service.create_plan(session, city="   ", interests="art"))

        assert session.generation_used() == 0

    def test_a_spent_generation_cap_is_reported_as_its_own_error(self) -> None:
        # Distinct from an unreachable model: this one resets at the top of the hour and
        # retrying cannot help.
        session = _Session(caps={shared.CAPABILITY_GENERATION: 0})

        with _patch_model(_plan_model(GOOD_PLAN)):
            with pytest.raises(service.UsageLimitReachedError):
                asyncio.run(service.create_plan(session, city="Lisbon", interests="art"))


class TestExecution:
    def test_steps_run_in_order_and_the_itinerary_comes_last(self) -> None:
        session = _Session()

        with _patch_model(_execution_model()), _patch_search():
            events = _collect(session, _plan_object())

        assert [event.kind for event in events] == ["step_result", "step_result", "itinerary"]
        assert [event.step_result.step_index for event in events[:2]] == [1, 2]

    def test_each_step_result_is_yielded_before_the_next_step_runs(self) -> None:
        """Sequential, not gathered -- which is what lets Phase 3 stream them.

        Recording how many searches had happened at each yield distinguishes a
        genuinely incremental run from one that computed everything and then
        replayed the results in order.
        """
        session = _Session()
        searches: list[str] = []

        async def counting_search(query: str):
            searches.append(query)
            return RESULTS

        observed: list[int] = []

        async def run():
            async for event in service.execute_plan(
                session, goal="goal", plan=_plan_object()
            ):
                if event.kind == "step_result":
                    observed.append(len(searches))

        with _patch_model(_execution_model()), patch.object(service, "search", counting_search):
            asyncio.run(run())

        assert observed == [1, 2]

    def test_a_failed_research_step_does_not_halt_the_run(self) -> None:
        """The capability's step-failure mitigation, exactly.

        The step is marked failed, the following step still runs, and the
        itinerary is still composed -- from what did succeed.
        """
        session = _Session()

        with _patch_model(_execution_model()), _patch_search(
            error=RuntimeError("exa exploded")
        ):
            with patch.object(service, "STEP_ATTEMPTS", 1):
                events = _collect(session, _plan_object())

        assert [event.kind for event in events] == ["step_result", "step_result", "itinerary"]

    def test_a_search_the_tool_could_not_run_marks_the_step_failed(self) -> None:
        from backend.app.services.web_search import ExaClientError

        session = _Session()

        with _patch_model(_execution_model()), _patch_search(error=ExaClientError("down")):
            events = _collect(session, _plan_object())

        results = [event.step_result for event in events if event.kind == "step_result"]
        assert all(result.status == "failed" for result in results)

    def test_a_search_that_ran_but_found_nothing_is_completed_not_failed(self) -> None:
        """The distinction the output shape cannot express on its own.

        An empty result set means the web had little to say, which is a finding.
        Marking it failed would tell the visitor the machinery broke.
        """
        session = _Session()

        with _patch_model(_execution_model()), _patch_search(results=[]):
            events = _collect(session, _plan_object())

        results = [event.step_result for event in events if event.kind == "step_result"]
        assert all(result.status == "completed" for result in results)
        assert all("no usable results" in result.summary for result in results)

    def test_sources_on_a_step_result_are_what_the_tool_returned(self) -> None:
        session = _Session()

        with _patch_model(_execution_model()), _patch_search():
            events = _collect(session, _plan_object())

        first = events[0].step_result
        assert [source.url for source in first.sources] == ["https://a.test/1"]

    def test_each_model_authored_search_is_metered_and_persisted(self) -> None:
        session = _Session()

        with _patch_model(_execution_model()), _patch_search():
            _collect(session, _plan_object())

        queries = [row for row in session.added if isinstance(row, SearchQuery)]
        assert len(queries) == 2
        assert session.search_used() == 2


class TestTheGateAndTheCeiling:
    def test_the_quota_gate_is_consulted_before_every_model_call(self) -> None:
        """Per call, not per step -- the assertion the design turns on.

        A research step makes two model requests (one to call the tool, one to
        read the results and answer). Two research steps plus the synthesis step
        is five requests, so a run that reserved per *step* would show three.
        """
        session = _Session()

        with _patch_model(_execution_model()), _patch_search():
            events = _collect(session, _plan_object())

        assert [event.kind for event in events][-1] == "itinerary"
        assert session.generation_used() == 5

    def test_a_fully_spent_budget_halts_rather_than_calling_anything(self) -> None:
        # Nothing left for even the synthesis call, so the run ends at the
        # ceiling with whatever it has.
        session = _Session()

        with _patch_model(_execution_model()), _patch_search():
            events = _collect(session, _plan_object(), calls_used=MAX_MODEL_CALLS)

        assert events[-1].kind == "halted"
        assert events[-1].code == "call_ceiling_reached"

    def test_a_tight_budget_skips_research_but_still_composes_an_itinerary(self) -> None:
        """The budget is spent on the output, not on the notes.

        A live run spent everything on research and halted with no itinerary at
        all. One call is now held back for synthesis, so a run short on budget
        degrades to a thinner itinerary that says which steps it lost -- which
        is the capability's gap-acknowledgement behaviour rather than a
        different failure.
        """
        session = _Session()

        with _patch_model(_execution_model()), _patch_search():
            events = _collect(session, _plan_object(), calls_used=MAX_MODEL_CALLS - 3)

        assert [event.kind for event in events] == ["step_result", "step_result", "itinerary"]

        skipped = events[1].step_result
        assert skipped.status == "failed"
        assert "budget" in skipped.summary

    def test_a_step_that_cannot_finish_is_never_started(self) -> None:
        """A one-request research step is a guaranteed failure that still costs a call.

        Starting it would spend the call the synthesis step is being held for,
        to learn something the budget arithmetic already knew.
        """
        session = _Session()

        with _patch_model(_execution_model()), _patch_search():
            events = _collect(session, _plan_object(), calls_used=MAX_MODEL_CALLS - 2)

        # One call left after the synthesis reserve is not enough for a research
        # step, so both are skipped and nothing but the synthesis call is spent.
        assert [event.kind for event in events] == ["step_result", "step_result", "itinerary"]
        assert session.generation_used() == 1
        assert session.search_used() == 0

    def test_the_step_timeout_exceeds_a_measured_step(self) -> None:
        """The specification says 30s; a real step was measured at 40.7s.

        The bound exists to end a hung step, and a threshold healthy steps trip
        does not do that -- it doubles their cost, because a timeout is retried.
        """
        assert service.STEP_TIMEOUT_SECONDS > 40

    def test_the_ceiling_refuses_the_call_without_spending_quota_on_it(self) -> None:
        # charge() runs before reserve_capability(), so a refused call costs
        # nothing. The counter and the cap must not disagree about what happened.
        session = _Session()

        with _patch_model(_execution_model()), _patch_search():
            _collect(session, _plan_object(), calls_used=MAX_MODEL_CALLS)

        assert session.generation_used() == 0

    def test_a_spent_generation_cap_mid_run_halts_with_its_own_code(self) -> None:
        session = _Session(caps={shared.CAPABILITY_GENERATION: 0})

        with _patch_model(_execution_model()), _patch_search():
            events = _collect(session, _plan_object())

        assert events[-1].kind == "halted"
        assert events[-1].code == "usage_limit_reached"


class TestSynthesisFailure:
    def test_a_failed_synthesis_halts_with_partial_results_preserved(self) -> None:
        def behave(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            tool_names = {tool.name for tool in info.function_tools}
            if "web_search" in tool_names:
                return ModelResponse(
                    parts=[ToolCallPart(info.output_tools[0].name, {"summary": "found"})]
                )
            raise RuntimeError("synthesis model is down")

        session = _Session()

        with _patch_model(FunctionModel(behave)), _patch_search():
            events = _collect(session, _plan_object())

        assert [event.kind for event in events] == ["step_result", "step_result", "halted"]
        assert events[-1].code == "synthesis_failed"
        assert "retrying runs only the final step" in events[-1].notice

    def test_retrying_synthesis_alone_reruns_nothing_else(self) -> None:
        session = _Session()
        results = [StepResult(step_index=1, status="completed", summary="Found a food hall.")]

        with _patch_model(_execution_model()), _patch_search():
            itinerary = asyncio.run(
                service.retry_synthesis(
                    session, goal="goal", plan=_plan_object(), results=results
                )
            )

        assert itinerary.city == "Lisbon"
        assert session.generation_used() == 1
        assert session.search_used() == 0


class TestPersistence:
    def test_no_authored_text_is_persisted(self) -> None:
        """This app keeps usage and outcomes, never content.

        `record_generation_request` writes prompt and response excerpts to the
        database; the capability's privacy section forbids retaining the goal or
        the itinerary, so this app must never call it -- the same rule the
        chained-calls app follows.
        """
        session = _Session()

        # Both halves of a run, each with the model that half actually uses:
        # the planner emits a Plan, the executor searches and emits an Itinerary.
        with _patch_model(_plan_model(GOOD_PLAN)), _patch_search():
            asyncio.run(service.create_plan(session, city="Reykjavik", interests="volcanoes"))

        with _patch_model(_execution_model()), _patch_search():
            _collect(session, _plan_object())

        assert not [row for row in session.added if isinstance(row, LanguageGenerationRequest)]

        for summary in session.summaries():
            assert "Reykjavik" not in summary
            assert "volcanoes" not in summary
            assert "Time Out Market" not in summary

    def test_the_run_is_still_logged_and_metered(self) -> None:
        # Unlogged is not unmetered, and unpersisted is not unobserved.
        session = _Session()

        with _patch_model(_execution_model()), _patch_search():
            _collect(session, _plan_object())

        assert session.summaries()
        assert session.generation_used() > 0
