#!/usr/bin/env python3
"""Stop hook for a fable-handoff run.

When the model tries to end its turn, this hook decides whether the mission
is finished. It checks, in this order:

1. fable/BLOCKED.md has content: allow the stop. The model has recorded that
   nothing can move without the owner.
2. fable/STATE.md has unchecked tasks: block and list them.
3. The verify command from fable/handoff.json fails: block and show the output.
4. fable/REPORT.md is missing or empty: block.
5. Otherwise allow the stop.

Exit 0 allows the stop. Exit 2 blocks it, and the text written to stderr is
shown to the model as its next instruction.

So that a run cannot loop forever, each block is counted in
fable/.run/stop_gate.json. After too many blocks in a row without progress,
or too many in total, the gate gives up: it allows the stop and writes the
reason to fable/.run/stop_gate_exhausted.txt.

With FABLE_GATE_DRY_RUN=1 in the environment the gate only answers. It
counts nothing and writes nothing. The launcher and the readiness check use
this to ask "is the mission finished?".
"""
from __future__ import annotations

import datetime
import json
import os
import re
import signal
import subprocess
import sys

TASK_LINE = re.compile(r"^\s*[-*+]\s+\[( |x|X)\]\s+(.*)$")
OUTPUT_TAIL_LINES = 40
OUTPUT_TAIL_CHARS = 4000


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


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def open_tasks(state_text):
    """Unchecked "- [ ]" items in the ledger. Lines inside code fences do not count."""
    tasks, in_fence = [], False
    for line in state_text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        found = TASK_LINE.match(line)
        if found and not in_fence and found.group(1) == " ":
            tasks.append(found.group(2).strip())
    return tasks


