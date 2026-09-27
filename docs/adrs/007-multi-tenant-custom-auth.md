# ADR-007: Multi-Tenant Architecture & Custom Authentication

## Status
Accepted. Reviewed against the code on 2026-09-26 (roadmap 1.3):
- **Implemented:** in-house JWT auth (bcrypt via passlib), token in an httpOnly cookie
  (`Secure` flag via `COOKIE_SECURE`, off by default for local http); tenant id and role in
  the claims; every tenant route resolves the user from the DB and scopes queries by
  `company_id`; ticket threads are namespaced by tenant.
- **Partial:** "any database query is strictly scoped" relies on application filters.
  Postgres Row-Level Security is written and tested (`src/db/rls/`, CI runs it) but only
  enforced once the owner applies it (`DB_RLS_ENABLED=true`).
- **Superseded:** SQLite-only identity DB — Postgres (Supabase) is supported and the schema
  is managed by Alembic migrations; checkpoints live in Postgres too when configured.

## Context
Aether ITSM is pivoting from a single-instance demo to a B2B SaaS platform. This requires the system to support multiple companies (Tenants), where each company has its own isolated data, users, and AI context. Furthermore, we must decide how to manage user identity and authentication.

## Decisions

### 1. Tenant Isolation via Context Injection
**Decision:** We will use a logical separation model (Tenant Isolation). The `tenant_id` (company ID) will be embedded into the user's secure token. When a request hits the backend, the middleware will extract the `tenant_id` and inject it into the LangGraph `AgentState`. 
*   **Why?** This guarantees that any database query or MCP tool executed by the LLM is strictly scoped to the correct company, preventing cross-tenant data leaks.

### 2. Custom JWT Authentication (In-House)
**Decision:** We will build our own authentication system using JSON Web Tokens (JWT), `passlib` for password hashing, and a relational database (SQLite via SQLAlchemy) rather than relying on a third-party Identity Provider (IdP) like Firebase, Supabase, or Auth0.
*   **Why?** Building custom auth demonstrates deep engineering mastery (a key goal for the portfolio). It avoids vendor lock-in, reduces external dependencies, and gives us 100% control over the scaling of the platform and the structure of the JWT claims (such as injecting our custom `tenant_id` and `role`).

### 3. Database Layer for Identity
**Decision:** We will introduce a relational database (`app.db`) managed by SQLAlchemy, entirely separate from LangGraph's internal state database (`checkpoints.db`).
*   **Why?** LangGraph's checkpointer is designed for graph state memory, not relational business logic. Separating the identity database ensures we can scale the SaaS application independently from the Agent's memory.
