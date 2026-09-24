from langchain_core.embeddings import Embeddings

from src.config import get_settings

# Some embedding models are trained with task prefixes and lose retrieval
# quality without them — nomic-embed-text expects "search_document: " on
# indexed text and "search_query: " on queries (see its model card). Keyed by
# model-name prefix so tags like "nomic-embed-text:latest" match too.
_TASK_PREFIXES: dict[str, tuple[str, str]] = {
    "nomic-embed-text": ("search_document: ", "search_query: "),
}


class TaskPrefixedEmbeddings(Embeddings):
    """
    Decorator over any Embeddings that prepends the model's document/query
    task prefixes. Only the vectors see the prefix — PGVector still stores
    and returns the original, unprefixed text.
    """

    def __init__(self, inner: Embeddings, document_prefix: str, query_prefix: str):
        self.inner = inner
        self.document_prefix = document_prefix
        self.query_prefix = query_prefix

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents([self.document_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(self.query_prefix + text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self.inner.aembed_documents([self.document_prefix + t for t in texts])

    async def aembed_query(self, text: str) -> list[float]:
        return await self.inner.aembed_query(self.query_prefix + text)


def _with_task_prefixes(embeddings: Embeddings, model: str) -> Embeddings:
    for model_prefix, (doc_prefix, query_prefix) in _TASK_PREFIXES.items():
        if model.startswith(model_prefix):
            return TaskPrefixedEmbeddings(embeddings, doc_prefix, query_prefix)
    return embeddings


def get_embeddings() -> Embeddings:
    """
    Returns the configured embeddings model. Model ids live in Settings
    (src/config.py) exclusively, so switching Ollama -> Nebius/OpenAI is a
    .env change, never a code change here.
    """
    settings = get_settings()

    if settings.use_ollama:
        from langchain_ollama import OllamaEmbeddings
        model = settings.ollama_embedding_model
        return _with_task_prefixes(OllamaEmbeddings(model=model), model)

    from langchain_openai import OpenAIEmbeddings

    if settings.nebius_api_key:
        api_key = settings.nebius_api_key
        base_url = "https://api.studio.nebius.ai/v1/"
        model = settings.nebius_embedding_model
    elif settings.openai_api_key:
        api_key = settings.openai_api_key
        base_url = None
        model = settings.openai_embedding_model
    else:
        raise RuntimeError(
            "NEBIUS_API_KEY or OPENAI_API_KEY is required when USE_OLLAMA=False"
        )

    return _with_task_prefixes(OpenAIEmbeddings(model=model, api_key=api_key, base_url=base_url), model)
