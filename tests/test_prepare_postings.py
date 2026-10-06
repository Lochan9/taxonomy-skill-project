"""Tests for src/prepare_postings.py. Uses synthetic snapshots only."""

from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path

import pytest

import fetch_greenhouse as fg
import prepare_postings as pp

SNAP = "20261006T120000Z"


def gh(markup: str) -> str:
    """Encode HTML the way Greenhouse's `content` field does (entity-escaped markup)."""
    return html.escape(markup, quote=True)


def job(job_id, title="Data Analyst", markup="<p>Analyse data.</p>", **extra):
    j = {
        "id": job_id,
        "internal_job_id": job_id + 1000,
        "title": title,
        "content": gh(markup) if markup is not None else None,
        "location": {"name": "Remote"},
        "departments": [{"id": 1, "name": "Data"}, {"id": 2, "name": "Analytics"}],
        "offices": [{"id": 9, "name": "New York"}],
        "absolute_url": f"https://job-boards.greenhouse.io/acme/jobs/{job_id}",
        "updated_at": "2026-09-01T10:00:00-04:00",
        "language": "en",
        "company_name": "Acme",
    }
    j.update(extra)
    if markup is None and "content" not in extra:
        j["content"] = None
    return j


def make_snapshot(root: Path, boards_jobs: dict[str, list[dict]]) -> list[fg.Board]:
    boards = []
    for token, jobs in boards_jobs.items():
        body = json.dumps({"jobs": jobs, "meta": {"total": len(jobs)}}).encode()
        path = fg.write_snapshot_file(root / fg.RAW_SUBDIR / SNAP, token, body)
        fg.append_manifest_row(root / fg.MANIFEST_SUBPATH, {
            "snapshot_id": SNAP, "board_token": token,
            "file_path": path.relative_to(root).as_posix(), "fetched_at": "2026-10-06T12:00:00Z",
            "http_status": 200, "job_count": len(jobs),
            "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
        })
        boards.append(fg.Board(token, f"{token.title()} Inc.", "Software", "test label"))
    return boards


def raw_hashes(root: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root / fg.RAW_SUBDIR).rglob("*.json")}


# ------------------------------------------------------------------- HTML cleaning


def test_decodes_double_encoded_entities_and_removes_tags():
    raw = gh("<p>R&amp;D at <strong>Acme</strong>&nbsp;&mdash; &quot;fast&quot; &lt;3</p>")
    assert pp.html_to_text(raw) == 'R&D at Acme — "fast" <3'


def test_drops_iframe_script_and_style_content():
    raw = gh('<p>Intro</p><iframe src="x">video</iframe><script>alert(1)</script>'
             '<style>p{}</style><p>Body</p>')
    assert pp.html_to_text(raw) == "Intro\n\nBody"


def test_paragraph_and_bullet_boundaries():
    raw = gh("<h3>What you'll do</h3><ul><li>Build models</li><li><p>Ship&nbsp;code</p></li>"
             "<li>Review <em>PRs</em></li></ul><p>Benefits:</p><p>Line one<br>Line two</p>")
    assert pp.html_to_text(raw) == (
        "What you'll do\n\n"
        "- Build models\n"
        "- Ship code\n"
        "- Review PRs\n\n"
        "Benefits:\n\n"
        "Line one\nLine two"
    )


def test_nested_bullets_are_indented_and_empty_bullets_dropped():
    raw = gh("<ul><li>Python<ul><li>pandas</li></ul></li><li> </li><li>SQL</li></ul>")
    assert pp.html_to_text(raw) == "- Python\n  - pandas\n- SQL"


def test_adjacent_text_across_tags_is_not_merged():
    assert pp.html_to_text(gh("<div>Alpha</div><div>Beta</div>")) == "Alpha\n\nBeta"


# -------------------------------------------------------------------- row building


def test_stable_posting_ids(tmp_path):
    boards = make_snapshot(tmp_path, {"acme": [job(22), job(3)]})
    first = pp.prepare(SNAP, boards, tmp_path, log=lambda *_: None)
    second = pp.prepare(SNAP, boards, tmp_path, log=lambda *_: None)
    assert [r["posting_id"] for r in first] == ["greenhouse:acme:3", "greenhouse:acme:22"]
    assert [r["posting_id"] for r in first] == [r["posting_id"] for r in second]
    assert first[0]["source_job_id"] == "3" and first[0]["internal_job_id"] == "1003"


