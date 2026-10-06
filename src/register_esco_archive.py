"""Register a manually downloaded ESCO archive (Sprint 1, Section B reference data).

The official ESCO portal (https://esco.ec.europa.eu/en/use-esco/download) delivers datasets
by an emailed link, so the archive is downloaded by a team member and then registered here:

    python src/register_esco_archive.py \
        --archive "~/Downloads/ESCO dataset - v1.2.1 - classification - en - csv.zip" \
        --version v1.2.1 --language en --downloaded-on 2026-10-07

What it does (no network access, never overwrites):
1. Copies the original archive to data/reference/esco/{version}/archive/ (byte-identical).
2. Validates every zip member (no absolute paths, no "..", no symlinks, size limits) BEFORE
   writing anything, then extracts to data/reference/esco/{version}/extracted/.
3. Records SHA-256 and size of the archive and every extracted file in the tracked
   manifest data/reference_manifest.csv, with source URL, version, download date, licence.
4. Writes reports/esco_headers_{version}.md listing each CSV's actual header and row count,
   which the ESCO loader will be designed from.

Re-registering the identical archive is a no-op. A different archive for the same version,
or an existing file with different content, is rejected and nothing is written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import stat
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_URL = "https://esco.ec.europa.eu/en/use-esco/download"
LICENCE = ("Commission Decision 2011/833/EU: free reuse for any purpose; acknowledge the source "
           "('This service uses the ESCO classification of the European Commission'); "
           "modified versions must be indicated as such. "
           "See https://esco.ec.europa.eu/en/about-esco/faq")
MANIFEST_FIELDS = ["dataset", "version", "language", "content", "file_format", "role",
                   "relative_path", "sha256", "bytes", "source_url", "acquired_on",
                   "acquisition_evidence", "registered_at", "licence"]
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+$")
MAX_TOTAL_UNCOMPRESSED = 2 * 1024**3   # 2 GiB
MAX_MEMBERS = 5000
MAX_RATIO = 200                        # uncompressed / compressed, zip-bomb guard


class RegistrationError(Exception):
    """The archive or its registration is invalid or conflicts with existing files."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    """Validate all members; return (info, relative path) for regular files."""
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise RegistrationError(f"archive has {len(infos)} members (limit {MAX_MEMBERS})")
    total, out, seen = 0, [], set()
    for info in infos:
        name = info.filename
        p = PurePosixPath(name)
        if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name) or ".." in p.parts or "\\" in name:
            raise RegistrationError(f"unsafe path in archive: {name!r}")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise RegistrationError(f"symlink in archive: {name!r}")
        if info.is_dir():
            continue
        if p.name.startswith("._") or "__MACOSX" in p.parts:
            continue  # macOS resource-fork noise, not data
        key = p.as_posix().casefold()
        if key in seen:
            raise RegistrationError(f"duplicate member (case-insensitive): {name!r}")
        seen.add(key)
        total += info.file_size
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
            raise RegistrationError(f"suspicious compression ratio for {name!r}")
        out.append((info, p))
    if total > MAX_TOTAL_UNCOMPRESSED:
        raise RegistrationError(f"archive expands to {total} bytes (limit {MAX_TOTAL_UNCOMPRESSED})")
    if not out:
        raise RegistrationError("archive contains no files")
    return out


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != MANIFEST_FIELDS:
            raise RegistrationError(f"{path} has unexpected columns {reader.fieldnames}")
        return list(reader)


def _write_new(dest: Path, data: bytes) -> None:
    """Write bytes to dest; never overwrite (link fails if dest exists)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.part")
    tmp.write_bytes(data)
    try:
        os.link(tmp, dest)
    finally:
        tmp.unlink()


def csv_headers(path: Path) -> tuple[list[str], int]:
    # Real ESCO fields exceed csv's 128 KiB default (conceptSchemes.hasTopConcept lists every top concept).
    csv.field_size_limit(max(csv.field_size_limit(), 64 * 1024 * 1024))
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        rows = sum(1 for _ in reader)
    return header, rows


