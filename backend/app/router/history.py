# Built with Spec4 AI - https://spec4.ai
"""The Router's two shared histories: recording rules, writers, SQL reads.

## Recording rules (pure functions)

- **Agreement row** only for a preset run the router decided -- routed or
  low-confidence. `agreed` when the dispatched route equals the expected route
  after a confident choice; `disagreed` when it does not (including an
  evaluator fallback, the router's own misroute); `declined` for every
  low-confidence run, including a tie-break that happens to land on the
  expected route, which earns no credit. Free text, comparison re-runs and
  malformed-decision fallbacks write nothing.
- **Latency row** only for a real search-route run: the search ran and an
  answer was composed, on a routed or low-confidence dispatch, never a re-run.
  A search that failed or found nothing did not do the work the baseline
  describes, so its time would understate "typical".

## Reads (SQL)

Counts, rates and the rolling median are computed in the database, and the
five-observation rule is applied there too: a cell with fewer than
`MIN_OBSERVATIONS` rows comes back with a null rate, and the baseline with a
null median. The statements use only portable SQL -- `CASE`, `COUNT`, window
functions -- so the same statements are tested against SQLite and run on Neon.
There is no hard-coded nominal latency anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Float,
    Select,
    case,
    cast,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import RouterAgreementRecord, RouterLatencyObservation
from backend.app.router.constants import (
    LATENCY_MEDIAN_WINDOW_N,
    MIN_OBSERVATIONS,
    SEARCH_GENERATION,
)
from backend.app.router.decision import LowConfidence, Malformed, Outcome
from backend.app.router.presets import PRESETS, RouterPreset


class AgreementOutcome(StrEnum):
    """What an agreement row records. `disagreed` is the card's "misrouted"."""

    AGREED = "agreed"
    DISAGREED = "disagreed"
    DECLINED = "declined"


def agreement_row(
    *,
    preset: RouterPreset | None,
    outcome: Outcome,
    dispatched_route: str,
    is_rerun: bool = False,
) -> AgreementOutcome | None:
    """Decide the agreement row a run writes, if any.

    Args:
        preset: The preset, or None for free text.
        outcome: The run's outcome.
        dispatched_route: Where the request was finally dispatched.
        is_rerun: True for a comparison re-run.

    Returns:
        The outcome to record, or None when the run writes no agreement row.
    """
    if preset is None or is_rerun or isinstance(outcome, Malformed):
        return None
    if isinstance(outcome, LowConfidence):
        return AgreementOutcome.DECLINED
    if dispatched_route == preset.expected_route:
        return AgreementOutcome.AGREED
    return AgreementOutcome.DISAGREED


def latency_row(
    *,
    outcome: Outcome,
    dispatched_route: str,
    answered: bool,
    route_ms: int,
    is_rerun: bool = False,
) -> int | None:
    """Decide the latency row a run writes, if any.

    Args:
        outcome: The run's outcome.
        dispatched_route: Where the request was finally dispatched.
        answered: True when the route searched and composed an answer.
        route_ms: The route's own measured time.
        is_rerun: True for a comparison re-run.

    Returns:
        The duration to record, or None when the run writes no latency row.
    """
    if is_rerun or isinstance(outcome, Malformed):
        return None
    if dispatched_route != SEARCH_GENERATION or not answered:
        return None
    return max(0, route_ms)


async def write_history(
    session: AsyncSession,
    *,
    preset_id: str | None,
    agreement: AgreementOutcome | None,
    latency_ms: int | None,
) -> None:
    """Append the run's history rows, if any, and commit.

    Args:
        session: The run generator's own session.
        preset_id: The preset, for the agreement row.
        agreement: The agreement outcome, or None.
        latency_ms: The search-route duration, or None.
    """
    if agreement is not None and preset_id is not None:
        session.add(RouterAgreementRecord(preset_id=preset_id, outcome=agreement.value))
    if latency_ms is not None:
        session.add(
            RouterLatencyObservation(route=SEARCH_GENERATION, duration_ms=latency_ms)
        )
    if agreement is not None or latency_ms is not None:
        await session.commit()


@dataclass(frozen=True)
class AgreementCell:
    """One preset's agreement counts, and its rate once it has enough rows.

    Attributes:
        preset_id: The preset, or None for the overall row.
        agreed: Agreed count.
        disagreed: Disagreed count.
        declined: Declined count.
        rate: agreed / (agreed + disagreed + declined), or None below the
            five-observation minimum.
    """

    preset_id: str | None
    agreed: int
    disagreed: int
    declined: int
    rate: float | None

    @property
    def total(self) -> int:
        """All three counts together: the rate's denominator."""
        return self.agreed + self.disagreed + self.declined


@dataclass(frozen=True)
class LatencyBaseline:
    """The cost strip's typical search-route time.

    Attributes:
        typical_ms: Median of the most recent window, or None below the
            five-observation minimum.
        sample_size: Rows the median rests on.
        window: The window size, `LATENCY_MEDIAN_WINDOW_N`.
    """

    typical_ms: int | None
    sample_size: int
    window: int = LATENCY_MEDIAN_WINDOW_N


