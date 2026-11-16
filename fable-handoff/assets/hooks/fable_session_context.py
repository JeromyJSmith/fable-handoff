#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SessionStart hook for a fable-handoff run.

Prints a short note that Claude Code adds to the model's context when a
session starts, resumes or continues after compaction. The note points at
the three files that hold the run's memory, so that the model rereads them
instead of relying on what it remembers.

Prints nothing when the project has no fable/handoff.json.
"""
from __future__ import annotations

import json
import os
import re
import sys

TASK_LINE = re.compile(r"^\s*[-*+]\s+\[( |x|X)\]\s+")


def read_payload():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def find_project(payload):
    """Return the first candidate directory that holds fable/handoff.json."""
    candidates = [os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd"), os.getcwd()]
    for candidate in candidates:
        if candidate and os.path.isfile(os.path.join(candidate, "fable", "handoff.json")):
            return os.path.realpath(candidate)
    return None


def count_tasks(project):
    """Return (done, remaining) from fable/STATE.md, skipping code fences."""
    done = remaining = 0
    try:
        with open(os.path.join(project, "fable", "STATE.md"), encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    in_fence = False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        found = TASK_LINE.match(line)
        if found and not in_fence:
            if found.group(1) == " ":
                remaining += 1
            else:
                done += 1
    return done, remaining


def main():
    payload = read_payload()
    project = find_project(payload)
    if project is None:
        return 0
    source = payload.get("source") or "unknown"
    counts = count_tasks(project)
    if counts is None:
        ledger = "fable/STATE.md is missing, so recreate it from the mission before anything else."
    else:
        ledger = "Task ledger: %d done, %d remaining." % counts
    print(
        "This project is set up for an unattended handoff run. Session event: %s. %s\n"
        "Before you act, read fable/MISSION.md (the job and its limits), fable/STATE.md "
        "(what is done and the next step) and fable/DECISIONS.md (decisions already made). "
        "Trust those files over your memory of earlier turns, which may have been compacted. "
        "Nobody is available to answer questions during the run." % (source, ledger)
    )
    try:
        with open(os.path.join(project, "fable", "BLOCKED.md"), encoding="utf-8", errors="replace") as handle:
            blocked = handle.read().strip() != ""
    except OSError:
        blocked = False
    if blocked:
        print("fable/BLOCKED.md has content: a blocker for the owner was recorded. Read it before continuing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
