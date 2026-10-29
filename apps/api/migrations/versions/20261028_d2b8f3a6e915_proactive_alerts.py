"""proactive alerts

Revision ID: d2b8f3a6e915
Revises: c4e7a1d9b2f0
Create Date: 2026-10-28 23:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2b8f3a6e915"
down_revision: str | None = "c4e7a1d9b2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="chat"),
    )
    op.alter_column("conversations", "kind", server_default=None)
    op.add_column(
        "conversations", sa.Column("last_read_message_id", sa.BigInteger(), nullable=True)
    )
    op.create_check_constraint("kind", "conversations", "kind IN ('chat', 'alerts')")
    op.create_index(
        "uq_conversations_user_alerts",
        "conversations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'alerts'"),
    )
    op.add_column(
        "conversation_messages", sa.Column("alert_kind", sa.String(length=48), nullable=True)
    )
    # New jobs take run_after from the database clock (claims compare it with now()).
    op.alter_column("jobs", "run_after", server_default=sa.text("now()"))


def downgrade() -> None:
    op.alter_column("jobs", "run_after", server_default=None)
    op.drop_column("conversation_messages", "alert_kind")
    op.drop_index("uq_conversations_user_alerts", table_name="conversations")
    op.drop_constraint("kind", "conversations", type_="check")
    op.drop_column("conversations", "last_read_message_id")
    op.drop_column("conversations", "kind")
