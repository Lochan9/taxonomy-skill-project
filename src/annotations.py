"""Local human-annotation workflow for the Sprint 2 skill set (Section B). No LLM, no network.

    python src/annotations.py export   --db DB            # texts (git-ignored) + empty templates
    python src/annotations.py init     --annotator alice  # personal copies of the templates
    python src/annotations.py locate   --db DB --posting ID --text "exact phrase" [--occurrence 2]
    python src/annotations.py validate --db DB --dir data/annotation/sprint2_v1/annotators/alice
    python src/annotations.py compare  --db DB --a alice --b bob

Records (CSV, UTF-8) live in data/annotation/sprint2_v1/:
    postings_review.csv  one row per selected posting: review_status not_started | in_progress |
                         reviewed. A "reviewed" posting with no skill rows is a deliberate
                         zero-skill posting; "not_started"/"in_progress" are unfinished.
    skills.csv           one row per atomic skill statement with evidence offsets.

Offsets are zero-based Python string indices into the posting's unchanged clean_text, end
exclusive: clean_text[evidence_start:evidence_end] == evidence_text exactly.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import derive_features as df
from select_annotation_set import REPO_ROOT, SelectionError, read_manifest, set_dir

REVIEW_FIELDS = ["snapshot_id", "posting_id", "split", "review_status", "annotator_id", "reviewed_at", "review_notes"]
SKILL_FIELDS = ["snapshot_id", "posting_id", "annotation_id", "skill_statement", "evidence_text", "evidence_start",
                "evidence_end", "required_or_preferred", "alternative_group_id", "skill_category", "annotator_id",
                "review_notes"]
# Optional. Records sharing an id within one posting are ALTERNATIVES ("Go or Python"): the
# posting asks for at least one of them, not all. Skills joined by "and" are never grouped.
ALT_GROUP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
REVIEW_STATUSES = {"not_started", "in_progress", "reviewed"}
REQUIREMENT_VALUES = {"required", "preferred", "unspecified"}
SKILL_CATEGORIES = {"", "technical", "tool", "domain_knowledge", "transferable"}  # optional field
ANNOTATOR_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ][0-9:.]+Z?)?$")


class AnnotationError(Exception):
    """Inputs for an annotation command are invalid."""


@dataclass
class Problem:
    file: str
    line: int
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: [{self.field}] {self.message}"


# ------------------------------------------------------------------------- texts


def load_texts(db: Path, manifest: list[dict]) -> dict[str, str]:
    """clean_text of every manifest posting, verified against the manifest's SHA-256."""
    snapshot = {r["snapshot_id"] for r in manifest}
    if len(snapshot) != 1:
        raise AnnotationError(f"manifest mixes snapshots {sorted(snapshot)}")
    conn = df.connect_readonly(db)
    try:
        rows = dict(conn.execute(
            "SELECT posting_id, clean_text FROM usable_postings WHERE snapshot_id = ?", (snapshot.pop(),)).fetchall())
    finally:
        conn.close()
    texts = {}
    for r in manifest:
        t = rows.get(r["posting_id"])
        if t is None:
            raise AnnotationError(f"{r['posting_id']} is not a usable posting in snapshot {r['snapshot_id']}")
        if hashlib.sha256(t.encode("utf-8")).hexdigest() != r["clean_text_sha256"]:
            raise AnnotationError(f"{r['posting_id']}: clean_text no longer matches the frozen manifest")
        texts[r["posting_id"]] = t
    return texts


