-- Safety and compliance: which terms each user accepted (and when), and abuse reports with their
-- outcome (kept for the record; the reported files themselves are deleted when needed).

ALTER TABLE users ADD COLUMN terms_version TEXT;
ALTER TABLE users ADD COLUMN terms_accepted_at DOUBLE PRECISION;

CREATE TABLE reports (
    id TEXT PRIMARY KEY,
    client_id TEXT,                                    -- the workspace / client the content belongs to (if known)
    job_id TEXT,
    output_id TEXT,
    reason TEXT NOT NULL,                              -- copyright | illegal | harassment | privacy | spam | other
    details TEXT,
    reporter TEXT,                                     -- user:<id> | client:<id> | public
    reporter_email TEXT,
    ip TEXT,
    status TEXT NOT NULL,                              -- open | dismissed | removed | suspended
    resolution TEXT,
    resolved_by TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    resolved_at DOUBLE PRECISION
);
CREATE INDEX reports_status ON reports (status, created_at);

-- A result can be held (downloads refused) while a report about it is looked at.
ALTER TABLE outputs ADD COLUMN held_at DOUBLE PRECISION;
