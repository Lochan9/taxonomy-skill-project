# ai_draft workspace: provenance and review list

**What this is:** draft skill records for all 20 development postings. The suggestions were ChatGPT-assisted (supplied by the team). Claude Code checked each one against the posting's unchanged `clean_text`, located the evidence, computed the offsets, and accepted, merged or rejected it under guidelines v0.2.2. No LLM API was called by the pipeline.

**What this is not:** hand-labelled data, human-reviewed data or gold annotations. Every skill row's `review_notes` starts with `AI-DRAFT:`. Do not copy this folder into `adjudicated/`, and do not use it as an annotator in `compare` for agreement figures.

**Review status:** all 20 development postings are `in_progress`, which means *unfinished draft work*, not human approval. `annotator_id` and `reviewed_at` are empty on every posting row, and no posting is `reviewed`. The 80 evaluation postings are `not_started` and untouched.

**Merge policy (atomicity review):** related concepts are kept as separate records. Two suggestions are merged only when they name the same ability, e.g. one ability with two audiences ("influencing executives and boards") or two wordings of one concept ("deploy ML algorithms" = "getting ML models into production").

| # | posting_id | title | rows | R | P | U | alt groups | DISCUSS rows |
|---|---|---|---|---|---|---|---|---|
| 1 | `greenhouse:duolingo:8675713002` | Senior Product Designer | 15 | 5 | 5 | 5 | 0 | 8 |
| 2 | `greenhouse:duolingo:8722385002` | Senior Learning Designer, Indian Languages | 34 | 25 | 4 | 5 | 0 | 12 |
| 3 | `greenhouse:duolingo:8810661002` | Senior Creative, Social | 18 | 14 | 0 | 4 | 0 | 7 |
| 4 | `greenhouse:duolingo:8863967002` | Illustrator, Intern | 5 | 3 | 0 | 2 | 0 | 4 |
| 5 | `greenhouse:figma:6013304004` | Data Scientist, Finance | 29 | 5 | 16 | 8 | 3 | 17 |
| 6 | `greenhouse:oura:4386217009` | Senior Software Test Engineer | 45 | 25 | 6 | 14 | 1 | 18 |
| 7 | `greenhouse:oura:4156667009` | Senior Director, Corporate Strategy | 20 | 11 | 2 | 7 | 1 | 2 |
| 8 | `greenhouse:figma:6191697004` | Manager, Recruiting - Sales | 13 | 8 | 1 | 4 | 0 | 3 |
| 9 | `greenhouse:figma:6152695004` | Software Engineer Intern (London, United Kingdom) (Summer 2027) | 23 | 19 | 0 | 4 | 0 | 11 |
| 10 | `greenhouse:figma:6131079004` | Brand Designer,  Product Launches | 15 | 9 | 5 | 1 | 1 | 6 |
| 11 | `greenhouse:figma:6112135004` | Director, Marketing - Figma Weave (New York, United States) | 12 | 8 | 2 | 2 | 0 | 6 |
| 12 | `greenhouse:robinhood:8175213` | Engineering Manager, International | 18 | 14 | 0 | 4 | 0 | 6 |
| 13 | `greenhouse:robinhood:4738660` | Senior Software Engineer, Data Engineering | 17 | 12 | 0 | 5 | 0 | 7 |
| 14 | `greenhouse:oura:4419167009` | Senior ML Algorithm Scientist | 25 | 15 | 0 | 10 | 0 | 12 |
| 15 | `greenhouse:oura:4409462009` | Director, Product Design Operations | 22 | 18 | 0 | 4 | 0 | 5 |
| 16 | `greenhouse:recursionpharmaceuticals:8049037` | Executive Director, Corporate Strategy & Intelligence | 25 | 21 | 2 | 2 | 0 | 7 |
| 17 | `greenhouse:oura:4429661009` | Staff AI Data Transformation Architect | 50 | 23 | 21 | 6 | 2 | 13 |
| 18 | `greenhouse:robinhood:8197614` | People Partner Intern (Summer 2027) | 11 | 4 | 2 | 5 | 0 | 0 |
| 19 | `greenhouse:robinhood:8202146` | Internal Audit Senior Associate | 33 | 17 | 0 | 16 | 0 | 12 |
| 20 | `greenhouse:recursionpharmaceuticals:8188707` | Senior AI Researcher | 7 | 5 | 2 | 0 | 0 | 0 |
| | **total** | | **437** | 261 | 68 | 108 | 8 | 156 |

## 1. Senior Product Designer (`greenhouse:duolingo:8675713002`)
- **Unresolved (no record):**
  - 'Experience shipping products at scale in a product organization' (R): experience/setting by default (§2); no record
  - 'A big appetite for feedback' (R): receptiveness to feedback – trait or skill? no record
  - 'The desire to make decisions fast' (P): a desire/trait; no record

## 2. Senior Learning Designer, Indian Languages (`greenhouse:duolingo:8722385002`)
- Posting note: DISCUSS: Punjabi, Bengali, Urdu, Telugu, Tamil, Kannada are contextual/illustrative mentions; no records
- **Unresolved (no record):**
  - Six Hindi linguistic-knowledge records (grammar … learner challenges): too granular?

## 3. Senior Creative, Social (`greenhouse:duolingo:8810661002`)
- Posting note: DISCUSS: experiential activations, earned-media stunts, OOH etc. are examples of idea formats; platform names (TikTok …) are not tool skills
- **Added (guideline-driven):**
  - 'short-form video' (required): category of the 'including' list (§3b)

