"""Tests for src/load_postings.py. Uses temporary SQLite files and synthetic rows."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import load_postings as lp
import prepare_postings as pp

SNAP_A = "20261006T171338Z"
SNAP_B = "20261013T090000Z"


def row(job_id: int, snapshot: str = SNAP_A, text: str = "Build models.", board: str = "acme", **over) -> dict:
    r = {
        "posting_id": f"greenhouse:{board}:{job_id}",
        "source": "greenhouse",
        "source_job_id": str(job_id),
        "internal_job_id": str(job_id + 1000),
        "board_token": board,
        "company_name": "Acme Inc.",
        "source_company_name": "Acme",
        "title": "Data Analyst",
        "location": "Remote",
        "departments": ["Data"],
        "offices": ["New York", "Ōsaka"],
        "raw_text": f"&lt;p&gt;{text}&lt;/p&gt;",
        "clean_text": text,
        "absolute_url": f"https://job-boards.greenhouse.io/{board}/jobs/{job_id}",
        "source_updated_at": "2026-09-01T10:00:00-04:00",
        "fetched_at": "2026-10-06T17:13:38Z",
        "snapshot_id": snapshot,
        "industry": "Software",
        "industry_source": "test label",
        "source_language": "en",
        "text_hash": pp.text_hash(text),
        "word_count": pp.word_count(text),
        "is_placeholder": False,
        "exclusion_reason": "",
        "is_duplicate_of": None,
        "cleaning_version": "0.1.0",
    }
    r.update(over)
    return r


def flagged_rows(snapshot: str = SNAP_A) -> list[dict]:
    return [
        row(1, snapshot),
        row(2, snapshot, text="Ship code."),
        row(3, snapshot, title="Don't see what you're looking for?", is_placeholder=True,
            exclusion_reason="placeholder_title:dont_see_role"),
        row(4, snapshot, text="", raw_text=None, text_hash=None, word_count=0,
            exclusion_reason="missing_description"),
        row(5, snapshot, is_duplicate_of="greenhouse:acme:1", exclusion_reason="exact_duplicate"),
    ]


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def load_file(path: Path, db: Path) -> dict:
    rows, sha = lp.read_input(path)
    conn = lp.connect(db)
    try:
        lp.ensure_schema(conn)
        return lp.load(rows, sha, path.as_posix(), conn)
    finally:
        conn.close()


def query(db: Path, sql: str, params=()) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def table_counts(db: Path) -> dict[str, int]:
    return {t: query(db, f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("snapshots", "loads", "postings")}


# --------------------------------------------------------------------------- basics


def test_fields_match_cleaner_output():
    assert lp.FIELDS == pp.OUTPUT_FIELDS


def test_loads_all_rows_including_flagged(tmp_path):
    db = tmp_path / "t.sqlite"
    result = load_file(write_jsonl(tmp_path / "in.jsonl", flagged_rows()), db)
    assert result["inserted"] == 5 and result["unchanged"] == 0
    assert table_counts(db) == {"snapshots": 1, "loads": 1, "postings": 5}
    assert query(db, "SELECT COUNT(*) FROM usable_postings")[0][0] == 2
    reasons = dict(query(db, "SELECT posting_id, exclusion_reason FROM postings"))
    assert reasons["greenhouse:acme:3"] == "placeholder_title:dont_see_role"
    assert reasons["greenhouse:acme:4"] == "missing_description"


def test_every_field_round_trips(tmp_path):
    db = tmp_path / "t.sqlite"
    rows = flagged_rows()
    load_file(write_jsonl(tmp_path / "in.jsonl", rows), db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    stored = {r["posting_id"]: dict(r) for r in conn.execute("SELECT * FROM postings")}
    conn.close()
    for original in rows:
        s = stored[original["posting_id"]]
        back = {f: s[f] for f in lp.FIELDS}
        back["departments"] = json.loads(back["departments"])
        back["offices"] = json.loads(back["offices"])
        back["is_placeholder"] = bool(back["is_placeholder"])
        assert back == original


def test_provenance_recorded(tmp_path):
    db = tmp_path / "t.sqlite"
    path = write_jsonl(tmp_path / "in.jsonl", flagged_rows())
    load_file(path, db)
    [(snap, version, sha, n, inserted)] = query(
        db, "SELECT snapshot_id, cleaning_version, input_sha256, row_count, inserted_rows FROM loads")
    assert (snap, version, n, inserted) == (SNAP_A, "0.1.0", 5, 5)
    assert sha == hashlib.sha256(path.read_bytes()).hexdigest()
    assert query(db, "SELECT DISTINCT load_id FROM postings") == [(1,)]
    assert query(db, "SELECT value FROM schema_meta WHERE key='schema_version'") == [("1",)]


# --------------------------------------------------------------------------- repeat


def test_repeat_load_is_a_no_op(tmp_path):
    db = tmp_path / "t.sqlite"
    path = write_jsonl(tmp_path / "in.jsonl", flagged_rows())
    load_file(path, db)
    before = query(db, "SELECT * FROM postings ORDER BY posting_id")
    second = load_file(path, db)
    assert second["already_loaded"] is True
    assert second["inserted"] == 0 and second["unchanged"] == 5
    assert table_counts(db) == {"snapshots": 1, "loads": 1, "postings": 5}
    assert query(db, "SELECT * FROM postings ORDER BY posting_id") == before


def test_superset_input_adds_only_new_rows(tmp_path):
    db = tmp_path / "t.sqlite"
    load_file(write_jsonl(tmp_path / "a.jsonl", flagged_rows()[:2]), db)
    result = load_file(write_jsonl(tmp_path / "b.jsonl", flagged_rows()), db)
    assert result["inserted"] == 3 and result["unchanged"] == 2
    assert table_counts(db)["postings"] == 5


def test_conflicting_content_is_rejected_and_nothing_written(tmp_path):
    db = tmp_path / "t.sqlite"
    load_file(write_jsonl(tmp_path / "a.jsonl", flagged_rows()), db)
    before = query(db, "SELECT * FROM postings ORDER BY posting_id")

    changed = flagged_rows()
    changed[1] = row(2, text="Ship different code.")
    changed.append(row(6))  # a new row that must not sneak in
    with pytest.raises(lp.ConflictError, match="greenhouse:acme:2.*clean_text"):
        load_file(write_jsonl(tmp_path / "b.jsonl", changed), db)
    assert query(db, "SELECT * FROM postings ORDER BY posting_id") == before
    assert table_counts(db) == {"snapshots": 1, "loads": 1, "postings": 5}


def test_different_cleaning_version_for_same_snapshot_conflicts(tmp_path):
    db = tmp_path / "t.sqlite"
    load_file(write_jsonl(tmp_path / "a.jsonl", [row(1)]), db)
    with pytest.raises(lp.ConflictError, match="cleaning_version"):
        load_file(write_jsonl(tmp_path / "b.jsonl", [row(1, cleaning_version="0.2.0")]), db)


# ------------------------------------------------------------------------ snapshots


def test_same_posting_across_snapshots_keeps_history(tmp_path):
    db = tmp_path / "t.sqlite"
    load_file(write_jsonl(tmp_path / "a.jsonl", [row(1, SNAP_A, text="Old text.")]), db)
    load_file(write_jsonl(tmp_path / "b.jsonl", [row(1, SNAP_B, text="New text.",
                                                      fetched_at="2026-10-13T09:00:00Z")]), db)
    stored = query(db, "SELECT snapshot_id, clean_text FROM postings WHERE posting_id = ? ORDER BY snapshot_id",
                   ("greenhouse:acme:1",))
    assert stored == [(SNAP_A, "Old text."), (SNAP_B, "New text.")]
    assert table_counts(db) == {"snapshots": 2, "loads": 2, "postings": 2}


# ------------------------------------------------------------------------- rollback


def test_database_error_mid_load_rolls_back_everything(tmp_path, monkeypatch):
    db = tmp_path / "t.sqlite"
    rows = flagged_rows()
    real_to_db = lp.to_db

    def bad_to_db(r):
        out = real_to_db(r)
        if r["posting_id"] == "greenhouse:acme:4":
            out["departments"] = "not json"  # violates the CHECK constraint on insert
        return out

    monkeypatch.setattr(lp, "to_db", bad_to_db)
    with pytest.raises(sqlite3.IntegrityError):
        load_file(write_jsonl(tmp_path / "in.jsonl", rows), db)
    assert table_counts(db) == {"snapshots": 0, "loads": 0, "postings": 0}


def test_invalid_jsonl_loads_nothing(tmp_path):
    db = tmp_path / "t.sqlite"
    load_file(write_jsonl(tmp_path / "ok.jsonl", [row(1)]), db)
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(row(2)) + "\n{not json\n", encoding="utf-8")
    with pytest.raises(lp.InputError, match="line 2: invalid JSON"):
        load_file(bad, db)
    assert table_counts(db) == {"snapshots": 1, "loads": 1, "postings": 1}


def test_foreign_keys_enforced(tmp_path):
    db = tmp_path / "t.sqlite"
    load_file(write_jsonl(tmp_path / "in.jsonl", [row(1)]), db)
    conn = lp.connect(db)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        values = lp.to_db(row(9, snapshot="20991231T000000Z"))
        cols = ", ".join(lp.FIELDS)
        params = ", ".join(f":{f}" for f in lp.FIELDS)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute(f"INSERT INTO postings ({cols}, load_id) VALUES ({params}, 1)", values)
        dangling = lp.to_db(row(10, is_duplicate_of="greenhouse:acme:999", exclusion_reason="exact_duplicate"))
        conn.execute("BEGIN")
        conn.execute(f"INSERT INTO postings ({cols}, load_id) VALUES ({params}, 1)", dangling)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute("COMMIT")
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    assert table_counts(db)["postings"] == 1


# ----------------------------------------------------------------------- validation


@pytest.mark.parametrize("mutate, match", [
    (lambda r: r.pop("title"), "missing fields"),
    (lambda r: r.update(extra=1), "unexpected fields"),
    (lambda r: r.update(word_count="3"), "word_count"),
    (lambda r: r.update(is_placeholder="false"), "is_placeholder must be"),
    (lambda r: r.update(departments="Data"), "departments must be a list"),
    (lambda r: r.update(posting_id="greenhouse:acme:999"), "does not match"),
    (lambda r: r.update(snapshot_id="2026-10-06"), "invalid snapshot_id"),
    (lambda r: r.update(text_hash="abc"), "text_hash"),
    (lambda r: r.update(is_placeholder=True), "disagrees"),
    (lambda r: r.update(exclusion_reason="exact_duplicate"), "disagrees"),
])
def test_row_validation(tmp_path, mutate, match):
    r = row(1)
    mutate(r)
    with pytest.raises(lp.InputError, match=match):
        lp.read_input(write_jsonl(tmp_path / "in.jsonl", [r]))


@pytest.mark.parametrize("rows, match", [
    ([row(1), row(2, SNAP_B)], "exactly one snapshot_id"),
    ([row(1), row(2, cleaning_version="0.2.0")], "exactly one snapshot_id"),
    ([row(1), row(1)], "duplicate posting_id"),
    ([row(1, is_duplicate_of="greenhouse:acme:7", exclusion_reason="exact_duplicate")], "not in the input"),
    ([], "no rows"),
])
def test_file_validation(tmp_path, rows, match):
    with pytest.raises(lp.InputError, match=match):
        lp.read_input(write_jsonl(tmp_path / "in.jsonl", rows))


# ------------------------------------------------------------------------------ CLI


def test_cli_exit_codes(tmp_path, capsys):
    db = tmp_path / "t.sqlite"
    good = write_jsonl(tmp_path / "good.jsonl", flagged_rows())
    assert lp.main(["--input", str(good), "--db", str(db)]) == 0
    assert lp.main(["--input", str(good), "--db", str(db)]) == 0
    assert "already loaded" in capsys.readouterr().out

    conflict = write_jsonl(tmp_path / "conflict.jsonl", [row(1, text="Changed.")])
    assert lp.main(["--input", str(conflict), "--db", str(db)]) == 3
    assert lp.main(["--input", str(tmp_path / "missing.jsonl"), "--db", str(db)]) == 2
    assert table_counts(db)["postings"] == 5
