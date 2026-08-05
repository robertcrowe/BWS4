# Built with Spec4 AI - https://spec4.ai
"""The golden harness: the loop's structural invariants over every case.

## What this suite is evidence for, and what it is not

Every case drives the **real** `stream_run` with exactly two things replaced:
the model lane and Exa's HTTP transport. The budget ledger, the duplicate
guard, the observation builder, the terminal-card decision and the whole
reserve/redeem/refund lifecycle are production code, so what the grid pins are
properties of the code -- true whatever a model does.

What it deliberately cannot establish is how often a *live* model behaves like
a case's script. `loop_cases.json` says so in its own header, and the opt-in
live smoke marker in `test_react_live_smoke.py` is what covers that. A recorded
grid presented as a measurement of model quality would be the same over-claim
this app's annotation panel exists to prevent.

## The invariants are asserted over every case, never a sample

A spot check cannot prove an invariant. The failure being guarded against is a
regression that only shows up on the case nobody parametrised -- the empty
observation, the unreachable provider, the loop that circles. So the ordering,
ceiling, terminal-card and duplicate assertions are `parametrize`d across the
whole file, and adding a case to the JSON extends every one of them at once.

## Offline by construction, not by convention

`test_the_whole_grid_runs_with_no_provider_reachable` replays every case with
`build_fallback_model` patched to raise. "No credential configured" would be
weaker: this fails if any path reaches a provider at all.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from backend.app.react import annotation, presets, runtime, schemas, service
from backend.app.services import agent_runtime, allowance_holds, shared

GOLDEN = Path(__file__).resolve().parent / "golden"
CASES: dict[str, Any] = json.loads((GOLDEN / "loop_cases.json").read_text())
CASE_LIST: list[dict[str, Any]] = CASES["cases"]
CASE_IDS = [case["id"] for case in CASE_LIST]

BUDGET = 8
CEILING = runtime.max_provider_requests(BUDGET)


# ---------------------------------------------------------------------------
# Driving a case
# ---------------------------------------------------------------------------


def _scripted_lane(script: list[dict[str, Any]]) -> Any:
    """A lane that plays one case's authored model behaviour, in order.

    The last entry repeats, which is what a ceiling case needs: a loop asked to
    run longer than its script keeps making the same decision rather than
    falling off the end.

    The annotation and final-answer calls are answered separately, because they
    are different output types on the same lane -- and because a case's script
    describes the *cycle* decisions, not the composition that follows them.
    """
    queue = list(script)
    asked: list[Any] = []

    async def fake(**kwargs: Any) -> Any:
        output_type = kwargs.get("output_type")
        asked.append(output_type)
        if output_type is schemas.HopAnnotations:
            # Decorative and post-run. Cases here are about the loop, so it has
            # nothing to say; the annotation grid is its own file.
            return agent_runtime.StepResult(
                output=schemas.HopAnnotations(hops=[]), model="fake/model", requests=1
            )
        if output_type is schemas.ComposedAnswer:
            return agent_runtime.StepResult(
                output=schemas.ComposedAnswer(
                    answer="The composed answer.", grounded_on=[1]
                ),
                model="fake/model",
                requests=1,
            )

        entry = queue.pop(0) if len(queue) > 1 else queue[0]
        if entry["kind"] == "lane_error":
            raise agent_runtime.AgentLaneError("react-cycle", "unusable step")
        if entry["kind"] == "answer":
            step: Any = schemas.ReactStep(
                thought="The observations cover it.",
                action=schemas.AnswerAction(
                    answer="A drafted answer.", grounded_on=entry["grounded_on"]
                ),
            )
        else:
            step = schemas.ReactSearchStep(
                thought=f"I need to look up {entry['query']}.",
                action=schemas.SearchAction(query=entry["query"]),
            )
        return agent_runtime.StepResult(output=step, model="fake/model", requests=1)

    patcher = patch.object(agent_runtime, "run_typed_step", fake)
    # Exposed so a test can assert which output *type* the loop offered, not
    # merely which action the script happened to return.
    patcher.asked_output_types = asked  # type: ignore[attr-defined]
    return patcher


def _request(case: dict[str, Any]) -> schemas.RunRequest:
    origin = case["question_origin"]
    if origin == presets.CUSTOM_ORIGIN:
        return schemas.RunRequest(
            preset_question_id=None, visitor_question=case["question"], session_id="s"
        )
    return schemas.RunRequest(
        preset_question_id=origin, visitor_question=None, session_id="s"
    )


def _drive(
    case: dict[str, Any], session: Any, replay: Any, settle: Any
) -> tuple[list[service.StreamEvent], Any]:
    """Run one case end to end and return its events and the Exa replay."""
    request = _request(case)

    async def go() -> list[service.StreamEvent]:
        return [
            event
            async for event in service.stream_run(
                session, run_id=uuid.UUID(int=7), request=request
            )
        ]

    lane = _scripted_lane(case["script"])
    with replay(*case["exa_fixtures"]) as exa:
        with lane, settle(session):
            events = asyncio.run(go())
    exa.asked_output_types = lane.asked_output_types
    return events, exa


@pytest.fixture
def drive(react_session: Any, exa_replay: Any, settle_session: Any) -> Any:
    """Drive a case against a fresh fake session.

    Returns:
        A callable taking a case dict and returning `(events, session, exa)`.
    """

    def run(case: dict[str, Any], caps: dict[str, int] | None = None) -> Any:
        session = react_session(caps)
        events, exa = _drive(case, session, exa_replay, settle_session)
        return events, session, exa

    return run


def _names(events: list[service.StreamEvent]) -> list[str]:
    return [event.name for event in events]


def _terminal(events: list[service.StreamEvent]) -> service.StreamEvent:
    """The run's one terminal card.

    Not `events[-1]`: the decorative `hop_annotations` event legitimately
    follows the card, which is the required ordering -- the visitor has their
    result before the annotation call even starts.
    """
    terminal = [e for e in events if e.name in schemas.TERMINAL_EVENTS]
    assert len(terminal) == 1, (
        f"expected exactly one terminal event, got {_names(events)}"
    )
    return terminal[0]


# ---------------------------------------------------------------------------
# The structural invariants — instruction 3
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_each_cycle_runs_thought_then_action_then_observation(
    case: dict[str, Any], drive: Any
) -> None:
    """The order the app exists to show, asserted per cycle rather than per run."""
    events, _session, _exa = drive(case)

    seen: dict[int, list[str]] = {}
    for event in events:
        cycle = event.payload.get("cycle") or event.payload.get("index")
        if event.name in {
            schemas.EVENT_CYCLE_THOUGHT,
            schemas.EVENT_CYCLE_ACTION,
            schemas.EVENT_CYCLE_OBSERVATION,
        }:
            seen.setdefault(int(cycle), []).append(event.name)

    for cycle, order in seen.items():
        # An observation is absent when the cycle decided to answer or its
        # query was refused; what may never happen is a reordering.
        expected = [
            name
            for name in (
                schemas.EVENT_CYCLE_THOUGHT,
                schemas.EVENT_CYCLE_ACTION,
                schemas.EVENT_CYCLE_OBSERVATION,
            )
            if name in order
        ]
        assert order == expected, f"cycle {cycle} emitted {order}"


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_every_cycle_after_the_first_follows_an_observation(
    case: dict[str, Any], drive: Any
) -> None:
    """The claim the pattern rests on: the next step is chosen after a result."""
    events, _session, _exa = drive(case)

    thoughts = [e for e in events if e.name == schemas.EVENT_CYCLE_THOUGHT]
    for thought in thoughts[1:]:
        cycle = int(thought.payload["cycle"])
        position = events.index(thought)
        earlier = _names(events[:position])
        assert schemas.EVENT_CYCLE_OBSERVATION in earlier, (
            f"cycle {cycle} began with no observation before it"
        )


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_every_run_emits_exactly_one_terminal_event(
    case: dict[str, Any], drive: Any
) -> None:
    """Both endings, or neither, is the failure the single call site prevents."""
    events, _session, _exa = drive(case)
    card = _terminal(events)

    assert card.name in schemas.TERMINAL_EVENTS
    # The card is last, or second-to-last with only the decorative annotation
    # after it -- which is the required ordering: the visitor has their result
    # before the annotation call even starts.
    after = _names(events)[_names(events).index(card.name) + 1 :]
    assert after in ([], [schemas.EVENT_HOP_ANNOTATIONS]), after


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_no_run_exceeds_the_search_ceiling(case: dict[str, Any], drive: Any) -> None:
    """Eight searches, whatever the model asks for."""
    events, _session, _exa = drive(case)

    searches = [
        e
        for e in events
        if e.name == schemas.EVENT_CYCLE_ACTION and e.payload.get("kind") == "search"
    ]
    assert len(searches) <= BUDGET
    counters = [e for e in events if e.name == schemas.EVENT_CYCLE_COUNTER]
    for counter in counters:
        assert counter.payload["searches_used"] <= counter.payload["cycle_budget"]


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_cycle_one_always_searches(case: dict[str, Any], drive: Any) -> None:
    """The answer branch is not *offered* until an observation exists.

    Asserted on the output **type** the loop handed the lane, not on the action
    the script returned -- a script that happens to search first would satisfy
    the weaker form against a loop that had stopped constraining cycle 1 at all.
    A type, not a prompt instruction, which is why it holds even for the
    memory-answerable case where the model plainly knew the answer already.
    """
    events, _session, exa = drive(case)

    first = next((e for e in events if e.name == schemas.EVENT_CYCLE_ACTION), None)
    if first is None:
        pytest.skip("this case never reached a first action")
    assert first.payload["kind"] == "search"
    assert exa.asked_output_types[0] is schemas.ReactSearchStep


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_no_duplicate_query_survives_the_guard(
    case: dict[str, Any], drive: Any
) -> None:
    """Zero near-duplicates reach Exa, measured on what was actually issued."""
    events, _session, exa = drive(case)

    issued = [
        e.payload["query"] for e in events if e.name == schemas.EVENT_CYCLE_OBSERVATION
    ]
    assert len(issued) == len(set(issued))
    # And the guard's refusals cost a cycle, never a search: Exa saw exactly
    # the queries the observations record.
    assert exa.calls == len(issued)


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_observation_payloads_match_the_recording_exactly(
    case: dict[str, Any], drive: Any
) -> None:
    """Verbatim, field for field.

    The single mechanical guard on this app's honesty claim: the model authors
    the thought and the answer, never an observation. Any paraphrase,
    capitalisation fix or "summarised" suffix fails here.
    """
    events, _session, exa = drive(case)

    observations = [e for e in events if e.name == schemas.EVENT_CYCLE_OBSERVATION]
    for call, event in enumerate(observations):
        recorded = exa.recorded_results(call)
        results = event.payload["results"]
        assert len(results) == len(recorded)
        for got, source in zip(results, recorded, strict=True):
            assert got["title"] == source["title"]
            assert got["url"] == source["url"]
            assert got["published_date"] == source.get("publishedDate")
            assert got["snippet"] == source["summary"]


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_every_grounded_index_exists_in_the_run(
    case: dict[str, Any], drive: Any
) -> None:
    """A final answer may only cite observations this run actually made."""
    events, _session, _exa = drive(case)
    card = _terminal(events)
    if card.name != schemas.EVENT_FINAL_ANSWER:
        pytest.skip("this case does not end in an answer")

    available = {
        e.payload["index"] for e in events if e.name == schemas.EVENT_CYCLE_OBSERVATION
    }
    for index in card.payload["observation_cycles"]:
        assert index in available
    for index in card.payload["audit"]["cited"]:
        assert index in available


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_a_budget_exhausted_run_carries_no_answer(
    case: dict[str, Any], drive: Any
) -> None:
    """Structural: the card has no field an answer could be put in."""
    events, _session, _exa = drive(case)
    card = _terminal(events)
    if card.name != schemas.EVENT_BUDGET_EXHAUSTED:
        pytest.skip("this case ends in an answer")

    assert "answer" not in card.payload
    assert card.payload["unresolved"]


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_each_case_reaches_its_labelled_ending(
    case: dict[str, Any], drive: Any
) -> None:
    """The human label in the fixture file, including the four adversarial classes."""
    events, session, _exa = drive(case)
    card = _terminal(events)
    expected = case["expected"]

    assert card.name == expected["ending"], case.get("rationale", "")

    if "searches_used" in expected:
        assert card.payload["searches_used"] == expected["searches_used"]
    if "empty_observations" in expected:
        empty = [
            e
            for e in events
            if e.name == schemas.EVENT_CYCLE_OBSERVATION and e.payload["is_empty"]
        ]
        assert len(empty) == expected["empty_observations"]
    if expected.get("answer_absent"):
        assert "answer" not in card.payload
    if "duplicates_blocked_min" in expected:
        row = session.runs[0]
        assert row.duplicate_queries_blocked >= expected["duplicates_blocked_min"]


# ---------------------------------------------------------------------------
# The allowance lifecycle — instruction 4
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_every_run_reserves_the_whole_ceiling_before_its_first_cycle(
    case: dict[str, Any], drive: Any
) -> None:
    """Ten units, held before anything is promised."""
    _events, session, _exa = drive(case)

    assert session.hold_units() == CEILING == 10


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_the_unspent_remainder_comes_back(case: dict[str, Any], drive: Any) -> None:
    """The refund is what makes an eight-search budget affordable at all."""
    _events, session, _exa = drive(case)

    spent = session.used(shared.CAPABILITY_GENERATION)
    assert 0 < spent <= CEILING
    assert session.hold_state() == allowance_holds.STATE_REDEEMED


@pytest.mark.parametrize("case", CASE_LIST, ids=CASE_IDS)
def test_a_completed_run_never_redeems_more_than_ten_calls(
    case: dict[str, Any], drive: Any
) -> None:
    """The run-cost invariant behind the page's disclosed budget.

    The quota note beside the Start control promises a worst case of ten. This
    is the assertion that stops the code and the copy diverging -- and the
    matching `requests_redeemed` field on `react_run_summary` is what makes a
    divergence visible in production rather than only here.
    """
    _events, session, _exa = drive(case)

    assert session.used(shared.CAPABILITY_GENERATION) <= 10


def test_an_early_answer_refunds_the_bulk_of_its_reservation(drive: Any) -> None:
    """One search, one deciding cycle, one compose, one annotation."""
    case = next(c for c in CASE_LIST if c["id"] == "p2_early_answer_refund")
    _events, session, _exa = drive(case)

    spent = session.used(shared.CAPABILITY_GENERATION)
    assert spent == 4
    assert CEILING - spent == 6


def test_a_refused_reservation_issues_no_model_and_no_search_call(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """Nothing is spent by a run the gate would not allow to start."""
    case = next(c for c in CASE_LIST if c["id"] == "p1_two_hop_answer")
    session = react_session({shared.CAPABILITY_GENERATION: 0})
    calls = {"model": 0}

    async def counting(**kwargs: Any) -> Any:
        calls["model"] += 1
        raise AssertionError("a refused run must not reach the lane")

    request = _request(case)

    async def go() -> list[service.StreamEvent]:
        return [
            event
            async for event in service.stream_run(
                session, run_id=uuid.UUID(int=9), request=request
            )
        ]

    with exa_replay(*case["exa_fixtures"]) as exa:
        with patch.object(agent_runtime, "run_typed_step", counting):
            with settle_session(session):
                events = asyncio.run(go())

    assert _names(events) == [schemas.EVENT_ERROR]
    assert events[0].payload["code"] == "usage_limit_reached"
    assert calls["model"] == 0
    assert exa.calls == 0
    assert session.holds == {}


def test_a_disconnect_refunds_the_remainder(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """The path a live run found broken, and the only shape that reproduces it.

    sse-starlette cancels an **anyio cancel scope**, and a cancel scope
    re-delivers cancellation at every `await` inside it -- so a teardown that
    simply awaits its cleanup never performs it. `aclose()` on a healthy task
    runs the teardown in a clean context and plain `task.cancel()` delivers
    cancellation once, so neither reproduces it; a real task group does.
    """
    case = next(c for c in CASE_LIST if c["id"] == "p5_search_ceiling")
    session = react_session()

    async def go() -> None:
        import anyio

        request = _request(case)

        async with anyio.create_task_group() as group:

            async def consume() -> None:
                count = 0
                async for _event in service.stream_run(
                    session, run_id=uuid.UUID(int=11), request=request
                ):
                    count += 1
                    if count == 4:
                        group.cancel_scope.cancel()

            group.start_soon(consume)

    with exa_replay(*case["exa_fixtures"]):
        with _scripted_lane(case["script"]), settle_session(session):
            asyncio.run(go())

    assert session.hold_state() == allowance_holds.STATE_REDEEMED
    spent = session.used(shared.CAPABILITY_GENERATION)
    assert spent < CEILING, "an abandoned run must not be charged its whole ceiling"


def test_a_blocked_duplicate_consumes_no_search(drive: Any) -> None:
    """A refused query costs a cycle, never one of the eight searches."""
    case = next(c for c in CASE_LIST if c["id"] == "custom_circling")
    events, session, exa = drive(case)

    row = session.runs[0]
    assert row.duplicate_queries_blocked >= 1
    # Exa saw only the queries that survived the guard.
    assert exa.calls == row.searches_used
    assert row.searches_used < BUDGET


# ---------------------------------------------------------------------------
# The preset catalogue — instruction 6
# ---------------------------------------------------------------------------


def test_no_preset_stores_an_answer() -> None:
    """Structural, not a read-through of the file.

    Three of the five turn on facts that move, so a stored answer would be
    stale within a year and *wrong on screen while looking authoritative*. The
    failure mode is a well-meant convenience field, so the assertion is that no
    such field exists rather than that none is populated.
    """
    fields = set(presets.Preset.__dataclass_fields__)
    hop_fields = set(presets.PresetHop.__dataclass_fields__)

    for name in fields | hop_fields:
        assert "answer" not in name.lower(), name

    published = service.public_presets().model_dump()
    blob = json.dumps(published).lower()
    assert '"answer"' not in blob


def test_all_five_presets_parse_into_the_typed_catalogue() -> None:
    """Five entries, each with hops that agree with their own metadata."""
    assert len(presets.PRESETS) == 5
    for preset in presets.PRESETS:
        assert preset.hop_count == len(preset.expected_hops)
        assert preset.question.strip()
        if preset.guaranteed_fully_observed:
            assert all(hop.requires_observation for hop in preset.expected_hops)


# ---------------------------------------------------------------------------
# The suite's own guarantee
# ---------------------------------------------------------------------------


def test_the_whole_grid_runs_with_no_provider_reachable(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """Offline by construction: any path reaching a provider fails loudly."""
    with patch.object(
        agent_runtime,
        "build_fallback_model",
        lambda *_a, **_k: pytest.fail("the grid reached a real provider"),
    ):
        for case in CASE_LIST:
            session = react_session()
            events, _exa = _drive(case, session, exa_replay, settle_session)
            assert _terminal(events).name == case["expected"]["ending"]


def test_the_fixture_file_says_it_is_not_a_live_recording() -> None:
    """The disclaimer is part of the evidence, so it is asserted like one."""
    assert "NOT captured from a live provider" in CASES["_how_it_was_built"]
    assert "live smoke" in CASES["_how_it_was_built"]


def test_the_grid_covers_every_adversarial_class_the_specification_names() -> None:
    """Single-hop, unanswerable, ambiguous and memory-answerable, each labelled."""
    classes = {case["class"] for case in CASE_LIST}

    assert {
        "adversarial_single_hop",
        "adversarial_unanswerable",
        "adversarial_ambiguous",
        "adversarial_memory_answerable",
    } <= classes
    # Both endings are exercised, or the grid would be proving one branch.
    endings = {case["expected"]["ending"] for case in CASE_LIST}
    assert endings == {schemas.ENDING_FINAL_ANSWER, schemas.ENDING_BUDGET_EXHAUSTED}


def test_every_case_carries_a_rationale_for_its_label() -> None:
    """Ground truth auditable in diff, per instruction 10."""
    for case in CASE_LIST:
        assert case.get("rationale", "").strip(), case["id"]


def test_the_annotation_outcome_is_classified_in_one_place() -> None:
    """The persisted column and the telemetry summary cannot disagree."""
    assert annotation.outcome_of(None) == annotation.OUTCOME_UNAVAILABLE
    empty = schemas.AnnotationResult(
        hops=[], all_hops_observed=False, observed_count=0, recalled_count=0
    )
    assert annotation.outcome_of(empty) == annotation.OUTCOME_SKIPPED
