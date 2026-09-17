import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.api.routes import router as webhook_router
from src.auth.router import router as auth_router
from src.tenant.router import router as tenant_router
from src.tenant.user_router import router as user_router
from src.rag.router import router as rag_router
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


def _ensure_schema_migrations():
    """
    Best-effort ALTER TABLE for columns added after create_all() already ran
    once on an existing dev DB. There's no Alembic in this project yet, so
    this keeps existing SQLite/Postgres databases working without a manual
    step. Safe to run on every startup: failures mean the column already
    exists.
    """
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE companies ADD COLUMN api_key_hash VARCHAR"))
            conn.commit()
        except Exception:
            conn.rollback()


_ensure_schema_migrations()

def seed_database():
    from src.db.database import SessionLocal
    from src.auth.service import get_password_hash
    db = SessionLocal()
    
    try:
        # Seed Plans
        plans = [
            models.SubscriptionPlan(id="plan_free", name="Free", price_usd=0.0, max_users=2, max_tickets_per_month=100, max_ai_resolutions_per_month=50),
            models.SubscriptionPlan(id="plan_pro", name="Pro", price_usd=49.0, max_users=10, max_tickets_per_month=500, max_ai_resolutions_per_month=250),
            models.SubscriptionPlan(id="plan_enterprise", name="Enterprise", price_usd=199.0, max_users=999, max_tickets_per_month=9999, max_ai_resolutions_per_month=9999)
        ]
        
        for p in plans:
            existing = db.query(models.SubscriptionPlan).filter(models.SubscriptionPlan.id == p.id).first()
            if not existing:
                db.add(p)
                
        # Seed Superadmin
        sa_email = "admin@aether.ai"
        sa = db.query(models.User).filter(models.User.email == sa_email).first()
        if not sa:
            logger.info("Seeding superadmin account...")
            sa_password = settings.superadmin_password
                
            company = models.Company(name="Aether Systems", industry="SaaS", onboarding_completed="true", plan_id="plan_enterprise")
            db.add(company)
            db.commit()
            db.refresh(company)
            
            user = models.User(
                email=sa_email,
                full_name="Platform Creator",
                password_hash=get_password_hash(sa_password),
                role="superadmin",
                company_id=company.id
            )
            db.add(user)
            
        db.commit()
    except Exception as e:
        logger.error(f"Error seeding database: {e}")
    finally:
        db.close()

seed_database()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI to handle global resources."""
    # Initialize the LangGraph checkpointer connection once for the whole app
    logger.info("Initializing AsyncSqliteSaver at %s", settings.checkpoint_db_path)
    async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db_path) as memory:
        app.state.checkpointer = memory
        yield
    logger.info("Shutting down AsyncSqliteSaver")

from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from src.security.limiter import limiter

app = FastAPI(
    title="ITSM Agent API",
    description="API for the AI-powered IT Support Agent using Nebius Token Factory",
    version="1.0.0",
    lifespan=lifespan
)

# Configure rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: Response(content="Rate limit exceeded", status_code=429))
app.add_middleware(SlowAPIMiddleware)

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
app.include_router(tenant_router, prefix="/api")
app.include_router(user_router, prefix="/api")
app.include_router(rag_router, prefix="/api")

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "ITSM Agent API is running"}
