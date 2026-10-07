"""Local Team B dashboard: corpus explorer, extraction results, annotation review.

    python src/dashboard.py [--port 8765] [--reviews-dir PATH]   # then open http://127.0.0.1:8765/

Standard library only (WSGI). It binds to 127.0.0.1, reads local files only, makes no API calls
and reads no credentials (.env is never opened).

Read-only sources: the SQLite DB (opened with mode=ro), reports/, data/processed/derived/,
data/extraction/runs/, and the AI draft workspaces (annotators/ai_revised, annotators/ai_draft).
The only writes are reviewer decisions, appended to
data/annotation/sprint2_v1/reviews/<reviewer_id>/decisions.jsonl.

Held-out data stays out: the evaluation postings and every posting grouped with one in the
frozen manifest (near-identical variants) have their text withheld, and review and extraction
views accept development postings only. Human annotator folders are not loaded.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import annotations as an
import derive_features as df
from select_annotation_set import REPO_ROOT, read_manifest, set_dir

STATIC = Path(__file__).resolve().parent / "dashboard_static"
REVIEW_SOURCES = ("ai_revised", "ai_draft")  # development AI drafts only; human folders are excluded
ACTIONS = {"accept", "reject", "edit", "add", "reopen"}
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

    def __init__(self, root: Path, db: Path | None = None, reviews_dir: Path | None = None):
        self.root = root
        self.set_dir = set_dir(root)
        self.db = db or root / "data" / "processed" / "taxonomy_pilot.sqlite"
        self.reviews_dir = reviews_dir or self.set_dir / "reviews"
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


def place_evidence(text: str, evidence: str, occurrence: int | None = None, start: int | None = None) -> tuple[int, int]:
    """Offsets of an exact evidence string, computed here. Never trusts a client offset alone."""
    if not isinstance(evidence, str) or not evidence:
        raise DashboardError("evidence_text is required")
    if evidence != evidence.strip():
        raise DashboardError("evidence_text starts or ends with whitespace; trim the span")
    hits, i = [], text.find(evidence)
    while i >= 0:
        hits.append(i)
        i = text.find(evidence, i + 1)
    if not hits:
        raise DashboardError("evidence_text does not occur exactly in clean_text "
                             "(it must match case, punctuation and spacing)")
    if start is not None:
        if start not in hits:
            raise DashboardError("evidence_start does not point at an occurrence of evidence_text", occurrences=hits)
        return start, start + len(evidence)
    if occurrence is not None:
        if not 1 <= occurrence <= len(hits):
            raise DashboardError(f"occurrence must be between 1 and {len(hits)}", occurrences=hits)
        return hits[occurrence - 1], hits[occurrence - 1] + len(evidence)
    if len(hits) > 1:
        raise DashboardError(f"evidence_text occurs {len(hits)} times; choose an occurrence", occurrences=hits)
    return hits[0], hits[0] + len(evidence)


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


# ------------------------------------------------------------------------- annotation review


def _source_path(ctx: Context, source: str) -> Path:
    if source not in REVIEW_SOURCES:
        raise DashboardError(f"source must be one of {list(REVIEW_SOURCES)}")
    p = ctx.set_dir / "annotators" / source / "skills.csv"
    if not p.is_file():
        raise DashboardError(f"draft workspace {source} not found", 404)
    return p


def _reviewer(rid: str) -> str:
    if not isinstance(rid, str) or not an.ANNOTATOR_RE.match(rid):
        raise DashboardError("reviewer_id must be lowercase letters/digits/_/- (max 32)")
    if rid in REVIEW_SOURCES or rid.startswith("ai_"):
        raise DashboardError("reviewer_id must identify a person, not an AI workspace")
    return rid


def decisions_path(ctx: Context, reviewer: str) -> Path:
    return ctx.reviews_dir / reviewer / "decisions.jsonl"


def load_decisions(ctx: Context, reviewer: str) -> list[dict]:
    return _read_jsonl(decisions_path(ctx, reviewer))


def _flags(row: dict) -> list[str]:
    notes = row.get("review_notes", "")
    f = []
    if "DISCUSS" in notes:
        f.append("discuss")
    if "illustrative list" in notes:
        f.append("illustrative")
    if notes.startswith("AI-SUGGESTED"):
        f.append("suggested_addition")
    if row.get("alternative_group_id"):
        f.append("alternative")
    return f


def review_overview(ctx: Context, source: str, reviewer: str | None) -> dict:
    rows = list(csv.DictReader(open(_source_path(ctx, source), encoding="utf-8", newline="")))
    dec = load_decisions(ctx, _reviewer(reviewer)) if reviewer else []
    out = []
    for pid, mr in sorted(ctx.dev.items()):
        mine = [r for r in rows if r["posting_id"] == pid]
        state = _effective(mine, [d for d in dec if d["source"] == source and d["posting_id"] == pid])
        out.append({"posting_id": pid, "title": mr["title"].strip(), "company_name": mr["company_name"],
                    "n_draft": len(mine), "n_discuss": sum("discuss" in _flags(r) for r in mine),
                    "n_pending": sum(s["state"] == "pending" for s in state),
                    "n_decided": sum(s["state"] != "pending" for s in state)})
    return {"source": source, "label": f"{AI_LABEL} drafts", "reviewer": reviewer, "postings": out,
            "snapshot_id": ctx.snapshot}


def _effective(draft_rows: list[dict], decisions: list[dict]) -> list[dict]:
    """Latest decision per record; drafts themselves are never modified."""
    latest: dict[str, dict] = {}
    last_record: dict[str, dict] = {}
    for d in decisions:  # file order = time order
        latest[d["annotation_id"]] = d
        if d.get("record"):
            last_record[d["annotation_id"]] = d["record"]
    items = []
    draft_ids = set()
    for r in draft_rows:
        aid = r["annotation_id"]
        draft_ids.add(aid)
        d = latest.get(aid)
        state = "pending" if d is None or d["action"] == "reopen" else \
            {"accept": "accepted", "reject": "rejected", "edit": "edited"}[d["action"]]
        items.append({"annotation_id": aid, "origin": "draft", "draft": r, "flags": _flags(r), "state": state,
                      "decision": d if state != "pending" else None,
                      "current": d["record"] if state == "edited" else r})
    for aid, d in latest.items():  # records the reviewer added
        if aid in draft_ids:
            continue
        items.append({"annotation_id": aid, "origin": "reviewer", "draft": None, "flags": [],
                      "state": "rejected" if d["action"] == "reject" else "added", "decision": d,
                      "current": last_record[aid]})
    return items


def review_posting(ctx: Context, source: str, pid: str, reviewer: str | None) -> dict:
    text = ctx.dev_text(pid)
    rows = [r for r in csv.DictReader(open(_source_path(ctx, source), encoding="utf-8", newline=""))
            if r["posting_id"] == pid]
    dec = [d for d in (load_decisions(ctx, _reviewer(reviewer)) if reviewer else [])
           if d["source"] == source and d["posting_id"] == pid]
    items = _effective(rows, dec)
    spans = []
    for it in items:
        c = it["current"]
        try:
            spans.append({"id": it["annotation_id"], "start": int(c["evidence_start"]), "end": int(c["evidence_end"]),
                          "evidence": c["evidence_text"]})
        except (KeyError, TypeError, ValueError):
            spans.append({"id": it["annotation_id"], "start": None, "end": None, "evidence": None})
    segs, invalid = segment_text(text, spans)
    bad = {i["id"] for i in invalid}
    for it in items:
        it["offset_valid"] = it["annotation_id"] not in bad
    review_row = next((r for r in csv.DictReader(open(_source_path(ctx, source).with_name("postings_review.csv"),
                                                      encoding="utf-8", newline="")) if r["posting_id"] == pid), {})
    return {"source": source, "label": f"{AI_LABEL} drafts", "posting_id": pid, "title": ctx.dev[pid]["title"].strip(),
            "posting_notes": review_row.get("review_notes", ""), "segments": segs, "items": items,
            "invalid_offsets": invalid, "clean_text_sha256": ctx.dev[pid]["clean_text_sha256"]}


def _record(ctx: Context, text: str, pid: str, aid: str, body: dict) -> dict:
    stmt = (body.get("skill_statement") or "").strip()
    if not stmt:
        raise DashboardError("skill_statement is required")
    req = body.get("required_or_preferred")
    if req not in an.REQUIREMENT_VALUES:
        raise DashboardError(f"required_or_preferred must be one of {sorted(an.REQUIREMENT_VALUES)}")
    cat = body.get("skill_category") or ""
    if cat not in an.SKILL_CATEGORIES:
        raise DashboardError(f"skill_category must be empty or one of {sorted(an.SKILL_CATEGORIES - {''})}")
    alt = (body.get("alternative_group_id") or "").strip()
    if alt and not an.ALT_GROUP_RE.match(alt):
        raise DashboardError("alternative_group_id must be letters/digits/_/./- (max 40)")
    occ, st = body.get("occurrence"), body.get("evidence_start")
    if occ is not None and not isinstance(occ, int) or st is not None and not isinstance(st, int):
        raise DashboardError("occurrence and evidence_start must be integers")
    s, e = place_evidence(text, body.get("evidence_text"), occ, st)
    return {"snapshot_id": ctx.snapshot, "posting_id": pid, "annotation_id": aid, "skill_statement": stmt,
            "evidence_text": text[s:e], "evidence_start": s, "evidence_end": e, "required_or_preferred": req,
            "alternative_group_id": alt, "skill_category": cat, "review_notes": (body.get("review_notes") or "").strip()}


def save_decision(ctx: Context, body: dict) -> dict:
    reviewer = _reviewer(body.get("reviewer_id"))
    source, pid, action = body.get("source"), body.get("posting_id"), body.get("action")
    src = _source_path(ctx, source)
    if action not in ACTIONS:
        raise DashboardError(f"action must be one of {sorted(ACTIONS)}")
    text = ctx.dev_text(pid)
    drafts = {r["annotation_id"]: r for r in csv.DictReader(open(src, encoding="utf-8", newline=""))
              if r["posting_id"] == pid}
    prior = [d for d in load_decisions(ctx, reviewer) if d["source"] == source and d["posting_id"] == pid]
    added = {d["annotation_id"] for d in prior if d["action"] == "add"}
    if action == "add":
        aid = f"{reviewer}-add-{uuid.uuid4().hex[:10]}"
        origin = "reviewer"
    else:
        aid = body.get("annotation_id")
        if aid not in drafts and aid not in added:
            raise DashboardError(f"{aid!r} is not a record of {source} for {pid}", 404)
        origin = "draft" if aid in drafts else "reviewer"
    record = None
    if action in ("edit", "add"):
        record = _record(ctx, text, pid, aid, body)
    elif action == "accept":
        r = drafts.get(aid)
        if r is None:
            raise DashboardError("accept applies to draft records; edit an added record instead")
        s, e = int(r["evidence_start"]), int(r["evidence_end"])
        if text[s:e] != r["evidence_text"]:
            raise DashboardError("the draft's evidence does not match clean_text; edit it before accepting", 409)
        record = {k: r[k] for k in ("snapshot_id", "posting_id", "annotation_id", "skill_statement", "evidence_text",
                                    "evidence_start", "evidence_end", "required_or_preferred",
                                    "alternative_group_id", "skill_category", "review_notes")}
        record["evidence_start"], record["evidence_end"] = s, e
    elif action == "reject":
        record = drafts.get(aid) or next(d["record"] for d in reversed(prior) if d["annotation_id"] == aid)
    decision = {"decision_id": uuid.uuid4().hex, "timestamp": now_iso(), "reviewer_id": reviewer,
                "source": source, "source_skills_sha256": sha256_bytes(src.read_bytes()),
                "posting_id": pid, "clean_text_sha256": ctx.dev[pid]["clean_text_sha256"],
                "annotation_id": aid, "origin": origin, "action": action, "record": record,
                "original": drafts.get(aid), "comment": (body.get("comment") or "").strip()}
    p = decisions_path(ctx, reviewer)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:  # append-only log; earlier decisions are never rewritten
        f.write(json.dumps(decision, ensure_ascii=False) + "\n")
    return {"saved": decision}


def locate(ctx: Context, pid: str, evidence: str) -> dict:
    text = ctx.dev_text(pid)
    hits, i = [], text.find(evidence) if evidence else -1
    while i >= 0:
        hits.append(i)
        i = text.find(evidence, i + 1)
    return {"posting_id": pid, "evidence_text": evidence, "occurrences": hits,
            "contexts": [text[max(0, h - 40):h + len(evidence) + 40] for h in hits[:10]]}


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
                    "/api/run": lambda: run_detail(self.ctx, g("run_id")),
                    "/api/run/posting": lambda: run_posting(self.ctx, g("run_id"), g("posting_id")),
                    "/api/review": lambda: review_overview(self.ctx, g("source") or REVIEW_SOURCES[0], g("reviewer")),
                    "/api/review/posting": lambda: review_posting(self.ctx, g("source") or REVIEW_SOURCES[0],
                                                                  g("posting_id"), g("reviewer")),
                    "/api/locate": lambda: locate(self.ctx, g("posting_id"), g("evidence") or ""),
                }
                if path in routes:
                    return self._json(start, routes[path]())
                raise DashboardError("not found", 404)
            if method == "POST" and path == "/api/review/decision":
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
                return self._json(start, save_decision(self.ctx, body), "201 Created")
            raise DashboardError("method not allowed", 405)
        except DashboardError as e:
            status = {400: "400 Bad Request", 403: "403 Forbidden", 404: "404 Not Found", 405: "405 Method Not Allowed",
                      409: "409 Conflict", 413: "413 Payload Too Large"}[e.status]
            return self._json(start, {"error": str(e), **e.extra}, status)
        except an.AnnotationError as e:
            return self._json(start, {"error": str(e)}, "409 Conflict")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Team B local dashboard (localhost only).")
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--reviews-dir", type=Path, default=None, help="default: data/annotation/sprint2_v1/reviews")
    a = ap.parse_args(argv)
    ctx = Context(a.root.resolve(), a.db, a.reviews_dir)
    with make_server("127.0.0.1", a.port, App(ctx, a.port)) as srv:
        print(f"Team B dashboard on http://127.0.0.1:{a.port}/ (Ctrl+C to stop)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
