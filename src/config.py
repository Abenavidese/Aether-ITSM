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

    # ── Database ──
    database_url: str = Field(
        default="sqlite:///./app.db",
        description="SQLAlchemy connection string"
    )

    # ── LLM Provider ──
    use_ollama: bool = Field(default=True, description="Use local Ollama models for $0 dev")
    ollama_model: str = "llama3.1"
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
    Reads USE_OLLAMA to determine if it should use local free models or Nebius Production models.
    """
    settings = get_settings()

    if settings.use_ollama:
        from langchain_ollama import ChatOllama

        llm_nano = ChatOllama(model=settings.ollama_model, temperature=0.0)
        llm_super = ChatOllama(model=settings.ollama_model, temperature=0.0)
    else:
        from langchain_openai import ChatOpenAI

        api_key = settings.nebius_api_key or settings.openai_api_key
        if not api_key:
            raise RuntimeError(
                "NEBIUS_API_KEY or OPENAI_API_KEY is required when USE_OLLAMA=False"
            )
        base_url = "https://api.studio.nebius.ai/v1/" if settings.nebius_api_key else None

        llm_nano = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, api_key=api_key, base_url=base_url)
        llm_super = ChatOpenAI(model="gpt-4o", temperature=0.0, api_key=api_key, base_url=base_url)

    return llm_nano, llm_super
