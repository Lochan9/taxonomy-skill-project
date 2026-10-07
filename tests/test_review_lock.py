"""Tests for the review log's inter-process lock (review_workflow._file_lock).

Real-process tests run natively on this machine's OS (POSIX: fcntl.flock). The Windows-backend and
no-backend tests MOCK the platform modules: they check the code paths, not native Windows behaviour."""

from __future__ import annotations

import errno
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

import review_workflow as rw
from test_dashboard import DRAFT, call, decide, hdrs, repo, view  # noqa: F401  (repo is a fixture)

SRC = Path(rw.__file__).resolve().parent
TESTS = Path(__file__).resolve().parent

WORKER = textwrap.dedent("""
    import json, sys, time
    from pathlib import Path
    sys.path[:0] = [{src!r}, {tests!r}]
    import dashboard as dash, review_workflow as rw
    root, db, pid, start, rid = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), sys.argv[5]
    review = rw.Review(dash.Context(root, db))
    st = review.posting_state("alice", "development", "ai_revised", pid)
    while not start.exists():
        time.sleep(0.005)
    try:
        ev, created = review.apply({{"reviewer_id": "alice", "mode": "development", "source": "ai_revised",
            "posting_id": pid, "action": "add", "skill_statement": "SQL", "evidence_text": "SQL",
            "required_or_preferred": "required", "expected_version": st["version"],
            "expected_source_sha": st["draft_sha"], "client_request_id": rid}})
        print(json.dumps({{"status": 201 if created else 200}}))
    except rw.ReviewError as e:
        print(json.dumps({{"status": e.status, "error": str(e)}}))
""")


