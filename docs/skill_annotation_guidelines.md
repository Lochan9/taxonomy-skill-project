# Skill Annotation Guidelines (Team B, Sprint 2), v0.2.1 DRAFT

**Purpose:** humans label the skill statements in the 100-posting set
(`data/annotation/sprint2_v1/`), so that Sprint 2 extraction can be measured with precision
and recall (brief p.3).
**Status:** draft for the team's calibration round on the 20 development postings. Revise
it, bump the version, and record the changes below *before* annotating the evaluation
postings.
**Labels are human-made.** No LLM fills in, suggests or pre-labels gold annotations.

## 1. What to annotate

An **atomic skill statement** is **one ability or one knowledge item** that the posting's
own text says the role needs, or would value. Record it as a short normalised phrase
(`skill_statement`), linked to the exact text that supports it (`evidence_text` plus
offsets). The posting does not have to use a skill noun: an ability stated as an action
("Build prototypes") is recorded in its noun form (*prototyping*), as long as the
normalisation is faithful (§3a).

| Kind (`skill_category`, optional) | Examples |
|---|---|
| `technical`: methods and techniques | algorithms, system design, multithreaded programming, A/B testing |
| `tool`: named software, languages, platforms, equipment | Python, Go, Kafka, Postgres, Kubernetes, Solidworks |
| `domain_knowledge`: knowledge of a field, regulation or market | iOS application development, securities regulation, clinical pharmacology |
| `transferable`: skills that carry across roles | communication, collaboration, stakeholder management |

Leave `skill_category` empty when unsure. It is optional and not used to score extraction.

## 2. What is *not* a skill statement

| Not a skill | Example (pilot) | Why |
|---|---|---|
| **Task-only statement** | "Own sales activity"; "Work to develop and circulate best practices in a collaboration first environment" | Describes work to be done or the workplace, and states no ability, method, tool or knowledge area. Do not invent the skill it implies. **A duty that does state one is annotated, even as a verb phrase** ("Build a lot of prototypes" → *prototyping*, §3a) |
| **Qualification** (degree, certificate, licence) | "A Bachelor's degree in Computer Science or a related technical field" | A credential, not an ability. Do not turn it into "computer science" |
| **Experience as tenure or setting** | "2+ years of experience in software development"; "Experience working at a fintech company or financial institution" | Duration and employer type are not skills. Annotate the capability inside an experience phrase only if one is named ("Experience with multithreaded programming" → *multithreaded programming*) |
| **Benefits / perks** | "401(k) matching" | Employer offering |
| **Employer description / values / mission** | "At Figma, one of our values is Grow as you go." | Describes the company, not the role's needs |
| **EEO, accommodation, privacy, application text** | equal-opportunity statements | Boilerplate (see `docs/extraction_input_policy.md`) |
| **Personality without an ability** | "passionate", "curious" on its own | Not an ability. Discuss if worded as one ("curiosity to learn new tools") |

For "2+ years of experience in software development", the guideline is: **no annotation**
by default. Discuss it in calibration if the team wants to capture "software development"
as a broad skill.

## 3. Splitting and context

1. **One skill per record.** Split coordinated lists into separate records.
   - "Proficiency in Go or Python" gives two records: *Go programming* and *Python
     programming*. They are **alternatives**, so both get the same `alternative_group_id`
     (§3b).
   - "Knowledge of additional languages such as C++ or Go" gives *C++* and *Go*, but this
     is an **illustrative list**, not an alternative set: no group by default (§3b).
   - "Strong collaboration and communication skills" gives *collaboration* and
     *communication*. These are joined by "and", so both are needed and there is **no**
     group.
2. **Keep the context the skill needs, and nothing more.** "Kafka or similar data
   streaming technologies" gives *Kafka* and *data streaming technologies*, recorded as
   alternatives (§3b). "Strong technical knowledge of iOS mobile application development"
   gives *iOS application development*, not "strong technical knowledge".
