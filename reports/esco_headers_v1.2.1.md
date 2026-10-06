# ESCO v1.2.1 CSV headers (as found on disk)

Folder: `data/reference/ESCO dataset - v1.2.1 - classification - en - csv` (registered in place)
Original ZIP: **not available**; no archive hash recorded.
Source: https://esco.ec.europa.eu/en/use-esco/download · acquired 2026-10-06 (date the extracted folder appeared in this repo (filesystem creation time 2026-10-06 14:47 EDT); portal download date not stated; original ZIP not available) · language `en`

| File | Data rows | Columns |
|---|---|---|
| `ISCOGroups_en.csv` | 619 | `conceptType`, `conceptUri`, `code`, `preferredLabel`, `status`, `altLabels`, `inScheme`, `description` |
| `broaderRelationsOccPillar_en.csv` | 3,648 | `conceptType`, `conceptUri`, `conceptLabel`, `broaderType`, `broaderUri`, `broaderLabel` |
| `broaderRelationsSkillPillar_en.csv` | 20,819 | `conceptType`, `conceptUri`, `conceptLabel`, `broaderType`, `broaderUri`, `broaderLabel` |
| `conceptSchemes_en.csv` | 20 | `conceptType`, `conceptSchemeUri`, `preferredLabel`, `title`, `status`, `description`, `hasTopConcept` |
| `dictionary_en.csv` | 160 | `filename`, `data header`, `property`, `description` |
| `digCompSkillsCollection_en.csv` | 25 | `conceptType`, `conceptUri`, `preferredLabel`, `status`, `skillType`, `reuseLevel`, `altLabels`, `description`, `broaderConceptUri`, `broaderConceptPT` |
| `digitalSkillsCollection_en.csv` | 1,284 | `conceptType`, `conceptUri`, `preferredLabel`, `status`, `skillType`, `reuseLevel`, `altLabels`, `description`, `broaderConceptUri`, `broaderConceptPT` |
| `greenShareOcc_en.csv` | 3,590 | `conceptType`, `conceptUri`, `code`, `preferredLabel`, `greenShare` |
| `greenSkillsCollection_en.csv` | 629 | `conceptType`, `conceptUri`, `preferredLabel`, `status`, `skillType`, `reuseLevel`, `altLabels`, `description`, `broaderConceptUri`, `broaderConceptPT` |
| `languageSkillsCollection_en.csv` | 359 | `conceptType`, `conceptUri`, `skillType`, `reuseLevel`, `preferredLabel`, `status`, `altLabels`, `description`, `broaderConceptUri`, `broaderConceptPT` |
| `occupationSkillRelations_en.csv` | 126,051 | `occupationUri`, `occupationLabel`, `relationType`, `skillType`, `skillUri`, `skillLabel` |
| `occupations_en.csv` | 3,043 | `conceptType`, `conceptUri`, `iscoGroup`, `preferredLabel`, `altLabels`, `hiddenLabels`, `status`, `modifiedDate`, `regulatedProfessionNote`, `scopeNote`, `definition`, `inScheme`, `description`, `code`, `naceCode` |
| `researchOccupationsCollection_en.csv` | 122 | `conceptType`, `conceptUri`, `preferredLabel`, `status`, `altLabels`, `description`, `broaderConceptUri`, `broaderConceptPT` |
| `researchSkillsCollection_en.csv` | 40 | `conceptType`, `conceptUri`, `preferredLabel`, `status`, `skillType`, `reuseLevel`, `altLabels`, `description`, `broaderConceptUri`, `broaderConceptPT` |
| `skillGroups_en.csv` | 640 | `conceptType`, `conceptUri`, `preferredLabel`, `altLabels`, `hiddenLabels`, `status`, `modifiedDate`, `scopeNote`, `inScheme`, `description`, `code` |
| `skillSkillRelations_en.csv` | 5,818 | `originalSkillUri`, `originalSkillType`, `relationType`, `relatedSkillType`, `relatedSkillUri` |
| `skillsHierarchy_en.csv` | 640 | `Level 0 URI`, `Level 0 preferred term`, `Level 1 URI`, `Level 1 preferred term`, `Level 2 URI`, `Level 2 preferred term`, `Level 3 URI`, `Level 3 preferred term`, `Description`, `Scope note`, `Level 0 code`, `Level 1 code`, `Level 2 code`, `Level 3 code` |
| `skills_en.csv` | 13,960 | `conceptType`, `conceptUri`, `skillType`, `reuseLevel`, `preferredLabel`, `altLabels`, `hiddenLabels`, `status`, `modifiedDate`, `scopeNote`, `definition`, `inScheme`, `description` |
| `transversalSkillsCollection_en.csv` | 95 | `conceptType`, `conceptUri`, `skillType`, `reuseLevel`, `preferredLabel`, `status`, `altLabels`, `description`, `broaderConceptUri`, `broaderConceptPT` |
