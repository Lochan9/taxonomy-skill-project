"""Tests for the annotation review workflow (src/review_workflow.py through the dashboard routes):
decisions, splits, discussion resolution, completion, exports, conflicts and evaluation isolation.
Synthetic repo in a temp dir (fixture from test_dashboard); no server, no network."""

from __future__ import annotations

import csv
import json
import uuid

import pytest

import annotations as an
import dashboard as dash
import extract_skills
import review_workflow as rw
from test_dashboard import DRAFT, call, decide, hdrs, repo, sha, view  # noqa: F401  (repo is a fixture)


def ok(res, code=201):
    status, body = res
    assert status == code, body
    return body


def item(v, aid):
    return next(i for i in v["items"] if i["annotation_id"] == aid)


def complete(r, pid=None, reviewer="alice", mode="development", zero=False, **kw):
    return decide(r, reviewer=reviewer, mode=mode, pid=pid, action="complete_posting", confirm_read_full_text=True,
                  confirm_checked_missing_skills=True, confirm_zero_skills=zero, **kw)


def settle_p0(r):
    """Decide every draft record of p0 and resolve its discussions."""
    ok(decide(r, annotation_id="ai_draft-0001", action="accept"))
    ok(decide(r, annotation_id="ai_draft-0002", action="edit", skill_statement="SQL querying", evidence_text="SQL",
              required_or_preferred="preferred", skill_category="tool"))
    ok(decide(r, annotation_id="ai_draft-0002", action="resolve_discussion", reason="SQL is named directly"))
    ok(decide(r, annotation_id="ai_revised-0001", action="reject", comment="task-only"))


# ------------------------------------------------------------------------- decisions + persistence


def test_actions_are_appended_with_human_provenance_and_survive_restart(repo):
    settle_p0(repo)
    add = ok(decide(repo, action="add", skill_statement="building pipelines", evidence_text="Build pipelines",
                    required_or_preferred="unspecified", review_notes="from the duty line"))
    ok(decide(repo, annotation_id="ai_draft-0001", action="reopen"))
    events = repo["app"].review.events("alice")
    assert [e["action"] for e in events] == ["accept", "edit", "resolve_discussion", "reject", "add", "reopen"]
    for k, e in enumerate(events, 1):
        assert e["seq"] == k and e["actor"] == "human" and e["reviewer_id"] == "alice"
        assert e["timestamp"].endswith("Z") and e["mode"] == "development" and e["source"] == DRAFT
        assert e["source_skills_sha256"] == sha(repo["draft"]) and e["base_version"] == k - 1
        assert e["clean_text_sha256"] == repo["ctx"].dev[repo["p0"]]["clean_text_sha256"]
    assert events[1]["original"]["skill_statement"] == "SQL"  # the AI draft row is kept for audit
    # server offsets, not client offsets
    assert repo["t0"][add["saved"]["record"]["evidence_start"]:add["saved"]["record"]["evidence_end"]] == "Build pipelines"
    # a fresh app over the same folders (= server restart) replays the same state
    app2 = dash.App(dash.Context(repo["root"], repo["db"]))
    _, v = call(app2, "GET", "/api/review/posting", f"source={DRAFT}&posting_id={repo['p0']}&reviewer=alice")
    st = {i["annotation_id"]: i["state"] for i in v["items"]}
    assert st == {"ai_draft-0001": "pending", "ai_draft-0002": "edited", "ai_revised-0001": "rejected",
                  add["saved"]["annotation_id"]: "added"}
    assert item(v, "ai_draft-0002")["current"]["skill_statement"] == "SQL querying"
    assert v["counts"]["pending"] == 1 and v["counts"]["rejected"] == 1 and v["counts"]["added"] == 1
    # decisions are per reviewer
    assert all(i["state"] == "pending" for i in view(repo, reviewer="bob")["items"])


