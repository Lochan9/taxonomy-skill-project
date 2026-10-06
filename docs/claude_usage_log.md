# Claude Code Usage Log — Section B

The brief asks teams to "keep a log of useful prompts that worked well" and to "document your
Claude Code interactions and LLM prompts in your sprint reports" (p.6–7). Claude Code usage is
worth 15 of the 100 rubric points.

Add one entry per meaningful session. Keep entries short and record what you verified yourself.

## Template

```
### YYYY-MM-DD — <short title>  (Sprint N, <who>)
**Goal:**
**Prompt (summary or verbatim):**
**What Claude did:**
**What we checked / changed:**
**Outcome / lessons:**
```

---

## Sprint 1

### 2026-10-06 — Project scaffolding (Sprint 1)
**Goal:** Set up the repository structure and the Sprint 1 planning docs from the master brief,
with no data fetching or extraction yet.
**Prompt (summary):** Read `docs/master_project_description.pdf`. We are Section B, building
a skill taxonomy from Greenhouse Job Board API postings. Create the folder structure (`src/`,
`data/{raw,processed,reference}/`, `notebooks/`, `reports/`, `config/`), plus README,
`.gitignore`, `.env.example`, a Sprint 1 checklist, a draft data contract for Section A, and
this log. Separate the brief's requirements from its recommendations. Initialize Git and keep
existing files.
**What Claude did:** Read the 8-page brief. Initialized Git on `main`. Created the folders,
each with a `.gitkeep`. Wrote the README, `.gitignore`, `.env.example`,
`docs/sprint1_checklist.md` (items tagged REQ / SAMPLE / REC with page citations), and
`docs/data_contract.md` (draft v0.1).
**What we checked / changed:** *(team to fill in after review)*
**Outcome / lessons:** Claude flagged two things to confirm: instructor approval for
Greenhouse, and Section A's agreement to a shared corpus. The first was overstated and was
corrected in the review below.

### 2026-10-06 — Scaffolding review corrections (Sprint 1)
**Goal:** Fix problems the team found when reviewing the first scaffolding pass.
**Corrections requested and applied:**
1. `.env.example`: added an empty `ANTHROPIC_API_KEY=` placeholder (university-provided
   Anthropic API access) and `anthropic` as an `LLM_PROVIDER` option.
2. `data_contract.md`: `statement_id` is now `{run_id}:{posting_id}:{kind}:{n}`. The
   original format would let two extraction runs produce the same ID and overwrite each
   other's statements.
3. Database: SQLite/DuckDB are now described as local development options only. The shared
   engine and location are left pending Section A (D3), and the docs note that separate
   database copies are not shared automatically. `DATABASE_PATH` was renamed to
   `LOCAL_DATABASE_PATH`.
4. Caching: "never re-fetch" was replaced with "reuse cached snapshots by default; an
   explicit refresh saves a new timestamped snapshot".
5. Source permission: instructor confirmation is needed only if permission is uncertain.
   Greenhouse not appearing in the brief's example list does not by itself make approval
   mandatory.
6. Added a raw snapshot preservation and sharing scheme (contract §10, README): immutable
   timestamped folders, a tracked `data/raw_manifest.csv` with SHA-256 hashes, and archives
   uploaded to one shared location (to be agreed, D8).
**Lessons:** Check ID schemes for collisions across re-runs. Don't present a single local
file as a "shared" database. Keep the brief's wording ("if unsure, ask") instead of
strengthening it into a requirement.

### 2026-10-06 — Greenhouse snapshot fetcher (Sprint 1)
**Goal:** Implement the raw snapshot fetcher described in data contract §10. Test it with
mocked responses only. No real postings are fetched yet.
**Prompt (summary):** Create `config/boards.yaml` as an empty draft with a commented
example. Write `src/fetch_greenhouse.py` against `GET /v1/boards/{board_token}/jobs?content=true`
(public, no auth, no POST, no Anthropic calls). Requirements: config validation including
duplicate tokens; a clean exit on an empty list; validation that responses have a `jobs`
list; original bytes saved in timestamped snapshots; cache reuse verified by hash; `--refresh`
that never overwrites; timeouts, a delay between boards, and bounded retries; `Retry-After`
honoured within a retry budget; manifest fields from the contract; separate
fetched/cached/failed reporting; failed responses never cached; `--dry-run`; original
snapshot IDs kept on cache reuse. Add requirements files and a `.venv`, mocked tests for 10
listed scenarios, a fix to D1 wording, README commands, and this log entry.
**What Claude did:**
- `src/fetch_greenhouse.py`:
  - Uses `requests` and `PyYAML`, plus `python-dotenv` to read `HTTP_USER_AGENT` and
    `GREENHOUSE_BASE_URL` from `.env`. The base URL must be https.
  - Retries only on 429/5xx, timeouts and connection errors. The retry budget is cumulative
    per board. `Retry-After` accepts both seconds and HTTP-date values.
  - Writes files atomically and refuses to overwrite: it writes a temporary file, then uses
    `os.link`, which fails if the target already exists.
  - Appends to the manifest only after the file is saved. Exit codes are 0 / 1 / 2.
