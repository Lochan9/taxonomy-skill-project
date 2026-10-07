"""Local Team B dashboard: corpus explorer, extraction results, annotation review.

    python src/dashboard.py [--port 8765] [--reviews-dir PATH] [--reviewed-dir PATH]
    # then open http://127.0.0.1:8765/

Standard library only (WSGI). It binds to 127.0.0.1, reads local files only, makes no API calls
and reads no credentials (.env is never opened).

Read-only sources: the SQLite DB (opened with mode=ro), reports/, data/processed/derived/,
data/extraction/runs/, and the AI draft workspaces (annotators/ai_revised, annotators/ai_draft).
Writes (see review_workflow.py):
  - reviewer decisions, appended to data/annotation/sprint2_v1/reviews/<reviewer_id>/decisions.jsonl
  - exports, each in a new folder data/annotation/sprint2_v1/reviewed/<reviewer_id>/<mode>-<timestamp>/

Held-out data: the evaluation postings' text is served only in explicit evaluation annotation mode
(header X-Dashboard-Mode: evaluation), where no AI drafts or predictions are read. Corpus, extraction and
development review never show it, nor the text of non-selected variants grouped with an evaluation
posting. Human annotator folders are not loaded.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import annotations as an
import derive_features as df
import review_workflow as rw
from select_annotation_set import REPO_ROOT, read_manifest, set_dir

STATIC = Path(__file__).resolve().parent / "dashboard_static"
REVIEW_SOURCES = rw.DEV_SOURCES  # development AI drafts only; human folders are never loaded
AI_LABEL = "AI-generated, unreviewed"
MAX_BODY = 1_000_000


class DashboardError(Exception):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------------- context


class Context:
    """Paths and the frozen selection. Texts are fetched read-only on demand."""

    def __init__(self, root: Path, db: Path | None = None, reviews_dir: Path | None = None,
                 reviewed_dir: Path | None = None):
        self.root = root
        self.set_dir = set_dir(root)
        self.db = db or root / "data" / "processed" / "taxonomy_pilot.sqlite"
        self.reviews_dir = reviews_dir or self.set_dir / "reviews"
        self.reviewed_dir = reviewed_dir or self.set_dir / "reviewed"
        self.runs_dir = root / "data" / "extraction" / "runs"
        self.manifest = read_manifest(self.set_dir / "selection_manifest.csv")
        self.snapshot = self.manifest[0]["snapshot_id"]
        self.dev = {r["posting_id"]: r for r in self.manifest if r["split"] == "development"}
        held = {r["posting_id"] for r in self.manifest if r["split"] == "evaluation"}
        for r in self.manifest:
            if r["split"] == "evaluation":
                held |= {m for m in r["group_members"].split(";") if m}
        self.held_out = held - set(self.dev)

    def connect(self):
        return df.connect_readonly(self.db)

    def text(self, posting_id: str) -> str:
        if posting_id in self.held_out:
            raise DashboardError("held out: evaluation postings and their variants are not shown", 403)
        conn = self.connect()
        try:
            row = conn.execute("SELECT clean_text FROM postings WHERE snapshot_id = ? AND posting_id = ?",
                               (self.snapshot, posting_id)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise DashboardError(f"unknown posting {posting_id}", 404)
        return row["clean_text"]

    def dev_text(self, posting_id: str) -> str:
        if posting_id not in self.dev:
            raise DashboardError("only development postings are available in this view", 403)
        text = self.text(posting_id)
        if sha256_bytes(text.encode("utf-8")) != self.dev[posting_id]["clean_text_sha256"]:
            raise DashboardError(f"{posting_id}: clean_text no longer matches the frozen manifest", 409)
        return text


# ------------------------------------------------------------------------- evidence


def segment_text(text: str, spans: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split text into segments, each listing the span ids that cover it.

    Spans are {"id", "start", "end", "evidence"}; a span is drawn only if 0 <= start < end <= len(text)
    and text[start:end] == evidence. Others are returned as invalid (never moved or "repaired").
    Concatenating the segment texts always reproduces `text` exactly.
    """
    valid, invalid = [], []
    for s in spans:
        st, en = s.get("start"), s.get("end")
        ok = isinstance(st, int) and isinstance(en, int) and 0 <= st < en <= len(text) \
            and text[st:en] == s.get("evidence")
        (valid if ok else invalid).append(s)
    cuts = sorted({0, len(text)} | {s["start"] for s in valid} | {s["end"] for s in valid})
    segs = []
    for a, b in zip(cuts, cuts[1:]):
        ids = [s["id"] for s in valid if s["start"] <= a and b <= s["end"]]
        segs.append({"text": text[a:b], "ids": ids})
    return segs, [{"id": s["id"], "reason": "offsets do not match clean_text"} for s in invalid]