def test_split_creates_traceable_parts(repo):
    res = ok(decide(repo, annotation_id="ai_revised-0001", action="split", parts=[
        {"skill_statement": "collaboration", "evidence_text": "Collaborate", "required_or_preferred": "unspecified"},
        {"skill_statement": "stakeholder management", "evidence_text": "stakeholders", "required_or_preferred": "unspecified"}]))
    v = res["state"]
    orig = item(v, "ai_revised-0001")
    assert orig["state"] == "split" and not orig["active"] and len(orig["split_into"]) == 2
    parts = [item(v, p) for p in orig["split_into"]]
    assert all(p["split_from"] == "ai_revised-0001" and p["state"] == "added" and p["active"] for p in parts)
    assert [repo["t0"][p["current"]["evidence_start"]:p["current"]["evidence_end"]] for p in parts] == ["Collaborate", "stakeholders"]
    # the original's AI DISCUSS flag no longer blocks: it was replaced by the parts
    assert not any(b["annotation_id"] == "ai_revised-0001" for b in v["blocking"])
    # parts can be edited and rejected like any record; the split itself cannot be reopened
    ok(decide(repo, annotation_id=parts[0]["annotation_id"], action="edit", skill_statement="collaborating",
              evidence_text="Collaborate", required_or_preferred="unspecified"))
    ok(decide(repo, annotation_id=parts[1]["annotation_id"], action="reject"))
    assert decide(repo, annotation_id="ai_revised-0001", action="reopen")[0] == 409
    # invalid splits
    assert decide(repo, annotation_id="ai_draft-0001", action="split", parts=[
        {"skill_statement": "x", "evidence_text": "Python", "required_or_preferred": "required"}])[0] == 400
    s, e = decide(repo, annotation_id="ai_draft-0001", action="split", parts=[
        {"skill_statement": "x", "evidence_text": "Python", "required_or_preferred": "required"},
        {"skill_statement": "y", "evidence_text": "not in text", "required_or_preferred": "required"}])
    assert s == 400 and e["error"].startswith("part 2:")


# ------------------------------------------------------------------------- evidence + field validation


@pytest.mark.parametrize("evidence, fragment", [
    ("python", "does not occur exactly"), ("Build  pipelines", "does not occur exactly"),
    (" Python", "whitespace"), ("", "required")])
def test_invalid_evidence_is_rejected_and_not_saved(repo, evidence, fragment):
    s, r = decide(repo, action="add", skill_statement="x", evidence_text=evidence, required_or_preferred="required")
    assert s == 400 and fragment in r["error"] and repo["app"].review.events("alice") == []


def test_repeated_evidence_requires_an_explicit_occurrence(repo):
    t = repo["t0"]
    word = next(w for w in ("role", "Build", "in") if t.count(w) > 1)
    s, r = decide(repo, action="add", skill_statement="x", evidence_text=word, required_or_preferred="required")
    assert s == 400 and "choose an occurrence" in r["error"] and len(r["occurrences"]) == t.count(word)
    second = r["occurrences"][1]
    r = ok(decide(repo, action="add", skill_statement="x", evidence_text=word, required_or_preferred="required", occurrence=2))
    assert r["saved"]["record"]["evidence_start"] == second
    assert decide(repo, action="add", skill_statement="y", evidence_text=word, required_or_preferred="required",
                  evidence_start=second + 1)[0] == 400
    assert decide(repo, action="add", skill_statement="y", evidence_text=word, required_or_preferred="required",
                  occurrence=99)[0] == 400


@pytest.mark.parametrize("change, fragment", [
    ({"required_or_preferred": "must"}, "required_or_preferred"), ({"skill_statement": "  "}, "skill_statement"),
    ({"alternative_group_id": "alt 1"}, "alternative_group_id"), ({"skill_category": "magic"}, "skill_category"),
    ({"reviewer_id": "Alice!"}, "reviewer_id"), ({"reviewer_id": "ai_revised"}, "person"),
    ({"reviewer_id": "ai-bot"}, "person"), ({"source": "annotator-a"}, "source"), ({"action": "approve"}, "action"),
    ({"client_request_id": "x"}, "client_request_id"), ({"expected_version": "0"}, "expected_version"),
])
def test_invalid_requests_are_rejected(repo, change, fragment):
    v = view(repo)
    body = {"reviewer_id": "alice", "mode": "development", "source": DRAFT, "posting_id": repo["p0"], "action": "add",
            "expected_version": v["version"], "expected_source_sha": v["draft_sha"],
            "client_request_id": uuid.uuid4().hex, "skill_statement": "SQL", "evidence_text": "SQL",
            "required_or_preferred": "required", **change}
    s, r = call(repo["app"], "POST", "/api/review/decision", body=body)
    assert s == 400 and fragment in r["error"], r


