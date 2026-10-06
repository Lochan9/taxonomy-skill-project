# Sprint 2 Annotation Preparation (Team B), PILOT

**Date:** 2026-10-06 · **Status:** the selection is frozen and the workflow is ready.
**No postings have been annotated yet.** There are 0 gold labels, and no LLM or automatic
extraction was used.

- **Selection manifest:** `data/annotation/sprint2_v1/selection_manifest.csv` (tracked).
- **Guidelines:** `docs/skill_annotation_guidelines.md` (v0.2.1 draft: skills inside duties are annotated, including abilities stated as actions; "X or Y" alternatives are grouped, illustrative "such as" lists are not by default).
- **Tools:** `src/select_annotation_set.py` and `src/annotations.py`.

## 1. Scope and a proposed deviation from the brief

The brief says to "hand-label 100 postings to measure extraction precision/recall" (p.3).
Team B **proposes** a split of the same 100 postings:
- **20 development** postings for guideline calibration and for tuning extraction rules or
  prompts.
- **80 held-out evaluation** postings, used only for scoring.

**All 100 still need human annotation.** Tuning on postings that are later scored inflates
precision and recall, so the held-out 80 give the honest number. Because this departs from
the brief's literal "100 postings to measure P/R", the split is marked **proposed**.

If the instructor prefers the literal reading, report P/R on all 100, with the 80-only figure
alongside. Nothing in the files prevents that.

## 2. Inputs (read-only)

- **Population:** the **468** postings in `usable_postings` for snapshot `20261006T171338Z`.
  The 2 flagged placeholders are excluded, per extraction policy P2.
- **Fields inspected before choosing strata:**
  - `board_token` / `company_name`: 5 employers.
  - `title`: seniority via `config/seniority_rules.yaml` v0.1.0, and base titles for
    variant grouping.
  - `departments`: 96 names, all employer-specific. The first department is used as a
    role-variety proxy.
  - `location`.
  - `internal_job_id`: shared requisitions.
  - `word_count`.
  - The Sprint 1 near-duplicate candidates.
- **Not used:** `industry`, which is one label per employer and so duplicates the employer
  stratum.
- **Integrity:** the database and raw files were not modified (SHA-256 checked before and
  after).

## 3. Grouping decisions: review before splitting

**Related-posting groups** are the union of postings on the same board that share an
`internal_job_id` or the same **base title**. A base title is the title with trailing
parentheticals removed, so "Solutions Consultant (London, United Kingdom)" becomes
"solutions consultant".

| | Count |
|---|---|
| Groups over the 468 usable postings | **411** (373 singletons, **38** multi-member groups covering 95 postings) |
| Multi-member groups by basis | base title 16 · base title + shared requisition 11 · shared requisition only 11 |
| Sprint 1 candidate pairs (30) that fall inside one group | **30 / 30** |

- **What the base-title rule adds:** the Sprint 1 detector missed Figma's location-suffixed
  variants ("Account Executive, Enterprise (Paris, France)" …). This rule catches them.
- **What a group means:** the postings are **related and kept together**. It is *not* a
  duplicate decision. Similarity alone never proves duplication: some shared-requisition
  groups are different teams (Robinhood "Android Engineer, Government Products / Money
  Experience / Social"), and one is a retitled role (Duolingo "Ad Sales Lead - West" /
  "Director of Ad Sales - West").
- **One representative per group** is drawn with the seeded RNG. Related variants therefore
  **cannot end up in different splits**, and annotation effort isn't spent on near-repeats.
- **Every manifest row records its group** (`group_id`, `group_size`, `group_basis`,
  `group_members`), so any non-selected variant inherits its group's split if it's ever
  added.

**Selected postings that belong to multi-member groups (7)**

