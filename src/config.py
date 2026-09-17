"""
Centralized application configuration.
All secrets and settings are loaded from environment variables — no fallbacks for sensitive values.
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


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

    nebius_api_key: str | None = None
    openai_api_key: str | None = None

    # ── Infrastructure ──
    checkpoint_db_path: str = Field(default="checkpoints.db", description="Path to LangGraph sqlite memory")
    
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

        llm_nano = ChatOllama(model=settings.ollama_model_nano, temperature=0.0)
        llm_super = ChatOllama(model=settings.ollama_model_super, temperature=0.0)
        return llm_nano, llm_super

    from langchain_openai import ChatOpenAI

    if settings.nebius_api_key:
        api_key = settings.nebius_api_key
        base_url = "https://api.studio.nebius.ai/v1/"
        nano_model, super_model = settings.nebius_model_nano, settings.nebius_model_super
    elif settings.openai_api_key:
        api_key = settings.openai_api_key
        base_url = None
        nano_model, super_model = settings.openai_model_nano, settings.openai_model_super
    else:
        raise RuntimeError(
            "NEBIUS_API_KEY or OPENAI_API_KEY is required when USE_OLLAMA=False"
        )

    llm_nano = ChatOpenAI(model=nano_model, temperature=0.0, api_key=api_key, base_url=base_url)
    llm_super = ChatOpenAI(model=super_model, temperature=0.0, api_key=api_key, base_url=base_url)
    return llm_nano, llm_super
