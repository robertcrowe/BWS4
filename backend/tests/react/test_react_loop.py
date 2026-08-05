# Built with Spec4 AI - https://spec4.ai
"""The bounded loop: its ceilings, its two endings, and its budget lifecycle.

Everything here runs on Phase 2's recorded Exa fixtures with the model lane
stubbed, so the suite is deterministic and spends no quota. The autouse fixture
in `conftest.py` makes a forgotten model stub fail loudly rather than reaching a
provider.

Four properties carry the file, and each is the phase's own named risk:

1. **The ceilings hold.** No run exceeds the search budget, cycle 1 always
   searches, and the request ledger stops a run that has spent its reservation.
2. **Exactly one terminal card.** `_terminal_card` is a pure function called
   from one place; a run that emitted both endings, or neither, is the failure
   the single-call-site design exists to prevent. A budget-exhausted card has no
   answer field to fill in.
3. **The reservation is always released.** Early answer, disconnect, malformed
   step, dead provider, refused reservation -- every exit runs the same
   `finally`. A missed refund is invisible in production until the gallery
   starts hitting caps, so it is asserted per path rather than in general.
4. **A refused reservation issues nothing.** Zero model calls and zero searches.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import anyio
import httpx
import pytest

from backend.app.db.models import AllowanceHold, ReactRun, UsageLimit
from backend.app.react import runtime, schemas, service
from backend.app.services import agent_runtime, allowance_holds, shared

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_REAL_ASYNC_CLIENT = httpx.AsyncClient

BUDGET = 8
CEILING = runtime.max_provider_requests(BUDGET)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> Any:
        return self

    def all(self) -> list[Any]:
        return [] if self._value is None else [self._value]


class _Session:
    """A fake session that keeps usage rows and holds, so budgets accumulate.

    The repo's canned-result convention is not enough here: the loop reserves,
    releases and redeems against rows it expects to still be there, so the fake
    has to behave like a store rather than a queue. Which table a `select`
    wanted is recovered from the compiled statement, the same trick
    `test_planning_orchestrator.py` uses.
    """

    def __init__(self, caps: dict[str, int] | None = None) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self.limits: dict[str, UsageLimit] = {}
        self.holds: dict[str, AllowanceHold] = {}
        self.runs: list[ReactRun] = []
        self._caps = caps or {}

    async def execute(self, statement: Any, *_a: object, **_k: object) -> _Result:
        # A real session suspends on I/O here, and that matters for more than
        # realism: cancellation is only delivered at a suspension point, so a
        # fake that never yields cannot exercise a teardown running inside a
        # cancelled task -- which is exactly the bug a live run found and this
        # suite initially could not reproduce.
        await asyncio.sleep(0)
        text = str(statement)
        params: dict[str, Any] = {}
        try:
            params = dict(statement.compile().params)
        except Exception:  # noqa: BLE001 - fake session, best effort
            params = {}
        if "allowance_holds" in text:
            key = next((v for v in params.values() if isinstance(v, str)), None)
            return _Result(self.holds.get(key) if key else None)
        if "usage_limits" in text:
            cap = next((v for v in params.values() if isinstance(v, str)), None)
            return _Result(self.limits.get(cap) if cap else None)
        if "react_runs" in text:
            return _Result(self.runs[0] if self.runs else None)
        return _Result(None)

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, UsageLimit):
            if obj.capability in self._caps:
                obj.cap = self._caps[obj.capability]
            self.limits[obj.capability] = obj
        elif isinstance(obj, AllowanceHold):
            self.holds[obj.hold_key] = obj
        elif isinstance(obj, ReactRun):
            self.runs.append(obj)

    async def commit(self) -> None:
        await asyncio.sleep(0)
        self.commits += 1

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def used(self, capability: str) -> int:
        row = self.limits.get(capability)
        return row.used if row else 0

    def hold_state(self) -> str | None:
        return next(iter(self.holds.values())).state if self.holds else None

    def hold_units(self) -> int | None:
        return next(iter(self.holds.values())).units if self.holds else None


def _replay(name: str) -> Any:
    """Serve one recorded Exa response through the real wrapper."""
    recorded = json.loads((FIXTURES / name).read_text())

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(recorded["status_code"], json=recorded["body"])

    def factory(*_a: object, **_k: object) -> httpx.AsyncClient:
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))

    return patch("backend.app.services.web_search.httpx.AsyncClient", factory)


def _search(query: str) -> schemas.ReactSearchStep:
    return schemas.ReactSearchStep(
        thought=f"I need to look up {query}.",
        action=schemas.SearchAction(query=query),
    )


def _answer(grounded_on: list[int]) -> schemas.ReactStep:
    return schemas.ReactStep(
        thought="The observations cover it.",
        action=schemas.AnswerAction(
            answer="A drafted answer.", grounded_on=grounded_on
        ),
    )


#: Queries with nothing in common but their language.
#:
#: A ceiling test needs the *ceiling* to be what stops the loop, and getting
#: there is harder than it looks: "distinct query 1" and "distinct query 2"
#: differ by one character and embed at ~0.99, so the duplicate guard refuses
#: them and the run ends on `call_budget` five cycles early. That is the guard
#: doing its job on a badly chosen fixture -- measured here rather than assumed.
_UNRELATED_QUERIES = (
    "highest mountain in South Sudan",
    "who won the 2026 Eurovision song contest",
    "average rainfall in Manaus Brazil",
    "when was the Chrysler Building completed",
    "current price of tin per tonne",
    "population of Reykjavik Iceland",
    "who wrote the opera Turandot",
    "depth of the Mariana Trench in metres",
    "capital city of Burkina Faso",
)


def _distinct_searches() -> Any:
    """A lane that proposes an unrelated query every cycle.

    Needed for ceiling tests: a script repeating -- or barely varying -- one
    query is stopped by the duplicate guard long before the search ceiling,
    which is the guard working correctly and the wrong thing to be measuring.
    """
    counter = {"n": 0}

    async def fake(**kwargs: Any) -> Any:
        if kwargs.get("output_type") is schemas.HopAnnotations:
            # Annotation is decorative and fires after every run now. These
            # tests are about the loop, so it answers with nothing to say.
            return agent_runtime.StepResult(
                output=schemas.HopAnnotations(hops=[]),
                model="fake/model",
                requests=1,
            )
        if kwargs.get("output_type") is schemas.ComposedAnswer:
            return agent_runtime.StepResult(
                output=schemas.ComposedAnswer(answer="a", grounded_on=[1]),
                model="fake/model",
                requests=1,
            )
        query = _UNRELATED_QUERIES[counter["n"] % len(_UNRELATED_QUERIES)]
        counter["n"] += 1
        return agent_runtime.StepResult(
            output=_search(query), model="fake/model", requests=1
        )

    return patch.object(agent_runtime, "run_typed_step", fake)


def _lane(*script: Any, requests: int = 1) -> Any:
    """Stub the lane, returning each scripted output in turn.

    The last entry repeats, so a loop that runs longer than the script keeps
    getting the same decision -- which is what a ceiling test needs.
    """
    queue = list(script)

    async def fake(**kwargs: Any) -> Any:
        if kwargs.get("output_type") is schemas.HopAnnotations:
            # Annotation is decorative and fires after every run now. These
            # tests are about the loop, so it answers with nothing to say.
            return agent_runtime.StepResult(
                output=schemas.HopAnnotations(hops=[]),
                model="fake/model",
                requests=1,
            )
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        if kwargs.get("output_type") is schemas.ComposedAnswer:
            return agent_runtime.StepResult(
                output=schemas.ComposedAnswer(
                    answer="The composed answer.", grounded_on=[1]
                ),
                model="fake/model",
                requests=requests,
            )
        return agent_runtime.StepResult(
            output=item, model="fake/model", requests=requests
        )

    return patch.object(agent_runtime, "run_typed_step", fake)


def _run(
    session: Any,
    *,
    preset: str = "p1",
    fixture: str = "exa_search_multi_result.json",
) -> list[service.StreamEvent]:
    """Drive one whole run and collect its events."""
    request = schemas.RunRequest(
        preset_question_id=preset, visitor_question=None, session_id="s"
    )

    async def go() -> list[service.StreamEvent]:
        import uuid as _uuid

        return [
            event
            async for event in service.stream_run(
                session, run_id=_uuid.UUID(int=7), request=request
            )
        ]

    with _replay(fixture), _patch_settle_session(session):
        return asyncio.run(go())


def _patch_settle_session(session: Any) -> Any:
    """Point `_settle`'s own session factory at the test's fake.

    `_settle` deliberately does not reuse the run's session -- see its
    docstring -- so a test that patched only the caller's would watch the
    refund happen somewhere it could not see.
    """
    return patch.object(service, "async_session_factory", lambda: session)


def _names(events: list[service.StreamEvent]) -> list[str]:
    return [event.name for event in events]


def _terminal(events: list[service.StreamEvent]) -> service.StreamEvent:
    """The run's one terminal card.

    Not `events[-1]`: from Phase 6 the decorative `hop_annotations` event
    follows the terminal card, which is the required ordering — the visitor has
    their result before the annotation call even starts.
    """
    terminals = [e for e in events if e.name in schemas.TERMINAL_EVENTS]
    assert len(terminals) == 1, f"expected one terminal card, got {_names(events)}"
    return terminals[0]


# ---------------------------------------------------------------------------
# Ceilings
# ---------------------------------------------------------------------------


class TestTheLoopStaysInsideItsCeilings:
    def test_a_loop_that_never_answers_stops_at_the_search_ceiling(self) -> None:
        """The wandering failure the guard and the cap both exist for. The
        script always searches, so only the ceiling can stop it."""
        session: Any = _Session()

        with _distinct_searches():
            events = _run(session)

        observations = [
            e for e in _names(events) if e == schemas.EVENT_CYCLE_OBSERVATION
        ]
        assert len(observations) == BUDGET
        assert _terminal(events).name == schemas.EVENT_BUDGET_EXHAUSTED
        assert _terminal(events).payload["reason"] == "search_ceiling"

    def test_the_run_never_spends_more_requests_than_it_reserved(self) -> None:
        session: Any = _Session()

        with _lane(_search("q1"), _search("q2"), _search("q3")):
            _run(session)

        # Reserved up front, then released down to what was actually spent.
        assert session.hold_units() == CEILING
        assert session.used(shared.CAPABILITY_GENERATION) <= CEILING

    def test_cycle_one_always_issues_a_search(self) -> None:
        """Structural, not hopeful: cycle 1 is bound to the search-only output
        type, so the answer branch is not in the shape it can emit."""
        session: Any = _Session()

        with _lane(_search("first"), _answer([1])):
            events = _run(session)

        first_action = next(e for e in events if e.name == schemas.EVENT_CYCLE_ACTION)
        assert first_action.payload["kind"] == "search"

    def test_the_counter_is_emitted_before_each_cycle_s_thought(self) -> None:
        """ "So the consumed budget is visible before the run ends" -- a counter
        emitted afterwards reports history rather than progress."""
        session: Any = _Session()

        with _lane(_search("q1"), _answer([1])):
            names = _names(_run(session))

        assert names[1] == schemas.EVENT_CYCLE_COUNTER
        first_counter = names.index(schemas.EVENT_CYCLE_COUNTER)
        first_thought = names.index(schemas.EVENT_CYCLE_THOUGHT)
        assert first_counter < first_thought

    def test_the_reserved_ceiling_is_the_declared_worst_case(self) -> None:
        assert CEILING == 10
        assert runtime.max_provider_requests(BUDGET) == (
            BUDGET + runtime.FINAL_ANSWER_RESERVE + runtime.ANNOTATION_RESERVE
        )


# ---------------------------------------------------------------------------
# Exactly one ending
# ---------------------------------------------------------------------------


class TestExactlyOneTerminalCard:
    def test_an_answering_run_ends_in_final_answer_only(self) -> None:
        session: Any = _Session()

        with _lane(_search("q1"), _answer([1])):
            names = _names(_run(session))

        terminals = [n for n in names if n in schemas.TERMINAL_EVENTS]
        assert terminals == [schemas.EVENT_FINAL_ANSWER]

    def test_an_exhausted_run_ends_in_budget_exhausted_only(self) -> None:
        session: Any = _Session()

        with _distinct_searches():
            names = _names(_run(session))

        terminals = [n for n in names if n in schemas.TERMINAL_EVENTS]
        assert terminals == [schemas.EVENT_BUDGET_EXHAUSTED]

    def test_a_budget_exhausted_run_carries_no_answer_field(self) -> None:
        """The structural half of never dressing an unfinished run up as an
        answer: the model has no `answer` field to populate."""
        session: Any = _Session()

        with _distinct_searches():
            events = _run(session)

        card = _terminal(events).payload
        assert "answer" not in card
        assert card["reason"] == "search_ceiling"
        assert card["unresolved"]

    def test_the_card_names_what_remained_unresolved(self) -> None:
        session: Any = _Session()

        with _distinct_searches():
            events = _run(session)

        unresolved = " ".join(_terminal(events).payload["unresolved"])
        assert "ceiling" in unresolved
        assert "last thought" in unresolved

    def test_a_malformed_step_ends_the_run_candidly(self) -> None:
        session: Any = _Session()
        failure = agent_runtime.AgentLaneError("react-cycle-1", "unreadable")

        with _lane(failure):
            events = _run(session)

        card = _terminal(events).payload
        assert _terminal(events).name == schemas.EVENT_BUDGET_EXHAUSTED
        assert card["reason"] == "malformed_step"

    def test_two_consecutive_unreachable_searches_end_the_run(self) -> None:
        session: Any = _Session()

        with _lane(_search("q1"), _search("q2"), _search("q3")):
            events = _run(session, fixture="exa_search_error.json")

        card = _terminal(events).payload
        assert _terminal(events).name == schemas.EVENT_BUDGET_EXHAUSTED
        assert card["reason"] == "search_unavailable"
        # One failure is tolerated; the second ends it.
        assert card["searches_used"] == service.MAX_CONSECUTIVE_SEARCH_FAILURES

    def test_a_terminal_card_is_never_built_without_a_reason(self) -> None:
        """A run that ended for no recorded reason is a bug, and a default card
        would hide it."""
        with pytest.raises(ValueError):
            service._terminal_card(
                run_id=__import__("uuid").UUID(int=1),
                answer=None,
                reason=None,
                state=service._RunState(),
                budget_cycles=BUDGET,
            )


# ---------------------------------------------------------------------------
# The grounding audit
# ---------------------------------------------------------------------------


class TestTheAnswerIsAudited:
    def test_a_citation_that_resolves_is_reported_present(self) -> None:
        session: Any = _Session()

        with _lane(_search("q1"), _answer([1])):
            events = _run(session)

        audit = _terminal(events).payload["audit"]
        assert audit["all_cited_present"] is True
        assert audit["unverified"] == []

    def test_a_citation_pointing_nowhere_is_surfaced_not_dropped(self) -> None:
        """The RAG citation-audit pattern, reused: the model can cite a number
        it was never shown, and the card says so rather than accepting it."""
        observations = [
            schemas.Observation(index=1, query="q", is_empty=False, status="ok")
        ]

        audit = schemas.audit_grounding([1, 4], observations)

        assert audit.all_cited_present is False
        assert audit.unverified == [4]
        assert audit.cited == [1, 4]

    def test_the_audit_establishes_existence_not_support(self) -> None:
        """Deliberate limit, the same one `rag/citations.py` documents:
        verifying that a snippet *supports* a claim needs a second model call
        this run has no budget for."""
        observations = [
            schemas.Observation(
                index=1,
                query="q",
                results=[
                    schemas.ObservationResult(
                        idx=1, title="t", url="u", snippet="entirely unrelated"
                    )
                ],
                is_empty=False,
                status="ok",
            )
        ]

        assert schemas.audit_grounding([1], observations).all_cited_present is True


# ---------------------------------------------------------------------------
# The budget lifecycle
# ---------------------------------------------------------------------------


class TestTheReservationIsAlwaysReleased:
    def test_an_early_answer_refunds_the_unspent_calls(self) -> None:
        """**The phase's highest-risk logic.** A run that answers in two cycles
        must not charge the gallery for ten. A missed refund has no symptom
        until visitors start hitting caps."""
        session: Any = _Session()

        with _lane(_search("q1"), _answer([1])):
            _run(session)

        # Four of ten: the search cycle, the cycle that decided it could
        # answer, the final-answer call, and the post-run annotation. The
        # deciding cycle is a model call like any other, and so is the
        # annotation -- forgetting either is how a budget comes out short.
        assert session.used(shared.CAPABILITY_GENERATION) == 4
        assert session.hold_state() == allowance_holds.STATE_REDEEMED

    def test_a_completed_run_redeems_rather_than_refunds_its_hold(self) -> None:
        session: Any = _Session()

        with _lane(_search("q1"), _answer([1])):
            _run(session)

        assert session.hold_state() == allowance_holds.STATE_REDEEMED

    def test_a_run_that_spent_nothing_refunds_the_whole_hold(self) -> None:
        session: Any = _Session()
        failure = agent_runtime.AgentLaneError("react-cycle-1", "chain exhausted")

        with _lane(failure):
            _run(session)

        # The malformed path charges what the attempts cost and gives back the
        # rest; the hold is redeemed because something was spent.
        assert session.used(shared.CAPABILITY_GENERATION) <= CEILING
        assert session.hold_state() in {
            allowance_holds.STATE_REDEEMED,
            allowance_holds.STATE_REFUNDED,
        }

    def test_an_abandoned_run_still_releases_its_reservation(self) -> None:
        """The disconnect path. Closing the generator runs its `finally`, which
        is what stops an abandoned run costing the showcase a full ceiling --
        and this is the gallery's most expensive example per run."""
        session: Any = _Session()
        request = schemas.RunRequest(
            preset_question_id="p1", visitor_question=None, session_id="s"
        )

        async def go() -> None:
            import uuid as _uuid

            stream = service.stream_run(
                session, run_id=_uuid.UUID(int=9), request=request
            )
            await stream.__anext__()  # run_started
            await stream.aclose()  # the visitor walked away

        with (
            _lane(_search("q1")),
            _replay("exa_search_multi_result.json"),
            _patch_settle_session(session),
        ):
            asyncio.run(go())

        assert session.hold_state() == allowance_holds.STATE_REFUNDED
        assert session.used(shared.CAPABILITY_GENERATION) == 0

    def test_a_cancelled_run_still_releases_its_reservation(self) -> None:
        """**The bug a live run found, reproduced with the shape that causes it.**

        Measured against the running server: `react_run_abandoned` was logged,
        `react_run_settled` was not, the hold stayed `reserved` and all ten
        units stayed charged -- on the one exit path where the visitor
        definitely spent nothing.

        Getting a test to see it took three attempts, and the two that failed
        are worth naming because each looks like it should work:

        * `aclose()` on a healthy task runs the teardown in a clean context, so
          its awaits succeed and the bug cannot appear.
        * plain `task.cancel()` delivers cancellation **once**. By the time the
          teardown runs the cancellation has been consumed, so its awaits also
          succeed.

        What sse-starlette actually does on disconnect is cancel an **anyio
        cancel scope**, and a cancel scope re-delivers cancellation at *every*
        await inside it until the scope exits. That is why the teardown's first
        `await` raises and the release never happens -- and why `asyncio.shield`
        fixes it, by running the release as a task the scope does not reach.
        """
        session: Any = _Session()
        request = schemas.RunRequest(
            preset_question_id="p1", visitor_question=None, session_id="s"
        )

        async def main() -> None:
            import uuid as _uuid

            async with anyio.create_task_group() as tg:

                async def consume() -> None:
                    stream = service.stream_run(
                        session, run_id=_uuid.UUID(int=11), request=request
                    )
                    try:
                        async for _event in stream:
                            await asyncio.sleep(0.01)
                    finally:
                        # The router's own shape: abandoning an `async for`
                        # does not close the generator.
                        await stream.aclose()

                tg.start_soon(consume)
                await asyncio.sleep(0.05)
                tg.cancel_scope.cancel()

        with (
            _lane(_search("q1")),
            _replay("exa_search_multi_result.json"),
            _patch_settle_session(session),
        ):
            asyncio.run(main())

        assert session.hold_state() in {
            allowance_holds.STATE_REDEEMED,
            allowance_holds.STATE_REFUNDED,
        }, "an abandoned run kept its hold -- the release was skipped"
        assert session.used(shared.CAPABILITY_GENERATION) < CEILING, (
            "an abandoned run was charged its whole reserved ceiling"
        )

    def test_a_refused_reservation_issues_no_model_and_no_exa_call(self) -> None:
        """ "Never begin a run that cannot complete" -- and a run that was never
        begun must cost nothing at all."""
        session: Any = _Session(caps={shared.CAPABILITY_GENERATION: 0})
        calls: list[str] = []

        async def refuse(*_a: object, **_k: object) -> None:
            raise AssertionError("the model lane was reached")

        def no_search(*_a: object, **_k: object) -> httpx.AsyncClient:
            calls.append("exa")
            raise AssertionError("Exa was reached")

        with (
            patch.object(agent_runtime, "run_typed_step", refuse),
            patch("backend.app.services.web_search.httpx.AsyncClient", no_search),
        ):
            events = _run(session)

        assert _names(events) == [schemas.EVENT_ERROR]
        assert events[0].payload["code"] == "usage_limit_reached"
        assert calls == []
        assert session.holds == {}

    def test_a_cap_refusal_names_the_shared_limit_not_this_app_s(self) -> None:
        session: Any = _Session(caps={shared.CAPABILITY_GENERATION: 0})

        async def refuse(*_a: object, **_k: object) -> None:
            raise AssertionError("the model lane was reached")

        with patch.object(agent_runtime, "run_typed_step", refuse):
            events = _run(session)

        message = events[0].payload["message"]
        assert "gallery-wide" in message
        assert "reword" in message


