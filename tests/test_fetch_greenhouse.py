"""Tests for src/fetch_greenhouse.py. All HTTP traffic is mocked; nothing touches the network."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

import fetch_greenhouse as fg

START = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
JOBS_BODY = json.dumps({"jobs": [{"id": 1, "title": "Data Analyst"}, {"id": 2, "title": "ML Engineer"}],
                        "meta": {"total": 2}}).encode()
EMPTY_BODY = b'{"jobs": [], "meta": {"total": 0}}'
FAST = fg.FetchSettings(timeout=5, delay=1.0, max_retries=2, backoff=1.0, retry_budget=10.0)


# ----------------------------------------------------------------------------- fakes


class FakeResponse:
    def __init__(self, status_code: int = 200, content: bytes = JOBS_BODY, headers: dict | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class FakeSession:
    """Returns queued responses (or raises queued exceptions) per board token."""

    def __init__(self, responses: dict[str, list]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[dict] = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        token = url.split("/boards/")[1].split("/")[0]
        item = self.responses[token].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, *args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("POST must never be used")


class Clock:
    def __init__(self, start: datetime = START):
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


class Sleeper:
    def __init__(self, clock: Clock | None = None):
        self.calls: list[float] = []
        self.clock = clock

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.clock:
            self.clock.advance(seconds)


def boards(*tokens: str) -> list[fg.Board]:
    return [fg.Board(t, f"{t} Inc.") for t in tokens]


def do_run(root, tokens, session, clock=None, sleeper=None, **kwargs):
    clock = clock or Clock()
    sleeper = sleeper or Sleeper(clock)
    return fg.run(boards(*tokens), FAST, root, session=session, sleep=sleeper, now=clock,
                  log=lambda *_: None, **kwargs)


def manifest_rows(root: Path) -> list[dict]:
    return fg.read_manifest(root / fg.MANIFEST_SUBPATH)


def all_files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "boards.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------- config


def test_config_valid(tmp_path):
    path = write_config(tmp_path, """
boards:
  - board_token: acme
    company_name: Acme
    industry: Software
    industry_source: manual
  - board_token: beta-co
    company_name: Beta
""")
    loaded = fg.load_config(path)
    assert [b.board_token for b in loaded] == ["acme", "beta-co"]
    assert loaded[0].industry == "Software"


def test_config_rejects_duplicate_board_tokens(tmp_path):
    path = write_config(tmp_path, """
boards:
  - {board_token: acme, company_name: Acme}
  - {board_token: ACME, company_name: Acme again}
