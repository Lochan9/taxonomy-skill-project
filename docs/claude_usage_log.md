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

## LLM token usage (pipeline)

| Sprint | Provider / model | Tokens in | Tokens out | Notes |
|---|---|---|---|---|
| 1 | — | 0 | 0 | No LLM used in the pipeline yet |