- `tests/test_fetch_greenhouse.py`: 42 tests using a fake session, a fake clock and a fake
  sleep, so nothing touches the network and nothing really waits. `pytest.ini` puts `src/`
  on the import path.
- `requirements.txt` (requests, PyYAML, python-dotenv) and `requirements-dev.txt` (+ pytest).
  Created `.venv` with Python 3.14.
- Updated D1 and the §10 note in the contract (v0.2.1), the README, and the checklist.
**Design choices to review:**
- An empty `jobs` list counts as a successful snapshot and is flagged "0 jobs". A board can
  legitimately have no openings.
- Board tokens are compared case-insensitively when checking for duplicates.
- If the newest cached file is corrupted, the fetcher falls back to the newest **valid**
  older snapshot for that board. It refetches only if none is valid. The corrupted file is
  left untouched.
- If the snapshot folder for the current second already exists, the run aborts before
  making any requests.
- Only successful responses go into the manifest, so `http_status` is always 200 there.
  Failures appear in the run summary only.
**What we checked / changed:** *(team to fill in after review)*
**Outcome / lessons:** 42/42 tests pass. A CLI dry run and a normal run against the empty
shipped config both print the "No boards configured" message and exit 0 without touching
the network.

### 2026-10-06 — Pilot employers and first real collection (Sprint 1)
**Goal:** Commit the fetcher, choose pilot employers with verified Greenhouse boards, and run
the first real collection. Labelled as a pilot; no cleaning, DB loading or extraction.
**Prompt (summary):** Review the diff and status, check that `.env`, `.venv` and raw data are
ignored, and commit as "Add Greenhouse snapshot fetcher and tests". Find 5 employers across
3 or more industries and verify their tokens on official careers pages, without guessing or
using documentation example companies. Populate `boards.yaml` as a pilot proposal. Run a dry
run, then the real fetch. Inspect the snapshots read-only. Update the checklist and this log,
and write `reports/sprint1_pilot_collection.md`. No push and no upload.
**What Claude did:**
- Confirmed the ignore rules with `git check-ignore`, then committed `dfc411d`.
- Downloaded the HTML of about 45 official careers pages with `curl` and grepped it for
  Greenhouse board, API or embed URLs. Kept only tokens that actually appear on the
  company's own page. JavaScript-rendered pages and pages that returned 403 (e.g. Airbnb,
  Stripe, Datadog) were skipped rather than guessed.
- Chose `duolingo`, `robinhood`, `recursionpharmaceuticals`, `oura` and `figma` (5
  industries), with `reddit` as a verified alternate. Verification URLs are recorded as YAML
  comments, because the config schema does not allow extra keys.
- The dry run planned 5 GETs to the expected URL pattern. The real run fetched 5 boards
  (470 postings) with 0 failures and no zero-job boards.
- The inspection script lives outside the repo and reads files only. Hashes and sizes match
  the manifest. Raw files were re-hashed after inspection and were unchanged.
**What we checked / changed:** *(team to fill in after review)*
**Outcome / lessons:**
- One bash loop reused a stale `page.html` after a failed request, which briefly looked like
  a false Greenhouse hit for Warby Parker. It was caught and fixed by deleting the file on
  each iteration. Lesson: clear temporary outputs in loops so a failure can't inherit the
  previous result.
- Greenhouse's `language` field is set by the employer. It is not a detected language.
- Recursion's board includes a placeholder "Don't see what you're looking for?" posting,
  which will need filtering.

