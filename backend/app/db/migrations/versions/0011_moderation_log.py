# Built with Spec4 AI - https://spec4.ai
"""moderation log

Telemetry for the safety gate that screens free-form visitor questions.

**There is deliberately no column for the question itself.** The capability's
privacy requirement is that raw visitor text is not retained, and the way to
honour that is for the schema to make it impossible rather than for every writer
to remember. What is stored is a *salted* hash: enough to recognise the same
question arriving repeatedly, not enough to recover what it said. Unsalted, a
hash of a short question would be trivially reversible by guessing -- the space
of plausible questions is small enough to enumerate.

The rest is operational: which category came back, how confident, how long the
call took, and whether it failed closed. That last one matters most. A
moderation service that is unreachable must block rather than wave the question
through, and this column is how an operator can tell "nothing was flagged" apart
from "nothing was checked".

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "moderation_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Salted SHA-256, hex encoded. Never the question.
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("app_name", sa.String(length=100), nullable=False),
        # Null when nothing was flagged; the flagged category otherwise.
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        # True when the gate blocked because it could not reach the service, as
        # opposed to because the content was flagged. Without this, an outage
        # and a clean run look identical in the log.
        sa.Column(
            "failed_closed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Time is how this table is read: rates over a window, not lookups by row.
    op.create_index("ix_moderation_log_created_at", "moderation_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_moderation_log_created_at", table_name="moderation_log")
    op.drop_table("moderation_log")