def test_alternative_group_ids_must_be_unique_across_postings(repo):
    p1 = repo["dev"][1]
    ok(decide(repo, action="add", skill_statement="Python", evidence_text="Python", required_or_preferred="required",
              alternative_group_id="g-1"))
    s, r = decide(repo, pid=p1, action="add", skill_statement="SQL", evidence_text="SQL", required_or_preferred="required",
                  alternative_group_id="g-1")
    assert s == 400 and "already used" in r["error"]


# ------------------------------------------------------------------------- discussion + completion


def test_discussion_items_block_completion_until_resolved_with_a_reason(repo):
    v = view(repo)
    assert {b["reason"] for b in v["blocking"]} >= {"no decision yet", "unresolved discussion"}
    assert v["counts"]["discussion_open"] == 2 and v["counts"]["discussion_total"] == 2
    ok(decide(repo, annotation_id="ai_draft-0001", action="accept"))
    ok(decide(repo, annotation_id="ai_draft-0002", action="accept"))
    s, r = complete(repo)
    assert s == 409 and any(b["reason"] == "unresolved discussion" for b in r["blocking"])
    assert decide(repo, annotation_id="ai_draft-0002", action="resolve_discussion", reason="  ")[0] == 400
    v = ok(decide(repo, annotation_id="ai_draft-0002", action="resolve_discussion", reason="named directly"))["state"]
    assert item(v, "ai_draft-0002")["discussion"] == {"required": True, "resolved": True, "reason": "named directly"}
    assert decide(repo, annotation_id="ai_draft-0001", action="resolve_discussion", reason="x")[0] == 400  # no flag
    # rejecting a flagged suggestion takes it out of the way; a DISCUSS edit reopens the question
    ok(decide(repo, annotation_id="ai_revised-0001", action="reject"))
    ok(decide(repo, annotation_id="ai_draft-0002", action="edit", skill_statement="SQL", evidence_text="SQL",
              required_or_preferred="required", review_notes="DISCUSS: preferred or required?"))
    v = view(repo)
    assert item(v, "ai_draft-0002")["discussion_open"] and v["counts"]["discussion_open"] == 1


def test_posting_level_discussion_must_be_resolved(repo):
    rf = repo["draft"].with_name("postings_review.csv")
    rows = list(csv.DictReader(rf.open(encoding="utf-8", newline="")))
    for r in rows:
        if r["posting_id"] == repo["p0"]:
            r["review_notes"] = "AI-REVISED: notes | DISCUSS: is the PhD line a skill?"
    an._write_csv(rf, an.REVIEW_FIELDS, rows)
    settle_p0(repo)
    s, r = complete(repo)
    assert s == 409 and any(b["annotation_id"] == rw.POSTING_ITEM for b in r["blocking"])
    ok(decide(repo, annotation_id=rw.POSTING_ITEM, action="resolve_discussion", reason="qualification, not a skill"))
    assert complete(repo)[0] == 201


def test_completion_requires_confirmations_and_records_versions(repo):
    g = repo["root"] / "docs" / "skill_annotation_guidelines.md"
    g.parent.mkdir(parents=True, exist_ok=True)
    g.write_text("# Skill Annotation Guidelines (Team B, Sprint 2), v9.8.7 DRAFT\n")
    s, r = complete(repo)
    assert s == 409 and len(r["blocking"]) >= 3          # pending decisions and open discussions
    settle_p0(repo)
    assert decide(repo, action="complete_posting", confirm_read_full_text=True)[0] == 400
    assert decide(repo, action="complete_posting", confirm_checked_missing_skills=True)[0] == 400
    r = ok(complete(repo))
    c = r["saved"]["completion"]
    assert c["guidelines"] == {"version": "9.8.7", "sha256": sha(g)}
    assert c["draft_sha256"] == sha(repo["draft"]) and c["zero_skills"] is False
    assert r["saved"]["clean_text_sha256"] == repo["ctx"].dev[repo["p0"]]["clean_text_sha256"]
    assert r["state"]["status"] == "completed" and complete(repo)[0] == 409   # already completed
    # any change invalidates the completion until reconfirmed
    v = ok(decide(repo, annotation_id="ai_draft-0001", action="reopen"))["state"]
    assert v["status"] == "completion_invalidated" and v["completion"] is None
    ok(decide(repo, annotation_id="ai_draft-0001", action="accept"))
    assert ok(complete(repo))["state"]["status"] == "completed"
    v = ok(decide(repo, action="reopen_posting"))["state"]
    assert v["status"] == "completion_invalidated"


