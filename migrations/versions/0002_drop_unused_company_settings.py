"""drop unused company settings

llm_engine, webhook_url, mcp_server_url and mcp_auth_token were stored and
shown in Settings but no code ever read them (roadmap 1.2): models are
platform configuration (src/core/config.py), the MCP server is a local stdio
subprocess, and outbound ITSM notifications don't exist yet (roadmap 3.6
will add them with a signing secret, not a bare URL).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26 17:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ("llm_engine", "webhook_url", "mcp_server_url", "mcp_auth_token")


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        for column in _COLUMNS:
            batch_op.drop_column(column)


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        for column in _COLUMNS:
            batch_op.add_column(sa.Column(column, sa.String(), nullable=True))
