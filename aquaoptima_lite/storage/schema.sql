-- Optimizer Lite audit store schema.
--
-- One row per closed cycle: snapshot, quality decision, baseline
-- recommendation, authority gate decision, the runtime mode that was
-- in effect, the config hash, and the creation timestamp.
--
-- Every payload column is stored as JSON-encoded text so the store is
-- self-describing for forensic replay; index columns are surfaced for
-- common queries (latest-by-site, latest-by-mode).
CREATE TABLE IF NOT EXISTS audit_cycle (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    site_id         TEXT    NOT NULL,
    runtime_mode    TEXT    NOT NULL,
    config_hash     TEXT    NOT NULL,
    snapshot_json   TEXT    NOT NULL,
    quality_json    TEXT    NOT NULL,
    recommendation_json TEXT NOT NULL,
    authority_json  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_cycle_site_created
    ON audit_cycle(site_id, created_at);

CREATE INDEX IF NOT EXISTS idx_audit_cycle_mode_created
    ON audit_cycle(runtime_mode, created_at);
