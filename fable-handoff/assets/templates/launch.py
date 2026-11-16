#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Start the unattended run for this project and keep it going until it is finished.

Usage, from the project root (the launcher finds the project from its own
location, so any other directory works too):
    uv run --script fable/launch.py --dry-run     show the command, start nothing
    uv run --script fable/launch.py               start the run

What it does:
1. Refuses to start unless the readiness check passed for the current
   contents of fable/MISSION.md, fable/OPERATING_RULES.md and fable/handoff.json.
2. Moves a fable/REPORT.md left by an earlier run to
   fable/.run/REPORT-previous-<timestamp>.md, so that only a report written
   during this run can satisfy the stop gate.
3. Starts the Claude CLI in print mode with the mission as the prompt.
4. When the CLI exits, asks the stop gate whether the mission is finished.
   If it is not, and no blocker was recorded, it starts the CLI again, up to
   max_relaunches extra times and never beyond max_budget_usd.

Output goes to fable/.run/: transcript-<n>.jsonl, stderr-<n>.log and
launch_log.json.

Exit codes: 0 finished, 1 unfinished, 2 refused to start, 3 stopped on a
blocker recorded in fable/BLOCKED.md, 4 everything that can move is done and
the rest waits on the owner's answers in the question system.
"""
from __future__ import annotations

# Every script in this skill runs under uv, never a bare interpreter.
UV_SCRIPT = ["uv", "run", "--quiet", "--script"]

import argparse
import hashlib
import json
import re
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
FABLE = PROJECT / "fable"
RUN_DIR = FABLE / ".run"
HASHED_FILES = ["MISSION.md", "OPERATING_RULES.md", "handoff.json"]

RESUME_PROMPT = (
    "This is a relaunch of an unattended run that stopped before the mission was finished. "
    "Read fable/STATE.md first: it holds the task list, the current focus and the next step. "
    "Then read fable/DECISIONS.md, look at `git status` and `git log` for work in progress, "
    "and continue from the next step. Do not redo tasks that are already checked off."
)


FAILURE_LINE = re.compile(r"^\s*(=+ )?([0-9]+ failed\b|FAILED\b|Traceback \(most recent call last\)|[A-Za-z.]*(Error|Exception): |NOT READY\b|fatal: |error: )")


def last_session_note(attempt):
    """What the previous attempt was doing when it stopped, from its own transcript.

    A relaunched session starts with no memory of the last one beyond the
    ledger. This adds its last words, its last failing output and, after a
    crash, the end of its error log, so the next session does not start blind.
    """
    lines = []
    transcript = RUN_DIR / ("transcript-%d.jsonl" % attempt)
    last_text, last_failure = "", ""
    if transcript.exists():
        for raw in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("parent_tool_use_id"):
                continue  # subagent output is not the session's own state
            content = (event.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if event.get("type") == "assistant" and block.get("type") == "text" and block.get("text", "").strip():
                    last_text = block["text"].strip()
                elif block.get("type") == "tool_result":
                    body = block.get("content")
                    body = body if isinstance(body, str) else json.dumps(body)
                    hits = [l.strip() for l in body.splitlines() if FAILURE_LINE.search(l)]
                    if hits:
                        last_failure = hits[0]
    if last_text:
        lines.append("Its last message was: " + " ".join(last_text.split())[:600])
    if last_failure:
        lines.append("The last failing output it saw was: " + last_failure[:300])
    errors = RUN_DIR / ("stderr-%d.log" % attempt)
    if errors.exists():
        tail = [l for l in errors.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()][-3:]
        if tail:
            lines.append("The CLI's error output ended with: " + " | ".join(tail)[:300])
    if not lines:
        return ""
    return "\n\nWhere the previous session stopped (attempt %d):\n- " % attempt + "\n- ".join(lines)


def say(message):
    print("[launch] " + message, flush=True)


def refuse(message):
    sys.stderr.write("[launch] Not starting: " + message + "\n")
    sys.exit(2)


def package_hash():
    """SHA-256 over the three files that define the run. Must match readiness_check.py."""
    digest = hashlib.sha256()
    for name in HASHED_FILES:
        digest.update(name.encode("utf-8"))
        path = FABLE / name
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def has_content(path):
    return path.exists() and path.read_text(encoding="utf-8", errors="replace").strip() != ""


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def check_readiness():
    record = load_json(RUN_DIR / "readiness.json", None)
    how = "Run the readiness_check.py script of the fable-handoff skill with --project %s, fix what it reports, then launch again." % PROJECT
    if not isinstance(record, dict):
        refuse("there is no readiness record at fable/.run/readiness.json. " + how)
    if record.get("ok") is not True:
        refuse("the last readiness check failed. " + how)
    if record.get("package_hash") != package_hash():
        refuse(
            "fable/MISSION.md, fable/OPERATING_RULES.md or fable/handoff.json changed after the last readiness check, "
            "so that check no longer covers what would run. " + how
        )


def archive_stale_report():
    """Move a report left by an earlier run into fable/.run/.

    The stop gate takes an existing fable/REPORT.md as proof that the report
    was written. A stale one would let this run stop before any work is done.
    """
    report = FABLE / "REPORT.md"
    if not report.exists():
        return
    archive = RUN_DIR / ("REPORT-previous-%s.md" % time.strftime("%Y%m%d-%H%M%S"))
    report.replace(archive)
    say("fable/REPORT.md is left from an earlier run. It was moved to fable/.run/%s, and this run has to write its own." % archive.name)


def spent_so_far():
    """Sum of total_cost_usd over the result lines of every transcript in fable/.run/."""
    total = 0.0
    for transcript in RUN_DIR.glob("transcript-*.jsonl"):
        for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                cost = event.get("total_cost_usd")
                if isinstance(cost, (int, float)):
                    total += cost
    return total


def build_command(config, prompt, budget, resume):
    command = [
        str(config.get("claude_binary") or "claude"),
        "-p", prompt,
        "--model", str(config.get("model", "fable")),
        "--effort", str(config.get("effort", "high")),
        "--permission-mode", str(config.get("permission_mode", "auto")),
        "--append-system-prompt-file", "fable/OPERATING_RULES.md",
        "--output-format", "stream-json",
        "--verbose",
    ]
    if resume:
        command.append("--continue")
    if budget is not None:
        command += ["--max-budget-usd", "%.2f" % budget]
    if config.get("mcp_config"):
        # MCP servers the run may use, such as InfraNodus for gap checks. Their
        # tools still go through the permission mode.
        command += ["--mcp-config", str(config["mcp_config"])]
    if config.get("max_turns"):
        command += ["--max-turns", str(config["max_turns"])]
    return command + [str(arg) for arg in config.get("extra_cli_args") or []]


HOOK_FILES = ["fable_guard.py", "fable_stop_gate.py", "fable_session_context.py"]
# Files that shape the system prompt or the tool list. Claude Fable 5.2 binds
# its preserved thinking to them: if one changes, continuing the old
# conversation fails with HTTP 400, so the next launch must start fresh.
CONTEXT_FILES = [".claude/settings.json", ".claude/settings.local.json", "CLAUDE.md", "CLAUDE.local.md", ".mcp.json", "fable/OPERATING_RULES.md"]


def context_hash(config):
    digest = hashlib.sha256()
    paths = [PROJECT / rel for rel in CONTEXT_FILES] + sorted((PROJECT / ".claude" / "agents").glob("*.md"))
    if config.get("mcp_config"):
        paths.append((PROJECT / str(config["mcp_config"])).resolve())
    for path in paths:
        digest.update(str(path).encode())
        digest.update(path.read_bytes() if path.is_file() else b"-")
    return digest.hexdigest()


def mcp_failures(attempt):
    """MCP servers that the CLI reported as not connected, from the init event of a transcript."""
    transcript = RUN_DIR / ("transcript-%d.jsonl" % attempt)
    if not transcript.exists():
        return []
    for raw in transcript.read_text(encoding="utf-8", errors="replace").splitlines()[:50]:
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "system" and event.get("subtype") == "init":
            return [s.get("name", "?") for s in event.get("mcp_servers") or [] if isinstance(s, dict) and s.get("status") not in ("connected", None)]
    return []


def load_questions():
    path = FABLE / "questions.py"
    if not path.exists():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("fable_questions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answers_waiting():
    """Topics the owner answered that this project has not imported yet."""
    questions = load_questions()
    if questions is None:
        return []
    try:
        return [q.get("topic") for q in questions.system(PROJECT).load() if q.get("status") == "answered"]
    except Exception:
        return []


def parked_count():
    state = FABLE / "STATE.md"
    return len(re.findall(r"^- \[ \] .*\(waiting on owner: ", state.read_text(encoding="utf-8"), re.M)) if state.exists() else 0


def mission_finished(config):
    """Ask the stop gate, in dry-run mode, whether it would allow a stop."""
    gate = PROJECT / ".claude" / "hooks" / "fable_stop_gate.py"
    if not gate.exists():
        say("warning: .claude/hooks/fable_stop_gate.py is missing, so the run cannot be confirmed as finished.")
        return False
    env = dict(os.environ, FABLE_GATE_DRY_RUN="1", CLAUDE_PROJECT_DIR=str(PROJECT))
    timeout = (config.get("verify_timeout_seconds") or 1800) + 120
    try:
        result = subprocess.run([*UV_SCRIPT, str(gate)], input="{}", text=True, capture_output=True, cwd=PROJECT, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Start the unattended run described in fable/MISSION.md.")
    parser.add_argument("--dry-run", action="store_true", help="print the command that would run and exit")
    parser.add_argument("--skip-readiness", action="store_true", help="start without a passing readiness record. For debugging the launcher only.")
    args = parser.parse_args()
    os.chdir(PROJECT)

    config = load_json(FABLE / "handoff.json", None)
    if not isinstance(config, dict):
        refuse("fable/handoff.json is missing or is not valid JSON. Restore it, run the readiness check, then launch again.")
    if not (FABLE / "MISSION.md").exists():
        refuse("fable/MISSION.md is missing.")
    if not args.skip_readiness:
        check_readiness()

    mission = (FABLE / "MISSION.md").read_text(encoding="utf-8")
    cap = config.get("max_budget_usd")
    cap = float(cap) if isinstance(cap, (int, float)) else None
    log = load_json(RUN_DIR / "launch_log.json", [])
    if not isinstance(log, list):
        log = []

    if args.dry_run:
        budget = None if cap is None else max(cap - spent_so_far(), 0.0)
        placeholder = "<contents of fable/MISSION.md, %d characters>" % len(mission)
        print(shlex.join(build_command(config, placeholder, budget, resume=False)))
        return 0

    binary = str(config.get("claude_binary") or "claude")
    if shutil.which(binary) is None:
        refuse("the Claude CLI %r was not found. Install it, or set claude_binary in fable/handoff.json to its full path and rerun the readiness check." % binary)
    if has_content(FABLE / "BLOCKED.md"):
        refuse("fable/BLOCKED.md has content, which tells the run to stop at once. Record the owner's answer in fable/DECISIONS.md, delete fable/BLOCKED.md, then launch again.")
    waiting = answers_waiting()
    if waiting:
        refuse("the owner has answered %d parked question(s) (%s). Bring the answers in first, so the parked tasks resume: "
               "uv run --script fable/questions.py import, then rerun the readiness check and launch again." % (len(waiting), ", ".join(waiting)))

    missing_hooks = [name for name in HOOK_FILES if not (PROJECT / ".claude" / "hooks" / name).is_file()]
    if missing_hooks:
        # Claude Code treats a hook whose script is missing as non-blocking, so
        # the guard or the stop gate would silently not exist.
        refuse("hook script(s) missing from .claude/hooks/: %s. Run init_handoff.py --refresh-hooks, then the readiness check." % ", ".join(missing_hooks))
    if config.get("mcp_config") and not (PROJECT / str(config["mcp_config"])).is_file():
        refuse("mcp_config names %s, which does not exist." % config["mcp_config"])

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    # Stop-gate counts belong to one launcher session. Start this one from zero.
    for stale in ("stop_gate.json", "stop_gate_exhausted.txt"):
        if (RUN_DIR / stale).exists():
            (RUN_DIR / stale).unlink()

    # The first launch of a project gets the mission alone. Any later launch
    # is told to resume from the ledger.
    mode = "fresh"
    prompt = mission if not log else RESUME_PROMPT + "\n\nThe mission follows.\n\n" + mission
    outcome = "unfinished"
    launches = int(config.get("max_relaunches", 3) or 0) + 1

    started_context = context_hash(config)
    for launch in range(launches):
        budget = None
        if cap is not None:
            budget = cap - spent_so_far()
            if budget < 0.01:
                say("the budget of $%.2f is spent, so no further launch starts." % cap)
                break
        if launch == 0:
            archive_stale_report()
        attempt = len(log)
        while (RUN_DIR / ("transcript-%d.jsonl" % attempt)).exists():
            attempt += 1
        if mode == "continue" and context_hash(config) != started_context:
            # The system prompt or the tools changed since the conversation began.
            # Continuing it would fail, so start fresh from the ledger instead.
            say("settings, instructions or MCP servers changed since the session began, so this launch starts fresh.")
            mode, prompt = "fresh", prompt + "\n\nThe mission follows.\n\n" + mission
        if mode == "fresh":
            started_context = context_hash(config)
        command = build_command(config, prompt, budget, resume=(mode == "continue"))
        say("attempt %d (%s)%s, launch %d of at most %d" % (attempt, mode, "" if budget is None else ", budget $%.2f" % budget, launch + 1, launches))

        started = time.time()
        with open(RUN_DIR / ("transcript-%d.jsonl" % attempt), "w") as out, open(RUN_DIR / ("stderr-%d.log" % attempt), "w") as err:
            process = subprocess.Popen(command, cwd=PROJECT, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
            try:
                exit_code = process.wait()
            except KeyboardInterrupt:
                process.terminate()
                process.wait()
                say("interrupted. The ledger in fable/STATE.md holds the progress so far.")
                return 1
        seconds = round(time.time() - started, 1)

        failed_mcp = mcp_failures(attempt)
        if failed_mcp:
            say("warning: MCP server(s) did not connect: %s. The run continued without their tools." % ", ".join(failed_mcp))
        blocked = has_content(FABLE / "BLOCKED.md")
        finished = not blocked and mission_finished(config)
        log.append({
            "attempt": attempt,
            "mode": mode,
            "exit_code": exit_code,
            "seconds": seconds,
            "budget_usd": budget,
            "finished": finished,
            "blocked": blocked,
            "mcp_failed": failed_mcp,
        })
        (RUN_DIR / "launch_log.json").write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
        say("attempt %d ended with exit code %d after %s seconds." % (attempt, exit_code, seconds))

        if blocked:
            outcome = "blocked"
            break
        if finished:
            outcome = "parked" if parked_count() else "finished"
            break
        # A clean exit leaves a session that can be continued. A crashed one
        # may be damaged, so the next launch starts fresh from the ledger.
        note = last_session_note(attempt)
        if exit_code == 0:
            mode, prompt = "continue", RESUME_PROMPT + note
        else:
            mode, prompt = "fresh", RESUME_PROMPT + note + "\n\nThe mission follows.\n\n" + mission

    review = "Review it with the post_run_report.py script of the fable-handoff skill (--project %s)." % PROJECT
    if outcome == "finished":
        say("The mission is finished: tasks checked, verify passing, report written. " + review)
        return 0
    if outcome == "parked":
        say("Every task that can move is done; %d task(s) wait on the owner. Their questions are in the project's question system. "
            "Answer them there, then: uv run --script fable/questions.py import, rerun the readiness check and launch again to resume. " % parked_count() + review)
        return 4
    if outcome == "blocked":
        say("The run stopped on a recorded blocker. Read fable/BLOCKED.md, record your answer in fable/DECISIONS.md, delete fable/BLOCKED.md, rerun the readiness check and launch again.")
        return 3
    say("The run ended unfinished. Logs are in fable/.run/. " + review)
    return 1


if __name__ == "__main__":
    sys.exit(main())
