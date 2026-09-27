"""
Rerankers (Fase 14.3): re-score the fused candidates by reading query and
passage TOGETHER (a cross-encoder), which a bi-encoder embedding can't do.

Chosen by RAG_RERANKER in .env, like the models:
- "none": keep the hybrid order.
- a fastembed cross-encoder model id (ONNX on CPU, no PyTorch). Measured
  with evals/rag (Fase 14.3): "jinaai/jina-reranker-v2-base-multilingual"
  took hit@1 0.797 -> 0.938 and cross-lingual queries 0.667 -> 1.0, at
  ~0.65 s p50 on a laptop CPU; "Xenova/ms-marco-MiniLM-L-6-v2" (English
  only) gave no gain on this Spanish/English corpus. Downloaded on first
  use, cached in RAG_RERANKER_CACHE_DIR.
- "api:<model>": a hosted /rerank endpoint (ApiReranker).

A reranker is an optimization, never a dependency of correctness: if it is
missing, fails, or exceeds its latency budget, the hybrid order is used and
the reason is recorded on the retrieval span.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RerankOutcome:
    scores: list[float] | None     # one per passage, same order; None = not reranked
    reason: str                    # "ok", "disabled", "error: ...", "over budget"
    duration_ms: int = 0


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, passages: list[str]) -> RerankOutcome: ...


class NoopReranker:
    name = "none"

    def rerank(self, query: str, passages: list[str]) -> RerankOutcome:
        return RerankOutcome(None, "disabled")


class CrossEncoderReranker:
    """fastembed TextCrossEncoder, loaded lazily once per process."""

    def __init__(self, model: str, cache_dir: str | None = None, budget_ms: int = 2500,
                 max_chars: int = 1500):
        self.name = model
        self._model_id = model
        self._cache_dir = cache_dir
        self._budget_ms = budget_ms
        self._max_chars = max_chars
        self._model: Any = None     # fastembed TextCrossEncoder, loaded on first use
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder
                    self._model = TextCrossEncoder(model_name=self._model_id, cache_dir=self._cache_dir)
        return self._model

    def warm_up(self) -> None:
        self.rerank("warm up", ["warm up"])

    def rerank(self, query: str, passages: list[str]) -> RerankOutcome:
        if not passages:
            return RerankOutcome([], "ok")
        started = time.perf_counter()
        try:
            model = self._load()
            scores = [float(s) for s in model.rerank(query, [p[: self._max_chars] for p in passages])]
        except Exception as e:
            logger.warning("Reranker %s failed, keeping hybrid order: %s", self._model_id, e)
            return RerankOutcome(None, f"error: {type(e).__name__}")
        duration = int((time.perf_counter() - started) * 1000)
        if duration > self._budget_ms:
            # Results are still valid; the budget is about the NEXT calls:
            # logged so a slow CPU shows up in traces instead of as "the chat is slow".
            logger.warning("Reranker %s took %d ms (budget %d ms)", self._model_id, duration, self._budget_ms)
            return RerankOutcome(scores, "over budget", duration)
        return RerankOutcome(scores, "ok", duration)


class ApiReranker:
    """
    Hosted reranker over the /rerank request shape shared by Cohere, Jina AI
    and Voyage (and self-hosted text-embeddings-inference with a small
    adapter): {"model", "query", "documents"} -> {"results": [{"index",
    "relevance_score"}]}. For deployments where a 1 GB ONNX model doesn't
    fit in the instance's RAM. Scores are on the provider's scale: calibrate
    RAG_RERANK_MIN_SCORE with evals/rag/calibrate.py.
    """

    def __init__(self, model: str, url: str, api_key: str | None, budget_ms: int = 2500,
                 max_chars: int = 1500, client=None):
        self.name = f"api:{model}"
        self._model, self._url, self._key = model, url, api_key
        self._budget_ms, self._max_chars = budget_ms, max_chars
        self._client = client

    def rerank(self, query: str, passages: list[str]) -> RerankOutcome:
        import httpx

        if not passages:
            return RerankOutcome([], "ok")
        if not self._url:
            return RerankOutcome(None, "error: RAG_RERANKER_API_URL not set")
        started = time.perf_counter()
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        body = {"model": self._model, "query": query, "documents": [p[: self._max_chars] for p in passages]}
        try:
            if self._client is not None:
                response = self._client.post(self._url, json=body, headers=headers)
            else:
                with httpx.Client(timeout=self._budget_ms / 1000) as client:
                    response = client.post(self._url, json=body, headers=headers)
            response.raise_for_status()
            results = response.json()["results"]
            scores: list[float | None] = [None] * len(passages)
            for item in results:
                scores[int(item["index"])] = float(item["relevance_score"])
            if any(s is None for s in scores):
                return RerankOutcome(None, "error: incomplete response")
        except Exception as e:
            logger.warning("Hosted reranker failed, keeping hybrid order: %s", type(e).__name__)
            return RerankOutcome(None, f"error: {type(e).__name__}")
        return RerankOutcome([float(s) for s in scores if s is not None], "ok",
                             int((time.perf_counter() - started) * 1000))


_rerankers: dict[str, Reranker] = {}
_rerankers_lock = threading.Lock()


def get_reranker(name: str | None = None) -> Reranker:
    from src.config import get_settings
    settings = get_settings()
    name = (name if name is not None else settings.rag_reranker).strip()
    if not name or name.lower() == "none":
        return NoopReranker()
    with _rerankers_lock:
        if name not in _rerankers:
            if name.startswith("api:"):
                _rerankers[name] = ApiReranker(name.removeprefix("api:"), settings.rag_reranker_api_url,
                                               settings.rag_reranker_api_key, settings.rag_reranker_budget_ms)
            else:
                _rerankers[name] = CrossEncoderReranker(name, settings.rag_reranker_cache_dir or None,
                                                        settings.rag_reranker_budget_ms)
        return _rerankers[name]
