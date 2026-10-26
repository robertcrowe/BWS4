# Built with Spec4 AI - https://spec4.ai
"""Wire schemas for the Router slice's HTTP surface."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backend.app.router.constants import (
    DECISION_MARGIN,
    MIN_OBSERVATIONS,
    ROUTE_COST_ORDER,
    RouteId,
)
from backend.app.router.history import AgreementCell, HistorySnapshot
from backend.app.router.presets import PRESET_SET_VERSION, PRESETS, PairName, PairRole
from backend.app.router.state import RouteDescriptions


class PublicPreset(BaseModel):
    """One curated request as published to the client.

    Carries the expected route so agreement can be computed and explained;
    the visitor UI keeps it hidden until a run has been decided. Never an
    answer, because the catalogue holds none.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    request: str
    expected_route: RouteId
    reason: str
    pair: PairName | None
    pair_role: PairRole | None


class PublicRoute(BaseModel):
    """One route as the router is told it."""

    model_config = ConfigDict(frozen=True)

    id: RouteId
    label: str
    description: str
    cost_rank: int


class PresetsResponse(BaseModel):
    """Body of `GET /api/router/presets`.

    `route_descriptions_block` is the exact string the router prompt receives;
    the page renders it verbatim, and `route_descriptions_sha256` lets anyone
    check that what they see is what was hashed server-side.

    `available` is false while the route descriptions are not ready. The
    presets and fixed settings are still served then, but `route_descriptions`
    is empty and the block and its hash are null -- never invented text.
    """

    model_config = ConfigDict(frozen=True)

    available: bool
    presets: list[PublicPreset]
    set_version: str
    decision_margin: float
    cost_order: list[RouteId]
    route_descriptions: list[PublicRoute]
    route_descriptions_block: str | None
    route_descriptions_sha256: str | None


class RetryResponse(BaseModel):
    """Body of a successful `POST /api/router/retry`."""

    model_config = ConfigDict(frozen=True)

    available: bool


def public_presets(descriptions: RouteDescriptions | None) -> PresetsResponse:
    """Project the catalogue, fixed settings and route descriptions to the wire.

    Args:
        descriptions: The generated route descriptions, or None while they are
            not ready.

    Returns:
        Availability, the six presets, the catalogue version, the decision
        margin, the route cost order, and the four route descriptions with their
        exact block and its hash (empty and null while unavailable).
    """
    return PresetsResponse(
        available=descriptions is not None,
        presets=[
            PublicPreset(
                id=preset.id,
                request=preset.request,
                expected_route=preset.expected_route,
                reason=preset.reason,
                pair=preset.pairing.pair if preset.pairing else None,
                pair_role=preset.pairing.role if preset.pairing else None,
            )
            for preset in PRESETS
        ],
        set_version=PRESET_SET_VERSION,
        decision_margin=DECISION_MARGIN,
        cost_order=list(ROUTE_COST_ORDER),
        route_descriptions=[
            PublicRoute(
                id=route.id,
                label=route.label,
                description=route.description,
                cost_rank=route.cost_rank,
            )
            for route in (descriptions.routes if descriptions else ())
        ],
        route_descriptions_block=descriptions.block if descriptions else None,
        route_descriptions_sha256=descriptions.sha256 if descriptions else None,
    )


class AgreementCellOut(BaseModel):
    """One agreement-history cell. `rate` is null below the minimum."""

    preset_id: str | None
    agreed: int
    disagreed: int
    declined: int
    total: int
    rate: float | None


class BaselineOut(BaseModel):
    """The typical search-route time. `typical_ms` is null below the minimum."""

    typical_ms: int | None
    sample_size: int
    window: int


class HistoryResponse(BaseModel):
    """Body of `GET /api/router/history`."""

    presets: list[AgreementCellOut]
    overall: AgreementCellOut
    baseline: BaselineOut
    min_observations: int


def public_history(snapshot: HistorySnapshot) -> HistoryResponse:
    """Project a history snapshot onto the wire.

    Args:
        snapshot: The snapshot read from the database.

    Returns:
        The response body.
    """

    def cell(source: AgreementCell) -> AgreementCellOut:
        return AgreementCellOut(
            preset_id=source.preset_id,
            agreed=source.agreed,
            disagreed=source.disagreed,
            declined=source.declined,
            total=source.total,
            rate=source.rate,
        )

    return HistoryResponse(
        presets=[cell(item) for item in snapshot.presets],
        overall=cell(snapshot.overall),
        baseline=BaselineOut(
            typical_ms=snapshot.baseline.typical_ms,
            sample_size=snapshot.baseline.sample_size,
            window=snapshot.baseline.window,
        ),
        min_observations=MIN_OBSERVATIONS,
    )
