# Sprint 1 Summary: Team B (Section B, Skill Taxonomy)

**Date:** 2026-10-06 · **Sprint 1 status: in progress, NOT complete.** The local pipeline work
is done. The shared deliverables (agreed corpus, data contract, shared database) are still
open, as listed in §8.

## 1. What Team B built

Seven local commits so far (`31e6c67` → `5f342cf`). Every stage keeps its inputs unchanged
and is tested.

| Stage | Code | What it does |
|---|---|---|
| Acquisition | `src/fetch_greenhouse.py` | Public Greenhouse Job Board GET only. Immutable timestamped snapshots, a SHA-256 manifest (`data/raw_manifest.csv`), cache-first reuse, `--refresh`, `--dry-run`, bounded retries that honour `Retry-After` |
| Cleaning | `src/prepare_postings.py` | Decodes the double-encoded HTML and keeps paragraph and bullet boundaries. Gives stable `posting_id`s. Flags missing/empty descriptions, placeholders and exact duplicates, and keeps flagged rows. Writes JSONL + CSV and a quality report |
| Local DB | `src/load_postings.py`, `sql/schema_v1.sql` | SQLite, key (`snapshot_id`, `posting_id`), `usable_postings` view, foreign keys, one transaction per load, idempotent re-runs, conflicting content rejected |
| Exploration | `notebooks/sprint1_exploration.ipynb`, `src/derive_features.py`, `config/seniority_rules.yaml` | Read-only analysis. Rule-based seniority, local language detection, near-duplicate candidate pairs. Derived results stored outside `postings` |
| Reference data | `src/register_esco_archive.py`, `src/load_esco.py`, `sql/migration_002_esco_reference.sql` | ESCO provenance manifest (`data/reference_manifest.csv`) and a transactional import of the skill pillar |
| Policy (proposed) | `docs/extraction_input_policy.md` | Rules for what goes into Sprint 2 extraction. Not implemented |

The draft data contract (`docs/data_contract.md`, v0.4) describes all of these tables. It
is a **proposal**, not yet agreed with Section A.

## 2. Corpus: a five-employer pilot

| | Value |
|---|---|
| Source | Greenhouse Job Board API (public, no key), snapshot `20261006T171338Z` |
| Employers (team-assigned industry) | Duolingo (education tech), Robinhood (financial services), Recursion Pharmaceuticals (biotech), Oura (consumer health tech), Figma (software). Board tokens were verified on each company's careers page |
| Postings | **470** total · **468** usable · **2** flagged (both Recursion general-interest postings, kept for audit) |
| Exact duplicates | 0 |

## 3. Exploration findings and sampling limitations

All figures below are from `reports/sprint1_exploration.md`. "Usable" means n = 468.

- **Concentration:** Figma and Robinhood are **67.9%** of usable rows (HHI 0.277).
  Recursion has only 10. Industry is assigned per employer, so "by industry" means "by
  employer".
- **Length:** median **927** words per description (range 492–1,665). This includes heavy
  boilerplate: equal-opportunity text appears in 468 / 468 postings and benefits text in
  466 / 468.
- **Seniority** (rules v0.1.0, from title wording): `unknown` 34.0%, senior 21.6%, manager
  14.5%, staff/principal 10.3%, intern 7.7%. "Unknown" means no seniority word in the
  title, not mid-level.
- **Language:** a local detector (lingua 2.2.0) found **470 / 470 English**, with 0
  uncertain and 0 disagreements with the employer-set field. I manually checked 43
  postings located in non-English markets, and all are English.
- **Duplicates:** 0 exact, 13 repeated-title groups. **30 near-duplicate candidate pairs**
  (9 at ≥ 0.99 similarity), mostly the same role in different locations. One requisition
  is posted under two titles.
- **Sampling limitations:**
  - Five employers is far too few for an occupational taxonomy, and four of them are tech
    companies.
  - This is one snapshot, so there is no time dimension.
  - Selection was by board availability, not by sampling design.
  - Seniority labels have no ground truth.
  - Near-duplicate detection is incomplete.
  - **None of these findings generalise beyond the pilot.**

## 4. ESCO import results

ESCO **v1.2.1**, English, CSV classification (licence: Commission Decision 2011/833/EU,
attribution required). It was downloaded manually by a team member. **The original ZIP is
not available**, so the hashes of the 19 extracted CSVs are recorded instead. The
acquisition date is recorded as 2026-10-06, with its evidence. The data is in the
**local-dev** DB only.

| | Count |
|---|---|
| Concepts | **14,579** = 13,939 `KnowledgeSkillCompetence` + 640 `SkillGroup` |
| Broader relations | **20,819** (skill→group 13,723 · skill→skill 6,460 · group→group 636); 4,759 skills have more than one parent |
| Skill–skill relations | **5,818** (optional 5,629 · essential 189) |
| Unresolved endpoints / cycles / missing hierarchy links | **0 / 0 / 0** |
| Repeated source URIs | 21. They differ only in `modifiedDate`, the latest row is loaded, and all 42 original rows are kept in `esco_source_duplicates` |
| Postings before / after the import | 470 / 468 / 2 → **470 / 468 / 2**. Existing tables are content-identical, `integrity_check` ok, 0 FK violations |

Details: `reports/sprint1_esco_reference.md`.

## 5. Problems encountered and fixes