def safe_name(posting_id: str) -> str:
    return posting_id.replace(":", "__")


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def read_csv(path: Path, fields: list[str]) -> list[tuple[int, dict]]:
    """Rows with their file line numbers (header = line 1). Raises on a wrong header."""
    if not path.is_file():
        raise AnnotationError(f"missing file: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if r.fieldnames != fields:
            raise AnnotationError(f"{path.name}: columns {r.fieldnames}, expected {fields}")
        out = []
        for row in r:
            out.append((r.line_num, row))
        return out


def export(db: Path, root: Path = REPO_ROOT) -> dict:
    base = set_dir(root)
    manifest = read_manifest(base / "selection_manifest.csv")
    texts = load_texts(db, manifest)
    tdir = base / "texts"
    for r in manifest:
        p = tdir / r["split"] / f"{safe_name(r['posting_id'])}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        # newline="" keeps the text byte-identical, so editor offsets equal Python offsets
        with p.open("w", encoding="utf-8", newline="") as f:
            f.write(texts[r["posting_id"]])
    with (tdir / "texts.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in manifest:
            f.write(json.dumps({"snapshot_id": r["snapshot_id"], "posting_id": r["posting_id"], "split": r["split"],
                                "title": r["title"], "company_name": r["company_name"],
                                "clean_text": texts[r["posting_id"]]}, ensure_ascii=False) + "\n")
    tmpl = base / "templates"
    _write_csv(tmpl / "postings_review.csv", REVIEW_FIELDS,
               [{"snapshot_id": r["snapshot_id"], "posting_id": r["posting_id"], "split": r["split"],
                 "review_status": "not_started", "annotator_id": "", "reviewed_at": "", "review_notes": ""}
                for r in sorted(manifest, key=lambda r: (r["split"], r["posting_id"]))])
    _write_csv(tmpl / "skills.csv", SKILL_FIELDS, [])
    return {"texts": len(texts), "dir": tdir, "templates": tmpl}


def init_annotator(annotator: str, root: Path = REPO_ROOT) -> Path:
    if not ANNOTATOR_RE.match(annotator):
        raise AnnotationError("annotator id must be lowercase letters/digits/_/- (max 32)")
    base = set_dir(root)
    dest = base / "annotators" / annotator
    if dest.exists():
        raise AnnotationError(f"{dest} already exists; not overwriting someone's annotations")
    for name in ("postings_review.csv", "skills.csv"):
        src = base / "templates" / name
        if not src.is_file():
            raise AnnotationError("templates missing; run `export` first")
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest / name)
    return dest


def locate(text: str, phrase: str, occurrence: int = 1) -> tuple[int, int]:
    if not phrase:
        raise AnnotationError("phrase is empty")
    starts = [m.start() for m in re.finditer(re.escape(phrase), text)]
    if not starts:
        raise AnnotationError("phrase not found (it must match clean_text exactly, including case and spaces)")
    if not 1 <= occurrence <= len(starts):
        raise AnnotationError(f"phrase occurs {len(starts)} time(s); occurrence {occurrence} is out of range")
    s = starts[occurrence - 1]
    return s, s + len(phrase)


# ---------------------------------------------------------------------- validation


def validate(ann_dir: Path, manifest: list[dict], texts: dict[str, str], final: bool = False) -> dict:
    """Validate one annotation folder. Returns {'problems': [...], 'summary': {...}}."""
    problems: list[Problem] = []
    rev_path, sk_path = ann_dir / "postings_review.csv", ann_dir / "skills.csv"
    reviews = read_csv(rev_path, REVIEW_FIELDS)
    skills = read_csv(sk_path, SKILL_FIELDS)
    by_id = {r["posting_id"]: r for r in manifest}
    snap = manifest[0]["snapshot_id"]

    status: dict[str, str] = {}
    for line, r in reviews:
        P = lambda f, m: problems.append(Problem(rev_path.name, line, f, m))
        pid = r["posting_id"]
        if pid not in by_id:
            P("posting_id", f"{pid!r} is not in the selection manifest")
            continue
        if pid in status:
            P("posting_id", f"{pid} listed more than once")
            continue
        if r["snapshot_id"] != snap:
            P("snapshot_id", f"{r['snapshot_id']!r} != selection snapshot {snap}")
        if r["split"] != by_id[pid]["split"]:
            P("split", f"{r['split']!r} != manifest split {by_id[pid]['split']!r}")
        if r["review_status"] not in REVIEW_STATUSES:
            P("review_status", f"{r['review_status']!r} must be one of {sorted(REVIEW_STATUSES)}")
        if r["review_status"] == "reviewed":
            if not r["annotator_id"]:
                P("annotator_id", "required when review_status is 'reviewed'")
            if r["reviewed_at"] and not ISO_DATE_RE.match(r["reviewed_at"]):
                P("reviewed_at", f"{r['reviewed_at']!r} is not an ISO date (YYYY-MM-DD)")
        status[pid] = r["review_status"]
    missing = sorted(set(by_id) - set(status))
    if missing:
        problems.append(Problem(rev_path.name, 0, "posting_id", f"{len(missing)} selected posting(s) missing, e.g. {missing[0]}"))

    seen_ids: set[str] = set()
    seen_spans: set[tuple] = set()
    per_posting: Counter = Counter()
    alt_groups: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for line, r in skills:
        gid = r["alternative_group_id"].strip()
        if gid:
            if not ALT_GROUP_RE.match(gid):
                problems.append(Problem(sk_path.name, line, "alternative_group_id",
                                        f"{gid!r} must be letters/digits/_/./- (max 40), e.g. 'alt-1'"))
            else:
                alt_groups[gid].append((line, r))
        P = lambda f, m: problems.append(Problem(sk_path.name, line, f, m))
        pid = r["posting_id"]
        if r["snapshot_id"] != snap:
            P("snapshot_id", f"{r['snapshot_id']!r} != selection snapshot {snap}")
        if pid not in by_id:
            P("posting_id", f"{pid!r} is not in the selection manifest")
            continue
        aid = r["annotation_id"].strip()
        if not aid:
            P("annotation_id", "empty")
        elif aid in seen_ids:
            P("annotation_id", f"{aid!r} is used more than once")
        seen_ids.add(aid)
        if not r["skill_statement"].strip():
            P("skill_statement", "empty")
        if r["required_or_preferred"] not in REQUIREMENT_VALUES:
            P("required_or_preferred", f"{r['required_or_preferred']!r} must be one of {sorted(REQUIREMENT_VALUES)}")
        if r["skill_category"] not in SKILL_CATEGORIES:
            P("skill_category", f"{r['skill_category']!r} must be empty or one of {sorted(SKILL_CATEGORIES - {''})}")
        if not r["annotator_id"].strip():
            P("annotator_id", "empty")
        if status.get(pid) == "not_started":
            P("posting_id", f"{pid} has skill rows but review_status is 'not_started'")
        try:
            start, end = int(r["evidence_start"]), int(r["evidence_end"])
        except ValueError:
            P("evidence_start/end", f"offsets must be integers, got {r['evidence_start']!r}, {r['evidence_end']!r}")
            continue
        text = texts[pid]
        if not (0 <= start < end <= len(text)):
            P("evidence_start/end", f"need 0 <= start < end <= {len(text)}, got {start}..{end}")
            continue
        actual = text[start:end]
        if actual != r["evidence_text"]:
            hint = ""
            hits = [m.start() for m in re.finditer(re.escape(r["evidence_text"]), text)] if r["evidence_text"] else []
            if hits:
                hint = f"; evidence_text occurs at start offset(s) {hits[:3]} (end = start + {len(r['evidence_text'])})"
            P("evidence_text", f"clean_text[{start}:{end}] is {actual[:60]!r}, not {r['evidence_text'][:60]!r}{hint}")
            continue
        if actual != actual.strip():
            P("evidence_text", "evidence starts or ends with whitespace; trim the span")
        key = (pid, start, end, r["skill_statement"].strip().casefold())
        if key in seen_spans:
            P("skill_statement", "same statement and span recorded twice (repeated mentions: record one; see guidelines)")
        seen_spans.add(key)
        per_posting[pid] += 1

    for gid, members in alt_groups.items():
        first_line = members[0][0]
        P = lambda f, m: problems.append(Problem(sk_path.name, first_line, f, m))
        postings = {r["posting_id"] for _, r in members}
        if len(postings) > 1:
            P("alternative_group_id", f"{gid!r} is used in {len(postings)} postings; an alternative group "
                                      "belongs to one posting (use a new id per posting)")
            continue
        if len(members) < 2:
            P("alternative_group_id", f"{gid!r} has only one record; alternatives need at least two "
                                      "(leave the field empty for a single skill)")
        reqs = {r["required_or_preferred"] for _, r in members}
        if len(reqs) > 1:
            P("required_or_preferred", f"alternative group {gid!r} mixes {sorted(reqs)}; the group shares one "
                                       "requirement value (it applies to 'at least one of' the group)")
        statements = [r["skill_statement"].strip().casefold() for _, r in members]
        if len(set(statements)) < len(statements):
            P("skill_statement", f"alternative group {gid!r} lists the same skill twice")

    reviewed = [p for p, s in status.items() if s == "reviewed"]
    summary = {
        "selected": len(by_id),
        "reviewed": len(reviewed),
        "reviewed_with_skills": sum(1 for p in reviewed if per_posting[p]),
        "reviewed_zero_skills": sum(1 for p in reviewed if not per_posting[p]),
        "in_progress": sum(1 for s in status.values() if s == "in_progress"),
        "not_started": sum(1 for s in status.values() if s == "not_started") + len(missing),
        "skill_rows": len(skills),
        "alternative_groups": len(alt_groups),
    }
    summary["complete"] = summary["reviewed"] == len(by_id) and not problems
    if final and not summary["complete"]:
        problems.append(Problem(rev_path.name, 0, "review_status",
                                f"final set requires all {len(by_id)} postings reviewed with no problems "
                                f"({summary['reviewed']} reviewed)"))
    return {"problems": problems, "summary": summary}


# ------------------------------------------------------------------------ compare


def compare(a_dir: Path, b_dir: Path, manifest: list[dict]) -> dict:
    """Span-overlap agreement on postings both annotators marked reviewed. For adjudication, not gold."""
    def load(d):
        st = {r["posting_id"]: r["review_status"] for _, r in read_csv(d / "postings_review.csv", REVIEW_FIELDS)}
        sk = defaultdict(list)
        for _, r in read_csv(d / "skills.csv", SKILL_FIELDS):
            sk[r["posting_id"]].append(r)
        return st, sk
    (sa, ka), (sb, kb) = load(a_dir), load(b_dir)
    both = sorted(p for p in (r["posting_id"] for r in manifest) if sa.get(p) == sb.get(p) == "reviewed")
    exact = overlap = only_a = only_b = req_disagree = alt_disagree = 0
    rows = []
    for pid in both:
        A = [(int(r["evidence_start"]), int(r["evidence_end"]), r) for r in ka[pid]]
        B = [(int(r["evidence_start"]), int(r["evidence_end"]), r) for r in kb[pid]]
        used = set()
        for s, e, r in A:
            match = None
            for j, (s2, e2, r2) in enumerate(B):
                if j in used:
                    continue
                if (s, e) == (s2, e2) or (s < e2 and s2 < e):
                    match = j
                    if (s, e) == (s2, e2):
                        break
            if match is None:
                only_a += 1
                rows.append({"posting_id": pid, "kind": "only_a", "a": r["evidence_text"], "b": ""})
            else:
                used.add(match)
                s2, e2, r2 = B[match]
                if (s, e) == (s2, e2):
                    exact += 1
                else:
                    overlap += 1
                if r["required_or_preferred"] != r2["required_or_preferred"]:
                    req_disagree += 1
                alt_differs = bool(r["alternative_group_id"].strip()) != bool(r2["alternative_group_id"].strip())
                alt_disagree += alt_differs
                if (s, e) != (s2, e2) or r["required_or_preferred"] != r2["required_or_preferred"] or alt_differs:
                    rows.append({"posting_id": pid, "kind": "differs", "a": r["evidence_text"], "b": r2["evidence_text"]})
        for j, (_, _, r2) in enumerate(B):
            if j not in used:
                only_b += 1
                rows.append({"posting_id": pid, "kind": "only_b", "a": "", "b": r2["evidence_text"]})
    matched = exact + overlap
    na, nb = matched + only_a, matched + only_b
    return {"postings_compared": len(both), "exact_span_matches": exact, "overlapping_matches": overlap,
            "only_a": only_a, "only_b": only_b, "requirement_disagreements": req_disagree,
            "alternative_disagreements": alt_disagree,
            "overlap_f1": round(2 * matched / (na + nb), 4) if na + nb else None, "disagreements": rows}


# ---------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sprint 2 annotation workflow (local, human labels only).")
    p.add_argument("--root", type=Path, default=REPO_ROOT)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export"); e.add_argument("--db", type=Path, required=True)
    i = sub.add_parser("init"); i.add_argument("--annotator", required=True)
    lo = sub.add_parser("locate"); lo.add_argument("--db", type=Path, required=True)
    lo.add_argument("--posting", required=True); lo.add_argument("--text", required=True)
    lo.add_argument("--occurrence", type=int, default=1)
    v = sub.add_parser("validate"); v.add_argument("--db", type=Path, required=True)
    v.add_argument("--dir", type=Path, required=True); v.add_argument("--final", action="store_true")
    c = sub.add_parser("compare"); c.add_argument("--db", type=Path, required=True)
    c.add_argument("--a", required=True); c.add_argument("--b", required=True)
    args = p.parse_args(argv)
    root = args.root.resolve()
    try:
        manifest = read_manifest(set_dir(root) / "selection_manifest.csv")
        if args.cmd == "export":
            r = export(args.db, root)
            print(f"exported {r['texts']} texts to {r['dir']} and empty templates to {r['templates']}")
        elif args.cmd == "init":
            print(f"created {init_annotator(args.annotator, root)} (copy of the empty templates)")
        elif args.cmd == "locate":
            rows = [r for r in manifest if r["posting_id"] == args.posting]
            if not rows:
                raise AnnotationError(f"{args.posting} is not in the selection manifest")
            s, e2 = locate(load_texts(args.db, rows)[args.posting], args.text, args.occurrence)
            print(f"evidence_start={s} evidence_end={e2}")
        elif args.cmd == "validate":
            res = validate(args.dir, manifest, load_texts(args.db, manifest), final=args.final)
            for pr in res["problems"]:
                print(pr, file=sys.stderr)
            print(json.dumps(res["summary"]))
            return 0 if not res["problems"] else 1
        elif args.cmd == "compare":
            base = set_dir(root) / "annotators"
            res = compare(base / args.a, base / args.b, manifest)
            print(json.dumps({k: v for k, v in res.items() if k != "disagreements"}))
            for d in res["disagreements"][:50]:
                print(f"  {d['posting_id']} {d['kind']}: A={d['a'][:60]!r} B={d['b'][:60]!r}")
    except (AnnotationError, SelectionError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
