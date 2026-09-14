from src.config import get_settings

def get_embeddings():
    """
    Returns the configured embeddings model.
    Currently uses Ollama for local open-source setup, but easily switchable to OpenAI/Nebius.
    """
    settings = get_settings()
    
    if settings.use_ollama:
        from langchain_ollama import OllamaEmbeddings
        # Defaulting to nomic-embed-text for local vectors
        return OllamaEmbeddings(model="nomic-embed-text")
    else:
        from langchain_openai import OpenAIEmbeddings
        api_key = settings.nebius_api_key or settings.openai_api_key
        base_url = "https://api.studio.nebius.ai/v1/" if settings.nebius_api_key else None
        
        return OpenAIEmbeddings(
            model="text-embedding-3-small", 
            api_key=api_key,
            base_url=base_url
        )