def run_verify(command, project, timeout):
    """Run the verify command. Returns (exit code or None on timeout, output)."""
    options = {"start_new_session": True} if hasattr(os, "killpg") else {}
    # The dry-run switch is meant for this gate only. If the verify command
    # inherited it, a test suite that itself runs a stop gate would see every
    # gate call as a dry run and fail, and the launcher would then think a
    # finished mission is unfinished.
    env = {name: value for name, value in os.environ.items() if name != "FABLE_GATE_DRY_RUN"}
    process = subprocess.Popen(
        command, shell=True, cwd=project, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", **options
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        return process.returncode, output
    except subprocess.TimeoutExpired:
        # Kill the whole process group, so that test runners started by the
        # shell do not keep running after the gate has answered.
        if hasattr(os, "killpg"):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
        else:
            process.kill()
        output, _ = process.communicate()
        return None, output


# A task may name the command that proves it: "- [x] Parser handles JSON (check: `pytest -k json`)".
# Only a command in backticks after "check:" is run; prose checks are left to the reader.
TASK_CHECK = re.compile(r"\(check:\s*`([^`]+)`\s*\)")


def checked_task_commands(state_text):
    """(task text, command) for every checked task that names its check, outside code fences."""
    out, in_fence = [], False
    for line in state_text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        found = TASK_LINE.match(line)
        if found and not in_fence and found.group(1) in ("x", "X"):
            check = TASK_CHECK.search(found.group(2))
            if check:
                out.append((found.group(2).strip(), check.group(1).strip()))
    return out


def tail(output):
    lines = (output or "").strip().splitlines()[-OUTPUT_TAIL_LINES:]
    return "\n".join(lines)[-OUTPUT_TAIL_CHARS:] or "(the command printed nothing)"


def evaluate(project, config):
    """Decide whether the stop is allowed.

    Returns (message, progress). `message` is None when the stop is allowed.
    `progress` describes how far the run is: the number of open tasks and the
    verify result. The block counter restarts when it changes.
    """
    fable = os.path.join(project, "fable")
    blocked_note = read_text(os.path.join(fable, "BLOCKED.md"))
    if blocked_note and blocked_note.strip():
        return None, {}

    state = read_text(os.path.join(fable, "STATE.md"))
    if state is None:
        return (
            "The stop gate cannot find fable/STATE.md, so it cannot tell whether the mission is finished.\n"
            "\n"
            "What to do now: recreate fable/STATE.md from fable/MISSION.md. List every task as a\n"
            '"- [ ]" item, check off ("- [x]") only what you have verified is done, then continue\n'
            "with the first open task.",
            {"open_tasks": -1, "verify": "not run"},
        )
    tasks = open_tasks(state)
    if tasks:
        shown = ["  - " + task for task in tasks[:20]]
        if len(tasks) > 20:
            shown.append("  ... and %d more" % (len(tasks) - 20))
        return (
            "The run is not finished: fable/STATE.md still has %d unchecked task%s.\n" % (len(tasks), "" if len(tasks) == 1 else "s")
            + "\n".join(shown) + "\n"
            "\n"
            "What to do now: continue with the next task. Check a task off only after you have\n"
            "verified it. If a task no longer applies, remove it from the list and record the\n"
            "reason in fable/DECISIONS.md.\n"
            "\n"
            "If no remaining task can move without the owner, write fable/BLOCKED.md (what is\n"
            "blocked, what you tried, the exact decision or access you need, what is already\n"
            "complete), then write fable/REPORT.md. With a BLOCKED.md that has content you will be\n"
            "allowed to stop.",
            {"open_tasks": len(tasks), "verify": "not run"},
        )

    # A checked box is a claim. Where the task names its own check, run it.
    timeout = config.get("verify_timeout_seconds") or 1800
    false_checks = []
    for task, check in checked_task_commands(state):
        code, output = run_verify(check, project, timeout)
        if code != 0:
            false_checks.append((task, check, "timed out" if code is None else "exit code %d" % code, tail(output)))
    if false_checks:
        shown = []
        for task, check, result, out in false_checks[:5]:
            shown += ["  - %s" % task, "    `%s` -> %s" % (check, result)] + ["      " + l for l in out.splitlines()[-6:]]
        return (
            "The run is not finished: %d checked task%s fail%s %s own check.\n" % (
                len(false_checks), "" if len(false_checks) == 1 else "s", "s" if len(false_checks) == 1 else "",
                "its" if len(false_checks) == 1 else "their")
            + "\n".join(shown) + "\n"
            "\n"
            "What to do now: uncheck each of these in fable/STATE.md, fix the work until its check\n"
            "passes, then check it off again. Do not change the check to make it pass.",
            {"open_tasks": len(false_checks), "verify": "task checks failed"},
        )

    command = str(config.get("verify_command") or "").strip()
    verify = "not run"
    if command:
        timeout = config.get("verify_timeout_seconds") or 1800
        code, output = run_verify(command, project, timeout)
        if code != 0:
            result = "timed out after %s seconds" % timeout if code is None else "exit code %d" % code
            return (
                "The run is not finished: every task is checked off, but the verify command fails.\n"
                "\n"
                "Command: %s\n"
                "Result: %s\n"
                "Last lines of its output:\n"
                "%s\n"
                "\n"
                "What to do now: fix what the output shows, then run the command yourself to confirm\n"
                "it exits 0. Fix the work, not the check: do not delete, skip or weaken tests to get a\n"
                "pass. If it cannot pass without something only the owner can give, write\n"
                "fable/BLOCKED.md and fable/REPORT.md, and you will be allowed to stop."
                % (command, result, tail(output)),
                {"open_tasks": 0, "verify": "failed"},
            )
        verify = "passed"

    report = read_text(os.path.join(fable, "REPORT.md"))
    if not report or not report.strip():
        return (
            "Nearly finished: every task is checked off and the verify command passes, but\n"
            "fable/REPORT.md is missing or empty.\n"
            "\n"
            "What to do now: write fable/REPORT.md for a reader who saw none of the run. Put the\n"
            "outcome first, then what was delivered, the proof, the decisions you made, anything\n"
            "you changed that the mission did not ask for, and what is left for the owner. Then stop.",
            {"open_tasks": 0, "verify": verify},
        )
    return None, {"open_tasks": 0, "verify": verify}


def record_block(project, config, message, progress):
    """Count this block. Returns True when the gate should give up and allow the stop."""
    run_dir = os.path.join(project, "fable", ".run")
    os.makedirs(run_dir, exist_ok=True)
    count_path = os.path.join(run_dir, "stop_gate.json")
    try:
        counts = json.loads(read_text(count_path) or "{}")
    except ValueError:
        counts = {}
    if not isinstance(counts, dict):
        counts = {}

    same_progress = counts.get("progress") == progress
    counts["consecutive"] = int(counts.get("consecutive", 0)) + 1 if same_progress else 1
    counts["total"] = int(counts.get("total", 0)) + 1
    counts["progress"] = progress
    counts["last_block"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(count_path, "w", encoding="utf-8") as handle:
        json.dump(counts, handle, indent=2)

    max_row = config.get("max_stop_blocks", 8)
    max_total = config.get("max_total_stop_blocks", 60)
    reasons = []
    if isinstance(max_row, int) and counts["consecutive"] > max_row:
        reasons.append(
            "The model tried to stop %d times in a row without progress (max_stop_blocks is %d). "
            "Progress means the number of open tasks or the verify result changed."
            % (counts["consecutive"], max_row)
        )
    if isinstance(max_total, int) and counts["total"] > max_total:
        reasons.append(
            "The gate blocked %d stops in total (max_total_stop_blocks is %d)." % (counts["total"], max_total)
        )
    if not reasons:
        return False
    with open(os.path.join(run_dir, "stop_gate_exhausted.txt"), "w", encoding="utf-8") as handle:
        handle.write(
            "The stop gate gave up at %s and allowed the run to stop unfinished.\n\n" % counts["last_block"]
            + "\n".join(reasons)
            + "\n\nWhat the gate was still asking for:\n\n" + message + "\n"
        )
    return True


def main():
    payload = read_payload()
    project = find_project(payload)
    if project is None:
        return 0
    dry_run = os.environ.get("FABLE_GATE_DRY_RUN") == "1"

    try:
        config = json.loads(read_text(os.path.join(project, "fable", "handoff.json")) or "")
        if not isinstance(config, dict):
            raise ValueError("the file does not hold a JSON object")
    except ValueError as error:
        # Without a config there is nothing to check against, and blocking
        # with no counter could loop. Allow the stop and leave a note for the
        # owner. The guard blocks all writes in this state, so the run cannot
        # do damage.
        if not dry_run:
            run_dir = os.path.join(project, "fable", ".run")
            os.makedirs(run_dir, exist_ok=True)
            with open(os.path.join(run_dir, "stop_gate_exhausted.txt"), "w", encoding="utf-8") as handle:
                handle.write("The stop gate could not read fable/handoff.json (%s), so it allowed the stop without checking anything.\n" % error)
        return 0

    message, progress = evaluate(project, config)
    if message is None:
        return 0
    if not dry_run and record_block(project, config, message, progress):
        return 0
    sys.stderr.write(message + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
