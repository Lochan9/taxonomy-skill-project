"""Tests for src/dashboard.py: evidence highlighting, review persistence, invalid evidence,
held-out data and preservation of source data. Synthetic repo in a temp dir; no server, no network."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from wsgiref.util import setup_testing_defaults

import pytest

import annotations as an
import dashboard as dash
import select_annotation_set as sel
from test_annotation_set import SNAP, build_db

DRAFT = "ai_revised"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    db = build_db(root)
    assert sel.main(["--db", str(db), "--snapshot", SNAP, "--root", str(root)]) == 0
    base = sel.set_dir(root)
    manifest = sel.read_manifest(base / "selection_manifest.csv")
    texts = an.load_texts(db, manifest)
    dev = sorted(r["posting_id"] for r in manifest if r["split"] == "development")
    ev = sorted(r["posting_id"] for r in manifest if r["split"] == "evaluation")
    p0 = dev[0]
    t0 = texts[p0]

    # an AI draft workspace (development rows only), like annotators/ai_revised
    an.export(db, root)
    d = an.init_annotator(DRAFT, root)
    def row(aid, ev_text, stmt, notes="AI-REVISED: test draft", occ=1):
        s, e = an.locate(t0, ev_text, occ)
        return {"snapshot_id": SNAP, "posting_id": p0, "annotation_id": aid, "skill_statement": stmt,
                "evidence_text": ev_text, "evidence_start": s, "evidence_end": e, "required_or_preferred": "required",
                "alternative_group_id": "", "skill_category": "tool", "annotator_id": DRAFT, "review_notes": notes}
    an._write_csv(d / "skills.csv", an.SKILL_FIELDS, [
        row("ai_draft-0001", "Python", "Python"),
        row("ai_draft-0002", "SQL", "SQL", notes="AI-REVISED: x | DISCUSS: illustrative list (§3b)"),
        row("ai_revised-0001", "Collaborate with stakeholders", "stakeholder collaboration",
            notes="AI-SUGGESTED ADDITION: report | DISCUSS: suggested addition"),
    ])

    # a saved extraction run: one valid statement, one overlapping, one with a tampered offset
    rd = root / "data" / "extraction" / "runs" / "skx-test"
    rd.mkdir(parents=True)
    ps, pe = t0.index("Python"), t0.index("Python") + 6
    stmt = lambda n, text, s, e, span, rel="direct", ex=None: {
        "statement_id": f"skx-test:{p0}:skill:{n}", "posting_id": p0, "snapshot_id": SNAP, "kind": "skill",
        "text": text, "source_span": span, "evidence_start": s, "evidence_end": e, "evidence_resolution": "unique",
        "section": None, "requirement_status": "required", "mention_relation": rel, "example_of": ex,
        "alternative_group": None, "skill_category": "tool", "model_notes": None}
    clause = "Build pipelines in Python and SQL."
    cs = t0.index(clause)
    statements = [stmt(0, "Python", ps, pe, "Python", "illustrative_example", "languages"),
                  stmt(1, "pipelines", cs, cs + len(clause), clause),
                  stmt(2, "SQL", 0, 3, "SQL")]  # tampered: offsets do not point at "SQL"
    (rd / "statements.jsonl").write_text("".join(json.dumps(s) + "\n" for s in statements))
    (rd / "rejected.jsonl").write_text(json.dumps({"run_id": "skx-test", "posting_id": p0, "model_index": 3,
                                                   "reason": "unsupported: evidence_text does not occur in clean_text",
                                                   "record": {"skill_statement": "Rust", "evidence_text": "Rust"}}) + "\n")
    (rd / "postings.jsonl").write_text(json.dumps({"posting_id": p0, "snapshot_id": SNAP, "status": "ok", "cache_hit": False,
                                                   "usage": {"input_tokens": 10, "output_tokens": 5}, "request_id": "req_x",
                                                   "attempts": [], "error": None}) + "\n")
    (rd / "run.json").write_text(json.dumps({"run_id": "skx-test", "model": "test-model", "provider": "anthropic",
                                             "status": "finished", "prompt_version": "v1", "schema_version": "s1",
                                             "counts": {"ok": 1}, "n_statements": 3, "llm_tokens_in": 10,
                                             "llm_tokens_out": 5, "token_usage_billed": {"input_tokens": 10},
                                             "config": {"provider_access": "university-provided Anthropic access",
                                                        "brief_p7_compliance": "unresolved"}}))
    ctx = dash.Context(root, db)
    return {"root": root, "db": db, "ctx": ctx, "app": dash.App(ctx), "dev": dev, "ev": ev, "p0": p0, "t0": t0,
            "manifest": manifest, "draft": d / "skills.csv", "run": rd}


def call(app, method, path, qs="", body=None, headers=None, host="127.0.0.1:8765"):
    env = {}
    setup_testing_defaults(env)
    data = json.dumps(body).encode() if body is not None else b""
    env.update(REQUEST_METHOD=method, PATH_INFO=path, QUERY_STRING=qs, HTTP_HOST=host, CONTENT_TYPE="application/json",
               CONTENT_LENGTH=str(len(data)), **{"wsgi.input": io.BytesIO(data)})
    env.update({"HTTP_X_DASHBOARD": "1"} if headers is None else headers)
    out = {}
    body_bytes = b"".join(app(env, lambda status, hdrs: out.update(status=status, headers=dict(hdrs))))
    ctype = out["headers"]["Content-Type"]
    return int(out["status"][:3]), json.loads(body_bytes) if ctype.startswith("application/json") else body_bytes


def decide(r, **kw):
    body = {"reviewer_id": "alice", "source": DRAFT, "posting_id": r["p0"], **kw}
    return call(r["app"], "POST", "/api/review/decision", body=body)


# ------------------------------------------------------------------------- highlighting


def test_segments_reassemble_text_and_mark_overlaps():
    text = "Strong SQL and Python skills."
    spans = [{"id": "a", "start": 7, "end": 10, "evidence": "SQL"},
             {"id": "b", "start": 0, "end": 21, "evidence": "Strong SQL and Python"},
             {"id": "c", "start": 15, "end": 21, "evidence": "Python"}]
    segs, invalid = dash.segment_text(text, spans)
    assert "".join(s["text"] for s in segs) == text and invalid == []
    by = {s["text"]: s["ids"] for s in segs}
    assert by["SQL"] == ["a", "b"] and by["Python"] == ["b", "c"] and by[" skills."] == []


@pytest.mark.parametrize("span", [
    {"id": "x", "start": 0, "end": 3, "evidence": "SQL"},          # offsets point at other words
    {"id": "x", "start": 7, "end": 99, "evidence": "SQL"},         # out of range
    {"id": "x", "start": "7", "end": 10, "evidence": "SQL"},       # not integers
    {"id": "x", "start": 10, "end": 7, "evidence": "SQL"},         # reversed
])
def test_invalid_offsets_are_reported_not_highlighted_or_repaired(span):
    text = "Strong SQL and Python skills."
    segs, invalid = dash.segment_text(text, [span])
    assert invalid == [{"id": "x", "reason": "offsets do not match clean_text"}]
    assert segs == [{"text": text, "ids": []}]


def test_extraction_view_highlights_validated_offsets_only(repo):
    status, d = call(repo["app"], "GET", "/api/run/posting", f"run_id=skx-test&posting_id={repo['p0']}")
    assert status == 200 and d["label"] == "AI-generated, unreviewed" and not d["empty"]
    assert "".join(s["text"] for s in d["segments"]) == repo["t0"]
    marked = {i for s in d["segments"] for i in s["ids"]}
    tampered = f"skx-test:{repo['p0']}:skill:2"
    assert tampered not in marked and [i["id"] for i in d["invalid_offsets"]] == [tampered]
    by = {s["text"]: s for s in d["statements"]}
    assert by["SQL"]["offset_valid"] is False and by["Python"]["offset_valid"] is True
    # illustrative examples are labelled apart from individual requirements
    assert by["Python"]["kind_of_mention"] == "illustrative example" and by["pipelines"]["kind_of_mention"] == "individual requirement"
    # the overlapping "Python" is covered by both the clause and the word
    assert any(set(s["ids"]) == {f"skx-test:{repo['p0']}:skill:0", f"skx-test:{repo['p0']}:skill:1"} for s in d["segments"])
    assert d["rejected"][0]["reason"].startswith("unsupported")


def test_run_overview_shows_model_tokens_and_empty_states(repo):
    status, d = call(repo["app"], "GET", "/api/run", "run_id=skx-test")
    assert status == 200 and d["model"] == "test-model" and d["llm_tokens_in"] == 10 and d["llm_tokens_out"] == 5
    assert d["brief_p7_compliance"] == "unresolved" and len(d["postings"]) == 20
    assert sum(p["status"] is None for p in d["postings"]) == 19
    other = next(p for p in repo["dev"] if p != repo["p0"])
    status, e = call(repo["app"], "GET", "/api/run/posting", f"run_id=skx-test&posting_id={other}")
    assert status == 200 and e["empty"] is True and e["statements"] == []
    assert call(repo["app"], "GET", "/api/run", "run_id=../../etc")[0] == 400
    # the header's snapshot label can be filled from any view (found in browser testing)
    assert call(repo["app"], "GET", "/api/runs")[1]["snapshot_id"] == SNAP
    assert call(repo["app"], "GET", "/api/review", f"source={DRAFT}")[1]["snapshot_id"] == SNAP


# ------------------------------------------------------------------------- review persistence


def test_review_decisions_are_appended_with_reviewer_and_timestamp(repo):
    s1, a = decide(repo, annotation_id="ai_draft-0001", action="accept")
    s2, e = decide(repo, annotation_id="ai_draft-0002", action="edit", skill_statement="SQL querying",
                   evidence_text="SQL", required_or_preferred="preferred", skill_category="tool",
                   review_notes="DISCUSS: still unsure")
    s3, x = decide(repo, annotation_id="ai_revised-0001", action="reject", comment="task-only")
    s4, add = decide(repo, action="add", skill_statement="building pipelines", evidence_text="Build pipelines",
                     required_or_preferred="unspecified")
    assert (s1, s2, s3, s4) == (201, 201, 201, 201)
    lines = dash.load_decisions(repo["ctx"], "alice")
    assert [d["action"] for d in lines] == ["accept", "edit", "reject", "add"]
    for d in lines:
        assert d["reviewer_id"] == "alice" and d["timestamp"].endswith("Z") and d["source"] == DRAFT
        assert d["clean_text_sha256"] == hashlib.sha256(repo["t0"].encode()).hexdigest()
        assert d["source_skills_sha256"] == sha(repo["draft"])
    # offsets come from the server, and the edit keeps the original draft for audit
    assert lines[1]["record"]["evidence_start"] == repo["t0"].index("SQL") and lines[1]["original"]["skill_statement"] == "SQL"
    assert repo["t0"][lines[3]["record"]["evidence_start"]:lines[3]["record"]["evidence_end"]] == "Build pipelines"
    # the effective view reflects the latest decision; unresolved flags stay visible
    status, v = call(repo["app"], "GET", "/api/review/posting", f"source={DRAFT}&posting_id={repo['p0']}&reviewer=alice")
    states = {i["annotation_id"]: i for i in v["items"]}
    assert states["ai_draft-0001"]["state"] == "accepted" and states["ai_draft-0002"]["state"] == "edited"
    assert states["ai_draft-0002"]["current"]["skill_statement"] == "SQL querying"
    assert "discuss" in states["ai_draft-0002"]["flags"] and "illustrative" in states["ai_draft-0002"]["flags"]
    assert states["ai_revised-0001"]["state"] == "rejected" and "suggested_addition" in states["ai_revised-0001"]["flags"]
    added = [i for i in v["items"] if i["origin"] == "reviewer"]
    assert len(added) == 1 and added[0]["state"] == "added" and all(i["offset_valid"] for i in v["items"])
    # reopen returns a record to pending; the log keeps every step
    decide(repo, annotation_id="ai_draft-0001", action="reopen")
    _, v2 = call(repo["app"], "GET", "/api/review/posting", f"source={DRAFT}&posting_id={repo['p0']}&reviewer=alice")
    assert {i["annotation_id"]: i["state"] for i in v2["items"]}["ai_draft-0001"] == "pending"
    assert len(dash.load_decisions(repo["ctx"], "alice")) == 5
    # decisions are per reviewer
    _, v3 = call(repo["app"], "GET", "/api/review/posting", f"source={DRAFT}&posting_id={repo['p0']}&reviewer=bob")
    assert all(i["state"] == "pending" for i in v3["items"])


def test_reviewer_added_record_can_be_edited_and_rejected(repo):
    _, add = decide(repo, action="add", skill_statement="SQL", evidence_text="SQL", required_or_preferred="required")
    aid = add["saved"]["annotation_id"]
    assert aid.startswith("alice-add-")
    assert decide(repo, annotation_id=aid, action="edit", skill_statement="SQL (querying)", evidence_text="SQL",
                  required_or_preferred="required")[0] == 201
    assert decide(repo, annotation_id=aid, action="reject")[0] == 201
    _, v = call(repo["app"], "GET", "/api/review/posting", f"source={DRAFT}&posting_id={repo['p0']}&reviewer=alice")
    it = next(i for i in v["items"] if i["annotation_id"] == aid)
    assert it["state"] == "rejected" and it["current"]["skill_statement"] == "SQL (querying)"
    assert decide(repo, annotation_id=aid, action="accept")[0] == 400  # accept is for draft records


# ------------------------------------------------------------------------- invalid evidence


@pytest.mark.parametrize("evidence, fragment", [
    ("python", "does not occur exactly"),                    # wrong case
    ("Build  pipelines", "does not occur exactly"),          # changed spacing
    (" Python", "whitespace"),
    ("", "required"),
])
def test_invalid_evidence_is_rejected_and_not_saved(repo, evidence, fragment):
    status, r = decide(repo, action="add", skill_statement="x", evidence_text=evidence, required_or_preferred="required")
    assert status == 400 and fragment in r["error"]
    assert dash.load_decisions(repo["ctx"], "alice") == []


def test_repeated_evidence_requires_an_explicit_occurrence(repo):
    t = repo["t0"]
    word = next(w for w in ("role", "Build", "in") if t.count(w) > 1)
    status, r = decide(repo, action="add", skill_statement="x", evidence_text=word, required_or_preferred="required")
    assert status == 400 and "choose an occurrence" in r["error"] and len(r["occurrences"]) == t.count(word)
    second = r["occurrences"][1]
    status, r = decide(repo, action="add", skill_statement="x", evidence_text=word, required_or_preferred="required",
                       occurrence=2)
    assert status == 201 and r["saved"]["record"]["evidence_start"] == second
    assert decide(repo, action="add", skill_statement="x", evidence_text=word, required_or_preferred="required",
                  evidence_start=second + 1)[0] == 400  # a client offset must point at a real occurrence
    assert decide(repo, action="add", skill_statement="x", evidence_text=word, required_or_preferred="required",
                  occurrence=99)[0] == 400


@pytest.mark.parametrize("change, fragment", [
    ({"required_or_preferred": "must"}, "required_or_preferred"),
    ({"skill_statement": "  "}, "skill_statement"),
    ({"alternative_group_id": "alt 1"}, "alternative_group_id"),
    ({"skill_category": "magic"}, "skill_category"),
    ({"reviewer_id": "Alice!"}, "reviewer_id"),
    ({"reviewer_id": "ai_revised"}, "person"),
    ({"source": "annotator-a"}, "source"),
    ({"action": "approve"}, "action"),
])
def test_invalid_fields_are_rejected(repo, change, fragment):
    body = {"reviewer_id": "alice", "source": DRAFT, "posting_id": repo["p0"], "action": "add",
            "skill_statement": "SQL", "evidence_text": "SQL", "required_or_preferred": "required", **change}
    status, r = call(repo["app"], "POST", "/api/review/decision", body=body)
    assert status == 400 and fragment in r["error"]


# ------------------------------------------------------------------------- held-out data


def test_evaluation_texts_and_labels_stay_out(repo):
    ev = repo["ev"][0]
    app = repo["app"]
    assert call(app, "GET", "/api/corpus/posting", f"posting_id={ev}")[0] == 403
    assert call(app, "GET", "/api/review/posting", f"source={DRAFT}&posting_id={ev}")[0] == 403
    assert call(app, "GET", "/api/run/posting", f"run_id=skx-test&posting_id={ev}")[0] == 403
    assert call(app, "GET", "/api/locate", f"posting_id={ev}&evidence=Python")[0] == 403
    status, r = call(app, "POST", "/api/review/decision", body={"reviewer_id": "alice", "source": DRAFT, "posting_id": ev,
                                                                "action": "add", "skill_statement": "x",
                                                                "evidence_text": "Python", "required_or_preferred": "required"})
    assert status == 403
    status, c = call(app, "GET", "/api/corpus")
    assert status == 200 and "clean_text" not in json.dumps(c)          # listings never carry texts
    assert {p["posting_id"] for p in c["postings"] if p["held_out"]} >= set(repo["ev"])
    status, o = call(app, "GET", "/api/review", f"source={DRAFT}")
    assert {p["posting_id"] for p in o["postings"]} == set(repo["dev"])  # development only
    assert call(app, "GET", "/api/review", "source=annotator-a")[0] == 400  # human folders are not loaded


def test_variants_grouped_with_evaluation_postings_are_held_out(repo):
    variant = next((m for r in repo["manifest"] if r["split"] == "evaluation"
                    for m in r["group_members"].split(";") if m != r["posting_id"]), None)
    if variant is None:
        pytest.skip("synthetic selection has no grouped evaluation variant")
    assert variant in repo["ctx"].held_out
    assert call(repo["app"], "GET", "/api/corpus/posting", f"posting_id={variant}")[0] == 403


def test_corpus_filters(repo):
    _, all_ = call(repo["app"], "GET", "/api/corpus")
    emp = all_["facets"]["employers"][0]
    _, f = call(repo["app"], "GET", "/api/corpus", f"employer={emp.replace(' ', '+')}")
    assert f["shown"] and all(p["company_name"] == emp for p in f["postings"])
    _, x = call(repo["app"], "GET", "/api/corpus", "exclusion=excluded")
    assert x["shown"] == 2 and all(p["excluded"] for p in x["postings"])
    _, u = call(repo["app"], "GET", "/api/corpus", "exclusion=usable")
    assert u["shown"] == all_["total"] - 2


# ------------------------------------------------------------------------- source preservation + safety


def test_source_data_is_never_modified(repo):
    watched = [repo["db"], repo["draft"], repo["draft"].with_name("postings_review.csv"),
               sel.set_dir(repo["root"]) / "selection_manifest.csv", *sorted(repo["run"].iterdir())]
    before = {p: sha(p) for p in watched}
    app = repo["app"]
    for path, qs in [("/api/corpus", ""), ("/api/corpus/posting", f"posting_id={repo['p0']}"), ("/api/runs", ""),
                     ("/api/run", "run_id=skx-test"), ("/api/run/posting", f"run_id=skx-test&posting_id={repo['p0']}"),
                     ("/api/review", f"source={DRAFT}&reviewer=alice"),
                     ("/api/review/posting", f"source={DRAFT}&posting_id={repo['p0']}&reviewer=alice")]:
        assert call(app, "GET", path, qs)[0] == 200
    decide(repo, annotation_id="ai_draft-0001", action="edit", skill_statement="Python 3", evidence_text="Python",
           required_or_preferred="required")
    decide(repo, annotation_id="ai_draft-0002", action="reject")
    decide(repo, action="add", skill_statement="x", evidence_text="SQL", required_or_preferred="required")
    assert {p: sha(p) for p in watched} == before
    written = [p for p in repo["root"].rglob("*") if p.is_file() and "reviews" in p.parts]
    assert [p.name for p in written] == ["decisions.jsonl"]


def test_requests_must_be_local_and_from_the_page(repo):
    app = repo["app"]
    assert call(app, "GET", "/api/runs", host="evil.example:8765")[0] == 403
    body = {"reviewer_id": "alice", "source": DRAFT, "posting_id": repo["p0"], "annotation_id": "ai_draft-0001",
            "action": "accept"}
    assert call(app, "POST", "/api/review/decision", body=body, headers={})[0] == 403   # no X-Dashboard header
    assert call(app, "GET", "/static/../dashboard.py")[0] == 404
    assert call(app, "GET", "/figures/../../db.sqlite")[0] == 404
    assert dash.load_decisions(repo["ctx"], "alice") == []


def test_dashboard_never_reads_credentials():
    src = Path(dash.__file__).read_text()
    assert "dotenv" not in src and "import anthropic" not in src and "API_KEY" not in src
    js = (dash.STATIC / "app.js").read_text()
    assert "innerHTML" not in js and "http://" not in js and "https://" not in js  # local, text-only rendering


def test_real_server_sends_one_content_length_per_response(repo):
    # Regression: a shared header list was mutated by wsgiref (found in browser testing), so every
    # response after /favicon.ico carried a second "Content-Length: 0" and Chrome refused the page.
    import http.client
    import threading
    from wsgiref.simple_server import WSGIRequestHandler, make_server

    class Quiet(WSGIRequestHandler):
        def log_message(self, *a):
            pass

    srv = make_server("127.0.0.1", 0, repo["app"], handler_class=Quiet)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        port = srv.server_address[1]
        for path in ["/favicon.ico", "/", "/api/runs", "/favicon.ico", "/static/app.js", "/"]:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
            r = c.getresponse()
            body = r.read()
            lengths = [v for k, v in r.getheaders() if k.lower() == "content-length"]
            assert len(lengths) == 1 and int(lengths[0]) == len(body), (path, lengths)
            assert r.status == (204 if path == "/favicon.ico" else 200)
            c.close()
    finally:
        srv.shutdown()
        srv.server_close()
    assert isinstance(dash.SECURITY_HEADERS, tuple)
