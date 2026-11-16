#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Rebuild a concise context document from Claude Code conversation logs.

    python3 scripts/conversation_context.py --project . --project-logs
    python3 scripts/conversation_context.py --project . --logs ~/.claude/projects/-Users-me-app/
    python3 scripts/conversation_context.py --project . --logs a.jsonl b.jsonl --json

Reads one or more JSONL conversation logs: main sessions, resumed sessions,
subagent logs with their .meta.json files, and print-mode stream-json output
such as fable/.run/transcript-<n>.jsonl. It links parent and child
conversations, finds forks (edited or retried prompts), follows the active
branch, and extracts intent, issues, successes, achievements and progress.

The extraction is the jq module assets/jq/conversations.jq, so jq must be
installed. This script only finds the files, runs jq once over all of them,
and writes:

  fable/CONTEXT.md     the context document, for people and for the mission
  fable/context.json   the same data, for scripts and jq queries

--project-logs finds the logs Claude Code keeps for the project, in
~/.claude/projects/<the project path with every character other than letters
and digits turned into "-">/, including subagent logs. Use --logs to point at
other files or directories instead, or as well.

Exit codes: 0 written, 1 no logs found, 2 jq missing or failed.
Standard library only, apart from the jq binary.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
JQ_DIR = SKILL / "assets" / "jq"


def claude_log_dir(project: Path) -> Path:
    """Where Claude Code stores the conversation logs of a project directory."""
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(project))


def collect(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files += sorted(p for p in path.rglob("*.jsonl") if p.is_file())
            files += sorted(p for p in path.rglob("agent-*.meta.json") if p.is_file())
    seen, out = set(), []
    for f in files:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def run_jq(files: list[Path], expr: str, raw: bool) -> subprocess.CompletedProcess:
    jq = shutil.which("jq")
    cmd = [jq, "-n", "-L", str(JQ_DIR)] + (["-r"] if raw else []) + [f'include "conversations"; load | {expr}', "--"] + [str(f) for f in files]
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".", help="project root; outputs go to its fable/ directory")
    ap.add_argument("--project-logs", action="store_true", help="read the logs Claude Code keeps for this project")
    ap.add_argument("--logs", nargs="*", default=[], metavar="PATH", help="log files or directories to read")
    ap.add_argument("--json", action="store_true", help="print the JSON instead of the Markdown")
    ap.add_argument("--no-write", action="store_true", help="print only; write nothing")
    args = ap.parse_args()

    if not shutil.which("jq"):
        print("jq is not installed. Install it (brew install jq, apt install jq) and run this again.", file=sys.stderr)
        return 2
    project = Path(args.project).expanduser().resolve()
    sources = [Path(p).expanduser() for p in args.logs]
    if args.project_logs:
        sources.append(claude_log_dir(project))
    if not sources:
        print("Name the logs with --logs, or pass --project-logs.", file=sys.stderr)
        return 1
    files = collect(sources)
    if not files:
        print("No conversation logs found in: " + ", ".join(str(s) for s in sources), file=sys.stderr)
        return 1

    md = run_jq(files, "context_md", raw=True)
    data = run_jq(files, "context", raw=False)
    if md.returncode != 0 or data.returncode != 0:
        print("jq failed: " + (md.stderr or data.stderr).strip()[:500], file=sys.stderr)
        return 2
    if not args.no_write:
        (project / "fable").mkdir(exist_ok=True)
        (project / "fable" / "CONTEXT.md").write_text(md.stdout.rstrip() + "\n", encoding="utf-8")
        (project / "fable" / "context.json").write_text(data.stdout, encoding="utf-8")
    print(data.stdout if args.json else md.stdout.rstrip())
    if not args.no_write:
        print(f"\nWrote fable/CONTEXT.md and fable/context.json from {len(files)} log file(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
