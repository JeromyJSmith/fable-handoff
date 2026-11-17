#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Stop hook for a fable-handoff run.

When the model tries to end its turn, this hook decides whether the mission
is finished. It checks, in this order:

1. fable/BLOCKED.md has content: allow the stop. The model has recorded that
   nothing can move without the owner.
2. fable/STATE.md has unchecked tasks: block and list them. A task marked
   "(waiting on owner: <topic>)" counts as finished for this run only when a
   question with that topic is open in the project's question system with a
   complete record (fable/questions.py check passes it). Otherwise it is open.
3. The verify command from fable/handoff.json fails: block and show the output.
   With parked tasks, a failing verify is expected, so the stop is allowed
   once fable/REPORT.md names every parked question.
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
from pathlib import Path

TASK_LINE = re.compile(r"^\s*[-*+]\s+\[( |x|X)\]\s+(.*)$")
OUTPUT_TAIL_LINES = 40
OUTPUT_TAIL_CHARS = 4000


# Output that means the command never got to check anything: the interpreter,
# a module or the program itself is missing. On macOS a bare `python3` is often
# a different interpreter from the one with the project's packages, so a verify
# command like `python3 -m pytest` fails this way forever.
CANNOT_RUN = re.compile(
    r"No module named|ModuleNotFoundError|command not found|: not found\b|No such file or directory|"
    r"error: Failed to spawn|ImportError while loading conftest",
    re.IGNORECASE,
)


def cannot_run(code, output):
    """True when a failing command failed before it could check anything."""
    return code in (126, 127) or (code not in (0, None) and bool(CANNOT_RUN.search(output or "")))

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