| Split | Selected posting | Basis | Other members (not selected) |
|---|---|---|---|
| development | `greenhouse:duolingo:8675713002` Senior Product Designer | base_title (identical titles) | 1 |
| development | `greenhouse:figma:6152695004` Software Engineer Intern (London…) (Summer 2027) | base_title | 2 |
| development | `greenhouse:robinhood:8175213` Engineering Manager, International | base_title + internal_job_id | 1 |
| evaluation | `greenhouse:duolingo:8705196002` Ad Sales Lead - West | internal_job_id (retitled pair) | 1 |
| evaluation | `greenhouse:figma:5735493004` Solutions Consultant (London…) | base_title | 3 |
| evaluation | `greenhouse:recursionpharmaceuticals:8234254` Executive Director, Clinical Pharmacology/… | base_title + internal_job_id | 1 |
| evaluation | `greenhouse:robinhood:8142278` Senior Staff Software Developer, Core Infrastructure | internal_job_id | 1 |

The 10 related postings that weren't selected are excluded from the annotation set and
recorded in the manifest. 5 of the 30 Sprint 1 candidate pairs involve a selected posting.

## 4. Selection method (v1.0.0, seed 20261006)

1. **Employer quotas, balanced not proportional:**
   - Each employer starts with an equal share of 100, capped by its number of groups.
   - Leftover seats go to the employers with the most groups.
   - Result: Recursion **9** (all its groups), Duolingo **22**, Figma, Oura and Robinhood
     **23** each.
2. **Seniority variety:** within an employer, the quota is spread over title-based seniority
   labels in proportion to their group counts, with **at least one per label present**
   (largest-remainder rounding).
3. **Role variety:** within each employer × seniority cell, groups are drawn in seeded order,
   **preferring departments not yet chosen** for that employer.
4. **Split:** 20 development postings, allocated per employer by largest remainder of 20%,
   with members drawn by the seeded RNG. Every other posting is evaluation.
5. **Frozen manifest:**
   - Each row records the snapshot ID, posting ID, split, grouping, seniority label,
     first department, the **SHA-256 of `clean_text`**, the seed and the selection version.
   - `--check` re-derives the selection and fails if it differs, or if any text has
     changed.
   - Re-running without `--force` refuses to overwrite a different manifest.

## 5. Distribution of the selection

**Employer × split**

| Employer (team-assigned industry) | Usable postings | Groups | Selected | Development | Evaluation |
|---|---|---|---|---|---|
| Duolingo (education tech) | 60 | 54 | 22 | 4 | 18 |
| Figma (software) | 159 | 129 | 23 | 5 | 18 |
| Oura (consumer health tech) | 80 | 80 | 23 | 5 | 18 |
| Recursion Pharmaceuticals (biotech) | 10 | 9 | 9 | 2 | 7 |
| Robinhood (financial services) | 159 | 139 | 23 | 4 | 19 |
| **Total** | **468** | **411** | **100** | **20** | **80** |

**Seniority label (rules v0.1.0, from title wording; not verified levels)**

| Label | Usable pool (468) | Selected (100) | Development (20) |
|---|---|---|---|
| unknown | 159 | 21 | 2 |
| senior | 101 | 22 | 8 |
| manager | 68 | 14 | 2 |
| staff_principal | 48 | 9 | 1 |
| intern | 36 | 8 | 3 |
| director | 32 | 12 | 4 |
| ambiguous | 14 | 5 | 0 |
| executive | 6 | 6 | 0 |
| entry / mid | 2 / 2 | 2 / 1 | 0 / 0 |

**Role variety:**
- **Departments:** 71 distinct (employer, first-department) pairs among the 100. By
  employer: Robinhood 23, Duolingo 18, Figma 13, Oura 13, Recursion 4.
- **Length:** median description length is 967 words (range 492–1,526), against 927 in
  the pool.

The selection deliberately **oversamples** rare levels: all 6 executive-titled postings and
12 of the 32 director-titled postings are included. It **undersamples** the large `unknown`
class (21 of 159).

## 6. Limitations

- **Small, tech-heavy pilot:** five employers, four of them technology companies, and a
  single snapshot. A score on this set says how well extraction works **on these
  employers' writing styles**, not on the job market.
