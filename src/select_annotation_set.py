"""Select the Sprint 2 human annotation set (100 postings) reproducibly. Section B, PILOT.

    python src/select_annotation_set.py --db data/processed/taxonomy_pilot.sqlite \
        --snapshot 20261006T171338Z            # writes the frozen manifest
    python src/select_annotation_set.py ... --check   # re-derive and compare to the frozen manifest

Method (selection version SELECTION_VERSION, seed SEED), applied to usable postings only:
1. Related-posting groups: union of postings on the same board that share an
   `internal_job_id` or the same *base title* (title with trailing parentheticals removed,
   e.g. "Account Executive, Enterprise (Paris, France)" -> "account executive, enterprise").
   Groups mean "related; keep together"; they are NOT duplicate decisions.
2. One representative per group is drawn with the seeded RNG, so related variants can never
   land in different splits (and annotation effort is not spent on near-repeats).
3. Employer quotas are balanced (equal share, capped by each employer's group count, the
   remainder going to employers with the most groups).
4. Within an employer, the quota is spread over title-based seniority labels
   (config/seniority_rules.yaml) proportionally, at least one per label present; within
   each label, groups are drawn in seeded order preferring departments not yet chosen.
5. 20 development / 80 evaluation postings, allocated per employer by largest remainder of
   20%, members drawn with the seeded RNG.

Reads the database read-only; writes only under data/annotation/{set_name}/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import derive_features as df

REPO_ROOT = Path(__file__).resolve().parent.parent
SET_NAME = "sprint2_v1"
SELECTION_VERSION = "1.0.0"
SEED = 20261006
TOTAL = 100
DEV = 20
MANIFEST_FIELDS = ["snapshot_id", "posting_id", "split", "board_token", "company_name", "title", "location",
                   "first_department", "seniority_label", "group_id", "group_size", "group_basis",
                   "group_members", "clean_text_sha256", "seed", "selection_version"]


class SelectionError(Exception):
    """Selection inputs are invalid or the frozen manifest does not reproduce."""


def base_title(title: str | None) -> str:
    t = (title or "").casefold().strip()
    while re.search(r"\s*\([^()]*\)\s*$", t):
        t = re.sub(r"\s*\([^()]*\)\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def load_usable(db: Path, snapshot_id: str) -> list[dict]:
    conn = df.connect_readonly(db)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM usable_postings WHERE snapshot_id = ? ORDER BY posting_id", (snapshot_id,))]
    finally:
        conn.close()
    if not rows:
        raise SelectionError(f"no usable postings for snapshot {snapshot_id}")
    return rows


def build_groups(postings: list[dict]) -> dict[str, dict]:
    """Union-find over (board, internal_job_id) and (board, base_title). Returns group_id -> info."""
    parent = {p["posting_id"]: p["posting_id"] for p in postings}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    keys: dict[tuple, list[str]] = defaultdict(list)
    for p in postings:
        if p["internal_job_id"]:
            keys[(p["board_token"], "internal_job_id", p["internal_job_id"])].append(p["posting_id"])
        keys[(p["board_token"], "base_title", base_title(p["title"]))].append(p["posting_id"])
    bases: dict[str, set[str]] = defaultdict(set)
    for (board, basis, _), ids in keys.items():
        for other in ids[1:]:
            a, b = find(ids[0]), find(other)
            if a != b:
                parent[a] = b
        if len(ids) > 1:
            for i in ids:
                bases[i].add(basis)

    members: dict[str, list[str]] = defaultdict(list)
    for p in postings:
        members[find(p["posting_id"])].append(p["posting_id"])
    groups = {}
    for ids in members.values():
        ids = sorted(ids)
        gid = f"grp:{ids[0]}"
        basis = sorted({b for i in ids for b in bases[i]}) if len(ids) > 1 else ["singleton"]
        groups[gid] = {"group_id": gid, "members": ids, "basis": "+".join(basis)}
    return groups


def balanced_quotas(capacity: dict[str, int], total: int) -> dict[str, int]:
    """Equal shares capped by capacity; leftover seats go to employers with the most capacity."""
    if sum(capacity.values()) < total:
        raise SelectionError(f"only {sum(capacity.values())} groups available, need {total}")
    quota = {k: 0 for k in capacity}
    remaining = total
    open_ = sorted(capacity, key=lambda k: (-capacity[k], k))
    while remaining:
        active = [k for k in open_ if quota[k] < capacity[k]]
        share = max(remaining // len(active), 1)
        for k in active:
            add = min(share, capacity[k] - quota[k], remaining)
            quota[k] += add
            remaining -= add
            if not remaining:
                break
    return quota


def largest_remainder(weights: dict[str, float], total: int, minimum: int = 0) -> dict[str, int]:
    keys = sorted(weights)
    if minimum and minimum * len(keys) > total:
        minimum = 0
    alloc = {k: minimum for k in keys}
    rest = total - minimum * len(keys)
    wsum = sum(weights.values()) or 1
    raw = {k: rest * weights[k] / wsum for k in keys}
    for k in keys:
        alloc[k] += math.floor(raw[k])
    left = total - sum(alloc.values())
    for k in sorted(keys, key=lambda k: (-(raw[k] - math.floor(raw[k])), k))[:left]:
        alloc[k] += 1
    return alloc


def select(postings: list[dict], seed: int = SEED, total: int = TOTAL, dev: int = DEV) -> list[dict]:
    rng = random.Random(seed)
    rules = df.load_rules()
    by_id = {p["posting_id"]: p for p in postings}
    groups = build_groups(postings)

    # 1. representative per group (seeded), with strata attributes
    units = []
    for gid in sorted(groups):
        g = groups[gid]
        rep = by_id[rng.choice(g["members"])]
        units.append({**g, "rep": rep,
                      "board": rep["board_token"],
                      "seniority": df.classify_title(rep["title"], rules)["seniority_label"],
                      "dept": (json.loads(rep["departments"]) or ["(none)"])[0]})

    # 2. employer quotas
    by_board: dict[str, list[dict]] = defaultdict(list)
    for u in units:
        by_board[u["board"]].append(u)
    quotas = balanced_quotas({b: len(us) for b, us in by_board.items()}, total)

    chosen: list[dict] = []
    for board in sorted(by_board):
        pool = by_board[board]
        cells: dict[str, list[dict]] = defaultdict(list)
        for u in pool:
            cells[u["seniority"]].append(u)
        alloc = largest_remainder({s: len(us) for s, us in cells.items()}, quotas[board], minimum=1)
        # cap by cell size; give overflow to other cells with room, largest first
        overflow = sum(max(0, alloc[s] - len(cells[s])) for s in alloc)
        alloc = {s: min(alloc[s], len(cells[s])) for s in alloc}
        for s in sorted(cells, key=lambda s: (-(len(cells[s]) - alloc[s]), s)):
            take = min(overflow, len(cells[s]) - alloc[s])
            alloc[s] += take
            overflow -= take
        used_depts: set[str] = set()
        for s in sorted(cells):
            order = sorted(cells[s], key=lambda u: u["group_id"])
            rng.shuffle(order)
            picked = []
            while len(picked) < alloc[s]:
                fresh = [u for u in order if u not in picked and u["dept"] not in used_depts]
                u = fresh[0] if fresh else next(u for u in order if u not in picked)
                picked.append(u)
                used_depts.add(u["dept"])
            chosen.extend(picked)

    # 3. dev / eval split per employer
    sel_by_board: dict[str, list[dict]] = defaultdict(list)
    for u in chosen:
        sel_by_board[u["board"]].append(u)
    dev_alloc = largest_remainder({b: len(us) for b, us in sel_by_board.items()}, dev)
    out = []
    for board in sorted(sel_by_board):
        us = sorted(sel_by_board[board], key=lambda u: u["group_id"])
        dev_ids = {u["group_id"] for u in rng.sample(us, dev_alloc[board])}
        for u in us:
            rep = u["rep"]
            out.append({
                "snapshot_id": rep["snapshot_id"], "posting_id": rep["posting_id"],
                "split": "development" if u["group_id"] in dev_ids else "evaluation",
                "board_token": board, "company_name": rep["company_name"], "title": rep["title"],
                "location": rep["location"], "first_department": u["dept"],
                "seniority_label": u["seniority"], "group_id": u["group_id"],
                "group_size": len(u["members"]), "group_basis": u["basis"],
                "group_members": ";".join(u["members"]),
                "clean_text_sha256": hashlib.sha256(rep["clean_text"].encode("utf-8")).hexdigest(),
                "seed": seed, "selection_version": SELECTION_VERSION,
            })
    return sorted(out, key=lambda r: (r["split"], r["posting_id"]))


# ------------------------------------------------------------------------ manifest


def set_dir(root: Path, set_name: str = SET_NAME) -> Path:
    return root / "data" / "annotation" / set_name


def write_manifest(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read_manifest(path: Path) -> list[dict]:
    if not path.is_file():
        raise SelectionError(f"manifest not found: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if r.fieldnames != MANIFEST_FIELDS:
            raise SelectionError(f"{path} has unexpected columns {r.fieldnames}")
        return list(r)


def validate_manifest(rows: list[dict], postings: list[dict], snapshot_id: str) -> list[str]:
    """Structural checks; returns a list of problems (empty = valid)."""
    problems = []
    usable = {p["posting_id"]: p for p in postings}
    ids = [r["posting_id"] for r in rows]
    if len(rows) != TOTAL or len(set(ids)) != TOTAL:
        problems.append(f"expected {TOTAL} distinct postings, got {len(rows)} rows / {len(set(ids))} distinct")
    for r in rows:
        if r["snapshot_id"] != snapshot_id:
            problems.append(f"{r['posting_id']}: snapshot {r['snapshot_id']} != {snapshot_id}")
        p = usable.get(r["posting_id"])
        if p is None:
            problems.append(f"{r['posting_id']}: not a usable posting in snapshot {snapshot_id}")
        elif hashlib.sha256(p["clean_text"].encode("utf-8")).hexdigest() != r["clean_text_sha256"]:
            problems.append(f"{r['posting_id']}: clean_text changed since selection")
    splits = Counter(r["split"] for r in rows)
    if splits != Counter({"development": DEV, "evaluation": TOTAL - DEV}):
        problems.append(f"split sizes {dict(splits)}, expected development={DEV} evaluation={TOTAL - DEV}")
    group_splits: dict[str, set[str]] = defaultdict(set)
    member_split: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        group_splits[r["group_id"]].add(r["split"])
        for m in r["group_members"].split(";"):
            member_split[m].add(r["split"])
    problems += [f"group {g} crosses splits {sorted(s)}" for g, s in group_splits.items() if len(s) > 1]
    problems += [f"related posting {m} is linked to both splits" for m, s in member_split.items() if len(s) > 1]
    # every candidate pair from Sprint 1's detector must be inside one group
    groups = build_groups(postings)
    gid_of = {m: g for g, info in groups.items() for m in info["members"]}
    for pair in df.near_duplicate_candidates(postings):
        if gid_of[pair["posting_id_a"]] != gid_of[pair["posting_id_b"]]:
            problems.append(f"candidate pair {pair['posting_id_a']} / {pair['posting_id_b']} split across groups")
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Select the 100-posting Sprint 2 annotation set.")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--root", type=Path, default=REPO_ROOT)
    p.add_argument("--check", action="store_true", help="verify the frozen manifest reproduces; write nothing")
    p.add_argument("--force", action="store_true", help="overwrite an existing manifest (changes the frozen set!)")
    args = p.parse_args(argv)
    path = set_dir(args.root.resolve()) / "selection_manifest.csv"
    try:
        postings = load_usable(args.db, args.snapshot)
        rows = select(postings)
        stringify = lambda rs: [{k: str(v) for k, v in r.items()} for r in rs]
        if args.check:
            frozen = read_manifest(path)
            problems = validate_manifest(frozen, postings, args.snapshot)
            if stringify(rows) != frozen:
                problems.append("re-running the selection does not reproduce the frozen manifest")
            for pr in problems:
                print(f"problem: {pr}", file=sys.stderr)
            print("frozen manifest OK (reproducible, valid)" if not problems else f"{len(problems)} problem(s)")
            return 0 if not problems else 1
        if path.exists() and not args.force:
            frozen = read_manifest(path)
            if stringify(rows) == frozen:
                print(f"manifest already frozen and identical: {path}")
                return 0
            raise SelectionError(f"{path} exists and differs; refusing to overwrite the frozen set (use --force)")
        problems = validate_manifest(stringify(rows), postings, args.snapshot)
        if problems:
            raise SelectionError("; ".join(problems[:5]))
        write_manifest(rows, path)
    except (SelectionError, FileNotFoundError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {path} ({len(rows)} postings, seed {SEED}, selection v{SELECTION_VERSION})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
