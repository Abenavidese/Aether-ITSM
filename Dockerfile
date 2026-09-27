# Aether API (FastAPI + LangGraph agents + queue worker + MCP tool server).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations/ migrations/
COPY src/ src/

RUN useradd --create-home --uid 10001 aether && mkdir -p temp_uploads && chown aether temp_uploads
USER aether

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# Migrations are an explicit step before serving (never implicit on a shared DB).
CMD ["sh", "-c", "python -m src.db.migrate && uvicorn src.main:app --host 0.0.0.0 --port 8000"]