@dataclass(frozen=True)
class HistorySnapshot:
    """Everything the agreement panel and the cost strip read."""

    presets: list[AgreementCell]
    overall: AgreementCell
    baseline: LatencyBaseline


def _count(outcome: AgreementOutcome) -> ColumnElement[int]:
    return func.coalesce(
        func.sum(case((RouterAgreementRecord.outcome == outcome.value, 1), else_=0)),
        0,
    )


def _rate() -> ColumnElement[float | None]:
    agreed = cast(
        func.sum(case((RouterAgreementRecord.outcome == "agreed", 1), else_=0)),
        Float,
    )
    total = func.count(RouterAgreementRecord.id)
    return case((total >= MIN_OBSERVATIONS, agreed / total), else_=None)


def agreement_by_preset_statement() -> Select[Any]:
    """Per-preset counts and rate, the rate null below the minimum.

    Returns:
        The statement.
    """
    return (
        select(
            RouterAgreementRecord.preset_id,
            _count(AgreementOutcome.AGREED),
            _count(AgreementOutcome.DISAGREED),
            _count(AgreementOutcome.DECLINED),
            _rate(),
        )
        .group_by(RouterAgreementRecord.preset_id)
        .order_by(RouterAgreementRecord.preset_id)
    )


def agreement_overall_statement() -> Select[Any]:
    """Overall counts and rate across every preset row.

    Returns:
        The statement.
    """
    return select(
        _count(AgreementOutcome.AGREED),
        _count(AgreementOutcome.DISAGREED),
        _count(AgreementOutcome.DECLINED),
        _rate(),
    )


def latency_baseline_statement(
    window: int = LATENCY_MEDIAN_WINDOW_N,
) -> Select[Any]:
    """Rolling median of the most recent `window` search-route rows, and n.

    The median is the mean of the middle one (odd n) or two (even n) rows,
    picked with `row_number()` over the window ordered by duration. The median
    is null below the minimum; the sample size is always returned.

    Args:
        window: How many of the most recent rows to take.

    Returns:
        The statement, yielding one row: (median or null, sample size).
    """
    recent = (
        select(RouterLatencyObservation.duration_ms)
        .where(RouterLatencyObservation.route == SEARCH_GENERATION)
        .order_by(
            RouterLatencyObservation.created_at.desc(),
            RouterLatencyObservation.id.desc(),
        )
        .limit(window)
        .subquery("recent")
    )
    ranked = select(
        recent.c.duration_ms,
        func.row_number().over(order_by=recent.c.duration_ms).label("rn"),
        func.count().over().label("n"),
    ).subquery("ranked")
    sample = select(func.count()).select_from(recent).scalar_subquery()
    middle = or_(
        ranked.c.rn == (ranked.c.n + 1) // 2, ranked.c.rn == (ranked.c.n + 2) // 2
    )
    median = (
        select(func.avg(cast(ranked.c.duration_ms, Float)))
        .where(middle)
        .scalar_subquery()
    )
    return select(
        case((sample >= MIN_OBSERVATIONS, median), else_=literal(None)),
        sample,
    )


async def read_latency_baseline(session: AsyncSession) -> LatencyBaseline:
    """Read the typical search-route time and its sample size.

    Args:
        session: An async session.

    Returns:
        The baseline; `typical_ms` is None below the minimum.
    """
    median, sample = (await session.execute(latency_baseline_statement())).one()
    return LatencyBaseline(
        typical_ms=round(median) if median is not None else None,
        sample_size=int(sample or 0),
    )


async def read_history(session: AsyncSession) -> HistorySnapshot:
    """Read per-preset agreement, the overall rate and the latency baseline.

    Every preset appears, with zero counts if it has no rows yet.

    Args:
        session: An async session.

    Returns:
        The snapshot.
    """
    rows = (await session.execute(agreement_by_preset_statement())).all()
    by_id = {
        row[0]: AgreementCell(
            preset_id=row[0],
            agreed=int(row[1]),
            disagreed=int(row[2]),
            declined=int(row[3]),
            rate=float(row[4]) if row[4] is not None else None,
        )
        for row in rows
    }
    presets = [
        by_id.get(preset.id, AgreementCell(preset.id, 0, 0, 0, None))
        for preset in PRESETS
    ]
    agreed, disagreed, declined, rate = (
        await session.execute(agreement_overall_statement())
    ).one()
    overall = AgreementCell(
        preset_id=None,
        agreed=int(agreed or 0),
        disagreed=int(disagreed or 0),
        declined=int(declined or 0),
        rate=float(rate) if rate is not None else None,
    )
    return HistorySnapshot(
        presets=presets,
        overall=overall,
        baseline=await read_latency_baseline(session),
    )
