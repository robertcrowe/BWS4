# Built with Spec4 AI - https://spec4.ai
"""collab negotiation runs and peer messages

Two tables for the multi-agent collaboration example app.

`negotiation_runs` holds one immutable record per run. Stage payloads are
JSONB because they are read back whole -- nobody queries inside a bid. The two
call counts are **not** in that JSONB: they are top-level integer columns
because they are the capability's eval signal, and the alert that fires when a
run's negotiation stage count differs from six has to be a `WHERE` clause
rather than a scan. A number that is expensive to query is a number nobody
checks.

`peer_messages` holds one row per exchange, foreign-keyed to the run. This is
what makes the app's headline opacity claim provable rather than asserted: the
seller-to-seller count is a single SQL predicate over `sender` and `recipient`,
expected to be zero for every run ever recorded. The composite index on those
two columns exists for that query specifically. A client-side tally would only
prove what the client was shown.

JSONB rather than the `sa.JSON` used by revision 0004: on Postgres these are
different types, and JSONB is the one that stores compactly and can be indexed
if a later phase needs to reach inside a stage payload.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "negotiation_runs",
        # Shares its value with the allowance hold that reserved this run's
        # budget, so a run and its reservation are joinable.
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("weighting_id", sa.String(length=64), nullable=False),
        # Queryable top-level integers, deliberately not inside the JSONB.
        sa.Column(
            "negotiation_stage_call_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_model_calls_used",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("quotation_request", postgresql.JSONB(), nullable=True),
        sa.Column("opening_bids", postgresql.JSONB(), nullable=True),
        sa.Column("counter_offers", postgresql.JSONB(), nullable=True),
        sa.Column("final_bids", postgresql.JSONB(), nullable=True),
        sa.Column("award", postgresql.JSONB(), nullable=True),
        # Written only after the award stage completes.
        sa.Column("reveal", postgresql.JSONB(), nullable=True),
        sa.Column("sensitivity", postgresql.JSONB(), nullable=True),
        sa.Column("stage_timings", postgresql.JSONB(), nullable=True),
        sa.Column("degradation_flags", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_negotiation_runs_created_at", "negotiation_runs", ["created_at"]
    )
    op.create_index(
        "ix_negotiation_runs_scenario_id", "negotiation_runs", ["scenario_id"]
    )

    op.create_table(
        "peer_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("negotiation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("sender", sa.String(length=64), nullable=False),
        sa.Column("recipient", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("work_item", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # The opacity predicate: `WHERE sender IN (sellers) AND recipient IN
    # (sellers)`, expected to return nothing, forever.
    op.create_index(
        "ix_peer_messages_sender_recipient", "peer_messages", ["sender", "recipient"]
    )
    # Sequence is the run's own ordering, so it is unique per run rather than
    # globally.
    op.create_index(
        "ix_peer_messages_run_sequence",
        "peer_messages",
        ["run_id", "sequence"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_peer_messages_run_sequence", table_name="peer_messages")
    op.drop_index("ix_peer_messages_sender_recipient", table_name="peer_messages")
    op.drop_table("peer_messages")
    op.drop_index("ix_negotiation_runs_scenario_id", table_name="negotiation_runs")
    op.drop_index("ix_negotiation_runs_created_at", table_name="negotiation_runs")
    op.drop_table("negotiation_runs")
