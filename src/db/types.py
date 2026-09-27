"""Column types that differ per database dialect."""
import json

from sqlalchemy.types import Text, TypeDecorator


class Embedding(TypeDecorator):
    """
    A float vector: pgvector's `vector` (no fixed dimension — see
    KnowledgeChunk) on Postgres, JSON text elsewhere (SQLite dev/tests, where
    search falls back to scoring in Python — src/rag/store.py).
    """
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector
            return dialect.type_descriptor(Vector())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None or dialect.name == "postgresql":
            return value
        return json.dumps([float(x) for x in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return [float(x) for x in value]
        return json.loads(value)