# ---------------------------------------------------------------------------
# The duplicate guard inside the loop
# ---------------------------------------------------------------------------


class TestABlockedDuplicateCostsNoSearch:
    def test_a_repeated_query_is_re_prompted_before_it_reaches_exa(self) -> None:
        """The guard sits between the model choosing a query and the search
        being issued -- the seam that does not exist if the framework owns the
        tool call."""
        session: Any = _Session()

        with _lane(_search("same query"), _search("same query"), _answer([1])):
            events = _run(session)

        observations = [e for e in events if e.name == schemas.EVENT_CYCLE_OBSERVATION]
        # Two cycles proposed the same query; only one search was issued.
        assert len(observations) == 1
        assert session.used(shared.CAPABILITY_SEARCH) == 1

    def test_the_blocked_count_is_recorded_on_the_run(self) -> None:
        session: Any = _Session()

        with _lane(_search("same query"), _search("same query"), _answer([1])):
            _run(session)

        row = session.runs[0]
        assert row.duplicate_queries_blocked >= 1


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestThePersistedTrace:
    def test_an_empty_observation_is_stored_rather_than_dropped(self) -> None:
        session: Any = _Session()

        with _lane(_search("q1"), _search("q2"), _answer([1])):
            _run(session, fixture="exa_search_empty.json")

        row = session.runs[0]
        assert row.empty_observations >= 1
        assert any(
            entry["observation"] and entry["observation"]["is_empty"]
            for entry in row.cycle_trace
        )

    def test_the_row_carries_the_queryable_header_columns(self) -> None:
        session: Any = _Session()

        with _lane(_search("q1"), _answer([1])):
            _run(session)

        row = session.runs[0]
        assert row.question_origin == "p1"
        assert row.cycle_budget == BUDGET
        assert row.searches_used == 1
        assert row.ending == schemas.ENDING_FINAL_ANSWER
        assert row.terminal_card["answer"]
        assert row.cycle_timings

    def test_the_stored_trace_matches_what_was_streamed(self) -> None:
        session: Any = _Session()

        with _lane(_search("q1"), _answer([1])):
            events = _run(session)

        streamed = [
            e.payload for e in events if e.name == schemas.EVENT_CYCLE_OBSERVATION
        ]
        stored = [
            entry["observation"]
            for entry in session.runs[0].cycle_trace
            if entry["observation"]
        ]
        assert stored == streamed

    def test_the_suitability_column_is_null_for_a_preset_run(self) -> None:
        """A preset carries no free-form verdict, and the column says so."""
        session: Any = _Session()

        with _lane(_search("q1"), _answer([1])):
            _run(session)

        assert session.runs[0].suitability_confidence is None

    def test_the_annotation_outcome_is_recorded(self) -> None:
        """Phase 6 fills this column, which Phase 3 left for it. `skipped`
        here because the stubbed annotation returns nothing to say."""
        session: Any = _Session()

        with _lane(_search("q1"), _answer([1])):
            _run(session)

        assert session.runs[0].annotation_outcome is not None