def register(archive: Path, version: str, language: str, downloaded_on: str, root: Path = REPO_ROOT,
             content: str = "classification", file_format: str = "csv",
             source_url: str = SOURCE_URL) -> dict:
    archive = archive.expanduser()
    if not VERSION_RE.match(version):
        raise RegistrationError(f"version must look like v1.2.1, got {version!r}")
    try:
        if date.fromisoformat(downloaded_on) > date.today():
            raise RegistrationError("downloaded_on is in the future")
    except ValueError as exc:
        raise RegistrationError(f"downloaded_on must be YYYY-MM-DD: {exc}") from exc
    if not re.fullmatch(r"[a-z]{2}|all", language):
        raise RegistrationError("language must be a 2-letter code or 'all'")
    if not archive.is_file() or not zipfile.is_zipfile(archive):
        raise RegistrationError(f"not a zip archive: {archive}")

    base = root / "data" / "reference" / "esco" / version
    archive_dest = base / "archive" / archive.name
    extract_dir = base / "extracted"
    manifest_path = root / "data" / "reference_manifest.csv"
    manifest = read_manifest(manifest_path)
    archive_sha = sha256_file(archive)

    existing_archives = [r for r in manifest if r["dataset"] == "esco" and r["version"] == version
                         and r["role"] == "archive"]
    for r in existing_archives:
        if r["sha256"] != archive_sha:
            raise RegistrationError(
                f"ESCO {version} is already registered from a different archive "
                f"({r['relative_path']}, sha256 {r['sha256'][:12]}…); refusing to mix versions")

    # ---- plan and validate everything before writing anything
    with zipfile.ZipFile(archive) as zf:
        members = safe_members(zf)
        planned: list[tuple[Path, bytes]] = []
        for info, rel in members:
            data = zf.read(info)
            dest = extract_dir / Path(*rel.parts)
            if not dest.resolve().is_relative_to(extract_dir.resolve()):
                raise RegistrationError(f"member escapes extraction dir: {info.filename!r}")
            if dest.exists():
                if hashlib.sha256(data).hexdigest() != sha256_file(dest):
                    raise RegistrationError(f"existing file differs, not overwriting: {dest}")
            planned.append((dest, data))
    if archive_dest.exists() and sha256_file(archive_dest) != archive_sha:
        raise RegistrationError(f"existing archive differs, not overwriting: {archive_dest}")

    # ---- write (only files that do not exist yet)
    written = 0
    if not archive_dest.exists():
        archive_dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = archive_dest.with_name(f".{archive_dest.name}.part")
        shutil.copyfile(archive, tmp)
        try:
            os.link(tmp, archive_dest)
        finally:
            tmp.unlink()
        written += 1
    for dest, data in planned:
        if not dest.exists():
            _write_new(dest, data)
            written += 1

    entries = [("archive", archive_dest)] + [("extracted", d) for d, _ in planned]
    meta = {"version": version, "language": language, "content": content, "file_format": file_format,
            "source_url": source_url, "acquired_on": downloaded_on,
            "acquisition_evidence": "portal download date stated by the registrant"}
    added = _append_manifest(manifest_path, manifest, entries, meta, root)
    report = _write_header_report(
        root, version, extract_dir, [d for d, _ in planned],
        [f"Archive: `{archive_dest.relative_to(root).as_posix()}` (sha256 `{archive_sha}`)",
         f"Source: {source_url} · downloaded {downloaded_on} · language `{language}`"])
    csv_count = sum(1 for d, _ in planned if d.suffix.lower() == ".csv")
    return {"archive_sha256": archive_sha, "files_written": written, "manifest_rows_added": added,
            "csv_files": csv_count, "report": report, "already_registered": written == 0 and not added}


