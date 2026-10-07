"""Human review workflow behind the dashboard's Annotation review page (Team B, Sprint 2).

Two modes, kept apart:
  development  review the AI drafts (annotators/ai_revised or ai_draft) of the 20 development postings
  evaluation   label the 80 evaluation postings independently, from the original text, starting empty;
               no AI drafts, predictions or suggestions are ever read in this mode

Storage (append-only, one file per reviewer):
  <reviews_dir>/<reviewer_id>/decisions.jsonl
Every event names its mode, source, posting, the draft file hash and the clean_text hash it was made
against, the posting version it expected, and a client request id (so a repeated click is not written
twice). Nothing is ever rewritten; the current state is replayed from the log.

Exports go to a NEW folder per export, <reviewed_dir>/<reviewer_id>/<mode>-<timestamp>/, in the existing
annotation CSV format, validated with annotations.validate. They never touch annotators/ (ai_draft,
ai_revised or human folders) and are never called gold.
"""

from __future__ import annotations

import csv
import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import annotations as an

MODES = ("development", "evaluation")
DEV_SOURCES = ("ai_revised", "ai_draft")
EVAL_SOURCE = "none"
POSTING_ITEM = "__posting__"
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
ACTIONS = {
    "development": {"accept", "edit", "reject", "reopen", "add", "split", "resolve_discussion",
                    "complete_posting", "reopen_posting"},
    "evaluation": {"add", "edit", "delete", "reopen", "split", "resolve_discussion", "complete_posting",
                   "reopen_posting"},
}
COMPLETION_EVENTS = {"complete_posting", "reopen_posting"}
RECORD_FIELDS = ("skill_statement", "evidence_text", "evidence_start", "evidence_end", "required_or_preferred",
                 "alternative_group_id", "skill_category", "review_notes")
_lock = threading.Lock()


class ReviewError(Exception):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def guidelines_version(root: Path) -> dict:
    p = root / "docs" / "skill_annotation_guidelines.md"
    if not p.is_file():
        return {"version": None, "sha256": None}
    first = p.read_text(encoding="utf-8").splitlines()[0]
    m = re.search(r"\bv(\d+(?:\.\d+)+)", first)
    return {"version": m.group(1) if m else None, "sha256": sha256_bytes(p.read_bytes())}


def check_reviewer(rid) -> str:
    if not isinstance(rid, str) or not an.ANNOTATOR_RE.match(rid):
        raise ReviewError("reviewer_id must be lowercase letters/digits/_/- (max 32)")
    if rid in DEV_SOURCES or rid.startswith("ai_") or rid.startswith("ai-"):
        raise ReviewError("reviewer_id must identify a person, not an AI workspace")
    return rid


# ------------------------------------------------------------------------- texts and drafts


def place_evidence(text: str, evidence, occurrence=None, start=None) -> tuple[int, int]:
    """Offsets of an exact evidence string, computed here; a client offset alone is never trusted."""
    if not isinstance(evidence, str) or not evidence:
        raise ReviewError("evidence_text is required")
    if evidence != evidence.strip():
        raise ReviewError("evidence_text starts or ends with whitespace; trim the span")
    hits, i = [], text.find(evidence)
    while i >= 0:
        hits.append(i)
        i = text.find(evidence, i + 1)
    if not hits:
        raise ReviewError("evidence_text does not occur exactly in clean_text "
                          "(it must match case, punctuation and spacing)")
    if start is not None:
        if start not in hits:
            raise ReviewError("evidence_start does not point at an occurrence of evidence_text", occurrences=hits)
        return start, start + len(evidence)
    if occurrence is not None:
        if not 1 <= occurrence <= len(hits):
            raise ReviewError(f"occurrence must be between 1 and {len(hits)}", occurrences=hits)
        return hits[occurrence - 1], hits[occurrence - 1] + len(evidence)
    if len(hits) > 1:
        raise ReviewError(f"evidence_text occurs {len(hits)} times; choose an occurrence", occurrences=hits)
    return hits[0], hits[0] + len(evidence)


def occurrences(text: str, evidence: str) -> list[int]:
    hits, i = [], text.find(evidence) if evidence else -1
    while i >= 0:
        hits.append(i)
        i = text.find(evidence, i + 1)
    return hits