def test_zero_skill_posting_needs_a_deliberate_confirmation(repo):
    p1 = repo["dev"][1]                                  # no AI drafts for this posting
    s, r = complete(repo, pid=p1)
    assert s == 400 and "zero-skill" in r["error"]
    r = ok(complete(repo, pid=p1, zero=True))
    assert r["saved"]["completion"]["zero_skills"] is True and r["state"]["status"] == "completed"


def test_single_member_alternative_group_blocks_completion(repo):
    settle_p0(repo)
    ok(decide(repo, annotation_id="ai_draft-0001", action="edit", skill_statement="Python", evidence_text="Python",
              required_or_preferred="required", alternative_group_id="p00-alt-1"))
    s, r = complete(repo)
    assert s == 409 and any("only one active record" in b["reason"] for b in r["blocking"])


# ------------------------------------------------------------------------- integrity


def test_stale_version_and_duplicate_clicks_never_overwrite(repo):
    rid = uuid.uuid4().hex
    v0 = view(repo)
    first = ok(decide(repo, annotation_id="ai_draft-0001", action="accept", request_id=rid))
    again = ok(decide(repo, annotation_id="ai_draft-0001", action="accept", request_id=rid, expected_version=0), 200)
    assert again["created"] is False and again["saved"]["decision_id"] == first["saved"]["decision_id"]
    assert len(repo["app"].review.events("alice")) == 1
    # the same request id cannot be reused for a different decision
    assert decide(repo, annotation_id="ai_draft-0001", action="reject", request_id=rid)[0] == 409
    # a second tab working from the old version gets a conflict, not a silent overwrite
    s, r = decide(repo, annotation_id="ai_draft-0001", action="reject", expected_version=v0["version"])
    assert s == 409 and r["current_version"] == 1 and len(repo["app"].review.events("alice")) == 1


def test_changed_draft_file_is_detected(repo):
    ok(decide(repo, annotation_id="ai_draft-0001", action="accept"))
    old = view(repo)
    rows = list(csv.DictReader(repo["draft"].open(encoding="utf-8", newline="")))
    rows[0]["skill_statement"] = "Python programming"      # the AI draft changes after the decision
    an._write_csv(repo["draft"], an.SKILL_FIELDS, rows)
    s, r = decide(repo, annotation_id="ai_draft-0002", action="accept", expected_source_sha=old["draft_sha"])
    assert s == 409 and "draft file changed" in r["error"]
    v = view(repo)
    it = item(v, "ai_draft-0001")
    assert it["stale"] and any(b["reason"].startswith("stale") for b in v["blocking"])
    v = ok(decide(repo, annotation_id="ai_draft-0001", action="accept"))["state"]   # re-decide on the new draft
    assert not item(v, "ai_draft-0001")["stale"] and item(v, "ai_draft-0001")["current"]["skill_statement"] == "Python programming"


# ------------------------------------------------------------------------- export