""")
    with pytest.raises(fg.ConfigError, match="duplicate board_token"):
        fg.load_config(path)


@pytest.mark.parametrize("text, match", [
    ("boards: {acme: 1}", "must be a list"),
    ("board: []", "top-level 'boards'"),
    ("boards: []\nextra: 1", "unknown top-level"),
    ("boards:\n  - {company_name: X}", "missing required"),
    ("boards:\n  - {board_token: '../evil', company_name: X}", "board_token must be"),
    ("boards:\n  - {board_token: a, company_name: X, colour: red}", "unknown keys"),
    ("boards:\n  - {board_token: a, company_name: X, industry: Tech}", "industry_source is required"),
    ("boards: [", "Could not parse"),
])
def test_config_rejects_invalid(tmp_path, text, match):
    with pytest.raises(fg.ConfigError, match=match):
        fg.load_config(write_config(tmp_path, text))


def test_shipped_config_is_valid_and_empty():
    assert fg.load_config(fg.REPO_ROOT / "config" / "boards.yaml") == []


def test_empty_board_list_exits_cleanly(tmp_path, capsys):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text("boards: []\n")
    assert fg.main(["--root", str(tmp_path)]) == 0
    assert "No boards configured" in capsys.readouterr().out
    assert all_files(tmp_path).keys() == {"config/boards.yaml"}


def test_main_reports_config_error(tmp_path, capsys):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text(
        "boards:\n  - {board_token: a, company_name: A}\n  - {board_token: a, company_name: B}\n")
    assert fg.main(["--root", str(tmp_path)]) == 2
    assert "duplicate board_token" in capsys.readouterr().err


# ---------------------------------------------------------------------------- fetch


def test_success_saves_original_bytes_and_manifest(tmp_path):
    session = FakeSession({"acme": [FakeResponse(200, JOBS_BODY)]})
    [result] = do_run(tmp_path, ["acme"], session)

    assert result.status == "fetched"
    assert result.snapshot_id == "20261006T120000Z"
    assert result.job_count == 2
    saved = tmp_path / "data/raw/greenhouse/20261006T120000Z/acme.json"
    assert saved.read_bytes() == JOBS_BODY

    call = session.calls[0]
    assert call["url"] == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    assert call["timeout"] == FAST.timeout
    assert "User-Agent" in call["headers"]

    [row] = manifest_rows(tmp_path)
    assert list(row) == fg.MANIFEST_FIELDS
    assert row == {
        "snapshot_id": "20261006T120000Z",
        "board_token": "acme",
        "file_path": "data/raw/greenhouse/20261006T120000Z/acme.json",
        "fetched_at": "2026-10-06T12:00:00Z",
        "http_status": "200",
        "job_count": "2",
        "sha256": hashlib.sha256(JOBS_BODY).hexdigest(),
        "bytes": str(len(JOBS_BODY)),
    }
    assert not list(saved.parent.glob(".*.part"))


def test_empty_jobs_list_is_a_successful_snapshot(tmp_path):
    [result] = do_run(tmp_path, ["quiet"], FakeSession({"quiet": [FakeResponse(200, EMPTY_BODY)]}))
    assert result.status == "fetched"
    assert result.job_count == 0
    assert "0 jobs" in result.message
    assert manifest_rows(tmp_path)[0]["job_count"] == "0"


@pytest.mark.parametrize("body, match", [
    (b"<html>not json</html>", "not valid JSON"),
    (b'{"jobs": [', "not valid JSON"),
    (b'{"meta": {"total": 0}}', "no 'jobs' key"),
    (b'{"jobs": {"id": 1}}', "not a list"),
    (b'[]', "no 'jobs' key"),
])
def test_invalid_responses_fail_and_are_not_saved(tmp_path, body, match):
    [result] = do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse(200, body)]}))
    assert result.status == "failed"
    assert match in result.message
    assert not (tmp_path / "data").exists()  # no snapshot folder, no manifest


def test_non_transient_http_error_is_not_retried(tmp_path):
    session = FakeSession({"missing": [FakeResponse(404, b'{"status": 404}')]})
    [result] = do_run(tmp_path, ["missing"], session)
    assert result.status == "failed"
    assert "HTTP 404" in result.message
    assert len(session.calls) == 1
    assert not (tmp_path / "data").exists()


def test_transient_errors_retry_with_bounded_attempts(tmp_path):
    session = FakeSession({"flaky": [FakeResponse(503, b""), requests.Timeout("slow"), FakeResponse(500, b"")]})
    sleeper = Sleeper()
    [result] = do_run(tmp_path, ["flaky"], session, sleeper=sleeper)
    assert result.status == "failed"
    assert "gave up after 3 attempts" in result.message
    assert len(session.calls) == FAST.max_retries + 1
    assert sleeper.calls == [1.0, 2.0]  # exponential backoff
    assert not (tmp_path / "data").exists()


def test_transient_error_then_success(tmp_path):
    session = FakeSession({"flaky": [requests.ConnectionError("reset"), FakeResponse(200, JOBS_BODY)]})
    [result] = do_run(tmp_path, ["flaky"], session)
    assert result.status == "fetched"
    assert len(session.calls) == 2


# ------------------------------------------------------------------------ rate limit


def test_429_respects_retry_after_seconds(tmp_path):
    session = FakeSession({"acme": [FakeResponse(429, b"", {"Retry-After": "7"}), FakeResponse(200, JOBS_BODY)]})
    sleeper = Sleeper()
    [result] = do_run(tmp_path, ["acme"], session, sleeper=sleeper)
    assert result.status == "fetched"
    assert sleeper.calls == [7.0]  # waited exactly as asked, not the shorter backoff


def test_429_respects_retry_after_http_date(tmp_path):
    later = "Tue, 06 Oct 2026 12:00:05 GMT"
    session = FakeSession({"acme": [FakeResponse(429, b"", {"Retry-After": later}), FakeResponse(200, JOBS_BODY)]})
    sleeper = Sleeper()
    [result] = do_run(tmp_path, ["acme"], session, sleeper=sleeper)
    assert result.status == "fetched"
    assert sleeper.calls == [5.0]


def test_429_retry_after_beyond_budget_fails_without_early_retry(tmp_path):
    session = FakeSession({"acme": [FakeResponse(429, b"", {"Retry-After": "3600"}), FakeResponse(200, JOBS_BODY)]})
    sleeper = Sleeper()
    [result] = do_run(tmp_path, ["acme"], session, sleeper=sleeper)
    assert result.status == "failed"
    assert "exceeds remaining retry budget" in result.message
    assert len(session.calls) == 1  # did not retry early
    assert sleeper.calls == []
    assert not (tmp_path / "data").exists()


def test_retry_budget_is_cumulative(tmp_path):
    session = FakeSession({"acme": [FakeResponse(429, b"", {"Retry-After": "6"}),
                                    FakeResponse(429, b"", {"Retry-After": "6"}),
                                    FakeResponse(200, JOBS_BODY)]})
    sleeper = Sleeper()
    [result] = do_run(tmp_path, ["acme"], session, sleeper=sleeper)
    assert result.status == "failed"  # 6 + 6 > budget of 10
    assert sleeper.calls == [6.0]
    assert len(session.calls) == 2


def test_delay_between_boards(tmp_path):
    session = FakeSession({"a": [FakeResponse()], "b": [FakeResponse()], "c": [FakeResponse()]})
    sleeper = Sleeper()
    results = do_run(tmp_path, ["a", "b", "c"], session, sleeper=sleeper)
    assert [r.status for r in results] == ["fetched"] * 3
    assert sleeper.calls == [FAST.delay, FAST.delay]


def test_mixed_results_are_reported_separately(tmp_path, capsys):
    do_run(tmp_path, ["old"], FakeSession({"old": [FakeResponse()]}))
    session = FakeSession({"new": [FakeResponse()], "bad": [FakeResponse(404, b"")]})
    results = do_run(tmp_path, ["old", "new", "bad"], session, clock=Clock(START + timedelta(hours=1)))
    assert {r.board_token: r.status for r in results} == {"old": "cached", "new": "fetched", "bad": "failed"}

    fg.print_summary(results, dry_run=False)
    out = capsys.readouterr().out
    assert "Fetched: 1" in out and "Cached (reused): 1" in out and "Failed: 1" in out


# ----------------------------------------------------------------------------- cache


def test_cache_reuse_keeps_original_snapshot_and_timestamp(tmp_path):
    do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse()]}))
    session = FakeSession({"acme": []})
    [result] = do_run(tmp_path, ["acme"], session, clock=Clock(START + timedelta(days=1)))

    assert result.status == "cached"
    assert result.snapshot_id == "20261006T120000Z"
    assert result.fetched_at == "2026-10-06T12:00:00Z"
    assert result.job_count == 2
    assert session.calls == []
    assert len(manifest_rows(tmp_path)) == 1
    assert not (tmp_path / "data/raw/greenhouse/20261007T120000Z").exists()


def test_corrupted_cache_is_detected_and_refetched(tmp_path):
    do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse()]}))
    old = tmp_path / "data/raw/greenhouse/20261006T120000Z/acme.json"
    old.write_bytes(JOBS_BODY.replace(b"Analyst", b"Analyzt"))  # same size, different hash
    tampered = old.read_bytes()

    session = FakeSession({"acme": [FakeResponse()]})
    warnings: list[str] = []
    clock = Clock(START + timedelta(days=1))
    [result] = fg.run(boards("acme"), FAST, tmp_path, session=session, sleep=Sleeper(),
                      now=clock, log=warnings.append)

    assert result.status == "fetched"
    assert result.snapshot_id == "20261007T120000Z"
    assert any("SHA-256 mismatch" in w for w in warnings)
    assert old.read_bytes() == tampered  # corrupted file left as-is for inspection
    assert len(manifest_rows(tmp_path)) == 2


def test_missing_cache_file_is_refetched(tmp_path):
    do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse()]}))
    (tmp_path / "data/raw/greenhouse/20261006T120000Z/acme.json").unlink()
    [result] = do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse()]}),
                      clock=Clock(START + timedelta(days=1)))
    assert result.status == "fetched"


def test_cache_falls_back_to_newest_valid_snapshot(tmp_path):
    do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse()]}))
    do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse(200, EMPTY_BODY)]}),
           clock=Clock(START + timedelta(days=1)), refresh=True)
    (tmp_path / "data/raw/greenhouse/20261007T120000Z/acme.json").write_bytes(b"garbage")

    [result] = do_run(tmp_path, ["acme"], FakeSession({"acme": []}), clock=Clock(START + timedelta(days=2)))
    assert result.status == "cached"
    assert result.snapshot_id == "20261006T120000Z"


def test_failed_fetch_never_becomes_cache(tmp_path):
    do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse(200, b"not json")]}))
    session = FakeSession({"acme": [FakeResponse()]})
    [result] = do_run(tmp_path, ["acme"], session, clock=Clock(START + timedelta(hours=1)))
    assert result.status == "fetched"  # the earlier failure was not treated as cached data
    assert len(session.calls) == 1


# --------------------------------------------------------------------------- refresh


def test_refresh_creates_new_snapshot_and_preserves_old(tmp_path):
    do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse(200, JOBS_BODY)]}))
    old = tmp_path / "data/raw/greenhouse/20261006T120000Z/acme.json"

    [result] = do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse(200, EMPTY_BODY)]}),
                      clock=Clock(START + timedelta(days=1)), refresh=True)

    assert result.status == "fetched"
    assert result.snapshot_id == "20261007T120000Z"
    assert old.read_bytes() == JOBS_BODY
    assert (tmp_path / "data/raw/greenhouse/20261007T120000Z/acme.json").read_bytes() == EMPTY_BODY
    assert [r["snapshot_id"] for r in manifest_rows(tmp_path)] == ["20261006T120000Z", "20261007T120000Z"]


def test_refresh_refuses_existing_snapshot_folder(tmp_path):
    do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse()]}))
    before = all_files(tmp_path)
    session = FakeSession({"acme": [FakeResponse(200, EMPTY_BODY)]})
    with pytest.raises(fg.ConfigError, match="already exists"):
        do_run(tmp_path, ["acme"], session, refresh=True)  # same clock -> same snapshot_id
    assert session.calls == []
    assert all_files(tmp_path) == before


def test_write_snapshot_file_never_overwrites(tmp_path):
    fg.write_snapshot_file(tmp_path, "acme", b"first")
    with pytest.raises(FileExistsError):
        fg.write_snapshot_file(tmp_path, "acme", b"second")
    assert (tmp_path / "acme.json").read_bytes() == b"first"


# --------------------------------------------------------------------------- dry run


def test_dry_run_makes_no_network_calls_or_file_changes(tmp_path):
    do_run(tmp_path, ["cached"], FakeSession({"cached": [FakeResponse()]}))
    before = all_files(tmp_path)

    session = FakeSession({"cached": [], "new": []})
    results = do_run(tmp_path, ["cached", "new"], session, clock=Clock(START + timedelta(days=1)), dry_run=True)

    assert {r.board_token: r.status for r in results} == {"cached": "would_use_cache", "new": "would_fetch"}
    assert session.calls == []
    assert all_files(tmp_path) == before


def test_dry_run_with_refresh_plans_all_fetches(tmp_path):
    do_run(tmp_path, ["acme"], FakeSession({"acme": [FakeResponse()]}))
    before = all_files(tmp_path)
    session = FakeSession({"acme": []})
    [result] = do_run(tmp_path, ["acme"], session, dry_run=True, refresh=True)
    assert result.status == "would_fetch"
    assert session.calls == []
    assert all_files(tmp_path) == before


def test_dry_run_cli_with_boards(tmp_path, capsys, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text("boards:\n  - {board_token: acme, company_name: Acme}\n")
    monkeypatch.setattr(fg.requests.Session, "get", lambda *a, **k: pytest.fail("network used"))
    assert fg.main(["--root", str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "Would fetch: 1" in out
    assert all_files(tmp_path).keys() == {"config/boards.yaml"}


# --------------------------------------------------------------------------- helpers


def test_manifest_with_wrong_columns_is_rejected(tmp_path):
    path = tmp_path / fg.MANIFEST_SUBPATH
    path.parent.mkdir(parents=True)
    path.write_text("snapshot_id,board_token\n")
    with pytest.raises(fg.ConfigError, match="unexpected columns"):
        fg.read_manifest(path)


def test_parse_retry_after():
    assert fg.parse_retry_after("12", START) == 12.0
    assert fg.parse_retry_after(None, START) is None
    assert fg.parse_retry_after("soon", START) is None
    assert fg.parse_retry_after("Tue, 06 Oct 2026 11:00:00 GMT", START) == 0.0
