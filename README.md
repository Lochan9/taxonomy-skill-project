# Skill Taxonomy from Public Job Postings — Section B

Capstone project: *Taxonomy of Work*. Section B builds a **skill taxonomy** (a hierarchy of
capabilities derived from posting requirements) and evaluates it against **ESCO** and
**Lightcast Open Skills**. Section A builds the parallel task taxonomy; the two are joined in
Sprint 5 through a shared data contract (`docs/data_contract.md`).

Job postings come from the **Greenhouse Job Board API** (public, read-only endpoints at
`boards-api.greenhouse.io`). See "Data source" below for the open questions.

**Current status:** Sprint 1 (Data Acquisition & Exploration). Scaffolding only; no data has
been fetched and no extraction exists yet. See `docs/sprint1_checklist.md`.

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
src/               Pipeline source code
```

## Setup

Requires Python 3.11+ and Git.

```bash
git clone <repo-url> taxonomy-skill-project
cd taxonomy-skill-project

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
# pip install -r requirements.txt  # added once Sprint 1 code lands

cp .env.example .env               # then fill in your own keys locally
```

`.env` is git-ignored. **Never commit API keys** (a requirement of the project brief). The
Greenhouse Job Board GET endpoints need no key. Keys are only needed for an LLM provider if
the pipeline later uses one (e.g. `ANTHROPIC_API_KEY` for the university-provided Anthropic
access, or a free-tier provider).

## Data source

- **Postings:** Greenhouse Job Board API, e.g.
  `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`.
  The list of company board tokens will live in `config/` (not yet created).
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
