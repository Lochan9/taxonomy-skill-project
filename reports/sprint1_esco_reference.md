# Sprint 1 ESCO Reference Data (Section B): **imported (local development DB)**

**Date:** 2026-10-06 · **Owner:** Section B (skill taxonomy) · **LLM tokens:** 0

ESCO is Section B's reference standard (brief p.2, p.5). The skill-pillar files of **ESCO v1.2.1
(English, classification, CSV)** are now in the **local development** database
`data/processed/taxonomy_pilot.sqlite`. This is **not** the shared database (D3 is still
pending). No postings have been mapped to ESCO and no skills have been extracted.

- **Machine-readable summary:** `reports/esco_import_summary_v1.2.1.json`.
- **Actual headers:** `reports/esco_headers_v1.2.1.md`.

## 1. Source and provenance

| Item | Value |
|---|---|
| Official source | https://esco.ec.europa.eu/en/use-esco/download (European Commission) |
| Version / content / language / format | **v1.2.1** / classification / English (`en`) / CSV |
| Licence | Commission Decision 2011/833/EU: free reuse for any purpose. The source must be acknowledged ("This service uses the ESCO classification of the European Commission"), and modified versions must be indicated as such. [ESCO FAQ](https://esco.ec.europa.eu/en/about-esco/faq?page=2&search=) |
| How acquired | Downloaded manually by a team member through the portal's emailed link, then extracted into the repo |
| Local folder | `data/reference/ESCO dataset - v1.2.1 - classification - en - csv` (located by name prefix, not hard-coded; registered **in place**, nothing moved or copied) |
| **Acquisition date** | **2026-10-06**, i.e. the date the extracted folder appeared in this repo (filesystem creation time 14:47 EDT). The actual portal download date was not stated. The source files' own timestamps are 2025-12-16, preserved from the archive |
| **Original ZIP** | **Not available.** No archive hash is recorded or claimed. Only the extracted CSVs are hashed |
| File hashes | All **19** CSVs are recorded with SHA-256 and size in the tracked `data/reference_manifest.csv` (`role = source_file`). The importer refuses any file that is missing from the manifest or whose hash differs |

SHA-256 of the six files the importer reads:

| File | Bytes | SHA-256 |
|---|---|---|
| `skills_en.csv` | 9,302,000 | `d03b10efca94b4bcfa260a992cfde89c375f0fa12095d6662a663cfd2f9f2950` |
| `skillGroups_en.csv` | 340,935 | `644b68a174299eb05336eec36e0716c4671a0c6bdd4ac268803ecd6533dc739d` |
| `broaderRelationsSkillPillar_en.csv` | 4,944,592 | `56b70f4852b1f53c6192c979310c34c93f95436621d907083cf0d55b51d8e42d` |
| `skillSkillRelations_en.csv` | 1,031,275 | `64a5f8fb7b8dda4932ff06db4738ce1beed3906e45a49b14453349056c609439` |
| `conceptSchemes_en.csv` | 941,042 | `4e5b4800e6cdc2013df0f22dfff72c0499cdce8bf9cfa333d6c4c14879dce517` |
| `skillsHierarchy_en.csv` | 381,733 | `295133872c6be7b7560de943efa4a6aab833a1b15af4d60c03b050ab0a75edcb` (validation only) |

The source folder's 19 files were hashed before and after registration and import, and all
were byte-identical.

## 2. What the files contain (confirmed from the real headers)

| File | Rows | What it is |
|---|---|---|
| `skills_en.csv` | 13,960 (13,939 unique URIs) | Skill/knowledge concepts: `conceptUri`, `preferredLabel`, `altLabels`, `description`, `skillType`, `reuseLevel`, … |
| `skillGroups_en.csv` | 640 | Skill-group concepts (`conceptType = SkillGroup`), with a `code` such as `S3.4.2` |
| `broaderRelationsSkillPillar_en.csv` | 20,819 | `conceptUri → broaderUri`, with the source `conceptType` / `broaderType` |
| `skillSkillRelations_en.csv` | 5,818 | Skill→skill relations with `relationType` (`essential` / `optional`) |
| `conceptSchemes_en.csv` | 20 | Concept schemes referenced by `inScheme` |
| `skillsHierarchy_en.csv` | 640 | Level 0–3 group paths. **Used only to cross-check** the broader relations, not loaded |

Not loaded, because they are out of scope for the skill reference tables: the occupation pillar
(`occupations`, `ISCOGroups`, `broaderRelationsOccPillar`, `occupationSkillRelations`,
`greenShareOcc`), the collection files (`digital`, `green`, `language`, `transversal`,
`research`, `digComp`) and `dictionary`. Collection *membership* is still available through
`inScheme`.

## 3. Import results

Command: `python src/load_esco.py --db data/processed/taxonomy_pilot.sqlite --version v1.2.1 --source-dir auto`.
The migration (`sql/migration_002_esco_reference.sql`) and the import ran in **one
transaction**. A **second run** reported "already imported (no changes)".

**Concepts (14,579), key (`esco_version`, `concept_uri`)**

| `concept_type` (source term) | Count | Notes |
|---|---|---|
| `KnowledgeSkillCompetence` | 13,939 | `skill_type`: skill/competence 10,715 · knowledge 3,219 · *empty in source* 5. `reuse_level`: sector-specific 6,655 · cross-sector 3,783 · occupation-specific 3,044 · transversal 452 · *empty in source* 5 |
| `SkillGroup` | 640 | 4 top-level groups with no broader link: "skills" (S), "knowledge" (K), "transversal skills and competences" (T), "language skills and knowledge" (L) |

**Relationships (all endpoints resolved)**

| Relationship | Type (source terms) | Count |
|---|---|---|
| broader | `KnowledgeSkillCompetence` → `SkillGroup` | 13,723 |
| broader | `KnowledgeSkillCompetence` → `KnowledgeSkillCompetence` | 6,460 |
| broader | `SkillGroup` → `SkillGroup` | 636 |
| **broader, total** (narrower = inverse view `esco_narrower_relations`) | | **20,819** |
| skill–skill | `optional`: skill/competence → knowledge 5,453 · skill/competence → skill/competence 141 · knowledge → knowledge 35 | 5,629 |
| skill–skill | `essential`: skill/competence → knowledge 93 · skill/competence → skill/competence 82 · knowledge → knowledge 14 | 189 |
| **skill–skill, total** | | **5,818** |
| scheme membership (`inScheme`) | 10 schemes | 31,840 |

- Every skill has at least one broader link, and **4,759 skills have more than one**, so ESCO
  is a polyhierarchy, not a tree.
- The broader graph has no cycles.

**Validation and unresolved references**

| Check | Result |
|---|---|
| Unresolved broader endpoints | **0** of 20,819 |
| Unresolved skill–skill endpoints | **0** of 5,818 |
| Unresolved `inScheme` scheme URIs | **0** |
| Broader rows whose stated type ≠ the concept's file type | 0 |
| Labels in the relation files ≠ the concept's `preferredLabel` | 0 |
| `skillsHierarchy` links (636) missing from the broader relations | **0**. No link was created from that file |
| Self-loops / duplicate pairs / cycles | 0 / 0 / 0 |

**Missing values (as in the source)**

| | Skills (13,939) | Skill groups (640) |
|---|---|---|
| Missing preferred label | 0 | 0 |
| No alternative labels | 18 | 528 |
| Missing description | **0** | **133** |
| Missing `skillType` / `reuseLevel` | 5 / 5 | n/a |
| Missing code | n/a | 0 |

**Source quirks, kept and reported rather than "fixed"**

- **Repeated URIs:** 21 skill URIs appear **twice** in `skills_en.csv`, and the two rows
  differ **only** in `modifiedDate`. One row per URI is loaded (the latest `modifiedDate`),
  and all 42 source rows are kept in `esco_source_duplicates` with their row numbers. A
  repeat that differs in any other field would abort the import.
- **Empty label pieces:** 4 empty alternative-label pieces (trailing newlines) were dropped.
  The 86,622 non-empty alternative labels are stored as JSON arrays.
- **Ragged rows:** 188 `skillsHierarchy` rows omit trailing empty fields. This is accepted
  for that file only; any other file with a wrong field count aborts the import.
- **Empty types:** the 5 skills with empty `skillType` and `reuseLevel` are the DigComp
  areas (e.g. "ICT safety", "digital content creation"). They are stored as NULL and not
  guessed.

## 4. Five real concept examples

| URI (suffix) | Type | Preferred label | Details | Broader (type: label) |
|---|---|---|---|---|
| `skill/00090cc1-…` | KnowledgeSkillCompetence | identify available services | skill/competence, cross-sector, 8 alt labels | SkillGroup: assisting people to access services |
| `skill/000f1d3d-…` | KnowledgeSkillCompetence | Haskell | knowledge, sector-specific | KnowledgeSkillCompetence: computer programming · SkillGroup: software and applications development and analysis |
| `skill/001115fb-…` | KnowledgeSkillCompetence | show initiative | skill/competence, **transversal**, 7 alt labels | SkillGroup: taking a proactive approach |
| `skill/11dc8e6b-…` | KnowledgeSkillCompetence | operate pumping equipment | sector-specific; **2 source rows** (repeated URI) | KSC: operate pumping systems · KSC: operate pumps · SkillGroup: operating pumping systems or equipment |
| `skill/00d5d1d2-…` | SkillGroup | accompanying and welcoming people | code `S3.4.2` | SkillGroup: providing information and support to the public and clients |

Full URIs are in `reports/esco_import_summary_v1.2.1.json`. The examples were picked as the
first URI, in sort order, matching each of five criteria (not cherry-picked).

## 5. Existing data preserved

| Check | Before import | After import (and after the repeat run) |
|---|---|---|
| Postings, snapshot `20261006T171338Z` | 470 total / 468 usable / 2 flagged | **470 / 468 / 2** |
| Content fingerprints of `postings`, `snapshots`, `loads`, `schema_meta` | recorded | **identical** |
| `schema_meta.schema_version` (postings schema) | 1 | 1 (migrations tracked separately in `schema_migrations`) |
| `PRAGMA integrity_check` / `foreign_key_check` | ok / 0 | **ok / 0** |
| Raw Greenhouse files (5) | hashed | byte-identical |
| ESCO source folder (19 files) | hashed | byte-identical |

A backup copy of the pre-import database was kept outside the repo during the session.

## 6. Reproduce

```bash
# 1. Download ESCO v1.2.1 (classification, English, CSV) from the official portal (emailed
#    link) and extract it under data/reference/ (the folder name starts with
#    "ESCO dataset - v1.2.1 - classification - en - csv").
# 2. Record SHA-256 hashes in data/reference_manifest.csv (read-only; regenerates the headers report).
#    With the original ZIP, use --archive ZIP --downloaded-on YYYY-MM-DD instead.
python src/register_esco_archive.py --extracted-dir auto --version v1.2.1 --language en \
  --acquired-on YYYY-MM-DD --acquisition-evidence "how you know this date"
# 3. Import (migration + data in one transaction; re-runs are no-ops; conflicts are rejected)
python src/load_esco.py --db data/processed/taxonomy_pilot.sqlite --version v1.2.1 --source-dir auto
```

The hashes in `data/reference_manifest.csv` tell a teammate whether their download is
byte-identical to ours.

## 7. Out of scope, and open items

- [ ] **Mapping and extraction:** postings → ESCO mapping and skill extraction start in
  Sprint 2. None is done here.
- [ ] **Shared database:** the engine and location are pending with Section A (D3). These
  tables live in the local development SQLite only.
- [ ] **O*NET** (task–skill priors, Sprint 5): a **shared dependency to coordinate with
  Section A**. Ownership is **not** agreed, and Section B has not loaded O*NET (D10).
- [ ] **Lightcast Open Skills** (emerging-skill coverage): not started.
- [ ] **Original ZIP:** if the team wants archive-level provenance, download it again and
  register it with `--archive`. Its CSVs should then match the hashes above.
