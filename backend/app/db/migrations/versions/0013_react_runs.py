# Built with Spec4 AI - https://spec4.ai
"""react loop runs

One table for the ReAct loop example app, written once at run end and read
back whole by `GET /api/react/run/{run_id}`.

The split between top-level columns and JSONB follows revision 0012's reasoning
and the stack spec's own words for this collection: **reading a whole trace by
run_id is the only read pattern the feature has**, so the cycles, the terminal
card, the hop annotations and the per-cycle timings are JSONB -- nobody queries
inside a cycle. The eval signal is the opposite case: `searches_used` against
`cycle_budget`, the ending distribution, the duplicate-query and empty-
observation counts are aggregated *across* runs to answer "are budget-exhausted
endings rising?", and that has to be a `GROUP BY` rather than a scan-and-parse.
A number that is expensive to query is a number nobody checks.

`ending` is nullable with a check constraint rather than an enum type: a row is
written only at run end so in practice it is always set, but a partial write
must not be able to claim an ending that is neither of the two the feature
promises. The constraint permits NULL and exactly the two values.

The four suitability columns and `annotation_outcome` are nullable and unwritten
until Phases 5 and 6. They are created here rather than in a later migration
because they are header columns of the same record, and splitting one record's
schema across three revisions buys nothing.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "react_runs",
        # The run_id the retrieval route takes, and the value the run's
        # allowance hold is keyed by, so a run and its reservation are
        # joinable.
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # A preset id ('p1'..'p5') or the literal 'custom'. Never the question
        # itself: a free-form question is visitor-written text, and this table
        # is telemetry as much as it is a trace store.
        sa.Column("question_origin", sa.String(length=32), nullable=False),
        # Queryable eval signal, deliberately not inside the JSONB.
        sa.Column(
            "searches_used", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("cycle_budget", sa.Integer(), nullable=False),
        sa.Column("ending", sa.String(length=32), nullable=True),
        sa.Column(
            "duplicate_queries_blocked",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "empty_observations",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        # The suitability verdict, populated only for custom questions from
        # Phase 5. Null on every preset run, which is the difference between
        # "no verdict was reached" and "no verdict was needed" -- read alongside
        # question_origin, which says which.
        sa.Column("suitability_chained_facts", sa.Boolean(), nullable=True),
        sa.Column("suitability_needs_live_info", sa.Boolean(), nullable=True),
        sa.Column("suitability_estimated_hops", sa.Integer(), nullable=True),
        sa.Column("suitability_confidence", sa.String(length=32), nullable=True),
        # Populated in Phase 6.
        sa.Column("annotation_outcome", sa.String(length=32), nullable=True),
        sa.Column("cycle_trace", postgresql.JSONB(), nullable=True),
        sa.Column("terminal_card", postgresql.JSONB(), nullable=True),
        sa.Column("hop_annotations", postgresql.JSONB(), nullable=True),
        sa.Column("cycle_timings", postgresql.JSONB(), nullable=True),
        # A run ends in exactly one of two states, both shown candidly. NULL is
        # permitted because the column exists before a run terminates; what is
        # refused is a third ending that the UI has no card for.
        sa.CheckConstraint(
            "ending IS NULL OR ending IN ('final_answer', 'budget_exhausted')",
            name="ck_react_runs_ending",
        ),
    )
    op.create_index("ix_react_runs_created_at", "react_runs", ["created_at"])
    # The ending distribution is the metric the capability asks to be watched,
    # and it is watched per question source: a rise in budget-exhausted endings
    # on presets means something different from a rise on free-form questions.
    op.create_index(
        "ix_react_runs_origin_ending", "react_runs", ["question_origin", "ending"]
    )


def downgrade() -> None:
    op.drop_index("ix_react_runs_origin_ending", table_name="react_runs")
    op.drop_index("ix_react_runs_created_at", table_name="react_runs")
    op.drop_table("react_runs")
