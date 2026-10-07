"""Queue handlers for the knowledge base (Fase 14.6): indexing runs in the worker, not in the upload request."""
import asyncio
import logging

from src.jobs.worker import WorkerDeps
from src.rag import documents

logger = logging.getLogger(__name__)


async def index_document(payload: dict, deps: WorkerDeps) -> None:
    from src.db.database import engine
    from src.rag.embeddings import embedding_model_id, get_embeddings

    outcome = await asyncio.to_thread(
        documents.index_version, payload["tenant_id"], payload["document_id"], payload["version"],
        get_embeddings(), embedding_model_id(), engine,
    )
    logger.info("Indexed document %s v%s: %s", payload["document_id"], payload["version"], outcome)
    try:
        from src.rag.service import purge_query_log
        await asyncio.to_thread(purge_query_log)
    except Exception:
        logger.warning("Could not purge the RAG query log", exc_info=True)


async def index_document_dead(payload: dict, deps: WorkerDeps, error: str) -> None:
    await asyncio.to_thread(documents.mark_failed, payload["tenant_id"], payload["document_id"],
                            payload["version"], error)


HANDLERS = {"index_document": index_document}
DEAD_HANDLERS = {"index_document": index_document_dead}
