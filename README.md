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

**Platforms.** The code is developed and tested on **macOS** (Apple silicon, Python 3.14).
- The dashboard's review log is protected by an inter-process file lock: `fcntl` on macOS,
  Linux and WSL, and `msvcrt` on native Windows.
- **Native Windows has not been tested.** The Windows lock is covered only by mocked tests.
- Neither module is a pip package: both come with Python on their own platform. Don't try to
  `pip install fcntl`.
- If the review folder cannot be locked (some network or cloud-synced folders), saving a
  decision is refused with a clear error, and decisions are never written without the lock.
  Use `--reviews-dir` on a local disk.

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

**Status:** the selection is frozen and the workflow is ready. **No human annotations or gold
labels exist yet.** AI-assisted drafts for the 20 development postings sit in separate
`annotators/ai_draft/` and `annotators/ai_revised/` workspaces, labelled as AI drafts and not
human-reviewed (see `docs/claude_usage_log.md`). See `reports/sprint2_annotation_preparation.md`
and `docs/skill_annotation_guidelines.md`.

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

## Sprint 2: skill extraction with an LLM (Team B)

**Status: implemented, tested with mocked responses, and piloted once.** Pilot run
`skx-20261007T003601Z` used `claude-sonnet-5-5` on 3 development postings: 3 of 3 ok, 35
statements accepted, 0 rejected, 14,266 input and 7,860 output tokens (about $0.098). Its
output is AI-generated and unreviewed. The other 17 development postings have not been run.
Mapping to ESCO is out of scope here.

`src/extract_skills.py` sends each **development** posting's unchanged `clean_text` to an
LLM. It uses the official Anthropic SDK behind a small provider interface (`Backend`), with
structured JSON output. It then checks the result locally.

```bash
python src/extract_skills.py --dry-run --limit 3        # no network, no API key, writes nothing
python src/extract_skills.py --model <model-id> --limit 3
python src/extract_skills.py --model <model-id> --resume <run_id>
```

- **Scope:** only the frozen selection's 20 `development` postings (`ALLOWED_SPLITS`). The
  80 evaluation postings are refused, and each text is checked against the manifest
  SHA-256.
- **Model and key:**
  - The model is never guessed: pass `--model` or set `EXTRACTION_MODEL` in `.env` after
    checking which models the account can use.
  - `ANTHROPIC_API_KEY` is read from `.env` (or the environment). It is never printed or
    stored.
  - Optional request settings, such as `effort`, are in `config/extraction.yaml` and are off
    by default.
- **Prompt and schema (versioned):**
  - `config/prompts/skill_extraction_v1.md` and
    `config/schemas/skill_extraction_output_v1.json`
  - Each skill record has a statement, exact `evidence_text` plus its `evidence_context`,
    the section heading, `requirement_status`, `mention_relation` (`direct` |
    `illustrative_example` | `category`, a proposed field; see data contract §12), the
    `alternative_group`, and an optional category.
- **Local validation:**
  - The output must match the JSON schema.
  - Evidence must occur exactly in `clean_text`. Offsets are computed locally, and the
    model never supplies positions.
  - Repeated evidence is resolved through its context sentence, or rejected as ambiguous.
  - Unsupported or duplicate records are rejected individually (`rejected.jsonl`).
  - Invalid alternative groups are dropped with a warning.
- **Result per posting:**
  - `ok`
  - `zero_skills`: a valid empty result with a reason
  - `all_rejected`
  - `failed`: an API error after bounded retries, a refusal, truncation, invalid JSON or a
    schema violation
- **Cache and resumability:**
  - Responses are cached under a key built from the `clean_text` hash, the model, the
    prompt and schema versions and file hashes, and the request settings. A re-run is free,
    and an invalid cached response is called again.
  - Every response received is kept under `responses/`.
  - `--resume` re-runs only unfinished or failed postings.
