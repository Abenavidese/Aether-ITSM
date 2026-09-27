"""knowledge store: documents, chunks, query log, span attributes

Fase 14.1: the RAG moves off langchain-postgres' generic table (tenant in
JSON, untyped vector, no vector index, searched outside RLS) to tables of
its own. The legacy table is not touched here — it is library-managed; its
content is carried over by `python -m src.rag.admin migrate-legacy`.

Postgres-only parts (skipped on SQLite dev/tests): the pgvector extension
and the GIN full-text index. Per-model HNSW indexes are created at runtime
by the indexer, because they depend on the configured embedding model's
dimension (src/rag/store.py:ensure_vector_index).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from src.db.types import Embedding

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column("active_version", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("page_map", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column("chunker_version", sa.String(), nullable=True),
        sa.Column("warnings", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "filename", name="uq_knowledge_document_tenant_filename"),
    )
    op.create_index("ix_knowledge_documents_tenant_id", "knowledge_documents", ["tenant_id"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("document_id", sa.String(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("embedding", Embedding(), nullable=True),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("chunk_metadata", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_chunks_search", "knowledge_chunks", ["tenant_id", "is_active", "source_type"])
    op.create_index("ix_knowledge_chunks_document", "knowledge_chunks", ["document_id", "version"])
    if _is_postgres():
        op.execute("CREATE INDEX ix_knowledge_chunks_fts ON knowledge_chunks "
                   "USING gin (to_tsvector('simple', search_text))")

    op.create_table(
        "rag_queries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("rewritten", sa.Boolean(), nullable=False),
        sa.Column("passages", sa.Integer(), nullable=False),
        sa.Column("top_score", sa.Float(), nullable=True),
        sa.Column("document_ids", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rag_queries_tenant_id", "rag_queries", ["tenant_id"])
    op.create_index("ix_rag_queries_created_at", "rag_queries", ["created_at"])

    with op.batch_alter_table("agent_spans") as batch_op:
        batch_op.add_column(sa.Column("attributes", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_spans") as batch_op:
        batch_op.drop_column("attributes")
    op.drop_index("ix_rag_queries_created_at", table_name="rag_queries")
    op.drop_index("ix_rag_queries_tenant_id", table_name="rag_queries")
    op.drop_table("rag_queries")
    if _is_postgres():
        op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_fts")
    op.drop_index("ix_knowledge_chunks_document", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_search", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_documents_tenant_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
