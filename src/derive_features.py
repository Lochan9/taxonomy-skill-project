"""Derive exploratory features from the local posting database (Sprint 1, pilot).

    python src/derive_features.py --db data/processed/taxonomy_pilot.sqlite \
        --snapshot 20261006T171338Z

Reads the database READ-ONLY (SQLite `mode=ro`), filtered to one snapshot, and writes
derived results separately from the immutable `postings` table:

    data/processed/derived/seniority_{snapshot}.csv     rule-based, from config/seniority_rules.yaml
    data/processed/derived/language_{snapshot}.csv      local detector (lingua), no LLM / API
    reports/sprint1_near_duplicate_candidates_{snapshot}.csv   candidate pairs for manual review

Nothing here changes the database or the raw snapshots. Near-duplicate pairs are
CANDIDATES only; they are not excluded and this does not find every near-duplicate.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import itertools
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES = REPO_ROOT / "config" / "seniority_rules.yaml"

# Language detection thresholds (documented in the exploration report).
LANG_MIN_CONFIDENCE = 0.90   # top-language confidence below this -> uncertain
LANG_MIN_MARGIN = 0.25       # top minus second confidence below this -> uncertain
LANG_MIN_WORDS = 30          # texts shorter than this -> uncertain
LANG_PARAGRAPH_MIN_WORDS = 25  # paragraphs checked individually for a different language

SENIORITY_FIELDS = ["snapshot_id", "posting_id", "title", "seniority_label", "rule_id",
                    "matched_text", "other_matches", "rules_version", "rules_sha256"]
LANGUAGE_FIELDS = ["snapshot_id", "posting_id", "source_language", "detected_language",
                   "primary_share", "whole_text_language", "whole_text_confidence",
                   "second_language", "second_confidence", "other_language_paragraphs",
                   "is_uncertain", "uncertainty_reason", "agrees_with_source",
                   "detector", "detector_version"]
PAIR_FIELDS = ["status", "board_token", "basis", "group_key", "posting_id_a", "posting_id_b",
               "title_a", "title_b", "location_a", "location_b", "internal_job_id_a",
               "internal_job_id_b", "text_similarity", "token_jaccard", "exact_text_match",
               "exclusion_reason_a", "exclusion_reason_b"]


class RulesError(Exception):
    """The seniority rules file is invalid."""


# ------------------------------------------------------------------------ database


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_postings(conn: sqlite3.Connection, snapshot_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM postings WHERE snapshot_id = ? ORDER BY posting_id", (snapshot_id,)
    ).fetchall()
    if not rows:
        raise ValueError(f"No postings for snapshot {snapshot_id}")
    return [dict(r) for r in rows]


# ----------------------------------------------------------------------- seniority


@dataclass(frozen=True)
class Rule:
    id: str
    label: str
    patterns: tuple[re.Pattern, ...]
    exclude: tuple[re.Pattern, ...]


@dataclass(frozen=True)
class RuleSet:
    version: str
    sha256: str
    labels: tuple[str, ...]
    rules: tuple[Rule, ...]
    default_label: str


def load_rules(path: Path = DEFAULT_RULES) -> RuleSet:
    raw = path.read_bytes()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        raise RulesError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RulesError(f"{path} must be a mapping")
    for key in ("version", "labels", "rules", "default_label"):
        if key not in data:
            raise RulesError(f"{path} is missing '{key}'")
    labels = data["labels"]
    if not isinstance(labels, list) or not labels or len(set(labels)) != len(labels):
        raise RulesError("labels must be a non-empty list of unique names")
    if data["default_label"] not in labels:
        raise RulesError(f"default_label {data['default_label']!r} is not in labels")

    rules, seen = [], set()
    for i, r in enumerate(data["rules"] or []):
        where = f"rules[{i}]"
        if not isinstance(r, dict) or set(r) - {"id", "label", "patterns", "exclude"}:
            raise RulesError(f"{where} must have only id, label, patterns, exclude")
        if r.get("id") in seen or not r.get("id"):
            raise RulesError(f"{where}: missing or duplicate id {r.get('id')!r}")
        seen.add(r["id"])
        if r.get("label") not in labels:
            raise RulesError(f"{where}: label {r.get('label')!r} is not in labels")
        if not r.get("patterns"):
            raise RulesError(f"{where}: patterns must be a non-empty list")
        try:
            pats = tuple(re.compile(p, re.I) for p in r["patterns"])
            excl = tuple(re.compile(p, re.I) for p in r.get("exclude") or [])
        except re.error as exc:
            raise RulesError(f"{where}: invalid regex: {exc}") from exc
        rules.append(Rule(r["id"], r["label"], pats, excl))
    if not rules:
        raise RulesError("at least one rule is required")
    return RuleSet(str(data["version"]), hashlib.sha256(raw).hexdigest(), tuple(labels),
                   tuple(rules), data["default_label"])


def _rule_match(rule: Rule, title: str) -> str | None:
    if any(e.search(title) for e in rule.exclude):
        return None
    for p in rule.patterns:
        m = p.search(title)
        if m:
            return m.group(0)
    return None


def classify_title(title: str | None, rules: RuleSet) -> dict:
    """First matching rule wins; later matches are kept in other_matches for review."""
    title = (title or "").strip()
    hits = [(r, txt) for r in rules.rules if (txt := _rule_match(r, title)) is not None]
    if not hits:
        return {"seniority_label": rules.default_label, "rule_id": "", "matched_text": "",
                "other_matches": ""}
    (rule, text), others = hits[0], hits[1:]
    return {
        "seniority_label": rule.label,
        "rule_id": rule.id,
        "matched_text": text,
        "other_matches": ";".join(f"{r.id}:{r.label}" for r, _ in others),
    }


def derive_seniority(postings: list[dict], rules: RuleSet) -> list[dict]:
    return [
        {"snapshot_id": p["snapshot_id"], "posting_id": p["posting_id"], "title": p["title"],
         **classify_title(p["title"], rules), "rules_version": rules.version,
         "rules_sha256": rules.sha256}
        for p in postings
    ]


# ------------------------------------------------------------------------ language


def build_detector():
    from lingua import LanguageDetectorBuilder

    return LanguageDetectorBuilder.from_all_languages().build()


def detector_info() -> tuple[str, str]:
    name = "lingua-language-detector"
    return name, metadata.version(name)


def _iso(lang) -> str:
    return lang.iso_code_639_1.name.lower()


def detect_language(text: str, detector) -> dict:
    """Detect the main language of a posting.

    The label is the language covering the most words across paragraphs of at least
    LANG_PARAGRAPH_MIN_WORDS words (falling back to the whole text when no paragraph is that
    long). lingua's whole-text result is recorded too: on mixed-language input it can follow
    the minority language with high confidence, so a disagreement marks the row uncertain.
    """
    words = len(text.split())
    if not text.strip():
        return {"detected_language": None, "primary_share": None, "whole_text_language": None,
                "whole_text_confidence": None, "second_language": None, "second_confidence": None,
                "other_language_paragraphs": 0, "is_uncertain": True, "uncertainty_reason": "empty_text"}

    values = detector.compute_language_confidence_values(text)
    top = values[0]
    second = values[1] if len(values) > 1 else None
    whole = _iso(top.language)

    para_langs: list[tuple[str, float, int]] = []
    for para in re.split(r"\n\s*\n", text):
        n = len(para.split())
        if n >= LANG_PARAGRAPH_MIN_WORDS:
            pv = detector.compute_language_confidence_values(para)[0]
            para_langs.append((_iso(pv.language), pv.value, n))

    if para_langs:
        share: dict[str, int] = {}
        for lang, _, n in para_langs:
            share[lang] = share.get(lang, 0) + n
        primary = max(sorted(share), key=share.get)
        primary_share = share[primary] / sum(share.values())
        other_paragraphs = sum(1 for lang, conf, _ in para_langs
                               if lang != primary and conf >= LANG_MIN_CONFIDENCE)
    else:
        primary, primary_share, other_paragraphs = whole, None, 0

    reasons = []
    if top.value < LANG_MIN_CONFIDENCE:
        reasons.append("low_confidence")
    if second is not None and top.value - second.value < LANG_MIN_MARGIN:
        reasons.append("small_margin")
    if words < LANG_MIN_WORDS:
        reasons.append("short_text")
    if whole != primary:
        reasons.append("whole_text_disagrees")
    if other_paragraphs:
        reasons.append("other_language_paragraphs")
    return {
        "detected_language": primary,
        "primary_share": None if primary_share is None else round(primary_share, 4),
        "whole_text_language": whole,
        "whole_text_confidence": round(top.value, 4),
        "second_language": _iso(second.language) if second else None,
        "second_confidence": round(second.value, 4) if second else None,
        "other_language_paragraphs": other_paragraphs,
        "is_uncertain": bool(reasons),
        "uncertainty_reason": ";".join(reasons),
    }


def derive_language(postings: list[dict], detector=None) -> list[dict]:
    detector = detector or build_detector()
    name, version = detector_info()
    out = []
    for p in postings:
        d = detect_language(p["clean_text"] or "", detector)
        src = (p["source_language"] or "").lower() or None
        agrees = None if src is None or d["detected_language"] is None else src == d["detected_language"]
        out.append({"snapshot_id": p["snapshot_id"], "posting_id": p["posting_id"],
                    "source_language": p["source_language"], **d,
                    "agrees_with_source": agrees, "detector": name, "detector_version": version})
    return out


# ------------------------------------------------------------------ near-duplicates


def normalize_title(title: str | None) -> str:
    return re.sub(r"\s+", " ", (title or "").casefold()).strip()


def token_jaccard(a: str, b: str) -> float:
    ta, tb = set(re.findall(r"\w+", a.casefold())), set(re.findall(r"\w+", b.casefold()))
    if not ta and not tb:
        return 1.0
    return len(ta & tb) / len(ta | tb)


def near_duplicate_candidates(postings: list[dict]) -> list[dict]:
    """All pairs within each same-board group sharing internal_job_id or normalized title."""
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for p in postings:
        if p["internal_job_id"] is not None:
            groups.setdefault((p["board_token"], "internal_job_id", p["internal_job_id"]), []).append(p)
        if normalize_title(p["title"]):
            groups.setdefault((p["board_token"], "title", normalize_title(p["title"])), []).append(p)

    pairs: dict[tuple[str, str], dict] = {}
    for (board, basis, key), members in sorted(groups.items()):
        if len(members) < 2:
            continue
        for a, b in itertools.combinations(sorted(members, key=lambda m: m["posting_id"]), 2):
            k = (a["posting_id"], b["posting_id"])
            if k in pairs:  # found via both bases
                pairs[k]["basis"] = "internal_job_id+title"
                pairs[k]["group_key"] += f" | {basis}={key}"
                continue
            ta, tb = a["clean_text"] or "", b["clean_text"] or ""
            pairs[k] = {
                "status": "candidate",
                "board_token": board,
                "basis": basis,
                "group_key": f"{basis}={key}",
                "posting_id_a": a["posting_id"], "posting_id_b": b["posting_id"],
                "title_a": a["title"], "title_b": b["title"],
                "location_a": a["location"], "location_b": b["location"],
                "internal_job_id_a": a["internal_job_id"], "internal_job_id_b": b["internal_job_id"],
                "text_similarity": round(difflib.SequenceMatcher(None, ta, tb, autojunk=False).ratio(), 4),
                "token_jaccard": round(token_jaccard(ta, tb), 4),
                "exact_text_match": a["text_hash"] is not None and a["text_hash"] == b["text_hash"],
                "exclusion_reason_a": a["exclusion_reason"], "exclusion_reason_b": b["exclusion_reason"],
            }
    return sorted(pairs.values(), key=lambda r: (-r["text_similarity"], r["posting_id_a"], r["posting_id_b"]))


# -------------------------------------------------------------------------- output


def _csv_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return "" if v is None else str(v)


def write_csv(rows: list[dict], fields: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for r in rows:
            w.writerow([_csv_value(r[k]) for k in fields])
    os.replace(tmp, path)


def output_paths(root: Path, snapshot_id: str) -> dict[str, Path]:
    derived = root / "data" / "processed" / "derived"
    return {
        "seniority": derived / f"seniority_{snapshot_id}.csv",
        "language": derived / f"language_{snapshot_id}.csv",
        "pairs": root / "reports" / f"sprint1_near_duplicate_candidates_{snapshot_id}.csv",
    }


def run_all(db_path: Path, snapshot_id: str, root: Path = REPO_ROOT,
            rules_path: Path = DEFAULT_RULES, detector=None) -> dict:
    conn = connect_readonly(db_path)
    try:
        postings = fetch_postings(conn, snapshot_id)
    finally:
        conn.close()
    rules = load_rules(rules_path)
    result = {
        "postings": postings,
        "seniority": derive_seniority(postings, rules),
        "language": derive_language(postings, detector),
        "pairs": near_duplicate_candidates(postings),
        "rules": rules,
        "paths": output_paths(root, snapshot_id),
    }
    write_csv(result["seniority"], SENIORITY_FIELDS, result["paths"]["seniority"])
    write_csv(result["language"], LANGUAGE_FIELDS, result["paths"]["language"])
    write_csv(result["pairs"], PAIR_FIELDS, result["paths"]["pairs"])
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Derive seniority, language and near-duplicate candidates.")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    args = p.parse_args(argv)
    try:
        r = run_all(args.db, args.snapshot, rules_path=args.rules)
    except (FileNotFoundError, ValueError, RulesError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Snapshot {args.snapshot}: {len(r['postings'])} postings")
    print(f"  seniority rules v{r['rules'].version}; language detector {detector_info()[1]}; "
          f"{len(r['pairs'])} near-duplicate candidate pairs")
    for path in r["paths"].values():
        print(f"  wrote {path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
