"""
Re-embeds knowledge-base chunks produced by an older chunking strategy.

Needed once after the contextual-chunking change (src/rag/chunking.py +
task-prefixed embeddings): old vectors were computed WITHOUT nomic's
"search_document: " prefix, so they aren't comparable with the new
"search_query: " vectors and silently rank worse — mixing both in one
collection is the worst of both worlds.

The original uploaded files are not kept (src/rag/router.py deletes them
after ingestion), so the source here is the stored chunk text itself. Each
legacy chunk is re-chunked on its own: it gets the "Documento" header and a
"Sección" wherever a heading appears inside it, but a section that started
in a previous chunk can't be recovered. For full section headers
everywhere, re-upload the original file from the dashboard (uploads now
replace a file's chunks instead of duplicating them).

Usage (from the project root, Ollama running for the embeddings):
    python scripts/reindex_rag.py            # dry run: shows what would change
    python scripts/reindex_rag.py --apply
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from src.db.database import engine  # noqa: E402
from src.rag.chunking import CHUNKER_VERSION, chunk_document  # noqa: E402
from src.rag.service import replace_chunks  # noqa: E402


def main(apply: bool) -> None:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT document, cmetadata FROM langchain_pg_embedding
            WHERE coalesce(cmetadata->>'chunker', '') <> :version
        """), {"version": CHUNKER_VERSION}).fetchall()

    files: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for document, metadata in rows:
        key = (metadata.get("tenant_id"), metadata.get("filename"), metadata.get("source_type"))
        if not all(key):
            print(f"  skip chunk with incomplete metadata: {metadata}")
            continue
        files[key].append(document)

    print(f"{len(rows)} legacy chunks in {len(files)} files (target chunker: {CHUNKER_VERSION})")
    for (tenant_id, filename, source_type), documents in sorted(files.items()):
        chunks = []
        for document in documents:
            chunks.extend(chunk_document(
                document, filename, base_metadata={"tenant_id": tenant_id, "source_type": source_type},
            ))
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = i
        print(f"  {tenant_id} {filename} [{source_type}]: {len(documents)} -> {len(chunks)} chunks")
        if apply:
            replace_chunks(tenant_id, filename, chunks)

    print("Done." if apply else "Dry run — nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
