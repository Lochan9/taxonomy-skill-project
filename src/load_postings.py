"""Load processed postings (JSONL) into a LOCAL SQLite database for development (Sprint 1).

    python src/load_postings.py \
        --input data/processed/postings_20261006T171338Z.jsonl \
        --db data/processed/taxonomy_pilot.sqlite

This is a local development store only; the shared database choice is still pending with
Section A (data contract D3). Schema: sql/schema_v1.sql.

Guarantees:
- Every row is stored, including flagged ones; `usable_postings` is a view over the rest.
- Rows are keyed by (snapshot_id, posting_id), so later snapshots never overwrite history.
- The whole input is validated before writing and loaded in one transaction; any error rolls
  everything back.
- Re-loading identical input is a no-op. A row whose key already exists with different
  content is rejected (ConflictError) and nothing from that input is written.
- Never UPDATEs or DELETEs existing data. Foreign keys are enforced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "sql" / "schema_v1.sql"
SCHEMA_VERSION = "1"
LOADER_VERSION = "0.1.0"
MIN_SQLITE = (3, 37, 0)

# Exactly the fields written by src/prepare_postings.py (data contract §2).
FIELDS = [
    "posting_id", "source", "source_job_id", "internal_job_id", "board_token",
    "company_name", "source_company_name", "title", "location", "departments", "offices",
    "raw_text", "clean_text", "absolute_url", "source_updated_at", "fetched_at",
    "snapshot_id", "industry", "industry_source", "source_language", "text_hash",
    "word_count", "is_placeholder", "exclusion_reason", "is_duplicate_of", "cleaning_version",
]
REQUIRED_STR = {"posting_id", "source", "source_job_id", "board_token", "company_name",
                "clean_text", "fetched_at", "snapshot_id", "exclusion_reason", "cleaning_version"}
OPTIONAL_STR = set(FIELDS) - REQUIRED_STR - {"departments", "offices", "word_count", "is_placeholder"}
LIST_FIELDS = ("departments", "offices")
SNAPSHOT_RE = re.compile(r"^\d{8}T\d{6}Z$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class InputError(Exception):
    """The processed input is malformed."""


class ConflictError(Exception):
    """An existing (snapshot_id, posting_id) row has different content."""


# ------------------------------------------------------------------------ validation


def _check_row(row: object, lineno: int) -> dict:
    where = f"line {lineno}"
    if not isinstance(row, dict):
        raise InputError(f"{where}: expected a JSON object")
    missing, extra = set(FIELDS) - set(row), set(row) - set(FIELDS)
    if missing or extra:
        raise InputError(f"{where}: missing fields {sorted(missing)}, unexpected fields {sorted(extra)}")

    for f in REQUIRED_STR:
        if not isinstance(row[f], str):
            raise InputError(f"{where}: {f} must be a string")
    for f in OPTIONAL_STR:
        if row[f] is not None and not isinstance(row[f], str):
            raise InputError(f"{where}: {f} must be a string or null")
    for f in LIST_FIELDS:
        if not isinstance(row[f], list) or not all(isinstance(x, str) for x in row[f]):
            raise InputError(f"{where}: {f} must be a list of strings")
    if not isinstance(row["word_count"], int) or isinstance(row["word_count"], bool) or row["word_count"] < 0:
        raise InputError(f"{where}: word_count must be a non-negative integer")
    if not isinstance(row["is_placeholder"], bool):
        raise InputError(f"{where}: is_placeholder must be true or false")

    pid = row["posting_id"]
    if pid != f"{row['source']}:{row['board_token']}:{row['source_job_id']}":
        raise InputError(f"{where}: posting_id {pid!r} does not match source:board_token:source_job_id")
    if not SNAPSHOT_RE.match(row["snapshot_id"]):
        raise InputError(f"{where}: invalid snapshot_id {row['snapshot_id']!r}")
    if row["text_hash"] is not None and not HASH_RE.match(row["text_hash"]):
        raise InputError(f"{where}: text_hash is not a SHA-256 hex digest")

    reasons = [r for r in row["exclusion_reason"].split(";") if r]
    if row["is_placeholder"] != any(r.startswith("placeholder_") for r in reasons):
        raise InputError(f"{where}: is_placeholder disagrees with exclusion_reason")
    if (row["is_duplicate_of"] is not None) != ("exact_duplicate" in reasons):
        raise InputError(f"{where}: is_duplicate_of disagrees with exclusion_reason")
    return row


def read_input(path: Path) -> tuple[list[dict], str]:
    """Parse and validate the whole JSONL file. Returns (rows, sha256 of the file bytes)."""
    if not path.is_file():
        raise InputError(f"Input file not found: {path}")
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"{path} is not valid UTF-8: {exc}") from exc

    rows: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise InputError(f"line {lineno}: blank line")
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InputError(f"line {lineno}: invalid JSON: {exc}") from exc
        rows.append(_check_row(obj, lineno))
    if not rows:
        raise InputError(f"{path} contains no rows")

    snapshots = {r["snapshot_id"] for r in rows}
    versions = {r["cleaning_version"] for r in rows}
    sources = {r["source"] for r in rows}
    if len(snapshots) != 1 or len(versions) != 1 or len(sources) != 1:
        raise InputError(
            f"input must hold exactly one snapshot_id, cleaning_version and source; got "
            f"{sorted(snapshots)}, {sorted(versions)}, {sorted(sources)}"
        )
    ids = [r["posting_id"] for r in rows]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise InputError(f"duplicate posting_id within input: {dupes[:5]}")
    known = set(ids)
    for r in rows:
        if r["is_duplicate_of"] is not None and r["is_duplicate_of"] not in known:
            raise InputError(f"{r['posting_id']}: is_duplicate_of {r['is_duplicate_of']!r} is not in the input")
    return rows, hashlib.sha256(data).hexdigest()


# -------------------------------------------------------------------------- database


def to_db(row: dict) -> dict:
    out = dict(row)
    for f in LIST_FIELDS:
        out[f] = json.dumps(row[f], ensure_ascii=False)
    out["is_placeholder"] = int(row["is_placeholder"])
    return out


def connect(db_path: Path) -> sqlite3.Connection:
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise RuntimeError(f"SQLite {sqlite3.sqlite_version} is too old; need >= 3.37 for STRICT tables")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)  # explicit BEGIN/COMMIT below
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("could not enable foreign-key enforcement")
    return conn


def ensure_schema(conn: sqlite3.Connection, schema_path: Path = SCHEMA_PATH) -> None:
    conn.executescript(schema_path.read_text(encoding="utf-8"))  # idempotent (IF NOT EXISTS)
    conn.execute("PRAGMA foreign_keys = ON")  # executescript does not reset it, but be explicit
    version = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    if version is None or version[0] != SCHEMA_VERSION:
        raise RuntimeError(f"database schema version {version and version[0]!r}, expected {SCHEMA_VERSION}")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(rows: list[dict], input_sha256: str, input_path: str, conn: sqlite3.Connection) -> dict:
    """Insert rows in one transaction. Returns counts; raises ConflictError on mismatch."""
    snapshot_id = rows[0]["snapshot_id"]
    cleaning_version = rows[0]["cleaning_version"]
    db_rows = [to_db(r) for r in rows]
    now = _utcnow()

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT OR IGNORE INTO snapshots (snapshot_id, source, first_loaded_at) VALUES (?, ?, ?)",
            (snapshot_id, rows[0]["source"], now),
        )
        existing_snapshot_source = conn.execute(
            "SELECT source FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()[0]
        if existing_snapshot_source != rows[0]["source"]:
            raise ConflictError(f"snapshot {snapshot_id} is recorded with source {existing_snapshot_source!r}")

        prior = conn.execute(
            "SELECT load_id FROM loads WHERE snapshot_id = ? AND cleaning_version = ? AND input_sha256 = ?",
            (snapshot_id, cleaning_version, input_sha256),
        ).fetchone()

        cols = ", ".join(FIELDS)
        select_existing = f"SELECT {cols} FROM postings WHERE snapshot_id = ? AND posting_id = ?"
        new_rows, unchanged = [], 0
        for r in db_rows:
            existing = conn.execute(select_existing, (snapshot_id, r["posting_id"])).fetchone()
            if existing is None:
                new_rows.append(r)
                continue
            diffs = [f for f in FIELDS if existing[f] != r[f]]
            if diffs:
                raise ConflictError(
                    f"({snapshot_id}, {r['posting_id']}) already stored with different "
                    f"{', '.join(diffs[:5])}; refusing to overwrite"
                )
            unchanged += 1

        if prior is not None and new_rows:
            raise ConflictError("identical input was loaded before but rows are missing; database inconsistent")

        load_id = prior[0] if prior is not None else None
        if prior is None:
            cur = conn.execute(
                "INSERT INTO loads (snapshot_id, cleaning_version, input_path, input_sha256, row_count, "
                "inserted_rows, loader_version, loaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (snapshot_id, cleaning_version, input_path, input_sha256, len(rows), len(new_rows),
                 LOADER_VERSION, now),
            )
            load_id = cur.lastrowid

        placeholders = ", ".join(f":{f}" for f in FIELDS)
        conn.executemany(
            f"INSERT INTO postings ({cols}, load_id) VALUES ({placeholders}, :load_id)",
            [{**r, "load_id": load_id} for r in new_rows],
        )
        conn.execute("COMMIT")  # deferred FK checks run here
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    return {
        "snapshot_id": snapshot_id,
        "cleaning_version": cleaning_version,
        "load_id": load_id,
        "input_rows": len(rows),
        "inserted": len(new_rows),
        "unchanged": unchanged,
        "already_loaded": prior is not None,
    }


# ----------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Load processed postings JSONL into a local SQLite DB.")
    p.add_argument("--input", type=Path, required=True, help="processed JSONL from prepare_postings.py")
    p.add_argument("--db", type=Path, required=True, help="SQLite database file (created if missing)")
    args = p.parse_args(argv)

    try:
        rows, sha = read_input(args.input)
        conn = connect(args.db)
        try:
            ensure_schema(conn)
            result = load(rows, sha, args.input.as_posix(), conn)
        finally:
            conn.close()
    except InputError as exc:
        print(f"Invalid input, nothing loaded: {exc}", file=sys.stderr)
        return 2
    except ConflictError as exc:
        print(f"Conflict, nothing loaded: {exc}", file=sys.stderr)
        return 3
    except (sqlite3.Error, RuntimeError) as exc:
        print(f"Database error, nothing loaded: {exc}", file=sys.stderr)
        return 4

    state = "already loaded (no changes)" if result["already_loaded"] else f"load_id={result['load_id']}"
    print(f"Snapshot {result['snapshot_id']} (cleaning {result['cleaning_version']}): {state}")
    print(f"  input rows={result['input_rows']} inserted={result['inserted']} unchanged={result['unchanged']}")
    print(f"  database: {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
