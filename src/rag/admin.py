"""
Knowledge-base maintenance commands (Fase 14.1).

    python -m src.rag.admin status
    python -m src.rag.admin migrate-legacy            # dry run: what would be carried over
    python -m src.rag.admin migrate-legacy --apply    # needs the embedding model reachable
    python -m src.rag.admin reindex [--force]         # queue re-index of stale documents, every tenant

migrate-legacy carries the pre-Fase-14 store (langchain-postgres'
langchain_pg_embedding, tenant in JSON) into knowledge_documents/chunks. The
original files were never kept, so each document is rebuilt from its stored
chunks: ordered by chunk_index, the "Documento:/Sección:" header removed, the
section turned back into a Markdown heading, overlapping text between
consecutive chunks dropped. Then it is indexed with the current pipeline.
Re-uploading the original file afterwards gives the best result (PDF tables
and headings are only recovered from the real file). The legacy table is
left untouched; drop it by hand once the new store is verified.
"""
import argparse
import json
import logging
import sys
from collections import defaultdict

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def _legacy_documents(engine) -> dict[tuple[str, str], dict]:
    if "langchain_pg_embedding" not in inspect(engine).get_table_names():
        return {}
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT document, cmetadata FROM langchain_pg_embedding")).fetchall()
    docs: dict[tuple[str, str], dict] = defaultdict(lambda: {"chunks": [], "source_type": None})
    for content, meta in rows:
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        tenant, filename = meta.get("tenant_id"), meta.get("filename")
        if not tenant or not filename:
            continue
        doc = docs[(tenant, filename)]
        doc["source_type"] = meta.get("source_type") or "company_policy"
        doc["chunks"].append((int(meta.get("chunk_index") or 0), meta.get("section") or "", content or ""))
    return docs


def rebuild_text(chunks: list[tuple[int, str, str]]) -> str:
    from .retrieval import _join_without_overlap

    parts: list[str] = []
    current_section: str | None = None
    body = ""
    for _, section, content in sorted(chunks):
        lines = content.split("\n")
        while lines and (lines[0].startswith("Documento:") or lines[0].startswith("Sección:") or not lines[0].strip()):
            lines.pop(0)
        chunk_body = "\n".join(lines).strip()
        if section != current_section:
            if body:
                parts.append(body)
            parts.append(f"## {section}" if section else "")
            current_section, body = section, chunk_body
        else:
            body = _join_without_overlap(body, chunk_body)
    if body:
        parts.append(body)
    return "\n\n".join(p for p in parts if p).strip()


def migrate_legacy(apply: bool) -> None:
    from src.db.database import SessionLocal, engine
    from src.db.models import Company, KnowledgeDocument

    from .documents import index_version, register_upload
    from .embeddings import embedding_model_id, get_embeddings
    from .parsing import ParsedDocument

    legacy = _legacy_documents(engine)
    if not legacy:
        print("No legacy knowledge store found — nothing to migrate.")
        return
    db = SessionLocal()
    try:
        tenants = {c.id for c in db.query(Company.id).all()}
        existing = {(d.tenant_id, d.filename) for d in db.query(KnowledgeDocument).all()}
    finally:
        db.close()

    embeddings, model_id = (get_embeddings(), embedding_model_id()) if apply else (None, None)
    migrated = skipped = 0
    for (tenant_id, filename), doc in sorted(legacy.items()):
        reason = ("company no longer exists" if tenant_id not in tenants else
                  "already in the new store" if (tenant_id, filename) in existing else None)
        if reason:
            print(f"skip  {tenant_id[:8]} {filename}: {reason}")
            skipped += 1
            continue
        content = rebuild_text(doc["chunks"])
        print(f"{'migrate' if apply else 'would migrate'} {tenant_id[:8]} {filename} "
              f"({len(doc['chunks'])} legacy chunks, {len(content)} chars, {doc['source_type']})")
        if apply:
            outcome = register_upload(tenant_id, None, filename, doc["source_type"], ParsedDocument(text=content))
            index_version(tenant_id, outcome.document_id, outcome.version, embeddings, model_id, engine)
            with engine.connect() as conn:  # indexed here, not by the queue
                conn.execute(text("DELETE FROM jobs WHERE dedupe_key = :k"),
                             {"k": f"rag-index:{outcome.document_id}:{outcome.version}"})
                conn.commit()
        migrated += 1
    print(f"\n{migrated} document(s) {'migrated' if apply else 'to migrate'}, {skipped} skipped.")
    if not apply:
        print("Dry run. Re-run with --apply (the embedding model must be reachable).")


def reindex_all(force: bool) -> None:
    from src.db.database import SessionLocal
    from src.db.models import Company

    from .documents import reindex_stale
    from .embeddings import embedding_model_id

    db = SessionLocal()
    try:
        tenants = [c.id for c in db.query(Company.id).all()]
    finally:
        db.close()
    total = sum(reindex_stale(t, embedding_model_id(), force=force) for t in tenants)
    print(f"Queued {total} document(s) for re-indexing (the job worker picks them up).")


def status() -> None:
    from src.db.database import engine

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT status, embedding_model, count(*) FROM knowledge_documents GROUP BY status, embedding_model"
        )).fetchall()
        chunks = conn.execute(text("SELECT count(*), count(*) FILTER (WHERE is_active) FROM knowledge_chunks")
                              ).one() if engine.dialect.name == "postgresql" else None
    for s, model, n in rows:
        print(f"{n:5d}  {s:15s} {model or '-'}")
    if chunks:
        print(f"chunks: {chunks[0]} total, {chunks[1]} active")
    print(f"legacy documents: {len(_legacy_documents(engine))}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    m = sub.add_parser("migrate-legacy")
    m.add_argument("--apply", action="store_true")
    r = sub.add_parser("reindex")
    r.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "status":
        status()
    elif args.command == "migrate-legacy":
        migrate_legacy(args.apply)
    else:
        reindex_all(args.force)


if __name__ == "__main__":
    main()