class Review:
    """Review state for one dashboard context (paths come from dashboard.Context)."""

    def __init__(self, ctx, reviewed_dir: Path | None = None):
        self.ctx = ctx
        self.reviewed_dir = reviewed_dir or ctx.set_dir / "reviewed"
        self.eval = {r["posting_id"]: r for r in ctx.manifest if r["split"] == "evaluation"}

    # --- texts (evaluation text only through this class, in evaluation mode)
    def postings(self, mode: str) -> dict:
        if mode == "development":
            return self.ctx.dev
        if mode == "evaluation":
            return self.eval
        raise ReviewError(f"mode must be one of {list(MODES)}")

    def text(self, mode: str, pid: str) -> str:
        rows = self.postings(mode)
        if pid not in rows:
            raise ReviewError(f"{pid} is not a {mode} posting", 403)
        if mode == "development":
            return self.ctx.dev_text(pid)
        conn = self.ctx.connect()
        try:
            row = conn.execute("SELECT clean_text FROM postings WHERE snapshot_id = ? AND posting_id = ?",
                               (self.ctx.snapshot, pid)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ReviewError(f"unknown posting {pid}", 404)
        t = row["clean_text"]
        if sha256_bytes(t.encode("utf-8")) != rows[pid]["clean_text_sha256"]:
            raise ReviewError(f"{pid}: clean_text no longer matches the frozen manifest", 409)
        return t

    def source(self, mode: str, source) -> str:
        if mode == "evaluation":
            return EVAL_SOURCE
        source = source or DEV_SOURCES[0]
        if source not in DEV_SOURCES:
            raise ReviewError(f"source must be one of {list(DEV_SOURCES)}")
        return source

    def draft_file(self, source: str) -> Path:
        p = self.ctx.set_dir / "annotators" / source / "skills.csv"
        if not p.is_file():
            raise ReviewError(f"draft workspace {source} not found", 404)
        return p

    def drafts(self, mode: str, source: str, pid: str) -> tuple[list[dict], str | None, str]:
        """(draft rows for the posting, draft file sha, posting-level note). Evaluation mode: none."""
        if mode == "evaluation":
            return [], None, ""
        f = self.draft_file(source)
        with f.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r["posting_id"] == pid]
        note = ""
        rf = f.with_name("postings_review.csv")
        if rf.is_file():
            with rf.open(encoding="utf-8", newline="") as fh:
                note = next((r["review_notes"] for r in csv.DictReader(fh) if r["posting_id"] == pid), "")
        return rows, sha256_bytes(f.read_bytes()), note

    # --- event log
    def log_path(self, reviewer: str) -> Path:
        return self.ctx.reviews_dir / reviewer / "decisions.jsonl"

    def events(self, reviewer: str) -> list[dict]:
        p = self.log_path(reviewer)
        if not p.is_file():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                e.setdefault("mode", "development")  # events written before modes existed
                out.append(e)
        return out

    @staticmethod
    def scope(events: list[dict], mode: str, source: str, pid: str) -> list[dict]:
        return [e for e in events if e["mode"] == mode and e["source"] == source and e["posting_id"] == pid]

    # --- state
    def posting_state(self, reviewer: str | None, mode: str, source, pid: str, events=None) -> dict:
        source = self.source(mode, source)
        text = self.text(mode, pid)
        meta = self.postings(mode)[pid]
        drafts, draft_sha, posting_note = self.drafts(mode, source, pid)
        evs = self.scope(events if events is not None else (self.events(reviewer) if reviewer else []), mode, source, pid)
        return replay(text, meta, drafts, draft_sha, posting_note, evs, mode, source)

    def overview(self, reviewer: str | None, mode: str, source) -> dict:
        source = self.source(mode, source)
        events = self.events(check_reviewer(reviewer)) if reviewer else []
        rows = []
        for pid, meta in sorted(self.postings(mode).items()):
            st = self.posting_state(reviewer, mode, source, pid, events)
            rows.append({"posting_id": pid, "title": meta["title"].strip(), "company_name": meta["company_name"],
                         "counts": st["counts"], "status": st["status"], "blocking": len(st["blocking"])})
        done = sum(r["status"] == "completed" for r in rows)
        return {"mode": mode, "source": source, "reviewer": reviewer, "postings": rows,
                "progress": {"completed": done, "total": len(rows),
                             "in_progress": sum(r["status"] in ("in_progress", "completion_invalidated") for r in rows)},
                "snapshot_id": self.ctx.snapshot, "guidelines": guidelines_version(self.ctx.root)}

    # --- writes
    def apply(self, body: dict) -> tuple[dict, bool]:
        """Validate and append one event. Returns (event, created). Raises ReviewError (409 on conflicts)."""
        reviewer = check_reviewer(body.get("reviewer_id"))
        mode = body.get("mode") or "development"
        if mode not in MODES:
            raise ReviewError(f"mode must be one of {list(MODES)}")
        source = self.source(mode, body.get("source"))
        pid, action = body.get("posting_id"), body.get("action")
        if pid not in self.postings(mode):  # scope first: a posting outside this mode is refused outright
            raise ReviewError(f"{pid} is not a {mode} posting", 403)
        if action not in ACTIONS[mode]:
            raise ReviewError(f"action must be one of {sorted(ACTIONS[mode])} in {mode} mode")
        rid = body.get("client_request_id")
        if not isinstance(rid, str) or not REQUEST_ID_RE.match(rid):
            raise ReviewError("client_request_id is required (8-64 letters/digits/_/-)")
        expected = body.get("expected_version")
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ReviewError("expected_version (integer) is required")
        text = self.text(mode, pid)
        with _lock, _file_lock(self.log_path(reviewer)):
            events = self.events(reviewer)
            dup = next((e for e in events if e.get("client_request_id") == rid), None)
            if dup is not None:  # a repeated click or retry: never written twice
                if dup["posting_id"] != pid or dup["action"] != action:
                    raise ReviewError("client_request_id was already used for a different decision", 409)
                return dup, False
            st = self.posting_state(reviewer, mode, source, pid, events)
            if expected != st["version"]:
                raise ReviewError("this posting changed since you loaded it (another tab or a retry); "
                                  "reload to see the latest decisions", 409, current_version=st["version"])
            if mode == "development" and body.get("expected_source_sha") != st["draft_sha"]:
                raise ReviewError("the AI draft file changed since you loaded it; reload before deciding", 409,
                                  current_source_sha=st["draft_sha"])
            event = self._build(reviewer, mode, source, pid, action, body, text, st, events)
            p = self.log_path(reviewer)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        return event, True

    def _build(self, reviewer, mode, source, pid, action, body, text, st, events) -> dict:
        items = {i["annotation_id"]: i for i in st["items"]}
        aid = body.get("annotation_id")
        record, parts, reason, completion, original = None, None, None, None, None
        need_item = action not in ("add", "complete_posting", "reopen_posting") and \
            not (action == "resolve_discussion" and aid == POSTING_ITEM)
        it = items.get(aid) if need_item else None
        if need_item and it is None:
            raise ReviewError(f"{aid!r} is not a record of this posting", 404)
        if it is not None and it.get("stale") and action not in ("reopen", "reject", "delete", "accept", "edit"):
            raise ReviewError("this record is stale (its draft changed); accept, edit, reject or reopen it first", 409)
        if action == "accept":
            if it["origin"] != "draft":
                raise ReviewError("accept applies to AI draft records; added records are already yours")
            if it["state"] == "accepted" and not it.get("stale"):
                raise ReviewError("already accepted", 409)
            if it["state"] == "split":
                raise ReviewError("this record was split; decide on its parts", 409)
            d = it["draft"]
            if d is None:
                raise ReviewError("the draft record no longer exists; reject it", 409)
            s, e = int(d["evidence_start"]), int(d["evidence_end"])
            if text[s:e] != d["evidence_text"]:
                raise ReviewError("the draft's evidence does not match clean_text; edit it instead", 409)
            record = _draft_record(d)
            original = d
        elif action == "edit":
            if it["state"] in ("split", "rejected"):
                raise ReviewError(f"cannot edit a {it['state']} record; reopen it first", 409)
            record = self._record(reviewer, mode, source, pid, text, body, events, exclude=aid)
            original = it["draft"]
        elif action in ("reject", "delete"):
            if it["state"] in ("rejected", "split"):
                raise ReviewError(f"already {it['state']}", 409)
            original = it["draft"]
        elif action == "reopen":
            if it["state"] in ("pending", "added"):
                raise ReviewError("nothing to reopen", 409)
            if it["state"] == "split":
                raise ReviewError("a split record cannot be reopened; reject or edit its parts", 409)
            original = it["draft"]
        elif action == "add":
            aid = f"{reviewer}-add-{uuid.uuid4().hex[:10]}"
            record = self._record(reviewer, mode, source, pid, text, body, events)
        elif action == "split":
            if it["state"] in ("rejected", "split"):
                raise ReviewError(f"cannot split a {it['state']} record", 409)
            raw = body.get("parts")
            if not isinstance(raw, list) or len(raw) < 2:
                raise ReviewError("a split needs at least two parts")
            parts = []
            for k, part in enumerate(raw):
                if not isinstance(part, dict):
                    raise ReviewError(f"part {k + 1} is not an object")
                try:
                    rec = self._record(reviewer, mode, source, pid, text, part, events, exclude=aid)
                except ReviewError as e:
                    raise ReviewError(f"part {k + 1}: {e}", e.status, **e.extra) from None
                parts.append({"annotation_id": f"{reviewer}-split-{uuid.uuid4().hex[:10]}", "record": rec})
            if len({p["record"]["skill_statement"].casefold() for p in parts}) < len(parts):
                raise ReviewError("split parts must be different skills")
            original = it["draft"]
        elif action == "resolve_discussion":
            reason = (body.get("reason") or "").strip()
            if not reason:
                raise ReviewError("a reason is required to resolve a discussion item")
            target = st["posting_discussion"] if aid == POSTING_ITEM else (it or {}).get("discussion")
            if not target or not target["required"]:
                raise ReviewError("this item has no discussion flag to resolve")
            if target["resolved"]:
                raise ReviewError("already resolved", 409)
        elif action == "complete_posting":
            if st["status"] == "completed":
                raise ReviewError("already marked reviewed", 409)
            if st["blocking"]:
                raise ReviewError("the posting cannot be completed yet", 409, blocking=st["blocking"])
            if body.get("confirm_read_full_text") is not True or body.get("confirm_checked_missing_skills") is not True:
                raise ReviewError("confirm that you read the full description and checked for missing skills")
            zero = st["counts"]["active"] == 0
            if zero and body.get("confirm_zero_skills") is not True:
                raise ReviewError("no skills are recorded: confirm this is a deliberate zero-skill posting")
            completion = {"zero_skills": zero, "active_records": st["counts"]["active"],
                          "guidelines": guidelines_version(self.ctx.root), "draft_sha256": st["draft_sha"],
                          "confirm_read_full_text": True, "confirm_checked_missing_skills": True,
                          "confirm_zero_skills": bool(zero)}
            aid = POSTING_ITEM
        elif action == "reopen_posting":
            if st["status"] != "completed":
                raise ReviewError("the posting is not marked reviewed", 409)
            aid = POSTING_ITEM
        return {"decision_id": uuid.uuid4().hex, "seq": len(events) + 1, "timestamp": now_iso(),
                "reviewer_id": reviewer, "actor": "human", "mode": mode, "source": source,
                "source_skills_sha256": st["draft_sha"], "posting_id": pid,
                "clean_text_sha256": self.postings(mode)[pid]["clean_text_sha256"],
                "annotation_id": aid, "origin": (it or {}).get("origin", "reviewer") if aid != POSTING_ITEM else None,
                "action": action, "record": record, "parts": parts, "reason": reason, "completion": completion,
                "original": original, "comment": (body.get("comment") or "").strip(),
                "client_request_id": body["client_request_id"], "base_version": st["version"]}

    def _record(self, reviewer, mode, source, pid, text, body, events, exclude=None) -> dict:
        stmt = (body.get("skill_statement") or "").strip()
        if not stmt:
            raise ReviewError("skill_statement is required")
        req = body.get("required_or_preferred")
        if req not in an.REQUIREMENT_VALUES:
            raise ReviewError(f"required_or_preferred must be one of {sorted(an.REQUIREMENT_VALUES)}")
        cat = body.get("skill_category") or ""
        if cat not in an.SKILL_CATEGORIES:
            raise ReviewError(f"skill_category must be empty or one of {sorted(an.SKILL_CATEGORIES - {''})}")
        alt = (body.get("alternative_group_id") or "").strip()
        if alt:
            if not an.ALT_GROUP_RE.match(alt):
                raise ReviewError("alternative_group_id must be letters/digits/_/./- (max 40)")
            other = self._alt_owner(reviewer, mode, source, alt, events, pid)
            if other:
                raise ReviewError(f"alternative group {alt!r} is already used in {other}; group ids must be unique "
                                  f"across the export (e.g. prefix them per posting)")
        occ, st = body.get("occurrence"), body.get("evidence_start")
        if (occ is not None and (not isinstance(occ, int) or isinstance(occ, bool))) or \
                (st is not None and (not isinstance(st, int) or isinstance(st, bool))):
            raise ReviewError("occurrence and evidence_start must be integers")
        s, e = place_evidence(text, body.get("evidence_text"), occ, st)
        return {"skill_statement": stmt, "evidence_text": text[s:e], "evidence_start": s, "evidence_end": e,
                "required_or_preferred": req, "alternative_group_id": alt, "skill_category": cat,
                "review_notes": (body.get("review_notes") or "").strip()}

    def _alt_owner(self, reviewer, mode, source, alt, events, pid) -> str | None:
        for other in {e["posting_id"] for e in events if e["mode"] == mode and e["source"] == source} - {pid}:
            st = self.posting_state(reviewer, mode, source, other, events)
            if any(i["current"].get("alternative_group_id") == alt for i in st["items"] if i["active"]):
                return other
        return None

    # --- export
    def build_export(self, reviewer: str, mode: str, source) -> dict:
        reviewer = check_reviewer(reviewer)
        source = self.source(mode, source)
        events = self.events(reviewer)
        targets = self.postings(mode)
        skills, reviews, prov, n = [], [], [], 0
        status_count = {"completed": 0, "in_progress": 0, "not_started": 0}
        for m in sorted(self.ctx.manifest, key=lambda r: (r["split"], r["posting_id"])):
            pid = m["posting_id"]
            row = {"snapshot_id": m["snapshot_id"], "posting_id": pid, "split": m["split"],
                   "review_status": "not_started", "annotator_id": "", "reviewed_at": "", "review_notes": ""}
            if pid in targets and self.scope(events, mode, source, pid):
                st = self.posting_state(reviewer, mode, source, pid, events)
                if st["status"] == "completed":
                    c = st["completion"]
                    row.update(review_status="reviewed", annotator_id=reviewer, reviewed_at=c["timestamp"],
                               review_notes=(f"HUMAN-REVIEWED by {reviewer} at {c['timestamp']} ({mode} mode"
                                             + (f", AI-assisted drafts from {source}" if mode == "development" else
                                                ", independent; no AI suggestions shown")
                                             + f"; guidelines v{c['completion']['guidelines']['version']})"
                                             + ("; deliberate zero-skill posting" if c["completion"]["zero_skills"] else "")
                                             + "; not gold until adjudicated"))
                    status_count["completed"] += 1
                else:
                    row.update(review_status="in_progress",
                               review_notes=f"PARTIAL: review by {reviewer} in progress ({mode} mode); not gold")
                    status_count["in_progress"] += 1
                for it in st["items"]:
                    if not it["active"]:
                        continue
                    n += 1
                    new_id = f"{reviewer}-{n:04d}"
                    c = it["current"]
                    how = _provenance_text(it, reviewer, source, mode)
                    notes = " | ".join(x for x in [how, c.get("review_notes", "")] if x)
                    skills.append({"snapshot_id": m["snapshot_id"], "posting_id": pid, "annotation_id": new_id,
                                   "skill_statement": c["skill_statement"], "evidence_text": c["evidence_text"],
                                   "evidence_start": c["evidence_start"], "evidence_end": c["evidence_end"],
                                   "required_or_preferred": c["required_or_preferred"],
                                   "alternative_group_id": c.get("alternative_group_id", ""),
                                   "skill_category": c.get("skill_category", ""), "annotator_id": reviewer,
                                   "review_notes": notes})
                    prov.append({"annotation_id": new_id, "posting_id": pid, "mode": mode, "source": source,
                                 "origin": it["origin"], "ai_annotation_id": it["annotation_id"] if it["origin"] == "draft" else None,
                                 "split_from": it.get("split_from"), "state": it["state"],
                                 "decision_ids": [e["decision_id"] for e in it["history"]],
                                 "ai_draft_record": it["draft"], "discussion": it["discussion"],
                                 "posting_completed": st["status"] == "completed"})
            elif pid in targets:
                status_count["not_started"] += 1
            reviews.append(row)
        problems = self._validate(skills, reviews)
        complete = status_count["completed"] == len(targets) and not problems
        return {"reviewer": reviewer, "mode": mode, "source": source, "status": "complete" if complete else "partial",
                "gold": False, "postings": status_count, "total_postings": len(targets), "skill_rows": skills,
                "review_rows": reviews, "provenance": prov, "problems": problems,
                "note": "Human-reviewed export; not gold until adjudicated." if complete else
                        "PARTIAL export: some postings are not marked reviewed. Not gold.",
                "decision_log_sha256": sha256_bytes(self.log_path(reviewer).read_bytes())
                if self.log_path(reviewer).is_file() else None,
                "guidelines": guidelines_version(self.ctx.root)}

    def _validate(self, skills, reviews) -> list[str]:
        texts = {}
        for pid in {r["posting_id"] for r in skills}:
            mode = "development" if pid in self.ctx.dev else "evaluation"
            texts[pid] = self.text(mode, pid)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            an._write_csv(d / "skills.csv", an.SKILL_FIELDS, skills)
            an._write_csv(d / "postings_review.csv", an.REVIEW_FIELDS, reviews)
            res = an.validate(d, self.ctx.manifest, texts)
        return [str(p) for p in res["problems"]]

    def write_export(self, reviewer: str, mode: str, source) -> dict:
        exp = self.build_export(reviewer, mode, source)
        if exp["problems"]:
            raise ReviewError("the export does not validate; fix the listed problems first", 409,
                              problems=exp["problems"])
        if not exp["skill_rows"] and not exp["postings"]["completed"]:
            raise ReviewError("nothing to export yet")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        out = self.reviewed_dir / exp["reviewer"] / f"{mode}-{stamp}"
        annot = (self.ctx.set_dir / "annotators").resolve()
        if out.resolve().is_relative_to(annot):
            raise ReviewError("exports may not be written under annotators/", 403)
        out.mkdir(parents=True, exist_ok=False)  # a new folder every time: earlier exports are never overwritten
        an._write_csv(out / "skills.csv", an.SKILL_FIELDS, exp["skill_rows"])
        an._write_csv(out / "postings_review.csv", an.REVIEW_FIELDS, exp["review_rows"])
        (out / "provenance.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n"
                                                      for p in exp["provenance"]), encoding="utf-8")
        meta = {k: exp[k] for k in ("reviewer", "mode", "source", "status", "gold", "postings", "total_postings",
                                     "note", "decision_log_sha256", "guidelines")}
        meta.update(exported_at=now_iso(), skill_rows=len(exp["skill_rows"]), path=str(out))
        (out / "export.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return meta


# ------------------------------------------------------------------------- replay


def _draft_record(d: dict) -> dict:
    return {"skill_statement": d["skill_statement"], "evidence_text": d["evidence_text"],
            "evidence_start": int(d["evidence_start"]), "evidence_end": int(d["evidence_end"]),
            "required_or_preferred": d["required_or_preferred"], "alternative_group_id": d["alternative_group_id"],
            "skill_category": d["skill_category"], "review_notes": d["review_notes"]}


def _flags(notes: str) -> list[str]:
    f = []
    if "DISCUSS" in notes:
        f.append("discuss")
    if "illustrative list" in notes:
        f.append("illustrative")
    if notes.startswith("AI-SUGGESTED"):
        f.append("suggested_addition")
    return f


def _provenance_text(it: dict, reviewer: str, source: str, mode: str) -> str:
    last = it["history"][-1] if it["history"] else {}
    who = f"by {reviewer} at {last.get('timestamp', '?')}"
    if it["origin"] == "draft":
        kind = "AI-SUGGESTED ADDITION" if "suggested_addition" in it["flags"] else "AI-assisted draft"
        verb = "accepted" if it["state"] == "accepted" else "edited"
        s = f"HUMAN-REVIEWED: {kind} {it['annotation_id']} ({source}) {verb} {who}"
    elif it.get("split_from"):
        s = f"HUMAN-REVIEWED: split from {it['split_from']} {who}"
    else:
        s = f"HUMAN-ANNOTATED: added {who}" + (" (independent evaluation mode)" if mode == "evaluation" else "")
    d = it["discussion"]
    if d["required"] and d["resolved"]:
        s += f" | discussion resolved: {d['reason']}"
    return s


def replay(text: str, meta: dict, drafts: list[dict], draft_sha, posting_note: str, evs: list[dict],
           mode: str, source: str) -> dict:
    items: dict[str, dict] = {}
    order: list[str] = []
    for d in drafts:
        aid = d["annotation_id"]
        notes = d.get("review_notes", "")
        items[aid] = {"annotation_id": aid, "origin": "draft", "draft": d, "current": _draft_record(d),
                      "state": "pending", "flags": _flags(notes), "history": [], "split_from": None,
                      "split_into": [], "stale": False, "edited": False,
                      "discussion": {"required": "DISCUSS" in notes, "resolved": False, "reason": None}}
        order.append(aid)
    posting_disc = {"required": mode == "development" and "DISCUSS" in posting_note, "resolved": False,
                    "reason": None, "note": posting_note}
    completion, invalidated = None, False
    for e in evs:
        a, aid = e["action"], e["annotation_id"]
        if a in COMPLETION_EVENTS:
            if a == "complete_posting":
                completion, invalidated = {"timestamp": e["timestamp"], "decision_id": e["decision_id"],
                                           "completion": e["completion"]}, False
            else:
                completion, invalidated = None, True
            continue
        if completion is not None:  # any change after completion invalidates it
            completion, invalidated = None, True
        if a == "resolve_discussion" and aid == POSTING_ITEM:
            posting_disc.update(resolved=True, reason=e["reason"])
            continue
        if a == "add":
            items[aid] = {"annotation_id": aid, "origin": "reviewer", "draft": None, "current": e["record"],
                          "state": "added", "flags": _flags(e["record"]["review_notes"]), "history": [e],
                          "split_from": None, "split_into": [], "stale": False, "edited": False,
                          "discussion": {"required": "DISCUSS" in e["record"]["review_notes"], "resolved": False,
                                         "reason": None}}
            order.append(aid)
            continue
        it = items.get(aid)
        if it is None:  # a decision on a draft record that no longer exists in the draft file
            it = items[aid] = {"annotation_id": aid, "origin": e.get("origin") or "draft", "draft": None,
                               "current": e.get("record") or (e.get("original") and _draft_record(e["original"])) or {},
                               "state": "pending", "flags": [], "history": [], "split_from": None, "split_into": [],
                               "stale": True, "edited": False,
                               "discussion": {"required": False, "resolved": False, "reason": None}}
            order.append(aid)
        it["history"].append(e)
        if it["origin"] == "draft" and it["draft"] is not None and e.get("original") is not None \
                and e["original"] != it["draft"]:
            it["stale"] = True  # decided against an older version of this draft row
        if it["origin"] == "draft" and a in ("accept", "edit") and e.get("original") == it["draft"]:
            it["stale"] = False  # re-decided against the current draft row
        if a == "accept":
            it.update(state="accepted", current=e["record"])
        elif a == "edit":
            it["current"] = e["record"]
            it["edited"] = True
            it["state"] = "edited" if it["origin"] == "draft" else "added"
            if "DISCUSS" in e["record"]["review_notes"]:
                it["discussion"].update(required=True, resolved=False, reason=None)
        elif a in ("reject", "delete"):
            it["state"] = "rejected"
        elif a == "reopen":
            if it["origin"] == "draft":
                it.update(state="pending", current=_draft_record(it["draft"]) if it["draft"] else it["current"],
                          edited=False)
            else:
                it["state"] = "added"
        elif a == "split":
            it["state"] = "split"
            for p in e["parts"]:
                pid_ = p["annotation_id"]
                it["split_into"].append(pid_)
                items[pid_] = {"annotation_id": pid_, "origin": "reviewer", "draft": None, "current": p["record"],
                               "state": "added", "flags": _flags(p["record"]["review_notes"]), "history": [e],
                               "split_from": aid, "split_into": [], "stale": False, "edited": False,
                               "discussion": {"required": "DISCUSS" in p["record"]["review_notes"], "resolved": False,
                                              "reason": None}}
                order.append(pid_)
        elif a == "resolve_discussion":
            it["discussion"].update(resolved=True, reason=e["reason"])
    out = [items[a] for a in order]
    for it in out:
        it["active"] = it["state"] in ("accepted", "edited", "added")
        c = it["current"]
        try:
            s, e_ = int(c["evidence_start"]), int(c["evidence_end"])
            it["offset_valid"] = text[s:e_] == c["evidence_text"]
        except (KeyError, TypeError, ValueError):
            it["offset_valid"] = False
        d = it["discussion"]
        it["discussion_open"] = d["required"] and not d["resolved"] and it["state"] not in ("rejected", "split")
    blocking = []
    for it in out:
        if it["state"] == "pending":
            blocking.append({"annotation_id": it["annotation_id"], "reason": "no decision yet"})
        if it["discussion_open"]:
            blocking.append({"annotation_id": it["annotation_id"], "reason": "unresolved discussion"})
        if it["stale"] and it["state"] != "rejected":
            blocking.append({"annotation_id": it["annotation_id"], "reason": "stale: the draft changed since it was decided"})
        if it["active"] and not it["offset_valid"]:
            blocking.append({"annotation_id": it["annotation_id"], "reason": "evidence offsets do not match clean_text"})
    if posting_disc["required"] and not posting_disc["resolved"]:
        blocking.append({"annotation_id": POSTING_ITEM, "reason": "unresolved posting-level discussion"})
    groups: dict[str, list[dict]] = {}
    for it in out:
        g = it["current"].get("alternative_group_id") if it["active"] else ""
        if g:
            groups.setdefault(g, []).append(it)
    for g, members in groups.items():
        if len(members) < 2:
            blocking.append({"annotation_id": members[0]["annotation_id"],
                             "reason": f"alternative group {g!r} has only one active record"})
        elif len({m["current"]["required_or_preferred"] for m in members}) > 1:
            blocking.append({"annotation_id": members[0]["annotation_id"],
                             "reason": f"alternative group {g!r} mixes requirement values"})
    counts = {
        "pending": sum(i["state"] == "pending" for i in out),
        "accepted": sum(i["state"] == "accepted" for i in out),
        "edited": sum(i["state"] == "edited" or (i["origin"] == "reviewer" and i["edited"] and i["active"]) for i in out),
        "rejected": sum(i["state"] == "rejected" for i in out),
        "added": sum(i["state"] == "added" for i in out),
        "split": sum(i["state"] == "split" for i in out),
        "discussion_open": sum(i["discussion_open"] for i in out) + int(posting_disc["required"] and not posting_disc["resolved"]),
        "discussion_total": sum(i["discussion"]["required"] for i in out) + int(posting_disc["required"]),
        "active": sum(i["active"] for i in out), "total": len(out),
    }
    status = "completed" if completion else "completion_invalidated" if invalidated else \
        "in_progress" if evs else "not_started"
    return {"posting_id": meta["posting_id"], "title": meta["title"].strip(), "company_name": meta["company_name"],
            "mode": mode, "source": source, "items": out, "counts": counts, "blocking": blocking, "status": status,
            "completion": completion, "version": len(evs), "draft_sha": draft_sha, "posting_discussion": posting_disc,
            "clean_text_sha256": meta["clean_text_sha256"], "text_length": len(text)}


class _file_lock:
    """Advisory exclusive lock on the reviewer's log while appending (also guards other processes)."""

    def __init__(self, path: Path):
        self.path = path.with_name(path.name + ".lock")

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("a")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()
