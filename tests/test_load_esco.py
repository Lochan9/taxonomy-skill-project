"""Tests for src/load_esco.py.

Fixtures use the real ESCO v1.2.1 header names with tiny SYNTHETIC rows (example.org URIs);
they are not ESCO content.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from pathlib import Path

import pytest

import load_esco as le
import load_postings as lp
import register_esco_archive as reg
from test_load_postings import flagged_rows, row, write_jsonl

V = "v9.9.9"
U = "http://example.org/esco/"
H = le.EXPECTED_HEADERS


def csv_text(header: list[str], rows: list[list[str]], ragged: bool = False) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(r if ragged else r + [""] * (len(header) - len(r)))
    return buf.getvalue()


def fixture_files() -> dict[str, str]:
    skills = [
        ["KnowledgeSkillCompetence", U + "s1", "skill/competence", "cross-sector", "use Python",
         "write Python\nPython programming\n", "", "released", "2024-01-01T00:00:00Z", "", "",
         f"{U}scheme/skills,\n{U}scheme/member", "Write programs in Python."],
        ["KnowledgeSkillCompetence", U + "s2", "knowledge", "sector-specific", "statistics", "", "", "released",
         "2024-01-01T00:00:00Z", "", "", f"{U}scheme/skills", "The study of data."],
        ["KnowledgeSkillCompetence", U + "s1", "skill/competence", "cross-sector", "use Python",
         "write Python\nPython programming\n", "", "released", "2025-06-01T00:00:00Z", "", "",
         f"{U}scheme/skills,\n{U}scheme/member", "Write programs in Python."],  # repeat, newer date
    ]
    groups = [
        ["SkillGroup", U + "g0", "skills", "", "", "released", "", "", f"{U}scheme/skills", "", "S"],
        ["SkillGroup", U + "g1", "computing", "", "", "released", "", "", f"{U}scheme/skills", "Computing.", "S1"],
    ]
    schemes = [["ConceptScheme", f"{U}scheme/skills", "ESCO skills", "Skills", "released", "", U + "g0"],
               ["ConceptScheme", f"{U}scheme/member", "Member skills", "", "released", "", ""]]
    broader = [["SkillGroup", U + "g1", "computing", "SkillGroup", U + "g0", "skills"],
               ["KnowledgeSkillCompetence", U + "s1", "use Python", "SkillGroup", U + "g1", "computing"],
               ["KnowledgeSkillCompetence", U + "s2", "statistics", "KnowledgeSkillCompetence", U + "s1", "use Python"]]
    skillrel = [[U + "s1", "skill/competence", "optional", "knowledge", U + "s2"]]
    hierarchy = [[U + "g0", "skills", "", "", "", "", "", "", "", "", "S"],      # ragged (11 of 14 fields)
                 [U + "g0", "skills", U + "g1", "computing", "", "", "", "", "Computing.", "", "S", "S1"]]
    return {
        "skills": csv_text(H["skills"], skills),
        "skillGroups": csv_text(H["skillGroups"], groups),
        "conceptSchemes": csv_text(H["conceptSchemes"], schemes),
        "broaderRelationsSkillPillar": csv_text(H["broaderRelationsSkillPillar"], broader),
        "skillSkillRelations": csv_text(H["skillSkillRelations"], skillrel),
        "skillsHierarchy": csv_text(H["skillsHierarchy"], hierarchy, ragged=True),
    }


def make_source(root: Path, files: dict[str, str] | None = None, suffix: str = "", register: bool = True) -> Path:
    d = root / "data" / "reference" / f"ESCO dataset - {V} - classification - en - csv{suffix}"
    d.mkdir(parents=True)
    for key, text in (files or fixture_files()).items():
        (d / f"{key}_en.csv").write_text(text, encoding="utf-8")
    if register:
        reg.register_extracted_dir(d, V, "en", "2026-10-06", "test fixture", root=root)
    return d


def seed_postings(db: Path, tmp: Path) -> None:
    p = write_jsonl(tmp / "postings.jsonl", flagged_rows())
    rows, sha = lp.read_input(p)
    conn = lp.connect(db)
    lp.ensure_schema(conn)
    lp.load(rows, sha, p.as_posix(), conn)
    conn.close()


def q(db: Path, sql: str, params=()):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def tables(db: Path) -> set[str]:
    return {r[0] for r in q(db, "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}


def counts(db: Path) -> dict[str, int]:
    return {t: q(db, f"SELECT COUNT(*) FROM {t}")[0][0] for t in sorted(tables(db))
            if t.startswith("esco_") or t in {"postings", "loads", "snapshots", "schema_migrations"}}


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "repo"
    db = root / "data" / "processed" / "t.sqlite"
    db.parent.mkdir(parents=True)
    seed_postings(db, tmp_path)
    return root, db


# ------------------------------------------------------------------------ success


def test_successful_import(env):
    root, db = env
    make_source(root)
    postings_before = q(db, "SELECT * FROM postings ORDER BY posting_id")
    r = le.run(db, V, "en", None, root=root)
    assert r["already_imported"] is False

    c = counts(db)
    assert c["esco_concepts"] == 4 and c["esco_broader_relations"] == 3 and c["esco_skill_relations"] == 1
    assert c["esco_concept_schemes"] == 2 and c["esco_concept_scheme_members"] == 5
    assert c["esco_narrower_relations"] == 3 and c["esco_source_duplicates"] == 2
    assert dict(q(db, "SELECT concept_type, COUNT(*) FROM esco_concepts GROUP BY 1")) == \
        {"KnowledgeSkillCompetence": 2, "SkillGroup": 2}

    [(label, alt, mdate, n)] = q(db, "SELECT preferred_label, alt_labels, modified_date, source_row_count "
                                     "FROM esco_concepts WHERE concept_uri = ?", (U + "s1",))
    assert label == "use Python" and json.loads(alt) == ["write Python", "Python programming"]
    assert mdate == "2025-06-01T00:00:00Z" and n == 2  # latest repeated row kept
    assert q(db, "SELECT source_row_number, kept, differing_fields FROM esco_source_duplicates ORDER BY 1") == \
        [(1, 0, '["modifiedDate"]'), (3, 1, '["modifiedDate"]')]
    # Source terminology preserved verbatim.
    assert q(db, "SELECT relation_type, original_skill_type, related_skill_type FROM esco_skill_relations") == \
        [("optional", "skill/competence", "knowledge")]
    assert q(db, "SELECT narrower_uri FROM esco_narrower_relations WHERE concept_uri = ?", (U + "g0",)) == [(U + "g1",)]
    # Provenance.
    [(ver, lang, acq, note, files)] = q(db, "SELECT esco_version, language, acquired_on, acquisition_note, source_files FROM esco_imports")
    assert (ver, lang, acq, note) == (V, "en", "2026-10-06", "test fixture") and len(json.loads(files)) == 6
    assert q(db, "SELECT migration_id, name FROM schema_migrations") == [("002", "migration_002_esco_reference.sql")]
    # Existing data untouched.
    assert q(db, "SELECT * FROM postings ORDER BY posting_id") == postings_before
    assert q(db, "SELECT value FROM schema_meta WHERE key='schema_version'") == [("1",)]
    assert q(db, "PRAGMA integrity_check") == [("ok",)] and q(db, "PRAGMA foreign_key_check") == []
    rep = r["built"]["report"]
    assert rep["hierarchy_file"] == {"links": 1, "missing_from_broader_relations": 0, "unknown_uris": 0}
    assert rep["broader_cycles"] == 0 and rep["empty_label_pieces_dropped"] == 1


def test_postings_loader_still_works_after_migration(env, tmp_path):
    root, db = env
    make_source(root)
    le.run(db, V, "en", None, root=root)
    p = write_jsonl(tmp_path / "later.jsonl", [row(1, snapshot="20261013T090000Z")])
    rows, sha = lp.read_input(p)
    conn = lp.connect(db)
    lp.ensure_schema(conn)
    assert lp.load(rows, sha, p.as_posix(), conn)["inserted"] == 1
    conn.close()
    assert counts(db)["esco_concepts"] == 4


# ------------------------------------------------------------------------- repeat


def test_repeat_import_is_a_no_op(env):
    root, db = env
    make_source(root)
    le.run(db, V, "en", None, root=root)
    before = counts(db)
    snapshot = q(db, "SELECT * FROM esco_imports")
    again = le.run(db, V, "en", None, root=root)
    assert again["already_imported"] is True
    assert counts(db) == before and q(db, "SELECT * FROM esco_imports") == snapshot


# ------------------------------------------------------------- invalid + rollback


def test_header_mismatch_rejected_before_touching_db(env):
    root, db = env
    files = fixture_files()
    files["skills"] = files["skills"].replace("preferredLabel", "prefLabel", 1)
    make_source(root, files)
    before = tables(db)
    with pytest.raises(le.InputError, match="header"):
        le.run(db, V, "en", None, root=root)
    assert tables(db) == before


def test_database_failure_rolls_back_migration_and_rows(env, monkeypatch):
    root, db = env
    make_source(root)
    before_tables, before_postings = tables(db), q(db, "SELECT COUNT(*) FROM postings")
    real = le._insert

    def failing(conn, table, rows, extra):
        if table == "esco_broader_relations":
            raise sqlite3.OperationalError("simulated failure mid-import")
        real(conn, table, rows, extra)

    monkeypatch.setattr(le, "_insert", failing)
    with pytest.raises(sqlite3.OperationalError, match="simulated"):
        le.run(db, V, "en", None, root=root)
    assert tables(db) == before_tables  # migration DDL rolled back too
    assert q(db, "SELECT COUNT(*) FROM postings") == before_postings


def test_unregistered_or_modified_source_rejected(env):
    root, db = env
    d = make_source(root, register=False)
    with pytest.raises(le.InputError, match="not registered"):
        le.run(db, V, "en", None, root=root)
    reg.register_extracted_dir(d, V, "en", "2026-10-06", "test fixture", root=root)
    (d / "skills_en.csv").write_text(fixture_files()["skills"] + "\n", encoding="utf-8")
    with pytest.raises(le.InputError, match="does not match its registered SHA-256"):
        le.run(db, V, "en", None, root=root)


def test_ragged_rows_only_tolerated_in_hierarchy(env):
    root, db = env
    files = fixture_files()
    files["skillSkillRelations"] = csv_text(H["skillSkillRelations"], [[U + "s1", "skill/competence", "optional"]], ragged=True)
    make_source(root, files)
    with pytest.raises(le.InputError, match="fields, expected"):
        le.run(db, V, "en", None, root=root)


def test_repeated_uri_with_different_content_rejected(env):
    root, db = env
    files = fixture_files()
    # Edit the parsed records (altLabels contain embedded newlines, so text lines != records).
    records = list(csv.reader(io.StringIO(files["skills"])))
    records[3][H["skills"].index("description")] = "Something else."  # the repeated s1 row
    files["skills"] = csv_text(records[0], records[1:])
    make_source(root, files)
    with pytest.raises(le.InputError, match="repeated with different"):
        le.run(db, V, "en", None, root=root)


# ----------------------------------------------------------------------- conflict


def test_conflicting_import_rejected(env):
    root, db = env
    make_source(root)
    le.run(db, V, "en", None, root=root)
    before = counts(db)
    files = fixture_files()
    files["skills"] = files["skills"].replace("The study of data.", "Changed description.")
    other = make_source(root, files, suffix=" (re-download)")
    with pytest.raises(le.ConflictError, match="different source files"):
        le.run(db, V, "en", other, root=root)
    assert counts(db) == before


# ----------------------------------------------------------- relationship checks


@pytest.mark.parametrize("bad_row, match", [
    (["KnowledgeSkillCompetence", U + "s2", "statistics", "SkillGroup", U + "missing", "?"], "unresolved references: broader=1"),
    (["KnowledgeSkillCompetence", U + "s2", "statistics", "SkillGroup", U + "s1", "use Python"], "broader_type_mismatches=1"),
    (["KnowledgeSkillCompetence", U + "s2", "statistics", "KnowledgeSkillCompetence", U + "s2", "statistics"], "self-loop"),
    (["SkillGroup", U + "g0", "skills", "KnowledgeSkillCompetence", U + "s2", "statistics"], "cycle"),
])
def test_broader_relation_validation(env, bad_row, match):
    root, db = env
    files = fixture_files()
    files["broaderRelationsSkillPillar"] += csv_text(H["broaderRelationsSkillPillar"], [bad_row]).split("\n", 1)[1]
    make_source(root, files)
    before = tables(db)
    with pytest.raises(le.InputError, match=match):
        le.run(db, V, "en", None, root=root)
    assert tables(db) == before


def test_skill_relation_endpoint_must_be_a_skill(env):
    root, db = env
    files = fixture_files()
    files["skillSkillRelations"] = csv_text(H["skillSkillRelations"], [[U + "s1", "skill/competence", "optional", "knowledge", U + "g1"]])
    make_source(root, files)
    with pytest.raises(le.InputError, match="skill_relations=1"):
        le.run(db, V, "en", None, root=root)


def test_unknown_scheme_reference_rejected(env):
    root, db = env
    files = fixture_files()
    files["skillGroups"] = files["skillGroups"].replace(f"{U}scheme/skills,Computing.", f"{U}scheme/nope,Computing.")
    make_source(root, files)
    with pytest.raises(le.InputError, match="inScheme=1"):
        le.run(db, V, "en", None, root=root)


def test_hierarchy_file_link_missing_is_warning_not_invented(env):
    root, db = env
    files = fixture_files()
    files["skillsHierarchy"] = csv_text(H["skillsHierarchy"], [[U + "g1", "computing", U + "g0", "skills"]])
    make_source(root, files)
    r = le.run(db, V, "en", None, root=root)
    assert r["built"]["report"]["hierarchy_file"]["missing_from_broader_relations"] == 1
    assert r["built"]["report"]["warnings"]
    # Only the 3 source broader relations exist; the hierarchy-file link was not added.
    assert counts(db)["esco_broader_relations"] == 3


def test_cli_exit_codes(env, capsys):
    root, db = env
    make_source(root)
    args = ["--db", str(db), "--version", V, "--root", str(root)]
    assert le.main(args) == 0
    assert le.main(args) == 0
    assert "already imported" in capsys.readouterr().out
    assert le.main(["--db", str(db), "--version", "v0.0.1", "--root", str(root)]) == 2
