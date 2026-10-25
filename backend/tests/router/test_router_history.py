# Built with Spec4 AI - https://spec4.ai
"""The Router's histories: migration, recording rules, SQL reads, cost strip.

The SQL is portable by design, so the real statements run here against an
in-memory SQLite database -- the counts, the rate's three-way denominator, the
five-observation rule, and the rolling median's window are all checked on
actual rows rather than on a mock.
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.db.models import RouterAgreementRecord, RouterLatencyObservation
from backend.app.main import app
from backend.app.router import classifier, history, service
from backend.app.router.classifier import Classification, RoutingDecision
from backend.app.router.constants import LATENCY_MEDIAN_WINDOW_N
from backend.app.router.cost_strip import SAVED_NOTHING, build_cost_strip
from backend.app.router.decision import LowConfidence, Malformed, Routed, decide
from backend.app.router.history import (
    AgreementCell,
    AgreementOutcome,
    HistorySnapshot,
    LatencyBaseline,
    agreement_by_preset_statement,
    agreement_overall_statement,
    agreement_row,
    latency_baseline_statement,
    latency_row,
)
from backend.app.router.presets import RouterPreset, get_preset
from backend.app.router.run_schemas import RunRequest
from backend.app.services.moderation import ModerationCategory, ModerationVerdict

client = TestClient(app)

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "app/db/migrations/versions/0014_router_histories.py"
)


def _preset(preset_id: str) -> RouterPreset:
    preset = get_preset(preset_id)
    assert preset is not None
    return preset


def _scores(**top: float) -> dict[str, float]:
    scores = {
        "deterministic_evaluator": 0.0,
        "single_call": 0.0,
        "retrieval": 0.0,
        "search_generation": 0.0,
    }
    scores.update(top)
    return scores


def _outcome(scores: dict[str, float], route: str) -> Routed | LowConfidence:
    decision = RoutingDecision.model_validate(
        {"scores": scores, "route": route, "rationale": "r", "expression": None}
    )
    outcome = decide(Classification(decision=decision, model="m", elapsed_ms=1))
    assert not isinstance(outcome, Malformed)
    return outcome


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0014", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigration:
    def test_revision_follows_0013(self) -> None:
        module = _load_migration()
        assert module.revision == "0014"
        assert module.down_revision == "0013"

    def test_upgrade_then_downgrade(self) -> None:
        module = _load_migration()
        engine = create_engine("sqlite://")
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                module.upgrade()
            tables = set(inspect(connection).get_table_names())
            assert {"router_agreement_records", "router_latency_observations"} <= tables
            indexes = {
                index["name"]
                for index in inspect(connection).get_indexes(
                    "router_latency_observations"
                )
            }
            assert "ix_router_latency_observations_route_created" in indexes

            with Operations.context(context):
                module.downgrade()
            tables = set(inspect(connection).get_table_names())
            assert "router_agreement_records" not in tables
            assert "router_latency_observations" not in tables


# ---------------------------------------------------------------------------
# Recording rules
# ---------------------------------------------------------------------------


class TestAgreementRow:
    def test_agreed(self) -> None:
        outcome = _outcome(_scores(single_call=0.9), "single_call")
        assert (
            agreement_row(
                preset=_preset("p2"), outcome=outcome, dispatched_route="single_call"
            )
            is AgreementOutcome.AGREED
        )

    def test_disagreed(self) -> None:
        outcome = _outcome(_scores(retrieval=0.9), "retrieval")
        assert (
            agreement_row(
                preset=_preset("p5"), outcome=outcome, dispatched_route="retrieval"
            )
            is AgreementOutcome.DISAGREED
        )

    def test_evaluator_fallback_is_disagreed(self) -> None:
        # Router chose deterministic for p1, but the request went to single call.
        outcome = _outcome(
            _scores(deterministic_evaluator=0.9), "deterministic_evaluator"
        )
        assert (
            agreement_row(
                preset=_preset("p1"), outcome=outcome, dispatched_route="single_call"
            )
            is AgreementOutcome.DISAGREED
        )

    def test_lucky_tie_break_is_declined_and_earns_no_credit(self) -> None:
        outcome = _outcome(_scores(retrieval=0.6, search_generation=0.6), "retrieval")
        assert isinstance(outcome, LowConfidence)
        # p3 expects retrieval, and the tie-break lands on retrieval.
        assert (
            agreement_row(
                preset=_preset("p3"), outcome=outcome, dispatched_route="retrieval"
            )
            is AgreementOutcome.DECLINED
        )

    def test_free_text_writes_nothing(self) -> None:
        outcome = _outcome(_scores(single_call=0.9), "single_call")
        assert (
            agreement_row(preset=None, outcome=outcome, dispatched_route="single_call")
            is None
        )

    def test_malformed_writes_nothing(self) -> None:
        assert (
            agreement_row(
                preset=_preset("p2"),
                outcome=Malformed(failure="x"),
                dispatched_route="single_call",
            )
            is None
        )

    def test_rerun_writes_nothing(self) -> None:
        outcome = _outcome(_scores(single_call=0.9), "single_call")
        assert (
            agreement_row(
                preset=_preset("p2"),
                outcome=outcome,
                dispatched_route="single_call",
                is_rerun=True,
            )
            is None
        )


class TestLatencyRow:
    def _search(self) -> Routed | LowConfidence:
        return _outcome(_scores(search_generation=0.9), "search_generation")

    def test_answered_search_run_is_recorded(self) -> None:
        assert (
            latency_row(
                outcome=self._search(),
                dispatched_route="search_generation",
                answered=True,
                route_ms=4200,
            )
            == 4200
        )

    def test_other_routes_are_not(self) -> None:
        outcome = _outcome(_scores(retrieval=0.9), "retrieval")
        assert (
            latency_row(
                outcome=outcome, dispatched_route="retrieval", answered=True, route_ms=9
            )
            is None
        )

    def test_failed_or_empty_search_is_not(self) -> None:
        assert (
            latency_row(
                outcome=self._search(),
                dispatched_route="search_generation",
                answered=False,
                route_ms=900,
            )
            is None
        )

    def test_rerun_is_not(self) -> None:
        assert (
            latency_row(
                outcome=self._search(),
                dispatched_route="search_generation",
                answered=True,
                route_ms=4200,
                is_rerun=True,
            )
            is None
        )

    def test_malformed_is_not(self) -> None:
        assert (
            latency_row(
                outcome=Malformed(failure="x"),
                dispatched_route="search_generation",
                answered=True,
                route_ms=1,
            )
            is None
        )


# ---------------------------------------------------------------------------
# SQL, on real rows
# ---------------------------------------------------------------------------


@pytest.fixture
def db() -> Engine:
    engine = create_engine("sqlite://")
    RouterAgreementRecord.__table__.create(engine)  # type: ignore[attr-defined]
    RouterLatencyObservation.__table__.create(engine)  # type: ignore[attr-defined]
    return engine


def _agreements(engine: Engine, rows: list[tuple[str, str]]) -> None:
    with Session(engine) as session:
        session.add_all(
            RouterAgreementRecord(preset_id=preset, outcome=outcome)
            for preset, outcome in rows
        )
        session.commit()


def _latencies(engine: Engine, durations: list[int]) -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    with Session(engine) as session:
        session.add_all(
            RouterLatencyObservation(
                route="search_generation",
                duration_ms=duration,
                created_at=start + timedelta(minutes=i),
            )
            for i, duration in enumerate(durations)
        )
        session.commit()


class TestAgreementSql:
    def test_counts_and_rate_with_declined_in_the_denominator(self, db: Engine) -> None:
        _agreements(
            db,
            [("p1", "agreed")] * 3
            + [("p1", "disagreed")]
            + [("p1", "declined")]
            + [("p2", "agreed")] * 2,
        )
        with db.connect() as connection:
            rows = {
                row[0]: row
                for row in connection.execute(agreement_by_preset_statement())
            }

        preset_id, agreed, disagreed, declined, rate = rows["p1"]
        assert (agreed, disagreed, declined) == (3, 1, 1)
        assert rate == pytest.approx(3 / 5)  # declined counts in the denominator

    def test_below_five_is_counts_only(self, db: Engine) -> None:
        _agreements(db, [("p2", "agreed")] * 4)
        with db.connect() as connection:
            rows = {
                row[0]: row
                for row in connection.execute(agreement_by_preset_statement())
            }

        assert rows["p2"][1] == 4
        assert rows["p2"][4] is None

    def test_overall_rate(self, db: Engine) -> None:
        _agreements(
            db,
            [
                ("p1", "agreed"),
                ("p2", "agreed"),
                ("p3", "disagreed"),
                ("p4", "declined"),
            ],
        )
        with db.connect() as connection:
            agreed, disagreed, declined, rate = connection.execute(
                agreement_overall_statement()
            ).one()
        assert (agreed, disagreed, declined) == (2, 1, 1)
        assert rate is None  # four rows: below the minimum

        _agreements(db, [("p5", "agreed")])
        with db.connect() as connection:
            *_, rate = connection.execute(agreement_overall_statement()).one()
        assert rate == pytest.approx(3 / 5)

    def test_empty_history(self, db: Engine) -> None:
        with db.connect() as connection:
            assert connection.execute(agreement_overall_statement()).one() == (
                0,
                0,
                0,
                None,
            )


class TestLatencySql:
    def test_below_five_returns_sample_size_and_no_median(self, db: Engine) -> None:
        _latencies(db, [4000, 5000, 6000, 7000])
        with db.connect() as connection:
            median, sample = connection.execute(latency_baseline_statement()).one()
        assert median is None
        assert sample == 4

    def test_odd_median(self, db: Engine) -> None:
        _latencies(db, [9000, 1000, 5000, 3000, 7000])
        with db.connect() as connection:
            median, sample = connection.execute(latency_baseline_statement()).one()
        assert median == pytest.approx(5000)
        assert sample == 5

    def test_even_median(self, db: Engine) -> None:
        _latencies(db, [1000, 2000, 3000, 4000, 5000, 10000])
        with db.connect() as connection:
            median, sample = connection.execute(latency_baseline_statement()).one()
        assert median == pytest.approx(3500)
        assert sample == 6

    def test_only_the_most_recent_window_counts(self, db: Engine) -> None:
        # Three very old slow runs, then a full window of fast ones.
        _latencies(db, [99000] * 3 + [1000] * LATENCY_MEDIAN_WINDOW_N)
        with db.connect() as connection:
            median, sample = connection.execute(latency_baseline_statement()).one()
        assert sample == LATENCY_MEDIAN_WINDOW_N
        assert median == pytest.approx(1000)

    def test_small_window_parameter(self, db: Engine) -> None:
        _latencies(db, [100, 200, 300, 400, 500, 600, 700])
        with db.connect() as connection:
            median, sample = connection.execute(latency_baseline_statement(5)).one()
        assert sample == 5
        assert median == pytest.approx(500)  # the five most recent: 300..700


# ---------------------------------------------------------------------------
# Cost strip
# ---------------------------------------------------------------------------

FULL = LatencyBaseline(typical_ms=4800, sample_size=12)
SPARSE = LatencyBaseline(typical_ms=None, sample_size=2)


class TestCostStrip:
    def test_search_route_says_routing_saved_nothing(self) -> None:
        strip = build_cost_strip(
            route="search_generation",
            model_calls=1,
            searches=1,
            retrievals=0,
            route_ms=4300,
            overhead_calls=1,
            overhead_ms=800,
            baseline=FULL,
        )
        assert strip.saved_nothing
        assert SAVED_NOTHING in strip.notes
        assert strip.route_taken.measured_ms == 4300
        assert strip.baseline.typical_ms == 4800
        assert strip.baseline.sample_size == 12
        assert strip.overhead.model_calls == 1

    def test_deterministic_route_releases_a_unit_and_spends_no_model(self) -> None:
        strip = build_cost_strip(
            route="deterministic_evaluator",
            model_calls=0,
            searches=0,
            retrievals=0,
            route_ms=0,
            overhead_calls=1,
            overhead_ms=700,
            baseline=FULL,
            unit_released=True,
        )
        assert strip.route_taken.model_calls == 0
        assert strip.route_taken.searches == 0
        assert not strip.saved_nothing
        assert any("second reserved unit was released" in n for n in strip.notes)

    @pytest.mark.parametrize(
        ("route", "calls", "searches", "retrievals"),
        [("single_call", 1, 0, 0), ("retrieval", 1, 0, 1)],
    )
    def test_cheaper_routes_against_the_fixed_baseline(
        self, route: Any, calls: int, searches: int, retrievals: int
    ) -> None:
        strip = build_cost_strip(
            route=route,
            model_calls=calls,
            searches=searches,
            retrievals=retrievals,
            route_ms=1500,
            overhead_calls=1,
            overhead_ms=700,
            baseline=FULL,
        )
        assert (strip.baseline.model_calls, strip.baseline.searches) == (1, 1)
        assert strip.baseline.retrievals == 0
        assert strip.route_taken.retrievals == retrievals
        assert not strip.saved_nothing

    def test_below_five_omits_typical_time_with_a_note(self) -> None:
        strip = build_cost_strip(
            route="single_call",
            model_calls=1,
            searches=0,
            retrievals=0,
            route_ms=1500,
            overhead_calls=1,
            overhead_ms=700,
            baseline=SPARSE,
        )
        assert strip.baseline.typical_ms is None
        assert any("2 so far" in note for note in strip.notes)

    def test_a_rerun_shows_zero_overhead_and_does_not_claim_saved_nothing(self) -> None:
        strip = build_cost_strip(
            route="search_generation",
            model_calls=1,
            searches=1,
            retrievals=0,
            route_ms=4000,
            overhead_calls=0,
            overhead_ms=0,
            baseline=FULL,
        )
        assert strip.overhead.model_calls == 0
        assert not strip.saved_nothing


# ---------------------------------------------------------------------------
# The run writes history, and history never fails a run
# ---------------------------------------------------------------------------


async def _allow(_text: str, _context: str) -> ModerationVerdict:
    return ModerationVerdict(
        allowed=True, category=ModerationCategory.OK, visitor_message="ok"
    )


def _run(route: str, request: str, preset_id: str | None) -> dict[str, Any]:
    decision = RoutingDecision.model_validate(
        {
            "scores": _scores(**{route: 0.9}),
            "route": route,
            "rationale": "r",
            "expression": None,
        }
    )

    async def classify(_r: str, *, on_request: Any = None) -> Classification:
        if on_request is not None:
            await on_request()
        return Classification(decision=decision, model="m", elapsed_ms=700)

    async def scenario() -> dict[str, Any]:
        admitted = await service.admit(
            RunRequest(request=request, preset_id=preset_id, visit_id="v"),
            moderator=_allow,
        )
        events: dict[str, Any] = {}
        async for event in service.stream_run(admitted):
            events[event.name] = event.payload
        return events

    with patch.object(classifier, "classify", classify):
        return asyncio.run(scenario())


P4 = "Who won the most recent Formula 1 race?"


class TestRunHistory:
    def test_preset_search_run_writes_both_rows_and_carries_a_cost_strip(
        self, router_store: Any, stub_search: Any, stub_generation: Any
    ) -> None:
        store = router_store()
        events = _run("search_generation", P4, "p4")

        assert [(r.preset_id, r.outcome) for r in store.agreement_rows] == [
            ("p4", "agreed")
        ]
        assert len(store.latency_rows) == 1
        strip = events["run_end"]["cost_strip"]
        assert strip["saved_nothing"] is True
        assert strip["overhead"] == {"model_calls": 1, "measured_ms": 700}
        assert strip["route_taken"]["searches"] == 1
        assert strip["baseline"]["typical_ms"] is None
        assert strip["baseline"]["sample_size"] == 1

    def test_free_text_writes_no_agreement_row(
        self, router_store: Any, stub_search: Any, stub_generation: Any
    ) -> None:
        store = router_store()
        _run("search_generation", "What happened in tech news today?", None)

        assert store.agreement_rows == []
        assert len(store.latency_rows) == 1  # a real search-route run

    def test_typical_time_appears_from_five_observations(
        self, router_store: Any, stub_search: Any, stub_generation: Any
    ) -> None:
        store = router_store()
        for duration in (4000, 5000, 6000, 7000):
            store.latency_rows.append(
                RouterLatencyObservation(
                    route="search_generation", duration_ms=duration
                )
            )
        events = _run("search_generation", P4, "p4")

        baseline = events["run_end"]["cost_strip"]["baseline"]
        assert baseline["sample_size"] == 5
        assert baseline["typical_ms"] is not None

    def test_a_history_write_failure_does_not_fail_the_run(
        self, router_store: Any, stub_search: Any, stub_generation: Any
    ) -> None:
        store = router_store()

        async def broken(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("database went away")

        with patch.object(history, "write_history", broken):
            events = _run("search_generation", P4, "p4")

        assert events["run_end"]["ending"] == "routed_answer"
        assert store.rollbacks == 1


class TestHistoryEndpoint:
    def test_returns_cells_overall_and_baseline(self) -> None:
        snapshot = HistorySnapshot(
            presets=[
                AgreementCell("p1", 3, 1, 1, 0.6),
                AgreementCell("p2", 2, 0, 0, None),
            ],
            overall=AgreementCell(None, 5, 1, 1, 5 / 7),
            baseline=LatencyBaseline(typical_ms=4800, sample_size=9),
        )

        async def read(_session: Any) -> HistorySnapshot:
            return snapshot

        with patch.object(history, "read_history", read):
            body = client.get("/api/router/history").json()

        assert body["presets"][0] == {
            "preset_id": "p1",
            "agreed": 3,
            "disagreed": 1,
            "declined": 1,
            "total": 5,
            "rate": 0.6,
        }
        assert body["presets"][1]["rate"] is None
        assert body["overall"]["total"] == 7
        assert body["baseline"] == {
            "typical_ms": 4800,
            "sample_size": 9,
            "window": LATENCY_MEDIAN_WINDOW_N,
        }
        assert body["min_observations"] == 5

    def test_unreadable_history_is_a_503_not_invented_figures(self) -> None:
        async def down(_session: Any) -> HistorySnapshot:
            raise ConnectionError("down")

        with patch.object(history, "read_history", down):
            response = client.get("/api/router/history")

        assert response.status_code == 503
        assert "could not be read" in response.json()["detail"]
