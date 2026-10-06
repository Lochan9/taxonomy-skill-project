"""Tests for src/select_annotation_set.py and src/annotations.py (synthetic corpus, temp dirs)."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

import annotations as an
import load_postings as lp
import select_annotation_set as sel
from test_load_postings import row, write_jsonl

SNAP = "20261006T171338Z"
OTHER = "20261013T090000Z"
TITLES = ["Senior Data Engineer", "Data Analyst", "Engineering Manager", "Director of Product",
          "Software Engineer Intern", "Staff Engineer", "Account Executive"]


def corpus(snapshot=SNAP) -> list[dict]:
    """~140 usable postings on 5 boards, with variant groups and two flagged rows."""
    rows, jid = [], 1
    sizes = {"alpha": 40, "beta": 35, "gamma": 30, "delta": 25, "small": 10}
    for board, n in sizes.items():
        for i in range(n):
            title = f"{TITLES[i % len(TITLES)]}, Team {i}"
            text = f"{board} role {i}. Build pipelines in Python and SQL. Collaborate with stakeholders."
            r = row(jid, snapshot, text=text, board=board, title=title, departments=[f"Dept{i % 6}"],
                    company_name=f"{board.title()} Inc.")
            rows.append(r)
            jid += 1
    # Location variants (same base title) and a shared requisition on alpha.
    for k, loc in enumerate(["London, UK", "Paris, France"]):
        rows.append(row(jid, snapshot, text="alpha role 0 variant. Build pipelines in Python.", board="alpha",
                        title=f"{TITLES[0]}, Team 0 ({loc})", location=loc, departments=["Dept0"],
                        company_name="Alpha Inc."))
        jid += 1
    shared = rows[1]["internal_job_id"]
    rows.append(row(jid, snapshot, text="alpha shared requisition other team.", board="alpha",
                    title="Data Analyst, Other Team", internal_job_id=shared, company_name="Alpha Inc."))
    jid += 1
    # small board: two postings share a requisition -> 9 groups; plus two flagged placeholders.
    small = [r for r in rows if r["board_token"] == "small"]
    small[1]["internal_job_id"] = small[0]["internal_job_id"]
    for k in range(2):
        rows.append(row(jid, snapshot, board="small", title="Don't see what you're looking for?",
                        is_placeholder=True, exclusion_reason="placeholder_title:dont_see_role",
                        company_name="Small Inc."))
        jid += 1
    return rows


def build_db(root: Path, snapshots=(SNAP,)) -> Path:
    db = root / "data" / "processed" / "t.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    for s in snapshots:
        p = write_jsonl(root / f"in_{s}.jsonl", corpus(s))
        rows, sha = lp.read_input(p)
        conn = lp.connect(db)
        lp.ensure_schema(conn)
        lp.load(rows, sha, p.as_posix(), conn)
        conn.close()
    return db


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "repo"
    db = build_db(root, (SNAP, OTHER))
    return root, db


def freeze(root: Path, db: Path) -> list[dict]:
    assert sel.main(["--db", str(db), "--snapshot", SNAP, "--root", str(root)]) == 0
    return sel.read_manifest(sel.set_dir(root) / "selection_manifest.csv")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------------ selection


def test_selects_exactly_100_distinct_usable_postings(env):
    root, db = env
    usable = sel.load_usable(db, SNAP)
    rows = sel.select(usable)
    ids = [r["posting_id"] for r in rows]
    assert len(ids) == 100 == len(set(ids))
    usable_ids = {p["posting_id"] for p in usable}
    assert set(ids) <= usable_ids
    assert all(r["snapshot_id"] == SNAP for r in rows)
    assert not any("Don't see" in r["title"] for r in rows)  # flagged rows never eligible


def test_selection_is_reproducible_and_seed_dependent(env):
    _, db = env
    usable = sel.load_usable(db, SNAP)
    assert sel.select(usable) == sel.select(usable)
    assert sel.select(usable, seed=1) != sel.select(usable)


def test_splits_disjoint_and_sized(env):
    _, db = env
    rows = sel.select(sel.load_usable(db, SNAP))
    dev = {r["posting_id"] for r in rows if r["split"] == "development"}
    ev = {r["posting_id"] for r in rows if r["split"] == "evaluation"}
    assert len(dev) == 20 and len(ev) == 80 and not dev & ev


def test_related_variants_never_cross_splits(env):
    _, db = env
    usable = sel.load_usable(db, SNAP)
    rows = sel.select(usable)
    groups = sel.build_groups(usable)
    gid = {m: g for g, info in groups.items() for m in info["members"]}
    # at most one selected posting per group, so a group has exactly one split
    assert len({gid[r["posting_id"]] for r in rows}) == len(rows)
    # the location variants and shared-requisition posting are grouped with their originals
    alpha_multi = [g for g in groups.values() if len(g["members"]) > 1 and "alpha" in g["group_id"]]
    assert sorted(len(g["members"]) for g in alpha_multi) == [2, 3]
    bases = {g["basis"] for g in alpha_multi}
    assert "base_title" in bases and "internal_job_id" in bases


def test_balanced_quotas_cap_small_employer(env):
    _, db = env
    rows = sel.select(sel.load_usable(db, SNAP))
    per = Counter(r["board_token"] for r in rows)
    assert per["small"] == 9  # 10 usable postings, 9 groups -> capped
    assert sorted(per[b] for b in ("alpha", "beta", "gamma", "delta")) == [22, 23, 23, 23]


def test_balanced_quotas_helper():
    assert sel.balanced_quotas({"a": 9, "b": 54, "c": 80, "d": 129, "e": 139}, 100) == \
        {"a": 9, "b": 22, "c": 23, "d": 23, "e": 23}
    with pytest.raises(sel.SelectionError):
        sel.balanced_quotas({"a": 5}, 10)


def test_frozen_manifest_written_once_and_checked(env, capsys):
    root, db = env
    db_before = sha(db)
    frozen = freeze(root, db)
    assert sha(db) == db_before  # selection never writes to the DB
    assert {r["seed"] for r in frozen} == {str(sel.SEED)}
    assert {r["selection_version"] for r in frozen} == {sel.SELECTION_VERSION}
    assert sel.main(["--db", str(db), "--snapshot", SNAP, "--root", str(root), "--check"]) == 0
    path = sel.set_dir(root) / "selection_manifest.csv"
    text = path.read_text()
    path.write_text(text.replace(",development,", ",evaluation,", 1))  # tamper
    assert sel.main(["--db", str(db), "--snapshot", SNAP, "--root", str(root), "--check"]) == 1
    assert sel.main(["--db", str(db), "--snapshot", SNAP, "--root", str(root)]) == 2  # refuses overwrite
    assert "refusing to overwrite" in capsys.readouterr().err


def test_manifest_validation_catches_bad_ids(env):
    root, db = env
    frozen = freeze(root, db)
    usable = sel.load_usable(db, SNAP)
    bad = [dict(r) for r in frozen]
    bad[0]["snapshot_id"] = OTHER
    bad[1]["posting_id"] = "greenhouse:alpha:999999"
    bad[2]["clean_text_sha256"] = "0" * 64
    problems = sel.validate_manifest(bad, usable, SNAP)
    assert any("snapshot" in p for p in problems)
    assert any("not a usable posting" in p for p in problems)
    assert any("clean_text changed" in p for p in problems)


# ---------------------------------------------------------------------- annotation


@pytest.fixture
def ann(env):
    root, db = env
    manifest = freeze(root, db)
    an.export(db, root)
    texts = an.load_texts(db, manifest)
    d = an.init_annotator("alice", root)
    return root, db, manifest, texts, d


def write_review(d: Path, manifest, statuses: dict[str, str], annotator="alice"):
    rows = []
    for r in sorted(manifest, key=lambda r: (r["split"], r["posting_id"])):
        st = statuses.get(r["posting_id"], "not_started")
        rows.append({"snapshot_id": r["snapshot_id"], "posting_id": r["posting_id"], "split": r["split"],
                     "review_status": st, "annotator_id": annotator if st == "reviewed" else "",
                     "reviewed_at": "2026-10-07" if st == "reviewed" else "", "review_notes": ""})
    an._write_csv(d / "postings_review.csv", an.REVIEW_FIELDS, rows)


def skill(manifest_row, texts, phrase, aid, occurrence=1, **over):
    s, e = an.locate(texts[manifest_row["posting_id"]], phrase, occurrence)
    r = {"snapshot_id": manifest_row["snapshot_id"], "posting_id": manifest_row["posting_id"], "annotation_id": aid,
         "skill_statement": phrase, "evidence_text": phrase, "evidence_start": s, "evidence_end": e,
         "required_or_preferred": "required", "alternative_group_id": "", "skill_category": "tool",
         "annotator_id": "alice", "review_notes": ""}
    r.update(over)
    return r


def test_export_texts_are_exact_and_templates_empty(ann):
    root, db, manifest, texts, d = ann
    base = sel.set_dir(root)
    for r in manifest:
        p = base / "texts" / r["split"] / f"{an.safe_name(r['posting_id'])}.txt"
        assert hashlib.sha256(p.read_bytes()).hexdigest() == r["clean_text_sha256"]
    assert len(an.read_csv(base / "templates" / "skills.csv", an.SKILL_FIELDS)) == 0
    statuses = {r["review_status"] for _, r in an.read_csv(base / "templates" / "postings_review.csv", an.REVIEW_FIELDS)}
    assert statuses == {"not_started"}


def test_fresh_template_is_valid_but_not_complete(ann):
    root, db, manifest, texts, d = ann
    res = an.validate(d, manifest, texts)
    assert res["problems"] == []
    assert res["summary"]["not_started"] == 100 and res["summary"]["complete"] is False
    final = an.validate(d, manifest, texts, final=True)
    assert any("final set requires" in p.message for p in final["problems"])


def test_reviewed_zero_skill_distinguished_from_unfinished(ann):
    root, db, manifest, texts, d = ann
    a, b, c = manifest[0], manifest[1], manifest[2]
    write_review(d, manifest, {a["posting_id"]: "reviewed", b["posting_id"]: "reviewed", c["posting_id"]: "in_progress"})
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS, [skill(a, texts, "Python", "alice-0001")])
    s = an.validate(d, manifest, texts)["summary"]
    assert s["reviewed_with_skills"] == 1 and s["reviewed_zero_skills"] == 1
    assert s["in_progress"] == 1 and s["not_started"] == 97


def test_evidence_must_match_offsets(ann):
    root, db, manifest, texts, d = ann
    a = manifest[0]
    write_review(d, manifest, {a["posting_id"]: "reviewed"})
    good = skill(a, texts, "Python", "alice-0001")
    shifted = dict(good, annotation_id="alice-0002", evidence_start=good["evidence_start"] + 1,
                   evidence_end=good["evidence_end"] + 1)
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS, [good, shifted])
    problems = an.validate(d, manifest, texts)["problems"]
    assert len(problems) == 1
    p = problems[0]
    assert p.file == "skills.csv" and p.line == 3 and p.field == "evidence_text"
    assert f"occurs at start offset(s) [{good['evidence_start']}" in p.message  # actionable hint


@pytest.mark.parametrize("override, field, fragment", [
    ({"evidence_start": "x"}, "evidence_start/end", "integers"),
    ({"evidence_start": 5, "evidence_end": 5}, "evidence_start/end", "start < end"),
    ({"evidence_end": 10**7}, "evidence_start/end", "<="),
    ({"required_or_preferred": "must"}, "required_or_preferred", "must be one of"),
    ({"skill_category": "soft"}, "skill_category", "must be empty or one of"),
    ({"annotator_id": ""}, "annotator_id", "empty"),
    ({"skill_statement": "  "}, "skill_statement", "empty"),
    ({"snapshot_id": OTHER}, "snapshot_id", "selection snapshot"),
    ({"posting_id": "greenhouse:alpha:424242"}, "posting_id", "not in the selection manifest"),
])
def test_invalid_skill_rows_get_useful_errors(ann, override, field, fragment):
    root, db, manifest, texts, d = ann
    a = manifest[0]
    write_review(d, manifest, {a["posting_id"]: "reviewed"})
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS, [skill(a, texts, "Python", "alice-0001", **override)])
    problems = an.validate(d, manifest, texts)["problems"]
    assert any(p.field == field and fragment in p.message and p.line == 2 for p in problems), problems


def test_other_annotation_errors(ann):
    root, db, manifest, texts, d = ann
    a, b = manifest[0], manifest[1]
    write_review(d, manifest, {a["posting_id"]: "reviewed"})
    rows = [skill(a, texts, "Python", "dup"), skill(a, texts, "SQL", "dup"),           # duplicate id
            skill(b, texts, "Python", "alice-0003"),                                  # posting not started
            skill(a, texts, "Python", "alice-0004")]                                  # same span+statement twice
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS, rows)
    msgs = [p.message for p in an.validate(d, manifest, texts)["problems"]]
    assert any("used more than once" in m for m in msgs)
    assert any("review_status is 'not_started'" in m for m in msgs)
    assert any("recorded twice" in m for m in msgs)


def test_review_file_errors(ann):
    root, db, manifest, texts, d = ann
    write_review(d, manifest, {manifest[0]["posting_id"]: "reviewed"}, annotator="")
    rows = list(csv.DictReader((d / "postings_review.csv").open()))
    rows[1]["review_status"] = "done"
    rows[2]["split"] = "development" if rows[2]["split"] == "evaluation" else "evaluation"
    rows.pop()  # one posting missing
    an._write_csv(d / "postings_review.csv", an.REVIEW_FIELDS, rows)
    msgs = [f"{p.field}:{p.message}" for p in an.validate(d, manifest, texts)["problems"]]
    assert any(m.startswith("annotator_id:required") for m in msgs)
    assert any("must be one of" in m for m in msgs)
    assert any(m.startswith("split:") for m in msgs)
    assert any("missing" in m for m in msgs)


def test_wrong_header_rejected(ann):
    root, db, manifest, texts, d = ann
    (d / "skills.csv").write_text("posting_id,skill\n")
    with pytest.raises(an.AnnotationError, match="columns"):
        an.validate(d, manifest, texts)


def test_locate_and_init_guards(ann):
    root, db, manifest, texts, d = ann
    t = texts[manifest[0]["posting_id"]]
    s, e = an.locate(t, "Python")
    assert t[s:e] == "Python"
    with pytest.raises(an.AnnotationError, match="not found"):
        an.locate(t, "python ")
    with pytest.raises(an.AnnotationError, match="out of range"):
        an.locate(t, "Python", occurrence=9)
    with pytest.raises(an.AnnotationError, match="already exists"):
        an.init_annotator("alice", root)
    with pytest.raises(an.AnnotationError, match="annotator id"):
        an.init_annotator("Alice Smith", root)


def test_compare_two_annotators(ann):
    root, db, manifest, texts, d = ann
    a = manifest[0]
    b_dir = an.init_annotator("bob", root)
    for who, dd in (("alice", d), ("bob", b_dir)):
        write_review(dd, manifest, {a["posting_id"]: "reviewed"}, annotator=who)
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS,
                  [skill(a, texts, "Python", "a1"), skill(a, texts, "SQL", "a2"),
                   skill(a, texts, "Collaborate with stakeholders", "a3")])
    an._write_csv(b_dir / "skills.csv", an.SKILL_FIELDS,
                  [skill(a, texts, "Python", "b1", annotator_id="bob"),
                   skill(a, texts, "Python and SQL", "b2", annotator_id="bob", required_or_preferred="preferred")])
    res = an.compare(d, b_dir, manifest)
    assert res["postings_compared"] == 1
    assert res["exact_span_matches"] == 1 and res["overlapping_matches"] == 1
    assert res["only_a"] == 1 and res["only_b"] == 0 and res["requirement_disagreements"] == 1


def test_workflow_leaves_db_unchanged(ann):
    root, db, manifest, texts, d = ann
    before = sha(db)
    an.validate(d, manifest, texts)
    an.export(db, root)
    assert sha(db) == before


# ------------------------------------------------------------- alternative groups


def test_alternatives_go_or_python_are_valid_and_counted(ann):
    root, db, manifest, texts, d = ann
    a = manifest[0]
    write_review(d, manifest, {a["posting_id"]: "reviewed"})
    rows = [skill(a, texts, "Python", "alice-0001", alternative_group_id="alt-1"),
            skill(a, texts, "SQL", "alice-0002", alternative_group_id="alt-1"),
            skill(a, texts, "Collaborate with stakeholders", "alice-0003", skill_category="transferable")]
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS, rows)
    res = an.validate(d, manifest, texts)
    assert res["problems"] == [] and res["summary"]["alternative_groups"] == 1
    # offsets and requirement fields are untouched by grouping
    assert res["summary"]["skill_rows"] == 3


@pytest.mark.parametrize("mutate, field, fragment", [
    (lambda rs: rs[1].update(alternative_group_id=""), "alternative_group_id", "only one record"),
    (lambda rs: rs[1].update(required_or_preferred="preferred"), "required_or_preferred", "mixes"),
    (lambda rs: rs[1].update(skill_statement="python"), "skill_statement", "same skill twice"),
    (lambda rs: [r.update(alternative_group_id="alt 1") for r in rs], "alternative_group_id", "must be letters"),
])
def test_invalid_alternative_groups(ann, mutate, field, fragment):
    root, db, manifest, texts, d = ann
    a = manifest[0]
    write_review(d, manifest, {a["posting_id"]: "reviewed"})
    rows = [skill(a, texts, "Python", "alice-0001", alternative_group_id="alt-1"),
            skill(a, texts, "SQL", "alice-0002", alternative_group_id="alt-1")]
    mutate(rows)
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS, rows)
    problems = an.validate(d, manifest, texts)["problems"]
    assert any(p.field == field and fragment in p.message for p in problems), problems


def test_alternative_group_cannot_span_postings(ann):
    root, db, manifest, texts, d = ann
    a, b = manifest[0], manifest[1]
    write_review(d, manifest, {a["posting_id"]: "reviewed", b["posting_id"]: "reviewed"})
    rows = [skill(a, texts, "Python", "alice-0001", alternative_group_id="alt-1"),
            skill(b, texts, "SQL", "alice-0002", alternative_group_id="alt-1")]
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS, rows)
    msgs = [p.message for p in an.validate(d, manifest, texts)["problems"]]
    assert any("used in 2 postings" in m for m in msgs)


def test_old_header_without_alternative_column_is_rejected(ann):
    root, db, manifest, texts, d = ann
    old = [f for f in an.SKILL_FIELDS if f != "alternative_group_id"]
    (d / "skills.csv").write_text(",".join(old) + "\n")
    with pytest.raises(an.AnnotationError, match="columns"):
        an.validate(d, manifest, texts)


def test_compare_reports_alternative_disagreement(ann):
    root, db, manifest, texts, d = ann
    a = manifest[0]
    b_dir = an.init_annotator("bob", root)
    for who, dd in (("alice", d), ("bob", b_dir)):
        write_review(dd, manifest, {a["posting_id"]: "reviewed"}, annotator=who)
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS,
                  [skill(a, texts, "Python", "a1", alternative_group_id="alt-1"),
                   skill(a, texts, "SQL", "a2", alternative_group_id="alt-1")])
    an._write_csv(b_dir / "skills.csv", an.SKILL_FIELDS,
                  [skill(a, texts, "Python", "b1", annotator_id="bob"), skill(a, texts, "SQL", "b2", annotator_id="bob")])
    res = an.compare(d, b_dir, manifest)
    assert res["exact_span_matches"] == 2 and res["alternative_disagreements"] == 2


def test_action_phrase_normalised_to_skill_noun_is_valid(ann):
    # Guidelines §3a: "Build a lot of prototypes" -> *prototyping*. The statement need not
    # appear in the text; only the evidence span must match clean_text.
    root, db, manifest, texts, d = ann
    a = manifest[0]
    write_review(d, manifest, {a["posting_id"]: "reviewed"})
    rows = [skill(a, texts, "Build pipelines", "alice-0001", skill_statement="pipeline building",
                  required_or_preferred="unspecified", skill_category="technical")]
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS, rows)
    res = an.validate(d, manifest, texts)
    assert res["problems"] == [] and res["summary"]["skill_rows"] == 1


def test_illustrative_list_examples_are_recorded_ungrouped(ann):
    # Guidelines §3b: "languages such as C++ or Go" is an illustrative list. Default: one
    # record per named example, no alternative group, flagged for discussion.
    root, db, manifest, texts, d = ann
    a = manifest[0]
    write_review(d, manifest, {a["posting_id"]: "reviewed"})
    note = "DISCUSS: illustrative list"
    rows = [skill(a, texts, "Python", "alice-0001", required_or_preferred="preferred", review_notes=note),
            skill(a, texts, "SQL", "alice-0002", required_or_preferred="preferred", review_notes=note)]
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS, rows)
    res = an.validate(d, manifest, texts)
    assert res["problems"] == [] and res["summary"]["alternative_groups"] == 0


# ------------------------------------------------------- guideline worked examples (real data)

REAL_DB = an.REPO_ROOT / "data" / "processed" / "taxonomy_pilot.sqlite"
REAL_MANIFEST = sel.set_dir(an.REPO_ROOT) / "selection_manifest.csv"
GUIDELINES = an.REPO_ROOT / "docs" / "skill_annotation_guidelines.md"
ROBINHOOD, DUO_IOS, DUO_ANDROID = ("greenhouse:robinhood:7263592", "greenhouse:duolingo:8393272002",
                                   "greenhouse:duolingo:8628658002")
FIGMA_ML, FIGMA_AE, OURA = "greenhouse:figma:5551532004", "greenhouse:figma:5647851004", "greenhouse:oura:4203623009"
# (posting, start, end, exact text) for every offset quoted in guidelines §9.
GUIDELINE_EXAMPLES = [
    (ROBINHOOD, 3380, 3382, "Go"), (ROBINHOOD, 3386, 3392, "Python"),
    (ROBINHOOD, 3629, 3689, "technologies like Postgres, Kubernetes (K8s), Redis, and AWS"),
    (ROBINHOOD, 3647, 3655, "Postgres"), (ROBINHOOD, 3657, 3673, "Kubernetes (K8s)"),
    (ROBINHOOD, 3675, 3680, "Redis"), (ROBINHOOD, 3686, 3689, "AWS"),
    (ROBINHOOD, 3420, 3425, "Kafka"), (ROBINHOOD, 3429, 3464, "similar data streaming technologies"),
    (ROBINHOOD, 3021, 3067, "2+ years of experience in software development"),
    (ROBINHOOD, 3545, 3609, "Experience working at a fintech company or financial institution"),
    (ROBINHOOD, 3895, 3910, "401(k) matching"),
    (ROBINHOOD, 3188, 3253, "Commitment to high standards in code quality and review processes"),
    (ROBINHOOD, 3686, 3718, "AWS (or similar cloud platforms)"),
    (DUO_IOS, 2168, 2183, "data structures"), (DUO_IOS, 2185, 2195, "algorithms"),
    (DUO_IOS, 2201, 2216, "software design"), (DUO_IOS, 2598, 2623, "multithreaded programming"),
    (DUO_IOS, 2219, 2250, "Programming experience in Swift"),
    (DUO_IOS, 2030, 2098, "A Bachelor’s degree in Computer Science or a related technical field"),
    (FIGMA_ML, 3255, 3268, "collaboration"), (FIGMA_ML, 3273, 3293, "communication skills"),
    (FIGMA_ML, 3081, 3119, "additional languages such as C++ or Go"),
    (FIGMA_ML, 3110, 3113, "C++"), (FIGMA_ML, 3117, 3119, "Go"),
    (FIGMA_ML, 2443, 2519, "ML libraries like PyTorch, TensorFlow, Scikit-learn, Spark MLlib, or XGBoost"),
    (FIGMA_ML, 2443, 2455, "ML libraries"), (FIGMA_ML, 2461, 2468, "PyTorch"), (FIGMA_ML, 2470, 2480, "TensorFlow"),
    (FIGMA_ML, 2482, 2494, "Scikit-learn"), (FIGMA_ML, 2496, 2507, "Spark MLlib"), (FIGMA_ML, 2512, 2519, "XGBoost"),
    (FIGMA_ML, 3371, 3417, "At Figma, one of our values is Grow as you go."),
    (FIGMA_ML, 3151, 3244, "A product mindset with the ability to tie technical work to user outcomes and business impact"),
    (FIGMA_ML, 2662, 2689, "mentoring or leading others"),
    (FIGMA_ML, 2838, 2884, "search relevance, ranking, NLP, or RAG systems"),
    (OURA, 1523, 1529, "3D CAD"), (OURA, 1531, 1533, "NX"), (OURA, 1537, 1547, "Solidworks"),
    (OURA, 1523, 1548, "3D CAD (NX or Solidworks)"),
    (OURA, 1112, 1137, "Build a lot of prototypes"), (OURA, 1683, 1694, "Prototyping"),
    (OURA, 877, 894, "Mechanical design"), (OURA, 1139, 1170, "break them, and iterate quickly"),
    (OURA, 1017, 1109, "Drive product development with our manufacturing partners in Asia, North America, and Europe"),
    (OURA, 1023, 1042, "product development"),
    (FIGMA_AE, 1349, 1368, "revenue forecasting"), (FIGMA_AE, 1372, 1382, "Salesforce"),
    (FIGMA_AE, 1785, 1795, "Salesforce"), (FIGMA_AE, 1318, 1336, "Own sales activity"),
    (FIGMA_AE, 1273, 1315, "Manage a 360 deal cycle and exceed targets"), (FIGMA_AE, 1273, 1296, "Manage a 360 deal cycle"),
    (FIGMA_AE, 1247, 1270, "build a strong pipeline"), (FIGMA_AE, 1225, 1242, "outbound prospect"),
    (FIGMA_AE, 1385, 1466, "Work to develop and circulate best practices in a collaboration first environment"),
    (DUO_ANDROID, 1870, 1876, "Kotlin"), (DUO_ANDROID, 2062, 2068, "Kotlin"),
    (DUO_ANDROID, 1800, 1866, "Develop, release, and maintain native Android application features"),
    (DUO_ANDROID, 1879, 1885, "Mentor"), (DUO_ANDROID, 2363, 2376, "mentor others"),
    (DUO_ANDROID, 1890, 1913, "set technical direction"), (DUO_ANDROID, 2062, 2079, "Kotlin on Android"),
]


@pytest.mark.skipif(not (REAL_DB.exists() and REAL_MANIFEST.exists()), reason="local pilot DB / manifest not present")
def test_guideline_examples_match_clean_text_and_stay_outside_the_set():
    import sqlite3
    doc = GUIDELINES.read_text(encoding="utf-8")
    manifest = sel.read_manifest(REAL_MANIFEST)
    snap = manifest[0]["snapshot_id"]
    conn = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    try:
        texts = {p: conn.execute("SELECT clean_text FROM postings WHERE snapshot_id = ? AND posting_id = ?",
                                 (snap, p)).fetchone()[0] for p in {e[0] for e in GUIDELINE_EXAMPLES}}
    finally:
        conn.close()
    for pid, start, end, phrase in GUIDELINE_EXAMPLES:
        assert texts[pid][start:end] == phrase, (pid, start, end, texts[pid][start:end])
        assert f"{start}–{end}" in doc, f"offset {start}–{end} ({phrase!r}) not quoted in the guidelines"
    # no example comes from a selected posting or from any group related to one
    related = {m for r in manifest for m in r["group_members"].split(";")} | {r["posting_id"] for r in manifest}
    assert not related & set(texts)