def test_row_fields_and_metadata(tmp_path):
    boards = make_snapshot(tmp_path, {"acme": [job(1)]})
    [row] = pp.prepare(SNAP, boards, tmp_path)
    assert list(row) == pp.OUTPUT_FIELDS
    assert row["source"] == "greenhouse"
    assert row["company_name"] == "Acme Inc." and row["industry"] == "Software"
    assert row["source_company_name"] == "Acme"  # API value preserved alongside config name
    assert row["cleaning_version"] == pp.CLEANING_VERSION
    assert row["departments"] == ["Data", "Analytics"] and row["offices"] == ["New York"]
    assert row["raw_text"] == gh("<p>Analyse data.</p>")  # unmodified source field
    assert row["clean_text"] == "Analyse data."
    assert row["source_language"] == "en"
    assert row["snapshot_id"] == SNAP and row["fetched_at"] == "2026-10-06T12:00:00Z"
    assert row["word_count"] == 2
    assert row["exclusion_reason"] == "" and row["is_duplicate_of"] is None


def test_missing_source_company_name_is_null(tmp_path):
    j = job(1)
    del j["company_name"]
    boards = make_snapshot(tmp_path, {"acme": [j]})
    [row] = pp.prepare(SNAP, boards, tmp_path)
    assert row["source_company_name"] is None and row["company_name"] == "Acme Inc."


def test_report_shows_both_company_names(tmp_path):
    boards = make_snapshot(tmp_path, {"acme": [job(1)]})
    rows = pp.prepare(SNAP, boards, tmp_path)
    report = tmp_path / "report.md"
    pp.write_report(rows, SNAP, boards, report, tmp_path / "a.jsonl", tmp_path / "a.csv", tmp_path)
    assert "| acme | Acme Inc. | Acme (1) | yes |" in report.read_text(encoding="utf-8")


def test_missing_and_empty_descriptions_are_flagged_and_kept(tmp_path):
    no_content = job(1, markup=None)
    del no_content["content"]
    boards = make_snapshot(tmp_path, {"acme": [no_content, job(2, markup=None), job(3, markup="<p>&nbsp;</p><ul><li></li></ul>")]})
    rows = pp.prepare(SNAP, boards, tmp_path)
    assert [r["exclusion_reason"] for r in rows] == ["missing_description", "missing_description", "empty_description"]
    assert all(r["text_hash"] is None and r["word_count"] == 0 for r in rows)
    assert all(r["is_duplicate_of"] is None for r in rows)  # empty rows are not duplicates


@pytest.mark.parametrize("title, label", [
    ("Don't see what you're looking for?", "dont_see_role"),
    ("Don’t see the role for you?", "dont_see_role"),
    ("General Application - Engineering", "general_application"),
    ("Join our Talent Community", "talent_pool"),
    ("Future Opportunities", "future_opportunities"),
])
def test_placeholder_titles_flagged_with_reason(tmp_path, title, label):
    boards = make_snapshot(tmp_path, {"acme": [job(1, title=title)]})
    [row] = pp.prepare(SNAP, boards, tmp_path)
    assert row["is_placeholder"] is True
    assert row["exclusion_reason"] == f"placeholder_title:{label}"


@pytest.mark.parametrize("title", ["Talent Acquisition Partner", "General Counsel", "Senior Data Scientist"])
def test_real_titles_not_flagged_as_placeholders(title):
    assert pp.placeholder_reason(title) is None


def test_placeholder_detected_from_description_when_title_looks_normal(tmp_path):
    markup = ("<h2>Join our Internship Talent Network!</h2><p>We are currently not hiring interns. "
              "Send your resume so we have your information on file.</p>")
    boards = make_snapshot(tmp_path, {"acme": [job(1, title="Interested in an internship?", markup=markup)]})
    [row] = pp.prepare(SNAP, boards, tmp_path)
    assert row["is_placeholder"] is True
    assert row["exclusion_reason"] == "placeholder_text:join_talent_pool"


