# Sprint 1 Checklist: Data Acquisition & Exploration (Weeks 1–2)

Source: `docs/master_project_description.pdf` (page numbers cited as *p.N*).

Items are sorted into three groups by how firmly the brief states them:

- **[REQ] Required.** The brief uses "must", "not permitted", "never", or lists the item in
  the Deliverables Summary.
- **[SAMPLE] Sample task.** Listed under Sprint 1 "Sample Tasks / Sample Deliverable". The
  brief says instructors will assign the actual tasks (*p.2*), so treat these as the expected
  baseline until the instructor confirms.
- **[REC] Recommendation.** "Best practices" or "practices" from the brief, or a suggestion
  from our team (marked *team*). Not mandated.

---

## 1. Project-wide requirements that apply from Sprint 1

- [ ] **[REQ]** Use public data only: published datasets and official APIs (*p.5*).
- [ ] **[REQ]** No scraping of LinkedIn, Glassdoor, or any site whose terms prohibit it (*p.5*).
- [ ] **[REQ]** Do not collect individual profiles or any personal data (*p.5*).
- [ ] **[REQ]** If unsure whether a source is allowed, ask the instructor before collecting (*p.5*).
      → Kaggle, Adzuna and USAJobs are given only as examples (*p.3, p.5*). Greenhouse's
      absence from that list does not by itself make approval mandatory, because the Job Board
      API is an official public API. Ask the instructor **only if** the team is uncertain
      whether it meets the "published datasets and official APIs" rule, e.g. about its terms
      of use.
- [ ] **[REQ]** Never commit API keys; use environment variables (*p.7*).
      → Done in scaffolding: `.env` is git-ignored and `.env.example` holds placeholders.
- [ ] **[REQ]** If an LLM is used, it must be a free-tier or student-credit provider. Amazon
      Bedrock is not available (*p.7*). The team also has university-provided Anthropic API
      access (`ANTHROPIC_API_KEY`), which we treat as student-credit access.
- [ ] **[REQ]** All code is the team's own work, written with Claude Code assistance (*p.7*).
- [ ] **[REQ]** Document Claude Code interactions and LLM prompts in sprint reports (*p.7*).
      → Use `docs/claude_usage_log.md`.
- [ ] **[REQ]** End of sprint: working code plus a brief report that includes LLM token usage
      (*p.7, Deliverables Summary*). Report zero if no LLM was used.

## 2. Data contract (shared with Section A)

