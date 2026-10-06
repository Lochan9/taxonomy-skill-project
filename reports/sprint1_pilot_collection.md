# Sprint 1 Pilot Collection Report (Greenhouse)

**Status:** PILOT corpus. This is not the agreed shared corpus. The board list is a proposal
pending Section A agreement (data contract D2). Sprint 1 is **not** complete.
**Date:** 2026-10-06 · **Snapshot:** `20261006T171338Z` · **Fetcher commit:** `dfc411d`
**LLM token usage:** 0 (no LLM calls). **Greenhouse API key:** none used (public GET endpoint).

## 1. Pilot employers and token verification

Each board token was found in the HTML of the company's own careers page. None were guessed,
and no documentation example companies were used.

| board_token | Company | Industry (pilot label) | Verification URL | Evidence found on page |
|---|---|---|---|---|
| `duolingo` | Duolingo | Education technology | https://careers.duolingo.com/ | `boards-api.greenhouse.io/v1/boards/duolingo/departments` |
| `robinhood` | Robinhood | Financial services | https://careers.robinhood.com/ | `api.greenhouse.io/v1/boards/robinhood/jobs` |
| `recursionpharmaceuticals` | Recursion Pharmaceuticals | Biotechnology | https://www.recursion.com/careers | `boards.greenhouse.io/embed/job_board/js?for=recursionpharmaceuticals` |
| `oura` | Oura | Consumer health technology | https://ouraring.com/careers | `job-boards.greenhouse.io/oura` |
| `figma` | Figma | Software | https://www.figma.com/careers/ | `boards.greenhouse.io/figma/jobs/<id>` |

- The industry labels were assigned by the team from each company's primary product
  (`industry_source` in `config/boards.yaml`). They need review with Section A.
- Verified alternate, not collected: `reddit` (https://www.redditinc.com/careers).
- Not verified, so not used: several careers pages (e.g. Airbnb, Stripe, Datadog, Lyft)
  render jobs with JavaScript or returned HTTP 403 to a plain request, so no token could be
  confirmed from their HTML. Stripe's page exposes Greenhouse job IDs but no board token.

## 2. Collection run

Command: `.venv/bin/python src/fetch_greenhouse.py`. The default timeout, retry, delay and
caching settings were used. The dry run beforehand planned exactly 5
`GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true` requests.

| Result | Count |
|---|---|
| Fetched | 5 |
| Cached (reused) | 0 (first run) |
| Failed | 0 |
| Zero-job boards | 0 |

## 3. Snapshot contents (read-only inspection)

| Board | Postings | `meta.total` | Missing/null `content` | Empty after HTML strip | Description words (min / median / max) | Sample titles |
|---|---|---|---|---|---|---|
| duolingo | 60 | 60 | 0 | 0 | 507 / 740 / 1009 | Ad Sales Lead, Programmatic · Ad Sales Lead - West |
| robinhood | 159 | 159 | 0 | 0 | 582 / 909 / 1377 | Android Engineer, Government Products · Android Engineer, Money Experience |
| recursionpharmaceuticals | 12 | 12 | 0 | 0 | 740 / 1208 / 1451 | Associate Director, Computational Biology – Early Discovery · Don't see what you're looking for? |
| oura | 80 | 80 | 0 | 0 | 695 / 1047 / 1676 | Accounting Manager, Fixed Assets & Capital Accounting · Compliance Engineer |
| figma | 159 | 159 | 0 | 0 | 630 / 970 / 1297 | Account Executive, Enterprise · Account Executive, Enterprise (Bengaluru, India) |
| **Total** | **470** | | **0** | **0** | | |

Word counts come from a rough pass: HTML entities unescaped, tags stripped, whitespace
split. Counts are of the whole description text. This was an inspection only; no cleaned
text was stored.

## 4. Integrity checks

- All 5 files match the manifest SHA-256 and byte size.
- `job_count` in the manifest equals `len(jobs)` and `meta.total` for every board.
- No duplicate job `id`s within any board.
- The raw files were hashed before and after inspection, and all were unchanged (`shasum -c`: 5/5 OK).

## 5. Observations for the exploration notebook

- **Placeholder posting:** Recursion has a "Don't see what you're looking for?" entry, which
  appears to be a general-interest posting rather than a specific job. A filtering rule is
  needed before extraction. No other board had a title matching the same placeholder pattern.
- **Repeated titles:** Robinhood has 10 and Duolingo 3 title repeats within the board, and
  Recursion has 1. Figma lists the same role in different locations under distinct titles,
  e.g. "(Bengaluru, India)". This matters for the duplicate-rate statistic.
- **Language:** every posting has Greenhouse's `language` field set to `en`. This field is
  set by the employer, not detected from the text. Run actual language detection before
  reporting the language mix.
- **Available fields:** `id`, `internal_job_id`, `title`, `content`, `location`,
  `departments`, `offices`, `metadata`, `updated_at`, `first_published`, `company_name`,
  `language`, `absolute_url`, `requisition_id`, `application_deadline`, plus AI-disclaimer and
  data-compliance fields. `education` is present for Duolingo, Robinhood and Figma only.
  There is no industry or seniority field, as expected.
- **Skew:** two boards (Robinhood and Figma) account for 318 of the 470 postings, and the
  pilot is weighted towards technology companies. A broader, agreed board list is needed for
  the real corpus.

## 6. Storage

- Raw files: `data/raw/greenhouse/20261006T171338Z/{board_token}.json` (5 files, 5,652,963 bytes).
  They are git-ignored and exist only locally.
- Manifest: `data/raw_manifest.csv` (tracked in Git, not yet committed).
- **Not uploaded or shared yet.** The shared storage location is still pending (contract D8).

## 7. Not done (out of scope for this step)

Cleaning, database loading, skill extraction, the exploration notebook, Section A agreement.
