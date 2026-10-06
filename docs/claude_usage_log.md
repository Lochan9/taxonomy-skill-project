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

## LLM token usage (pipeline)

| Sprint | Provider / model | Tokens in | Tokens out | Notes |
|---|---|---|---|---|
| 1 | — | 0 | 0 | No LLM used in the pipeline yet |
