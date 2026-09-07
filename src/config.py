import os
from dotenv import load_dotenv

load_dotenv()

def get_llms():
    """
    Returns a tuple of (llm_nano, llm_super).
    Reads USE_OLLAMA to determine if it should use local free models or Nebius Production models.
    """
    use_ollama = os.getenv("USE_OLLAMA", "True").lower() == "true"
    
    if use_ollama:
        print("[CONFIG] Using OLLAMA for local $0 cost testing.")
        from langchain_ollama import ChatOllama
        
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1")
        # For local dev, we might use the same model for both nano and super if resources are constrained
        llm_nano = ChatOllama(model=ollama_model, temperature=0.0)
        llm_super = ChatOllama(model=ollama_model, temperature=0.0)
        
    else:
        print("[CONFIG] Using NEBIUS API (Production).")
        from langchain_openai import ChatOpenAI
        
        api_key = os.getenv("NEBIUS_API_KEY", os.getenv("OPENAI_API_KEY", "dummy"))
        base_url = "https://api.studio.nebius.ai/v1/" if os.getenv("NEBIUS_API_KEY") else None
        
        llm_nano = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, api_key=api_key, base_url=base_url)
        llm_super = ChatOpenAI(model="gpt-4o", temperature=0.0, api_key=api_key, base_url=base_url)
        
    return llm_nano, llm_super
