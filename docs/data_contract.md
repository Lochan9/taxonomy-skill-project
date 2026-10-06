# Shared Data Contract (DRAFT v0.4)

**Status:** Draft v0.4 proposed by Section B (skills) for review by Section A (tasks). Not agreed yet.
**Required by:** the end of Sprint 1. The brief says "Both groups must agree on a shared schema
in Sprint 1 so that Sprint 5 can join the taxonomies without rework" (p.5).

Field notes use these labels:
- **[MIN]** Covers the brief's minimum "Must Capture" items (p.5–6). Do not drop.
- **[PROP]** Our proposal. Open to negotiation.

---

## 0. Decisions needed from both sections

| # | Decision | Section B proposal |
|---|---|---|
| D1 | Shared posting source | Greenhouse Job Board API (public, official API). Confirm with the instructor only if the team is unsure whether it is permitted (brief p.5) |
| D2 | Board (company) list and snapshot date | One shared `config/boards.yaml`, frozen on an agreed date |
| D3 | Shared database engine and location | **Pending agreement with Section A.** SQLite/DuckDB are fine for local development, but each copy is a separate file and is not shared automatically, so they do not satisfy the "shared database" deliverable on their own. Section B has a local-dev SQLite implementation of §2 (`sql/schema_v1.sql`, see §11) that can be ported to whatever engine is agreed |
| D8 | Raw snapshot storage and sharing | See §10. The shared storage location is still to be agreed |
| D4 | ID formats | See §1 |
| D5 | Representation for comparing topics across groups | One shared sentence-embedding model (name and version recorded) |
| D6 | Language scope | English only for v1, with the language detected and stored |
| D9 | ESCO version | **ESCO v1.2.1**, English, CSV "classification" package from the official portal (proposal). Imported into Section B's local-dev DB; the original ZIP was not kept, and the CSV hashes are in `data/reference_manifest.csv`. See `reports/sprint1_esco_reference.md` |
| D10 | O*NET loading (shared dependency) | Needed by both sections (task–skill priors, Sprint 5). **Owner and version to be coordinated with Section A; not agreed.** Section B has not loaded O*NET |
| D7 | Who owns which tables | Postings: joint. Statements, topics, membership, hierarchy: each section writes its own rows, separated by `kind`. Task–skill map: joint (Sprint 5) |

## 1. Conventions [PROP]

- IDs are strings and deterministic, so re-running a step produces the same IDs.
  - `posting_id = "greenhouse:{board_token}:{job_id}"`
  - `statement_id = "{run_id}:{posting_id}:{kind}:{n}"`, where `n` is the 0-based order
    within the posting for that run. Including `run_id` means two extraction runs over the
    same posting can never produce colliding IDs or overwrite each other's statements.
  - `topic_id = "{kind}:{run_id}:{local_id}"`
- Timestamps use ISO 8601 UTC.
- `kind` is an enum with exactly two values: `task` and `skill`.
- Every derived row records `run_id`, which links to the `runs` table (§8). This makes
  re-runs and parameter sweeps traceable.

## 2. `postings` — shared by both sections

This section matches the columns `src/prepare_postings.py` actually produces (cleaning
version `0.1.0`), in output order. **[NEW v0.3]** marks fields added in this version. Like
every [PROP] field, they are proposals pending Section A.

`posting_id` is the stable identifier of a posting across snapshots. Because the same posting
can appear in several snapshots with different text, a stored row is identified by
**(`snapshot_id`, `posting_id`)** **[NEW v0.3]**. This way a later snapshot never overwrites
historical text. Downstream tables that need a specific version of a posting should
reference the pair.

