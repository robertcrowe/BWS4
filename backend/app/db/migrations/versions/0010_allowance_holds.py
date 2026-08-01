# Built with Spec4 AI - https://spec4.ai
"""allowance holds

Reserve/redeem/refund records against the showcase-wide hourly usage gate.

The orchestrated-subagents run needs to know *before* it shows a delegation
decision that the whole three-call budget is available, because the capability's
named failure is allowance running out between the decision and the visitor's
dispatch confirmation -- leaving a plan on screen that can no longer be
executed. A hold answers that up front: either the three calls are reserved, or
the run is refused with a reason.

`used` on `usage_limits` alone cannot express this. It records what has been
spent, not what is promised, so two visitors could each be told there was room
for three calls when between them there was room for four.

The three states are the whole lifecycle: **reserved** when the budget is taken,
**redeemed** when the calls were actually made, **refunded** when the run failed
before spending them. Refunding is what stops a failed run costing the showcase
the same as a successful one.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "allowance_holds",
        # The run's own identifier, opaque to this table. A natural primary key
        # rather than a surrogate id precisely so a retried request cannot
        # reserve the same budget twice.
        sa.Column("hold_key", sa.String(length=64), primary_key=True),
        sa.Column("capability", sa.String(length=50), nullable=False),
        sa.Column("app_name", sa.String(length=100), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        # The usage window the hold is charged against. A hold does not outlive
        # its window: once the gate has rolled over, a reservation made against
        # the previous hour has nothing left to redeem.
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # Enforced in the database rather than only in Python: this table is the
        # ledger the gate trusts, and a fourth state written by some future
        # caller would be silently uncounted by every reader of the other three.
        sa.CheckConstraint(
            "state IN ('reserved', 'redeemed', 'refunded')",
            name="ck_allowance_holds_state",
        ),
    )
    # The lookup every reader performs: what is outstanding for this capability
    # in this window.
    op.create_index(
        "ix_allowance_holds_capability_window",
        "allowance_holds",
        ["capability", "window_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_allowance_holds_capability_window", table_name="allowance_holds")
    op.drop_table("allowance_holds")
