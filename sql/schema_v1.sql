-- Local development schema, version 1 (Sprint 1).
--
-- LOCAL DEVELOPMENT ONLY. This does not finalize the shared database choice
-- (docs/data_contract.md, D3, pending Section A). It covers postings only; taxonomy tables
-- (statements, topics, ...) are intentionally not defined yet.
--
-- Rules:
--   * A stored posting is identified by (snapshot_id, posting_id), so a later snapshot can
--     never overwrite historical posting text.
--   * Rows are only ever inserted by src/load_postings.py; it never UPDATEs or DELETEs.
--   * Requires SQLite >= 3.37 (STRICT tables) with the JSON functions.
--   * Run with PRAGMA foreign_keys = ON (the loader enables and verifies it).

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', '1');

-- One row per raw snapshot that has been loaded.
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id     TEXT PRIMARY KEY CHECK (snapshot_id GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z'),
    source          TEXT NOT NULL,
    first_loaded_at TEXT NOT NULL
) STRICT;

-- One row per distinct processed input loaded (same file content is recorded once).
CREATE TABLE IF NOT EXISTS loads (
    load_id          INTEGER PRIMARY KEY,
    snapshot_id      TEXT NOT NULL REFERENCES snapshots (snapshot_id),
    cleaning_version TEXT NOT NULL,
    input_path       TEXT NOT NULL,
    input_sha256     TEXT NOT NULL,
    row_count        INTEGER NOT NULL CHECK (row_count >= 0),
    inserted_rows    INTEGER NOT NULL CHECK (inserted_rows >= 0),
    loader_version   TEXT NOT NULL,
    loaded_at        TEXT NOT NULL,
    UNIQUE (snapshot_id, cleaning_version, input_sha256)
) STRICT;

-- Every field produced by src/prepare_postings.py (data contract §2), plus load_id.
CREATE TABLE IF NOT EXISTS postings (
    snapshot_id       TEXT NOT NULL REFERENCES snapshots (snapshot_id),
    posting_id        TEXT NOT NULL,
    source            TEXT NOT NULL,
    source_job_id     TEXT NOT NULL,
    internal_job_id   TEXT,
    board_token       TEXT NOT NULL,
    company_name      TEXT NOT NULL,
    source_company_name TEXT,
    title             TEXT,
    location          TEXT,
    departments       TEXT NOT NULL CHECK (json_valid(departments) AND json_type(departments) = 'array'),
    offices           TEXT NOT NULL CHECK (json_valid(offices) AND json_type(offices) = 'array'),
    raw_text          TEXT,
    clean_text        TEXT NOT NULL,
    absolute_url      TEXT,
    source_updated_at TEXT,
    fetched_at        TEXT NOT NULL,
    industry          TEXT,
    industry_source   TEXT,
    source_language   TEXT,
    text_hash         TEXT,
    word_count        INTEGER NOT NULL CHECK (word_count >= 0),
    is_placeholder    INTEGER NOT NULL CHECK (is_placeholder IN (0, 1)),
    exclusion_reason  TEXT NOT NULL,
    is_duplicate_of   TEXT,
    cleaning_version  TEXT NOT NULL,
    load_id           INTEGER NOT NULL REFERENCES loads (load_id),
    PRIMARY KEY (snapshot_id, posting_id),
    CHECK (posting_id = source || ':' || board_token || ':' || source_job_id),
    CHECK (is_duplicate_of IS NULL OR is_duplicate_of <> posting_id),
    -- A duplicate must point at a posting stored in the same snapshot.
    FOREIGN KEY (snapshot_id, is_duplicate_of)
        REFERENCES postings (snapshot_id, posting_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX IF NOT EXISTS idx_postings_posting_id ON postings (posting_id);
CREATE INDEX IF NOT EXISTS idx_postings_board ON postings (snapshot_id, board_token);
CREATE INDEX IF NOT EXISTS idx_postings_text_hash ON postings (text_hash);

-- Rows with no exclusion reason (not placeholder, not empty/missing, not an exact duplicate).
CREATE VIEW IF NOT EXISTS usable_postings AS
SELECT * FROM postings WHERE exclusion_reason = '';