def _append_manifest(manifest_path: Path, manifest: list[dict], entries: list[tuple[str, Path]],
                     meta: dict, root: Path) -> int:
    """Append rows for files not yet recorded; reject a recorded path whose hash changed."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    known = {(r["dataset"], r["version"], r["relative_path"]): r["sha256"] for r in manifest}
    new_rows = []
    for role, path in entries:
        rel = path.relative_to(root).as_posix()
        digest = sha256_file(path)
        key = ("esco", meta["version"], rel)
        if key in known:
            if known[key] != digest:
                raise RegistrationError(f"manifest records a different hash for {rel}")
            continue
        new_rows.append({"dataset": "esco", **meta, "role": role, "relative_path": rel, "sha256": digest,
                         "bytes": path.stat().st_size, "registered_at": now, "licence": LICENCE})
    if new_rows:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not manifest_path.exists()
        with manifest_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if new_file:
                w.writeheader()
            w.writerows(new_rows)
    return len(new_rows)


def _write_header_report(root: Path, version: str, base_dir: Path, files: list[Path], intro: list[str]) -> Path:
    """Regenerate reports/esco_headers_{version}.md from the actual files."""
    csvs = sorted(p for p in files if p.suffix.lower() == ".csv")
    lines = [f"# ESCO {version} CSV headers (as found on disk)", "", *intro, "",
             "| File | Data rows | Columns |", "|---|---|---|"]
    for p in csvs:
        header, n = csv_headers(p)
        lines.append(f"| `{p.relative_to(base_dir).as_posix()}` | {n:,} | "
                     + ", ".join(f"`{h}`" for h in header) + " |")
    other = sorted(p for p in files if p.suffix.lower() != ".csv")
    if other:
        lines += ["", "Non-CSV files: " + ", ".join(f"`{p.relative_to(base_dir).as_posix()}`" for p in other)]
    report = root / "reports" / f"esco_headers_{version}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def find_extracted_dir(root: Path, version: str, language: str = "en", content: str = "classification") -> Path:
    """Locate the user-extracted folder by its documented name prefix; exactly one must match."""
    prefix = f"ESCO dataset - {version} - {content} - {language} - csv"
    matches = sorted(p for p in (root / "data" / "reference").iterdir() if p.is_dir() and p.name.startswith(prefix))
    if len(matches) != 1:
        raise RegistrationError(f"expected exactly one folder starting with {prefix!r} under data/reference, "
                                f"found {[m.name for m in matches]}")
    return matches[0]


def register_extracted_dir(source_dir: Path, version: str, language: str, acquired_on: str,
                           acquisition_evidence: str, root: Path = REPO_ROOT,
                           content: str = "classification", source_url: str = SOURCE_URL) -> dict:
    """Record hashes of an already-extracted folder in place (read-only; nothing is copied or moved).

    Used when the original ZIP is not available: no archive row is written and no archive hash
    is claimed. `acquisition_evidence` must say where `acquired_on` comes from.
    """
    if not VERSION_RE.match(version):
        raise RegistrationError(f"version must look like v1.2.1, got {version!r}")
    try:
        if date.fromisoformat(acquired_on) > date.today():
            raise RegistrationError("acquired_on is in the future")
    except ValueError as exc:
        raise RegistrationError(f"acquired_on must be YYYY-MM-DD: {exc}") from exc
    if not acquisition_evidence.strip():
        raise RegistrationError("acquisition_evidence is required")
    source_dir = source_dir.resolve()
    if not source_dir.is_dir() or not source_dir.is_relative_to((root / "data" / "reference").resolve()):
        raise RegistrationError(f"source dir must be a folder under data/reference: {source_dir}")
    files = sorted(p for p in source_dir.rglob("*") if p.is_file() and not p.name.startswith(".")
                   and not p.is_symlink())
    if not any(p.suffix.lower() == ".csv" for p in files):
        raise RegistrationError(f"no CSV files in {source_dir}")
    manifest_path = root / "data" / "reference_manifest.csv"
    manifest = read_manifest(manifest_path)
    meta = {"version": version, "language": language, "content": content, "file_format": "csv",
            "source_url": source_url, "acquired_on": acquired_on, "acquisition_evidence": acquisition_evidence}
    added = _append_manifest(manifest_path, manifest, [("source_file", p) for p in files], meta, root.resolve())
    report = _write_header_report(
        root, version, source_dir, files,
        [f"Folder: `{source_dir.relative_to(root.resolve()).as_posix()}` (registered in place)",
         "Original ZIP: **not available**; no archive hash recorded.",
         f"Source: {source_url} · acquired {acquired_on} ({acquisition_evidence}) · language `{language}`"])
    return {"files": len(files), "manifest_rows_added": added, "report": report,
            "csv_files": sum(1 for p in files if p.suffix.lower() == ".csv"), "already_registered": added == 0}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Register ESCO source files (original ZIP, or an extracted folder).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--archive", type=Path, help="original ZIP from the ESCO portal")
    src.add_argument("--extracted-dir", type=Path,
                     help="already-extracted folder under data/reference (use 'auto' to locate by name)")
    p.add_argument("--version", required=True, help="e.g. v1.2.1")
    p.add_argument("--language", default="en")
    p.add_argument("--downloaded-on", help="YYYY-MM-DD portal download date (with --archive)")
    p.add_argument("--acquired-on", help="YYYY-MM-DD acquisition date (with --extracted-dir)")
    p.add_argument("--acquisition-evidence", help="where --acquired-on comes from (with --extracted-dir)")
    p.add_argument("--content", default="classification")
    p.add_argument("--root", type=Path, default=REPO_ROOT)
    args = p.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.archive:
            if not args.downloaded_on:
                raise RegistrationError("--downloaded-on is required with --archive")
            r = register(args.archive, args.version, args.language, args.downloaded_on,
                         root=root, content=args.content)
            state = "already registered (no changes)" if r["already_registered"] else "registered"
            print(f"ESCO {args.version}: {state}; archive sha256 {r['archive_sha256']}")
            print(f"  files written={r['files_written']} manifest rows added={r['manifest_rows_added']} "
                  f"csv files={r['csv_files']}")
        else:
            if not args.acquired_on or not args.acquisition_evidence:
                raise RegistrationError("--acquired-on and --acquisition-evidence are required with --extracted-dir")
            folder = (find_extracted_dir(root, args.version, args.language, args.content)
                      if str(args.extracted_dir) == "auto" else args.extracted_dir)
            r = register_extracted_dir(folder, args.version, args.language, args.acquired_on,
                                       args.acquisition_evidence, root=root, content=args.content)
            state = "already registered (no changes)" if r["already_registered"] else "registered in place"
            print(f"ESCO {args.version}: {state}; folder {folder}")
            print(f"  files={r['files']} manifest rows added={r['manifest_rows_added']} csv files={r['csv_files']}"
                  " (original ZIP not available: no archive hash recorded)")
    except (RegistrationError, zipfile.BadZipFile, OSError) as exc:
        print(f"Not registered: {exc}", file=sys.stderr)
        return 2
    print(f"  headers: {r['report']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