### 2026-10-06 — Pilot text cleaning (Sprint 1)
**Goal:** Commit the pilot collection. Then turn snapshot `20261006T171338Z` into one
cleaned row per posting with audit flags. No DB loading and no extraction.
**Prompt (summary):** Commit as "Collect and validate Greenhouse pilot postings". Implement
`src/prepare_postings.py` with the 24 listed columns. Requirements: raw data left unchanged;
entity decoding and tag removal that keeps paragraph and bullet boundaries; stable IDs;
flags for missing/empty and placeholder postings, with flagged rows kept; exact duplicates
by normalized text, with repeated titles alone not counted as duplicates; source language
preserved without claiming detection; consistent list serialization. Write JSONL and CSV
plus a quality report, add focused tests, verify raw hashes, and report the results.
**What Claude did:**
- Committed `020c2eb`, confirming `.env`, `.venv` and raw files stay ignored.
- Inspected the raw `content` first. It is **double-encoded**: escaped markup with entities
  still inside after one unescape. The cleaner does one `html.unescape`, then a stdlib
  `HTMLParser` that decodes the rest. It turns block tags into paragraph breaks and `<li>`
  into `- ` bullets, indents nested lists, and drops iframe, script and style content.
- Reused `load_config`, `read_manifest` and `verify_cached_file` from the fetcher. The cleaner
  refuses to run if any raw file fails hash verification.
- Duplicate canonical order: config board order, then ascending job id. Empty text gets no
  hash, so empty rows are never duplicates of each other.
- 24 new tests (66 total, all passing).
**Corrections made during the session:**
- The title-only placeholder rules missed Recursion's "Interested in an internship?", whose
  text says "Join our Internship Talent Network!… we are currently not hiring interns". I
  measured candidate description rules against the pilot before adding any. "Not hiring"
  was rejected because it also matched a real Figma posting. I added two narrow phrases
  ("join our … talent network/community/pool", "resume on file") with tests for real
  descriptions that must not be flagged.
- Exact duplicates came out at 0, but a similarity check found 13 same-title groups at up
  to 0.998 similarity. A diff showed they differ only in location, salary or benefits lines.
  These are reported in an informational section and are **not** flagged, as the task
  required.
**What we checked / changed:** *(team to fill in after review)*
**Outcome / lessons:** 470 rows, 468 usable, 2 placeholders, 0 missing/empty, 0 exact
duplicates. Raw hashes were unchanged after every run. Lesson: inspect the real encoding,
and check the flag counts against the actual rows. Both corrections came from looking at
the output rather than trusting the green test run.

### 2026-10-06 — Contract alignment and company names (Sprint 1)
**Goal:** Make data contract §2 match the cleaner's real output. Keep both the standardized
and the source company names.
**What Claude did:**
- Added `source_company_name` (the API value) next to `company_name` (from config). Also
  added a per-row `cleaning_version` (`0.1.0`) so the planned loader can record
  cleaning provenance without guessing. The quality report gained a "Company names" table.
  Two boards differ: Recursion ("Recursion" vs "Recursion Pharmaceuticals") and Oura (the
  API says "Ōura").
- Contract bumped to v0.3. §2 now lists all 26 output columns, with the new fields marked
  as proposals. Stored rows are keyed by (`snapshot_id`, `posting_id`), and `statements`
  gained `snapshot_id`. `source_language` replaces the detected `language`. `seniority` and
  `detected_language` are now "planned".
- Reprocessed the pilot: 470 rows, 468 usable, same as before. Raw hashes unchanged. 68 tests pass.
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-06 — Local SQLite loading (Sprint 1)
**Goal:** Load the processed pilot into a **local development** SQLite database. This does
not choose the shared DB. No API calls.
**Prompt (summary):** Commit the cleaning work as "Clean and validate pilot job postings".
Implement `src/load_postings.py` with a versioned schema and tests. Requirements: explicit
input and DB paths; all 470 rows stored, flagged rows included; every field preserved;
primary key (`snapshot_id`, `posting_id`); a `usable_postings` view; foreign keys on;
validation followed by a single transaction; idempotent re-runs; conflicting content
rejected; snapshot and cleaning-version provenance; no deletes and no taxonomy tables.
Verify the counts against the JSONL.
**What Claude did:**
- Committed `3735716`.
- `sql/schema_v1.sql`:
  - STRICT tables `schema_meta`, `snapshots`, `loads` and `postings`, plus the
    `usable_postings` view.
  - CHECK constraints: posting_id format, valid JSON arrays, 0/1 booleans.
  - A composite deferred FK from `is_duplicate_of` to the same snapshot.
- `src/load_postings.py`:
  - Validates the whole file first: exact field set, types, ID consistency, a single
    snapshot and cleaning version, flag consistency, and duplicate targets present.
  - Loads inside `BEGIN IMMEDIATE`/`COMMIT`, with `ROLLBACK` on any error.
  - Compares every field of rows that already exist and raises `ConflictError` on any
    difference.
  - `loads` is unique on (snapshot, cleaning version, input SHA-256), so an identical
    re-run adds nothing.
