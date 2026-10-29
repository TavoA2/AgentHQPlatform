"""chat with dixon

Revision ID: c4e7a1d9b2f0
Revises: 5e1098904d3a
Create Date: 2026-10-28 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e7a1d9b2f0"
down_revision: str | None = "5e1098904d3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_user_updated", "conversations", ["user_id", "updated_at"], unique=False
    )
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("proposals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("model_provider", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("tokens_in", sa.BigInteger(), nullable=False),
        sa.Column("tokens_out", sa.BigInteger(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="role"),
        sa.CheckConstraint("status IN ('pending', 'complete', 'failed')", name="status"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_messages_conversation",
        "conversation_messages",
        ["conversation_id", "id"],
        unique=False,
    )
    # Jobs can now answer a chat message instead of running a task.
    op.alter_column("jobs", "task_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("jobs", sa.Column("conversation_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "jobs_conversation_id_fkey",
        "jobs",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "one_target", "jobs", "(task_id IS NULL) <> (conversation_id IS NULL)"
    )
    op.drop_constraint("job_kind", "jobs", type_="check")
    op.create_check_constraint("job_kind", "jobs", "kind IN ('start', 'resume', 'chat')")


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE conversation_id IS NOT NULL")
    op.drop_constraint("job_kind", "jobs", type_="check")
    op.create_check_constraint("job_kind", "jobs", "kind IN ('start', 'resume')")
    op.drop_constraint("one_target", "jobs", type_="check")
    op.drop_constraint("jobs_conversation_id_fkey", "jobs", type_="foreignkey")
    op.drop_column("jobs", "conversation_id")
    op.alter_column("jobs", "task_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index("ix_conversation_messages_conversation", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_user_updated", table_name="conversations")
    op.drop_table("conversations")