| Column | Type | Notes |
|---|---|---|
| `posting_id` | TEXT | **[MIN]** Stable identifier `greenhouse:{board_token}:{job_id}` |
| `source` | TEXT | **[MIN]** e.g. `greenhouse` |
| `source_job_id` | TEXT | [PROP] Greenhouse `id` |
| `internal_job_id` | TEXT NULL | **[NEW v0.3]** Greenhouse `internal_job_id`. Can group postings of one requisition |
| `board_token` | TEXT | [PROP] Company board identifier |
| `company_name` | TEXT | [PROP] Standardized name from `config/boards.yaml` |
| `source_company_name` | TEXT NULL | **[NEW v0.3]** The API's own `company_name`, unmodified (e.g. "Recursion", "Ōura") |
| `title` | TEXT | [PROP] |
| `location` | TEXT NULL | [PROP] `location.name` |
| `departments` | JSON array of TEXT | [PROP] Department names. Native array in JSONL, JSON-encoded text in CSV/SQL |
| `offices` | JSON array of TEXT | **[NEW v0.3]** Office names, serialized the same way as `departments` |
| `raw_text` | TEXT NULL | **[MIN]** Original `content` field, unmodified (entity-escaped HTML). NULL if the field is absent |
| `clean_text` | TEXT | [PROP] Decoded plain text with paragraph breaks and `- ` bullets. Empty if there is no description |
| `absolute_url` | TEXT | [PROP] Provenance link |
| `source_updated_at` | TIMESTAMP | [PROP] Greenhouse `updated_at`, as given (with offset) |
| `fetched_at` | TIMESTAMP | [PROP] From the raw manifest (UTC) |
| `snapshot_id` | TEXT | [PROP] Raw snapshot the row came from (§10). Part of the storage key |
| `industry` | TEXT NULL | [PROP] Team-assigned per board (Greenhouse has no industry field) |
| `industry_source` | TEXT NULL | **[NEW v0.3]** Where the industry label came from |
| `source_language` | TEXT NULL | **[NEW v0.3]** Greenhouse's employer-set `language` field. **Not detected** (replaces the v0.2 "detected `language`") |
| `text_hash` | TEXT NULL | [PROP] SHA-256 of normalized `clean_text` (NFKC, casefold, whitespace collapsed). NULL if the text is empty |
| `word_count` | INTEGER | **[NEW v0.3]** Tokens of `clean_text` that contain a letter or digit |
| `is_placeholder` | BOOLEAN | **[NEW v0.3]** General-interest / talent-pool posting (heuristic) |
| `exclusion_reason` | TEXT | **[NEW v0.3]** `;`-separated reasons (`missing_description`, `empty_description`, `placeholder_title:*`, `placeholder_text:*`, `exact_duplicate`). Empty string means usable. Flagged rows are kept |
| `is_duplicate_of` | TEXT NULL | [PROP] `posting_id` of the canonical copy, for exact normalized-text duplicates within the snapshot |
| `cleaning_version` | TEXT | **[NEW v0.3]** Version of the cleaning rules that produced the row |

Planned but **not yet produced**: `seniority` (derived from the title) and
`detected_language` (output of a language detector, kept separate from `source_language`).
The methods are still to be documented.

## 3. `statements` — one row per extracted task or skill

| Column | Type | Notes |
|---|---|---|
| `statement_id` | TEXT PK | |
| `posting_id` | TEXT | **[MIN]** Link back to the posting |
| `snapshot_id` | TEXT | **[NEW v0.3]** With `posting_id`, an FK to the exact stored posting version the statement was extracted from |
| `kind` | TEXT | **[MIN]** `task` or `skill` |
| `text` | TEXT | **[MIN]** The atomic statement, normalized |
| `source_span` | TEXT | [PROP] Original sentence or snippet it came from (evidence) |
| `section` | TEXT | [PROP] e.g. responsibilities, requirements, nice-to-have |
| `extraction_method` | TEXT | [PROP] e.g. `rules`, `llm:gemini-…` |
| `run_id` | TEXT FK → runs | [PROP] Also embedded in `statement_id`; keeps runs from colliding |

## 4. `topics` — leaf topics (and parent nodes)

| Column | Type | Notes |
|---|---|---|
| `topic_id` | TEXT PK | |
| `kind` | TEXT | `task` or `skill` |
| `name` | TEXT | **[MIN]** |
| `description` | TEXT | **[MIN]** |
| `size` | INTEGER | **[MIN]** Number of member statements |
| `level` | INTEGER | [PROP] 0 = leaf |
| `embedding` | FLOAT[] / BLOB | **[MIN]** Cross-group comparable representation, e.g. the centroid |
| `embedding_model` | TEXT | [PROP] Must be the same model in both sections (D5) |
| `reference_match` | TEXT NULL | [PROP] Closest ESCO/O*NET concept URI or code |
| `run_id` | TEXT FK → runs | [PROP] |

