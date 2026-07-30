# Built with Spec4 AI - https://spec4.ai
"""add mode to language_generation_requests

The single-call example app introduces a second kind of generation call --
schema-constrained structured output alongside free text -- and without this
column the two are indistinguishable in the log. Same app, same model, same
prompt length; nothing recorded said whether a schema had been demanded, which
is the first thing you would want when investigating why structured responses
are failing validation.

Note what this migration deliberately does *not* do. The phase instruction
calls for "adding a language_generation_requests table and any needed
columns/indexes to service_log_entries and usage_limits". All three already
exist: `language_generation_requests` and `service_log_entries` (with its
timestamp index) came in 0005, and `usage_limits` gained the `window_start`
column it needs in 0007. Re-creating them would fail, and adding speculative
columns nothing reads would be worse than adding none. `mode` is the one field
this revision genuinely lacks.

Existing rows are backfilled to 'plain' rather than left null. That is a real
claim about history, not a convenience default: every row written before this
revision came from a caller with no structured path -- shared.generate_text or
the tool-use agent's synthesis -- with the sole exception of the RAG app, whose
answers *are* schema-validated and which is therefore backfilled separately
below. Guessing wrong on a whole table is worse than a nullable column, so the
two known populations are set explicitly.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "language_generation_requests",
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="plain"),
    )
    # The RAG app's answers are validated against rag.schemas.LlmAnswer, so
    # they were structured before this column existed to say so.
    op.execute(
        "UPDATE language_generation_requests SET mode = 'structured' "
        "WHERE app_name = 'RAG Example App'"
    )
    # Drop the default now the backfill is done: it exists to make the column
    # NOT NULL against existing rows, not to let a future caller omit the mode.
    # Leaving it would silently record 'plain' for a structured call, which is
    # exactly the ambiguity this column was added to remove.
    op.alter_column("language_generation_requests", "mode", server_default=None)


def downgrade() -> None:
    op.drop_column("language_generation_requests", "mode")