def test_partial_export_applies_latest_decisions_and_validates(repo):
    settle_p0(repo)
    ok(decide(repo, annotation_id="ai_revised-0001", action="reopen"))
    ok(decide(repo, annotation_id="ai_revised-0001", action="split", parts=[
        {"skill_statement": "collaboration", "evidence_text": "Collaborate", "required_or_preferred": "unspecified"},
        {"skill_statement": "stakeholder management", "evidence_text": "stakeholders", "required_or_preferred": "unspecified"}]))
    ok(decide(repo, action="add", skill_statement="building pipelines", evidence_text="Build pipelines",
              required_or_preferred="unspecified"))
    _, p = call(repo["app"], "GET", "/api/export/preview", f"reviewer=alice&source={DRAFT}")
    assert p["status"] == "partial" and p["gold"] is False and p["problems"] == []
    stmts = sorted(r["skill_statement"] for r in p["skill_rows"])
    assert stmts == ["Python", "SQL querying", "building pipelines", "collaboration", "stakeholder management"]
    notes = {r["skill_statement"]: r["review_notes"] for r in p["skill_rows"]}
    assert "AI-assisted draft ai_draft-0001" in notes["Python"] and "accepted by alice" in notes["Python"]
    assert "edited by alice" in notes["SQL querying"] and "discussion resolved: SQL is named directly" in notes["SQL querying"]
    assert "split from ai_revised-0001" in notes["collaboration"] and "HUMAN-ANNOTATED: added" in notes["building pipelines"]
    assert all(r["annotator_id"] == "alice" for r in p["skill_rows"])
    # write: a new folder each time, never under annotators/, never overwriting
    s1, w1 = call(repo["app"], "POST", "/api/export", body={"reviewer_id": "alice", "mode": "development", "source": DRAFT})
    s2, w2 = call(repo["app"], "POST", "/api/export", body={"reviewer_id": "alice", "mode": "development", "source": DRAFT})
    assert s1 == s2 == 201 and w1["written"]["path"] != w2["written"]["path"]
    out = dash.Path(w1["written"]["path"])
    assert out.is_relative_to(repo["ctx"].reviewed_dir) and "annotators" not in out.parts
    meta = json.loads((out / "export.json").read_text())
    assert meta["status"] == "partial" and meta["gold"] is False and "PARTIAL" in meta["note"]
    texts = an.load_texts(repo["db"], repo["manifest"])
    assert an.validate(out, repo["manifest"], texts)["problems"] == []
    reviews = {r["posting_id"]: r["review_status"] for r in csv.DictReader((out / "postings_review.csv").open())}
    assert reviews[repo["p0"]] == "in_progress" and sum(v == "not_started" for v in reviews.values()) == 99
    prov = [json.loads(l) for l in (out / "provenance.jsonl").read_text().splitlines()]
    assert {p["origin"] for p in prov} == {"draft", "reviewer"} and any(p["split_from"] == "ai_revised-0001" for p in prov)
    # download returns the same CSV format
    s, body = call(repo["app"], "GET", "/api/export/download", f"reviewer=alice&source={DRAFT}&file=skills.csv")
    assert s == 200 and body.decode().splitlines()[0] == ",".join(an.SKILL_FIELDS)


def test_full_export_only_when_every_posting_is_reviewed(repo):
    settle_p0(repo)
    ok(complete(repo))
    for pid in repo["dev"][1:-1]:
        ok(complete(repo, pid=pid, zero=True))
    _, p = call(repo["app"], "GET", "/api/export/preview", f"reviewer=alice&source={DRAFT}")
    assert p["status"] == "partial" and p["postings"]["completed"] == 19
    ok(complete(repo, pid=repo["dev"][-1], zero=True))
    _, p = call(repo["app"], "GET", "/api/export/preview", f"reviewer=alice&source={DRAFT}")
    assert p["status"] == "complete" and p["gold"] is False and "not gold" in p["note"]
    _, w = call(repo["app"], "POST", "/api/export", body={"reviewer_id": "alice", "mode": "development", "source": DRAFT})
    out = dash.Path(w["written"]["path"])
    texts = an.load_texts(repo["db"], repo["manifest"])
    res = an.validate(out, [r for r in repo["manifest"]], texts)
    assert res["problems"] == [] and res["summary"]["reviewed"] == 20
    rows = list(csv.DictReader((out / "postings_review.csv").open()))
    assert all("not gold until adjudicated" in r["review_notes"] for r in rows if r["review_status"] == "reviewed")


def test_invalid_export_is_previewed_but_not_written(repo):
    p1 = repo["dev"][1]
    ok(decide(repo, pid=p1, action="add", skill_statement="Python", evidence_text="Python", required_or_preferred="required",
              alternative_group_id="lonely"))
    _, p = call(repo["app"], "GET", "/api/export/preview", f"reviewer=alice&source={DRAFT}")
    assert any("only one record" in x for x in p["problems"])
    s, r = call(repo["app"], "POST", "/api/export", body={"reviewer_id": "alice", "mode": "development", "source": DRAFT})
    assert s == 409 and not repo["ctx"].reviewed_dir.exists()


