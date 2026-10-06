"""Fetch raw Greenhouse Job Board snapshots (Sprint 1).

For every board in config/boards.yaml this calls the public, unauthenticated endpoint

    GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

and stores the response body, byte for byte, in an immutable timestamped snapshot:

    data/raw/greenhouse/{snapshot_id}/{board_token}.json

Each stored file gets a row in data/raw_manifest.csv (fields from docs/data_contract.md §10).

Behaviour:
- Cache first: by default the newest manifest entry for a board whose file still matches
  its recorded size and SHA-256 is reused, keeping its original snapshot_id and fetched_at.
- --refresh fetches every board into a NEW snapshot; earlier snapshots are never touched.
- --dry-run reads config and cache only: no network calls, no file changes.
- Failed responses are never written to disk or to the manifest.

Only GET requests are made. No application-submission endpoints, no API keys, no LLM calls.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://boards-api.greenhouse.io/v1/boards"
DEFAULT_USER_AGENT = "taxonomy-skill-project/0.1 (Section B capstone; Greenhouse public job boards)"

RAW_SUBDIR = Path("data/raw/greenhouse")
MANIFEST_SUBPATH = Path("data/raw_manifest.csv")
MANIFEST_FIELDS = [
    "snapshot_id",
    "board_token",
    "file_path",
    "fetched_at",
    "http_status",
    "job_count",
    "sha256",
    "bytes",
]

SNAPSHOT_ID_FORMAT = "%Y%m%dT%H%M%SZ"
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
BOARD_REQUIRED_KEYS = {"board_token", "company_name"}
BOARD_OPTIONAL_KEYS = {"industry", "industry_source"}
CONFIG_TOP_LEVEL_KEYS = {"boards"}
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


class ConfigError(Exception):
    """The board configuration or manifest is invalid."""


class FetchError(Exception):
    """A board could not be fetched or its response was invalid."""


@dataclass(frozen=True)
class Board:
    board_token: str
    company_name: str
    industry: str | None = None
    industry_source: str | None = None


@dataclass(frozen=True)
class FetchSettings:
    base_url: str = DEFAULT_BASE_URL
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = 30.0       # seconds, per request
    delay: float = 1.0          # seconds between network requests to different boards
    max_retries: int = 3        # retries after the first attempt, transient errors only
    backoff: float = 2.0        # base for exponential backoff when no Retry-After is given
    retry_budget: float = 60.0  # max total seconds spent waiting on retries, per board


@dataclass
class BoardResult:
    board_token: str
    status: str  # fetched | cached | failed | would_fetch | would_use_cache
    snapshot_id: str | None = None
    fetched_at: str | None = None
    job_count: int | None = None
    file_path: str | None = None
    message: str = ""


# --------------------------------------------------------------------------- config


def load_config(path: Path) -> list[Board]:
    """Load and validate the board list. Raises ConfigError on any problem."""
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse {path}: {exc}") from exc

    if not isinstance(data, dict) or "boards" not in data:
        raise ConfigError(f"{path} must be a mapping with a top-level 'boards' key")
    unknown = set(data) - CONFIG_TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(f"{path}: unknown top-level keys: {sorted(unknown)}")

    raw_boards = data["boards"]
    if raw_boards is None:
        raw_boards = []
    if not isinstance(raw_boards, list):
        raise ConfigError(f"{path}: 'boards' must be a list")

    boards: list[Board] = []
    seen: dict[str, int] = {}
    for i, entry in enumerate(raw_boards):
        where = f"{path}: boards[{i}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be a mapping")
        missing = BOARD_REQUIRED_KEYS - set(entry)
        if missing:
            raise ConfigError(f"{where} is missing required keys: {sorted(missing)}")
        unknown = set(entry) - BOARD_REQUIRED_KEYS - BOARD_OPTIONAL_KEYS
        if unknown:
            raise ConfigError(f"{where} has unknown keys: {sorted(unknown)}")

        token = entry["board_token"]
        if not isinstance(token, str) or not TOKEN_RE.match(token):
            raise ConfigError(
                f"{where}: board_token must be a non-empty string of letters, digits, '-' or '_'"
            )
        key = token.lower()
        if key in seen:
            raise ConfigError(
                f"{where}: duplicate board_token '{token}' (already used in boards[{seen[key]}])"
            )
        seen[key] = i

        for field in ("company_name", "industry", "industry_source"):
            value = entry.get(field)
            if field == "company_name" or value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ConfigError(f"{where}: {field} must be a non-empty string")
        if entry.get("industry") is not None and entry.get("industry_source") is None:
            raise ConfigError(f"{where}: industry_source is required when industry is set")

        boards.append(
            Board(
                board_token=token,
                company_name=entry["company_name"].strip(),
                industry=entry.get("industry"),
                industry_source=entry.get("industry_source"),
            )
        )
    return boards


# ------------------------------------------------------------------------- manifest


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != MANIFEST_FIELDS:
            raise ConfigError(
                f"{path} has unexpected columns {reader.fieldnames}; expected {MANIFEST_FIELDS}"
            )
        return list(reader)


def append_manifest_row(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


# ------------------------------------------------------------------------ responses


def validate_payload(body: bytes) -> int:
    """Return the number of jobs, or raise FetchError if the body is not a valid jobs response."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "jobs" not in payload:
        raise FetchError("response JSON has no 'jobs' key")
    if not isinstance(payload["jobs"], list):
        raise FetchError("response 'jobs' is not a list")
    return len(payload["jobs"])


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    """Parse a Retry-After header (delta-seconds or HTTP-date) into seconds from now."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - now).total_seconds())


def board_url(base_url: str, board_token: str) -> str:
    return f"{base_url.rstrip('/')}/{board_token}/jobs?content=true"


def fetch_board(
    session: requests.Session,
    board: Board,
    settings: FetchSettings,
    sleep: Callable[[float], None],
    now: Callable[[], datetime],
) -> tuple[bytes, int]:
    """GET one board with bounded retries. Returns (body bytes, HTTP status) on HTTP 200."""
    url = board_url(settings.base_url, board.board_token)
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    waited = 0.0

    for attempt in range(settings.max_retries + 1):
        retry_after: float | None = None
        try:
            response = session.get(url, headers=headers, timeout=settings.timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            problem = f"{type(exc).__name__}: {exc}"
        except requests.RequestException as exc:
            raise FetchError(f"request failed: {exc}") from exc
        else:
            if response.status_code == 200:
                return response.content, response.status_code
            if response.status_code not in TRANSIENT_STATUSES:
                raise FetchError(f"HTTP {response.status_code} (not retried)")
            problem = f"HTTP {response.status_code}"
            retry_after = parse_retry_after(response.headers.get("Retry-After"), now())

        if attempt == settings.max_retries:
            raise FetchError(f"{problem}; gave up after {attempt + 1} attempts")

        wait = retry_after if retry_after is not None else settings.backoff * (2**attempt)
        remaining = settings.retry_budget - waited
        if wait > remaining:
            source = "Retry-After" if retry_after is not None else "backoff"
            raise FetchError(
                f"{problem}; {source} wait of {wait:.0f}s exceeds remaining retry budget "
                f"of {remaining:.0f}s, not retrying"
            )
        sleep(wait)
        waited += wait

    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------- cache


def verify_cached_file(row: dict[str, str], root: Path) -> str | None:
    """Return None if the cached file matches the manifest row, else a reason it doesn't."""
    file_path = (root / row["file_path"]).resolve()
    if not file_path.is_relative_to(root.resolve()):
        return f"manifest path {row['file_path']} is outside the project"
    if not file_path.is_file():
        return f"file missing: {row['file_path']}"
    body = file_path.read_bytes()
    if str(len(body)) != row["bytes"]:
        return f"size mismatch for {row['file_path']}"
    if hashlib.sha256(body).hexdigest() != row["sha256"]:
        return f"SHA-256 mismatch for {row['file_path']}"
    try:
        validate_payload(body)
    except FetchError as exc:
        return f"{row['file_path']}: {exc}"
    return None


