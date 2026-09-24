import os

# Must run before ANY test module imports src.* — src.config caches settings
# and src.db.database builds its engine at import time, so whichever test
# file pytest collects first would otherwise bind them to the real .env
# (Supabase) instead of the throwaway sqlite test DB.
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["DATABASE_URL"] = "sqlite:///./test_app.db"
os.environ["USE_OLLAMA"] = "True"
os.environ["OLLAMA_MODEL"] = "llama3.1"
os.environ["CHECKPOINT_DB_PATH"] = "test_checkpoints.db"
