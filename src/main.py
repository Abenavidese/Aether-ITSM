from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from src.api.routes import router as webhook_router
from src.auth.router import router as auth_router
from src.db.database import engine
from src.db import models

# Create database tables
models.Base.metadata.create_all(bind=engine)

# Load environment variables (like NEBIUS_API_KEY)
load_dotenv()

app = FastAPI(
    title="ITSM Agent API",
    description="API for the AI-powered IT Support Agent using Nebius Token Factory",
    version="1.0.0"
)

# Configure CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router, prefix="/api")
app.include_router(auth_router, prefix="/api")

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "ITSM Agent API is running"}
