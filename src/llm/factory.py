"""
LLM factory: which model serves each role (nano / super / vision), from
settings. Ollama locally, a hosted OpenAI-compatible provider (Nebius Token
Factory, or OpenAI as a fallback) otherwise — switching is a .env change.
"""
from typing import Any

from langchain_core.language_models import BaseChatModel

from src.core.config import Settings, get_settings


def get_llms() -> tuple[BaseChatModel, BaseChatModel]:
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
        ollama_kwargs: dict[str, Any] = dict(
            temperature=0.0,
            num_ctx=settings.ollama_num_ctx,
            num_predict=settings.llm_max_output_tokens,
            client_kwargs={"timeout": settings.llm_timeout_seconds},
        )
        return (ChatOllama(model=settings.ollama_model_nano, **ollama_kwargs),
                ChatOllama(model=settings.ollama_model_super, **ollama_kwargs))

    from langchain_openai import ChatOpenAI

    provider = _hosted_provider(settings)
    openai_kwargs = _hosted_kwargs(settings, provider)
    return ChatOpenAI(model=provider["nano"], **openai_kwargs), ChatOpenAI(model=provider["super"], **openai_kwargs)


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


def get_vision_llm() -> BaseChatModel:
    """The image-reading model (see src/agents/runtime/vision.py), same provider switch as get_llms()."""
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


def _hosted_kwargs(settings: Settings, provider: dict) -> dict[str, Any]:
    return dict(
        temperature=0.0, api_key=provider["api_key"], base_url=provider["base_url"],
        max_tokens=settings.llm_max_output_tokens, timeout=settings.llm_timeout_seconds,
    )