def load_questions(project):
    """The project's fable/questions.py as a module, or None."""
    path = os.path.join(project, "fable", "questions.py")
    if not os.path.isfile(path):
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("fable_questions", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


def split_parked(project, config, tasks):
    """(parked tasks with a complete question record, tasks still open, problems)."""
    questions = load_questions(project)
    parked, still_open, problems = [], [], []
    records = None
    for task in tasks:
        match = re.search(r"\(waiting on owner: ([^)]+)\)", task)
        if not match:
            still_open.append(task)
            continue
        topic = match.group(1).strip()
        if questions is None:
            still_open.append(task)
            problems.append("%s: fable/questions.py is missing, so the question cannot be checked" % topic)
            continue
        if records is None:
            try:
                records = questions.system(Path(project), config).load()
            except Exception as error:
                records = []
                problems.append("the question system could not be read (%s)" % error)
        record = next((q for q in records if q.get("topic") == topic and q.get("status", "open") == "open"), None)
        found = questions.record_problems(record, questions.rung_names(config)) if record else ["no open question with this topic in the question system"]
        if found:
            still_open.append(task)
            problems.append("%s: %s" % (topic, "; ".join(found)))
        else:
            parked.append((task, topic))
    return parked, still_open, problems


# Deterministic code: when "deterministic_code" in fable/handoff.json names
# the calculation code (globs), no file there may call a language model. Jev
# and other model calls belong only in the files listed as "allowed" (for
# example the module that asks a written schema).
MODEL_CALL = (
    r"^\s*(?:import|from)\s+(?:anthropic|openai|litellm|ollama|typesafe\w*)\b|\bopenrouter\.ai\b|\.messages\.create\(|"
    r"\bchat\.completions\b|\bsystem_one\(|\bjev_client\b|\bjev_schema\.ask\(|\bgenerateText\(|\bstreamText\("
)


def model_call_findings(project, config):
    """[(file, line number, text)] for every model call inside the deterministic code."""
    import fnmatch
    import re
    spec = config.get("deterministic_code") or {}
    globs = [g for g in spec.get("paths") or [] if isinstance(g, str)]
    if not globs:
        return []
    allowed = [g for g in spec.get("allowed") or [] if isinstance(g, str)]
    pattern = re.compile(spec.get("pattern") or MODEL_CALL, re.MULTILINE)
    roots = [project] + [os.path.realpath(os.path.expanduser(str(c.get("path")))) for c in config.get("companion_repositories") or []
                         if isinstance(c, dict) and c.get("path")]
    found = []
    for g in globs:
        base = project
        for root in roots[1:]:
            if g.startswith(root + os.sep):
                base, g = root, os.path.relpath(g, root)
        import glob as globmod
        for path in sorted(globmod.glob(os.path.join(base, g), recursive=True)):
            rel = os.path.relpath(path, base)
            if not os.path.isfile(path) or any(fnmatch.fnmatch(rel, a) for a in allowed):
                continue
            text = read_text(path) or ""
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                found.append((rel, line, text.splitlines()[line - 1].strip()[:120]))
    return found


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
    parked, tasks, park_problems = split_parked(project, config, open_tasks(state))
    if tasks:
        if park_problems:
            return (
                "The run is not finished. These tasks are marked as waiting on the owner, but their\n"
                "question does not pass the judgment test, so they still count as open:\n"
                + "\n".join("  - " + p for p in park_problems) + "\n"
                "\n"
                "What to do now: search the evidence ladder in fable/handoff.json first. Most questions\n"
                "are settled by evidence: decide those and record them by evidence. Park only a true\n"
                "policy or preference call, with its full record, through:\n"
                "  uv run --script fable/questions.py park --record <file> --task \"<task>\"\n"
                "Then continue with every task that does not depend on it.",
                {"open_tasks": len(tasks), "verify": "not run", "parked": len(parked)},
            )
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
            "If a task needs a true judgment call (policy or preference that the evidence ladder\n"
            "cannot decide), park it with fable/questions.py and keep working on the rest.\n"
            "Write fable/BLOCKED.md only when nothing at all can move.",
            {"open_tasks": len(tasks), "verify": "not run", "parked": len(parked)},
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
        if cannot_run(code, output):
            return (
                "The run is not finished, and the verify command could not even start its checks.\n"
                "\n"
                "Command: %s\n"
                "Exit code: %d\n"
                "Last lines of its output:\n"
                "%s\n"
                "\n"
                "This is an environment problem, not unfinished work: a program or module the\n"
                "command needs is missing. Run Python tools through uv (for example `uv run pytest`)\n"
                "rather than a bare interpreter. Do not change the verify command in\n"
                "fable/handoff.json. If it cannot run without the owner, write fable/BLOCKED.md and\n"
                "fable/REPORT.md, and you will be allowed to stop."
                % (command, code, tail(output)),
                {"open_tasks": 0, "verify": "cannot run"},
            )
        if code != 0 and parked:
            report = read_text(os.path.join(fable, "REPORT.md")) or ""
            unnamed = [topic for _, topic in parked if topic not in report]
            if not unnamed:
                return None, {"open_tasks": 0, "verify": "failed, parked", "parked": len(parked)}
            return (
                "Every task that can move is done; %d task(s) wait on the owner. The verify command\n"
                "still fails, which is expected while they wait. Before you stop, write\n"
                "fable/REPORT.md with a section \"Waiting on owner\" that names each parked question:\n"
                % len(parked) + "\n".join("  - " + t for t in unnamed) + "\n"
                "and what each one blocks. Do not use BLOCKED.md for this; it is only for problems\n"
                "that stop all work.",
                {"open_tasks": 0, "verify": "failed, parked", "parked": len(parked)},
            )
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

    calls = model_call_findings(project, config)
    if calls:
        return (
            "The run is not finished: the calculation code calls a language model, and every calculation\n"
            "must be plain, tested code (deterministic_code in fable/handoff.json):\n"
            + "\n".join("  - %s:%d %s" % c for c in calls[:10]) + "\n"
            "\n"
            "What to do now: replace each call with coded, tested logic. A bounded decision under a\n"
            "written schema belongs in the files deterministic_code lists as allowed, never in a calculation.",
            {"open_tasks": 0, "verify": verify, "model_calls": len(calls)},
        )
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