place_evidence = rw.place_evidence  # evidence offsets are computed in one place (review_workflow)


# ------------------------------------------------------------------------- corpus explorer


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def corpus(ctx: Context, q: dict) -> dict:
    seniority = {r["posting_id"]: r["seniority_label"] for r in
                 _read_csv(ctx.root / "data" / "processed" / "derived" / f"seniority_{ctx.snapshot}.csv")}
    split = {r["posting_id"]: r["split"] for r in ctx.manifest}
    conn = ctx.connect()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT posting_id, company_name, title, location, word_count, exclusion_reason, is_duplicate_of, "
            "is_placeholder FROM postings WHERE snapshot_id = ? ORDER BY company_name, title", (ctx.snapshot,))]
    finally:
        conn.close()
    for r in rows:
        r["seniority"] = seniority.get(r["posting_id"], "")
        r["selection_split"] = split.get(r["posting_id"], "")
        r["held_out"] = r["posting_id"] in ctx.held_out
        r["excluded"] = bool(r["exclusion_reason"])
    facets = {"employers": sorted({r["company_name"] for r in rows}),
              "seniority": sorted({r["seniority"] for r in rows if r["seniority"]}),
              "exclusions": sorted({r["exclusion_reason"] for r in rows if r["exclusion_reason"]})}
    emp, sen, exc = (q.get(k, [""])[0] for k in ("employer", "seniority", "exclusion"))
    text_q = q.get("q", [""])[0].casefold()
    out = [r for r in rows if (not emp or r["company_name"] == emp) and (not sen or r["seniority"] == sen)
           and (not exc or (exc == "usable" and not r["excluded"]) or (exc == "excluded" and r["excluded"])
                or r["exclusion_reason"] == exc)
           and (not text_q or text_q in (r["title"] or "").casefold())]
    metrics_path = ctx.root / "reports" / "sprint1_exploration_metrics.json"
    figures = sorted(p.name for p in (ctx.root / "reports" / "figures").glob("*.png"))
    return {"snapshot_id": ctx.snapshot, "total": len(rows), "shown": len(out), "postings": out, "facets": facets,
            "metrics": json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.is_file() else None,
            "figures": figures, "held_out_count": len(ctx.held_out)}


def corpus_posting(ctx: Context, pid: str) -> dict:
    return {"posting_id": pid, "clean_text": ctx.text(pid)}


# ------------------------------------------------------------------------- extraction results


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_dir(ctx: Context, run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id or ""):
        raise DashboardError("invalid run id")
    d = ctx.runs_dir / run_id
    if not (d / "run.json").is_file():
        raise DashboardError(f"no run {run_id}", 404)
    return d


def list_runs(ctx: Context) -> dict:
    runs = []
    if ctx.runs_dir.is_dir():
        for d in sorted(ctx.runs_dir.iterdir(), reverse=True):
            if (d / "run.json").is_file():
                m = json.loads((d / "run.json").read_text(encoding="utf-8"))
                runs.append({k: m.get(k) for k in ("run_id", "model", "status", "started_at", "finished_at",
                                                   "counts", "n_statements", "llm_tokens_in", "llm_tokens_out")})
    return {"runs": runs, "label": AI_LABEL, "snapshot_id": ctx.snapshot}


