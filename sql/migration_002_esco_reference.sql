-- Migration 002: ESCO skill-pillar reference tables (Section B, Sprint 1). LOCAL DEVELOPMENT.
--
-- Applied by src/load_esco.py inside the same transaction as the import. It only ADDS tables
-- and views; existing tables (snapshots, loads, postings, schema_meta) are not altered.
-- Designed from the actual ESCO v1.2.1 English CSV headers (reports/esco_headers_v1.2.1.md).
--
-- Keys: every ESCO row is keyed by (esco_version, <uri>), so versions never overwrite each other.
-- Terminology: concept_type, skill_type, reuse_level, broader_type and relation_type keep the
-- source values verbatim (e.g. 'KnowledgeSkillCompetence', 'SkillGroup', 'skill/competence',
-- 'essential', 'optional'). No hierarchy link is created that is not in the source files.
-- Labels are English (the import language is recorded in esco_imports).

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    applied_at   TEXT NOT NULL
) STRICT;

-- One row per distinct import (identical source files are recorded once).
CREATE TABLE IF NOT EXISTS esco_imports (
    import_id           INTEGER PRIMARY KEY,
    esco_version        TEXT NOT NULL CHECK (esco_version GLOB 'v[0-9]*.[0-9]*.[0-9]*'),
    language            TEXT NOT NULL,
    source_dir          TEXT NOT NULL,
    source_files_sha256 TEXT NOT NULL,   -- SHA-256 over the sorted (file name, file SHA-256) list
    source_files        TEXT NOT NULL CHECK (json_valid(source_files)),  -- {file: sha256}
    acquired_on         TEXT NOT NULL,
    acquisition_note    TEXT NOT NULL,
    importer_version    TEXT NOT NULL,
    imported_at         TEXT NOT NULL,
    concept_count       INTEGER NOT NULL,
    broader_count       INTEGER NOT NULL,
    skill_relation_count INTEGER NOT NULL,
    UNIQUE (esco_version, language)
) STRICT;

CREATE TABLE IF NOT EXISTS esco_concept_schemes (
    esco_version    TEXT NOT NULL,
    scheme_uri      TEXT NOT NULL,
    concept_type    TEXT NOT NULL,
    preferred_label TEXT,
    title           TEXT,
    status          TEXT,
    description     TEXT,
    import_id       INTEGER NOT NULL REFERENCES esco_imports (import_id),
    PRIMARY KEY (esco_version, scheme_uri)
) STRICT;

-- Skill/knowledge concepts (skills_en.csv) and skill groups (skillGroups_en.csv).
CREATE TABLE IF NOT EXISTS esco_concepts (
    esco_version     TEXT NOT NULL,
    concept_uri      TEXT NOT NULL,
    concept_type     TEXT NOT NULL CHECK (concept_type IN ('KnowledgeSkillCompetence', 'SkillGroup')),
    preferred_label  TEXT NOT NULL,
    alt_labels       TEXT NOT NULL CHECK (json_valid(alt_labels) AND json_type(alt_labels) = 'array'),
    hidden_labels    TEXT NOT NULL CHECK (json_valid(hidden_labels) AND json_type(hidden_labels) = 'array'),
    description      TEXT,
    definition       TEXT,           -- skills only
    scope_note       TEXT,
    skill_type       TEXT,           -- skills only; source value, may be empty in source
    reuse_level      TEXT,           -- skills only; source value, may be empty in source
    code             TEXT,           -- skill groups only (skos:notation)
    status           TEXT,
    modified_date    TEXT,
    source_file      TEXT NOT NULL,
    source_row_count INTEGER NOT NULL CHECK (source_row_count >= 1),  -- >1 when the source repeats the URI
    import_id        INTEGER NOT NULL REFERENCES esco_imports (import_id),
    PRIMARY KEY (esco_version, concept_uri)
) STRICT;

CREATE TABLE IF NOT EXISTS esco_concept_scheme_members (
    esco_version TEXT NOT NULL,
    concept_uri  TEXT NOT NULL,
    scheme_uri   TEXT NOT NULL,
    PRIMARY KEY (esco_version, concept_uri, scheme_uri),
    FOREIGN KEY (esco_version, concept_uri) REFERENCES esco_concepts (esco_version, concept_uri),
    FOREIGN KEY (esco_version, scheme_uri) REFERENCES esco_concept_schemes (esco_version, scheme_uri)
) STRICT;

-- broaderRelationsSkillPillar_en.csv: child -> broader (skos:broader), both endpoints validated.
CREATE TABLE IF NOT EXISTS esco_broader_relations (
    esco_version TEXT NOT NULL,
    concept_uri  TEXT NOT NULL,
    concept_type TEXT NOT NULL,
    broader_uri  TEXT NOT NULL,
    broader_type TEXT NOT NULL,
    import_id    INTEGER NOT NULL REFERENCES esco_imports (import_id),
    PRIMARY KEY (esco_version, concept_uri, broader_uri),
    CHECK (concept_uri <> broader_uri),
    FOREIGN KEY (esco_version, concept_uri) REFERENCES esco_concepts (esco_version, concept_uri),
    FOREIGN KEY (esco_version, broader_uri) REFERENCES esco_concepts (esco_version, concept_uri)
) STRICT;

-- skillSkillRelations_en.csv: relation_type is the source value ('essential' / 'optional').
CREATE TABLE IF NOT EXISTS esco_skill_relations (
    esco_version       TEXT NOT NULL,
    original_skill_uri TEXT NOT NULL,
    original_skill_type TEXT NOT NULL,
    relation_type      TEXT NOT NULL,
    related_skill_type TEXT NOT NULL,
    related_skill_uri  TEXT NOT NULL,
    import_id          INTEGER NOT NULL REFERENCES esco_imports (import_id),
    PRIMARY KEY (esco_version, original_skill_uri, related_skill_uri),
    FOREIGN KEY (esco_version, original_skill_uri) REFERENCES esco_concepts (esco_version, concept_uri),
    FOREIGN KEY (esco_version, related_skill_uri) REFERENCES esco_concepts (esco_version, concept_uri)
) STRICT;

-- Audit of source rows that repeat a concept URI (kept = the row loaded into esco_concepts).
CREATE TABLE IF NOT EXISTS esco_source_duplicates (
    esco_version      TEXT NOT NULL,
    concept_uri       TEXT NOT NULL,
    source_file       TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,  -- 1-based data row in the CSV (header excluded)
    modified_date     TEXT,
    differing_fields  TEXT NOT NULL CHECK (json_valid(differing_fields)),
    kept              INTEGER NOT NULL CHECK (kept IN (0, 1)),
    import_id         INTEGER NOT NULL REFERENCES esco_imports (import_id),
    PRIMARY KEY (esco_version, source_file, source_row_number),
    FOREIGN KEY (esco_version, concept_uri) REFERENCES esco_concepts (esco_version, concept_uri)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_esco_broader_parent ON esco_broader_relations (esco_version, broader_uri);
CREATE INDEX IF NOT EXISTS idx_esco_skill_rel_related ON esco_skill_relations (esco_version, related_skill_uri);
CREATE INDEX IF NOT EXISTS idx_esco_concepts_label ON esco_concepts (esco_version, preferred_label);

-- skos:narrower is the inverse of skos:broader; exposed as a view, not stored twice.
CREATE VIEW IF NOT EXISTS esco_narrower_relations AS
SELECT esco_version, broader_uri AS concept_uri, broader_type AS concept_type,
       concept_uri AS narrower_uri, concept_type AS narrower_type, import_id
FROM esco_broader_relations;
