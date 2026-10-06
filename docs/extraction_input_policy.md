# Extraction Input Policy (PROPOSED, Team B / Section B)

**Status:** Proposal for Team B review. It is **not implemented**: no extraction input has been
built and no text has been removed. Policies that affect the shared corpus (P1, P3, P4)
also need Section A's agreement, because both sections extract from the same postings
(brief p.2).
**Applies to:** Sprint 2 skill-statement extraction, starting from the pilot snapshot
`20261006T171338Z` and later from the agreed corpus.
**Evidence base:** the pilot exploration (`reports/sprint1_exploration.md`) and a read-only
survey of the cleaned text of the 468 usable postings (§4).

## 1. Layers (nothing is ever overwritten)

| Layer | What it is | Mutable? |
|---|---|---|
| Raw snapshot | `data/raw/greenhouse/{snapshot_id}/*.json` | Never |
| `postings` table | All 470 rows, including `raw_text` and `clean_text`, keyed by (`snapshot_id`, `posting_id`) | Never (insert-only) |
| `usable_postings` view | Rows with an empty `exclusion_reason` (468 in the pilot) | Derived |
| **Extraction input** (proposed) | One record per posting selected for extraction, holding a *copy* of `clean_text` with clearly identified boilerplate removed, plus a log of what was removed | Derived, versioned, separate from `postings` |

## 2. Policies

**P1. Keep every original posting for audit.** All 470 postings stay in `postings` with
their `raw_text`, `clean_text` and flags. Exclusion is expressed by flags and views, never
by deleting rows. Extraction results must be traceable to (`snapshot_id`, `posting_id`).

**P2. Exclude the two flagged placeholders from extraction.**
`greenhouse:recursionpharmaceuticals:3955652` ("Don't see what you're looking for?") and
`greenhouse:recursionpharmaceuticals:7540026` ("Interested in an internship?") are
general-interest or talent-pool postings, not specific roles. They stay in `postings`
(P1). The extraction input starts from `usable_postings`, which leaves 468 postings.

**P3. Near-duplicate pairs are review candidates, not exclusions.** The 30 candidate pairs
in `reports/sprint1_near_duplicate_candidates_20261006T171338Z.csv` (9 at ≥ 0.99
similarity) are **not** removed automatically. The pilot shows why:
- Some high-similarity pairs are the same role in different locations.
- Some shared-requisition pairs are different teams (similarity 0.83–0.90).
- Some same-title pairs are different roles (< 0.60).
- One requisition is posted under two titles ("Ad Sales Lead - West" / "Director of Ad
  Sales - West").

Reviewers record a decision per pair (`same_role_location_variant`, `same_role_retitled`,
`different_role`, `unsure`) with a short note. The candidate detection is incomplete (it
misses, for example, Figma's location-suffixed titles), so review results must not be read
as a complete duplicate list.

**P4. Keep location variants traceable: posting counts vs distinct-role counts.** Every
posting stays in the extraction input, including location variants, so the extracted
statements stay linked to each posting. Reviewed pairs marked as the same role are joined
into a **role group** (`role_group_id`). Postings that are not reviewed or not merged form
their own group. Later skill frequencies are reported **both ways**:
- **Posting-level:** how many postings mention the skill. This reflects hiring volume and
  is inflated by multi-location reposts.
- **Role-level:** how many distinct role groups mention the skill. This is robust to
  reposts.

Every report must state which count it uses. Role grouping is a separate, versioned derived
table; it never alters `postings`.

**P5. Preserve `clean_text`. Remove boilerplate only in the separate extraction input.**
`clean_text` is never edited. The extraction input may drop **only clearly identified**
sections or paragraphs of these three kinds:

| Category | Examples seen in the pilot | Identification (proposed) |
|---|---|---|
| Benefits / perks | "What we offer" (Robinhood 156/159, Oura 74/80); benefits text in 466/468 | A section that starts at a known benefits heading and ends at the next heading |
| Application instructions / accommodations | "Examples of accommodations include but are not limited to" (Figma 159/159); accommodation-request text (Figma, Oura) | Known heading or paragraph patterns |
| Equal-opportunity / non-discrimination statements | Present in 468/468 usable postings | Paragraph-level patterns ("equal opportunity", "without regard to …", "protected veteran …") |

**P6. Preserve responsibilities, qualifications and skill-bearing text.**
- **Never removed:** sections such as "What you'll do", "What you bring", "We'd love to
  hear from you if you have", "In this role you will", "The experience you'll need",
  "Nice to have", and "About the team / role".
- **Conservative default:** if a paragraph mixes boilerplate with role content, or its
  category is unclear, **keep it**. Removing a skill-bearing sentence is worse than
  keeping a boilerplate one, because extraction quality and P/R evaluation can absorb
  noise better than lost recall.

**P7. Every removal is logged and measurable.** For each posting the extraction input
records:
- removed spans (category, matched rule, character offsets into `clean_text`, and a hash of
  the removed text)
- `retained_char_share`
- an `extraction_input_version`

A QA report shows retention per employer and a manual review of at least 20 postings
(4 per employer), checking that no responsibilities or qualifications were removed. Rules
live in config (like `config/seniority_rules.yaml`), not in code.

## 3. Open questions (need a team decision before implementation)

1. **Pay-transparency / compensation sections:**
   - **Where:** "Pay transparency disclosure" and "Annual base salary range" (Figma),
     "Salary range" (Duolingo), "Base pay range" and zone lists (Robinhood).
   - **Status:** not skill-bearing, but **not in the P5 removal list**.
   - **Proposal:** keep them in the input for now, and decide after the first extraction
     run shows whether they produce false skills.
2. **Recruiting notices:**
   - **Where:** Oura's "Disclaimer: beware of fake job offers" (80/80), and candidate
     privacy notices (Duolingo, Figma, Recursion, Robinhood).
   - **Proposal:** treat them as application instructions (removable) once reviewed.
3. **Company values / mission sections:**
   - **Where:** for example, Recursion's "The values we hope you share" (10/10).
   - **Status:** they may carry soft skills ("act boldly with integrity"), so they are
     **kept** by P6's default until the annotation guidelines say whether values count as
     skills.
4. **Who reviews near-duplicate candidates:** whether review is shared with Section A, so
   both sections use the same role groups (P4).

## 4. Pilot evidence (read-only survey, usable rows, n = 468)

| Pattern | Duolingo (60) | Figma (159) | Oura (80) | Recursion (10) | Robinhood (159) |
|---|---|---|---|---|---|
| Equal-opportunity language | 60 | 159 | 80 | 10 | 159 |
| Benefits language | 60 | 159 | 80 | 9 | 158 |
| Accommodation / application text | 0 | 159 | 80 | 0 | 0 |
| Salary / pay range | 58 | 99 | 68 | 9 | 112 |
| Candidate privacy notice | 60 | 159 | 0 | 10 | 159 |

These counts come from simple regular expressions, so they show the scale of the
boilerplate, not exact section boundaries. The real rules need their own precision check
(P7).