def run_detail(ctx: Context, run_id: str) -> dict:
    d = _run_dir(ctx, run_id)
    m = json.loads((d / "run.json").read_text(encoding="utf-8"))
    results = {r["posting_id"]: r for r in _read_jsonl(d / "postings.jsonl")}
    stmts = _read_jsonl(d / "statements.jsonl")
    rejected = _read_jsonl(d / "rejected.jsonl")
    postings = []
    for pid, mr in sorted(ctx.dev.items()):
        r = results.get(pid)
        postings.append({"posting_id": pid, "title": mr["title"].strip(), "company_name": mr["company_name"],
                         "status": r["status"] if r else None, "error": r.get("error") if r else None,
                         "n_statements": sum(s["posting_id"] == pid for s in stmts),
                         "n_rejected": sum(x["posting_id"] == pid for x in rejected),
                         "cache_hit": r.get("cache_hit") if r else None, "usage": r.get("usage") if r else None})
    cfg = m.get("config", {})
    return {"label": AI_LABEL, "run_id": m["run_id"], "model": m.get("model"), "provider": m.get("provider"),
            "provider_access": cfg.get("provider_access"), "brief_p7_compliance": cfg.get("brief_p7_compliance"),
            "prompt_version": m.get("prompt_version"), "schema_version": m.get("schema_version"),
            "status": m.get("status"), "started_at": m.get("started_at"), "finished_at": m.get("finished_at"),
            "counts": m.get("counts"), "token_usage_billed": m.get("token_usage_billed"),
            "llm_tokens_in": m.get("llm_tokens_in"), "llm_tokens_out": m.get("llm_tokens_out"),
            "api_calls": m.get("api_calls"), "cache_hits": m.get("cache_hits"), "postings": postings,
            "non_development_results_hidden": sum(pid not in ctx.dev for pid in results)}


def run_posting(ctx: Context, run_id: str, pid: str) -> dict:
    d = _run_dir(ctx, run_id)
    text = ctx.dev_text(pid)
    result = next((r for r in _read_jsonl(d / "postings.jsonl") if r["posting_id"] == pid), None)
    stmts = [s for s in _read_jsonl(d / "statements.jsonl") if s["posting_id"] == pid]
    rejected = [x for x in _read_jsonl(d / "rejected.jsonl") if x["posting_id"] == pid]
    spans = [{"id": s["statement_id"], "start": s.get("evidence_start"), "end": s.get("evidence_end"),
              "evidence": s.get("source_span")} for s in stmts]
    segs, invalid = segment_text(text, spans)
    bad = {i["id"] for i in invalid}
    for s in stmts:
        s["offset_valid"] = s["statement_id"] not in bad
        s["kind_of_mention"] = {"direct": "individual requirement", "illustrative_example": "illustrative example",
                                "category": "category of examples"}.get(s.get("mention_relation"), "unknown")
    return {"label": AI_LABEL, "run_id": run_id, "posting_id": pid, "title": ctx.dev[pid]["title"].strip(),
            "result": result, "empty": result is None, "segments": segs, "statements": stmts,
            "invalid_offsets": invalid, "rejected": rejected}


# ------------------------------------------------------------------------- annotation review (see review_workflow)


EVAL_HEADER = "HTTP_X_DASHBOARD_MODE"  # evaluation text is served only with X-Dashboard-Mode: evaluation


def _mode(environ, q) -> str:
    mode = (q.get("mode", ["development"])[0]) or "development"
    if mode not in rw.MODES:
        raise DashboardError(f"mode must be one of {list(rw.MODES)}")
    if mode == "evaluation" and environ.get(EVAL_HEADER) != "evaluation":
        raise DashboardError("evaluation postings are only available in explicit evaluation annotation mode", 403)
    return mode