3. **Do not merge separate skills** into one statement ("Python and SQL"), and do not split
   a single compound term ("machine learning", "Cocoa Touch", "3D CAD").
4. Proficiency words ("strong", "familiarity with", "hands-on") are **not** part of the
   statement. Mention them in `review_notes` only if they matter.

## 3a. Skills inside responsibilities (duties)

There is **no blanket exclusion of duties.** Responsibilities sections often state the
ability or knowledge a role needs.
- **Annotate** any ability, method, tool or knowledge area that a duty **explicitly
  expresses**. For "Analyse data using SQL", record *SQL*, and *data analysis* if the team
  treats it as a skill (see the calibration note below).
- **Do not annotate** the task itself, and **do not infer** a skill the duty only implies.

**Explicit actions can state skills.** A posting does not need a skill noun. When a verb
phrase itself states an ability, record that ability in noun form:
"Build a lot of prototypes" → *prototyping*; "Mentor … junior engineers" → *mentoring*;
"Develop, release, and maintain native Android application features" → *Android
application development*. The same applies in requirements sections ("Ability to
scrappily build prototypes").

A normalisation is **faithful** when all of these hold:
1. **Same concept, posting's own words.** The statement is the verb (plus its object, when
   the object is part of the skill) turned into its usual noun form. Use a synonym only
   when the meaning is identical.
2. **Same breadth.** Do not widen it ("prototyping" → "product development"), narrow it, or
   add a tool, method or domain the text does not name.
3. **Only qualifiers dropped.** Leave out scale, frequency, ownership and target words
   ("a lot of", "monthly", "own", "drive", "exceed targets"), as with proficiency words (§3).
4. **Reproducible.** Another annotator reading only the evidence span would arrive at the
   same skill.

It is **inference, not normalisation**, when the skill comes from what the task would
require rather than from what the words say: "Drive product development with our
manufacturing partners" → *supplier management*; "Manage a 360 deal cycle and exceed
targets" → *negotiation*. Generic verbs with no ability object ("Own sales activity",
"Work to develop and circulate best practices") give no record.