| Problem | Fix |
|---|---|
| Greenhouse `content` is entity-escaped HTML that still contains entities after one decode | Decode once, then run an HTML parser that decodes the rest. Tests cover nested bullets and entities |
| Title-only placeholder rules missed "Interested in an internship?" | Added two narrow description phrases, measured against the pilot first. Rejected "not hiring" because it also matched a real Figma posting |
| Exact-duplicate count of 0 hid location variants (similarity up to 0.998) | Reported repeated-title groups and candidate pairs separately; nothing excluded |
| lingua's whole-text label followed the **minority** language on mixed text (6 EN + 1 FR paragraphs → "fr", confidence 1.0) | Label = paragraph word-majority; the whole-text result is kept separately; any disagreement marks the row uncertain |
| Naive seniority words: "Account Executive", "Executive Assistant", "Creative Director", "Product Manager" | Ordered rules with excludes; `unknown` and `ambiguous` labels; other matches kept for review |
| ESCO portal delivers downloads only by an emailed link | Documented the blocker and did not guess URLs. A team member downloaded the files, and they were registered in place |
| A real ESCO field exceeds Python's 128 KiB CSV limit | Raised the limit, added a regression test, and re-ran (idempotent) |
| 21 ESCO URIs repeated, 188 ragged hierarchy rows | Explicit policies with audit trails; nothing silently dropped |
| Some of my own tests were wrong, and chart labels collided | Fixed the tests, not the code; re-rendered and re-checked every chart |

## 6. Reproduction and current test results

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest                                              # 177 passed (2026-10-06)

python src/fetch_greenhouse.py --dry-run                      # plan only
python src/fetch_greenhouse.py                                # reuses verified cache
python src/prepare_postings.py --snapshot 20261006T171338Z
python src/load_postings.py --input data/processed/postings_20261006T171338Z.jsonl \
                            --db data/processed/taxonomy_pilot.sqlite
python src/derive_features.py --db data/processed/taxonomy_pilot.sqlite --snapshot 20261006T171338Z
jupyter nbconvert --to notebook --execute --inplace notebooks/sprint1_exploration.ipynb
python src/register_esco_archive.py --extracted-dir auto --version v1.2.1 --language en \
  --acquired-on YYYY-MM-DD --acquisition-evidence "..."
python src/load_esco.py --db data/processed/taxonomy_pilot.sqlite --version v1.2.1 --source-dir auto
```

- **Tests:** 177 passing on Python 3.14.8 with SQLite 3.53.4. By file: fetcher 42,
  cleaner 26, loader 28, derived features 43, ESCO registration 21, ESCO import 17.
  Every test uses mocked HTTP or synthetic fixtures, and none touches the network.
- **What a rebuild needs:** the raw snapshot and the ESCO folder (both git-ignored). Their
  hashes in the tracked manifests let a teammate verify an identical copy.

## 7. LLM / API token usage

**Pipeline LLM tokens: 0.** No LLM was called by any pipeline step, and the ESCO and
language steps use local files and a local detector. The only data API was the
Greenhouse public job board (5 GET requests for the pilot). Separately, during development,
company careers pages were fetched to verify board tokens, and ESCO portal and
documentation pages were fetched to find the source and licence. Claude Code was used for
development; its interactions are logged in `docs/claude_usage_log.md`.

## 8. Outstanding shared decisions (not complete)

| Decision | Status |
|---|---|
| Shared corpus: board list and canonical snapshot (D1, D2) | **Open.** The 5 boards are a pilot proposal and need Section A's agreement |
| Data contract (brief: "must agree in Sprint 1") | **Open.** Draft v0.4 needs Section A review |
| Shared database engine and location (D3) | **Open.** SQLite here is local development only |
| Raw and reference file storage and sharing (D8) | **Open.** Nothing uploaded |
| ESCO version and table design (D9) | Proposed (v1.2.1), awaiting Section A |
| **O*NET (D10)** | **Unresolved shared dependency.** Needed for Sprint 5 task–skill priors. Ownership and version have **not** been agreed with Section A. Team B has not loaded O*NET |
| Language scope (D6), near-duplicate policy, boilerplate rules | Proposals: `docs/extraction_input_policy.md` |
| Lightcast Open Skills | Not started |

## 9. Sprint 2 preparation (Team B)

1. **Skill annotation guidelines:**
   - **Definitions:** what counts as one atomic skill statement (knowledge, skill/competence,
     tool or technology, soft skill); how to treat requirement vs. nice-to-have; how to
     treat values sections, years-of-experience and degrees.
   - **Worked examples** from pilot postings, and agreement rules.
2. **Hand-labelled evaluation set of 100 postings** (brief p.3):
   - a stratified sample from `usable_postings` across the five employers, seniority labels
     and role groups (P4), with a fixed seed and frozen IDs
   - double annotation of a subset to measure inter-annotator agreement
3. **Extraction:**
   - Build the extraction input under `docs/extraction_input_policy.md`, after the open
     questions are decided.
   - Choose and justify an approach (rules, NLP, LLM, or a mix). If an LLM is used:
     provider-agnostic interface, a disk cache, rate-limit handling, and token logging
     (brief p.7).
4. **Quality evaluation:**
   - precision and recall against the 100-posting set
   - error analysis by employer and section
   - posting-level vs. role-level counts
   - a first look at coverage against ESCO