- **Robustness:**
  - per-request timeout
  - bounded attempts with exponential backoff, honouring `retry-after` on 429
  - client-side pacing; non-retryable 4xx errors fail at once
- **Provenance:** `runs/{run_id}/run.json` records the model, prompt and schema versions
  and hashes, the git commit, the config, the SDK version, counts, failures and the token
  usage actually billed (`llm_tokens_in` / `llm_tokens_out`). Statement IDs follow contract
  §1: `{run_id}:{posting_id}:skill:{n}`.
- **Outputs:** `data/extraction/` (cache, responses, runs) is git-ignored.
- **Open:** the brief (p.7) asks for a free-tier or student-credit provider. The access is
  recorded as university-provided Anthropic access, with compliance **unresolved**
  (`config/extraction.yaml`). Results are not yet loaded
  into a `statements` table (the shared database, D3, is still open).

## Team B dashboard (local)

A local browser dashboard with three views: **corpus explorer**, **extraction results**,
and **annotation review**. It is built on the Python standard library alone (WSGI), with no
new dependencies, CDNs or external requests.

```bash
.venv/bin/python src/dashboard.py              # http://127.0.0.1:8765/  (Ctrl+C to stop)
.venv/bin/python src/dashboard.py --port 8800  # another port
```

- **Local only:** it binds to `127.0.0.1` and refuses other `Host` headers. It never reads
  `.env`, holds no keys and makes no API calls; the browser talks only to this server.
  Writes need a same-origin JSON request with a custom header.
- **Read-only sources:**
  - the SQLite DB (`mode=ro`)
  - `reports/sprint1_exploration_metrics.json` and `reports/figures/`
  - `data/processed/derived/` (seniority)
  - `data/extraction/runs/`
  - the AI draft workspaces `annotators/ai_revised` and `annotators/ai_draft`
- **Held-out data:**
  - The text of the 80 evaluation postings appears **only** in the explicit evaluation
    annotation mode, with no AI drafts or predictions. The corpus explorer, extraction
    results and development review never show it.
  - Non-selected variants grouped with an evaluation posting are never shown.
  - The extraction and development review views accept development postings only, and the
    human annotator folders are not loaded.
- **Extraction results** are labelled *AI-generated, unreviewed* and shown exactly as
  stored:
  - Evidence is highlighted only where the stored offsets match `clean_text`; mismatches
    are flagged, never moved.
  - Illustrative examples, categories and individual requirements are badged differently.
  - Postings without a result show an empty state.