def find_valid_cache(
    board_token: str, rows: list[dict[str, str]], root: Path
) -> tuple[dict[str, str] | None, list[str]]:
    """Newest manifest row for this board whose file verifies, plus warnings for bad ones."""
    warnings: list[str] = []
    candidates = [r for r in rows if r["board_token"] == board_token and r["http_status"] == "200"]
    for row in sorted(candidates, key=lambda r: r["snapshot_id"], reverse=True):
        problem = verify_cached_file(row, root)
        if problem is None:
            return row, warnings
        warnings.append(f"ignoring corrupted cache (snapshot {row['snapshot_id']}): {problem}")
    return None, warnings


# ------------------------------------------------------------------------------ run


def write_snapshot_file(snapshot_dir: Path, board_token: str, body: bytes) -> Path:
    """Write body to {snapshot_dir}/{board_token}.json without ever overwriting a file."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    final = snapshot_dir / f"{board_token}.json"
    tmp = snapshot_dir / f".{board_token}.json.part"
    tmp.write_bytes(body)
    try:
        os.link(tmp, final)  # fails if final already exists
    finally:
        tmp.unlink()
    return final


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(
    boards: list[Board],
    settings: FetchSettings,
    root: Path,
    *,
    refresh: bool = False,
    dry_run: bool = False,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    log: Callable[[str], None] = print,
) -> list[BoardResult]:
    manifest_path = root / MANIFEST_SUBPATH
    rows = read_manifest(manifest_path)

    snapshot_id = now().strftime(SNAPSHOT_ID_FORMAT)
    snapshot_dir = root / RAW_SUBDIR / snapshot_id
    if snapshot_dir.exists() and not dry_run:
        raise ConfigError(
            f"Snapshot folder {snapshot_dir} already exists; refusing to overwrite. "
            "Wait a second and re-run."
        )

    results: list[BoardResult] = []
    made_request = False
    session = session or requests.Session()

    for board in boards:
        token = board.board_token

        if not refresh:
            cached, warnings = find_valid_cache(token, rows, root)
            for w in warnings:
                log(f"  warning [{token}]: {w}")
            if cached is not None:
                results.append(
                    BoardResult(
                        board_token=token,
                        status="would_use_cache" if dry_run else "cached",
                        snapshot_id=cached["snapshot_id"],
                        fetched_at=cached["fetched_at"],
                        job_count=int(cached["job_count"]),
                        file_path=cached["file_path"],
                    )
                )
                continue

        if dry_run:
            results.append(
                BoardResult(token, "would_fetch", message=board_url(settings.base_url, token))
            )
            continue

        if made_request:
            sleep(settings.delay)
        made_request = True

        try:
            body, http_status = fetch_board(session, board, settings, sleep, now)
            job_count = validate_payload(body)
        except FetchError as exc:
            results.append(BoardResult(token, "failed", message=str(exc)))
            continue
        fetched_at = utc_iso(now())

        try:
            path = write_snapshot_file(snapshot_dir, token, body)
        except OSError as exc:
            results.append(BoardResult(token, "failed", message=f"could not save response: {exc}"))
            continue
        rel_path = path.relative_to(root).as_posix()
        row = {
            "snapshot_id": snapshot_id,
            "board_token": token,
            "file_path": rel_path,
            "fetched_at": fetched_at,
            "http_status": http_status,
            "job_count": job_count,
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
        append_manifest_row(manifest_path, row)
        rows.append({k: str(v) for k, v in row.items()})
        results.append(
            BoardResult(
                token,
                "fetched",
                snapshot_id=snapshot_id,
                fetched_at=fetched_at,
                job_count=job_count,
                file_path=rel_path,
                message="0 jobs on this board" if job_count == 0 else "",
            )
        )
    return results


def print_summary(results: list[BoardResult], dry_run: bool, log: Callable[[str], None] = print) -> None:
    groups = (
        [("Would fetch", "would_fetch"), ("Would reuse cache", "would_use_cache")]
        if dry_run
        else [("Fetched", "fetched"), ("Cached (reused)", "cached"), ("Failed", "failed")]
    )
    log("")
    log("DRY RUN: no network calls were made and no files were changed." if dry_run else "Summary")
    for title, status in groups:
        group = [r for r in results if r.status == status]
        log(f"{title}: {len(group)}")
        for r in group:
            parts = [f"  - {r.board_token}"]
            if r.snapshot_id:
                parts.append(f"snapshot={r.snapshot_id}")
            if r.fetched_at:
                parts.append(f"fetched_at={r.fetched_at}")
            if r.job_count is not None:
                parts.append(f"jobs={r.job_count}")
            if r.message:
                parts.append(f"({r.message})")
            log(" ".join(parts))


# ----------------------------------------------------------------------------- CLI


def settings_from_env(args: argparse.Namespace) -> FetchSettings:
    base_url = os.environ.get("GREENHOUSE_BASE_URL", DEFAULT_BASE_URL)
    if not base_url.startswith("https://"):
        raise ConfigError(f"GREENHOUSE_BASE_URL must be an https:// URL, got {base_url!r}")
    for name in ("timeout", "delay", "retry_budget", "max_retries"):
        if getattr(args, name) < 0:
            raise ConfigError(f"--{name.replace('_', '-')} must not be negative")
    return FetchSettings(
        base_url=base_url,
        user_agent=os.environ.get("HTTP_USER_AGENT") or DEFAULT_USER_AGENT,
        timeout=args.timeout,
        delay=args.delay,
        max_retries=args.max_retries,
        retry_budget=args.retry_budget,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Snapshot Greenhouse job boards (public GET only).")
    p.add_argument("--config", type=Path, default=None, help="board list (default: config/boards.yaml)")
    p.add_argument("--root", type=Path, default=REPO_ROOT, help="project root (default: repo root)")
    p.add_argument("--refresh", action="store_true", help="fetch every board into a new snapshot")
    p.add_argument("--dry-run", action="store_true", help="show the plan; no network, no file changes")
    p.add_argument("--timeout", type=float, default=FetchSettings.timeout, help="request timeout, seconds")
    p.add_argument("--delay", type=float, default=FetchSettings.delay, help="delay between boards, seconds")
    p.add_argument("--max-retries", type=int, default=FetchSettings.max_retries, help="retries for transient errors")
    p.add_argument(
        "--retry-budget", type=float, default=FetchSettings.retry_budget,
        help="max seconds spent waiting on retries per board",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    config_path = args.config or root / "config" / "boards.yaml"

    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
    except ImportError:
        pass

    try:
        boards = load_config(config_path)
        settings = settings_from_env(args)
        if not boards:
            print(
                f"No boards configured in {config_path}. Add boards (agreed with Section A) "
                "and re-run. Nothing was fetched."
            )
            return 0
        results = run(boards, settings, root, refresh=args.refresh, dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    print_summary(results, args.dry_run)
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