def review_view(review: rw.Review, mode: str, source, pid: str, reviewer: str | None) -> dict:
    """One posting: text segments, items with state, counts, blocking reasons and version for writes."""
    if reviewer:
        rw.check_reviewer(reviewer)
    st = review.posting_state(reviewer, mode, source, pid)
    text = review.text(mode, pid)
    spans = [{"id": i["annotation_id"], "start": i["current"].get("evidence_start"),
              "end": i["current"].get("evidence_end"), "evidence": i["current"].get("evidence_text")}
             for i in st["items"] if i["state"] not in ("rejected", "split")]
    segs, invalid = segment_text(text, spans)
    st.update(segments=segs, invalid_offsets=invalid,
              label=f"{AI_LABEL} drafts" if mode == "development" else
              "Independent evaluation annotation: no AI drafts, predictions or suggestions are shown",
              guidelines=rw.guidelines_version(review.ctx.root))
    for it in st["items"]:
        it["history"] = [{k: e.get(k) for k in ("timestamp", "reviewer_id", "action", "reason", "comment")}
                         for e in it["history"]]
    return st


def locate(review: rw.Review, mode: str, pid: str, evidence: str) -> dict:
    text = review.text(mode, pid)
    hits = rw.occurrences(text, evidence)
    return {"posting_id": pid, "evidence_text": evidence, "occurrences": hits,
            "contexts": [text[max(0, h - 40):h + len(evidence) + 40] for h in hits[:10]]}


def export_summary(exp: dict, limit: int = 400) -> dict:
    return {k: exp[k] for k in ("reviewer", "mode", "source", "status", "gold", "postings", "total_postings",
                                "problems", "note", "guidelines")} | {
        "skill_row_count": len(exp["skill_rows"]), "skill_rows": exp["skill_rows"][:limit],
        "reviewed_postings": [r["posting_id"] for r in exp["review_rows"] if r["review_status"] == "reviewed"]}


def export_csv(exp: dict, name: str) -> bytes:
    import io
    fields, rows = {"skills.csv": (an.SKILL_FIELDS, exp["skill_rows"]),
                    "postings_review.csv": (an.REVIEW_FIELDS, exp["review_rows"])}.get(name, (None, None))
    if fields is None:
        raise DashboardError("file must be skills.csv or postings_review.csv")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


# ------------------------------------------------------------------------- WSGI app


