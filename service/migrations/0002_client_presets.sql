-- Each client's own presets (plain preset JSON, checked against autoedit/presets/preset.schema.json).
CREATE TABLE client_presets (
    client_id TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (client_id, id)
);
