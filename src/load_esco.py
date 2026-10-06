"""Import ESCO skill-pillar reference data into the local SQLite database (Sprint 1, Section B).

    python src/load_esco.py --db data/processed/taxonomy_pilot.sqlite --version v1.2.1 --source-dir auto

Reads the user-extracted ESCO CSV folder (located by name prefix with `--source-dir auto`), and
loads, keyed by (esco_version, concept_uri):

    skills_{lang}.csv                   -> esco_concepts (KnowledgeSkillCompetence)
    skillGroups_{lang}.csv              -> esco_concepts (SkillGroup)
    conceptSchemes_{lang}.csv           -> esco_concept_schemes (+ inScheme -> esco_concept_scheme_members)
    broaderRelationsSkillPillar_{lang}.csv -> esco_broader_relations (narrower = view)
    skillSkillRelations_{lang}.csv      -> esco_skill_relations
    skillsHierarchy_{lang}.csv          -> validation only (its links must already be broader relations)

Guarantees:
- Every source file must be registered in data/reference_manifest.csv with a matching SHA-256.
- Headers must match exactly; everything is validated before writing; relationship endpoints
  must resolve to loaded concepts of the stated type (unresolved references abort the import).
- Migration sql/migration_002_esco_reference.sql and the import run in ONE transaction.
- Re-importing identical files is a no-op; different files for the same version/language are
  rejected. Existing tables (postings etc.) are never modified. Source files are read-only.
- Source rows that repeat a concept URI are accepted only if they differ in `modifiedDate`
  alone; the latest is loaded and every repeated row is kept in esco_source_duplicates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from load_postings import connect
from register_esco_archive import REPO_ROOT, RegistrationError, find_extracted_dir, read_manifest

IMPORTER_VERSION = "0.1.0"
MIGRATION_PATH = REPO_ROOT / "sql" / "migration_002_esco_reference.sql"
MIGRATION_ID = "002"

# Exact headers of ESCO v1.2.1 English CSVs (inspected; see reports/esco_headers_v1.2.1.md).
EXPECTED_HEADERS = {
    "skills": ["conceptType", "conceptUri", "skillType", "reuseLevel", "preferredLabel", "altLabels",
               "hiddenLabels", "status", "modifiedDate", "scopeNote", "definition", "inScheme", "description"],
    "skillGroups": ["conceptType", "conceptUri", "preferredLabel", "altLabels", "hiddenLabels", "status",
                    "modifiedDate", "scopeNote", "inScheme", "description", "code"],
    "conceptSchemes": ["conceptType", "conceptSchemeUri", "preferredLabel", "title", "status",
                       "description", "hasTopConcept"],
    "broaderRelationsSkillPillar": ["conceptType", "conceptUri", "conceptLabel", "broaderType",
                                    "broaderUri", "broaderLabel"],
    "skillSkillRelations": ["originalSkillUri", "originalSkillType", "relationType", "relatedSkillType",
                            "relatedSkillUri"],
    "skillsHierarchy": ["Level 0 URI", "Level 0 preferred term", "Level 1 URI", "Level 1 preferred term",
                        "Level 2 URI", "Level 2 preferred term", "Level 3 URI", "Level 3 preferred term",
                        "Description", "Scope note", "Level 0 code", "Level 1 code", "Level 2 code",
                        "Level 3 code"],
}
# Files whose rows may omit trailing empty fields in the source (observed in skillsHierarchy).
RAGGED_OK = {"skillsHierarchy"}
CONCEPT_TYPES = {"skills": "KnowledgeSkillCompetence", "skillGroups": "SkillGroup"}
DUPLICATE_TOLERATED_FIELDS = {"modifiedDate"}


class InputError(Exception):
    """Source files are missing, unregistered, malformed or internally inconsistent."""


class ConflictError(Exception):
    """The database already holds different ESCO data for this version/language."""


# ------------------------------------------------------------------------- reading


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_paths(source_dir: Path, language: str) -> dict[str, Path]:
    paths = {key: source_dir / f"{key}_{language}.csv" for key in EXPECTED_HEADERS}
    missing = [p.name for p in paths.values() if not p.is_file()]
    if missing:
        raise InputError(f"missing source files in {source_dir}: {missing}")
    return paths


def verify_against_manifest(paths: dict[str, Path], version: str, root: Path) -> dict[str, str]:
    """Every file must be registered for this version with an identical SHA-256."""
    try:
        manifest = read_manifest(root / "data" / "reference_manifest.csv")
    except RegistrationError as exc:
        raise InputError(str(exc)) from exc
    recorded = {r["relative_path"]: r for r in manifest if r["dataset"] == "esco" and r["version"] == version}
    hashes = {}
    for key, p in paths.items():
        rel = p.resolve().relative_to(root.resolve()).as_posix()
        if rel not in recorded:
            raise InputError(f"{rel} is not registered in data/reference_manifest.csv; "
                             "run src/register_esco_archive.py first")
        digest = sha256_file(p)
        if digest != recorded[rel]["sha256"]:
            raise InputError(f"{rel} does not match its registered SHA-256 (file changed since registration)")
        hashes[p.name] = digest
    return hashes


def read_csv(path: Path, key: str) -> list[dict[str, str]]:
    csv.field_size_limit(max(csv.field_size_limit(), 64 * 1024 * 1024))
    expected = EXPECTED_HEADERS[key]
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header != expected:
                raise InputError(f"{path.name}: header {header} does not match expected {expected}")
            rows = []
            for n, raw in enumerate(reader, start=1):
                if len(raw) != len(expected):
                    if key in RAGGED_OK and len(raw) < len(expected):
                        raw = raw + [""] * (len(expected) - len(raw))
                    else:
                        raise InputError(f"{path.name} row {n}: {len(raw)} fields, expected {len(expected)}")
                rows.append(dict(zip(expected, raw)))
    except UnicodeDecodeError as exc:
        raise InputError(f"{path.name} is not valid UTF-8: {exc}") from exc
    if not rows:
        raise InputError(f"{path.name} has no data rows")
    return rows


def split_labels(value: str) -> tuple[list[str], int]:
    """ESCO separates labels with newlines. Returns (labels, empty pieces dropped)."""
    if not value:
        return [], 0
    pieces = value.split("\n")
    labels = [p.strip() for p in pieces if p.strip()]
    return labels, len(pieces) - len(labels)


def split_uris(value: str) -> list[str]:
    """inScheme separates URIs with newlines and/or commas."""
    return [u for u in (x.strip() for x in re.split(r"[\n,]+", value or "")) if u]


# ---------------------------------------------------------------------- validation


def build(paths: dict[str, Path], version: str) -> dict:
    """Parse and validate everything; returns rows ready to insert plus a validation report."""
    data = {k: read_csv(p, k) for k, p in paths.items()}
    report: dict = {"warnings": [], "unresolved": {}}

    # --- schemes
    schemes = {}
    for r in data["conceptSchemes"]:
        if not r["conceptSchemeUri"]:
            raise InputError("conceptSchemes row without conceptSchemeUri")
        if r["conceptSchemeUri"] in schemes:
            raise InputError(f"duplicate concept scheme {r['conceptSchemeUri']}")
        schemes[r["conceptSchemeUri"]] = r

    # --- concepts (skills + groups), with the duplicate-URI policy
    concepts: dict[str, dict] = {}
    duplicates: list[dict] = []
    empty_label_pieces = 0
    for key in ("skills", "skillGroups"):
        by_uri: dict[str, list[tuple[int, dict]]] = defaultdict(list)
        for n, r in enumerate(data[key], start=1):
            if r["conceptType"] != CONCEPT_TYPES[key]:
                raise InputError(f"{paths[key].name} row {n}: conceptType {r['conceptType']!r}, "
                                 f"expected {CONCEPT_TYPES[key]!r}")
            if not r["conceptUri"].startswith("http"):
                raise InputError(f"{paths[key].name} row {n}: invalid conceptUri {r['conceptUri']!r}")
            if not r["preferredLabel"].strip():
                raise InputError(f"{paths[key].name} row {n}: empty preferredLabel")
            by_uri[r["conceptUri"]].append((n, r))
        for uri, group in by_uri.items():
            if uri in concepts:
                raise InputError(f"{uri} appears in both skills and skillGroups")
            if len(group) > 1:
                first = group[0][1]
                differing = sorted({f for _, r in group for f in r if r[f] != first[f]})
                if set(differing) - DUPLICATE_TOLERATED_FIELDS:
                    raise InputError(f"{paths[key].name}: {uri} repeated with different {differing}")
                kept_n, kept = max(group, key=lambda nr: (nr[1]["modifiedDate"], -nr[0]))
                for n, r in group:
                    duplicates.append({"esco_version": version, "concept_uri": uri,
                                       "source_file": paths[key].name, "source_row_number": n,
                                       "modified_date": r["modifiedDate"] or None,
                                       "differing_fields": json.dumps(differing), "kept": int(n == kept_n)})
            else:
                kept = group[0][1]
            alt, e1 = split_labels(kept["altLabels"])
            hidden, e2 = split_labels(kept["hiddenLabels"])
            empty_label_pieces += e1 + e2
            concepts[uri] = {
                "esco_version": version, "concept_uri": uri, "concept_type": kept["conceptType"],
                "preferred_label": kept["preferredLabel"], "alt_labels": json.dumps(alt, ensure_ascii=False),
                "hidden_labels": json.dumps(hidden, ensure_ascii=False),
                "description": kept["description"] or None, "definition": kept.get("definition") or None,
                "scope_note": kept["scopeNote"] or None, "skill_type": kept.get("skillType") or None,
                "reuse_level": kept.get("reuseLevel") or None, "code": kept.get("code") or None,
                "status": kept["status"] or None, "modified_date": kept["modifiedDate"] or None,
                "source_file": paths[key].name, "source_row_count": len(group),
                "_in_scheme": split_uris(kept["inScheme"]),
            }
    report["empty_label_pieces_dropped"] = empty_label_pieces

    members, unresolved_schemes = [], Counter()
    for c in concepts.values():
        for s in c.pop("_in_scheme"):
            if s in schemes:
                members.append({"esco_version": version, "concept_uri": c["concept_uri"], "scheme_uri": s})
            else:
                unresolved_schemes[s] += 1
    report["unresolved"]["inScheme"] = dict(unresolved_schemes)

    # --- broader relations
    broader, seen, unresolved_b, type_mismatch, label_mismatch = [], set(), [], 0, 0
    for n, r in enumerate(data["broaderRelationsSkillPillar"], start=1):
        child, parent = concepts.get(r["conceptUri"]), concepts.get(r["broaderUri"])
        if child is None or parent is None:
            unresolved_b.append({"row": n, "conceptUri": r["conceptUri"], "broaderUri": r["broaderUri"]})
            continue
        if child["concept_type"] != r["conceptType"] or parent["concept_type"] != r["broaderType"]:
            type_mismatch += 1
            continue
        if r["conceptUri"] == r["broaderUri"]:
            raise InputError(f"broader relation row {n} is a self-loop")
        pair = (r["conceptUri"], r["broaderUri"])
        if pair in seen:
            raise InputError(f"duplicate broader relation row {n}: {pair}")
        seen.add(pair)
        label_mismatch += (child["preferred_label"] != r["conceptLabel"]) + (parent["preferred_label"] != r["broaderLabel"])
        broader.append({"esco_version": version, "concept_uri": r["conceptUri"], "concept_type": r["conceptType"],
                        "broader_uri": r["broaderUri"], "broader_type": r["broaderType"]})
    report["unresolved"]["broader_relations"] = unresolved_b
    report["broader_type_mismatches"] = type_mismatch
    report["broader_label_mismatches"] = label_mismatch

    # --- skill-skill relations
    skill_rels, seen, unresolved_s, skilltype_mismatch = [], set(), [], 0
    for n, r in enumerate(data["skillSkillRelations"], start=1):
        a, b = concepts.get(r["originalSkillUri"]), concepts.get(r["relatedSkillUri"])
        if a is None or b is None or a["concept_type"] != "KnowledgeSkillCompetence" \
                or b["concept_type"] != "KnowledgeSkillCompetence":
            unresolved_s.append({"row": n, "originalSkillUri": r["originalSkillUri"],
                                 "relatedSkillUri": r["relatedSkillUri"]})
            continue
        pair = (r["originalSkillUri"], r["relatedSkillUri"])
        if pair in seen:
            raise InputError(f"duplicate skill relation row {n}: {pair}")
        seen.add(pair)
        skilltype_mismatch += (a["skill_type"] != r["originalSkillType"]) + (b["skill_type"] != r["relatedSkillType"])
        skill_rels.append({"esco_version": version, "original_skill_uri": r["originalSkillUri"],
                           "original_skill_type": r["originalSkillType"], "relation_type": r["relationType"],
                           "related_skill_type": r["relatedSkillType"], "related_skill_uri": r["relatedSkillUri"]})
    report["unresolved"]["skill_relations"] = unresolved_s
    report["skill_relation_skilltype_mismatches"] = skilltype_mismatch

    if unresolved_b or unresolved_s or unresolved_schemes or type_mismatch:
        raise InputError(
            f"unresolved references: broader={len(unresolved_b)} skill_relations={len(unresolved_s)} "
            f"inScheme={sum(unresolved_schemes.values())} broader_type_mismatches={type_mismatch}; "
            f"examples: {(unresolved_b + unresolved_s)[:3]}")

    # --- skillsHierarchy cross-check (validation only; no links are created from it)
    broader_pairs = {(b["concept_uri"], b["broader_uri"]) for b in broader}
    hier_links, hier_missing, hier_unknown = set(), [], 0
    for r in data["skillsHierarchy"]:
        chain = [r[f"Level {i} URI"] for i in range(4) if r[f"Level {i} URI"]]
        hier_unknown += sum(1 for u in chain if u not in concepts)
        for parent, child in zip(chain, chain[1:]):
            hier_links.add((child, parent))
    hier_missing = sorted(hier_links - broader_pairs)
    report["hierarchy_file"] = {"links": len(hier_links), "missing_from_broader_relations": len(hier_missing),
                                "unknown_uris": hier_unknown}
    if hier_missing or hier_unknown:
        report["warnings"].append(f"skillsHierarchy has {len(hier_missing)} links not in broader relations "
                                  f"and {hier_unknown} unknown URIs (not loaded; reported only)")

    # --- cycle check on broader graph
    parents = defaultdict(list)
    for c, p in broader_pairs:
        parents[c].append(p)
    state, cycles = {}, 0
    for start in parents:
        if state.get(start):
            continue
        stack = [(start, iter(parents[start]))]
        state[start] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                cycles += 1
            elif not state.get(nxt):
                state[nxt] = 1
                stack.append((nxt, iter(parents.get(nxt, []))))
    report["broader_cycles"] = cycles
    if cycles:
        raise InputError(f"broader relations contain {cycles} cycle(s)")

    scheme_rows = [{"esco_version": version, "scheme_uri": u, "concept_type": r["conceptType"],
                    "preferred_label": r["preferredLabel"] or None, "title": r["title"] or None,
                    "status": r["status"] or None, "description": r["description"] or None}
                   for u, r in schemes.items()]
    return {"concepts": list(concepts.values()), "schemes": scheme_rows, "members": members,
            "broader": broader, "skill_relations": skill_rels, "duplicates": duplicates, "report": report}


# ---------------------------------------------------------------------- database


def migration_statements(path: Path = MIGRATION_PATH) -> list[str]:
    statements, buf = [], ""
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if not buf and (not line.strip() or line.lstrip().startswith("--")):
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            statements.append(buf.strip())
            buf = ""
    if buf.strip():
        raise RuntimeError("migration file ends with an incomplete statement")
    return statements


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict], extra: dict) -> None:
    if not rows:
        return
    cols = list(rows[0]) + list(extra)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
    conn.executemany(sql, [{**r, **extra} for r in rows])


def files_digest(hashes: dict[str, str]) -> str:
    return hashlib.sha256("\n".join(f"{n}\t{h}" for n, h in sorted(hashes.items())).encode()).hexdigest()


def import_esco(conn: sqlite3.Connection, built: dict, *, version: str, language: str, source_dir: str,
                hashes: dict[str, str], acquired_on: str, acquisition_note: str,
                migration_path: Path = MIGRATION_PATH) -> dict:
    digest = files_digest(hashes)
    mig_sha = sha256_file(migration_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for stmt in migration_statements(migration_path):
            conn.execute(stmt)
        applied = conn.execute("SELECT sha256 FROM schema_migrations WHERE migration_id = ?", (MIGRATION_ID,)).fetchone()
        if applied is None:
            conn.execute("INSERT INTO schema_migrations VALUES (?, ?, ?, ?)",
                         (MIGRATION_ID, migration_path.name, mig_sha, now))
        elif applied[0] != mig_sha:
            raise ConflictError(f"migration {MIGRATION_ID} was applied from a different file version")

        existing = conn.execute("SELECT import_id, language, source_files_sha256 FROM esco_imports "
                                "WHERE esco_version = ?", (version,)).fetchall()
        for import_id, lang, sha in existing:
            if lang != language:
                raise ConflictError(f"ESCO {version} already imported in language {lang!r}; "
                                    "multi-language import is not supported by migration 002")
            if sha != digest:
                raise ConflictError(f"ESCO {version}/{language} already imported from different source "
                                    f"files (import {import_id}); refusing to overwrite")
            conn.execute("COMMIT")
            return {"import_id": import_id, "already_imported": True}
        if conn.execute("SELECT 1 FROM esco_concepts WHERE esco_version = ? LIMIT 1", (version,)).fetchone():
            raise ConflictError(f"esco_concepts already has {version} rows without an import record")

        cur = conn.execute(
            "INSERT INTO esco_imports (esco_version, language, source_dir, source_files_sha256, source_files, "
            "acquired_on, acquisition_note, importer_version, imported_at, concept_count, broader_count, "
            "skill_relation_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (version, language, source_dir, digest, json.dumps(hashes, sort_keys=True), acquired_on,
             acquisition_note, IMPORTER_VERSION, now, len(built["concepts"]), len(built["broader"]),
             len(built["skill_relations"])))
        extra = {"import_id": cur.lastrowid}
        _insert(conn, "esco_concept_schemes", built["schemes"], extra)
        _insert(conn, "esco_concepts", built["concepts"], extra)
        _insert(conn, "esco_concept_scheme_members", built["members"], {})
        _insert(conn, "esco_broader_relations", built["broader"], extra)
        _insert(conn, "esco_skill_relations", built["skill_relations"], extra)
        _insert(conn, "esco_source_duplicates", built["duplicates"], extra)
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ConflictError(f"foreign-key violations after import: {violations[:5]}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return {"import_id": extra["import_id"], "already_imported": False}


# --------------------------------------------------------------------------- CLI


def manifest_acquisition(root: Path, version: str, rel_paths: list[str]) -> tuple[str, str]:
    rows = [r for r in read_manifest(root / "data" / "reference_manifest.csv")
            if r["version"] == version and r["relative_path"] in rel_paths]
    dates = {r["acquired_on"] for r in rows}
    notes = {r["acquisition_evidence"] for r in rows}
    if len(dates) != 1 or len(notes) != 1:
        raise InputError(f"inconsistent acquisition records for {version}: {dates} / {notes}")
    return dates.pop(), notes.pop()


def run(db: Path, version: str, language: str, source_dir: Path | None, root: Path = REPO_ROOT) -> dict:
    root = root.resolve()
    try:
        folder = source_dir if source_dir is not None else find_extracted_dir(root, version, language)
    except RegistrationError as exc:
        raise InputError(str(exc)) from exc
    paths = source_paths(folder, language)
    hashes = verify_against_manifest(paths, version, root)
    acquired_on, note = manifest_acquisition(root, version,
                                             [p.resolve().relative_to(root).as_posix() for p in paths.values()])
    built = build(paths, version)
    conn = connect(db)
    try:
        result = import_esco(conn, built, version=version, language=language,
                             source_dir=folder.resolve().relative_to(root).as_posix(), hashes=hashes,
                             acquired_on=acquired_on, acquisition_note=note)
    finally:
        conn.close()
    return {**result, "built": built, "hashes": hashes}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Import ESCO skill-pillar CSVs into the local SQLite DB.")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--language", default="en")
    p.add_argument("--source-dir", default="auto", help="extracted ESCO folder, or 'auto' to locate by name")
    p.add_argument("--root", type=Path, default=REPO_ROOT)
    args = p.parse_args(argv)
    src = None if args.source_dir == "auto" else Path(args.source_dir)
    try:
        r = run(args.db, args.version, args.language, src, root=args.root)
    except InputError as exc:
        print(f"Invalid ESCO input, nothing imported: {exc}", file=sys.stderr)
        return 2
    except ConflictError as exc:
        print(f"Conflict, nothing imported: {exc}", file=sys.stderr)
        return 3
    except (sqlite3.Error, RuntimeError) as exc:
        print(f"Database error, nothing imported: {exc}", file=sys.stderr)
        return 4
    b = r["built"]
    state = "already imported (no changes)" if r["already_imported"] else f"imported (import_id={r['import_id']})"
    print(f"ESCO {args.version}/{args.language}: {state}")
    print(f"  concepts={len(b['concepts'])} broader={len(b['broader'])} skill_relations={len(b['skill_relations'])} "
          f"schemes={len(b['schemes'])} scheme_members={len(b['members'])} source_duplicate_rows={len(b['duplicates'])}")
    rep = b["report"]
    print(f"  unresolved: broader={len(rep['unresolved']['broader_relations'])} "
          f"skill_relations={len(rep['unresolved']['skill_relations'])} inScheme={sum(rep['unresolved']['inScheme'].values())}; "
          f"cycles={rep['broader_cycles']}; hierarchy-file links missing={rep['hierarchy_file']['missing_from_broader_relations']}")
    for w in rep["warnings"]:
        print(f"  warning: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
