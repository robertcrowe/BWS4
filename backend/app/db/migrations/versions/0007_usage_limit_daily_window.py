# Built with Spec4 AI - https://spec4.ai
"""add daily window to usage_limits

Turns the per-capability caps into genuine daily budgets. Before this, `used`
only ever incremented, so GENERATION_DAILY_LIMIT/SEARCH_DAILY_LIMIT were
lifetime totals and a deployment stopped serving permanently once they were
reached.

Existing rows are backfilled to today and zeroed: their counters represent an
unbounded historical total, not today's usage, so carrying them forward would
start every capability at or near its cap.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "usage_limits",
        sa.Column(
            "window_start",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
    )
    # Historical counters are lifetime totals; start today's window clean.
    op.execute("UPDATE usage_limits SET used = 0, window_start = CURRENT_DATE")


def downgrade() -> None:
    op.drop_column("usage_limits", "window_start")
