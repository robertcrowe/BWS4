# Built with Spec4 AI - https://spec4.ai
"""router agreement and latency histories

Two append-only tables for the Router example app, shared across visitors so
the agreement history and the cost strip's "typical" search-route time survive
restarts and redeploys.

- `router_agreement_records`: one row per qualifying preset run, outcome
  constrained to agreed / disagreed / declined. Counts and rates are computed
  in SQL with a `GROUP BY preset_id`, hence the index.
- `router_latency_observations`: one row per real search-route run. The
  rolling median reads the most recent N rows for the route, hence the index
  on (route, created_at). The route column is constrained to the one route it
  may hold.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "router_agreement_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("preset_id", sa.String(length=8), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "outcome IN ('agreed', 'disagreed', 'declined')",
            name="ck_router_agreement_records_outcome",
        ),
    )
    op.create_index(
        "ix_router_agreement_records_preset_id",
        "router_agreement_records",
        ["preset_id"],
    )

    op.create_table(
        "router_latency_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("route", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "route = 'search_generation'",
            name="ck_router_latency_observations_route",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0", name="ck_router_latency_observations_duration"
        ),
    )
    op.create_index(
        "ix_router_latency_observations_route_created",
        "router_latency_observations",
        ["route", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_router_latency_observations_route_created",
        table_name="router_latency_observations",
    )
    op.drop_table("router_latency_observations")
    op.drop_index(
        "ix_router_agreement_records_preset_id",
        table_name="router_agreement_records",
    )
    op.drop_table("router_agreement_records")
