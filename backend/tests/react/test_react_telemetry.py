# Built with Spec4 AI - https://spec4.ai
"""Per-run metrics, per-cycle spans, and nothing a visitor typed in either.

## The run summary is one record, not three

Answering "what did that run do?" from per-phase events means joining them by
run id. `react_run_summary` is the v5 `orchestrated_run_summary` shape applied
here: the ending, the budget consumption, the duplicate and empty counts, the
suitability verdict and the annotation outcome, in one row per run.

`requests_redeemed` is the disclosed-versus-actual check. The page beside the
Start control promises a worst case of ten calls; a divergence between that
promise and what a run really spends is visible in production because the run
logs both, not only because a test asserts it here.

## Spans answer a question the auto-integrations cannot

Sentry's auto-enabling integrations trace a request and its `httpx` calls. That
is enough while a request makes one outbound call, and this app's run is a
*sequence* -- so "which cycle was slow, and was it the model or the search?"
needs a cycle number the auto spans do not carry.

## Nothing here may carry the question

`send_default_pii` is off precisely so questions and search queries stay out of
Sentry, and the test scans **every value of every payload** rather than the
fields a handler happens to set -- so a field added later without thought is
caught rather than trusted.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import structlog

from backend.app.core import observability
from backend.app.react import annotation, runtime, schemas, service
from backend.app.services import agent_runtime, shared

GOLDEN = Path(__file__).resolve().parent / "golden"
CASES: list[dict[str, Any]] = json.loads((GOLDEN / "loop_cases.json").read_text())[
    "cases"
]

CUSTOM_QUESTION = "How old is the reigning marathon champion from Trondheim in Norway?"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _SpanRecorder:
    """Capture every span this run opened, with its op, name and data."""

    def __init__(self) -> None:
        self.spans: list[dict[str, Any]] = []

    @contextmanager
    def start_span(self, *, op: str, name: str) -> Iterator[Any]:
        entry: dict[str, Any] = {"op": op, "name": name, "data": {}}
        self.spans.append(entry)

        class _Active:
            def set_data(self, key: str, value: object) -> None:  # noqa: PLR6301
                entry["data"][key] = value

        yield _Active()

    def ops(self) -> list[str]:
        return [span["op"] for span in self.spans]


def _lane(script: list[dict[str, Any]]) -> Any:
    """The same scripted lane the golden grid uses, kept local to this file."""
    queue = list(script)

    async def fake(**kwargs: Any) -> Any:
        output_type = kwargs.get("output_type")
        if output_type is schemas.HopAnnotations:
            return agent_runtime.StepResult(
                output=schemas.HopAnnotations(
                    hops=[
                        schemas.HopAnnotation(
                            cycle_index=1,
                            fact="the first hop",
                            source="observation",
                            supporting_cycle=1,
                            note="Cycle 1's snippet carries it.",
                        )
                    ]
                ),
                model="fake/model",
                requests=1,
            )
        if output_type is schemas.ComposedAnswer:
            return agent_runtime.StepResult(
                output=schemas.ComposedAnswer(answer="An answer.", grounded_on=[1]),
                model="fake/model",
                requests=1,
            )
        entry = queue.pop(0) if len(queue) > 1 else queue[0]
        if entry["kind"] == "answer":
            step: Any = schemas.ReactStep(
                thought="Enough to answer.",
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

    return patch.object(agent_runtime, "run_typed_step", fake)


def _run(
    session: Any,
    replay: Any,
    settle: Any,
    *,
    case_id: str = "p1_two_hop_answer",
    request: schemas.RunRequest | None = None,
    suitability: schemas.QuestionSuitability | None = None,
) -> list[service.StreamEvent]:
    case = next(c for c in CASES if c["id"] == case_id)
    body = request or schemas.RunRequest(
        preset_question_id=case["question_origin"],
        visitor_question=None,
        session_id="s",
    )

    async def go() -> list[service.StreamEvent]:
        return [
            event
            async for event in service.stream_run(
                session,
                run_id=uuid.UUID(int=21),
                request=body,
                suitability=suitability,
            )
        ]

    with replay(*case["exa_fixtures"]):
        with _lane(case["script"]), settle(session):
            return asyncio.run(go())


def _verdict() -> schemas.QuestionSuitability:
    return schemas.QuestionSuitability(
        verdict="multi_hop_live",
        estimated_hops=3,
        requires_live_info=True,
        live_hop_description="the reigning champion",
        exercises_loop=True,
        confidence="high",
        visitor_message="This should exercise the loop.",
    )


# ---------------------------------------------------------------------------
# The per-run summary — instruction 13
# ---------------------------------------------------------------------------


def test_the_run_summary_carries_every_metric_the_stack_spec_names(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """One record per run, and it answers the operator's questions on its own."""
    session = react_session()
    with structlog.testing.capture_logs() as logs:
        _run(session, exa_replay, settle_session)

    summary = next(entry for entry in logs if entry["event"] == "react_run_summary")

    for field in (
        "run_id",
        "question_origin",
        "ending",
        "cycles",
        "searches_used",
        "cycle_budget",
        "duplicates_blocked",
        "empty_observations",
        "requests_spent",
        "requests_redeemed",
        "requests_reserved",
        "annotation_outcome",
        "suitability_verdict",
        "suitability_exercises_loop",
    ):
        assert field in summary, field

    assert summary["ending"] == schemas.ENDING_FINAL_ANSWER
    assert summary["cycle_budget"] == 8
    assert summary["requests_reserved"] == runtime.max_provider_requests(8) == 10


