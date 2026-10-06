# Shared Data Contract (DRAFT v0.2)

**Status:** Draft v0.2 proposed by Section B (skills) for review by Section A (tasks). Not agreed yet.
**Required by:** the end of Sprint 1. The brief says "Both groups must agree on a shared schema
in Sprint 1 so that Sprint 5 can join the taxonomies without rework" (p.5).

Field notes use these labels:
- **[MIN]** Covers the brief's minimum "Must Capture" items (p.5–6). Do not drop.
- **[PROP]** Our proposal. Open to negotiation.

---

## 0. Decisions needed from both sections

| # | Decision | Section B proposal |
|---|---|---|
| D1 | Shared posting source | Greenhouse Job Board API (pending instructor approval) |
| D2 | Board (company) list and snapshot date | One shared `config/boards.yaml`, frozen on an agreed date |
| D3 | Shared database engine and location | **Pending agreement with Section A.** SQLite/DuckDB are fine for local development, but each copy is a separate file and is not shared automatically, so they do not satisfy the "shared database" deliverable on their own |
| D8 | Raw snapshot storage and sharing | See §10. The shared storage location is still to be agreed |
| D4 | ID formats | See §1 |
| D5 | Representation for comparing topics across groups | One shared sentence-embedding model (name and version recorded) |
| D6 | Language scope | English only for v1, with the language detected and stored |
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

| Column | Type | Notes |
|---|---|---|
| `posting_id` | TEXT PK | **[MIN]** Stable identifier |
| `source` | TEXT | **[MIN]** e.g. `greenhouse` |
| `raw_text` | TEXT | **[MIN]** Original `content` field, unmodified (HTML) |
| `clean_text` | TEXT | [PROP] HTML-unescaped, tags stripped |
| `source_job_id` | TEXT | [PROP] Greenhouse `id` |
| `board_token` | TEXT | [PROP] Company board identifier |
| `company_name` | TEXT | [PROP] |
| `title` | TEXT | [PROP] |
| `location` | TEXT | [PROP] `location.name` |
| `departments` | TEXT (JSON) | [PROP] |
| `absolute_url` | TEXT | [PROP] Provenance link |
| `source_updated_at` | TIMESTAMP | [PROP] Greenhouse `updated_at` |
| `fetched_at` | TIMESTAMP | [PROP] |
| `snapshot_id` | TEXT | [PROP] Raw snapshot the row was loaded from (§10) |
| `industry` | TEXT | [PROP] Derived (Greenhouse has no industry field). Method to be documented |
| `seniority` | TEXT | [PROP] Derived from the title. Method to be documented |
| `language` | TEXT | [PROP] ISO 639-1, detected |
| `text_hash` | TEXT | [PROP] Hash of `clean_text`, for duplicate detection |
| `is_duplicate_of` | TEXT NULL | [PROP] `posting_id` of the canonical copy |

## 3. `statements` — one row per extracted task or skill

| Column | Type | Notes |
|---|---|---|
| `statement_id` | TEXT PK | |
| `posting_id` | TEXT FK → postings | **[MIN]** Link back to the posting |
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
- **Sharing:** each completed snapshot is archived (`{snapshot_id}.tar.gz`) and uploaded to
  one agreed shared location, for example a university-managed drive folder or a private
  GitHub Release asset. **The location is to be agreed with Section A (D8).** Nobody should
  rely on a teammate's local `data/raw/`.
- **Canonical snapshot:** the snapshot used for deliverables is named in this contract
  (below) once frozen, so both sections build from identical input.

Canonical snapshot: *not yet fetched*.

### Changelog
- v0.2: `statement_id` now includes `run_id`. The shared DB engine/location is pending
  (SQLite/DuckDB are local-dev only). Added `snapshot_id` to postings, §10 on raw snapshot
  preservation, and decision D8.
- v0.1: Initial draft (Section B).