## 5. `topic_membership`

| Column | Type | Notes |
|---|---|---|
| `statement_id` | TEXT FK → statements | **[MIN]** |
| `topic_id` | TEXT FK → topics | **[MIN]** |
| `strength` | REAL NULL | **[MIN]** (optional per the brief) 0–1 |
| PK | (`statement_id`, `topic_id`) | Allows multi-topic membership if a section chooses it |

## 6. `topic_hierarchy`

| Column | Type | Notes |
|---|---|---|
| `parent_topic_id` | TEXT FK → topics | **[MIN]** |
| `child_topic_id` | TEXT FK → topics | **[MIN]** |
| `kind` | TEXT | [PROP] |
| PK | (`parent_topic_id`, `child_topic_id`) | An edge list, so it supports more than two levels **[MIN]** |

## 7. `task_skill_map` — joint, Sprint 5

| Column | Type | Notes |
|---|---|---|
| `task_topic_id` | TEXT FK → topics (`kind=task`) | **[MIN]** |
| `skill_topic_id` | TEXT FK → topics (`kind=skill`) | **[MIN]** |
| `score` | REAL | **[MIN]** |
| `evidence` | TEXT (JSON) | **[MIN]** e.g. co-occurring `posting_id`s, similarity value, O*NET prior |
| `method` | TEXT | [PROP] |
| `run_id` | TEXT FK → runs | [PROP] |

## 8. Supporting tables [PROP]

- `runs(run_id, kind, step, started_at, git_commit, config_json, llm_tokens_in, llm_tokens_out)`
  supports reproducibility and the token-usage reporting the brief requires (p.7).
- Reference tables, loaded unmodified with a `source_version` column: `ref_esco_skills`,
  `ref_esco_skill_relations`, `ref_lightcast_skills`, `ref_onet_tasks`, `ref_onet_skills`,
  `ref_onet_occupation_skills`.
- **ESCO (Section B), v0.4:** implemented in local-dev SQLite through
  `sql/migration_002_esco_reference.sql`, designed from the real v1.2.1 headers. These tables
  replace the placeholder names `ref_esco_skills` and `ref_esco_skill_relations`. **[PROP]**,
  pending Section A:
  - `esco_concepts`: key (`esco_version`, `concept_uri`). Columns: `concept_type`
    (`KnowledgeSkillCompetence` | `SkillGroup`, source terms), `preferred_label`,
    `alt_labels` / `hidden_labels` (JSON arrays), `description`, `definition`,
    `scope_note`, `skill_type`, `reuse_level`, `code`, `status`, `modified_date`,
    `source_file`, `source_row_count`.
  - `esco_broader_relations`: `concept_uri → broader_uri`, with source `concept_type` and
    `broader_type`. The view `esco_narrower_relations` gives the inverse.
  - `esco_skill_relations`: source `relation_type` (`essential` / `optional`) and both
    skill types.
  - `esco_concept_schemes` and `esco_concept_scheme_members` (from `inScheme`).
  - `esco_source_duplicates`: an audit of source rows that repeat a URI.
  - `esco_imports`: provenance, including file hashes, the acquisition date and its
    evidence.
  - `schema_migrations`: the applied migrations. `schema_meta.schema_version` stays the
    postings schema version.
  - Downstream (Sprint 4) evaluation should reference (`esco_version`, `concept_uri`).
- **O*NET:** a shared dependency (D10), with ownership not yet agreed.

## 9. Change process [PROP]

Every schema change goes through a PR that edits this file and is approved by at least one
member of each section. Bump the version on each change and keep a changelog below.

## 10. Raw snapshot preservation and sharing [PROP]

Raw API responses are excluded from Git (`data/raw/*`), so they are preserved like this:

- **Layout:** `data/raw/greenhouse/{snapshot_id}/{board_token}.json`, where
  `snapshot_id = YYYYMMDDTHHMMSSZ` (UTC fetch start time). Each file holds the unmodified
  response body.
- **Immutable:** a snapshot folder is never edited or overwritten after it is written.
  Cleaning happens downstream in `data/processed/`.
