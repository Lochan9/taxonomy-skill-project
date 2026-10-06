"""Tests for src/derive_features.py (seniority rules, language detection, near-dup candidates)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import derive_features as df
import load_postings as lp
from test_load_postings import row, write_jsonl

RULES = df.load_rules()


# ----------------------------------------------------------------------- seniority


@pytest.mark.parametrize("title, label", [
    ("Data Science Intern (2027)", "intern"),
    ("Associate Product Manager, Intern", "intern"),
    ("Senior/Software Engineer II, Android", "ambiguous"),
    ("VP of Global Tax", "executive"),
    ("Chief Compliance Officer, UK", "executive"),
    ("Executive Assistant, Chief People Officer", "unknown"),  # assistant excluded
    ("Account Executive, Enterprise", "unknown"),              # sales role, not a level
    ("Executive Director, Clinical Pharmacology", "director"),
    ("Associate Director, Computational Biology", "director"),
    ("Head of Influencers & Community", "director"),
    ("Senior Creative Director, Marketing", "senior"),         # role name, falls through
    ("Principal Art Director, Product", "staff_principal"),
    ("Senior Staff Software Engineer", "staff_principal"),
    ("Senior Engineering Manager, Product", "manager"),
    ("Senior Product Manager, Growth", "senior"),              # IC role name excluded from manager
    ("Technical Program Manager", "unknown"),
    ("Software Engineer II, iOS", "mid"),
    ("Associate Product Manager (New Grad)", "entry"),
    ("Early Career, Product Designer (2027)", "entry"),
    ("Senior Underwriting Associate", "senior"),
    ("Ad Sales Lead - West", "ambiguous"),
    ("Compliance Engineer", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
])
def test_seniority_labels(title, label):
    assert df.classify_title(title, RULES)["seniority_label"] == label


def test_other_matches_are_recorded():
    r = df.classify_title("Senior Engineering Manager, Product", RULES)
    assert r["rule_id"] == "manager" and r["matched_text"].lower() == "manager"
    assert r["other_matches"] == "senior:senior"


def test_rules_version_and_hash_recorded():
    [s] = df.derive_seniority([{"snapshot_id": "S", "posting_id": "p", "title": "Staff Engineer"}], RULES)
    assert s["rules_version"] == RULES.version
    assert s["rules_sha256"] == hashlib.sha256(df.DEFAULT_RULES.read_bytes()).hexdigest()


@pytest.mark.parametrize("text, match", [
    ("version: '1'\nlabels: [a]\nrules: []\ndefault_label: a\n", "at least one rule"),
    ("version: '1'\nlabels: [a]\nrules: [{id: x, label: b, patterns: [x]}]\ndefault_label: a\n", "not in labels"),
    ("version: '1'\nlabels: [a]\nrules: [{id: x, label: a, patterns: ['(']}]\ndefault_label: a\n", "invalid regex"),
    ("version: '1'\nlabels: [a]\nrules: [{id: x, label: a, patterns: [x]}, {id: x, label: a, patterns: [y]}]\ndefault_label: a\n", "duplicate id"),
    ("version: '1'\nlabels: [a]\nrules: [{id: x, label: a, patterns: [x]}]\ndefault_label: z\n", "default_label"),
    ("labels: [a]\n", "missing 'version'"),
])
def test_invalid_rules_rejected(tmp_path, text, match):
    path = tmp_path / "rules.yaml"
    path.write_text(text)
    with pytest.raises(df.RulesError, match=match):
        df.load_rules(path)


# ------------------------------------------------------------------------ language


@pytest.fixture(scope="module")
def detector():
    return df.build_detector()


ENGLISH = ("We are looking for a data engineer to design, build and maintain reliable pipelines. "
           "You will work closely with analysts and product managers to deliver trusted datasets, "
           "improve data quality, and mentor other engineers on the team.")
FRENCH = ("Nous recherchons un ingénieur de données pour concevoir, construire et maintenir des "
          "pipelines fiables. Vous travaillerez avec les analystes et les chefs de produit pour "
          "livrer des données de confiance et améliorer leur qualité au quotidien.")


def test_detects_english_confidently(detector):
    d = df.detect_language(ENGLISH, detector)
    assert d["detected_language"] == "en" and d["is_uncertain"] is False
    assert d["whole_text_confidence"] >= df.LANG_MIN_CONFIDENCE
    assert d["primary_share"] == 1.0


def test_detects_french(detector):
    assert df.detect_language(FRENCH, detector)["detected_language"] == "fr"


def test_short_and_empty_text_are_uncertain(detector):
    assert "short_text" in df.detect_language("Data engineer role.", detector)["uncertainty_reason"]
    empty = df.detect_language("", detector)
    assert empty["is_uncertain"] is True and empty["detected_language"] is None


def test_mixed_text_uses_paragraph_majority_and_is_uncertain(detector):
    # lingua's whole-text label can follow the minority language on mixed input (observed:
    # six English paragraphs + one French -> whole text "fr", confidence 1.0). The label
    # therefore comes from the paragraph word majority, and the row is marked uncertain.
    d = df.detect_language("\n\n".join([ENGLISH] * 6 + [FRENCH]), detector)
    assert d["detected_language"] == "en"
    assert d["primary_share"] == pytest.approx(6 * 37 / (6 * 37 + 36), abs=1e-3)
    assert d["other_language_paragraphs"] == 1
    assert d["is_uncertain"] is True
    assert "other_language_paragraphs" in d["uncertainty_reason"]


def test_source_language_kept_separately(detector):
    postings = [
        {"snapshot_id": "S", "posting_id": "a", "clean_text": FRENCH, "source_language": "en"},
        {"snapshot_id": "S", "posting_id": "b", "clean_text": ENGLISH, "source_language": None},
    ]
    a, b = df.derive_language(postings, detector)
    assert a["source_language"] == "en" and a["detected_language"] == "fr"
    assert a["agrees_with_source"] is False
    assert b["source_language"] is None and b["agrees_with_source"] is None
    assert a["detector"] == "lingua-language-detector" and a["detector_version"]


# ------------------------------------------------------------------ near-duplicates


def posting(pid: int, board="acme", title="Engineer", internal="1", text="Build things.", loc="NYC"):
    return {"posting_id": f"greenhouse:{board}:{pid}", "board_token": board, "title": title,
            "internal_job_id": internal, "clean_text": text, "location": loc,
            "text_hash": hashlib.sha256(text.encode()).hexdigest(), "exclusion_reason": ""}


def test_all_pairs_in_group_compared():
    ps = [posting(1, loc="NYC"), posting(2, loc="London"), posting(3, loc="Toronto", text="Different.")]
    pairs = df.near_duplicate_candidates(ps)
    assert {(p["posting_id_a"], p["posting_id_b"]) for p in pairs} == {
        ("greenhouse:acme:1", "greenhouse:acme:2"),
        ("greenhouse:acme:1", "greenhouse:acme:3"),
        ("greenhouse:acme:2", "greenhouse:acme:3"),
    }
    assert all(p["basis"] == "internal_job_id+title" and p["status"] == "candidate" for p in pairs)
    top = pairs[0]
    assert top["text_similarity"] == 1.0 and top["exact_text_match"] is True
    assert {top["location_a"], top["location_b"]} == {"NYC", "London"}


def test_grouping_bases_and_boundaries():
    ps = [
        posting(1, title="Engineer", internal="10"),
        posting(2, title="Designer", internal="10"),        # same internal id only
        posting(3, title="  ENGINEER ", internal="20"),     # same normalized title only
        posting(4, title="Analyst", internal=None),
        posting(5, title="Analyst 2", internal=None),       # null ids are never grouped
        posting(6, board="beta", title="Engineer", internal="10"),  # other board
    ]
    pairs = {(p["posting_id_a"][-1], p["posting_id_b"][-1]): p["basis"] for p in df.near_duplicate_candidates(ps)}
    assert pairs == {("1", "2"): "internal_job_id", ("1", "3"): "title"}


def test_candidates_include_flagged_rows_but_do_not_exclude():
    ps = [posting(1), posting(2)]
    ps[1]["exclusion_reason"] = "placeholder_title:dont_see_role"
    [p] = df.near_duplicate_candidates(ps)
    assert p["exclusion_reason_b"] == "placeholder_title:dont_see_role"
    assert p["status"] == "candidate"


# --------------------------------------------------------------------------- run_all


def test_run_all_reads_db_without_modifying_it(tmp_path, detector):
    db = tmp_path / "t.sqlite"
    rows = [row(1, text=ENGLISH), row(2, text=ENGLISH + " Remote."),
            row(3, snapshot="20261013T090000Z", text=FRENCH)]
    for i, r in enumerate([rows[:2], rows[2:]]):
        p = write_jsonl(tmp_path / f"in{i}.jsonl", r)
        parsed, sha = lp.read_input(p)
        conn = lp.connect(db)
        lp.ensure_schema(conn)
        lp.load(parsed, sha, p.as_posix(), conn)
        conn.close()
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    result = df.run_all(db, "20261006T171338Z", root=tmp_path, detector=detector)

    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert [p["posting_id"] for p in result["postings"]] == ["greenhouse:acme:1", "greenhouse:acme:2"]
    assert [s["seniority_label"] for s in result["seniority"]] == ["unknown", "unknown"]
    assert all(p.is_file() for p in result["paths"].values())
    # Same board + same title ("Data Analyst"), different internal ids -> one title-based pair.
    [pair] = result["pairs"]
    assert pair["basis"] == "title" and 0.9 < pair["text_similarity"] < 1.0
    assert pair["exact_text_match"] is False
    # The other snapshot's posting is never mixed in.
    assert all(p["snapshot_id"] == "20261006T171338Z" for p in result["postings"])


def test_readonly_connection_cannot_write(tmp_path):
    db = tmp_path / "t.sqlite"
    p = write_jsonl(tmp_path / "in.jsonl", [row(1)])
    parsed, sha = lp.read_input(p)
    conn = lp.connect(db)
    lp.ensure_schema(conn)
    lp.load(parsed, sha, p.as_posix(), conn)
    conn.close()
    ro = df.connect_readonly(db)
    with pytest.raises(Exception, match="readonly"):
        ro.execute("DELETE FROM postings")
    ro.close()


def test_unknown_snapshot_errors(tmp_path):
    db = tmp_path / "t.sqlite"
    p = write_jsonl(tmp_path / "in.jsonl", [row(1)])
    parsed, sha = lp.read_input(p)
    conn = lp.connect(db)
    lp.ensure_schema(conn)
    lp.load(parsed, sha, p.as_posix(), conn)
    conn.close()
    with pytest.raises(ValueError, match="No postings"):
        df.run_all(db, "20990101T000000Z", root=tmp_path)
