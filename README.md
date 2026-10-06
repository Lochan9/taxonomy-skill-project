# Skill Taxonomy from Public Job Postings — Section B

Capstone project: *Taxonomy of Work*. Section B builds a **skill taxonomy** (a hierarchy of
capabilities derived from posting requirements) and evaluates it against **ESCO** and
**Lightcast Open Skills**. Section A builds the parallel task taxonomy; the two are joined in
Sprint 5 through a shared data contract (`docs/data_contract.md`).

Job postings come from the **Greenhouse Job Board API** (public, read-only endpoints at
`boards-api.greenhouse.io`). See "Data source" below for the open questions.

**Current status:** Sprint 1 (Data Acquisition & Exploration), in progress. The snapshot
fetcher is implemented and tested. A **pilot** snapshot (5 boards, 470 postings) was
collected on 2026-10-06; see `reports/sprint1_pilot_collection.md`. The board list is a
pilot proposal pending Section A. Pilot text cleaning is implemented (`src/prepare_postings.py`):
470 rows, 468 usable. See `reports/sprint1_cleaning_quality_20261006T171338Z.md`. The pilot
is loaded into a **local development** SQLite database (`src/load_postings.py`); the shared
database is still pending. A pilot exploration notebook is executed
(`notebooks/sprint1_exploration.ipynb`; findings in `reports/sprint1_exploration.md`). ESCO
v1.2.1 skill reference tables are imported into the same local database
(`reports/sprint1_esco_reference.md`). No extraction or ESCO mapping exists yet. See
`docs/sprint1_checklist.md`.

## Repository layout

```
config/            Pipeline configuration (board list, paths, model choice) — no secrets
data/raw/          Unmodified API responses (git-ignored)
data/processed/    Cleaned tables / local dev database (git-ignored)
data/raw_manifest.csv  Snapshot manifest (tracked; created by the first fetch)
data/reference/    ESCO, Lightcast, O*NET downloads (git-ignored)
docs/              Project brief, sprint checklists, data contract, Claude usage log
notebooks/         Exploration and evaluation notebooks
reports/           Sprint reports (incl. LLM token usage)
sql/               Versioned local-dev schema (schema_v1.sql) and migrations (migration_002_esco_reference.sql)
src/               Pipeline source code (fetch_greenhouse.py, prepare_postings.py, load_postings.py,
                   derive_features.py, register_esco_archive.py, load_esco.py,
                   select_annotation_set.py, annotations.py)
data/reference_manifest.csv  Reference-data file hashes (tracked; created on first registration)
data/annotation/   Sprint 2 annotation set: manifest, templates, human labels (tracked); texts/ (git-ignored)
tests/             pytest suite (mocked HTTP)
```

## Setup

Requires Python 3.11+ and Git.

```bash
git clone <repo-url> taxonomy-skill-project
cd taxonomy-skill-project

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt   # runtime deps + pytest + notebook tools
                                                # (runtime only: requirements.txt)

cp .env.example .env               # then fill in your own keys locally
```

All commands below assume the virtual environment is active and you are in the repo root.

## Tests

```bash
python -m pytest                   # mocked HTTP only; never touches the network
```

## Fetching Greenhouse snapshots

1. Add the agreed boards to `config/boards.yaml`. The file is a draft and the list stays
   empty until Section A agrees on it. The file's comments describe the format.
2. Preview the plan. This makes no network calls and changes no files:
   ```bash
   python src/fetch_greenhouse.py --dry-run
   ```
3. Fetch. The fetcher reuses verified cached snapshots and only fetches boards that have no
   valid cache:
   ```bash
   python src/fetch_greenhouse.py
   ```
4. Force a fresh snapshot of every board. This writes a new timestamped folder and never
   overwrites old snapshots:
   ```bash
   python src/fetch_greenhouse.py --refresh
   ```