- **Cache-first fetching:** by default the fetcher reuses the latest existing snapshot. A
  refresh only happens when explicitly requested (e.g. a `--refresh` flag), and it writes a
  **new** timestamped snapshot instead of replacing the old one.
- **Manifest (tracked in Git):** `data/raw_manifest.csv` with one row per file:
  `snapshot_id, board_token, file_path, fetched_at, http_status, job_count, sha256, bytes`.
  Anyone can check that their local copy matches the canonical one by comparing hashes.
  Only successful responses (HTTP 200 with a valid `jobs` list) are written and recorded.
  Failed responses are reported by the fetcher and never stored. Implemented in
  `src/fetch_greenhouse.py`.
- **Sharing:** each completed snapshot is archived (`{snapshot_id}.tar.gz`) and uploaded to
  one agreed shared location, for example a university-managed drive folder or a private
  GitHub Release asset. **The location is to be agreed with Section A (D8).** Nobody should
  rely on a teammate's local `data/raw/`.
- **Canonical snapshot:** the snapshot used for deliverables is named in this contract
  (below) once frozen, so both sections build from identical input.

Canonical snapshot: *not yet fetched*.

## 11. Local development storage (Section B) [PROP]

This is a reference implementation of §2, **not** the shared database (D3 is still pending).

- **Schema:** `sql/schema_v1.sql` (SQLite ≥ 3.37, STRICT tables, foreign keys on).
- **Tables:**
  - `postings`: every §2 field, plus `load_id`. Primary key (`snapshot_id`, `posting_id`).
  - `snapshots`: `snapshot_id`, `source`, `first_loaded_at`.
  - `loads`: `snapshot_id`, `cleaning_version`, `input_path`, `input_sha256`, `row_count`,
    `inserted_rows`, `loader_version` and `loaded_at`. Unique on (`snapshot_id`,
    `cleaning_version`, `input_sha256`).
- **Field encoding:** `departments` and `offices` are stored as JSON-array text (checked
  with `json_valid`). `is_placeholder` is stored as 0/1.
- **Duplicates:** `is_duplicate_of` has a composite foreign key to (`snapshot_id`,
  `posting_id`) in the same snapshot.
- **View:** `usable_postings` holds the rows with an empty `exclusion_reason`.
- **Loading rules** (`src/load_postings.py`):
  - Insert only, all rows in one transaction.
  - Identical input is a no-op.
  - Different content for an existing key is rejected, including a different
    `cleaning_version` for the same snapshot. Reloading a snapshot under new cleaning rules
    therefore needs a new database or a future schema version. This is an open design point.

### Changelog
- v0.4: ESCO v1.2.1 reference tables defined from the real headers and implemented in local-dev SQLite (§8). D9 updated. O*NET remains a shared dependency (D10, owner not agreed).
- v0.3.2: Added D9 (ESCO version proposal: v1.2.1 en CSV) and D10 (O*NET as a shared dependency, owner not agreed). §8 records the ESCO acquisition status: registration tool and manifest exist; tables wait for the real headers.
- v0.3.1: Added §11 describing Section B's local-dev SQLite implementation. D3 is still pending.
- v0.3: §2 now matches the cleaner's actual output (cleaning version 0.1.0). Proposed new
  fields, all pending Section A: `internal_job_id`, `source_company_name`, `offices`,
  `industry_source`, `source_language` (replaces the detected `language`), `word_count`,
  `is_placeholder`, `exclusion_reason` and `cleaning_version`. `departments` and `offices`
  are typed as JSON arrays of names. Stored rows are keyed by (`snapshot_id`, `posting_id`).
  `seniority` and `detected_language` are moved to "planned". `statements` gains
  `snapshot_id`, so (`snapshot_id`, `posting_id`) references a stored posting version.
- v0.2.1: D1 no longer says instructor approval is unconditionally pending. §10 notes that
  only successful responses are stored.
- v0.2: `statement_id` now includes `run_id`. The shared DB engine/location is pending
  (SQLite/DuckDB are local-dev only). Added `snapshot_id` to postings, §10 on raw snapshot
  preservation, and decision D8.
- v0.1: Initial draft (Section B).
