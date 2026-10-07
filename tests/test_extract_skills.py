"""Tests for src/extract_skills.py. No network: mocked SDK clients and an httpx2 MockTransport."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import anthropic
import httpx2
import pytest
from anthropic.types import Message

import extract_skills as ex
import select_annotation_set as sel
from test_annotation_set import SNAP, build_db

REPO = Path(__file__).resolve().parent.parent
MODEL = "test-model-id"  # placeholder; the extractor never assumes a real model ID
API_URL = "https://api.anthropic.com/v1/messages"


# ------------------------------------------------------------------------- fixtures / helpers


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "repo"
    db = build_db(root)
    assert sel.main(["--db", str(db), "--snapshot", SNAP, "--root", str(root)]) == 0
    for rel in ["config/extraction.yaml", "config/prompts/skill_extraction_v1.md",
                "config/schemas/skill_extraction_output_v1.json"]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)
    text = (root / "config/extraction.yaml").read_text().replace(
        "db: data/processed/taxonomy_pilot.sqlite", f"db: {db}")
    (root / "config/extraction.yaml").write_text(text)
    cfg = ex.load_config(root / "config/extraction.yaml", root)
    cfg.min_seconds_between_requests = 0.0
    return root, cfg


def message(payload, stop_reason="end_turn", usage=(120, 40), raw_text=None) -> Message:
    text = raw_text if raw_text is not None else json.dumps(payload)
    return Message.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": MODEL,
        "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]}})


def skill(statement, evidence, context=None, status="required", relation="direct", alt=None, example_of=None):
    return {"skill_statement": statement, "evidence_text": evidence, "evidence_context": context or evidence,
            "section_heading": None, "requirement_status": status, "mention_relation": relation,
            "example_of": example_of, "alternative_group": alt, "skill_category": "tool", "notes": None}


def ok_payload(_params=None):
    return {"skills": [skill("Python", "Python", alt="alt-1"), skill("SQL", "SQL", alt="alt-1"),
                       skill("stakeholder collaboration", "Collaborate with stakeholders", status="unspecified")],
            "no_skills_reason": None}


def http_error(cls, status, headers=None):
    resp = httpx2.Response(status, headers=headers or {}, request=httpx2.Request("POST", API_URL))
    return cls(f"HTTP {status}", response=resp, body=None)


class FakeClient:
    """Stands in for anthropic.Anthropic: messages.create(**params) -> responder(params, n)."""

    def __init__(self, responder):
        self.responder, self.calls = responder, []
        self.messages = self

    def create(self, **params):
        self.calls.append(params)
        out = self.responder(params, len(self.calls))
        if isinstance(out, Exception):
            raise out
        return out


def backend(responder) -> tuple[ex.AnthropicBackend, FakeClient]:
    client = FakeClient(responder)
    return ex.AnthropicBackend(api_key="unused", timeout=1, client=client), client


def run(cfg, root, be, **kw):
    sleeps = kw.pop("sleeps", [])
    return ex.run(cfg, root, kw.pop("model", MODEL), backend=be, sleep=sleeps.append, out=lambda *_: None, **kw)


def rundir(cfg, meta):
    return cfg.out_dir / "runs" / meta["run_id"]


# ------------------------------------------------------------------------- success


def test_success_offsets_computed_locally_and_provenance(env):
    root, cfg = env
    be, client = backend(lambda p, n: message(ok_payload()))
    meta = run(cfg, root, be, limit=2, run_id="r1")
    assert meta["counts"] == {"ok": 2, "zero_skills": 0, "all_rejected": 0, "failed": 0}
    d = rundir(cfg, meta)
    stmts = ex.read_jsonl(d / "statements.jsonl")
    postings = {p["posting_id"]: p for p in ex.load_postings(cfg, limit=2)}
    assert len(stmts) == 6
    for s in stmts:
        text = postings[s["posting_id"]]["clean_text"]
        assert text[s["evidence_start"]:s["evidence_end"]] == s["source_span"]
        assert s["kind"] == "skill" and s["statement_id"].startswith(f"r1:{s['posting_id']}:skill:")
        assert s["prompt_version"] == "skill_extraction_v1" and s["extraction_method"] == f"llm:anthropic:{MODEL}"
    assert {s["alternative_group"] for s in stmts if s["text"] in ("Python", "SQL")} == {"alt-1"}
    # request shape: structured output with the versioned schema, no guessed model, nothing model-specific added
    p0 = client.calls[0]
    assert p0["model"] == MODEL and p0["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in p0 and "effort" not in p0["output_config"]
    assert "<posting_text>" in p0["messages"][0]["content"]
    # provenance and token usage
    run_meta = json.loads((d / "run.json").read_text())
    assert run_meta["token_usage_billed"]["input_tokens"] == 240 and run_meta["llm_tokens_out"] == 80
    assert run_meta["allowed_splits"] == ["development"] and run_meta["status"] == "finished"
    assert len(list((cfg.out_dir / "cache").glob("*.json"))) == 2
    assert len(list((cfg.out_dir / "responses").rglob("*.json"))) == 2


def test_real_sdk_request_and_parsing_through_mock_transport(env):
    root, cfg = env
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        msg = message(ok_payload())
        return httpx2.Response(200, json=msg.to_dict(), headers={"request-id": "req_mock"})

    client = anthropic.Anthropic(api_key="sk-test-not-real", max_retries=0,
                                 http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    be = ex.AnthropicBackend(api_key="sk-test-not-real", timeout=1, client=client)
    meta = run(cfg, root, be, limit=1, run_id="sdk")
    assert meta["counts"]["ok"] == 1 and bodies[0]["output_config"]["format"]["schema"]["additionalProperties"] is False
    rec = ex.read_jsonl(rundir(cfg, meta) / "postings.jsonl")[0]
    assert rec["request_id"] == "req_mock"
    assert "sk-test-not-real" not in (rundir(cfg, meta) / "run.json").read_text()


# ------------------------------------------------------------------------- malformed output


@pytest.mark.parametrize("msg, fragment", [
    (message(None, raw_text='{"skills": [ {"skill_statement": '), "invalid_json"),
    (message({"skills": [{"skill_statement": "Python"}], "no_skills_reason": None}), "schema"),
    (message({"skills": [], "no_skills_reason": None, "extra": 1}), "schema"),
    (message(ok_payload(), stop_reason="max_tokens"), "truncated"),
    (message(ok_payload(), stop_reason="refusal"), "refusal"),
])
def test_malformed_responses_fail_and_are_preserved(env, msg, fragment):
    root, cfg = env
    be, client = backend(lambda p, n: msg)
    meta = run(cfg, root, be, limit=1, run_id="bad")
    rec = ex.read_jsonl(rundir(cfg, meta) / "postings.jsonl")[0]
    assert rec["status"] == "failed" and fragment in rec["error"]
    assert meta["failures"][0]["status"] == "failed" and ex.read_jsonl(rundir(cfg, meta) / "statements.jsonl") == []
    assert rec["usage_billed_this_run"] and meta["llm_tokens_in"] == 120  # tokens of a failed output still count
    assert len(list((cfg.out_dir / "responses").rglob("*.json"))) == 1   # original response kept
    # an invalid cached response is not reused: the next run calls again
    run(cfg, root, be, limit=1, run_id="bad2")
    assert len(client.calls) == 2


# ------------------------------------------------------------------------- evidence


def test_unsupported_evidence_is_rejected_not_kept(env):
    root, cfg = env
    payload = {"skills": [skill("Python", "Python"), skill("Kubernetes", "Kubernetes"),
                          skill("SQL", "sql")],  # wrong case is unsupported too
               "no_skills_reason": None}
    be, _ = backend(lambda p, n: message(payload))
    meta = run(cfg, root, be, limit=1, run_id="unsup")
    d = rundir(cfg, meta)
    assert [s["text"] for s in ex.read_jsonl(d / "statements.jsonl")] == ["Python"]
    rej = ex.read_jsonl(d / "rejected.jsonl")
    assert [r["record"]["skill_statement"] for r in rej] == ["Kubernetes", "SQL"]
    assert all(r["reason"].startswith("unsupported") for r in rej)


def test_all_records_rejected_is_a_failure_not_zero_skills(env):
    root, cfg = env
    be, _ = backend(lambda p, n: message({"skills": [skill("Rust", "Rust")], "no_skills_reason": None}))
    meta = run(cfg, root, be, limit=1, run_id="allrej")
    assert meta["counts"]["all_rejected"] == 1 and meta["failures"][0]["status"] == "all_rejected"


def test_repeated_evidence_resolved_by_context_or_rejected():
    text = "Requirements\n- Python for services.\n\nNice to have\n- Python for data tooling.\n"
    second = text.index("Python for data")
    assert ex.resolve_evidence(text, "Python", "- Python for data tooling.")[:2] == (second, second + 6)
    assert ex.resolve_evidence(text, "Python", "Python for services.")[2].startswith("context (2 occurrences)")
    for ctx, why in [("Python", "context occurs more than once"), ("not in text", "context not found"),
                     ("Requirements", "evidence not inside context")]:
        with pytest.raises(ValueError, match=why):
            ex.resolve_evidence(text, "Python", ctx)
    with pytest.raises(ValueError, match="ambiguous"):
        ex.resolve_evidence("Go or Go", "Go", "Go or Go")  # repeated inside its own context
    assert ex.resolve_evidence(text, " Python for services. ", "")[2] == "unique, trimmed whitespace"


def test_model_offsets_are_never_used():
    posting = {"posting_id": "p", "snapshot_id": SNAP, "clean_text": "Use SQL daily. SQL is required."}
    rec = skill("SQL", "SQL", context="SQL is required.")
    rec["evidence_start"], rec["evidence_end"] = 0, 3  # a model-supplied offset would be ignored (and is not in the schema)
    stmts, rej = ex.process_output({"skills": [rec], "no_skills_reason": None}, posting, "r", "m", {})
    assert (stmts[0]["evidence_start"], stmts[0]["evidence_end"]) == (15, 18) and not rej


def test_duplicate_statements_and_invalid_alternative_groups():
    posting = {"posting_id": "p", "snapshot_id": SNAP,
               "clean_text": "Go or Python. Languages such as C++ or Rust. Python again."}
    data = {"skills": [
        skill("Go", "Go", alt="a"), skill("Python", "Python", context="Go or Python.", alt="a"),
        skill("C++", "C++", relation="illustrative_example", alt="b", example_of="languages"),
        skill("Rust", "Rust", relation="illustrative_example", alt="b", example_of="languages"),
        skill("python", "Python again"),                     # duplicate statement
        skill("Solo", "Languages", alt="c"),                  # group with one member
    ], "no_skills_reason": None}
    stmts, rej = ex.process_output(data, posting, "r", "m", {})
    by = {s["text"]: s for s in stmts}
    assert by["Go"]["alternative_group"] == by["Python"]["alternative_group"] == "a"
    assert by["C++"]["alternative_group"] is None and "illustrative" in by["C++"]["warnings"][0]
    assert by["Solo"]["alternative_group"] is None and "fewer than two" in by["Solo"]["warnings"][0]
    assert [r["reason"] for r in rej] == ["duplicate skill_statement in this posting"]
    assert [s["statement_id"] for s in stmts] == [f"r:p:skill:{i}" for i in range(5)]


# ------------------------------------------------------------------------- zero skills


def test_zero_skills_is_valid_and_distinct_from_failure(env):
    root, cfg = env
    be, _ = backend(lambda p, n: message({"skills": [], "no_skills_reason": "only benefits text"}))
    meta = run(cfg, root, be, limit=1, run_id="zero")
    rec = ex.read_jsonl(rundir(cfg, meta) / "postings.jsonl")[0]
    assert rec["status"] == "zero_skills" and rec["error"] is None and meta["failures"] == []
    be2, _ = backend(lambda p, n: message({"skills": [], "no_skills_reason": None}))
    meta2 = run(cfg, root, be2, limit=1, run_id="zero-bad", model="other-model")
    assert ex.read_jsonl(rundir(cfg, meta2) / "postings.jsonl")[0]["status"] == "failed"


# ------------------------------------------------------------------------- rate limits, retries, failures


def test_rate_limit_honours_retry_after_then_succeeds(env):
    root, cfg = env
    be, client = backend(lambda p, n: http_error(anthropic.RateLimitError, 429, {"retry-after": "7"})
                         if n == 1 else message(ok_payload()))
    sleeps = []
    meta = run(cfg, root, be, limit=1, run_id="rl", sleeps=sleeps)
    rec = ex.read_jsonl(rundir(cfg, meta) / "postings.jsonl")[0]
    assert rec["status"] == "ok" and len(client.calls) == 2 and 7.0 in sleeps
    assert [a["outcome"] for a in rec["attempts"]] == ["error", "response"]
    assert rec["attempts"][0]["error_kind"] == "rate_limit" and rec["attempts"][0]["retry_after"] == 7.0


def test_rate_limit_through_real_sdk_is_mapped(env):
    root, cfg = env
    calls = []

    def handler(req):
        calls.append(1)
        return httpx2.Response(429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}},
                               headers={"retry-after": "2"})

    client = anthropic.Anthropic(api_key="sk-test", max_retries=0,
                                 http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    cfg.max_attempts = 3
    meta = run(cfg, root, ex.AnthropicBackend("sk-test", 1, client=client), limit=1, run_id="rl-sdk")
    rec = ex.read_jsonl(rundir(cfg, meta) / "postings.jsonl")[0]
    assert rec["status"] == "failed" and rec["error"].startswith("rate_limit") and len(calls) == 3  # bounded


@pytest.mark.parametrize("err, attempts", [
    (http_error(anthropic.BadRequestError, 400), 1),        # not retryable
    (http_error(anthropic.AuthenticationError, 401), 1),
    (http_error(anthropic.InternalServerError, 500), 4),    # retried up to max_attempts
    (anthropic.APIConnectionError(request=httpx2.Request("POST", API_URL)), 4),
    (anthropic.APITimeoutError(request=httpx2.Request("POST", API_URL)), 4),
])
def test_failed_calls_are_bounded_and_recorded(env, err, attempts):
    root, cfg = env
    be, client = backend(lambda p, n: err)
    sleeps = []
    meta = run(cfg, root, be, limit=1, run_id="fail", sleeps=sleeps)
    rec = ex.read_jsonl(rundir(cfg, meta) / "postings.jsonl")[0]
    assert rec["status"] == "failed" and len(client.calls) == attempts == len(rec["attempts"])
    assert len(sleeps) == attempts - 1 and all(s <= cfg.backoff_max_seconds for s in sleeps)
    assert meta["llm_tokens_in"] == 0 and meta["failures"][0]["posting_id"] == rec["posting_id"]
    assert not (cfg.out_dir / "cache").exists()  # nothing cached for a call without a response


# ------------------------------------------------------------------------- cache + resume


def test_cache_reuse_is_free_and_keyed_by_model_prompt_schema(env):
    root, cfg = env
    be, client = backend(lambda p, n: message(ok_payload()))
    run(cfg, root, be, limit=3, run_id="c1")
    meta = run(cfg, root, be, limit=3, run_id="c2")
    assert len(client.calls) == 3 and meta["cache_hits"] == 3 and meta["llm_tokens_in"] == 0
    assert meta["n_statements"] == 9
    run(cfg, root, be, limit=3, run_id="c3", model="another-model")       # model is in the key
    assert len(client.calls) == 6
    cfg.prompt_version = "skill_extraction_v1-test"                         # prompt version is in the key
    run(cfg, root, be, limit=3, run_id="c4")
    assert len(client.calls) == 9


def test_cache_key_covers_text_hash_and_prompt_content(env):
    root, cfg = env
    p = ex.load_postings(cfg, limit=1)[0]
    prompt, schema = cfg.prompt_path.read_text(), json.loads(cfg.schema_path.read_text())
    base = ex.cache_key(ex.key_fields(cfg, MODEL, prompt, schema, p))
    assert base != ex.cache_key(ex.key_fields(cfg, MODEL, prompt + " ", schema, p))
    assert base != ex.cache_key(ex.key_fields(cfg, MODEL, prompt, schema, dict(p, clean_text_sha256="0" * 64)))
    assert base != ex.cache_key(ex.key_fields(cfg, MODEL, prompt, {**schema, "x": 1}, p))


def test_resume_skips_completed_postings_and_retries_failed(env):
    root, cfg = env
    fail_second = lambda p, n: http_error(anthropic.BadRequestError, 400) if n == 2 else message(ok_payload())
    be, client = backend(fail_second)
    meta = run(cfg, root, be, limit=3, run_id="res")
    assert meta["counts"] == {"ok": 2, "zero_skills": 0, "all_rejected": 0, "failed": 1}
    be2, client2 = backend(lambda p, n: message(ok_payload()))
    meta2 = run(cfg, root, be2, limit=3, resume="res")
    assert len(client2.calls) == 1 and meta2["counts"]["ok"] == 3 and meta2["n_statements"] == 9
    ids = [s["statement_id"] for s in ex.read_jsonl(rundir(cfg, meta2) / "statements.jsonl")]
    assert len(ids) == len(set(ids)) == 9
    with pytest.raises(ex.ExtractionError, match="same model"):
        run(cfg, root, be2, limit=3, resume="res", model="other")
    with pytest.raises(ex.ExtractionError, match="already exists"):
        run(cfg, root, be2, limit=1, run_id="res")


# ------------------------------------------------------------------------- scope, dry run, secrets


def test_only_development_postings_are_allowed(env):
    root, cfg = env
    manifest = sel.read_manifest(cfg.set_dir / "selection_manifest.csv")
    ev = next(r["posting_id"] for r in manifest if r["split"] == "evaluation")
    with pytest.raises(ex.ExtractionError, match="evaluation"):
        ex.load_postings(cfg, posting_ids=[ev])
    assert {p["split"] for p in ex.load_postings(cfg)} == {"development"} and len(ex.load_postings(cfg)) == 20


def test_dry_run_uses_no_backend_no_key_and_writes_nothing(env):
    root, cfg = env
    res = ex.run(cfg, root, None, limit=4, dry_run=True, out=lambda *_: None)
    assert res["calls_needed"] is None and len(res["postings"]) == 4 and not cfg.out_dir.exists()
    res = ex.run(cfg, root, MODEL, limit=4, dry_run=True, out=lambda *_: None)
    assert res["calls_needed"] == 4 and not cfg.out_dir.exists()
    assert ex.main(["--root", str(root), "--dry-run", "--limit", "2"]) == 0 and not cfg.out_dir.exists()


def test_real_run_requires_model_and_key(env, monkeypatch):
    root, cfg = env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("EXTRACTION_MODEL", raising=False)
    with pytest.raises(ex.ExtractionError, match="no model set"):
        ex.run(cfg, root, None, limit=1, out=lambda *_: None)
    with pytest.raises(ex.ExtractionError, match="ANTHROPIC_API_KEY is not set"):
        ex.run(cfg, root, MODEL, limit=1, env={}, out=lambda *_: None)
    assert ex.main(["--root", str(root), "--limit", "1"]) == 2  # no model: refused before any call


def test_env_file_is_read_but_key_never_written(env, monkeypatch):
    root, cfg = env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-test-SECRET-123\nEXTRACTION_MODEL=from-env-model\n")
    vals = ex.read_env(root)
    assert vals["ANTHROPIC_API_KEY"] == "sk-test-SECRET-123" and vals["EXTRACTION_MODEL"] == "from-env-model"
    be, _ = backend(lambda p, n: message(ok_payload()))
    run(cfg, root, be, limit=1, run_id="sec")
    for f in cfg.out_dir.rglob("*.json*"):
        assert "SECRET-123" not in f.read_text()


def test_output_schema_is_api_compatible_and_checked():
    schema = json.loads((REPO / "config/schemas/skill_extraction_output_v1.json").read_text())

    def objects(s):
        if isinstance(s, dict):
            if s.get("type") == "object":
                yield s
            for v in s.values():
                yield from objects(v)
        elif isinstance(s, list):
            for v in s:
                yield from objects(v)

    for o in objects(schema):  # structured outputs: every object closed, every property required
        assert o["additionalProperties"] is False and set(o["required"]) == set(o["properties"])
    banned = {"minimum", "maximum", "minLength", "maxLength", "multipleOf"}
    assert not banned & set(json.dumps(schema).replace('"', " ").split())
    assert ex.check_schema(ok_payload(), schema) == []
    bad = ok_payload()
    bad["skills"][0]["requirement_status"] = "must"
    assert ex.check_schema(bad, schema) and ex.check_schema({"skills": []}, schema)
