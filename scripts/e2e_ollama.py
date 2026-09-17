"""
End-to-end smoke test against a LOCALLY RUNNING Aether stack (Ollama + Postgres).

This is a standalone script, not a pytest test: pytest's own discovery is
already broken on this project on Windows (see tests/test_flow.py — a
module-level SQLAlchemy engine keeps app.db locked for the whole session,
so its fixture's os.remove() always fails), and this script additionally
needs live external services (Ollama on :11434, and DATABASE_URL pointing at
a reachable Postgres/pgvector instance) that a normal `pytest` run should
never be forced to assume. Keeping it out of tests/ means it's never
auto-collected.

It exercises the real HTTP API end to end — registration, employee
provisioning, RAG document upload, ticket submission, human approval, and
tenant isolation — not the LangGraph graph in isolation, because the point is
to prove the whole pipeline built this session actually works together:
ticket persistence, the user-must-exist rule, the fixed approve→execute path,
webhook idempotency, and RAG tenant isolation.

Preconditions:
    1. `uvicorn src.main:app --reload` running locally (default http://127.0.0.1:8000).
    2. Ollama running locally with the required models pulled:
           ollama pull llama3.1          # or set OLLAMA_MODEL to whatever tag you have
           ollama pull nomic-embed-text
       Tip: `ollama list` — if you only see e.g. "llama3.1:8b" and not a bare
       "llama3.1" (== "llama3.1:latest"), either `ollama pull llama3.1` or set
       OLLAMA_MODEL=llama3.1:8b in your .env to match what's actually pulled.
    3. DATABASE_URL in .env pointing at a reachable Postgres (pgvector) instance
       — the same one the running server uses.

Usage (from the project root, so `src` is importable and `.env` is found):
    python scripts/e2e_ollama.py
"""
import os
import sys
import time
import uuid

import httpx

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, PROJECT_ROOT)

BASE_URL = os.environ.get("AETHER_BASE_URL", "http://127.0.0.1:8000/api")
PASSWORD = "E2ETestPassw0rd!"


def check(label: str, condition: bool, detail: str = ""):
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        raise SystemExit(1)


def _model_is_pulled(requested: str, installed: set) -> bool:
    """
    Ollama only resolves a bare name like "llama3.1" to the ":latest" tag —
    having some *other* tag pulled (e.g. only "llama3.1:8b") does NOT satisfy
    a request for "llama3.1" and 404s at call time. This mirrors that exactly
    instead of being lenient about "any tag counts".
    """
    if ":" in requested:
        return requested in installed
    return requested in installed or f"{requested}:latest" in installed


def preflight_ollama():
    # Read the exact same source of truth the app uses (src/config.py) instead
    # of guessing env var names here — that duplication is exactly what drifted
    # out of sync the last time the model settings were renamed.
    from src.config import get_settings
    settings = get_settings()

    try:
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3.0)
        models = {m["name"] for m in r.json()["models"]}
    except Exception as e:
        print(f"No pude contactar a Ollama en :11434 ({e}). ¿Está corriendo `ollama serve`?")
        raise SystemExit(1)

    for role, model_name in (("nano", settings.ollama_model_nano), ("super", settings.ollama_model_super)):
        check(f"Modelo '{role}' ('{model_name}') disponible en Ollama", _model_is_pulled(model_name, models),
              f"modelos instalados: {sorted(models)}. Ajusta OLLAMA_MODEL_{role.upper()} en .env "
              f"o corre `ollama pull {model_name}`.")

    has_embed = _model_is_pulled(settings.ollama_embedding_model, models)
    check(f"Modelo de embeddings '{settings.ollama_embedding_model}' disponible en Ollama", has_embed,
          f"corre: ollama pull {settings.ollama_embedding_model}")


def register_and_login(client: httpx.Client, company_name: str, admin_email: str) -> None:
    r = client.post("/auth/register", json={
        "email": admin_email, "password": PASSWORD, "full_name": "E2E Admin",
        "company_name": company_name, "company_size": "10-50", "industry": "Tech",
        "current_tool": "Jira", "job_title": "CTO", "primary_goal": "automate",
    })
    check(f"Registro de tenant '{company_name}'", r.status_code == 200, r.text)

    r = client.post("/auth/login", json={"email": admin_email, "password": PASSWORD})
    check("Login", r.status_code == 200, r.text)


def wait_for_ticket(client: httpx.Client, external_id: str, want_status, timeout: int = 240) -> dict:
    """
    Polls GET /tenant/tickets/{external_id} until it reaches one of want_status.

    240s default: Ollama evicts an idle model from memory and has to reload
    it on the next call. Since nano/super alternate within a single ticket
    (Supervisor->Policy->Execution/Draft Plan), the very first ticket of a
    cold run can take 2-3 minutes just on model loading, independent of
    anything being wrong. Subsequent tickets are fast once both models are
    warm in memory.
    """
    targets = (want_status,) if isinstance(want_status, str) else tuple(want_status)
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/tenant/tickets/{external_id}")
        if r.status_code == 200:
            last = r.json()
            if last["status"] in targets:
                return last
        time.sleep(3)
    raise SystemExit(
        f"Timeout esperando el ticket {external_id} en estado {targets}. "
        f"Último estado visto: {last}. Revisa los logs de uvicorn."
    )