def test_the_summary_records_the_suitability_verdict_for_a_custom_question(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """The verdict, never the question it was about."""
    session = react_session()
    request = schemas.RunRequest(
        preset_question_id=None, visitor_question=CUSTOM_QUESTION, session_id="s"
    )

    with structlog.testing.capture_logs() as logs:
        _run(
            session,
            exa_replay,
            settle_session,
            request=request,
            suitability=_verdict(),
        )

    summary = next(entry for entry in logs if entry["event"] == "react_run_summary")
    assert summary["question_origin"] == "custom"
    assert summary["suitability_verdict"] == "multi_hop_live"
    assert summary["suitability_exercises_loop"] is True


def test_a_preset_run_reports_no_suitability_verdict(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """Null, not a fabricated value: no check ran, so there is nothing to report."""
    session = react_session()
    with structlog.testing.capture_logs() as logs:
        _run(session, exa_replay, settle_session)

    summary = next(entry for entry in logs if entry["event"] == "react_run_summary")
    assert summary["suitability_verdict"] is None
    assert summary["suitability_exercises_loop"] is None


def test_the_summary_reports_the_annotation_outcome(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """Success and retry rates are these two events aggregated over runs."""
    session = react_session()
    with structlog.testing.capture_logs() as logs:
        _run(session, exa_replay, settle_session)

    summary = next(entry for entry in logs if entry["event"] == "react_run_summary")
    assert summary["annotation_outcome"] == annotation.OUTCOME_ANNOTATED

    completed = next(
        entry for entry in logs if entry["event"] == "react_annotation_completed"
    )
    assert completed["attempts"] == 1


def test_the_ending_distribution_is_recoverable_from_the_summaries(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """Both endings are named in the same field, so a GROUP BY answers it."""
    endings: list[str] = []
    for case_id in ("p1_two_hop_answer", "p5_search_ceiling"):
        session = react_session()
        with structlog.testing.capture_logs() as logs:
            _run(session, exa_replay, settle_session, case_id=case_id)
        summary = next(e for e in logs if e["event"] == "react_run_summary")
        endings.append(summary["ending"])

    assert endings == [
        schemas.ENDING_FINAL_ANSWER,
        schemas.ENDING_BUDGET_EXHAUSTED,
    ]


# ---------------------------------------------------------------------------
# The run-cost invariant — instruction 15
# ---------------------------------------------------------------------------


def test_a_completed_run_never_redeems_more_than_the_disclosed_ten(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """The page promises ten. This is what stops the code and the copy diverging."""
    for case in CASES:
        session = react_session()
        with structlog.testing.capture_logs() as logs:
            _run(session, exa_replay, settle_session, case_id=case["id"])

        summary = next((e for e in logs if e["event"] == "react_run_summary"), None)
        if summary is None:
            continue
        assert summary["requests_redeemed"] <= 10, case["id"]
        assert session.used(shared.CAPABILITY_GENERATION) <= 10, case["id"]


def test_the_redeemed_count_is_logged_so_a_divergence_is_visible(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """Logged per run, not merely asserted in a test that production never runs."""
    session = react_session()
    with structlog.testing.capture_logs() as logs:
        _run(session, exa_replay, settle_session, case_id="p2_early_answer_refund")

    summary = next(e for e in logs if e["event"] == "react_run_summary")
    settled = next(e for e in logs if e["event"] == "react_run_settled")

    assert summary["requests_redeemed"] == 4
    assert settled["reserved"] == 10
    assert settled["refunded"] == 6


# ---------------------------------------------------------------------------
# Spans — instruction 14
# ---------------------------------------------------------------------------


def test_one_span_per_cycle_covering_its_model_call_and_its_search(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """The auto-integrations carry no cycle number, which is the whole point."""
    recorder = _SpanRecorder()
    session = react_session()

    with patch.object(observability, "sentry_sdk", recorder):
        events = _run(session, exa_replay, settle_session)

    cycles = {
        e.payload["cycle"] for e in events if e.name == schemas.EVENT_CYCLE_THOUGHT
    }
    cycle_spans = [s for s in recorder.spans if s["op"] == "react.cycle"]
    assert len(cycle_spans) == len(cycles)
    assert {span["data"]["cycle"] for span in cycle_spans} == cycles

    # Inside each: the model call, and the search when one was issued.
    assert recorder.ops().count("react.cycle.model") >= len(cycles)
    searches = [e for e in events if e.name == schemas.EVENT_CYCLE_OBSERVATION]
    assert recorder.ops().count("react.cycle.search") == len(searches)


def test_the_answer_and_annotation_calls_each_get_their_own_span(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """Per-run spans, so the two post-loop calls are attributable separately."""
    recorder = _SpanRecorder()
    session = react_session()

    with patch.object(observability, "sentry_sdk", recorder):
        _run(session, exa_replay, settle_session)

    assert recorder.ops().count("react.answer") == 1
    assert recorder.ops().count("react.annotation") == 1


def test_the_suitability_check_gets_its_own_span() -> None:
    """The check is a separate call and is measured as one."""
    from backend.app.react import suitability as suitability_module

    recorder = _SpanRecorder()
    suitability_module.reset_state()

    async def fake(**_kwargs: Any) -> Any:
        return agent_runtime.StepResult(
            output=_verdict(), model="fake/model", requests=1
        )

    with patch.object(observability, "sentry_sdk", recorder):
        with patch.object(agent_runtime, "run_typed_step", fake):
            asyncio.run(suitability_module.assess(CUSTOM_QUESTION, session_id="s"))

    assert recorder.ops().count("react.suitability") == 1


def test_observability_no_ops_cleanly_with_no_dsn() -> None:
    """No DSN means `sentry_sdk` was never initialized and every path is free.

    Asserted by exercising the real module rather than by reading the guard:
    these calls run inside exception handlers and in a streaming generator's
    `finally`, where a raise would turn a graceful degradation into a 500.
    """
    from backend.app.core.config import get_settings

    assert not get_settings().sentry_dsn

    with observability.span("react.cycle", "no-op span", cycle=1):
        pass
    observability.report_abort("react_annotation_failed", run_id="r")


# ---------------------------------------------------------------------------
# Scrubbing — instruction 16
# ---------------------------------------------------------------------------


def _long_words(text: str) -> list[str]:
    return [word.strip("?,.").lower() for word in text.split() if len(word) > 4]


def test_no_question_text_reaches_any_span(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """Every value of every span, not the fields a handler happens to set."""
    recorder = _SpanRecorder()
    session = react_session()
    request = schemas.RunRequest(
        preset_question_id=None, visitor_question=CUSTOM_QUESTION, session_id="s"
    )

    with patch.object(observability, "sentry_sdk", recorder):
        _run(
            session,
            exa_replay,
            settle_session,
            request=request,
            suitability=_verdict(),
        )

    serialised = json.dumps(recorder.spans).lower()
    for word in _long_words(CUSTOM_QUESTION):
        assert word not in serialised, f"{word!r} reached a span payload"


def test_no_question_or_query_text_reaches_the_run_telemetry(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """The structlog record is scanned the same way, for the same reason.

    A field added later without thought is what this catches: scanning the
    whole serialised record rather than the columns that obviously should not
    hold it is the convention every other slice in this project follows.
    """
    session = react_session()
    request = schemas.RunRequest(
        preset_question_id=None, visitor_question=CUSTOM_QUESTION, session_id="s"
    )

    with structlog.testing.capture_logs() as logs:
        _run(
            session,
            exa_replay,
            settle_session,
            request=request,
            suitability=_verdict(),
        )

    react_logs = [e for e in logs if str(e.get("event", "")).startswith("react_")]
    serialised = json.dumps(react_logs, default=str).lower()
    for word in _long_words(CUSTOM_QUESTION):
        assert word not in serialised, f"{word!r} reached the telemetry"


def test_no_snippet_text_reaches_a_span(
    react_session: Any, exa_replay: Any, settle_session: Any
) -> None:
    """Observation snippets are third-party web content and stay out too."""
    recorder = _SpanRecorder()
    session = react_session()

    with patch.object(observability, "sentry_sdk", recorder):
        events = _run(session, exa_replay, settle_session)

    serialised = json.dumps(recorder.spans).lower()
    for event in events:
        if event.name != schemas.EVENT_CYCLE_OBSERVATION:
            continue
        for result in event.payload["results"]:
            for word in _long_words(result["snippet"])[:6]:
                assert word not in serialised, f"{word!r} reached a span payload"


def test_the_span_helper_documents_the_rule_it_depends_on() -> None:
    """The constraint is a convention, so it is written where a caller reads it."""
    assert "Pass no visitor text" in (observability.span.__doc__ or "")