def run_workers(r, tmp_path, request_ids):
    script = tmp_path / "worker.py"
    script.write_text(WORKER.format(src=str(SRC), tests=str(TESTS)))
    start = tmp_path / "go"
    procs = [subprocess.Popen([sys.executable, str(script), str(r["root"]), str(r["db"]), r["p0"], str(start), rid],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for rid in request_ids]
    time.sleep(1.0)            # let every worker load its state (same version 0) before any write
    start.touch()
    outs = [p.communicate(timeout=60) for p in procs]
    import json
    return [json.loads(o[0].strip().splitlines()[-1]) for o in outs], outs


@pytest.mark.skipif(rw.fcntl is None, reason="needs a POSIX fcntl backend on this machine")
def test_concurrent_processes_cannot_both_write_the_same_version(repo, tmp_path):
    """Native (this OS): 6 processes race with the same expected version; exactly one write wins."""
    results, outs = run_workers(repo, tmp_path, [uuid.uuid4().hex for _ in range(6)])
    statuses = sorted(r["status"] for r in results)
    assert statuses == [201] + [409] * 5, (results, [o[1][-300:] for o in outs])
    assert len(repo["app"].review.events("alice")) == 1


@pytest.mark.skipif(rw.fcntl is None, reason="needs a POSIX fcntl backend on this machine")
def test_concurrent_duplicate_submissions_are_written_once(repo, tmp_path):
    """Native (this OS): the same request id sent by 5 processes at once is written exactly once."""
    rid = uuid.uuid4().hex
    results, outs = run_workers(repo, tmp_path, [rid] * 5)
    assert sorted(r["status"] for r in results) == [200] * 4 + [201], results
    assert len(repo["app"].review.events("alice")) == 1


@pytest.mark.skipif(rw.fcntl is None, reason="needs a POSIX fcntl backend on this machine")
def test_lock_blocks_a_second_holder_until_released(tmp_path):
    """Native (this OS): while one process holds the lock, another waits for it."""
    log = tmp_path / "r" / "decisions.jsonl"
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import sys, time; sys.path.insert(0, {str(SRC)!r}); import review_workflow as rw
        from pathlib import Path
        with rw._file_lock(Path({str(log)!r})):
            print("held", flush=True); time.sleep(1.5)
        """)], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    t0 = time.monotonic()
    with rw._file_lock(log):
        waited = time.monotonic() - t0
    holder.wait(timeout=10)
    assert waited >= 0.8, waited


# ------------------------------------------------------------------------- mocked platforms


class FakeMsvcrt:
    """Stand-in for Windows msvcrt.locking; NOT native Windows."""
    LK_NBLCK, LK_UNLCK = 2, 0

    def __init__(self, busy_attempts=0):
        self.busy, self.calls = busy_attempts, []

    def locking(self, fd, mode, nbytes):
        self.calls.append((mode, nbytes))
        if mode == self.LK_NBLCK and self.busy > 0:
            self.busy -= 1
            raise OSError(errno.EACCES, "locked")


def test_windows_backend_path_is_used_when_fcntl_is_absent(repo, monkeypatch):
    """MOCKED Windows: without fcntl, the lock uses msvcrt.locking (retrying while busy)."""
    fake = FakeMsvcrt(busy_attempts=3)
    monkeypatch.setattr(rw, "fcntl", None)
    monkeypatch.setattr(rw, "msvcrt", fake)
    s, r = decide(repo, action="add", skill_statement="SQL", evidence_text="SQL", required_or_preferred="required")
    assert s == 201, r
    assert fake.calls == [(2, 1)] * 4 + [(0, 1)]           # 3 busy retries, then lock, then unlock
    assert len(repo["app"].review.events("alice")) == 1


def test_windows_backend_times_out_with_a_clear_error(repo, monkeypatch):
    """MOCKED Windows: a lock held too long gives 503, and nothing is written."""
    monkeypatch.setattr(rw, "fcntl", None)
    monkeypatch.setattr(rw, "msvcrt", FakeMsvcrt(busy_attempts=10 ** 6))
    monkeypatch.setattr(rw, "LOCK_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(rw._file_lock.__init__, "__defaults__", (0.2,))
    s, r = decide(repo, action="add", skill_statement="SQL", evidence_text="SQL", required_or_preferred="required")
    assert s == 503 and "try again" in r["error"]
    assert repo["app"].review.events("alice") == []


def test_no_locking_backend_keeps_viewing_but_refuses_writes(repo, monkeypatch):
    """MOCKED platform with neither fcntl nor msvcrt: read views work, writes are refused (503)."""
    monkeypatch.setattr(rw, "fcntl", None)
    monkeypatch.setattr(rw, "msvcrt", None)
    assert view(repo)["version"] == 0
    assert call(repo["app"], "GET", "/api/corpus")[0] == 200
    s, r = decide(repo, action="add", skill_statement="SQL", evidence_text="SQL", required_or_preferred="required")
    assert s == 503 and "no file-locking support" in r["error"]
    assert repo["app"].review.events("alice") == []


@pytest.mark.parametrize("err", [errno.ENOTSUP, errno.ENOLCK])
def test_filesystem_that_refuses_locks_gives_a_clear_error(repo, monkeypatch, err):
    """MOCKED filesystem: flock raising ENOTSUP/ENOLCK refuses the write instead of writing unlocked."""
    class NoLockFcntl:
        LOCK_EX, LOCK_UN = 2, 8

        @staticmethod
        def flock(fd, op):
            raise OSError(err, "Operation not supported")
    monkeypatch.setattr(rw, "fcntl", NoLockFcntl)
    s, r = decide(repo, action="add", skill_statement="SQL", evidence_text="SQL", required_or_preferred="required")
    assert s == 503 and "local disk" in r["error"]
    assert repo["app"].review.events("alice") == []


def test_modules_import_without_fcntl():
    """The dashboard and workflow import on a Python without fcntl (simulated by blocking the module)."""
    code = textwrap.dedent(f"""
        import sys; sys.modules["fcntl"] = None; sys.path.insert(0, {str(SRC)!r})
        import review_workflow as rw, dashboard
        print("ok", rw.fcntl is None)
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "ok True", out.stderr[-500:]
