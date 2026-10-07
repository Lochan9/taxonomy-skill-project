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

### 2026-10-06 — ESCO reference acquisition (Sprint 1), blocked on download
**Goal:** Commit the exploration work. Then download the official ESCO English CSV
archive, preserve it with hashes, inspect the real headers, and build a transactional
loader and migration. No mapping and no extraction; O*NET is recorded as a shared
dependency.
**What Claude did:**
- Committed `f937435`.
- Researched the official source. The portal lists v1.2.1 to v1.0.3 and documents an
  emailed-link process. Inspecting the page form and the confirmation page showed an email
  input and no archive URL. I did not guess URLs, did not use a third-party copy (the Tabiya
  GitHub repo is a transformed v1.1.1), and did not submit any email address.
- Confirmed the licence on the official FAQ: Commission Decision 2011/833/EU, free reuse,
  and attribution required.
- Following the instruction to inspect the real headers first, I **did not** write the ESCO
  loader or migration. Instead I built `src/register_esco_archive.py`, which does not depend
  on the headers. It:
  - preserves the original archive
  - validates every zip member before writing (zip-slip, symlink and zip-bomb checks)
  - extracts without overwriting anything
  - records hashes in the tracked manifest
  - writes a report of the real CSV headers
  16 tests were added, using synthetic fixtures that are clearly marked as not ESCO
  (155 tests in total, all passing).
- Confirmed the pilot DB is unchanged: 470 / 468 / 2, integrity ok, 0 FK violations, and
  the DB and raw files are byte-identical.
- Wrote `reports/sprint1_esco_reference.md` with the blocker, the manual procedure and the
  planned loader requirements.
**Not done (and not estimated):** ESCO concept and relationship counts, missing labels,
unresolved endpoints and examples. They all need the real files.
**What we checked / changed:** *(team to fill in after review)*
**Next:** a team member downloads v1.2.1 (en, CSV, classification) and runs the
registration command. The ESCO loader is then designed from `reports/esco_headers_v1.2.1.md`.

### 2026-10-06 — ESCO v1.2.1 import from manually downloaded CSVs (Sprint 1)
**Goal:** Use the team's manually downloaded ESCO v1.2.1 English CSVs: find the folder,
inspect the real headers, record hashes and the acquisition date (without claiming an
archive hash), and import the skill reference tables transactionally. Postings and source
files must be preserved.
**What Claude did:**
- Located the folder by its name prefix and found that there was **no ZIP**. Read all 19
  headers and the official `dictionary_en.csv` before designing anything.
- Profiled the real data first:
  - 21 URIs are repeated in `skills_en.csv`, differing only in `modifiedDate`.
  - 188 ragged rows in `skillsHierarchy`.
  - 5 skills with an empty `skillType` (the DigComp areas).
  - Mixed `inScheme` separators.
  - 0 unresolved endpoints.
  - All 636 hierarchy-file links are already broader relations.
- Extended `register_esco_archive.py` with `--extracted-dir auto` (in-place, read-only)
  and renamed the manifest's date column to `acquired_on` + `acquisition_evidence`, so a
  filesystem-derived date can't pass for a stated download date. The manifest file did not
  exist yet, so nothing was migrated.
- Wrote `sql/migration_002_esco_reference.sql` and `src/load_esco.py`:
  - exact header checks and verification against the manifest hashes
  - strict endpoint and type validation, a cycle check, and the hierarchy cross-check
  - the duplicate-URI policy, with an audit table
  - the migration and import in one `BEGIN IMMEDIATE` transaction (DDL included)
  - idempotent re-runs and conflict rejection
- Imported: 14,579 concepts, 20,819 broader relations, 5,818 skill relations, with 0
  unresolved references. The repeat run was a no-op. Content fingerprints of the existing
  tables are unchanged, postings are 470 / 468 / 2, and integrity is ok with 0 FK
  violations. The ESCO and Greenhouse source files are byte-identical.
- 22 new tests (177 in total, all passing). Fixtures use the real header names with
  synthetic example.org rows.
**Corrections made during the session:**
- The first registration run crashed while writing the header report: the real
  `conceptSchemes.hasTopConcept` field is larger than Python csv's 131,072-character
  default. The manifest rows were already correct. I raised the limit, added a regression
  test and re-ran, and the re-run proved idempotent.
- One of my tests edited CSV *text lines*, but `altLabels` contain embedded newlines, so
  the edit landed on the wrong record. I fixed the test to edit parsed records.
**What we checked / changed:** *(team to fill in after review)*
**Open:** the original ZIP is not available; mapping and extraction are not started; the
shared DB is pending; O*NET is a shared dependency with no owner agreed.

### 2026-10-06 — ESCO commit, extraction-input policy, Team B summary (Sprint 1)
**Goal:** Verify and commit the ESCO work, then document the extraction input policy and a
Team B Sprint 1 summary. No extraction, no Team A work, no O*NET, no LLM calls.
**What Claude did:**
- Re-verified the repeated ESCO URIs against the source CSV and the DB. All 21 URIs appear
  exactly twice and differ **only** in `modifiedDate`. All 42 original rows are in
  `esco_source_duplicates` with matching row numbers and dates. Exactly one row per URI is
  kept (the latest), and its label and description match the source.
