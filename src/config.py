"""
Centralized application configuration.
All secrets and settings are loaded from environment variables — no fallbacks for sensitive values.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from .env file and environment variables."""

    # ── Security (REQUIRED — app will crash if missing) ──
    jwt_secret_key: str = Field(..., description="Secret key for signing JWT tokens")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours
    superadmin_password: str = Field(..., description="Password for the initial superadmin account")
    encryption_key: str = Field(..., description="Secret key for encrypting integration tokens")
    cookie_secure: bool = Field(
        default=False,
        description="Send the auth cookie with the Secure flag (requires HTTPS). Set True in production.",
    )

    # ── Database ──
    database_url: str = Field(
        default="sqlite:///./app.db",
        description="SQLAlchemy connection string"
    )

    # ── LLM Provider ──
    # Every model name lives here and nowhere else. Swapping providers (local
    # Ollama -> Nebius in production) is a .env change — flip USE_OLLAMA and
    # set the nebius_* fields — never a code change in nodes.py/embeddings.py.
    #
    # "nano" = fast/cheap model for the Supervisor's lightweight risk
    # classification. "super" = stronger model for the reasoning-heavy nodes
    # (Policy, Execution, Draft Plan). Mirrors the Nemotron Nano/Super split
    # documented in docs/architecture.md.
    use_ollama: bool = Field(default=True, description="Use local Ollama models for $0 dev")

    ollama_model_nano: str = "llama3.2:1b"
    ollama_model_super: str = "llama3.1:8b"
    ollama_embedding_model: str = "nomic-embed-text"

    # Placeholder Nebius Token Factory model ids — adjust to the exact
    # catalog names when actually connecting (see docs/architecture.md,
    # base URL https://api.studio.nebius.ai/v1/).
    nebius_model_nano: str = "nvidia/nemotron-nano-9b-v2"
    nebius_model_super: str = "nvidia/llama-3.3-nemotron-super-49b-v1"
    nebius_embedding_model: str = "BAAI/bge-en-icl"

    openai_model_nano: str = "gpt-4o-mini"
    openai_model_super: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    # Vision model that turns an attached screenshot into text (visible
    # errors + a short description) for the text-only agents — see
    # src/agent/vision.py. Disabled -> the agents are told an image was
    # attached but couldn't be read, never that it said something.
    vision_enabled: bool = True
    ollama_model_vision: str = "qwen2.5vl:3b"
    nebius_model_vision: str = "Qwen/Qwen2.5-VL-72B-Instruct"
    openai_model_vision: str = "gpt-4o-mini"
    vision_max_chars: int = 2000

    # Limits applied to every LLM call (see get_llms): a structured reply is
    # a few hundred tokens, so 1024 leaves headroom while bounding a runaway
    # generation to seconds instead of forever.
    llm_max_output_tokens: int = 1024
    llm_timeout_seconds: float = 120.0
    ollama_num_ctx: int = 8192
    # Context window assumed for hosted (Nebius/OpenAI) models when budgeting
    # prompt history (src/agent/context_budget.py).
    hosted_context_window_tokens: int = 32768

    # ── LLM input limits (Fase 11.6) ──
    chat_message_max_chars: int = 4000
    chat_rate_limit: str = "20/minute"
    knowledge_upload_max_bytes: int = 10 * 1024 * 1024
    knowledge_upload_max_pdf_pages: int = 300
    knowledge_rate_limit: str = "10/minute"

    # ── Schema migrations (roadmap 1.4) ──
    # true: the API applies pending Alembic migrations at startup (dev/tests).
    # Keep false for any shared database: run `python -m src.db.migrate` as a
    # deliberate deploy step instead.
    db_auto_migrate: bool = False

    # ── Row-Level Security (roadmap 2.5) ──
    # Turn on only after src/db/rls/enable.sql was applied to the database
    # (scripts/apply_rls.py): tenant-scoped sessions then SET ROLE aether_tenant.
    db_rls_enabled: bool = False

    # ── Observability (roadmap 2.4) ──
    log_format: str = Field(default="text", description="text | json")
    # USD per 1M tokens, per model id: {"model": [input_price, output_price]}.
    # Local Ollama models cost nothing and are simply absent (cost 0). Fill in
    # the real Nebius/OpenAI prices of YOUR contract — they are not guessed here.
    llm_prices_json: str = "{}"

    # ── Background jobs (roadmap 2.2) ──
    # Embedded: the API process also drains the queue (dev default). Set
    # false and run `python -m src.jobs.worker` to scale/restart separately.
    jobs_embedded_worker: bool = True
    jobs_concurrency: int = 2
    jobs_poll_seconds: float = 1.0
    # A running job with no heartbeat for this long is presumed dead and requeued.
    jobs_visibility_timeout_seconds: float = 600.0

    # ── Outbound requests (Fase 11.4) ──
    # Healthchecks may only target publicly routable hosts. Set True only for
    # a self-hosted deployment that must monitor intranet services; cloud
    # metadata / link-local addresses stay blocked either way.
    allow_private_healthcheck_targets: bool = False

    # ── Platform logs (Fase 10) ──
    # Vercel drain lines are kept only this long (purged on each ingest).
    platform_log_retention_hours: int = 72
    # Upper bound for one drain delivery; larger bodies are rejected (413).
    platform_log_max_body_bytes: int = 5_000_000

    # ── RAG (Fase 14, src/rag/retrieval.py) ──
    # Every value here was chosen with the retrieval eval (evals/rag) — re-run
    # it before changing one, and after switching the embedding model.
    rag_top_k: int = 5                       # passages that reach the model
    rag_candidates: int = 20                 # per generator (dense/keyword/identifier) and reranked
    # Cosine-distance cutoff used when no reranker is active. Empty = the
    # calibrated default for the embedding model (retrieval.DEFAULT_MAX_DISTANCE).
    rag_max_distance: float | None = None
    # Reranker: "none", a local fastembed cross-encoder model id (ONNX, CPU,
    # downloaded on first use — recommended: jinaai/jina-reranker-v2-base-multilingual,
    # ~1.1 GB on disk and in RAM), or "api:<model>" for a hosted /rerank
    # endpoint (Cohere/Jina/Voyage request shape) at RAG_RERANKER_API_URL.
    rag_reranker: str = "none"
    rag_rerank_min_score: float | None = None   # empty = calibrated default for the reranker
    rag_reranker_budget_ms: int = 2500
    rag_reranker_cache_dir: str = ""
    rag_reranker_api_url: str = ""
    rag_reranker_api_key: str | None = None
    rag_rewrite_mode: str = "concat"         # off | concat | llm (follow-up questions)
    rag_context_chars: int = 6000            # budget for all passages in one prompt
    rag_query_log_retention_days: int = 30

    nebius_api_key: str | None = None
    openai_api_key: str | None = None

    # ── Infrastructure ──
    checkpoint_backend: str = Field(
        default="auto",
        description="auto|sqlite|postgres — auto uses Postgres when DATABASE_URL is Postgres (see src/agent/checkpointer.py)",
    )
    checkpoint_db_path: str = Field(default="checkpoints.db", description="Path to LangGraph sqlite memory (sqlite backend only)")
    checkpoint_pool_max_size: int = Field(
        default=5,
        description="Max Postgres connections for the checkpointer pool — keep low, Supabase's pooler caps total connections",
    )

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="Comma-separated list of allowed CORS origins"
    )

    # ── Business Logic Configuration ──
    mdm_software_whitelist: str = Field(
        default="pkg_docker,pkg_office365,pkg_vscode",
        description="Comma-separated list of allowed software for auto-provisioning"
    )

    @property
    def get_cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_context_window_tokens(self) -> int:
        return self.ollama_num_ctx if self.use_ollama else self.hosted_context_window_tokens

    @property
    def get_mdm_whitelist_list(self) -> list[str]:
        return [pkg.strip() for pkg in self.mdm_software_whitelist.split(",") if pkg.strip()]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor for application settings."""
    return Settings()


def get_llms():
    """
    Returns a tuple of (llm_nano, llm_super).
    Reads USE_OLLAMA to determine if it should use local free models or a
    hosted OpenAI-compatible provider (Nebius Token Factory, or plain OpenAI
    as a fallback). Which exact model id is used for each role is entirely
    controlled by the settings above — never hardcoded here.
    """
    settings = get_settings()

    if settings.use_ollama:
        from langchain_ollama import ChatOllama

        # Hard limits, found live: without num_predict Ollama's default is
        # "generate forever", and a model stuck in a repetition loop under
        # JSON-constrained decoding ran 27k+ tokens (context-shifting its own
        # window) and froze the chat with no error. num_ctx: Ollama's default
        # window silently truncates long prompts FROM THE START — i.e. it
        # drops the system prompt with all the instructions first.
        ollama_kwargs = dict(
            temperature=0.0,
            num_ctx=settings.ollama_num_ctx,
            num_predict=settings.llm_max_output_tokens,
            client_kwargs={"timeout": settings.llm_timeout_seconds},
        )
        llm_nano = ChatOllama(model=settings.ollama_model_nano, **ollama_kwargs)
        llm_super = ChatOllama(model=settings.ollama_model_super, **ollama_kwargs)
        return llm_nano, llm_super

    from langchain_openai import ChatOpenAI

    provider = _hosted_provider(settings)
    openai_kwargs = _hosted_kwargs(settings, provider)
    llm_nano = ChatOpenAI(model=provider["nano"], **openai_kwargs)
    llm_super = ChatOpenAI(model=provider["super"], **openai_kwargs)
    return llm_nano, llm_super


def active_models() -> dict:
    """The model id serving each role right now (shown read-only in Settings)."""
    settings = get_settings()
    if settings.use_ollama:
        provider = "ollama"
    elif settings.nebius_api_key:
        provider = "nebius"
    elif settings.openai_api_key:
        provider = "openai"
    else:
        return {"provider": "unconfigured", "nano": None, "super": None, "vision": None}
    return {
        "provider": provider,
        "nano": getattr(settings, f"{provider}_model_nano"),
        "super": getattr(settings, f"{provider}_model_super"),
        "vision": getattr(settings, f"{provider}_model_vision") if settings.vision_enabled else None,
    }


def get_vision_llm():
    """The image-reading model (see src/agent/vision.py), same provider switch as get_llms()."""
    settings = get_settings()
    if settings.use_ollama:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model_vision, temperature=0.0, num_ctx=settings.ollama_num_ctx,
            num_predict=settings.llm_max_output_tokens, client_kwargs={"timeout": settings.llm_timeout_seconds},
        )

    from langchain_openai import ChatOpenAI

    provider = _hosted_provider(settings)
    return ChatOpenAI(model=provider["vision"], **_hosted_kwargs(settings, provider))


def _hosted_provider(settings: Settings) -> dict:
    if settings.nebius_api_key:
        return {
            "api_key": settings.nebius_api_key, "base_url": "https://api.studio.nebius.ai/v1/",
            "nano": settings.nebius_model_nano, "super": settings.nebius_model_super,
            "vision": settings.nebius_model_vision,
        }
    if settings.openai_api_key:
        return {
            "api_key": settings.openai_api_key, "base_url": None,
            "nano": settings.openai_model_nano, "super": settings.openai_model_super,
            "vision": settings.openai_model_vision,
        }
    raise RuntimeError("NEBIUS_API_KEY or OPENAI_API_KEY is required when USE_OLLAMA=False")


def _hosted_kwargs(settings: Settings, provider: dict) -> dict:
    return dict(
        temperature=0.0, api_key=provider["api_key"], base_url=provider["base_url"],
        max_tokens=settings.llm_max_output_tokens, timeout=settings.llm_timeout_seconds,
    )