# ------------------------------------------------------------------------- independent evaluation mode


def test_evaluation_mode_is_isolated_and_starts_empty(repo, monkeypatch):
    app, ev = repo["app"], repo["ev"][0]
    # evaluation mode never reads AI drafts
    monkeypatch.setattr(rw.Review, "draft_file", lambda *a: (_ for _ in ()).throw(AssertionError("draft read")))
    s, o = call(app, "GET", "/api/review", "mode=evaluation&reviewer=eve", headers=hdrs("evaluation"))
    assert s == 200 and {p["posting_id"] for p in o["postings"]} == set(repo["ev"]) and o["progress"]["total"] == 80
    v = view(repo, reviewer="eve", mode="evaluation", pid=ev)
    assert v["items"] == [] and v["draft_sha"] is None and v["posting_discussion"]["required"] is False
    assert "".join(x["text"] for x in v["segments"]) == repo["app"].review.text("evaluation", ev)
    assert "AI" not in json.dumps({k: v[k] for k in ("items", "segments", "counts")})
    # add / edit / delete / reopen / split, with the same evidence checks
    a = ok(decide(repo, reviewer="eve", mode="evaluation", pid=ev, action="add", skill_statement="Python",
                  evidence_text="Python", required_or_preferred="required"))["saved"]["annotation_id"]
    assert decide(repo, reviewer="eve", mode="evaluation", pid=ev, action="add", skill_statement="x",
                  evidence_text="nope", required_or_preferred="required")[0] == 400
    ok(decide(repo, reviewer="eve", mode="evaluation", pid=ev, annotation_id=a, action="edit", skill_statement="Python 3",
              evidence_text="Python", required_or_preferred="preferred"))
    ok(decide(repo, reviewer="eve", mode="evaluation", pid=ev, annotation_id=a, action="delete"))
    ok(decide(repo, reviewer="eve", mode="evaluation", pid=ev, annotation_id=a, action="reopen"))
    assert decide(repo, reviewer="eve", mode="evaluation", pid=ev, annotation_id=a, action="accept")[0] == 400
    v = ok(complete(repo, reviewer="eve", mode="evaluation", pid=ev))["state"]
    assert v["status"] == "completed" and v["counts"]["active"] == 1
    # the evaluation export carries only evaluation postings
    _, p = call(app, "GET", "/api/export/preview", "mode=evaluation&reviewer=eve", headers=hdrs("evaluation"))
    assert p["problems"] == [] and {r["posting_id"] for r in p["skill_rows"]} == {ev} and p["status"] == "partial"
    assert p["reviewed_postings"] == [ev]
    assert "independent evaluation mode" in p["skill_rows"][0]["review_notes"]
    # development routes and extraction stay closed to evaluation postings
    assert call(app, "GET", "/api/review/posting", f"posting_id={ev}&reviewer=eve&source={DRAFT}")[0] == 403
    assert call(app, "GET", "/api/corpus/posting", f"posting_id={ev}")[0] == 403
    assert extract_skills.ALLOWED_SPLITS == frozenset({"development"})
    # development postings are not reachable in evaluation mode
    assert call(app, "GET", "/api/review/posting", f"mode=evaluation&posting_id={repo['p0']}&reviewer=eve",
                headers=hdrs("evaluation"))[0] == 403


def test_review_never_changes_drafts_texts_or_selection(repo):
    watched = [repo["db"], repo["draft"], repo["draft"].with_name("postings_review.csv"),
               repo["ctx"].set_dir / "selection_manifest.csv"]
    before = {p: sha(p) for p in watched}
    settle_p0(repo)
    ok(complete(repo))
    ok(decide(repo, reviewer="eve", mode="evaluation", pid=repo["ev"][0], action="add", skill_statement="Python",
              evidence_text="Python", required_or_preferred="required"))
    call(repo["app"], "POST", "/api/export", body={"reviewer_id": "alice", "mode": "development", "source": DRAFT})
    assert {p: sha(p) for p in watched} == before
    assert sorted(p.name for p in (repo["ctx"].set_dir / "annotators").iterdir()) == [DRAFT]
