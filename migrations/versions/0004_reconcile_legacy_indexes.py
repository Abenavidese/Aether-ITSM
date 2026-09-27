"""reconcile indexes missing from pre-Alembic databases

Found while rehearsing the production migration on a restored copy of the
Supabase database (2026-09-27): the pre-Alembic app never created three
objects the models declare, and adoption (src/db/migrate.py) stamps such a
database as the 0001 baseline, so nothing ever added them:

- ix_companies_api_key_hash (unique): every webhook call looks its tenant up
  by this hash — without it, a sequential scan, and no guarantee two
  companies can't share a key hash;
- ix_tickets_external_id;
- uq_ticket_tenant_external: the database half of webhook idempotency — two
  concurrent deliveries of the same ticket could both insert it.

Idempotent: creates only what is missing (a database built from 0001 already
has all three). Fails loudly if existing rows violate a unique rule, rather
than silently skipping it — deduplicate first in that case.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27 01:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _names(items) -> set[str]:
    return {i["name"] for i in items if i.get("name")}


def _has_unique(inspector, table: str, name: str, columns: list[str]) -> bool:
    uniques = inspector.get_unique_constraints(table) + [i for i in inspector.get_indexes(table) if i.get("unique")]
    return any(u.get("name") == name or u.get("column_names") == columns for u in uniques)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ix_companies_api_key_hash" not in _names(inspector.get_indexes("companies")):
        op.create_index("ix_companies_api_key_hash", "companies", ["api_key_hash"], unique=True)
    if "ix_tickets_external_id" not in _names(inspector.get_indexes("tickets")):
        op.create_index("ix_tickets_external_id", "tickets", ["external_id"])
    if not _has_unique(inspector, "tickets", "uq_ticket_tenant_external", ["tenant_id", "external_id"]):
        with op.batch_alter_table("tickets") as batch_op:
            batch_op.create_unique_constraint("uq_ticket_tenant_external", ["tenant_id", "external_id"])


def downgrade() -> None:
    # These objects belong to the baseline schema; on most databases this
    # migration didn't create them, so dropping them here would be wrong.
    pass
