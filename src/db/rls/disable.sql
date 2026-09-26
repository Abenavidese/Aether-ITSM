-- Rollback of enable.sql. Idempotent. Set DB_RLS_ENABLED=false BEFORE running
-- it, or tenant-scoped sessions will fail on SET ROLE of a missing role.

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['tickets', 'log_access_audit', 'platform_logs', 'knowledge_audit', 'agent_spans',
                             'companies', 'users', 'langchain_pg_embedding']
    LOOP
        IF to_regclass('public.' || t) IS NOT NULL THEN
            EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
            EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', t);
        END IF;
    END LOOP;
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aether_tenant') THEN
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM aether_tenant;
        REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM aether_tenant;
        REVOKE USAGE ON SCHEMA public FROM aether_tenant;
        EXECUTE format('REVOKE aether_tenant FROM %I', current_user);
        DROP ROLE aether_tenant;
    END IF;
END
$$;
