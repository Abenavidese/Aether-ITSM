-- Row-Level Security for Aether (roadmap 2.5). Idempotent: safe to re-run.
-- Applied by scripts/apply_rls.py; rollback: disable.sql.
--
-- The app's own connection role keeps its privileges (login, API-key lookup
-- and the job queue are cross-tenant by design). Tenant-scoped sessions
-- switch to aether_tenant for the transaction (src/db/tenant_scope.py), and
-- that role only ever sees rows whose tenant matches app.tenant_id.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aether_tenant') THEN
        CREATE ROLE aether_tenant NOLOGIN NOBYPASSRLS;
    END IF;
END
$$;

-- The connecting role must be a member to SET ROLE into it.
DO $$
BEGIN
    EXECUTE format('GRANT aether_tenant TO %I', current_user);
END
$$;

GRANT USAGE ON SCHEMA public TO aether_tenant;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aether_tenant;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aether_tenant;

-- Tables owned by a tenant through a `tenant_id` column.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['tickets', 'log_access_audit', 'platform_logs', 'knowledge_audit', 'agent_spans']
    LOOP
        IF to_regclass('public.' || t) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
            EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I TO aether_tenant '
                'USING (tenant_id = current_setting(''app.tenant_id'', true)) '
                'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', t);
        END IF;
    END LOOP;
END
$$;

-- A tenant sees only its own company row and its own users.
ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON companies;
CREATE POLICY tenant_isolation ON companies TO aether_tenant
    USING (id = current_setting('app.tenant_id', true))
    WITH CHECK (id = current_setting('app.tenant_id', true));

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON users;
CREATE POLICY tenant_isolation ON users TO aether_tenant
    USING (company_id = current_setting('app.tenant_id', true))
    WITH CHECK (company_id = current_setting('app.tenant_id', true));

-- RAG chunks (langchain-postgres) carry the tenant in their JSON metadata.
DO $$
BEGIN
    IF to_regclass('public.langchain_pg_embedding') IS NOT NULL THEN
        ALTER TABLE langchain_pg_embedding ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON langchain_pg_embedding;
        CREATE POLICY tenant_isolation ON langchain_pg_embedding TO aether_tenant
            USING (cmetadata->>'tenant_id' = current_setting('app.tenant_id', true))
            WITH CHECK (cmetadata->>'tenant_id' = current_setting('app.tenant_id', true));
    END IF;
END
$$;