- **Annotation review** (`src/review_workflow.py`): complete annotation in the browser, with no CSV
  editing and no annotation commands.
  - **Two modes.**
    - *Development review* works through the AI drafts (`ai_revised` or `ai_draft`) of the 20
      development postings.
    - *Evaluation annotation* covers the 80 evaluation postings: original text, empty skill
      lists, and no AI drafts, predictions or highlights. It opens only after an explicit
      confirmation, and its text is served only with the `X-Dashboard-Mode: evaluation`
      header. Corpus, extraction and development review still refuse it, and the frozen split
      and the extractor's development-only guard are unchanged.
  - **Actions:** accept, edit (wording, exact evidence, required/preferred/unspecified,
    category, alternative group, notes), reject (delete in evaluation mode), reopen, add,
    **split** (the original stays in the history as *split*; each part links back through
    `split_from`), and **resolve discussion**, which needs a recorded reason. There is no bulk
    accept.
  - **Evidence** must be copied exactly. The server computes offsets against the original
    `clean_text` and asks for an occurrence when the text repeats. Selecting text in the
    posting fills the evidence field.
  - **The page:** posting text sits beside the skill cards, and clicking a card highlights and
    scrolls to its evidence. Filters (pending, accepted, edited, rejected, added/split,
    discussion) show live counts. AI provenance notes sit behind **Details**, while DISCUSS
    and stale warnings stay visible. Previous/next buttons and overall progress are at the
    top. Saving shows *Saving…*, then *Saved* only after the write succeeds, or an error or
    conflict.
  - **Completion** ("Mark posting reviewed") is an explicit human action.
    - It needs every suggestion decided, every blocking discussion resolved, no stale
      records and valid alternative groups.
    - You must confirm that you read the full description and checked for missing skills. A
      posting with no records needs a deliberate zero-skill confirmation.
    - It records the reviewer, a timestamp, the text hash, the draft hash and the guidelines
      version.
    - Any later change, or "Reopen posting", invalidates the completion until it is
      reconfirmed.
  - **Integrity:**
    - Decisions are appended, never rewritten, to `reviews/<reviewer>/decisions.jsonl`
      (git-ignored: review logs and `reviewed/` exports stay local for now), and
      the state is replayed from that log after a refresh or a server restart.
    - Every write carries the posting version it expected (a stale tab gets a **conflict**,
      never a silent overwrite), the draft file hash (a changed draft is refused and flagged
      as *stale*), and a client request ID (a repeated click is never written twice).
    - Events record `actor: human`, and AI workspace names are refused as reviewer IDs.
  - **Export** (Export… dialog):
    - Builds the existing annotation CSV format (`skills.csv`, `postings_review.csv`) from
      your latest decisions: rejected records are omitted, and additions and split parts are
      included.
    - Validates it with `annotations.validate`, shows a preview, and offers downloads.
    - "Write export folder" writes a **new** folder,
      `reviewed/<reviewer>/<mode>-<timestamp>/` (CSVs, `provenance.jsonl`, `export.json`). It
      is never written under `annotators/`, and an invalid export is refused.
    - Exports are marked **partial** or **complete** (every posting in that mode marked
      reviewed), and **never gold** until adjudicated. Each row's notes keep the AI-assisted
      origin and the human decision.

  ```bash
  .venv/bin/python src/dashboard.py --reviews-dir /tmp/try_reviews --reviewed-dir /tmp/try_reviewed  # practice run
  .venv/bin/python src/dashboard.py   # real review: decisions in reviews/, exports in reviewed/
  ```
- **Tests:**
  - `tests/test_dashboard.py` (14 route and safety tests, including one against a real
    `wsgiref` server)
  - `tests/test_review_workflow.py` (31 workflow tests)
- **Browser verification (2026-10-07, review workflow):** `tests/browser/verify_dashboard.py`
  drove the installed Google Chrome headlessly with Playwright 1.63, against a dashboard
  started with **temporary** `--reviews-dir` and `--reviewed-dir` and the test reviewer
  `pwtest`. **74/74 checks passed:**
  - corpus and extraction views
  - accept, edit, reject, reopen, add and split
  - repeated evidence, invalid evidence, and discussion resolution
  - completion, invalidation and reconfirmation
  - refresh persistence, previous/next navigation, and a double click writing once
  - a stale second tab getting a conflict, then reloading
  - export preview, download and write
  - the evaluation gate, an empty start, add/delete/reopen/complete and its own export
  - held-out routes refused, no horizontal scroll at 390 px, and no unexpected console
    errors

  The real `reviews/` and `reviewed/` folders were not written, and every source and
  workspace file stayed byte-identical. Playwright is optional. To rerun (screenshots go to
  the git-ignored `reports/dashboard_screenshots/`):

  The script first asks the server where it writes (`/api/review/storage`). It refuses to run
  unless that is the temporary folders, so a dashboard already running on the port with real data
  is never used. Pick a free port with `DASH_URL`:

  ```bash
  python -m venv /tmp/pwvenv && /tmp/pwvenv/bin/pip install playwright
  .venv/bin/python src/dashboard.py --port 8799 --reviews-dir /tmp/dash_reviews --reviewed-dir /tmp/dash_reviewed &
  DASH_URL=http://127.0.0.1:8799 /tmp/pwvenv/bin/python tests/browser/verify_dashboard.py /tmp/dash_check /tmp/dash_reviews /tmp/dash_reviewed <eval_id> <variant_id>
  ```

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
