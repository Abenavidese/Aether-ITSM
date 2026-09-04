from fastapi import FastAPI
from dotenv import load_dotenv
from src.api.routes import router as api_router

# Load environment variables (like NEBIUS_API_KEY)
load_dotenv()

app = FastAPI(
    title="ITSM Agent API",
    description="API for the AI-powered IT Support Agent using Nebius Token Factory",
    version="1.0.0"
)

app.include_router(api_router, prefix="/api")

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "ITSM Agent API is running"}