- Confirmed that `.env`, `.venv`, the DB, the raw files, the ESCO CSVs and the derived files
  are ignored, and that nothing sensitive is tracked.
- 177 tests passed. Committed `5f342cf` "Add ESCO reference import and validation".
- Ran a read-only survey of section headings and boilerplate before drafting the policy:
  - equal-opportunity text appears in 468 / 468 usable postings, benefits in 466 / 468
  - Figma's accommodations section appears in 159 / 159
  - Oura's fraud disclaimer appears in 80 / 80
- Wrote `docs/extraction_input_policy.md` (P1–P7, proposed and not implemented). It lists
  open questions (pay sections, recruiting notices, values sections, shared review of
  near-duplicates) rather than deciding them.
- Wrote `reports/sprint1_team_b_summary.md`, and added a status overview to the checklist
  that separates completed local work from unresolved shared deliverables.
**Accuracy note:** my first summary draft said the Greenhouse API was the "only external
API". I corrected it to also mention the careers-page and ESCO documentation fetches made
during development.
**What we checked / changed:** *(team to fill in after review)*

## Sprint 2

### 2026-10-06 — Annotation preparation (Sprint 2, Team B)
**Goal:** Commit the Sprint 1 docs. Then prepare human skill annotation: guidelines, a
reproducible 100-posting selection with a 20/80 split, a local annotation workflow and
validation. No LLM, no extraction, no ESCO mapping, no Team A work.
**What Claude did:**
- Committed `72b703d`, with the policy still marked proposed.
- Re-read the brief. Its Sprint 2 task is "Hand-label 100 postings to measure extraction
  precision/recall", so the 20/80 split is marked **proposed**, and P/R on all 100 stays
  possible.
- Inspected the strata fields before designing the selection: employer, title-based
  seniority, employer-specific departments, `internal_job_id`, location, word count, and
  the Sprint 1 candidate pairs. Found 411 related-posting groups (38 multi-member). The new
  base-title rule also catches Figma's location-suffixed variants that the Sprint 1
  detector missed. All 30 candidate pairs fall inside groups.
- `src/select_annotation_set.py`:
  - one seeded representative per group
  - balanced employer quotas
  - seniority minimums and a department-variety preference
  - a largest-remainder 20/80 split
  - a frozen manifest with `clean_text` SHA-256, plus `--check` and overwrite protection
- `src/annotations.py`:
  - exports byte-identical texts (git-ignored) and empty templates
  - per-annotator folders, and a `locate` offset helper
  - a validator with file, line and field errors, and an offset hint
  - zero-skill vs unfinished status
  - `compare` for adjudication
- `docs/skill_annotation_guidelines.md` v0.1:
  - examples are taken only from postings outside the selection *and its groups*, so the
    guidelines don't leak evaluation postings
  - all 28 example offsets were computed, round-trip checked, and checked against their
    section headings
- 27 new tests (204 in total).
**Checks:** the DB SHA-256 is unchanged after selection, export and validation; the raw
files are unchanged; the 100 exported texts match the manifest hashes.
**What we checked / changed:** *(team to fill in after review)*
**Not done:** no annotations; the split is not approved; no extraction.

### 2026-10-06 — Guideline corrections: alternatives and skills inside duties (Sprint 2)
**Goal:** Correct two issues the team found in review:
1. "Go or Python" split into two records read as *both* required.
2. The guidelines excluded duties wholesale, which would miss skills stated in
   responsibilities.

**Corrections requested and applied:**
1. **Alternatives:**
   - Added an optional `alternative_group_id` to `skills.csv`, after
     `required_or_preferred`, and regenerated the empty template.
   - Validation: a group needs at least 2 records, a valid id format, one posting only, one
     shared `required_or_preferred`, and no repeated skill.
   - `compare` now counts alternative-grouping disagreements, and the validation summary
     counts groups.
   - Guidelines §3b explains that skills joined by "and" are never grouped. Examples: Go/Python,
     Kafka/"similar data streaming technologies", C++/Go, NX/Solidworks (with 3D CAD outside
     the group), and AWS "(or similar cloud platforms)" as a borderline case.
   - Data contract §12 (v0.5.1) documents the field and proposes it for extractor output too.
2. **Skills within duties:**
   - Replaced the "Duty / task" exclusion with "Task-only statement".
   - Added §3a: annotate abilities, methods, tools and knowledge that a duty explicitly
     expresses; don't annotate the task or infer implied skills.
   - New pilot examples, all from postings outside the frozen set and its groups:
     - positive: *revenue forecasting* and *Salesforce* (Figma SMB AE), *Kotlin*
       (Duolingo Android)
     - negative: Oura's "Build a lot of prototypes…" and "Drive product development…",
       Figma's "Manage a 360 deal cycle…"
     - borderline: "outbound prospect"
   - It also shows how a duty mention and a requirements mention of the same skill collapse
     into one `required` record.

