-- Row-level security for abuse reports (see 0004_rls.postgres.sql). Reports are written and read by
-- the system (the public report form, the admin pages) under '*'; a tenant only ever sees its own.

ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON reports USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));
