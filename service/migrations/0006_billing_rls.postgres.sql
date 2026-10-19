-- Row-level security for the billing tables (see 0004_rls.postgres.sql). Plans and trial claims
-- have no tenant; billing events are written by the system only.

ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON subscriptions USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON payments USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));

ALTER TABLE billing_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON billing_events USING (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true)) WITH CHECK (current_setting('app.tenant', true) = '*' OR client_id = current_setting('app.tenant', true));