- [ ] **[REQ]** Agree a shared schema with Section A **in Sprint 1** (*p.5: "Both groups must
      agree"*).
- [ ] **[REQ]** The schema covers at least these entities (*p.5–6*):
  - [ ] Postings: stable identifier, source, raw text
  - [ ] Statements: one row per task/skill statement, linked to its posting, with `kind` (task | skill)
  - [ ] Topics: leaf topics with name, description, size, and a cross-group comparable representation
  - [ ] Topic membership: statement → topic, with optional strength score
  - [ ] Hierarchy: parent–child relations supporting more than two levels
  - [ ] Task–skill map: task topic ↔ skill topic links with score and evidence
- [ ] **[REQ]** Both sections work from the **same corpus** (*p.2*).
      → **Action: get Section A to agree on Greenhouse as the shared source and on the board list.**
- [ ] **[REC]** Coordinate with Section A early (*p.7*).
- Draft: `docs/data_contract.md`.

## 3. Sprint 1 sample tasks (*p.3*)

- [ ] **[SAMPLE]** Set up the Claude Code environment and a shared repository.
  - [x] Local Git repo initialized with project structure
  - [ ] Create the shared remote (e.g. GitHub) and add teammates
- [ ] **[SAMPLE]** Collect a corpus of job postings from approved public sources.
  - [ ] Agree the final list of Greenhouse board tokens with Section A. **Pending.**
    - [x] Pilot proposal: 5 boards in 5 industries (Duolingo, Robinhood, Recursion, Oura,
          Figma). Tokens were verified on official careers pages and are listed in
          `config/boards.yaml`.
  - [x] Write a fetcher that saves untouched JSON responses to timestamped snapshots in
        `data/raw/` (see data contract §10): `src/fetch_greenhouse.py`, tested with mocks
  - [x] Pilot fetch: snapshot `20261006T171338Z`, 470 postings, 0 failures. See
        `reports/sprint1_pilot_collection.md`. This is a **pilot only**, not the shared corpus.
  - [x] Record each snapshot in `data/raw_manifest.csv` (pilot: 5 rows, hashes verified)
  - [ ] Archive snapshots to the agreed shared location (D8, pending)
  - [ ] Collect the agreed (non-pilot) corpus and name the canonical snapshot in the contract
- [ ] **[SAMPLE]** Load the postings into a **shared database**.
  - [ ] Agree the shared database engine and location with Section A (data contract D3).
        **Pending.**
  - [x] Local development SQLite loader: `src/load_postings.py` + `sql/schema_v1.sql`. The
        pilot is loaded into `data/processed/taxonomy_pilot.sqlite`: 470 rows (468 usable,
        2 flagged), and all counts and field values match the JSONL. This is **not** the
        shared database.
  - [ ] Until then, use SQLite/DuckDB for local development only. Every local copy is a
        separate file and is not shared automatically.
- [ ] **[SAMPLE]** Load O*NET and ESCO reference tables next to the postings.
  - [ ] ESCO skills plus skill hierarchy/relations (Section B's reference standard)
  - [ ] O*NET skills and occupation–skill links (needed for the Sprint 5 join)
  - [ ] **[REC]** Lightcast Open Skills as well. The brief names it as a Section B reference
        (*p.2, p.5*), but Sprint 1 only lists O*NET and ESCO.
- [ ] **[SAMPLE]** Generate summary statistics with Claude Code:
  - [ ] Postings by industry
  - [ ] Postings by seniority
  - [ ] Posting length distribution
  - [ ] Duplicate rate
  - [ ] Language mix
- [ ] **[SAMPLE]** Agree the shared schema with Section A (required anyway; see §2).

### Sample deliverable (*p.3*)
- [ ] Populated database
- [ ] Data exploration notebook (`notebooks/`) with documented findings
- [ ] Agreed data contract (**[REQ]**, see §2)

## 4. Greenhouse-specific points to resolve (*team*)

These come from the choice of source, not from the brief. Verify each one against real
responses during exploration.

- [ ] **[REC]** Greenhouse has no `industry` or `seniority` fields. Decide how to derive them
      (e.g. a manual industry label per board in `config/`, and seniority rules applied to titles)
      and document the method in the notebook.
- [x] **[REC]** `content` is HTML (entity-escaped). Keep the raw HTML and store a cleaned
      plain-text version alongside it. Done for the pilot in `src/prepare_postings.py`
      (`raw_text` + `clean_text`, with paragraph and bullet boundaries kept).
- [x] **[REC]** Posting ID scheme: `greenhouse:{board_token}:{job_id}`. Implemented. The
      scheme is still a proposal until the contract is agreed.
- [ ] **[REC]** Duplicates: check exact and near-duplicate text across boards and across
      repeated fetches. Record `fetched_at` so snapshots can be compared.
  - [x] Exact duplicates (normalized text) for the pilot: 0
  - [ ] Near-duplicates: 13 same-title groups differ only slightly (similarity up to 0.998;
        mostly location or salary variants). They are not flagged yet. Decide on handling
        before computing the duplicate rate and before extraction.
  - [ ] Across repeated fetches (only one snapshot so far)
- [x] **[REC]** Placeholder / talent-pool postings: flagged and kept for audit (pilot: 2,
      both Recursion). The rules are heuristic; review them on the full corpus.
- [ ] **[REC]** Language mix: detect the language per posting, then decide whether to filter
      to English or keep all languages. (`source_language` is employer-set, all `en` in the
      pilot. No detection has been done yet.)
- [ ] **[REC]** Rate limiting and caching: send polite requests (small delay, descriptive
      User-Agent). Reuse cached snapshots by default. Allow an explicit refresh that saves a
      **new** timestamped snapshot and never overwrites an existing one.
- [ ] **[REC]** Raw snapshots are git-ignored. Preserve and share them through the manifest
      and the archive process in data contract §10.
- [ ] **[REC]** Confirm that no applicant or personal data is stored. Only the public
      job-board endpoints are used, and the application-submission endpoints are never called.

## 5. Practice recommendations (*p.6–7*)

- [ ] **[REC]** Break big problems into smaller steps; test generated code before moving on.
- [ ] **[REC]** Keep a log of useful prompts (→ `docs/claude_usage_log.md`). Claude Code usage
      counts for 15 of the 100 rubric points (*p.6*).
- [ ] **[REC]** Be careful with the shared Claude Code account limits (*p.7*).
- [ ] **[REC]** If LLMs are used later: put them behind a provider-agnostic interface, cache
      responses to disk, use the smallest model that passes, and log tokens per sprint (*p.7*).

## 6. Out of scope for Sprint 1

Skill-statement extraction (Sprint 2), embeddings and clustering (Sprint 3), labeling and
hierarchy (Sprint 4).
