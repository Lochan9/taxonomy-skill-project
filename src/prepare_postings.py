"""Prepare cleaned posting rows from one raw Greenhouse snapshot (Sprint 1).

    python src/prepare_postings.py --snapshot 20261006T171338Z

Reads the raw files listed for that snapshot in data/raw_manifest.csv (verifying their
SHA-256 first), joins board metadata from config/boards.yaml, and writes one row per
posting to:

    data/processed/postings_{snapshot_id}.jsonl   (UTF-8, one JSON object per line)
    data/processed/postings_{snapshot_id}.csv     (UTF-8)
    reports/sprint1_cleaning_quality_{snapshot_id}.md

Raw snapshots are opened read-only and never modified. Flagged rows (missing or empty
description, placeholder postings, exact duplicates) are kept for audit, with
`exclusion_reason` saying why; a row is usable when `exclusion_reason` is empty.

List fields (`departments`, `offices`) are lists of names: native JSON arrays in JSONL and
JSON-encoded arrays in CSV. `source_language` is Greenhouse's employer-set `language` field,
not a detected language.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import html
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

from fetch_greenhouse import (
    MANIFEST_SUBPATH,
    REPO_ROOT,
    Board,
    ConfigError,
    load_config,
    read_manifest,
    verify_cached_file,
)

SOURCE_NAME = "greenhouse"
# Bump when cleaning rules change in a way that alters clean_text, hashes or flags.
CLEANING_VERSION = "0.1.0"

OUTPUT_FIELDS = [
    "posting_id",
    "source",
    "source_job_id",
    "internal_job_id",
    "board_token",
    "company_name",
    "source_company_name",
    "title",
    "location",
    "departments",
    "offices",
    "raw_text",
    "clean_text",
    "absolute_url",
    "source_updated_at",
    "fetched_at",
    "snapshot_id",
    "industry",
    "industry_source",
    "source_language",
    "text_hash",
    "word_count",
    "is_placeholder",
    "exclusion_reason",
    "is_duplicate_of",
    "cleaning_version",
]
LIST_FIELDS = ("departments", "offices")

# Titles of general-interest / talent-pool postings that are not a specific job.
PLACEHOLDER_PATTERNS = [
    ("dont_see_role", re.compile(r"\bdon'?t see (what|the role|a role|your role|a position|a job)", re.I)),
    ("general_application", re.compile(r"\bgeneral (application|interest|applications)\b", re.I)),
    ("talent_pool", re.compile(r"\btalent (community|pool|network|pipeline)\b", re.I)),
    ("future_opportunities", re.compile(r"\bfuture (opportunit|opening|role)", re.I)),
    ("open_application", re.compile(r"\b(open|spontaneous|unsolicited) application\b", re.I)),
    ("expression_of_interest", re.compile(r"\bexpression of interest\b", re.I)),
]
# Description phrases that mark a talent-pool posting even when the title looks normal
# (e.g. "Interested in an internship?" -> "Join our Internship Talent Network!").
# Kept deliberately narrow: "we are not hiring" alone also appears in real postings.
PLACEHOLDER_TEXT_PATTERNS = [
    ("join_talent_pool", re.compile(r"\bjoin our [\w\s-]{0,30}talent (network|community|pool)\b", re.I)),
    ("resume_on_file", re.compile(r"\b(keep|have) your (information|resume|cv) on file\b", re.I)),
]


# ------------------------------------------------------------------------- cleaning

BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "blockquote", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "tr", "hr",
}
SKIP_TAGS = {"script", "style", "iframe", "noscript", "svg"}
LIST_TAGS = {"ul", "ol"}


class _TextExtractor(HTMLParser):
    """Turn HTML into text with paragraph breaks and "- " bullets for <li> items."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.list_depth = 0
        self.at_bullet_start = False  # suppress block breaks between "- " and its text

    def _block_break(self) -> None:
        if not self.at_bullet_start:
            self.parts.append("\n\n")

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "br":
            if not self.at_bullet_start:
                self.parts.append("\n")
        elif tag == "li":
            indent = "  " * max(self.list_depth - 1, 0)
            self.parts.append(f"\n{indent}- ")
            self.at_bullet_start = True
        elif tag in BLOCK_TAGS:
            self._block_break()
        if tag in LIST_TAGS:
            self.list_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self.skip_depth = max(self.skip_depth - 1, 0)
            return
        if self.skip_depth:
            return
        if tag in LIST_TAGS:
            self.list_depth = max(self.list_depth - 1, 0)
        if tag == "li":
            self.parts.append("\n")
            self.at_bullet_start = False
        elif tag in BLOCK_TAGS:
            self._block_break()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.at_bullet_start and data.strip():
            self.at_bullet_start = False
            data = data.lstrip()
        self.parts.append(data)


