#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Link the git-ignored data a run reads from the main checkout into a fresh worktree.

A worktree gets only what git tracks. Data a project keeps out of git (loaded
tables, databases, imported files) is missing there, so the readiness check
fails and the run cannot start. "shared_data" in fable/handoff.json names it:

    "shared_data": {"from": "/path/to/the/main/checkout", "paths": ["data/", "store.duckdb"]}
    "shared_data": {"from": "/path/to/the/main/checkout", "all_ignored": true, "exclude": ["scratch/"]}

With "all_ignored", the paths are every entry git ignores in the main checkout
(`git status --ignored`), except environments, caches and locks (DEFAULT_EXCLUDE)
and anything in "exclude".

This script makes each missing path a symbolic link to the same path in the
main checkout. It never overwrites or removes anything: a path that already
exists is left as it is and reported. The links are read through like the
real files; the guard still refuses file-tool writes to them, because they
resolve outside the project. Database writes go through the project's own
writer, as they would from the main checkout, so one database stays the
only one.

    uv run --script scripts/link_shared_data.py --project <worktree>
    uv run --script scripts/link_shared_data.py --project <worktree> --check   # report only

Exit codes: 0 every path present, 1 something could not be linked or is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


DEFAULT_EXCLUDE = (".venv", ".pixi", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".DS_Store",
                   ".writer.lock", ".claude/", ".git/", ".locks", "__marimo__", ".orig")


def shared_paths(spec: dict, project: Path | None = None) -> list[str]:
    """The paths shared_data names: its list, or every git-ignored entry of the main checkout."""
    paths = [str(p).rstrip("/") for p in spec.get("paths") or []]
    if spec.get("all_ignored") and spec.get("from"):
        import subprocess
        source = Path(os.path.expanduser(str(spec["from"])))
        out = subprocess.run(["git", "-C", str(source), "status", "--ignored", "--porcelain"], capture_output=True, text=True).stdout
        exclude = list(DEFAULT_EXCLUDE) + [str(x) for x in spec.get("exclude") or []]
        for line in out.splitlines():
            if not line.startswith("!! "):
                continue
            rel = line[3:].strip().strip('"').rstrip("/")
            if rel and not any(x.rstrip("/") in rel.split("/") or rel.startswith(x) or rel.endswith(x) for x in exclude):
                if rel not in paths:
                    paths.append(rel)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--check", action="store_true", help="report what is present, linked or missing; change nothing")
    ap.add_argument("--preset", help="read shared_data from this preset (before init has written fable/handoff.json)")
    ap.add_argument("--from", dest="source", help="the main checkout, in place of shared_data.from")
    args = ap.parse_args()
    project = Path(args.project).expanduser().resolve()
    try:
        if args.preset:
            preset = json.loads((Path(__file__).resolve().parent.parent / "assets" / "presets" / args.preset / "preset.json").read_text(encoding="utf-8"))
            spec = (preset.get("config") or {}).get("shared_data") or {}
        else:
            spec = json.loads((project / "fable" / "handoff.json").read_text(encoding="utf-8")).get("shared_data") or {}
    except (OSError, ValueError) as error:
        print("cannot read the shared_data settings: %s" % error, file=sys.stderr)
        return 1
    if args.source:
        spec = dict(spec, **{"from": args.source})
    source = Path(os.path.expanduser(str(spec.get("from") or ""))).resolve() if spec.get("from") else None
    paths = shared_paths(spec)
    if not paths:
        print("shared_data names no paths; nothing to do")
        return 0
    if source is None or not source.is_dir():
        print("shared_data.from is not a directory: %s" % spec.get("from"), file=sys.stderr)
        return 1
    if source == project:
        print("this is the main checkout itself; nothing to link")
        return 0
    report, bad = [], 0
    for rel in paths:
        target, origin = project / rel, source / rel
        if target.is_symlink() or target.exists():
            report.append({"path": rel, "state": "linked" if target.is_symlink() else "present", "to": os.readlink(target) if target.is_symlink() else None})
            continue
        if not origin.exists():
            report.append({"path": rel, "state": "missing in the main checkout too"})
            bad += 1
            continue
        if args.check:
            report.append({"path": rel, "state": "missing", "would_link_to": str(origin)})
            bad += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(origin, target_is_directory=origin.is_dir())
        report.append({"path": rel, "state": "linked now", "to": str(origin)})
    print(json.dumps({"from": str(source), "paths": report}, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