- **Balanced, not representative:** employer quotas are equal, not proportional, so the set
  is not a random sample of the 468.
  - Corpus-level estimates (e.g. "share of postings requiring Python") must not be taken
    from it without re-weighting by employer: usable count ÷ selected count, e.g. Figma
    159/23 vs Recursion 10/9.
  - Precision and recall should be reported **per employer** as well as overall.
- **Recursion is thin:** 9 postings (2 development), so its per-employer figures will be
  noisy.
- **Weak strata:**
  - Seniority labels come from title wording, and 34% of the pool is `unknown`.
  - Department names are not harmonised across employers.
- **Development split coverage:** it is small and, by chance, contains no `ambiguous`,
  `executive`, `entry` or `mid` titles. Calibration may miss issues specific to those.
- **Grouping is conservative but incomplete:**
  - Variants with different base titles **and** different requisition IDs, or across
    boards, are not grouped.
  - The `Software Engineer Intern` group joins Summer and Winter 2027 internships, because
    parentheticals also hold dates.
- **Corpus dependence:** if the agreed corpus differs from this pilot (decision D1/D2 is
  still open with Section A), a new selection version is needed. This set would then remain
  only a pilot benchmark.

## 7. Annotation workflow (summary; details in the guidelines, §10)

- **Records:** `postings_review.csv` holds one row per posting, with `review_status`
  `not_started` | `in_progress` | `reviewed`. A **reviewed posting with zero skill rows is a
  deliberate zero-skill result**; the other two statuses mean unfinished. `skills.csv` holds
  one row per atomic skill statement.
- **Skill record fields:**
  - `snapshot_id`, `posting_id`, `annotation_id`, `skill_statement`
  - `evidence_text`, `evidence_start`, `evidence_end`
  - `required_or_preferred` (`required` | `preferred` | `unspecified`)
  - `alternative_group_id` (optional): marks "X or Y" alternatives so that split records
    don't read as all required
  - `skill_category` (optional)
  - `annotator_id`, `review_notes`
- **Offsets:** zero-based Python character positions into the unchanged `clean_text`, end
  exclusive. `clean_text[start:end] == evidence_text` is checked by the validator.
- **Exported texts:** `data/annotation/sprint2_v1/texts/` (git-ignored, regenerable). They
  are byte-identical to `clean_text` (100/100 verified by SHA-256), so editor offsets equal
  Python offsets.
- **Commands:**

  ```bash
  python src/annotations.py export   --db data/processed/taxonomy_pilot.sqlite
  python src/annotations.py init     --annotator <id>
  python src/annotations.py locate   --db … --posting <posting_id> --text "exact phrase" [--occurrence N]
  python src/annotations.py validate --db … --dir data/annotation/sprint2_v1/annotators/<id> [--final]
  python src/annotations.py compare  --db … --a <id1> --b <id2>
  ```

- **Disagreements:**
  - `compare` reports exact, overlapping and one-sided spans, requirement disagreements and
    alternative-grouping disagreements, with an overlap-F1.
  - Adjudicated results go to `data/annotation/sprint2_v1/adjudicated/`, and the annotators'
    originals stay unchanged.
  - `validate --final` must pass: all 100 reviewed and 0 problems.
- **Second review:** an independent second annotator is **recommended** for all 100 where
  capacity allows. The minimum is the 20 development postings plus a sample of 20 or more
  evaluation postings.

## 8. Remaining human work

- [ ] **Development round:** two annotators independently label the 20 development
  postings. Then compare, discuss, and revise the guidelines (v0.3).
- [ ] **Evaluation round:** label the 80 evaluation postings with the frozen guidelines.
  Get a second independent review where possible, and record agreement.
- [ ] **Adjudication:** resolve every disagreement, then run `validate --final` on
  `adjudicated/`.
- [ ] **Commit:** commit the annotator and adjudicated CSVs. Only then call the set "gold".
- [ ] **Instructor sign-off** on using 20 / 80 instead of all 100 for P/R (§1).

Separately, the shared Sprint 1 decisions (corpus, contract, shared database, storage, and
O*NET ownership) remain **open**. See `reports/sprint1_team_b_summary.md` §8.