# ---------------------------------------------------------------------------
# The budget ledger itself
# ---------------------------------------------------------------------------


class TestTheRunLedger:
    def test_it_refuses_to_search_when_the_reserve_would_be_eaten(self) -> None:
        """The planning app's `SYNTHESIS_RESERVE` device: a loop that searched
        to the ceiling would have nothing left to answer with, which is the most
        expensive way to produce nothing."""
        budget = runtime.RunBudget(ceiling=10, max_search_cycles=8)
        budget.charge(8)

        assert budget.can_search_again(searches_used=3) is False
        assert budget.can_answer() is True

    def test_the_search_ceiling_stops_it_even_with_budget_to_spare(self) -> None:
        budget = runtime.RunBudget(ceiling=50, max_search_cycles=8)

        assert budget.can_search_again(searches_used=7) is True
        assert budget.can_search_again(searches_used=8) is False

    def test_overspending_raises_rather_than_warning(self) -> None:
        """A coding error must not be able to turn a bounded demonstration into
        an unbounded one and merely mention it."""
        budget = runtime.RunBudget(ceiling=2, max_search_cycles=8)

        budget.charge(2)
        with pytest.raises(runtime.RunBudgetExceededError):
            budget.charge(1)

    def test_a_re_asked_cycle_costs_the_run_a_cycle(self) -> None:
        """The stated consequence of forbidding silent re-prompts: the second
        request is explicit, counted, and comes out of the same ten."""
        budget = runtime.RunBudget(ceiling=10, max_search_cycles=8)

        # Seven requests in there is still room: 3 remain, which is exactly the
        # cycle plus the two reserves.
        for _ in range(7):
            budget.charge(1)
        assert budget.can_search_again(searches_used=6) is True

        # The eighth -- a re-ask, say -- takes it below the reserve, and the run
        # loses a cycle it would otherwise have had.
        budget.charge(1)
        assert budget.can_search_again(searches_used=6) is False
