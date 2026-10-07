"""Tests for src/dashboard.py routes: evidence highlighting, extraction view, held-out data, source
preservation and request safety (the review workflow itself: tests/test_review_workflow.py). Synthetic repo in a temp dir; no server, no network."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
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


def hdrs(mode="development"):
    return {"HTTP_X_DASHBOARD": "1", **({"HTTP_X_DASHBOARD_MODE": "evaluation"} if mode == "evaluation" else {})}


def view(r, reviewer="alice", mode="development", pid=None, source=DRAFT):
    status, v = call(r["app"], "GET", "/api/review/posting",
                     f"mode={mode}&source={source}&posting_id={pid or r['p0']}&reviewer={reviewer}", headers=hdrs(mode))
    assert status == 200, v
    return v


def decide(r, reviewer="alice", mode="development", pid=None, request_id=None, expected_version=None,
           expected_source_sha=None, **kw):
    """POST a decision the way the page does: current version + draft hash + a fresh request id."""
    pid = pid or r["p0"]
    v = view(r, reviewer, mode, pid)
    body = {"reviewer_id": reviewer, "mode": mode, "source": DRAFT, "posting_id": pid,
            "expected_version": v["version"] if expected_version is None else expected_version,
            "expected_source_sha": v["draft_sha"] if expected_source_sha is None else expected_source_sha,
            "client_request_id": request_id or uuid.uuid4().hex, **kw}
    return call(r["app"], "POST", "/api/review/decision", body=body, headers=hdrs(mode))


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



def test_evaluation_texts_and_labels_stay_out(repo):
    ev = repo["ev"][0]
    app = repo["app"]
    assert call(app, "GET", "/api/corpus/posting", f"posting_id={ev}")[0] == 403
    assert call(app, "GET", "/api/review/posting", f"source={DRAFT}&posting_id={ev}&reviewer=alice")[0] == 403
    assert call(app, "GET", "/api/run/posting", f"run_id=skx-test&posting_id={ev}")[0] == 403
    assert call(app, "GET", "/api/locate", f"posting_id={ev}&evidence=Python")[0] == 403
    # development mode cannot write to an evaluation posting
    status, _ = call(app, "POST", "/api/review/decision", body={
        "reviewer_id": "alice", "mode": "development", "source": DRAFT, "posting_id": ev, "action": "add",
        "expected_version": 0, "client_request_id": uuid.uuid4().hex, "skill_statement": "x",
        "evidence_text": "Python", "required_or_preferred": "required"})
    assert status == 403
    # evaluation mode needs the explicit header, for reads and writes
    assert call(app, "GET", "/api/review/posting", f"mode=evaluation&posting_id={ev}&reviewer=alice")[0] == 403
    assert call(app, "GET", "/api/review", "mode=evaluation&reviewer=alice")[0] == 403
    assert call(app, "GET", "/api/locate", f"mode=evaluation&posting_id={ev}&evidence=Python")[0] == 403
    assert call(app, "POST", "/api/review/decision", body={"reviewer_id": "alice", "mode": "evaluation",
                                                           "posting_id": ev, "action": "add"})[0] == 403
    status, c = call(app, "GET", "/api/corpus")
    assert status == 200 and "clean_text" not in json.dumps(c)          # listings never carry texts
    assert {p["posting_id"] for p in c["postings"] if p["held_out"]} >= set(repo["ev"])
    status, o = call(app, "GET", "/api/review", f"source={DRAFT}&reviewer=alice")
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
    assert decide(repo, annotation_id="ai_draft-0001", action="edit", skill_statement="Python 3",
                  evidence_text="Python", required_or_preferred="required")[0] == 201
    assert decide(repo, annotation_id="ai_draft-0002", action="reject")[0] == 201
    assert decide(repo, action="add", skill_statement="x", evidence_text="SQL", required_or_preferred="required")[0] == 201
    assert {p: sha(p) for p in watched} == before
    written = sorted(p.name for p in repo["root"].rglob("*") if p.is_file() and "reviews" in p.parts)
    assert written == ["decisions.jsonl", "decisions.jsonl.lock"]


def test_requests_must_be_local_and_from_the_page(repo):
    app = repo["app"]
    assert call(app, "GET", "/api/runs", host="evil.example:8765")[0] == 403
    body = {"reviewer_id": "alice", "source": DRAFT, "posting_id": repo["p0"], "annotation_id": "ai_draft-0001",
            "action": "accept"}
    assert call(app, "POST", "/api/review/decision", body=body, headers={})[0] == 403   # no X-Dashboard header
    assert call(app, "GET", "/static/../dashboard.py")[0] == 404
    assert call(app, "GET", "/figures/../../db.sqlite")[0] == 404
    assert repo["app"].review.events("alice") == []


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
