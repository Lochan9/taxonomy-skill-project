"""Skill-statement extraction with an LLM (Team B, Sprint 2). Development postings only.

    python src/extract_skills.py --dry-run [--limit 3]           # no network, no key, writes nothing
    python src/extract_skills.py --model MODEL_ID [--limit 3]     # real calls (needs ANTHROPIC_API_KEY in .env)
    python src/extract_skills.py --model MODEL_ID --resume RUN_ID # continue an interrupted run

Only postings in the frozen selection's `development` split are processed (ALLOWED_SPLITS);
the evaluation postings are refused. clean_text is read from the DB read-only and checked
against the manifest SHA-256.

Model output is never trusted for positions. Every evidence string must occur exactly in the
unchanged clean_text; offsets are computed here. Repeated evidence is resolved through the
model's `evidence_context` (the containing sentence) or rejected as ambiguous.

Per posting the result is one of:
    ok            valid output with at least one accepted statement
    zero_skills   valid output that states no skills (an empty list, with a reason)
    all_rejected  valid output, but every skill record failed evidence/structure checks
    failed        no usable output: API error after bounded retries, refusal, truncation,
                  invalid JSON or a schema violation

Outputs (git-ignored) under data/extraction/:
    cache/{key}.json          latest response per cache key (posting text hash, model, prompt and
                              schema versions + file hashes, request settings); reused only if valid
    responses/{key}/*.json    every API response received, never overwritten
    runs/{run_id}/            run.json (provenance, token usage, failures), postings.jsonl,
                              statements.jsonl, rejected.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml

import annotations as an
from select_annotation_set import REPO_ROOT, read_manifest

ALLOWED_SPLITS = frozenset({"development"})  # initial runs only; evaluation postings stay held out
KIND = "skill"
STATUSES_DONE = {"ok", "zero_skills"}  # not re-run on --resume


class ExtractionError(Exception):
    """Bad configuration or inputs; nothing was extracted."""


# ------------------------------------------------------------------------- config


@dataclass
class Config:
    provider: str
    model: str | None
    prompt_version: str
    prompt_path: Path
    schema_version: str
    schema_path: Path
    max_tokens: int
    effort: str | None
    cache_system_prompt: bool
    timeout_seconds: float
    max_attempts: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    min_seconds_between_requests: float
    set_dir: Path
    db: Path
    out_dir: Path
    raw: dict = field(default_factory=dict)


def load_config(path: Path, root: Path) -> Config:
    c = yaml.safe_load(path.read_text(encoding="utf-8"))
    r = lambda p: (root / p) if not Path(p).is_absolute() else Path(p)
    return Config(
        provider=c["provider"], model=c.get("model"),
        prompt_version=c["prompt"]["version"], prompt_path=r(c["prompt"]["path"]),
        schema_version=c["schema"]["version"], schema_path=r(c["schema"]["path"]),
        max_tokens=int(c["request"]["max_tokens"]), effort=c["request"].get("effort"),
        cache_system_prompt=bool(c["request"].get("cache_system_prompt", True)),
        timeout_seconds=float(c["client"]["timeout_seconds"]), max_attempts=int(c["client"]["max_attempts"]),
        backoff_base_seconds=float(c["client"]["backoff_base_seconds"]),
        backoff_max_seconds=float(c["client"]["backoff_max_seconds"]),
        min_seconds_between_requests=float(c["client"]["min_seconds_between_requests"]),
        set_dir=r(c["input"]["set_dir"]), db=r(c["input"]["db"]), out_dir=r(c["output"]["dir"]), raw=c)


def read_env(root: Path) -> dict[str, str]:
    """Values from .env (if present), overridden by the process environment. Never printed."""
    from dotenv import dotenv_values

    vals = {k: v for k, v in dotenv_values(root / ".env").items() if v} if (root / ".env").is_file() else {}
    for k in ("ANTHROPIC_API_KEY", "EXTRACTION_MODEL", "LLM_PROVIDER"):
        if os.environ.get(k):
            vals[k] = os.environ[k]
    return vals


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------- inputs


def load_postings(cfg: Config, posting_ids: list[str] | None = None, limit: int | None = None) -> list[dict]:
    manifest = read_manifest(cfg.set_dir / "selection_manifest.csv")
    allowed = sorted((r for r in manifest if r["split"] in ALLOWED_SPLITS), key=lambda r: r["posting_id"])
    if posting_ids:
        by_id = {r["posting_id"]: r for r in manifest}
        for pid in posting_ids:
            if pid not in by_id:
                raise ExtractionError(f"{pid} is not in the frozen selection")
            if by_id[pid]["split"] not in ALLOWED_SPLITS:
                raise ExtractionError(f"{pid} is in the {by_id[pid]['split']!r} split; only "
                                      f"{sorted(ALLOWED_SPLITS)} postings may be extracted")
        allowed = [r for r in allowed if r["posting_id"] in set(posting_ids)]
    if limit is not None:
        if limit < 1:
            raise ExtractionError("--limit must be at least 1")
        allowed = allowed[:limit]
    texts = an.load_texts(cfg.db, allowed) if allowed else {}
    return [{"snapshot_id": r["snapshot_id"], "posting_id": r["posting_id"], "split": r["split"],
             "title": r["title"], "company_name": r["company_name"], "clean_text": texts[r["posting_id"]],
             "clean_text_sha256": r["clean_text_sha256"]} for r in allowed]


# ------------------------------------------------------------------------- request + cache key


def user_content(p: dict) -> str:
    return (f"<posting_metadata>\nposting_id: {p['posting_id']}\ntitle: {p['title']}\n"
            f"company: {p['company_name']}\n</posting_metadata>\n\n<posting_text>\n{p['clean_text']}\n</posting_text>")


def build_params(cfg: Config, model: str, prompt: str, schema: dict, posting: dict) -> dict:
    system: dict[str, Any] = {"type": "text", "text": prompt}
    if cfg.cache_system_prompt:
        system["cache_control"] = {"type": "ephemeral"}
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
    if cfg.effort:
        output_config["effort"] = cfg.effort
    return {"model": model, "max_tokens": cfg.max_tokens, "system": [system],
            "messages": [{"role": "user", "content": user_content(posting)}], "output_config": output_config}


def key_fields(cfg: Config, model: str, prompt: str, schema: dict, posting: dict) -> dict:
    return {"provider": cfg.provider, "model": model, "prompt_version": cfg.prompt_version,
            "prompt_sha256": sha256_text(prompt), "schema_version": cfg.schema_version,
            "schema_sha256": sha256_text(json.dumps(schema, sort_keys=True)),
            "clean_text_sha256": posting["clean_text_sha256"], "user_content_sha256": sha256_text(user_content(posting)),
            "max_tokens": cfg.max_tokens, "effort": cfg.effort}


def cache_key(fields: dict) -> str:
    return sha256_text(json.dumps(fields, sort_keys=True))


# ------------------------------------------------------------------------- backend (provider interface)


@dataclass
class LLMResponse:
    raw: dict            # full provider response, as returned
    text: str | None     # concatenated text blocks
    stop_reason: str | None
    usage: dict
    request_id: str | None


class LLMError(Exception):
    def __init__(self, kind: str, message: str, retryable: bool, status_code: int | None = None,
                 retry_after: float | None = None, request_id: str | None = None):
        super().__init__(message)
        self.kind, self.retryable, self.status_code = kind, retryable, status_code
        self.retry_after, self.request_id = retry_after, request_id


class Backend(Protocol):
    name: str

    def complete(self, params: dict) -> LLMResponse: ...


class AnthropicBackend:
    """Messages API through the official SDK. SDK retries are off; call_with_retries owns them."""

    name = "anthropic"

    def __init__(self, api_key: str, timeout: float, client: Any = None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)
        self.client = client

    def complete(self, params: dict) -> LLMResponse:
        import anthropic

        try:
            msg = self.client.messages.create(**params)
        except anthropic.RateLimitError as e:
            raise LLMError("rate_limit", str(e), True, 429, _retry_after(e), _rid(e)) from None
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise LLMError("auth", str(e), False, e.status_code, None, _rid(e)) from None
        except anthropic.NotFoundError as e:
            raise LLMError("not_found", str(e), False, 404, None, _rid(e)) from None
        except anthropic.APIStatusError as e:  # 408/409/5xx/529 retryable, other 4xx not
            retry = e.status_code in (408, 409) or e.status_code >= 500
            raise LLMError("server" if e.status_code >= 500 else "client", str(e), retry, e.status_code,
                           _retry_after(e), _rid(e)) from None
        except anthropic.APITimeoutError as e:
            raise LLMError("timeout", str(e), True) from None
        except anthropic.APIConnectionError as e:
            raise LLMError("connection", str(e), True) from None
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text") or None
        return LLMResponse(raw=msg.to_dict(), text=text, stop_reason=msg.stop_reason,
                           usage=msg.usage.to_dict() if msg.usage else {}, request_id=getattr(msg, "_request_id", None))


def _retry_after(e: Any) -> float | None:
    try:
        v = e.response.headers.get("retry-after")
        return float(v) if v is not None else None
    except (AttributeError, ValueError):
        return None


def _rid(e: Any) -> str | None:
    try:
        return e.response.headers.get("request-id")
    except AttributeError:
        return None


def make_backend(cfg: Config, env: dict[str, str]) -> Backend:
    if cfg.provider != "anthropic":
        raise ExtractionError(f"provider {cfg.provider!r} is not implemented (only 'anthropic')")
    key = env.get("ANTHROPIC_API_KEY")
    if not key:
        raise ExtractionError("ANTHROPIC_API_KEY is not set in .env or the environment")
    return AnthropicBackend(api_key=key, timeout=cfg.timeout_seconds)


# ------------------------------------------------------------------------- retries + pacing


class Pacer:
    def __init__(self, min_interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.min_interval, self.clock, self.sleep, self.last = min_interval, clock, sleep, None

    def wait(self) -> None:
        if self.last is not None:
            gap = self.min_interval - (self.clock() - self.last)
            if gap > 0:
                self.sleep(gap)
        self.last = self.clock()


def call_with_retries(backend: Backend, params: dict, cfg: Config, pacer: Pacer,
                      sleep: Callable[[float], None] = time.sleep) -> tuple[LLMResponse | None, list[dict], LLMError | None]:
    attempts: list[dict] = []
    for attempt in range(1, cfg.max_attempts + 1):
        pacer.wait()
        started = now_iso()
        try:
            resp = backend.complete(params)
            attempts.append({"attempt": attempt, "started_at": started, "outcome": "response",
                             "stop_reason": resp.stop_reason, "request_id": resp.request_id})
            return resp, attempts, None
        except LLMError as e:
            attempts.append({"attempt": attempt, "started_at": started, "outcome": "error", "error_kind": e.kind,
                             "status_code": e.status_code, "retry_after": e.retry_after, "request_id": e.request_id,
                             "message": str(e)[:500]})
            if not e.retryable or attempt == cfg.max_attempts:
                return None, attempts, e
            delay = e.retry_after if e.retry_after is not None else \
                min(cfg.backoff_base_seconds * 2 ** (attempt - 1) + random.uniform(0, cfg.backoff_base_seconds),
                    cfg.backoff_max_seconds)
            attempts[-1]["sleep_seconds"] = round(delay, 3)
            sleep(delay)
    raise AssertionError("unreachable")


# ------------------------------------------------------------------------- output validation


def check_schema(value: Any, schema: dict, path: str = "$") -> list[str]:
    """Validate against the subset of JSON Schema used by the output schema."""
    if "anyOf" in schema:
        if any(not check_schema(value, s, path) for s in schema["anyOf"]):
            return []
        return [f"{path}: does not match any allowed form"]
    t = schema.get("type")
    ok = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str),
          "null": value is None, "boolean": isinstance(value, bool),
          "integer": isinstance(value, int) and not isinstance(value, bool)}.get(t, True)
    if not ok:
        return [f"{path}: expected {t}, got {type(value).__name__}"]
    errs: list[str] = []
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in {schema['enum']}")
    if t == "object":
        props = schema.get("properties", {})
        errs += [f"{path}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            errs += [f"{path}: unexpected {k!r}" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                errs += check_schema(v, props[k], f"{path}.{k}")
    if t == "array" and "items" in schema:
        for i, v in enumerate(value):
            errs += check_schema(v, schema["items"], f"{path}[{i}]")
    return errs


def parse_output(resp: LLMResponse, schema: dict) -> tuple[dict | None, str | None]:
    """(data, None) for a well-formed result, else (None, reason). Never raises."""
    if resp.stop_reason == "refusal":
        return None, "refusal: the model declined; output may not match the schema"
    if resp.stop_reason == "max_tokens":
        return None, "truncated: stop_reason max_tokens; raise request.max_tokens"
    if resp.stop_reason not in ("end_turn", "stop_sequence"):
        return None, f"unexpected stop_reason {resp.stop_reason!r}"
    if not resp.text:
        return None, "no text content in the response"
    try:
        data = json.loads(resp.text)
    except json.JSONDecodeError as e:
        return None, f"invalid_json: {e.msg} at char {e.pos}"
    errs = check_schema(data, schema)
    if errs:
        return None, "schema: " + "; ".join(errs[:5]) + (f" (+{len(errs) - 5} more)" if len(errs) > 5 else "")
    if not data["skills"] and not (data["no_skills_reason"] or "").strip():
        return None, "schema: empty skills list without no_skills_reason"
    return data, None


def find_all(text: str, s: str) -> list[int]:
    out, i = [], text.find(s)
    while i >= 0:
        out.append(i)
        i = text.find(s, i + 1)
    return out


def resolve_evidence(text: str, evidence: str, context: str) -> tuple[int, int, str]:
    """(start, end, resolution) of evidence in text, or raise ValueError(reason)."""
    ev = evidence.strip()
    if not ev:
        raise ValueError("empty evidence_text")
    hits = find_all(text, ev)
    if not hits:
        raise ValueError("unsupported: evidence_text does not occur in clean_text")
    if len(hits) == 1:
        res = "unique"
        start = hits[0]
    else:
        ctx = context.strip()
        ctx_hits = find_all(text, ctx) if ctx else []
        inner = find_all(ctx, ev) if ctx else []
        if len(ctx_hits) == 1 and len(inner) == 1:
            start = ctx_hits[0] + inner[0]
            res = f"context ({len(hits)} occurrences)"
        else:
            why = ("context not found" if not ctx_hits else
                   "context occurs more than once" if len(ctx_hits) > 1 else
                   "evidence not inside context" if not inner else "evidence repeated inside context")
            raise ValueError(f"ambiguous: evidence_text occurs {len(hits)} times and {why}")
    if ev != evidence:
        res += ", trimmed whitespace"
    return start, start + len(ev), res


def process_output(data: dict, posting: dict, run_id: str, method: str, versions: dict) -> tuple[list[dict], list[dict]]:
    """Accepted statements and rejected records for one posting."""
    text, pid = posting["clean_text"], posting["posting_id"]
    accepted, rejected, seen = [], [], set()
    for i, s in enumerate(data["skills"]):
        reason = None
        stmt = s["skill_statement"].strip()
        if not stmt:
            reason = "empty skill_statement"
        else:
            try:
                start, end, res = resolve_evidence(text, s["evidence_text"], s["evidence_context"])
            except ValueError as e:
                reason = str(e)
        if reason is None and stmt.casefold() in seen:
            reason = "duplicate skill_statement in this posting"
        if reason:
            rejected.append({"run_id": run_id, "posting_id": pid, "model_index": i, "reason": reason, "record": s})
            continue
        seen.add(stmt.casefold())
        accepted.append({
            "posting_id": pid, "snapshot_id": posting["snapshot_id"], "kind": KIND, "text": stmt,
            "source_span": text[start:end], "evidence_start": start, "evidence_end": end,
            "evidence_resolution": res, "section": s["section_heading"], "requirement_status": s["requirement_status"],
            "mention_relation": s["mention_relation"], "example_of": s["example_of"],
            "alternative_group": (s["alternative_group"] or "").strip() or None, "skill_category": s["skill_category"],
            "model_notes": s["notes"], "model_index": i, "extraction_method": method, "run_id": run_id, **versions})
    check_alternatives(accepted)
    for n, st in enumerate(accepted):
        st["statement_id"] = f"{run_id}:{pid}:{KIND}:{n}"
    return accepted, rejected


def check_alternatives(stmts: list[dict]) -> None:
    """Drop invalid alternative groups (with a warning on each member); never invent groups."""
    groups: dict[str, list[dict]] = {}
    for s in stmts:
        if s["alternative_group"]:
            groups.setdefault(s["alternative_group"], []).append(s)
    for g, members in groups.items():
        problem = ("fewer than two members" if len(members) < 2 else
                   "members have different requirement_status" if len({m["requirement_status"] for m in members}) > 1
                   else "contains illustrative examples" if any(m["mention_relation"] == "illustrative_example"
                                                               for m in members) else None)
        if problem:
            for m in members:
                m["alternative_group"] = None
                m.setdefault("warnings", []).append(f"alternative group {g!r} dropped: {problem}")


# ------------------------------------------------------------------------- storage


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_cache(out_dir: Path, key: str) -> dict | None:
    p = out_dir / "cache" / f"{key}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def response_from_cache(entry: dict) -> LLMResponse:
    r = entry["response"]
    return LLMResponse(raw=r["raw"], text=r["text"], stop_reason=r["stop_reason"], usage=r["usage"],
                       request_id=r["request_id"])


def store_response(out_dir: Path, key: str, fields: dict, params: dict, resp: LLMResponse, run_id: str) -> None:
    entry = {"cache_key": key, "key_fields": fields, "received_at": now_iso(), "run_id": run_id,
             "request": {k: v for k, v in params.items() if k not in ("system", "messages")} |
                        {"output_config": {k: v for k, v in params["output_config"].items() if k != "format"}},
             "response": {"raw": resp.raw, "text": resp.text, "stop_reason": resp.stop_reason,
                          "usage": resp.usage, "request_id": resp.request_id}}
    stamp = entry["received_at"].replace(":", "").replace(".", "")
    write_json(out_dir / "responses" / key / f"{stamp}.json", entry)  # history, never overwritten
    write_json(out_dir / "cache" / f"{key}.json", entry)


def git_info(root: Path) -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                                check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True,
                                    check=True).stdout.strip())
        return {"git_commit": commit, "git_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_dirty": None}


USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def add_usage(total: dict, usage: dict) -> None:
    for k in USAGE_KEYS:
        total[k] = total.get(k, 0) + int(usage.get(k) or 0)


# ------------------------------------------------------------------------- run


def run(cfg: Config, root: Path, model: str | None, *, posting_ids: list[str] | None = None,
        limit: int | None = None, dry_run: bool = False, resume: str | None = None,
        backend: Backend | None = None, env: dict | None = None, sleep: Callable[[float], None] = time.sleep,
        run_id: str | None = None, out=print) -> dict:
    prompt = cfg.prompt_path.read_text(encoding="utf-8")
    schema = json.loads(cfg.schema_path.read_text(encoding="utf-8"))
    postings = load_postings(cfg, posting_ids, limit)
    versions = {"prompt_version": cfg.prompt_version, "schema_version": cfg.schema_version}

    if dry_run:
        rows = []
        for p in postings:
            if model:
                k = cache_key(key_fields(cfg, model, prompt, schema, p))
                entry = load_cache(cfg.out_dir, k)
                state = ("cached (valid)" if entry and parse_output(response_from_cache(entry), schema)[0] is not None
                         else "cached (invalid, would re-call)" if entry else "would call")
            else:
                state = "model not set"
            rows.append({"posting_id": p["posting_id"], "title": p["title"].strip(),
                         "chars": len(p["clean_text"]), "cache": state})
            out(f"  {p['posting_id']:46s} {len(p['clean_text']):6d} chars  {state}")
        calls = sum(r["cache"] in ("would call", "cached (invalid, would re-call)") for r in rows)
        out(f"dry run: {len(rows)} development postings, model={model or 'NOT SET'}, prompt {cfg.prompt_version} "
            f"({len(prompt)} chars), schema {cfg.schema_version}; API calls needed: "
            f"{calls if model else 'unknown until --model is set'}; nothing written, no network used")
        return {"dry_run": True, "postings": rows, "calls_needed": calls if model else None}

    if not model:
        raise ExtractionError("no model set: pass --model or set EXTRACTION_MODEL in .env "
                              "(check which models the account can use first)")
    if backend is None:
        backend = make_backend(cfg, env if env is not None else read_env(root))

    run_id = resume or run_id or "skx-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rdir = cfg.out_dir / "runs" / run_id
    prev: dict[str, dict] = {}
    if resume:
        if not (rdir / "run.json").is_file():
            raise ExtractionError(f"no run to resume at {rdir}")
        meta0 = json.loads((rdir / "run.json").read_text(encoding="utf-8"))
        if meta0["model"] != model or meta0["prompt_version"] != cfg.prompt_version or \
                meta0["schema_version"] != cfg.schema_version:
            raise ExtractionError("resume must use the same model, prompt and schema versions as the run")
        prev = {r["posting_id"]: r for r in read_jsonl(rdir / "postings.jsonl") if r["status"] in STATUSES_DONE}
        # keep only completed postings' rows, so an interruption mid-posting leaves no partial output
        for name in ("statements.jsonl", "rejected.jsonl"):
            rows = [r for r in read_jsonl(rdir / name) if r["posting_id"] in prev]
            (rdir / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        (rdir / "postings.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in prev.values()), encoding="utf-8")
    elif rdir.exists():
        raise ExtractionError(f"run {run_id} already exists; use --resume {run_id}")

    meta = {"run_id": run_id, "kind": KIND, "step": "extract_skills", "status": "running",
            "started_at": now_iso() if not resume else meta0["started_at"], "resumed_at": now_iso() if resume else None,
            "provider": backend.name, "model": model, **versions,
            "prompt_sha256": sha256_text(prompt), "schema_sha256": sha256_text(json.dumps(schema, sort_keys=True)),
            "extraction_method": f"llm:{backend.name}:{model}", "allowed_splits": sorted(ALLOWED_SPLITS),
            "posting_ids": [p["posting_id"] for p in postings], "config": cfg.raw, **git_info(root),
            "sdk_version": _sdk_version()}
    write_json(rdir / "run.json", meta)

    pacer = Pacer(cfg.min_seconds_between_requests, sleep=sleep)
    method = meta["extraction_method"]
    for p in postings:
        if p["posting_id"] in prev:
            continue
        fields = key_fields(cfg, model, prompt, schema, p)
        key = cache_key(fields)
        params = build_params(cfg, model, prompt, schema, p)
        entry = load_cache(cfg.out_dir, key)
        resp, attempts, err, cache_hit = None, [], None, False
        if entry is not None:
            cached = response_from_cache(entry)
            if parse_output(cached, schema)[0] is not None:
                resp, cache_hit = cached, True
        if resp is None:
            resp, attempts, err = call_with_retries(backend, params, cfg, pacer, sleep)
            if resp is not None:
                store_response(cfg.out_dir, key, fields, params, resp, run_id)
        rec = {"posting_id": p["posting_id"], "snapshot_id": p["snapshot_id"], "cache_key": key,
               "cache_hit": cache_hit, "attempts": attempts, "usage": resp.usage if resp else {},
               "usage_billed_this_run": not cache_hit and resp is not None,
               "request_id": resp.request_id if resp else None, "finished_at": None}
        stmts: list[dict] = []
        if resp is None:
            rec.update(status="failed", error=f"{err.kind}: {err}" if err else "no response")
        else:
            data, why = parse_output(resp, schema)
            if data is None:
                rec.update(status="failed", error=why, stop_reason=resp.stop_reason)
            else:
                stmts, rej = process_output(data, p, run_id, method, versions)
                append_jsonl(rdir / "rejected.jsonl", rej)
                rec.update(n_model_skills=len(data["skills"]), n_statements=len(stmts), n_rejected=len(rej),
                           no_skills_reason=data["no_skills_reason"],
                           status=("zero_skills" if not data["skills"] else "ok" if stmts else "all_rejected"),
                           error=None if stmts or not data["skills"] else "every skill record was rejected")
        append_jsonl(rdir / "statements.jsonl", stmts)
        rec["finished_at"] = now_iso()
        append_jsonl(rdir / "postings.jsonl", [rec])  # last: marks the posting complete
        out(f"  {p['posting_id']:46s} {rec['status']:12s} {('cache' if cache_hit else 'api'):5s} "
            f"{len(stmts):3d} statements" + (f"  [{rec['error']}]" if rec.get("error") else ""))

    results = read_jsonl(rdir / "postings.jsonl")
    billed: dict = {}
    for r in results:
        if r.get("usage_billed_this_run"):
            add_usage(billed, r["usage"])
    meta.update(status="finished", finished_at=now_iso(),
                counts={s: sum(r["status"] == s for r in results) for s in ("ok", "zero_skills", "all_rejected", "failed")},
                n_postings=len(results), n_statements=len(read_jsonl(rdir / "statements.jsonl")),
                n_rejected_records=len(read_jsonl(rdir / "rejected.jsonl")),
                api_calls=sum(len(r["attempts"]) for r in results),
                cache_hits=sum(bool(r["cache_hit"]) for r in results),
                token_usage_billed=billed,  # this run's new API usage only; cache hits cost nothing
                llm_tokens_in=billed.get("input_tokens", 0) + billed.get("cache_creation_input_tokens", 0)
                + billed.get("cache_read_input_tokens", 0),
                llm_tokens_out=billed.get("output_tokens", 0),
                failures=[{"posting_id": r["posting_id"], "status": r["status"], "error": r.get("error")}
                          for r in results if r["status"] in ("failed", "all_rejected")])
    write_json(rdir / "run.json", meta)
    out(f"run {run_id}: {meta['counts']}, statements {meta['n_statements']}, rejected records "
        f"{meta['n_rejected_records']}, cache hits {meta['cache_hits']}, tokens in/out "
        f"{meta['llm_tokens_in']}/{meta['llm_tokens_out']} -> {rdir}")
    return meta


def _sdk_version() -> str | None:
    try:
        import anthropic

        return anthropic.__version__
    except ImportError:
        return None


# ------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract skill statements from the development postings (LLM).")
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--config", type=Path, default=None, help="default: config/extraction.yaml")
    ap.add_argument("--model", default=None, help="model ID (or EXTRACTION_MODEL in .env); never guessed")
    ap.add_argument("--limit", type=int, default=None, help="process at most N development postings")
    ap.add_argument("--posting-id", action="append", default=None, help="restrict to these development postings")
    ap.add_argument("--dry-run", action="store_true", help="no network, no API key, nothing written")
    ap.add_argument("--resume", default=None, metavar="RUN_ID", help="continue an interrupted run")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    try:
        cfg = load_config(args.config or root / "config" / "extraction.yaml", root)
        env = {} if args.dry_run else read_env(root)
        if args.dry_run and not args.model:
            env = {k: v for k, v in read_env(root).items() if k == "EXTRACTION_MODEL"}  # model only; key untouched
        model = args.model or env.get("EXTRACTION_MODEL") or cfg.model
        meta = run(cfg, root, model, posting_ids=args.posting_id, limit=args.limit, dry_run=args.dry_run,
                   resume=args.resume, env=env)
    except (ExtractionError, an.AnnotationError, OSError, yaml.YAMLError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    if meta.get("dry_run"):
        return 0
    return 1 if meta["counts"]["failed"] or meta["counts"]["all_rejected"] else 0


if __name__ == "__main__":
    sys.exit(main())