_BULLET_RE = re.compile(r"^\s*- ")


def html_to_text(raw: str) -> str:
    """Decode Greenhouse's entity-escaped HTML and return readable plain text.

    Greenhouse returns `content` as HTML whose markup is itself entity-escaped
    (`&lt;p&gt;...`). One `html.unescape` recovers the HTML; the parser then decodes the
    remaining entities in the text (`&amp;nbsp;` -> `&nbsp;` -> space, etc.).
    """
    markup = html.unescape(raw)
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ").replace("​", "")

    lines: list[str] = []
    for line in text.split("\n"):
        indent = re.match(r"^ *", line).group(0) if _BULLET_RE.match(line) else ""
        line = indent + re.sub(r"[ \t\r\f\v]+", " ", line).strip()
        if line.strip() == "-":  # empty bullet
            continue
        lines.append(line.rstrip())

    # Collapse runs of blank lines; keep consecutive bullets on adjacent lines.
    out: list[str] = []
    for line in lines:
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        if _BULLET_RE.match(line) and len(out) >= 2 and out[-1] == "" and _BULLET_RE.match(out[-2]):
            out.pop()
        out.append(line)
    return "\n".join(out).strip()


def normalize_for_hash(text: str) -> str:
    """Normalization used for exact-duplicate detection."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def text_hash(clean_text: str) -> str | None:
    norm = normalize_for_hash(clean_text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest() if norm else None


def word_count(clean_text: str) -> int:
    return sum(1 for tok in clean_text.split() if any(ch.isalnum() for ch in tok))


def _normalize_quotes(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("’", "'")


def placeholder_reason(title: str | None, clean_text: str = "") -> str | None:
    """Reason a posting is a general-interest / talent-pool placeholder, or None."""
    if title:
        normalized = _normalize_quotes(title)
        for label, pattern in PLACEHOLDER_PATTERNS:
            if pattern.search(normalized):
                return f"placeholder_title:{label}"
    if clean_text:
        normalized = _normalize_quotes(clean_text)
        for label, pattern in PLACEHOLDER_TEXT_PATTERNS:
            if pattern.search(normalized):
                return f"placeholder_text:{label}"
    return None


def posting_id(board_token: str, job_id: object) -> str:
    return f"{SOURCE_NAME}:{board_token}:{job_id}"


# ----------------------------------------------------------------------------- rows


def _names(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(i["name"]) for i in items if isinstance(i, dict) and i.get("name") is not None]


def build_row(job: dict, board: Board, manifest_row: dict[str, str]) -> dict:
    content = job.get("content")
    reasons: list[str] = []
    if content is None:
        reasons.append("missing_description")
        clean = ""
    else:
        clean = html_to_text(str(content))
        if not clean:
            reasons.append("empty_description")

    placeholder = placeholder_reason(job.get("title"), clean)
    if placeholder:
        reasons.append(placeholder)

    location = job.get("location")
    internal = job.get("internal_job_id")
    return {
        "posting_id": posting_id(board.board_token, job["id"]),
        "source": SOURCE_NAME,
        "source_job_id": str(job["id"]),
        "internal_job_id": None if internal is None else str(internal),
        "board_token": board.board_token,
        "company_name": board.company_name,
        "source_company_name": job.get("company_name"),
        "title": job.get("title"),
        "location": location.get("name") if isinstance(location, dict) else None,
        "departments": _names(job.get("departments")),
        "offices": _names(job.get("offices")),
        "raw_text": content,
        "clean_text": clean,
        "absolute_url": job.get("absolute_url"),
        "source_updated_at": job.get("updated_at"),
        "fetched_at": manifest_row["fetched_at"],
        "snapshot_id": manifest_row["snapshot_id"],
        "industry": board.industry,
        "industry_source": board.industry_source,
        "source_language": job.get("language"),
        "text_hash": text_hash(clean),
        "word_count": word_count(clean),
        "is_placeholder": placeholder is not None,
        "exclusion_reason": reasons,  # joined after duplicate detection
        "is_duplicate_of": None,
        "cleaning_version": CLEANING_VERSION,
    }


def mark_duplicates(rows: list[dict]) -> None:
    """Flag exact duplicates of normalized description text (rows are in canonical order).

    The first row with a given text_hash is canonical; later rows point to it. Titles are
    not used, so repeated titles with different text are not duplicates, and identical text
    under different titles is.
    """
    first_seen: dict[str, str] = {}
    for row in rows:
        h = row["text_hash"]
        if h is None:
            continue
        if h in first_seen:
            row["is_duplicate_of"] = first_seen[h]
            row["exclusion_reason"].append("exact_duplicate")
        else:
            first_seen[h] = row["posting_id"]


def prepare(snapshot_id: str, boards: list[Board], root: Path, log=print) -> list[dict]:
    manifest = [r for r in read_manifest(root / MANIFEST_SUBPATH) if r["snapshot_id"] == snapshot_id]
    if not manifest:
        raise ConfigError(f"No manifest rows for snapshot {snapshot_id}")
    by_token = {r["board_token"]: r for r in manifest}

    missing = [b.board_token for b in boards if b.board_token not in by_token]
    if missing:
        raise ConfigError(f"Snapshot {snapshot_id} has no file for configured boards: {missing}")
    for extra in sorted(set(by_token) - {b.board_token for b in boards}):
        log(f"warning: snapshot board '{extra}' is not in the config; skipped")

    rows: list[dict] = []
    for board in boards:  # config order, then job id: deterministic canonical order
        mrow = by_token[board.board_token]
        problem = verify_cached_file(mrow, root)
        if problem:
            raise ConfigError(f"Raw file failed verification, refusing to process: {problem}")
        with (root / mrow["file_path"]).open("rb") as f:
            payload = json.loads(f.read().decode("utf-8"))
        jobs = sorted(payload["jobs"], key=lambda j: int(j["id"]))
        rows.extend(build_row(job, board, mrow) for job in jobs)

    ids = Counter(r["posting_id"] for r in rows)
    dupe_ids = [i for i, c in ids.items() if c > 1]
    if dupe_ids:
        raise ConfigError(f"posting_id collisions: {dupe_ids[:5]}")

    mark_duplicates(rows)
    for row in rows:
        row["exclusion_reason"] = ";".join(row["exclusion_reason"])
    return rows


# --------------------------------------------------------------------------- output


def _atomic_write(path: Path, write) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        write(f)
    os.replace(tmp, path)


def write_jsonl(rows: list[dict], path: Path) -> None:
    def write(f):
        for row in rows:
            f.write(json.dumps({k: row[k] for k in OUTPUT_FIELDS}, ensure_ascii=False) + "\n")
    _atomic_write(path, write)


def csv_value(field: str, value: object) -> str:
    if field in LIST_FIELDS:
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def write_csv(rows: list[dict], path: Path) -> None:
    def write(f):
        writer = csv.writer(f)
        writer.writerow(OUTPUT_FIELDS)
        for row in rows:
            writer.writerow([csv_value(k, row[k]) for k in OUTPUT_FIELDS])
    _atomic_write(path, write)


def summarize(rows: list[dict]) -> dict:
    reasons = Counter()
    for r in rows:
        for reason in filter(None, r["exclusion_reason"].split(";")):
            reasons["placeholder" if reason.startswith("placeholder_") else reason] += 1
    by_title: dict[tuple[str, str], set] = defaultdict(set)
    for r in rows:
        if r["text_hash"]:
            by_title[(r["board_token"], r["title"])].add(r["text_hash"])
    return {
        "total": len(rows),
        "usable": sum(1 for r in rows if not r["exclusion_reason"]),
        "placeholder": reasons["placeholder"],
        "missing_description": reasons["missing_description"],
        "empty_description": reasons["empty_description"],
        "exact_duplicate": reasons["exact_duplicate"],
        "repeated_title_groups_distinct_text": sum(1 for s in by_title.values() if len(s) > 1),
    }


def _excerpt(text: str | None, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + " …"


def write_report(rows: list[dict], snapshot_id: str, boards: list[Board], path: Path,
                 jsonl: Path, csv_path: Path, root: Path) -> None:
    s = summarize(rows)
    lines = [
        f"# Sprint 1 Cleaning Quality Report — snapshot `{snapshot_id}` (PILOT)",
        "",
        "Generated by `src/prepare_postings.py`. Pilot corpus only; the board list is pending "
        "Section A agreement. Raw snapshots were verified against the manifest before "
        "processing and opened read-only.",
        "",
        f"Outputs: `{jsonl.relative_to(root).as_posix()}`, `{csv_path.relative_to(root).as_posix()}` (git-ignored).",
        "",
        "## Totals",
        "",
        "| Metric | Count |",
        "|---|---|",
        f"| Total rows | {s['total']} |",
        f"| Usable rows (no exclusion reason) | {s['usable']} |",
        f"| Placeholder / general-interest flags | {s['placeholder']} |",
        f"| Missing descriptions | {s['missing_description']} |",
        f"| Empty descriptions after cleaning | {s['empty_description']} |",
        f"| Exact duplicates (normalized text) | {s['exact_duplicate']} |",
        f"| Repeated-title groups with different text (not duplicates) | {s['repeated_title_groups_distinct_text']} |",
        "",
        "## Per board",
        "",
        "| Board | Rows | Usable | Placeholder | Missing/empty | Exact dup | Median words (usable) |",
        "|---|---|---|---|---|---|---|",
    ]
    for b in boards:
        br = [r for r in rows if r["board_token"] == b.board_token]
        usable = sorted(r["word_count"] for r in br if not r["exclusion_reason"])
        median = usable[len(usable) // 2] if usable else "—"
        lines.append(
            f"| {b.board_token} | {len(br)} | {sum(1 for r in br if not r['exclusion_reason'])} | "
            f"{sum(r['is_placeholder'] for r in br)} | "
            f"{sum(1 for r in br if 'description' in r['exclusion_reason'])} | "
            f"{sum(1 for r in br if r['is_duplicate_of'])} | {median} |"
        )

    lines += [
        "",
        "## Company names",
        "",
        "`company_name` is the standardized name from config. `source_company_name` is the "
        "API's value, kept unmodified.",
        "",
        "| Board | company_name | source_company_name (rows) | Differs |",
        "|---|---|---|---|",
    ]
    for b in boards:
        names = Counter(r["source_company_name"] for r in rows if r["board_token"] == b.board_token)
        shown = ", ".join(f"{n if n is not None else '(missing)'} ({c})" for n, c in sorted(
            names.items(), key=lambda kv: str(kv[0])))
        differs = "yes" if any(n != b.company_name for n in names) else "no"
        lines.append(f"| {b.board_token} | {b.company_name} | {shown} | {differs} |")

    lines += ["", "## Flagged rows (kept for audit)", ""]
    flagged = [r for r in rows if r["exclusion_reason"]]
    if flagged:
        lines += ["| posting_id | Title | exclusion_reason | is_duplicate_of |", "|---|---|---|---|"]
        for r in flagged:
            title = (r["title"] or "").replace("|", "\\|")
            lines.append(f"| `{r['posting_id']}` | {title} | {r['exclusion_reason']} | "
                         f"{'`' + r['is_duplicate_of'] + '`' if r['is_duplicate_of'] else ''} |")
    else:
        lines.append("None.")

    lines += [
        "",
        "## Repeated titles with different text (informational, not flagged)",
        "",
        "Same board and title, but different normalized text, so these rows are **not** "
        "duplicates. The similarity (difflib ratio of the first two rows' `clean_text`) is "
        "shown to help decide whether near-duplicate handling is needed later. It is not "
        "used for any flag.",
        "",
    ]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if r["text_hash"]:
            groups[(r["board_token"], r["title"])].append(r)
    repeated = []
    for (token, title), members in groups.items():
        if len({m["text_hash"] for m in members}) > 1:
            ratio = difflib.SequenceMatcher(
                None, members[0]["clean_text"], members[1]["clean_text"], autojunk=False
            ).ratio()
            repeated.append((ratio, token, title, members))
    if repeated:
        lines += ["| Board | Title | Rows | Similarity | Locations |", "|---|---|---|---|---|"]
        for ratio, token, title, members in sorted(repeated, key=lambda x: (-x[0], x[1], x[2])):
            locs = " · ".join(str(m["location"]) for m in members).replace("|", "\\|")
            lines.append(f"| {token} | {title.replace('|', chr(92) + '|')} | {len(members)} | "
                         f"{ratio:.3f} | {locs} |")
    else:
        lines.append("None.")

    lines += [
        "",
        "## Method",
        "",
        "- `clean_text`: one `html.unescape` of Greenhouse's entity-escaped HTML, then an HTML "
        "parser that decodes remaining entities, drops `script/style/iframe` content, turns block "
        "tags into paragraph breaks and `<li>` into `- ` bullets (nested lists indented).",
        "- `text_hash`: SHA-256 of `clean_text` after NFKC, casefolding and whitespace collapsing. "
        "Empty text gets no hash, so empty rows are never \"duplicates\" of each other.",
        "- Exact duplicates: rows sharing a `text_hash`; the first in config-board order then "
        "ascending job id is canonical. Titles are not used.",
        "- Placeholders: title matches a general-interest / talent-pool pattern "
        f"({', '.join(label for label, _ in PLACEHOLDER_PATTERNS)}), or the description "
        f"matches a narrow talent-pool phrase ({', '.join(label for label, _ in PLACEHOLDER_TEXT_PATTERNS)}). "
        "Rules are heuristic; flagged rows are kept for review.",
        "- `source_language`: Greenhouse's employer-set `language` field, **not** detected language.",
        "- `company_name` (standardized), `industry`, `industry_source`: from `config/boards.yaml`. "
        "`source_company_name`: the API's own `company_name`, unmodified.",
        f"- `cleaning_version`: `{CLEANING_VERSION}`.",
    ]
    _atomic_write(path, lambda f: f.write("\n".join(lines) + "\n"))


# ----------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Clean one raw Greenhouse snapshot into posting rows.")
    p.add_argument("--snapshot", required=True, help="snapshot_id, e.g. 20261006T171338Z")
    p.add_argument("--config", type=Path, default=None, help="board list (default: config/boards.yaml)")
    p.add_argument("--root", type=Path, default=REPO_ROOT, help="project root (default: repo root)")
    args = p.parse_args(argv)
    root = args.root.resolve()

    try:
        boards = load_config(args.config or root / "config" / "boards.yaml")
        if not boards:
            print("No boards configured; nothing to prepare.")
            return 0
        rows = prepare(args.snapshot, boards, root)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    jsonl = root / "data" / "processed" / f"postings_{args.snapshot}.jsonl"
    csv_path = jsonl.with_suffix(".csv")
    report = root / "reports" / f"sprint1_cleaning_quality_{args.snapshot}.md"
    write_jsonl(rows, jsonl)
    write_csv(rows, csv_path)
    write_report(rows, args.snapshot, boards, report, jsonl, csv_path, root)

    s = summarize(rows)
    print(f"Snapshot {args.snapshot}: {s['total']} rows, {s['usable']} usable")
    print(f"  placeholder={s['placeholder']} missing={s['missing_description']} "
          f"empty={s['empty_description']} exact_duplicate={s['exact_duplicate']} "
          f"repeated_title_groups_distinct_text={s['repeated_title_groups_distinct_text']}")
    for path in (jsonl, csv_path, report):
        print(f"  wrote {path.relative_to(root).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