# A tuple, copied into every response: wsgiref appends to the header list it is given, so a shared
# list would leak headers (e.g. a second Content-Length) into every later response.
SECURITY_HEADERS = (
    ("Content-Security-Policy", "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
                                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
    ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"), ("Cache-Control", "no-store"),
)


class App:
    def __init__(self, ctx: Context, port: int = 8765):
        self.ctx, self.port = ctx, port
        self.review = rw.Review(ctx, ctx.reviewed_dir)

    def _json(self, start, obj, status="200 OK"):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        start(status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))]
              + list(SECURITY_HEADERS))
        return [body]

    def _file(self, start, path: Path):
        body = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start("200 OK", [("Content-Type", ctype), ("Content-Length", str(len(body)))] + list(SECURITY_HEADERS))
        return [body]

    def __call__(self, environ, start):
        try:
            host = environ.get("HTTP_HOST", "")
            if host.split(":")[0] not in ("127.0.0.1", "localhost"):
                raise DashboardError("only localhost requests are served", 403)
            method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "/")
            q = parse_qs(environ.get("QUERY_STRING", ""))
            g = lambda k: q.get(k, [None])[0]
            if method == "GET":
                if path == "/favicon.ico":  # no icon; answer quietly instead of a 404
                    start("204 No Content", list(SECURITY_HEADERS))
                    return [b""]
                if path in ("/", "/index.html"):
                    return self._file(start, STATIC / "index.html")
                if path.startswith("/static/"):
                    name = path[len("/static/"):]
                    if name not in {p.name for p in STATIC.iterdir()}:
                        raise DashboardError("not found", 404)
                    return self._file(start, STATIC / name)
                if path.startswith("/figures/"):
                    name = path[len("/figures/"):]
                    figs = {p.name: p for p in (self.ctx.root / "reports" / "figures").glob("*.png")}
                    if name not in figs:
                        raise DashboardError("not found", 404)
                    return self._file(start, figs[name])
                routes = {
                    "/api/corpus": lambda: corpus(self.ctx, q),
                    "/api/corpus/posting": lambda: corpus_posting(self.ctx, g("posting_id")),
                    "/api/runs": lambda: list_runs(self.ctx),
                    # where decisions and exports go (local paths; lets test tools refuse a real-data server)
                    "/api/review/storage": lambda: {"reviews_dir": str(self.ctx.reviews_dir.resolve()),
                                                    "reviewed_dir": str(self.ctx.reviewed_dir.resolve())},
                    "/api/run": lambda: run_detail(self.ctx, g("run_id")),
                    "/api/run/posting": lambda: run_posting(self.ctx, g("run_id"), g("posting_id")),
                    "/api/review": lambda: self.review.overview(g("reviewer"), _mode(environ, q), g("source")),
                    "/api/review/posting": lambda: review_view(self.review, _mode(environ, q), g("source"),
                                                               g("posting_id"), g("reviewer")),
                    "/api/locate": lambda: locate(self.review, _mode(environ, q), g("posting_id"), g("evidence") or ""),
                    "/api/export/preview": lambda: export_summary(
                        self.review.build_export(g("reviewer"), _mode(environ, q), g("source"))),
                }
                if path in routes:
                    return self._json(start, routes[path]())
                if path == "/api/export/download":
                    exp = self.review.build_export(g("reviewer"), _mode(environ, q), g("source"))
                    name = g("file") or ""
                    body = export_csv(exp, name)
                    fname = f"{exp['reviewer']}-{exp['mode']}-{exp['status']}-{name}"
                    start("200 OK", [("Content-Type", "text/csv; charset=utf-8"), ("Content-Length", str(len(body))),
                                     ("Content-Disposition", f'attachment; filename="{fname}"')] + list(SECURITY_HEADERS))
                    return [body]
                raise DashboardError("not found", 404)
            if method == "POST" and path in ("/api/review/decision", "/api/export"):
                # same-origin JSON only: a custom header forces a CORS preflight, which is never answered
                if environ.get("HTTP_X_DASHBOARD") != "1" or \
                        not environ.get("CONTENT_TYPE", "").startswith("application/json"):
                    raise DashboardError("requests must come from the dashboard page", 403)
                n = int(environ.get("CONTENT_LENGTH") or 0)
                if n > MAX_BODY:
                    raise DashboardError("request too large", 413)
                try:
                    body = json.loads(environ["wsgi.input"].read(n) or b"{}")
                except json.JSONDecodeError:
                    raise DashboardError("invalid JSON") from None
                if not isinstance(body, dict):
                    raise DashboardError("invalid JSON object")
                mode = body.get("mode") or "development"
                if mode == "evaluation" and environ.get(EVAL_HEADER) != "evaluation":
                    raise DashboardError("evaluation postings are only available in explicit evaluation annotation mode", 403)
                if path == "/api/export":
                    return self._json(start, {"written": self.review.write_export(body.get("reviewer_id"), mode,
                                                                                  body.get("source"))}, "201 Created")
                event, created = self.review.apply(body)
                view = review_view(self.review, mode, body.get("source"), body["posting_id"], body["reviewer_id"])
                return self._json(start, {"saved": event, "created": created, "state": view},
                                  "201 Created" if created else "200 OK")
            raise DashboardError("method not allowed", 405)
        except (DashboardError, rw.ReviewError) as e:
            status = {400: "400 Bad Request", 403: "403 Forbidden", 404: "404 Not Found", 405: "405 Method Not Allowed",
                      409: "409 Conflict", 413: "413 Payload Too Large", 503: "503 Service Unavailable"}[e.status]
            return self._json(start, {"error": str(e), **e.extra}, status)
        except an.AnnotationError as e:
            return self._json(start, {"error": str(e)}, "409 Conflict")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Team B local dashboard (localhost only).")
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--reviews-dir", type=Path, default=None, help="default: data/annotation/sprint2_v1/reviews")
    ap.add_argument("--reviewed-dir", type=Path, default=None,
                    help="export target, default: data/annotation/sprint2_v1/reviewed (never annotators/)")
    a = ap.parse_args(argv)
    ctx = Context(a.root.resolve(), a.db, a.reviews_dir, a.reviewed_dir)
    with make_server("127.0.0.1", a.port, App(ctx, a.port)) as srv:
        print(f"Team B dashboard on http://127.0.0.1:{a.port}/ (Ctrl+C to stop)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