@pytest.mark.parametrize("text", [
    "We are not hiring for this team in Berlin right now, but this role is in London.",
    "You will partner with our Talent Acquisition team to grow the talent pipeline.",
])
def test_real_descriptions_not_flagged_as_placeholders(text):
    assert pp.placeholder_reason("Recruiter", text) is None


def test_exact_duplicates_use_normalized_text_not_titles(tmp_path):
    boards = make_snapshot(tmp_path, {
        "acme": [job(1, title="Engineer", markup="<p>Build  the THING.</p>"),
                 job(2, title="Engineer (London)", markup="<div>build the thing.</div>")],
        "beta": [job(5, title="Something else", markup="<p>Build the thing.</p>")],
    })
    rows = pp.prepare(SNAP, boards, tmp_path)
    by_id = {r["posting_id"]: r for r in rows}
    assert by_id["greenhouse:acme:1"]["is_duplicate_of"] is None
    assert by_id["greenhouse:acme:2"]["is_duplicate_of"] == "greenhouse:acme:1"
    assert by_id["greenhouse:beta:5"]["is_duplicate_of"] == "greenhouse:acme:1"  # across boards
    assert by_id["greenhouse:acme:2"]["exclusion_reason"] == "exact_duplicate"


def test_repeated_titles_with_different_text_are_not_duplicates(tmp_path):
    boards = make_snapshot(tmp_path, {"acme": [
        job(1, title="Android Engineer", markup="<p>Payments team.</p>"),
        job(2, title="Android Engineer", markup="<p>Growth team.</p>"),
    ]})
    rows = pp.prepare(SNAP, boards, tmp_path)
    assert all(r["is_duplicate_of"] is None and r["exclusion_reason"] == "" for r in rows)
    assert pp.summarize(rows)["repeated_title_groups_distinct_text"] == 1


# ------------------------------------------------------------- safety and outputs


def test_raw_snapshot_unchanged_and_outputs_written(tmp_path):
    boards = make_snapshot(tmp_path, {"acme": [job(1), job(2, title="Don't see what you're looking for?")]})
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text(
        "boards:\n  - {board_token: acme, company_name: Acme Inc., industry: Software, industry_source: test}\n")
    before = raw_hashes(tmp_path)

    assert pp.main(["--snapshot", SNAP, "--root", str(tmp_path)]) == 0
    assert raw_hashes(tmp_path) == before

    jsonl = tmp_path / f"data/processed/postings_{SNAP}.jsonl"
    rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and rows[1]["is_placeholder"] is True  # flagged row kept
    assert isinstance(rows[0]["departments"], list)

    with (tmp_path / f"data/processed/postings_{SNAP}.csv").open(encoding="utf-8", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert list(csv_rows[0]) == pp.OUTPUT_FIELDS
    assert json.loads(csv_rows[0]["departments"]) == ["Data", "Analytics"]
    assert csv_rows[1]["is_placeholder"] == "true" and csv_rows[0]["is_duplicate_of"] == ""
    assert (tmp_path / f"reports/sprint1_cleaning_quality_{SNAP}.md").is_file()


def test_refuses_corrupted_raw_file(tmp_path):
    boards = make_snapshot(tmp_path, {"acme": [job(1)]})
    raw = next((tmp_path / fg.RAW_SUBDIR).rglob("acme.json"))
    raw.write_bytes(raw.read_bytes().replace(b"Analyse", b"Analyze"))
    with pytest.raises(fg.ConfigError, match="failed verification"):
        pp.prepare(SNAP, boards, tmp_path)


def test_unknown_snapshot_and_missing_board_are_errors(tmp_path):
    boards = make_snapshot(tmp_path, {"acme": [job(1)]})
    with pytest.raises(fg.ConfigError, match="No manifest rows"):
        pp.prepare("20990101T000000Z", boards, tmp_path)
    with pytest.raises(fg.ConfigError, match="no file for configured boards"):
        pp.prepare(SNAP, boards + [fg.Board("other", "Other")], tmp_path)