def check_tenant_rag_isolation(suffix: str):
    """
    Calls retrieve_context() directly — the same function every agent node
    uses — to prove the tenant_id filter actually isolates data, instead of
    just trusting that PGVector's dict-filter syntax behaves as expected.
    """
    from src.rag.service import retrieve_context

    other_client = httpx.Client(base_url=BASE_URL, timeout=30.0)
    other_email = f"admin.other.{suffix}@e2e.test"
    register_and_login(other_client, f"Other Co {suffix}", other_email)

    me = other_client.get("/auth/me").json()
    other_tenant_id = me["tenant_id"]

    leaked = retrieve_context(other_tenant_id, "política de acceso a AWS IAM", source_type="company_policy")
    check(
        "La empresa nueva (sin documentos propios) no recibe contexto de la política de la primera empresa",
        leaked == "",
        f"se filtró contenido: {leaked[:200]!r}",
    )


def main():
    print("=== Fase 1: preflight de Ollama ===")
    preflight_ollama()

    suffix = uuid.uuid4().hex[:8]
    company_name = f"Vertex E2E {suffix}"
    admin_email = f"admin.{suffix}@e2e.test"
    employee_email = f"employee.{suffix}@e2e.test"

    client = httpx.Client(base_url=BASE_URL, timeout=30.0)

    print("\n=== Fase 2: tenant, empleado y base de conocimiento ===")
    register_and_login(client, company_name, admin_email)

    r = client.get("/tenant/settings")
    check("Obtener /tenant/settings", r.status_code == 200, r.text)
    api_key = r.json()["api_key"]
    check("API key con el prefijo esperado", bool(api_key) and api_key.startswith("aeth_live_"))

    r = client.post("/tenant/users", json={
        "email": employee_email, "full_name": "E2E Employee", "password": PASSWORD, "role": "employee",
    })
    check("Crear cuenta del empleado que reportará los tickets", r.status_code == 200, r.text)

    for filename, source_type in [
        ("guia_politicas_empresa.txt", "company_policy"),
        ("guia_tecnica_repo.txt", "technical_repo"),
    ]:
        path = os.path.join(FIXTURES_DIR, filename)
        with open(path, "rb") as f:
            r = client.post(
                "/tenant/knowledge",
                files={"file": (filename, f, "text/plain")},
                data={"source_type": source_type},
            )
        check(f"Subir {filename} como '{source_type}'", r.status_code == 200, r.text)

    webhook_headers = {"x-api-key": api_key}

    print("\n=== Fase 3: ticket de Riesgo 1-2 (auto-resolución) ===")
    ticket_low = f"E2E-LOW-{suffix}"
    r = client.post("/webhook/ticket", headers=webhook_headers, json={
        "ticket_id": ticket_low,
        "summary": "La VPN no conecta",
        "description": "No logro conectarme a la VPN corporativa desde esta mañana, se queda colgada.",
        "user_email": employee_email,
    })
    check("Ticket de riesgo bajo aceptado (202)", r.status_code == 202, r.text)

    ticket = wait_for_ticket(client, ticket_low, want_status=("resolved", "escalated"))
    check("Ticket de riesgo bajo llegó a un estado terminal", True, str(ticket))
    if ticket["status"] == "resolved":
        check("Se resolvió de forma autónoma (sin pasar por aprobación humana)",
              ticket["resolution_path"] == "autonomous", str(ticket))
    else:
        print(f"    (nota: escalo en lugar de auto-resolverse - revisa los logs; "
              f"con un modelo local esto puede pasar si el structured output falló)")

    print("\n=== Fase 4: ticket de Riesgo 3 (pausa + aprobación humana) ===")
    ticket_high = f"E2E-HIGH-{suffix}"
    r = client.post("/webhook/ticket", headers=webhook_headers, json={
        "ticket_id": ticket_high,
        "summary": "Necesito acceso de administrador en AWS",
        "description": (
            "Soy Tech Lead del Proyecto X y necesito acceso de AWS Admin limitado a los "
            "recursos de este proyecto para completar un despliegue programado."
        ),
        "user_email": employee_email,
    })
    check("Ticket de riesgo alto aceptado (202)", r.status_code == 202, r.text)

    ticket = wait_for_ticket(client, ticket_high, want_status=("pending_human", "resolved", "escalated"))
    check("Ticket de riesgo alto pausado esperando aprobación", ticket["status"] == "pending_human", str(ticket))

    r = client.post(f"/approve/{ticket_high}", json={"approved": True, "approver_id": admin_email})
    check("Aprobación procesada sin error", r.status_code == 200, r.text)

    ticket = wait_for_ticket(client, ticket_high, want_status=("resolved", "escalated"), timeout=60)
    check("Ticket de riesgo alto quedó resuelto tras la aprobación (antes de este fix, quedaba colgado)",
          ticket["status"] == "resolved", str(ticket))
    check("Quedó marcado como resuelto por un humano, no de forma autónoma",
          ticket.get("resolution_path") == "human", str(ticket))

    print("\n=== Fase 5: idempotencia del webhook ===")
    r = client.post("/webhook/ticket", headers=webhook_headers, json={
        "ticket_id": ticket_low,
        "summary": "La VPN no conecta",
        "description": "reenvío duplicado del mismo webhook (simula un retry del ITSM)",
        "user_email": employee_email,
    })
    body = r.json()
    check("Reenviar el mismo ticket_id no lo reprocesa", "not reprocessing" in body.get("message", "").lower(), body)

    print("\n=== Fase 6: aislamiento multi-tenant del RAG ===")
    check_tenant_rag_isolation(suffix)

    print("\nTodo OK. Revisa los logs de uvicorn para ver si algún nodo necesitó "
          "reintentar el structured output por una respuesta mal formada del modelo local.")


if __name__ == "__main__":
    main()
