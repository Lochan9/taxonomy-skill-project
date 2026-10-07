# Sprint 2 Checklist: Text Extraction (Weeks 3–4), Team B (skills)

Source: `docs/master_project_description.pdf` p.3. Tags as in `docs/sprint1_checklist.md`:
**[REQ]** required · **[SAMPLE]** sample task (instructors assign the actual tasks) ·
**[REC]** recommendation.

> **Sprint 1 is still open.** Its shared deliverables (agreed corpus, data contract, shared
> database, storage, O*NET ownership) are unresolved; see `docs/sprint1_checklist.md` §0.
> Sprint 2 work below runs on the **pilot** corpus and may need re-running on the agreed one.

## Sample tasks (p.3)

- [ ] **[SAMPLE]** Choose an extraction approach (section parsing, sentence splitting, NLP,
      LLM prompting, or a mix) and justify it
- [ ] **[SAMPLE]** Produce one atomic statement per skill mentioned in a posting
- [ ] **[SAMPLE]** If using an LLM: caching and rate-limit handling, so re-runs are free and
      quota-safe ([REQ] p.7: free-tier or student-credit provider only, keys in env vars,
      token logging)
- [ ] **[SAMPLE]** Hand-label 100 postings to measure extraction precision/recall
- [ ] **[SAMPLE] Deliverable:** statements table in the shared database, plus an extraction
      quality report

## Annotation preparation (done locally, no labels yet)

- [x] Annotation guidelines **v0.2.1 draft** (`docs/skill_annotation_guidelines.md`), with
      positive, negative and borderline pilot examples taken from outside the set
  - [x] Skills explicitly expressed in duties are annotated; task-only statements are not (§3a)
  - [x] Abilities stated as actions are faithfully normalised ("Build prototypes" →
        *prototyping*); inferred skills are not (§3a)
  - [x] Optional `alternative_group_id` for "X or Y" alternatives (§3b); never used for "and"
- [x] 100-posting selection, frozen and reproducible (`src/select_annotation_set.py`,
      `data/annotation/sprint2_v1/selection_manifest.csv`, seed 20261006, v1.0.0)
  - [x] Only the 468 usable postings of `20261006T171338Z`. Balanced employer quotas
        (9 / 22 / 23 / 23 / 23), seniority and department variety
  - [x] Related variants grouped (shared requisition or base title), one representative
        per group, so they never cross splits
  - [ ] **20 development / 80 evaluation split. PROPOSED**, because the brief says "100
        postings to measure P/R". Instructor or team sign-off needed
- [x] Local annotation workflow (`src/annotations.py`): export, init, locate, validate,
      compare. Zero-skill postings are distinguishable from unfinished ones
- [x] Tests for selection and annotation validation (35). See
      `reports/sprint2_annotation_preparation.md`

## Human annotation (not started)

- [ ] Calibration: 2 annotators on the 20 development postings, then `compare`, discussion,
      and guidelines v0.3
- [ ] Evaluation postings (80) annotated under the frozen guidelines
- [ ] Independent second review **[REC]**: all 100 if capacity allows, at least the
      development postings plus 20 evaluation postings
- [ ] Adjudication into `adjudicated/`, then `validate --final` passes, then commit. Only
      then call it gold

## Extraction (implemented; 3-posting pilot run)

- [ ] Decide the open extraction-policy questions (pay sections, recruiting notices, values
      sections, shared near-duplicate review)
- [ ] Build the versioned extraction input under `docs/extraction_input_policy.md`. Until
      then, the extractor reads the full unchanged `clean_text` (P5/P6 conservative
      default)
- [x] LLM extractor `src/extract_skills.py`, using the official Anthropic SDK behind a
      provider interface:
  - versioned prompt and JSON schema (`config/prompts/`, `config/schemas/`)
  - local evidence and offset validation
  - repeated-evidence handling
  - zero-skill vs failed results
  - caching, bounded retries and rate-limit handling, resumability
  - token usage and run provenance
  - `--dry-run`
  - 28 tests with mocked responses
- [x] Restricted to the 20 development postings. The evaluation postings are refused
- [ ] **Confirm that the provider qualifies** under brief p.7 (free-tier or student-credit
      provider). Recorded as university-provided Anthropic access, compliance
      **unresolved**
- [x] Enter `ANTHROPIC_API_KEY` locally in `.env`, run model discovery
      (`models.list()`), then choose the pilot model and set `EXTRACTION_MODEL`
- [x] Pilot prepared: 3 development postings (Duolingo 8675713002, Robinhood 4738660,
      Recursion 8188707), full `clean_text`, dry run OK
- [x] Model discovery done (13 models); pilot model `claude-sonnet-5-5` (user's choice)
- [x] Pilot run `skx-20261007T003601Z` on 3 development postings: 3/3 ok, 35 statements,
      0 rejected, 14,266 input / 7,860 output tokens, about $0.098
- [ ] Review the pilot outputs against the guidelines, then run the remaining 17
      development postings
- [ ] Decide on the proposed `mention_relation` field for annotations and statements
      (contract §12); `skills.csv` is unchanged
- [ ] Load accepted statements into `statements` rows (`kind = skill`, offsets under the
      shared convention, contract §12) once the shared database (D3) is agreed
- [ ] Quality report: P/R on the evaluation postings (and on all 100 if required), per
      employer, posting-level vs role-level counts, and token usage

## Out of scope for Team B

- Task extraction or a task taxonomy (Section A)
- O*NET loading (a shared dependency; owner not agreed)
- Mapping skills to ESCO (later sprint)