**Evidence for an action:** the shortest span holding the verb and its object ("Build a lot
of prototypes"). If the skill is also named in a requirements section, use that mention
instead (§7).

| Duty text (pilot) | Record(s) | Why |
|---|---|---|
| "Own sales activity and monthly **revenue forecasting** in **Salesforce**" (`greenhouse:figma:5647851004`) | *revenue forecasting* (`technical`), *Salesforce* (`tool`) | The method and the tool are named. "Own sales activity" is task-only: no record |
| "Develop, release, and maintain native **Android application** features in **Kotlin**" (`greenhouse:duolingo:8628658002`) | *Kotlin* (`tool`), *Android application development* (`technical`) | The language is named, and the verb phrase states the ability (faithful normalisation) |
| "**Mentor** and set technical direction for junior engineers" (same posting) | *mentoring* (`transferable`) | Explicit action. "set technical direction" is borderline (§9) |
| "**Build a lot of prototypes**, break them, and iterate quickly." (`greenhouse:oura:4203623009`) | *prototyping* (`technical`) | Explicit action. The posting also lists "Prototyping" under its requirements, so the record points there (§7) |
| "**Mechanical design** and development of cutting-edge wearable and other consumer devices" (same posting) | *mechanical design* (`technical`) | Named method |
| "Drive product development with our manufacturing partners in Asia, North America, and Europe" (same posting) | none by default | "supplier management" or "manufacturing knowledge" would be inferred. Whether *product development* is itself a skill here is borderline (§9) |
| "Manage a 360 deal cycle and exceed targets" (`greenhouse:figma:5647851004`) | none by default | "negotiation" would be inferred. *Full-cycle deal management* as a faithful normalisation is borderline (§9) |
| "Work to develop and circulate best practices in a collaboration first environment" (same posting) | none | Task-only. "collaboration first environment" describes the workplace, not an ability |

- **Requirement value:** a skill named only in responsibilities gets
  `required_or_preferred = unspecified` (§4).
- **Repeated mentions:** if the same skill is also listed under requirements, keep **one**
  record, with the requirement value and evidence of that mention (§7). Salesforce is
  also in Figma's "We'd love to hear from you if you have" list, Kotlin in Duolingo's
  "You have…" list, and Prototyping in Oura's "if you have" list (all `required`).
  Mentoring is also in Duolingo's "Exceptional candidates will have…" list, so it is one
  `preferred` record.
- **Calibration note:** activities sit on a line between ability and task ("revenue
  forecasting" or "build prototypes" vs "outbound prospect", "build a strong pipeline" or
  "drive product development"). Annotate them when the faithful-normalisation test above
  holds, mark `DISCUSS:` when you are unsure, and settle the line in the development round.

## 3b. Alternatives (`alternative_group_id`, optional)

Postings often accept **one of several** skills: "Go or Python", "NX or Solidworks", "Kafka
or similar data streaming technologies". Splitting these into separate records is right,
but the records must not read as "both required".

**Alternatives vs illustrative examples.** Group only when the listed skills **are** the
requirement and any one of them meets it.
- **Alternative requirement** (group): "X or Y", "either X or Y", "X or similar Y", "one of
  X, Y, Z". Example: "Proficiency in Go or Python".
- **Illustrative list** (no group by default): the requirement is a broader category, and
  the named items are examples of it, introduced by "such as", "like", "e.g.", "for
  example" or "including". An "or" or "and" inside the list joins the examples, and does
  not turn them into an alternative set. Example: "Knowledge of additional languages such
  as C++ or Go": the posting values additional languages; C++ and Go only illustrate them.
- **How to record an illustrative list (default until calibration):**
  - Record the **category** if it is itself a skill (*ML libraries* in "familiarity with ML
    libraries like PyTorch, TensorFlow, …"), with the sentence's requirement value. If it
    is too vague to be a skill ("additional languages", "technologies"), do not record it.
  - Record each **named example** as its own record, with **no** `alternative_group_id`
    and the sentence's requirement value, because each is explicitly named.
  - Add `DISCUSS: illustrative list` to `review_notes` of the example records. Calibration
    then decides between keeping the examples as separate records, grouping them with the
    category as alternatives, or keeping the category only. That matters most for
    `required` lists, where separate records overstate what is needed.
- **Unclear wording** (an "or" between two abilities, a parenthesised list without
  "such as", a list of areas): choose one reading and mark `DISCUSS:`. §9 lists the pilot
  cases.

- **How to record:** give every record in the set the **same `alternative_group_id`**, a
  short id unique within the posting such as `alt-1` or `alt-2`. The group means **at least
  one of these** is required (or preferred).
- **Shared requirement value:** all members share one `required_or_preferred`, and the
  validator rejects mixed values.
- **Size and scope:** a group needs **two or more** different skills in **one** posting.
  Leave the field empty for ordinary skills.
- **Never group skills joined by "and"** ("collaboration and communication", "Postgres,
  Kubernetes (K8s), Redis, and AWS"). Each of those is needed.
- **Neighbouring skills stay separate:** a skill next to an alternative set but outside it
  is not grouped. In "3D CAD (NX or Solidworks)", *NX* and *Solidworks* are alternatives,
  but *3D CAD* is a separate skill and is not in the group. (Whether the parenthesis is an
  alternative set or an illustrative list is itself open: `DISCUSS:`, §9.)
- **Unclear cases:** "AWS (or similar cloud platforms)" can be *AWS* alone, or *AWS* +
  *cloud platforms* as alternatives. Choose one and mark `DISCUSS:`.
- **Offsets don't change:** each record keeps its own evidence span.
  `alternative_group_id` adds meaning only.

## 4. Required vs preferred (`required_or_preferred`)

| Value | Use when |
|---|---|
| `required` | Listed under a requirements heading ("You have…", "What you bring", "We'd love to hear from you if you have", "The experience you'll need", "Requirements") or worded as necessary ("must", "required") |
| `preferred` | Listed under "Nice to have", "Bonus points", "Exceptional candidates will have", "While not required, it's an added plus…", or worded "is a plus", "preferred", "ideally" |
| `unspecified` | The posting gives no signal, e.g. a skill named only in a responsibilities section or the role summary |

Judge by the posting's own heading or wording, not by what seems important.

## 5. Evidence spans and offsets

- `evidence_text` is the **shortest contiguous span of `clean_text` that names the skill**.
  It is often just the skill's words ("Python", "Kubernetes (K8s)"), or a longer clause
  when the skill is described rather than named.
- **Offsets:** zero-based Python character positions into the posting's **unchanged
  `clean_text`**, with an **exclusive** end. `clean_text[evidence_start:evidence_end]`
  must equal `evidence_text` exactly, including case, punctuation, curly apostrophes and
  spaces. Do not include leading or trailing whitespace.
- **Getting offsets:** don't count by hand. Run
  `python src/annotations.py locate --db … --posting ID --text "exact phrase" [--occurrence N]`.
  The exported `.txt` files are byte-identical to `clean_text`, so you can copy phrases
  from them directly.
- **Shared evidence:** split records may share or overlap evidence, but each record should
  point at its own words where possible ("Go" and "Python", not the whole clause twice).

## 6. Explicit evidence only (no inference)

- Annotate what the text **states**. Do not add skills you would expect the role to need.
  An iOS role does not imply "Objective-C" unless the posting says so, and "Director of
  Sales" does not imply "negotiation".
- Do not normalise into a different concept. "review processes" is not "code review"
  unless the text says code review.
- Normalising the posting's **own** wording is not inference: an ability stated as an
  action ("Build a lot of prototypes") is recorded as its skill noun (*prototyping*), under
  the faithful-normalisation test in §3a.
- **ESCO** may help you choose clear wording for `skill_statement` ("computer
  programming", "show initiative"). Do **not** force a match to ESCO, and do not record ESCO
  URIs. Mapping comes later.

## 7. Repeated mentions within a posting

- Record **one** record per distinct skill per posting.
- The strongest mention sets the value: `required` over `preferred` over `unspecified`
  (responsibilities only). If a skill appears as both required and preferred, mark it
  `required`.
- Point the evidence at the **first explicit mention** in a section that sets that value.
  For a duty-only skill, use the first mention anywhere.
- Example (Duolingo iOS posting): "Programming experience in Swift" appears under *You
  have…* and "Strong proficiency in Swift" under *Exceptional candidates will have…*. That
  is **one** *Swift* record, `required`, with its evidence at the first mention.

## 8. Vague and borderline cases: discuss, don't guess

- Add a short `review_notes` entry starting with `DISCUSS:`.
- **Annotate it if you think it qualifies.** The second reviewer and adjudicator decide.
- Typical cases:
  - "A product mindset with the ability to tie technical work to user outcomes and
    business impact": a transferable skill or a trait?
  - "Commitment to high standards in code quality and review processes": is "code quality"
    a skill?
  - Values sections (open question 3 in the extraction policy).
  - "Experience working at a fintech company": domain knowledge or tenure? The default is
    tenure, so not a skill.
- Unclear `required_or_preferred` → `unspecified`, plus a note.

## 9. Worked examples from the pilot (not part of the 100-posting set)

All examples come from postings **outside** the annotation set **and outside any group
related to it**, so the guidelines don't leak evaluation postings. Snapshot:
`20261006T171338Z`. The offsets index into `clean_text`.

**Positive**

| Posting | `evidence_text` | start–end | Record(s) | Req/pref |
|---|---|---|---|---|
| `greenhouse:robinhood:7263592` (Software Engineer, Backend) | `Go` / `Python` (from "Proficiency in Go or Python") | 3380–3382 / 3386–3392 | *Go programming*, *Python programming* (tool), **`alternative_group_id = alt-1`** | required ("What you bring") |
| same | `Postgres`, `Kubernetes (K8s)`, `Redis`, `AWS` (from "technologies like …", 3629–3689) | 3647–3655, 3657–3673, 3675–3680, 3686–3689 | four tool records, **no group** (illustrative list joined by "and"; "technologies" is not a skill), each with `DISCUSS: illustrative list` (§3b) | **preferred** ("Bonus points") |
| same | `Kafka` / `similar data streaming technologies` | 3420–3425 / 3429–3464 | *Kafka* (tool), *data streaming technologies* (technical), **`alt-2`** | required |
| `greenhouse:duolingo:8393272002` (Senior iOS Engineer) | `data structures` / `algorithms` / `software design` | 2168–2183 / 2185–2195 / 2201–2216 | three technical records | required ("You have…") |
| same | `multithreaded programming` | 2598–2623 | *multithreaded programming* | **preferred** ("Exceptional candidates will have…") |
| same | `Programming experience in Swift` | 2219–2250 | *Swift* (one record; also mentioned at 2293–2320, see §7) | required |
| `greenhouse:figma:5551532004` (Software Engineer – ML) | `collaboration` / `communication skills` | 3255–3268 / 3273–3293 | *collaboration*, *communication* (transferable) | preferred ("While not required…") |
| same | `C++` / `Go` (from "additional languages such as C++ or Go", 3081–3119) | 3110–3113 / 3117–3119 | *C++*, *Go* (tool), **no group**: an illustrative list, not an alternative set. "additional languages" is too vague to record. Both get `DISCUSS: illustrative list` (§3b) | preferred ("is a plus, but not required") |
| same | `ML libraries` / `PyTorch` / `TensorFlow` / `Scikit-learn` / `Spark MLlib` / `XGBoost` (from "ML libraries like …", 2443–2519) | 2443–2455 / 2461–2468 / 2470–2480 / 2482–2494 / 2496–2507 / 2512–2519 | *ML libraries* (category, tool); five library records, **no group**, each with `DISCUSS: illustrative list` (a `required` list, so separate records may overstate it) | required ("We'd love to hear from you If you have") |
| `greenhouse:oura:4203623009` (Senior Product Design Engineer) | `3D CAD` / `NX` / `Solidworks` | 1523–1529 / 1531–1533 / 1537–1547 | *3D CAD modelling* (no group); *NX*, *Solidworks* **`alt-1`** (`DISCUSS:` alternative or illustrative, see borderline) | required |
| `greenhouse:figma:5647851004` (Account Executive, SMB, London) | `revenue forecasting` (duty) | 1349–1368 | *revenue forecasting* (technical) | unspecified (responsibilities only) |
| same | `Salesforce` (duty at 1372–1382, requirement at 1785–1795) | **1785–1795** | *Salesforce* (tool). One record, at the requirements mention (§3a, §7) | required |
| `greenhouse:duolingo:8628658002` (Senior/Software Engineer II, Android) | `Kotlin` (duty at 1870–1876, requirement at 2062–2068) | **2062–2068** | *Kotlin* (tool). One record, at the requirements mention | required |
| same | `Develop, release, and maintain native Android application features` (duty) | 1800–1866 | *Android application development* (technical): explicit action, faithfully normalised (§3a). See the borderline note on "Kotlin on Android" | unspecified |
| same | `mentor others` (duty "Mentor" at 1879–1885, preferred mention at 2363–2376) | **2363–2376** | *mentoring* (transferable): explicit action. One record, at the preferred mention (§7) | **preferred** ("Exceptional candidates will have…") |
| `greenhouse:oura:4203623009` | `Prototyping` (duty "Build a lot of prototypes" at 1112–1137, requirement at 1683–1694) | **1683–1694** | *prototyping* (technical): stated as an action in the duty and as an ability in the requirements. One record (§3a, §7) | required ("We would love to consider you for this role, if you have") |
| same | `Mechanical design` (duty) | 877–894 | *mechanical design* (technical) | unspecified |

"collaboration" occurs **twice** in the Figma posting. The record uses the second
occurrence, the one in the qualifications list: `locate … --text "collaboration" --occurrence 2`.

**Negative (no record)**

| Posting | Text (start–end) | Reason |
|---|---|---|
| `greenhouse:robinhood:7263592` | "2+ years of experience in software development" (3021–3067) | tenure (§2) |
| same | "Experience working at a fintech company or financial institution" (3545–3609) | employer setting (§2) |
| same | "401(k) matching" (3895–3910) | benefit |
| `greenhouse:duolingo:8393272002` | "A Bachelor’s degree in Computer Science or a related technical field" (2030–2098) | qualification |
| `greenhouse:figma:5551532004` | "At Figma, one of our values is Grow as you go." (3371–3417) | employer values |
| `greenhouse:figma:5647851004` | "Own sales activity" (1318–1336) | task-only: a generic verb with no ability object (§3a) |
| same | "Work to develop and circulate best practices in a collaboration first environment" (1385–1466) | task-only; "collaboration first environment" describes the workplace, so no *collaboration* record |
| same | "exceed targets" (in 1273–1315) and "negotiation" | outcome, not ability; "negotiation" would be inferred |
| `greenhouse:oura:4203623009` | "supplier management" / "manufacturing knowledge" from "Drive product development with our manufacturing partners…" (1017–1109) | inferred from the task, not stated |

**Borderline (annotate if convinced, and add `DISCUSS:`)**

| Posting | Text (start–end) | Question |
|---|---|---|
| `greenhouse:figma:5551532004` | "A product mindset with the ability to tie technical work to user outcomes and business impact" (3151–3244) | Transferable skill (*linking technical work to business outcomes*) or a trait? |
| `greenhouse:robinhood:7263592` | "Commitment to high standards in code quality and review processes" (3188–3253) | Is *code quality* a skill here, or an attitude? |
| `greenhouse:figma:5647851004` | "outbound prospect" (1225–1242, in "outbound prospect and build a strong pipeline") | Is *outbound prospecting* a named sales skill or a task? (§3a calibration note) |
| `greenhouse:robinhood:7263592` | "AWS (or similar cloud platforms)" (3686–3718) | *AWS* alone, or *AWS* / *cloud platforms* as alternatives? (§3b) |
| `greenhouse:figma:5647851004` | "build a strong pipeline" (1247–1270) | *pipeline building*: faithful normalisation of a sales ability, or a task? (§3a) |
| same | "Manage a 360 deal cycle" (1273–1296) | *full-cycle deal management*: faithful normalisation, or task-only? (§3a) |
| `greenhouse:oura:4203623009` | "Drive product development with our manufacturing partners in Asia, North America, and Europe" (1017–1109; "product development" at 1023–1042) | Is *product development* a skill here, or the scope of the job? (§3a) |
| same | "break them, and iterate quickly" (1139–1170) | Part of prototyping, or separate (*prototype testing*, *rapid iteration*)? Default: no extra record (§3a) |
| same | "3D CAD (NX or Solidworks)" (1523–1548) | Alternative set (the default, `alt-1`) or an illustrative list of CAD tools? (§3b) |
| `greenhouse:duolingo:8628658002` | "set technical direction" (1890–1913) | *setting technical direction* is faithful; *technical leadership* would be a different wording. Record or not? (§3a) |
| same | "Kotlin on Android" (2062–2079, under "You have…") | Does it make *Android application development* `required`, or only *Kotlin*? (§3a, §7) |
| `greenhouse:figma:5551532004` | "mentoring or leading others" (2662–2689, required) | Alternatives (`alt-n`: *mentoring* / *leadership*) or two separately valued abilities? (§3b) |
| same | "search relevance, ranking, NLP, or RAG systems" (2838–2884, preferred) | A set of alternative areas (group) or four separately valued areas? (§3b) |

## 10. Workflow: how labels are added, reviewed and finalised

1. **Setup (once per person):**
   - Make sure the DB exists, then run `python src/annotations.py export --db data/processed/taxonomy_pilot.sqlite`.
     This writes git-ignored texts and empty templates.
   - Each annotator runs `python src/annotations.py init --annotator <id>`. That creates
     `data/annotation/sprint2_v1/annotators/<id>/` with `postings_review.csv` and
     `skills.csv`.
2. **Annotate, one posting at a time:**
   - Set `review_status` to `in_progress` and add `skills.csv` rows.
   - When done, set it to `reviewed`, filling in `annotator_id` and `reviewed_at`
     (YYYY-MM-DD).
   - **A posting with no skills** is still marked `reviewed`, with zero skill rows and a
     note such as "no skills stated". That keeps it distinguishable from unfinished
     postings.
   - `annotation_id` must be unique per file. The suggested format is `<annotator>-0001`.
   - `alternative_group_id` is optional: fill it only for "X or Y" alternative sets (§3b).
3. **Validate often:**
   `python src/annotations.py validate --db … --dir data/annotation/sprint2_v1/annotators/<id>`.
   It reports every problem with file, line and field (e.g. mismatched offsets, with the
   correct offset suggested).
4. **Calibrate on the 20 development postings first.**
   - At least two people annotate them independently.
   - `python src/annotations.py compare --db … --a <id1> --b <id2>` lists exact, overlapping
     and one-sided spans, and requirement disagreements.
   - Discuss every disagreement, update these guidelines (bump the version), and only then
     start the evaluation postings.
5. **Second review (recommended where capacity allows):** a second annotator independently
   labels the evaluation postings, or at least a sample (≥ 20), and agreement is reported
   with `compare`.
6. **Adjudication:**
   - A third person, or both annotators together, resolve each disagreement into
     `data/annotation/sprint2_v1/adjudicated/` (same two files).
   - Record the decision in `review_notes`, and keep both annotators' original files
     unchanged.
7. **Finalise:** `validate --dir …/adjudicated --final` must pass. That requires all 100
   postings `reviewed` and no problems. Only then is the set called gold. Commit the
   annotator and adjudicated CSVs; the exported texts stay git-ignored.

### Changelog
- v0.2.1 (2026-10-06): explicit actions can state skills. A faithful normalisation of an
  ability stated as a verb phrase is annotated ("Build a lot of prototypes" →
  *prototyping*), with a four-point test and inference counter-examples (§1, §2, §3a, §6).
  Re-reviewed every duty example: *prototyping*, *mentoring*, *Android application
  development* and *mechanical design* added; "Manage a 360 deal cycle" and "Drive product
  development…" moved to borderline. §7 now says the strongest mention sets the value and
  the evidence. Distinguished alternative requirements from illustrative lists ("such as",
  "like", "e.g.", "including"): illustrative examples are not grouped by default and get
  `DISCUSS: illustrative list` (§3b). The Figma C++/Go example is no longer an alternative
  group; ML libraries and the Robinhood "technologies like…" list follow the same rule.
  New borderline cases: "mentoring or leading others", "search relevance, ranking, NLP, or
  RAG systems", "3D CAD (NX or Solidworks)", "Kotlin on Android", and others.
- v0.2 (2026-10-06): removed the blanket exclusion of duties. Skills explicitly expressed
  in responsibilities are annotated, and task-only statements are not (§2, §3a). Added the
  optional `alternative_group_id` for "X or Y" alternatives (§3b), and updated the
  examples.
- v0.1 (2026-10-06): first draft, before calibration.
