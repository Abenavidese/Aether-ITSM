"""incidents, code-fix proposals and in-app notifications

Fase 16: a chat turn that diagnoses a failing service stores the incident
on its ticket (structured, written by code), the ticket can carry a draft
fix pull request, the tenant opts in to fix proposals, and the requester is
notified in the portal as the ticket moves.

Additive only: two nullable ticket columns, one company flag defaulting to
off, one new table. Row-Level Security for `notifications` is added by
src/db/rls/enable.sql (re-run scripts/apply_rls.py on Postgres).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch:
        batch.add_column(sa.Column("incident", sa.Text(), nullable=True))
        batch.add_column(sa.Column("fix_pr_url", sa.String(), nullable=True))
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("code_fix_prs_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.String(), sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_index("ix_notifications_tenant_id", table_name="notifications")
    op.drop_table("notifications")
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("code_fix_prs_enabled")
    with op.batch_alter_table("tickets") as batch:
        batch.drop_column("fix_pr_url")
        batch.drop_column("incident")