- 28 loader tests (96 in total, all passing):
  - repeat load is a no-op; a superset input adds only the new rows
  - conflicting content is rejected and the DB is left unchanged
  - a different cleaning version for the same snapshot conflicts
  - the same posting in two snapshots keeps both texts
  - a DB error mid-insert (forced CHECK violation) rolls back to empty tables
  - invalid JSONL loads nothing
  - foreign keys are enforced, both immediate and deferred
  - field and file validation, CLI exit codes
- Loaded the pilot: 470 inserted. A second run reported "already loaded", inserted 0 and
  left 470 unchanged. A read-only verification script compared total, usable, flag and
  per-company counts, plus every field of every row: all matched. `integrity_check` is ok,
  there are 0 FK violations, and the raw hashes are unchanged.
**Design points to review:**
- Re-cleaning an already-loaded snapshot with a new `cleaning_version` is rejected as a
  conflict. That is safe, but it means a new DB or a schema change is needed later.
- A rebuilt DB is equivalent, not byte-identical, because the load timestamps differ.
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-06 — Pilot exploratory analysis (Sprint 1)
**Goal:** Commit the loader, then explore the pilot. Requirements: a read-only DB with every
query filtered to the snapshot; rule-based seniority; local language detection;
near-duplicate candidates; charts and a findings report. No skill extraction.
**Prompt (summary):** Commit as "Add local SQLite posting loader". Build
`notebooks/sprint1_exploration.ipynb` with counts, employer concentration, departments and
locations, word counts, missing fields, exact duplicates vs repeated titles, and
placeholders, using clear all-row and usable-row denominators. Seniority rules go in config,
with derived results stored separately. Language detection must be local (no LLM or API) and
must record the detector version and uncertain rows. Near-duplicate candidate pairs: all
pairs within same-board groups, labelled as candidates. Write
`reports/sprint1_exploration.md`, install the dependencies, execute the notebook, and verify
that nothing changed.
**What Claude did:**
- Committed `9a3d16e`.
- Looked at real titles before writing any rules. That surfaced several traps: "Account
  Executive" (sales), "Executive Assistant, Chief …", "Creative/Art Director" (role names),
  IC "Product/Program Manager", and "Senior/Software Engineer II" (a level range). These
  were encoded in `config/seniority_rules.yaml` as ordered rules with excludes. Labels
  include `unknown` and `ambiguous`, and `other_matches` is kept for review.
- `src/derive_features.py` opens SQLite with `mode=ro` and writes seniority and language
  CSVs to `data/processed/derived/` and candidate pairs to `reports/`. 43 tests were added
  (139 in total, all passing).
- Language: chose `lingua-language-detector` 2.2.0, which is offline, about 0.4 s and
  190 MB for the pilot.
- Charts: loaded the dataviz guidance first. All charts are single-series, one hue, with
  thin horizontal bars, ink labels and hairline grids. I rendered and viewed every PNG.
- The notebook hashes the DB and raw files before and after, and asserts they are equal. It
  executed 18/18 cells with no errors.
**Corrections made during the session:**
- **Language detector:** a test showed lingua's whole-text label can follow the
  *minority* language with confidence 1.0 (6 English paragraphs + 1 French → "fr"). The
  detection was redesigned: the label is now the paragraph word-majority, the whole-text
  result is stored separately, and any disagreement or other-language paragraph marks the
  row uncertain.
- **Test fix:** one test of mine expected a candidate pair between two rows that share
  neither a title nor an internal ID. The code was right and the test was wrong, so I
  rewrote the test to exercise a real title-based pair.
- **Chart layout:** viewing the rendered charts showed the footnote colliding with the
  x-axis ticks and overlapping dots on the similarity chart. Both were fixed and checked
  again.
**Manual inspection:** a 20-title seniority sample plus all 34 multi-match titles; a 12-row
language sample; and all 43 postings located in non-English markets. The only non-ASCII
letter among those 43 is the "ã" in "São Paulo".
**What we checked / changed:** *(team to fill in after review)*
**Outcome / lessons:** No LLM tokens used. Key findings: 68% of usable rows come from two
employers; 34% of titles are seniority `unknown`; all postings are English; there are 0 exact
duplicates but 9 candidate pairs at ≥ 0.99 similarity (location variants); and Duolingo has
one requisition posted under two titles. Lesson: render and look at the charts, and treat a
detector's confidence score as a claim to test rather than a fact.

## LLM token usage (pipeline)

| Sprint | Provider / model | Tokens in | Tokens out | Notes |
|---|---|---|---|---|
| 1 | — | 0 | 0 | No LLM used in the pipeline yet |