Other options: `--timeout` (default 30 s per request), `--delay` (1 s between boards),
`--max-retries` (3, transient errors only), `--retry-budget` (60 s of retry waiting per
board), and `--config PATH`. See `python src/fetch_greenhouse.py --help`.

The run ends with a summary that lists **Fetched**, **Cached (reused)** and **Failed**
boards separately. Exit codes: `0` means every board was fetched or cached, `1` means at
least one board failed, and `2` means a configuration error. An empty board list prints a
message and exits `0` without doing anything.

How the fetcher behaves:
- It only sends `GET` requests to the public endpoint. It needs no key or authentication,
  never calls application-submission endpoints, and makes no LLM calls.
- `HTTP 429` and `5xx` responses and timeouts are retried with backoff. A `Retry-After`
  header is always honoured. If the requested wait is longer than the remaining retry
  budget, the board is reported as failed instead of being retried early.
- Responses that are not HTTP 200 with a JSON `jobs` list are reported as failed. They are
  never saved or added to the manifest.
- A cached file is reused only if its size and SHA-256 match the manifest. A reused cache
  keeps its original `snapshot_id` and `fetched_at`. A corrupted cached file is left in
  place, a warning is printed, and the board is fetched again.

`.env` is git-ignored. **Never commit API keys** (a requirement of the project brief). The
Greenhouse Job Board GET endpoints need no key. Keys are only needed for an LLM provider if
the pipeline later uses one (e.g. `ANTHROPIC_API_KEY` for the university-provided Anthropic
access, or a free-tier provider).

## Preparing (cleaning) postings

Turn one raw snapshot into one cleaned row per posting. You must name the snapshot
explicitly:

```bash
python src/prepare_postings.py --snapshot 20261006T171338Z
```

- **Inputs:** the snapshot's files listed in `data/raw_manifest.csv` (their SHA-256 is
  verified first, and processing stops on any mismatch) and the board metadata in
  `config/boards.yaml`. Raw files are opened read-only and never changed.
- **Outputs (git-ignored, regenerable):** `data/processed/postings_{snapshot_id}.jsonl` and
  `.csv` (UTF-8).
