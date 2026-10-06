"""Tests for src/register_esco_archive.py.

Uses tiny synthetic zip fixtures with made-up column names. They are NOT ESCO data and say
nothing about real ESCO headers; they only exercise hashing, safe extraction and the manifest.
"""

from __future__ import annotations

import hashlib
import stat
import zipfile
from pathlib import Path

import pytest

import register_esco_archive as reg

V = "v9.9.9"


def make_zip(path: Path, members: dict[str, bytes], symlink: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return path


FIXTURE = {"fixture_a.csv": b"colA,colB\n1,x\n2,y\n", "sub/fixture_b.csv": b"\xef\xbb\xbfid,name\n9,z\n",
           "README.txt": b"fixture"}


def files_under(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_registers_archive_extracts_and_records_hashes(tmp_path):
    src = make_zip(tmp_path / "dl.zip", FIXTURE)
    root = tmp_path / "repo"
    r = reg.register(src, V, "en", "2026-10-06", root=root)

    base = root / "data/reference/esco" / V
    assert (base / "archive/dl.zip").read_bytes() == src.read_bytes()
    assert (base / "extracted/sub/fixture_b.csv").read_bytes() == FIXTURE["sub/fixture_b.csv"]
    rows = reg.read_manifest(root / "data/reference_manifest.csv")
    assert len(rows) == 4 and {r_["role"] for r_ in rows} == {"archive", "extracted"}
    for row in rows:
        assert row["sha256"] == hashlib.sha256((root / row["relative_path"]).read_bytes()).hexdigest()
        assert row["version"] == V and row["source_url"] == reg.SOURCE_URL
        assert "2011/833/EU" in row["licence"] and row["acquired_on"] == "2026-10-06"
        assert row["acquisition_evidence"] == "portal download date stated by the registrant"
    report = r["report"].read_text(encoding="utf-8")
    assert "| `fixture_a.csv` | 2 | `colA`, `colB` |" in report
    assert "| `sub/fixture_b.csv` | 1 | `id`, `name` |" in report  # BOM stripped
    assert r["csv_files"] == 2


def test_repeat_registration_is_a_no_op(tmp_path):
    src = make_zip(tmp_path / "dl.zip", FIXTURE)
    root = tmp_path / "repo"
    reg.register(src, V, "en", "2026-10-06", root=root)
    manifest = (root / "data/reference_manifest.csv").read_bytes()
    before = files_under(root / "data")
    r = reg.register(src, V, "en", "2026-10-06", root=root)
    assert r["already_registered"] is True and r["manifest_rows_added"] == 0
    assert (root / "data/reference_manifest.csv").read_bytes() == manifest
    assert files_under(root / "data") == before


def test_different_archive_for_same_version_rejected(tmp_path):
    root = tmp_path / "repo"
    reg.register(make_zip(tmp_path / "a.zip", FIXTURE), V, "en", "2026-10-06", root=root)
    before = files_under(root)
    other = make_zip(tmp_path / "b.zip", {**FIXTURE, "fixture_a.csv": b"colA,colB\n1,CHANGED\n"})
    with pytest.raises(reg.RegistrationError, match="different archive"):
        reg.register(other, V, "en", "2026-10-06", root=root)
    assert files_under(root) == before


def test_existing_extracted_file_with_different_content_not_overwritten(tmp_path):
    root = tmp_path / "repo"
    target = root / "data/reference/esco" / V / "extracted/fixture_a.csv"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"pre-existing\n")
    with pytest.raises(reg.RegistrationError, match="existing file differs"):
        reg.register(make_zip(tmp_path / "dl.zip", FIXTURE), V, "en", "2026-10-06", root=root)
    assert target.read_bytes() == b"pre-existing\n"
    assert not (root / "data/reference/esco" / V / "archive").exists()
    assert not (root / "data/reference_manifest.csv").exists()


@pytest.mark.parametrize("name", ["../escape.csv", "/abs.csv", "a/../../escape.csv", "C:/win.csv"])
def test_unsafe_paths_rejected_before_writing(tmp_path, name):
    root = tmp_path / "repo"
    with pytest.raises(reg.RegistrationError, match="unsafe path"):
        reg.register(make_zip(tmp_path / "bad.zip", {**FIXTURE, name: b"x"}), V, "en", "2026-10-06", root=root)
    assert not root.exists()


def test_symlink_member_rejected(tmp_path):
    root = tmp_path / "repo"
    with pytest.raises(reg.RegistrationError, match="symlink"):
        reg.register(make_zip(tmp_path / "s.zip", FIXTURE, symlink="link.csv"), V, "en", "2026-10-06", root=root)
    assert not root.exists()


def test_macos_resource_forks_skipped(tmp_path):
    root = tmp_path / "repo"
    r = reg.register(make_zip(tmp_path / "m.zip", {**FIXTURE, "__MACOSX/._fixture_a.csv": b"junk"}),
                     V, "en", "2026-10-06", root=root)
    assert not (root / "data/reference/esco" / V / "extracted/__MACOSX").exists()
    assert r["csv_files"] == 2


@pytest.mark.parametrize("kwargs, match", [
    ({"version": "1.2.1"}, "version must look like"),
    ({"downloaded_on": "06/10/2026"}, "YYYY-MM-DD"),
    ({"downloaded_on": "2999-01-01"}, "future"),
    ({"language": "english"}, "language"),
])
def test_invalid_arguments(tmp_path, kwargs, match):
    args = {"version": V, "language": "en", "downloaded_on": "2026-10-06", **kwargs}
    with pytest.raises(reg.RegistrationError, match=match):
        reg.register(make_zip(tmp_path / "dl.zip", FIXTURE), args["version"], args["language"],
                     args["downloaded_on"], root=tmp_path / "repo")


def test_not_a_zip(tmp_path):
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(reg.RegistrationError, match="not a zip"):
        reg.register(bad, V, "en", "2026-10-06", root=tmp_path / "repo")


def make_extracted(root: Path, name=f"ESCO dataset - {V} - classification - en - csv") -> Path:
    d = root / "data" / "reference" / name
    for rel, data in FIXTURE.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(data)
    (d / ".DS_Store").write_bytes(b"finder")
    return d


def test_register_extracted_dir_in_place_without_archive(tmp_path):
    root = tmp_path / "repo"
    d = make_extracted(root)
    before = files_under(d)
    r = reg.register_extracted_dir(d, V, "en", "2026-10-06", "folder creation time", root=root)
    assert files_under(d) == before  # nothing written into the source folder
    rows = reg.read_manifest(root / "data/reference_manifest.csv")
    assert {r_["role"] for r_ in rows} == {"source_file"}  # no archive row is invented
    assert len(rows) == 3 and not any(".DS_Store" in r_["relative_path"] for r_ in rows)
    assert all(r_["acquisition_evidence"] == "folder creation time" for r_ in rows)
    report = r["report"].read_text(encoding="utf-8")
    assert "Original ZIP: **not available**" in report and "| `fixture_a.csv` | 2 |" in report
    again = reg.register_extracted_dir(d, V, "en", "2026-10-06", "folder creation time", root=root)
    assert again["already_registered"] is True


def test_header_report_handles_fields_over_csv_default_limit(tmp_path):
    # Regression: the real conceptSchemes file has a field larger than csv's 131072 default.
    root = tmp_path / "repo"
    d = make_extracted(root)
    (d / "big.csv").write_text('id,hasTopConcept\n1,"' + "u," * 100_000 + '"\n', encoding="utf-8")
    r = reg.register_extracted_dir(d, V, "en", "2026-10-06", "evidence", root=root)
    assert "| `big.csv` | 1 | `id`, `hasTopConcept` |" in r["report"].read_text(encoding="utf-8")


def test_register_extracted_dir_detects_changed_file(tmp_path):
    root = tmp_path / "repo"
    d = make_extracted(root)
    reg.register_extracted_dir(d, V, "en", "2026-10-06", "evidence", root=root)
    (d / "fixture_a.csv").write_bytes(b"colA,colB\n1,changed\n")
    with pytest.raises(reg.RegistrationError, match="different hash"):
        reg.register_extracted_dir(d, V, "en", "2026-10-06", "evidence", root=root)


def test_register_extracted_dir_requires_evidence_and_location(tmp_path):
    root = tmp_path / "repo"
    d = make_extracted(root)
    with pytest.raises(reg.RegistrationError, match="evidence"):
        reg.register_extracted_dir(d, V, "en", "2026-10-06", " ", root=root)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "x.csv").write_text("a\n1\n")
    with pytest.raises(reg.RegistrationError, match="under data/reference"):
        reg.register_extracted_dir(outside, V, "en", "2026-10-06", "e", root=root)


def test_find_extracted_dir_by_prefix(tmp_path):
    root = tmp_path / "repo"
    d = make_extracted(root, name=f"ESCO dataset - {V} - classification - en - csv (1)")
    assert reg.find_extracted_dir(root, V) == d
    make_extracted(root, name=f"ESCO dataset - {V} - classification - en - csv copy")
    with pytest.raises(reg.RegistrationError, match="exactly one"):
        reg.find_extracted_dir(root, V)


def test_cli_exit_codes(tmp_path, capsys):
    src = make_zip(tmp_path / "dl.zip", FIXTURE)
    args = ["--archive", str(src), "--version", V, "--downloaded-on", "2026-10-06", "--root", str(tmp_path / "repo")]
    assert reg.main(args) == 0
    assert reg.main(args) == 0
    assert "already registered" in capsys.readouterr().out
    assert reg.main(["--archive", str(tmp_path / "missing.zip"), "--version", V,
                     "--downloaded-on", "2026-10-06", "--root", str(tmp_path / "repo")]) == 2
