import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.api.routes import router as webhook_router
from src.auth.router import router as auth_router
from src.db.database import engine
from src.db import models
from src.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Create database tables
models.Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI to handle global resources."""
    # Initialize the LangGraph checkpointer connection once for the whole app
    logger.info("Initializing AsyncSqliteSaver at %s", settings.checkpoint_db_path)
    async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db_path) as memory:
        app.state.checkpointer = memory
        yield
    logger.info("Shutting down AsyncSqliteSaver")

app = FastAPI(
    title="ITSM Agent API",
    description="API for the AI-powered IT Support Agent using Nebius Token Factory",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router, prefix="/api")
app.include_router(auth_router, prefix="/api")

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "ITSM Agent API is running"}
