from src.config import get_settings

def get_embeddings():
    """
    Returns the configured embeddings model. Model ids live in Settings
    (src/config.py) exclusively, so switching Ollama -> Nebius/OpenAI is a
    .env change, never a code change here.
    """
    settings = get_settings()

    if settings.use_ollama:
        from langchain_ollama import OllamaEmbeddings
        return OllamaEmbeddings(model=settings.ollama_embedding_model)

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

    return OpenAIEmbeddings(model=model, api_key=api_key, base_url=base_url)