## 4. Illustrator, Intern (`greenhouse:duolingo:8863967002`)
- Posting note: Degree, portfolio, GPA, availability and Duolingo streak are not skill statements (§2)

## 5. Data Scientist, Finance (`greenhouse:figma:6013304004`)

## 6. Senior Software Test Engineer (`greenhouse:oura:4386217009`)
- **Added (guideline-driven):**
  - 'CI/CD tools' (required): category of the 'such as' list (§3b)
  - 'validating wireless communication technologies' (required): explicit in 'What you'll bring'; first sentence of the bullet has no 'plus' wording

## 7. Senior Director, Corporate Strategy (`greenhouse:oura:4156667009`)
- Posting note: The business-model qualification is repeated verbatim; one record each, at the first R mention
- **Merged:**
  - R:Influencing executives + R:Influencing boards -> 'influencing executives and boards'

## 8. Manager, Recruiting - Sales (`greenhouse:figma:6191697004`)

## 9. Software Engineer Intern (London, United Kingdom) (Summer 2027) (`greenhouse:figma:6152695004`)
- Posting note: Engineering-interest areas (Product, Platform, Security, Open) are placement preferences, not qualifications
- **Added (guideline-driven):**
  - 'programming in a general-purpose language' (required): category of the 'e.g.' list (§3b): the actual requirement
  - 'computer science fundamentals' (required): category of the 'like' list (§3b)
  - 'AI-assisted development tools' (required): category of the 'e.g.' list (§3b)

## 10. Brand Designer,  Product Launches (`greenhouse:figma:6131079004`)
- Posting note: Project formats (launch films, explainer videos, walkthroughs) are not recorded as production skills

## 11. Director, Marketing - Figma Weave (New York, United States) (`greenhouse:figma:6112135004`)
- **Status differs from suggestion:**
  - R:Marketing strategy -> unspecified

## 12. Engineering Manager, International (`greenhouse:robinhood:8175213`)
- Posting note: 'Leadership expectations' section is generic leader expectations; not used as evidence

## 13. Senior Software Engineer, Data Engineering (`greenhouse:robinhood:4738660`)
- **Added (guideline-driven):**
  - 'open-source data processing frameworks' (required): category of the '(Spark, Flink, etc)' list (§3b)

## 14. Senior ML Algorithm Scientist (`greenhouse:oura:4419167009`)
- **Merged:**
  - R:Productionising ML models + U:Deploying ML algorithms -> 'productionising ML models'
- **Status differs from suggestion:**
  - U:Deploying ML algorithms -> required

## 15. Director, Product Design Operations (`greenhouse:oura:4409462009`)

## 16. Executive Director, Corporate Strategy & Intelligence (`greenhouse:recursionpharmaceuticals:8049037`)
- Posting note: Company values section excluded (extraction policy open question 3)
- **Rejected:**
  - U:Synthesising intelligence from multiple sources: the duty says the person grows/refines an intelligence system that synthesizes signals; the person's own synthesis is inferred (§3a)
- **Unresolved (no record):**
  - 'therapeutic area dynamics' is a fourth example in the drug-development 'including' list; not suggested, not recorded
  - 'Grow and refine a real-time intelligence system' – record 'intelligence system development' (U) instead of the rejected label?

## 17. Staff AI Data Transformation Architect (`greenhouse:oura:4429661009`)
- Posting note: Certifications (Databricks Certified …) are qualifications, not skill records
- **Status differs from suggestion:**
  - U:Designing vector-based data architectures -> preferred
  - U:Designing RAG patterns -> preferred
- **Added (guideline-driven):**
  - 'Databricks Lakehouse Federation' (preferred): named alternative in 'X or Y' (keeps the true alternative)
  - 'scripting' (preferred): named alternative in 'X or Y' (keeps the true alternative)
- **Unresolved (no record):**
  - 'MLflow, Feature Store, or Databricks Model Serving' (P): an 'or' list; only MLflow suggested – group or not?

## 18. People Partner Intern (Summer 2027) (`greenhouse:robinhood:8197614`)
- Posting note: 'Organized and detail-oriented' are attributes (no record); 'Google Suite' not split into apps
- **Unresolved (no record):**
  - 'Organized and detail-oriented': attribute or skill? (§2 personality without an ability)

## 19. Internal Audit Senior Associate (`greenhouse:robinhood:8202146`)
- Posting note: Degree, auditor certifications and industry experience are not skill records; MAS is a regulator, not recorded
- **Unresolved (no record):**
  - 'including exposure to Operations, Risk Management, Compliance, or IT/Information Security' (R): exposure areas within auditing – record as domain knowledge (alternatives)? not recorded

## 20. Senior AI Researcher (`greenhouse:recursionpharmaceuticals:8188707`)
- Posting note: DISCUSS: 'PhD in ML, NLP, computer vision, or the equivalent practical experience' is an academic qualification (§2); no ML/NLP/CV skill records | Company values section excluded; 'willingness to learn a must' is an attitude (no record)
- **Unresolved (no record):**
  - 'PhD in ML, NLP, computer vision, or the equivalent practical experience': academic qualification (§2), not recorded; does 'or the equivalent practical experience' make ML/NLP/CV skills?
  - 'willingness to learn a must' (R wording): attitude, not an ability – no record
