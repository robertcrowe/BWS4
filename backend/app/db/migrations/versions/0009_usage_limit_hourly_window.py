# Built with Spec4 AI - https://spec4.ai
"""usage limit hourly window

Moves the shared usage gate from a per-UTC-day window to a per-UTC-hour one, so
a showcase that fills its allowance recovers at the top of the hour instead of
staying dark until 00:00 UTC. It also puts the shared gate on the same clock as
the orchestrated-subagents app's own per-session run counter, which is what lets
one screen explain both limits without two different reset stories.

`window_start` becomes a timestamptz truncated to the hour rather than a date.

**Counters are zeroed, not converted**, exactly as 0007 did when it introduced
the window at all, and for the same reason: a number that meant "used so far
today" does not mean "used so far this hour", so carrying it forward would start
every capability at a figure it never spent in the window it now belongs to.

The default expression is written `date_trunc('hour', now() AT TIME ZONE 'UTC')
AT TIME ZONE 'UTC'` rather than the shorter `date_trunc('hour', now())`, because
the short form truncates in the *session* time zone. The application always sets
this column explicitly, so the default is a safety net -- but a safety net that
silently depends on a connection setting is not one.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UTC_HOUR = "date_trunc('hour', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"


def upgrade() -> None:
    op.alter_column(
        "usage_limits",
        "window_start",
        existing_type=sa.Date(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="date_trunc('hour', window_start::timestamptz)",
        server_default=sa.text(_UTC_HOUR),
    )
    # A daily total is not an hourly one. Start the new window clean.
    op.execute(f"UPDATE usage_limits SET used = 0, window_start = {_UTC_HOUR}")


def downgrade() -> None:
    op.alter_column(
        "usage_limits",
        "window_start",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.Date(),
        existing_nullable=False,
        postgresql_using="window_start::date",
        server_default=sa.text("CURRENT_DATE"),
    )
    # Symmetric with upgrade(): an hourly total is not a daily one either.
    op.execute("UPDATE usage_limits SET used = 0, window_start = CURRENT_DATE")
