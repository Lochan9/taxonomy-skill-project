# Skill Taxonomy from Public Job Postings — Section B

Capstone project: *Taxonomy of Work*. Section B builds a **skill taxonomy** (a hierarchy of
capabilities derived from posting requirements) and evaluates it against **ESCO** and
**Lightcast Open Skills**. Section A builds the parallel task taxonomy; the two are joined in
Sprint 5 through a shared data contract (`docs/data_contract.md`).

Job postings come from the **Greenhouse Job Board API** (public, read-only endpoints at
`boards-api.greenhouse.io`). See "Data source" below for the open questions.

**Current status:** Sprint 1 (Data Acquisition & Exploration). The snapshot fetcher is
implemented and tested with mocked responses. No real postings have been fetched yet, and no
extraction exists. See `docs/sprint1_checklist.md`.

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
src/               Pipeline source code (fetch_greenhouse.py)
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
python -m pip install -r requirements-dev.txt   # runtime deps + pytest
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

## Data source

- **Postings:** Greenhouse Job Board API, e.g.
  `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`.
  The list of company board tokens is in `config/boards.yaml` (empty draft, pending Section A).
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
are pending agreement with Section A.

## Documentation

| File | Purpose |
|---|---|
| `docs/master_project_description.pdf` | Course brief (source of truth) |
| `docs/sprint1_checklist.md` | Sprint 1 requirements vs. recommendations |
| `docs/data_contract.md` | Draft shared schema for agreement with Section A |
| `docs/claude_usage_log.md` | Log of Claude Code prompts and outcomes (graded) |