**Unchanged:** the frozen manifest (`--check` OK); evidence offsets and
`required_or_preferred`; no labels filled in. All new example offsets were round-trip
checked against `clean_text`. 8 new tests (212 in total, all passing).
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-06 — Guideline corrections: actions as skills, illustrative lists (Sprint 2)
**Goal:** Fix two remaining guideline issues found in review:
1. The guidelines required a skill noun, so "Build prototypes" was a negative example
   even though it states *prototyping*.
2. "languages such as C++ or Go" was treated as an alternative set, although it is an
   illustrative list.

**Corrections requested and applied (guidelines v0.2.1):**
1. **Explicit actions:**
   - §1, §3a and §6 now allow a faithful normalisation of an ability stated as a verb
     phrase. §3a gives a four-point test (same concept, same breadth, only qualifiers
     dropped, reproducible) plus inference counter-examples ("supplier management",
     "negotiation").
   - Re-reviewed every duty example. Added *prototyping* (one `required` record at
     Oura's "Prototyping" requirement), *mentoring* (Duolingo Android, `preferred`),
     *Android application development* and *mechanical design*. Moved "Manage a 360 deal
     cycle" and "Drive product development…" from negative to borderline. The §2 task-only
     examples are now "Own sales activity" and "Work to develop and circulate best
     practices…".
   - §7: the strongest mention (required > preferred > unspecified) sets both the value
     and the evidence location.
2. **Alternatives vs illustrative lists:**
   - §3b separates alternative requirements ("X or Y", "X or similar Y") from illustrative
     lists ("such as", "like", "e.g.", "including"). Default for the latter: record the
     category if it is a skill, record each named example ungrouped, and add
     `DISCUSS: illustrative list`.
   - Applied to the examples: Figma C++/Go (no longer `alt-1`), Figma ML libraries
     (PyTorch, TensorFlow, …), and Robinhood "technologies like Postgres, …, and AWS".
   - New borderline cases for calibration: "3D CAD (NX or Solidworks)", "mentoring or
     leading others", "search relevance, ranking, NLP, or RAG systems", "set technical
     direction", "Kotlin on Android", "build a strong pipeline", "break them, and iterate
     quickly".
- Version references in `docs/sprint2_checklist.md` and the preparation report updated.

**Tests:** 3 new tests (215 in total, all passing). Two synthetic tests show that a
normalised statement and ungrouped illustrative examples both validate. One test checks
all 62 offsets quoted in §9 against the local pilot `clean_text`, checks that each is quoted
in the guidelines, and checks that no example posting is in the selection or its groups. It
is skipped when the local DB is absent. This test found a straight apostrophe in the quoted
"A Bachelor’s degree…" negative example; it is now curly, as in `clean_text`.
**Unchanged:** the frozen manifest (`--check` OK, SHA-256 unchanged), the DB, the
validator code and templates. No labels filled in.
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-06 — AI-assisted annotation drafts (`ai_draft` workspace, Sprint 2)
**Goal:** Prepare *draft* skill records for the 20 development postings, so that human
annotators have something to review. These are not gold labels.

**Provenance:**
- **Suggestions:** the team supplied skill suggestions per posting, made with ChatGPT
  outside this repo. Each had a proposed status (R/P/U, or I for "illustrative").
  Claude Code made no LLM API call. ChatGPT token use was not recorded here.
- **What Claude Code did:**
  - matched each description to a frozen development posting by its actual text
  - checked every suggestion against the unchanged `clean_text`
  - located the evidence, computed the zero-based, end-exclusive offsets, and rechecked
    the requirement value against the posting's own wording
  - accepted, merged, rejected or flagged each suggestion under guidelines v0.2.1, and
    added records the guidelines call for (illustrative-list categories, partners of
    true "X or Y" alternatives)
- **Labelling of the output:**
  - workspace `data/annotation/sprint2_v1/annotators/ai_draft/`, created with
    `annotations.py init`; `annotator_id = ai_draft`
  - every skill row's `review_notes` starts with `AI-DRAFT: ChatGPT-assisted suggestion;
    evidence/offsets checked by Claude Code; NOT human-reviewed, NOT gold`
  - `AI_DRAFT_README.md` in the workspace lists every merge, rejection, added record and
    unresolved item, per posting
- **Status:** all 20 development postings are `in_progress`, meaning unfinished draft
  work, not approval. No posting is `reviewed`, and `annotator_id`/`reviewed_at` are
  empty on the review rows. The 80 evaluation postings are `not_started` and untouched.

**Corrections requested and applied:**
1. The 19 postings first stayed `not_started`, as requested. That made `validate` report
   one problem per row. All 20 are now `in_progress`.
2. The Senior AI Researcher posting (`recursionpharmaceuticals:8188707`) was added later,
   with 7 suggestions. The ML/NLP/computer-vision rows from "PhD in ML, NLP, computer
   vision, or the equivalent practical experience" were first drafted as an alternative
   group. They were then **removed**, as an academic qualification (§2); the issue stays
   in the posting note and the unresolved list.
3. **Atomicity review of merges:** related concepts are not automatically duplicates.
   - Re-split into separate records:
     - AI / LLMs and motion / animation (Duolingo design)
     - prototyping / high-fidelity prototyping
     - identifying / assessing trends
     - AI-assisted writing / debugging / optimising code, plus the tool-category record
     - brand / full-funnel growth metrics
     - cross-functional / end-to-end product delivery
     - distributed-system design / reliability / scalability / performance
     - the three data-stack problem areas
     - product reporting / dashboards
     - audit reporting / audit report writing
   - Kept merged, because they name one ability: "influencing executives and boards" (two
     audiences), and deploying ML algorithms = getting ML models into production.
4. **Software engineering** (Robinhood EM) was restored as a required record. The "5+
   years" requirement is excluded, not the named skill. The record carries a `DISCUSS:`
   note, because guidelines §2 still defaults to no record for "software development"
   tenure phrases.
5. **Alternative-group ids:** `validate` requires an id to be unique across the whole
   `skills.csv`; reusing `alt-1` in two postings fails. The drafts use `p05-alt-1` and so
   on. Guidelines v0.2.2 (§3b, §10) and data contract v0.5.2 (§12) now state this rule;
   before, they said "unique within the posting".

**Result:** 437 draft rows for 20 postings, with 8 alternative groups and 156 rows marked
`DISCUSS:`. The 431 suggestions break down into 1 rejected, 2 merges and 9 added records.
`validate` passes with no problems. The SHA-256 of the manifest, templates, DB,
`annotator-a` and `annotator-b` is unchanged.

**Open:** guidelines §0 says "No LLM fills in, suggests or pre-labels gold annotations".
The team should state whether separate, clearly labelled AI drafts are allowed, and how
reviewers may use them (e.g. not before their own independent pass).
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-06 — AI-revised annotation candidates (`ai_revised` workspace, Sprint 2)
**Goal:** Apply an AI review of the drafts in a separate candidate workspace. The drafts
and the human folders stay as they are.

**Provenance:**
- **Review input:** the drafts were exported as `reports/development_annotation_review.json`
  and reviewed in ChatGPT. That produced `reports/development_annotation_review_report.md`,
  which gives each of the 437 rows a decision (Keep 283, Revise 75, Discuss 79) and
  proposes 49 potential missing skills. The report's human sign-off section is still
  *pending*.
- **What Claude Code did:**
  - read the report as review input, not as approval
  - created `annotators/ai_revised/` with `annotations.py init`
  - applied the concrete Revise recommendations, rechecking each against the unchanged
    `clean_text` and recomputing the offsets
  - checked the 49 additions for support (all report offsets match `clean_text`) and
    for duplicates and overlaps
  - made no LLM API call
- **Labelling of the output:**
  - carried rows: `AI-REVISED: from ai_draft-NNNN …` plus the report decision
  - additions: `AI-SUGGESTED ADDITION: …` plus `DISCUSS:`
  - `annotator_id = ai_revised`; draft annotation ids are kept for traceability
  - `AI_REVISED_README.md` lists every change, addition and open item
- **Status:** all 20 development postings are `in_progress`. None is `reviewed` or gold,
  and approval of the report alone does not change that.

**Changes (437 → 492 rows):**
- **74 of 75 Revise rows applied:**
  - evidence widened to the full clause for isolated words (e.g. `verbal`, `building`,
    `market`, `training`); the span for "decision-making mechanisms" now crosses the
    source's bullet break
  - 7 renames (e.g. *colour* → *colour use in visual design*; *product dashboards* →
    *setting product-dashboard standards*)
  - 4 splits into 10 records: typological/pedagogical differences; four
    application-domain testing areas; feature decomposition/timeline planning; LLM
    knowledge/implementation patterns
  - 1 value change: *marketing strategy* U → R, at "strategist and operator", with a
    `DISCUSS:` note that the wording is generic
- **1 not applied:** ai_draft-0329 asks to narrow the evidence to "build commercial
  models", but that is not a contiguous span in the text.
- **49 flagged additions:** no exact duplicates. 25 have notes on overlaps or policy
  questions (illustrative examples, traits, conflicts with earlier unresolved items).
- **Unchanged:** the 283 Keep rows (except notes) and the 79 Discuss rows, which stay
  unresolved; the 8 alternative groups.

**Checks:** `validate` passes for `ai_revised` (492 rows) and for `ai_draft` (437). The
SHA-256 of `ai_draft`, `annotator-a`, `annotator-b`, the manifest, the templates and the
DB is unchanged. The evaluation rows are identical to the template.
**Not adopted:** the report's proposed `mention_relation=illustrative` convention
(decision 1) goes beyond guidelines v0.2.2 and needs a team decision.
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-06 — Skill extractor implemented, no real calls (Sprint 2)
**Goal:** Implement Team B's LLM skill extractor and test it fully offline before any real
run.

**Read first:** the master brief (Sprint 2 p.3, LLM practices p.7), data contract (§1 IDs,
§3 `statements`, §8 `runs`, §12 offsets), guidelines v0.2.2 and the extraction input policy.
SDK usage was checked against the bundled Claude API reference and the live
structured-outputs documentation (`output_config.format` with a JSON schema, closed
objects, no min/max constraints, `refusal`/`max_tokens` void the schema). The SDK is
`anthropic` 1.11.0.

**Built:**
- **Prompt and schema:** `config/prompts/skill_extraction_v1.md` and
  `config/schemas/skill_extraction_output_v1.json`, both versioned.
  - The prompt follows guidelines v0.2.2: atomic skills only; explicit actions faithfully
    normalised; no inference; qualifications, durations, settings and boilerplate excluded;
    strongest mention wins.
  - Each record gives the evidence copied exactly, plus its context sentence.
  - Requirement status is judged by the posting's own heading or wording.
  - `mention_relation` (`direct` | `illustrative_example` | `category`) and `example_of`
    keep examples apart from true alternatives.
- **Config:** `config/extraction.yaml`, with `model: null` on purpose; the model must be
  given with `--model` or `EXTRACTION_MODEL`.
- **Extractor:** `src/extract_skills.py`. It calls the official Anthropic SDK behind a small
  `Backend` interface (brief p.7) and owns its own retries (SDK `max_retries=0`). It also
  has:
  - **Scope guard:** `ALLOWED_SPLITS = {development}`, and each `clean_text` is checked
    against the manifest SHA-256.
  - **Validation:** a local schema check; evidence must occur exactly in `clean_text`;
    offsets are computed locally; repeated evidence is resolved by context or rejected as
    ambiguous; unsupported or duplicate records are rejected individually; invalid
    alternative groups are dropped with a warning.
  - **Results:** `ok`, `zero_skills` (valid and empty), `all_rejected` or `failed`.
  - **Caching:** keyed by the text hash, model, prompt and schema versions and file hashes,
    and request settings. Every response is archived, and invalid cached responses are
    called again.
  - **Retries and pacing:** bounded, with exponential backoff and `retry-after`, plus
    client-side pacing.
  - **Resumability:** `--resume` keeps completed postings and retries the rest.
  - **Provenance and tokens:** `run.json` records the git commit, config, SDK version,
    counts, failures and the token usage billed this run.
  - **`--dry-run`:** no network, no key, nothing written.
- **Tests:** 28 tests in `tests/test_extract_skills.py` (243 in total, all passing). They use
  real SDK types, a fake client and the real SDK over an `httpx2.MockTransport`, and cover:
  success, invalid JSON, schema violations, truncation, refusal, unsupported evidence,
  repeated evidence, zero skills, rate limits (`retry-after`), bounded failures, cache
  reuse and keying, resume, the development-only guard, dry run, and no key in outputs.
- **Docs:**
  - `.gitignore`: added `data/extraction/` and `reports/development_annotation_review.json`
    (which contains full posting texts).
  - `requirements.txt`: added `anthropic>=1.11,<2`.
  - README and the Sprint 2 checklist updated.
  - Data contract v0.5.3 (§12) documents `mention_relation` as a proposal; `skills.csv` is
    unchanged.

**Not done:** no real API call, so no extraction results or token counts. No ESCO
mapping. No human labels or annotation files changed. Nothing committed.
**Open:**
- The brief (p.7) limits pipeline LLMs to free-tier or student-credit providers. Confirm
  that the university Anthropic account qualifies, and which model it can use.
- No refusal fallback is configured, because it is model-specific; a refusal is recorded
  as `failed`.
- The `statements` table load waits on D3.
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-06 — First extraction pilot prepared, not run (Sprint 2)
**Goal:** Prepare a three-posting pilot of `src/extract_skills.py` without extracting
anything.

**Done:**
- **Key check:** a yes/no check that prints no value. There is no `.env` file, so
  `ANTHROPIC_API_KEY` is absent, and so is `EXTRACTION_MODEL`.
- **Model discovery:** blocked, because there is no key. No model was guessed and no API
  call was made. A discovery-only script (official `models.list()`, prints no credentials)
  is ready to run once the key is entered locally.
- **Provider:** recorded in `config/extraction.yaml` as `provider_access: "university-provided
  Anthropic access"` with `brief_p7_compliance: unresolved`. Brief p.7 requires free-tier
  or student-credit providers, and no document shows this access qualifies. The extractor
  writes the config into every `run.json`.
- **Input choice:** documented as `input.text: full_clean_text`. The pilot sends the full
  unchanged `clean_text`, boilerplate included, because the boilerplate-stripped
  extraction input (policy P5–P7) is not built. This follows the policy's conservative
  default (P6) and keeps the offsets valid against `clean_text`.
- **Pilot postings,** resolved from the frozen manifest (all development split):
  - Senior Product Designer: `greenhouse:duolingo:8675713002`
  - Senior Software Engineer, Data Engineering: `greenhouse:robinhood:4738660`
  - Senior AI Researcher: `greenhouse:recursionpharmaceuticals:8188707`
- **Dry run** on those three: no network, nothing written, model not set.

**Not done:** no extraction, no model chosen; waiting for the user's choice after
discovery. Annotation files are unchanged, and no evaluation posting was accessed.
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-07 — First real extraction pilot: 3 development postings (Sprint 2)
**Goal:** Run a baseline of `src/extract_skills.py` on three development postings. The
model was the user's choice, `claude-sonnet-5-5`, picked from the account's
`models.list()` results.

**Setup:**
- **Key handling:** the API key was moved from the tracked `.env.example` into a new,
  git-ignored `.env` (mode 0600) without being displayed, and `.env.example` was restored
  to its committed version. The key was found nowhere in git: not staged, not in any
  commit, the reflog or the stashes.
- **Model discovery:** 13 models were visible to the account.
- **Provider:** `provider_access: "university-provided Anthropic access"`;
  `brief_p7_compliance: unresolved`.
- **Settings:** the existing prompt (`skill_extraction_v1`), schema and caching, with full
  `clean_text`. Reasoning settings were unchanged (no `thinking`/`effort` sent, so the
  model's default adaptive thinking applied).

**Run:** `skx-20261007T003601Z`. A dry run first showed 3 calls were needed.
- 3 of 3 postings `ok`; 0 failures, 0 retries.
- 35 statements accepted, 0 rejected. All 35 evidence spans match the DB `clean_text`.
  - Duolingo 8675713002: 12
  - Recursion 8188707: 7
  - Robinhood 4738660: 16
- Repeated evidence resolved by context: 2 ("drug discovery", 6 occurrences; "Spark", 3).
- **Tokens (actual, from `usage`):** input 5,686; cache writes 2,860; cache reads 5,720;
  output 7,860, of which 2,964 were thinking tokens.
- **Estimated cost** at official prices (Sonnet 5.5: $2 input, $2.50 5-min cache write,
  $0.20 cache read, $10 output per MTok): about **$0.098**.

**First observations (unreviewed):**
- Duolingo keeps both *prototyping* (U) and *high fidelity prototyping* (R), although the
  model's note says it consolidated them.
- Spark is `required` as an illustrative example. It is also named in duties; the "strongest
  mention" rule chose the required list.
- The Robinhood data-stack areas are recorded as illustrative examples of "data stack".

**Not done:** no evaluation postings; annotation labels unchanged; nothing committed.
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-07 — Local Team B dashboard (Sprint 2)
**Goal:** One local tool to explore the corpus, inspect saved extraction runs, and review the
development drafts. No clusters, hierarchy or ESCO mapping yet.

**Choice:** Python standard-library WSGI (`wsgiref`) with a static HTML/JS/CSS page. That
means no new dependency, a testable app object, and nothing loaded from outside the
machine.

**Built:** `src/dashboard.py` and `src/dashboard_static/` (`index.html`, `app.js`, `app.css`).
- **Corpus explorer:** all 470 postings from the read-only DB, with employer, seniority,
  exclusion and title filters. It reuses the Sprint 1 metrics JSON and its 5 figures.
- **Extraction results:** reads `data/extraction/runs/` and shows:
  - the model, run ID, provider access, brief p.7 status (unresolved), prompt and schema
    versions, and the recorded token usage
  - per-posting status, with empty states for postings without a result
  - evidence highlighted only where `clean_text[start:end] == source_span`
  - `requirement_status` and `mention_relation` badges, so illustrative examples stand
    apart from individual requirements
  - warnings and rejected records
  - the label "AI-generated, unreviewed"; nothing stored is changed
- **Annotation review:** loads `ai_revised` or `ai_draft`, separately from the API runs.
  - Actions: accept, edit, reject, reopen, add.
  - Evidence must be exact. Offsets are computed on the server, and a repeated phrase needs
    an explicit occurrence.
  - Decisions are appended per reviewer, with an ID and timestamp, the draft and text
    hashes, and the original row. Drafts are never written.
  - DISCUSS, illustrative and suggested-addition flags stay visible.
- **Held out:** the 80 evaluation postings plus 6 grouped variants (86 texts) are withheld
  everywhere. Review and extraction accept development postings only, and human folders
  are not loaded.
- **Safety:** binds to 127.0.0.1 and checks the Host header; POSTs must be same-origin JSON
  with a custom header; CSP `default-src 'self'`; every value is rendered as text. It never
  reads `.env` and makes no API calls.

**Tests:** 28 tests in `tests/test_dashboard.py` (271 in total, all passing). They cover:
- segments that reassemble the text, overlaps, and invalid or tampered offsets (flagged,
  not drawn or repaired)
- extraction labels and empty states
- persistence: append-only, per reviewer, the latest decision wins, reopen, editing and
  rejecting added records
- invalid evidence (case, spacing, whitespace, empty, repeated without occurrence, wrong
  client offset) and invalid fields
- held-out texts refused on every route
- byte-identical DB, drafts, manifest and run files after reads and writes
- Host and header checks, path traversal, and no credential code

**Checked live:** a smoke test on the real data covered every endpoint, 86 held-out texts
refused, and the pilot run highlighted with 0 invalid offsets. A localhost server check
returned the CSP header, refused a foreign Host (403) and a POST without the header (403),
and listened on 127.0.0.1 only. `app.js` passes a syntax check. The UI has not been
clicked through in a browser.
**Not done:** no review decisions recorded; nothing committed.
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-07 — Dashboard browser verification and UI fixes (Sprint 2)
**Goal:** Test all three dashboard views in a real browser, fix what breaks, and record the
results.

**Setup:**
- **Browser:** the Claude in Chrome extension was declined. Instead, Playwright 1.63 (in a
  scratch venv, not a project dependency) drove the installed Google Chrome headlessly.
- **Isolation:** the dashboard ran with a temporary `--reviews-dir` and the test reviewer
  `pwtest`. Sixteen source files were hashed before the run: the DB, manifest, templates,
  `ai_draft`, `ai_revised`, `annotator-a`/`-b` and the pilot run files.
- **Script:** `tests/browser/verify_dashboard.py` (not collected by pytest). Screenshots
  are in `reports/dashboard_screenshots/` (git-ignored).

**Issues found in the browser and fixed:**
1. **Double `Content-Length`.** Every response after `/favicon.ico` carried a second
   `Content-Length: 0`, and Chrome refused to load the page
   (`ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_LENGTH`).
   - Cause: a shared module-level header list was passed to `start_response`, and wsgiref
     appended to it.
   - Fix: the headers are now a tuple, copied into each response.
   - New test: a real `wsgiref` server must send exactly one `Content-Length`. The old
     behaviour was reproduced in a scratch copy, and it sends two.
2. **Favicon 404 in the console.** `/favicon.ico` now returns 204.
3. **Clipped corpus table.** The Seniority, Words and Status columns were cut off. The corpus
   view now uses a wider left column, and detail panels are sticky on desktop.
4. **27 px horizontal scroll at phone width.** The long run dropdown caused it; form
   controls now fit their container.
5. **Overflowing add/edit dialog.** The occurrence options, which include context text,
   pushed the inputs and Save button outside the dialog. Its controls are now 100% width.
6. **Lost server error.** For repeated evidence, the server's message was overwritten by
   the local hint; it now stays visible.
7. **Redundant buttons.** Accepted records no longer show Accept, and rejected records no
   longer show Reject.
8. **Uniform highlights.** Extraction highlights didn't separate illustrative examples or
   categories from individual requirements. They are now tinted by mention type, with a
   legend; overlaps keep their own tint.
9. **Crash from the legend.** The legend's sample marks broke click-to-focus. Focus now
   uses `mark[data-ids]`.
10. **Empty snapshot label.** It stayed "…" when the page opened on the review or extraction
    tab; those endpoints now return `snapshot_id`.

**Result:** **50/50 browser checks passed** on the final run (`exit 0`).
- Corpus: 470 rows; filters, search, internal scrolling; 5 figures loaded; a held-out
  notice instead of text.
- Extraction: run metadata and tokens (14,266 / 7,860); 3 ok and 17 empty states; 16
  Robinhood statements with 7 illustrative; validated, tinted highlights; click-to-focus.
- Review:
  - DISCUSS flags visible
  - accept, reject, reopen and edit
  - invalid evidence rejected with the server's message
  - "Duolingo" offered 11 occurrences, and saving without choosing one was refused
  - adding with a chosen occurrence, and adding from a text selection
  - after a refresh: reviewer ID, tab and all 7 decisions restored
  - `decisions.jsonl` written only in the temporary directory
- Held out: five read routes and one write route refused an evaluation posting and a
  grouped variant (403).
- Phone width (390 px): no horizontal page scroll.
- Console: no unexpected errors; only the 2 deliberate invalid-evidence requests logged
  a 400.

**Checks afterwards:** all 16 hashed source files unchanged; the real `reviews/` folder
absent; 272 unit tests passing (`tests/test_dashboard.py`: 29).
**What we checked / changed:** *(team to fill in after review)*

### 2026-10-07 — Browser annotation workflow: review, completion, export, evaluation mode (Sprint 2)
**Goal:** Make the dashboard's Annotation review page enough to finish annotation in the
browser, with no CSV editing or annotation commands, while keeping every draft, text and
the frozen selection intact.

**Before starting:** no saved review decisions existed (`reviews/` and `reviewed/` absent).
I hashed 18 source and workspace files: the DB, manifest, templates, `ai_draft`,
`ai_revised`, `annotator-a`/`-b` and the pilot run.

**Built:**
- **`src/review_workflow.py`:**
  - **Log and replay:** an append-only event log per reviewer, replayed into the current
    state.
  - **Actions:** accept, edit, reject/delete, reopen, add, split (parts linked with
    `split_from`), resolve discussion (reason required), complete posting, reopen posting.
  - **Evidence:** offsets computed on the server against the original `clean_text`, with an
    explicit occurrence for repeated text.
  - **Completion rules:**
    - nothing pending and no open discussion; a DISCUSS flag on a rejected or split record
      no longer blocks
    - no stale records, valid alternative groups, and alternative-group IDs unique across
      postings
    - two confirmations (full text read, missing skills checked), plus a deliberate
      zero-skill confirmation when there are no records
    - records the reviewer, time, text hash, draft hash and guidelines version
    - invalidated by any later change or by reopening the posting
  - **Integrity:**
    - `expected_version` per posting, so a stale tab gets a 409 conflict
    - `expected_source_sha`, so a changed draft file is refused, and records decided against
      an older draft row are flagged *stale*
    - a client request ID, so a repeated click returns the first decision
    - a file lock and fsync on append
    - `actor: human` on every event, and AI workspace names refused as reviewer IDs
  - **Export:**
    - the existing annotation CSV format, from the latest decisions (rejected records
      omitted; additions and split parts included)
    - provenance in each row's notes and in `provenance.jsonl`
    - validated with `annotations.validate`; an invalid export is refused
    - a new folder for every write under `reviewed/<reviewer>/<mode>-<timestamp>/`, never
      under `annotators/`
    - marked partial or complete, and never gold
  - **Evaluation mode:**
    - 80 evaluation postings, starting empty
    - never reads drafts (tested by making draft reads fail)
    - text only behind the `X-Dashboard-Mode: evaluation` header
- **`src/dashboard.py`:** new routes `/api/review` and `/api/review/posting` (mode-aware),
  `/api/locate`, `/api/export/preview`, `/api/export/download` and `POST /api/export`.
  `--reviewed-dir` sets the export location.
- **The page (`app.js`, `index.html`, `app.css`):**
  - mode switch and evaluation gate; persisted reviewer ID; draft-source selector; progress
  - previous/next buttons; text beside the cards; click-to-scroll evidence
  - filter chips with counts, and Details for provenance notes
  - edit, split and resolve dialogs, with an occurrence picker and "Use selected text"
  - completion panel, and an export dialog with preview, downloads and write
  - Saving/Saved/error states, a Reload button on conflicts, and a single request in flight
    at a time

**Tests:**
- `tests/test_review_workflow.py`: 31 new tests.
- `tests/test_dashboard.py`: rewritten for the new API, 14 tests.
- 288 in total, all passing.
- `tests/browser/verify_dashboard.py` was extended to 74 checks.

**Browser verification:** Playwright drove the system Chrome headlessly, against temporary
`--reviews-dir` and `--reviewed-dir` with reviewer `pwtest`. Final run: **74/74**.

Issues the browser found, all fixed:
1. `.review-grid { display: grid }` overrode the `hidden` attribute, so the grid showed
   before a reviewer was set. Fix: a global `[hidden] { display: none !important }`.
2. Split parts copied the original's AI notes, including DISCUSS, so every part became an
   open discussion. Parts now start with empty notes; provenance stays on the original.
3. `replaceChildren(null)` printed "nullnull" in the evaluation posting header. Fixed by
   filtering out the null children.
4. A rejected DISCUSS record still said "unresolved". It now says "set aside (rejected)".
5. A development-mode write to an evaluation posting returned 400 instead of 403. The scope
   check now runs first.
6. The mode toggle broke at phone width; it is now a stacked list.
7. Disabled buttons looked enabled; they are now dimmed.
8. The completion note mentioned a draft version in evaluation mode.

**Also:** an older dashboard process without temporary directories (`src/dashboard.py` with
no arguments) was holding port 8765. It was stopped so the new code could be tested. The test
had only set a reviewer ID against it, which writes nothing, and the real `reviews/` folder
was never created.

**Afterwards:** all 18 hashed files unchanged; the real `reviews/` and `reviewed/` folders
absent; the 20 screenshots are in `reports/dashboard_screenshots/` (git-ignored).

**Limitations:**
- One reviewer's log is assumed to be used by one person at a time, through this server
  (conflicts are detected, not merged).
- There is no adjudication view or inter-annotator comparison in the page; use
  `annotations.py compare` on exported folders.
- Whether `reviews/` and `reviewed/` are committed is not yet decided.
- The guidelines version is read from the guidelines file header.

**What we checked / changed:** *(team to fill in after review)*

## LLM token usage (pipeline)

| Sprint | Provider / model | Tokens in | Tokens out | Notes |
|---|---|---|---|---|
| 1 | — | 0 | 0 | No LLM used in the pipeline yet |
| 2 | anthropic / claude-sonnet-5-5 | 14,266 (5,686 uncached + 2,860 cache write + 5,720 cache read) | 7,860 (incl. 2,964 thinking) | Pilot run skx-20261007T003601Z, 3 development postings, ≈ $0.098 |
