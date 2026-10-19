-- Row-level security (Postgres only): a second wall between tenants, under the `client_id = ?`
-- filters of every query. Each transaction sets app.tenant (service/db.py): a client's id while
-- serving that client, '*' for the system (workers, admin, janitor). Unset (e.g. a stray
-- connection) sees nothing. FORCE makes the policies apply to the tables' owner too; they do not
-- apply to a superuser or a BYPASSRLS user, so the service must connect as an ordinary user
-- (deploy/postgres-init.sql; /readyz reports "rls": "enforced"). On SQLite this file is skipped.

ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE clients FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON clients USING (current_setting('app.tenant', true) = '*' OR id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR id = current_setting('app.tenant', true));

ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON api_keys USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE uploads FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON uploads USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON jobs USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE outputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE outputs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON outputs USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE webhooks ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhooks FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON webhooks USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_deliveries FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON webhook_deliveries USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON usage USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE client_presets ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_presets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON client_presets USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON memberships USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE org_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_invites FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON org_invites USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON projects USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE job_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON job_events USING (current_setting('app.tenant', true) = '*' OR EXISTS (SELECT 1 FROM jobs j WHERE j.id = job_id)) WITH CHECK (current_setting('app.tenant', true) = '*' OR EXISTS (SELECT 1 FROM jobs j WHERE j.id = job_id));