- **Quality report (tracked):** `reports/sprint1_cleaning_quality_{snapshot_id}.md`.
- **Columns (26, see data contract §2):** `posting_id` (`greenhouse:{board_token}:{job_id}`),
  source and board metadata, `company_name` (standardized, from config) and
  `source_company_name` (the API's value), `raw_text` (unmodified `content`), `clean_text`,
  `text_hash`, `word_count`, `is_placeholder`, `exclusion_reason`, `is_duplicate_of` and
  `cleaning_version`. A row is usable when `exclusion_reason` is empty.
- **Kept for audit:** flagged rows (missing or empty description, placeholder or
  talent-pool posting, exact duplicate) stay in the output and are never deleted.
- **List fields:** `departments` and `offices` are lists of names. They are JSON arrays in
  JSONL and JSON-encoded strings in CSV.
- **`source_language`:** Greenhouse's employer-set `language` field. It is not a detected
  language.

No skill extraction yet.

## Loading into a local SQLite database (development only)

This is **not** the shared database. The shared engine and location are still pending with
Section A (data contract D3). Each SQLite file is a separate local copy.

```bash
python src/load_postings.py \
  --input data/processed/postings_20261006T171338Z.jsonl \
  --db data/processed/taxonomy_pilot.sqlite
```

- **Schema:** `sql/schema_v1.sql` (version recorded in `schema_meta`). It has `snapshots`,
  `loads` (provenance: snapshot, cleaning version, input SHA-256, loader version) and
  `postings` (every processed field), plus a `usable_postings` view (rows with an empty
  `exclusion_reason`). No taxonomy tables yet.
- **Key:** `(snapshot_id, posting_id)`, so a new snapshot adds rows and never overwrites
  older posting text.
- **Safety:** the whole file is validated first and loaded in one transaction, with
  foreign keys enforced. The loader never updates or deletes rows.
- **Re-runs:** re-running the same input is a no-op. If a row with an existing key has
  different content, the whole load is rejected and nothing is written.
- **Exit codes:** `0` loaded or already loaded, `2` invalid input, `3` conflict, `4`
  database error.
- Requires SQLite ≥ 3.37, which Python's bundled SQLite normally satisfies. The `.sqlite`
  file is git-ignored.

## Exploration (pilot)

Derived features are stored **separately** from the immutable `postings` table. The database
is opened read-only (`mode=ro`).

```bash
# Seniority (rule-based), detected language (local lingua), near-duplicate candidate pairs
python src/derive_features.py --db data/processed/taxonomy_pilot.sqlite --snapshot 20261006T171338Z

# Execute the exploration notebook end to end (it also runs the derivation above)
jupyter nbconvert --to notebook --execute --inplace notebooks/sprint1_exploration.ipynb
```

- **Seniority rules:** `config/seniority_rules.yaml`, ordered, first match wins. Labels
  include `unknown` (no marker) and `ambiguous`. The rules version and SHA-256 are stored
  with each derived row.
- **Language:** the `lingua-language-detector` models ship inside the wheel, so detection
  makes no network calls. `source_language` is kept separately from `detected_language`.
  Uncertain rows are flagged with a reason.
- **Outputs:**
  - `data/processed/derived/{seniority,language}_{snapshot}.csv` (git-ignored)
  - `reports/sprint1_near_duplicate_candidates_{snapshot}.csv` (candidates only; nothing is
    excluded)
  - `reports/figures/*.png`
  - `reports/sprint1_exploration_metrics.json`
- **Integrity check:** the notebook hashes the database and raw snapshot before and after,
  and fails if anything changed.

## Sprint 2 preparation: human skill annotation (Team B)

**Status:** the selection is frozen and the workflow is ready. **No annotations exist yet**
(no gold labels, no LLM pre-labelling). See `reports/sprint2_annotation_preparation.md` and
`docs/skill_annotation_guidelines.md`.

```bash
# 100 usable postings: 20 development + 80 evaluation (the split is PROPOSED), seed 20261006
python src/select_annotation_set.py --db data/processed/taxonomy_pilot.sqlite --snapshot 20261006T171338Z --check
python src/annotations.py export   --db data/processed/taxonomy_pilot.sqlite   # texts (git-ignored) + templates
python src/annotations.py init     --annotator <id>
python src/annotations.py locate   --db data/processed/taxonomy_pilot.sqlite --posting <posting_id> --text "exact phrase"
python src/annotations.py validate --db data/processed/taxonomy_pilot.sqlite --dir data/annotation/sprint2_v1/annotators/<id>
python src/annotations.py compare  --db data/processed/taxonomy_pilot.sqlite --a <id1> --b <id2>
```

- **Offsets:** zero-based Python character positions into the unchanged `clean_text`, end
  exclusive.
- **Zero-skill postings:** a posting with `review_status = reviewed` and no skill rows is a
  deliberate zero-skill posting, not an unfinished one.
- **Tracked files:** the manifest, the templates and all human CSVs. The exported texts
  are not tracked.

## Reference data: ESCO (Section B)

**Status: ESCO v1.2.1 (English, classification, CSV) is imported into the local development
SQLite database.** It is not mapped to postings yet. See `reports/sprint1_esco_reference.md`.

- **Source and licence:** the official portal https://esco.ec.europa.eu/en/use-esco/download
  (Commission Decision 2011/833/EU: free reuse with attribution, "This service uses the
  ESCO classification of the European Commission"). The portal emails the download link,
  so a team member downloads it manually.
- **Files:** extracted under `data/reference/ESCO dataset - v1.2.1 - classification - en - csv`
  (git-ignored). The scripts locate the folder by this name prefix. The original ZIP was
  not kept, so only the CSVs are hashed.
- **Step 1, record SHA-256 hashes** in the tracked `data/reference_manifest.csv`. This is
  read-only and also writes `reports/esco_headers_v1.2.1.md`:

  ```bash
  python src/register_esco_archive.py --extracted-dir auto --version v1.2.1 --language en \
    --acquired-on YYYY-MM-DD --acquisition-evidence "how you know this date"
  # or, with the original ZIP:
  python src/register_esco_archive.py --archive "/path/to/download.zip" --version v1.2.1 --downloaded-on YYYY-MM-DD
  ```

- **Step 2, import.** Migration `sql/migration_002_esco_reference.sql` and the data load
  run in one transaction:

  ```bash
  python src/load_esco.py --db data/processed/taxonomy_pilot.sqlite --version v1.2.1 --source-dir auto
  ```

- **Tables:** `esco_concepts` (skills and skill groups), `esco_broader_relations` (plus the
  `esco_narrower_relations` view), `esco_skill_relations`, `esco_concept_schemes`,
  `esco_concept_scheme_members`, `esco_source_duplicates`, `esco_imports` and
  `schema_migrations`. The key is (`esco_version`, `concept_uri`), and source terms
  (`KnowledgeSkillCompetence`, `SkillGroup`, `essential` / `optional`, …) are kept verbatim.
- **Safety:**
  - Files must match their registered hashes.
  - Headers must match exactly.
  - Unresolved relationship endpoints abort the import.
  - Re-importing identical files is a no-op; different files for the same version are
    rejected.
  - Existing posting tables are never modified.
- **O*NET:** a shared dependency to coordinate with Section A (contract D10). It is not
  loaded, and the owner has not been agreed.

## Data source

- **Postings:** Greenhouse Job Board API, e.g.
  `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`.
  The list of company board tokens is in `config/boards.yaml` (pilot proposal, pending Section A).
- **Reference taxonomies:** ESCO skills (Section B's reference standard), Lightcast Open
  Skills (emerging-skill coverage), O*NET (shared with Section A; task–skill priors).

Open items before collecting (see the checklist):
1. The brief allows published datasets and official APIs. It names Kaggle, Adzuna and USAJobs
   only as examples, so Greenhouse not being listed does not by itself require approval. Ask
   the instructor if the team is uncertain whether the source is permitted.
2. The brief says both sections work from **the same corpus**, so **confirm with Section A**
   that Greenhouse is the shared source.
3. Only job-posting data may be stored. No personal data or individual profiles.

### Raw data snapshots

Raw responses are git-ignored, so they are preserved outside Git (full details in
`docs/data_contract.md` §10):

- Each fetch writes an immutable, timestamped snapshot:
  `data/raw/greenhouse/{snapshot_id}/{board_token}.json`.
- Fetching is cache-first: the latest snapshot is reused by default. An explicit refresh
  writes a new snapshot and never overwrites an old one.
- `data/raw_manifest.csv` is tracked in Git and lists every snapshot file with its SHA-256
  hash, so anyone can verify their copy.
- Snapshots are archived and uploaded to one shared location (to be agreed with Section A).
  To reproduce, download the canonical snapshot named in the data contract into `data/raw/`.

### Database

SQLite/DuckDB files under `data/processed/` are **local development copies only**. Each copy
is a separate file and is not shared automatically. The shared database engine and location
are pending agreement with Section A. The local SQLite loader is described above. Anyone with the
raw snapshot can rebuild an equivalent database (same posting rows; only the load timestamps
differ) by running `prepare_postings.py`, then `load_postings.py`.

## Documentation

| File | Purpose |
|---|---|
| `docs/master_project_description.pdf` | Course brief (source of truth) |
| `docs/sprint1_checklist.md` | Sprint 1 requirements vs. recommendations |
| `docs/data_contract.md` | Draft shared schema for agreement with Section A |
| `docs/claude_usage_log.md` | Log of Claude Code prompts and outcomes (graded) |
