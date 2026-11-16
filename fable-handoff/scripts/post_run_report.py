#!/usr/bin/env python3
"""Review a project after an unattended run.

Prints a Markdown review that starts with a verdict: CLEAN, or NEEDS REVIEW
with the reasons. It checks the things a run can get wrong without anyone
noticing: tasks left open, a failing verify command, uncommitted work,
deleted or weakened tests, changes to protected files, a stop gate that gave
up, a recorded blocker and a missing report. Exit 0 only when clean.

A clean verdict means none of these signs were found. It does not replace
reading fable/REPORT.md and the diff.

Example:
    python3 post_run_report.py --project ~/code/shop --out /tmp/review.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# Always treated as protected in the review, whatever the config says now,
# because these files define the run.
CORE_PROTECTED = [
    ".claude/settings.json", ".claude/settings.local.json", ".claude/hooks/**",
    "fable/handoff.json", "fable/MISSION.md", "fable/OPERATING_RULES.md", "fable/launch.py",
]

# Added lines that skip tests or silence checks.
WEAKENING = [
    (re.compile(r"@pytest\.mark\.(?:skip|skipif|xfail)|\bpytest\.skip\(|@unittest\.skip|\bskipTest\(|\bSkipTest\b"), "skips a test"),
    (re.compile(r"\b(?:it|test|describe|context)\.(?:skip|only)\(|\bx(?:it|test|describe)\("), "skips a test"),
    (re.compile(r"@Disabled\b|@Ignore\b|\bt\.Skip(?:f|Now)?\("), "skips a test"),
    (re.compile(r"#\s*type:\s*ignore|@ts-ignore|@ts-nocheck|eslint-disable|#\s*noqa\b|pragma:\s*no cover"), "silences a check"),
    (re.compile(r"--no-verify\b"), "bypasses git hooks"),
]
TEST_FILE = re.compile(
    r"(?:^|/)(?:tests?|__tests__|specs?|\w+_tests?)/"            # in a test directory
    r"|(?:^|/)test_[^/]*$|_test\.\w+$|\.(?:test|spec)\.\w+$"     # test_x.py, x_test.go, x.spec.ts
    r"|Tests?\.\w+$|_spec\.\w+$",                                # XTest.java, x_spec.rb
)


# --------------------------------------------------------------- helpers

def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def git(project, *args):
    try:
        return subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, errors="replace")
    except OSError:
        return subprocess.CompletedProcess(args, 127, "", "git is not installed")


def run_shell(command, project, timeout):
    """Run a shell command. Returns (exit code or None on timeout, output, seconds)."""
    started = time.time()
    options = {"start_new_session": True} if hasattr(os, "killpg") else {}
    process = subprocess.Popen(
        command, shell=True, cwd=project, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", **options
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        code = process.returncode
    except subprocess.TimeoutExpired:
        if hasattr(os, "killpg"):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
        else:
            process.kill()
        output, _ = process.communicate()
        code = None
    return code, output, round(time.time() - started, 1)


def protected_regexes(patterns):
    """Compile gitignore-style globs the same way .claude/hooks/fable_guard.py does."""
    compiled = []
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        anchored = "/" in pattern.strip().rstrip("/")
        core = pattern.strip().strip("/")
        while core.endswith("/**"):
            core = core[:-3]
        if not core:
            continue
        body, i = "", 0
        while i < len(core):
            if core.startswith("**/", i):
                body, i = body + "(?:.*/)?", i + 3
            elif core.startswith("**", i):
                body, i = body + ".*", i + 2
            elif core[i] == "*":
                body, i = body + "[^/]*", i + 1
            elif core[i] == "?":
                body, i = body + "[^/]", i + 1
            else:
                body, i = body + re.escape(core[i]), i + 1
        compiled.append(re.compile("^" + ("" if anchored else "(?:.*/)?") + body + "(?:/.*)?$", re.IGNORECASE))
    return compiled


def tasks(state_text):
    """Return (done, open) task texts from the ledger, skipping code fences."""
    done, still_open, in_fence = [], [], False
    for line in (state_text or "").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        found = re.match(r"^\s*[-*+]\s+\[( |x|X)\]\s+(.*)$", line)
        if found and not in_fence:
            (still_open if found.group(1) == " " else done).append(found.group(2).strip())
    return done, still_open


def section_body(text, title):
    """Text under the "## title" heading, without HTML comments, or ""."""
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.DOTALL)
    found = re.search(r"(?ms)^##\s+%s\s*$(.*?)(?=^##\s|\Z)" % re.escape(title), text)
    return found.group(1).strip() if found else ""


def quote(text, limit=40):
    lines = text.strip().splitlines()
    shown = ["> " + line for line in lines[:limit]]
    if len(lines) > limit:
        shown.append("> ... (%d more lines)" % (len(lines) - limit))
    return shown


def weakened_lines(diff_text):
    """Added lines in a unified diff that skip tests or silence checks: (file, line, what, text)."""
    found, path, number = [], None, 0
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            start = re.search(r"\+(\d+)", line)
            number = int(start.group(1)) if start else 0
        elif line.startswith("+") and path:
            if not path.startswith("fable/"):
                for regex, what in WEAKENING:
                    if regex.search(line[1:]):
                        found.append((path, number, what, line[1:].strip()[:120]))
                        break
            number += 1
    return found


# --------------------------------------------------------------- main

STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "into", "add", "make", "is", "are", "to", "of", "in",
             "on", "a", "an", "be", "it", "by", "as", "or", "all", "its", "when", "test", "tests", "check", "full", "passes", "written"}


def words_of(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in STOPWORDS}


def task_evidence(done, commit_subjects, changed_paths):
    """For each checked task, the commits or changed files whose words overlap with it.

    A checked box is the model's claim; a commit or a change that matches the task
    is evidence. A task with neither is listed as unproven, for a person to look at.
    """
    rows = []
    paths_words = [(path, words_of(path.replace("/", " ").replace("_", " ").replace(".", " "))) for path in changed_paths]
    for task in done:
        if re.match(r"^Full verify command passes", task):
            continue  # proven by the verify run above
        want = words_of(re.sub(r"\(check:.*?\)", "", task))
        hits = [c for c in commit_subjects if len(want & words_of(c)) >= min(2, len(want))]
        files = [p for p, w in paths_words if want & w]
        rows.append({"task": task, "commits": hits[:3], "files": files[:3], "proven": bool(hits or files)})
    return rows


GUARD_RULE = re.compile(r"(?:rule '([^']+)'|pattern `([^`]+)`|forbidden pattern /(.+?)/|That is protected: it matches '([^']+)'|protected \(rule '([^']+)'\))")


def guard_blocks(run_dir):
    """Count guard blocks per rule from the launcher's transcripts."""
    counts = {}
    for path in sorted(run_dir.glob("transcript-*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "handoff guard" not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            content = (event.get("message") or {}).get("content") if isinstance(event, dict) else None
            for block in content if isinstance(content, list) else []:
                text = block.get("content") if isinstance(block, dict) and block.get("type") == "tool_result" else None
                text = json.dumps(text) if not isinstance(text, str) else text
                if text and "handoff guard" in text:
                    found = GUARD_RULE.search(text)
                    rule = next((g for g in found.groups() if g), "unknown rule") if found else "unknown rule"
                    counts[rule] = counts.get(rule, 0) + 1
    return counts


def run_conversation(fable):
    """The run's own transcripts read through conversation_context.py, or None without jq or transcripts."""
    transcripts = sorted((fable / ".run").glob("transcript-*.jsonl"))
    script = Path(__file__).resolve().parent / "conversation_context.py"
    if not transcripts or not shutil.which("jq") or not script.exists():
        return None
    proc = subprocess.run([sys.executable, str(script), "--project", str(fable.parent), "--json", "--no-write",
                           "--logs", *map(str, transcripts)], capture_output=True, text=True)
    try:
        return json.loads(proc.stdout) if proc.returncode == 0 else None
    except ValueError:
        return None


def lessons_for_next_run(project, fable, blocks, problems, still_open, unproven, conversation=None):
    """Concrete proposals for the next run. Nothing is applied: preflight reads this file
    and offers each proposal as a trap or an open question in the next spec."""
    proposals = []
    for rule, n in sorted(blocks.items(), key=lambda kv: -kv[1]):
        if n >= 3:
            proposals.append({"kind": "question", "text": "The guard blocked %d tool calls with the rule '%s'. If those calls were legitimate, narrow the rule in fable/handoff.json; if not, say in the mission why the rule exists." % (n, rule), "source": "fable/.run/transcript-*.jsonl"})
    names = {name for name, _ in problems}
    if "gate" in names:
        proposals.append({"kind": "question", "text": "The stop gate gave up because the run stopped repeatedly without progress. Is the Done section checkable in this environment, and does the verify command pass when the work is complete?", "source": "fable/.run/stop_gate_exhausted.txt"})
    if "blocker" in names:
        blocked = (read_text(fable / "BLOCKED.md") or "").strip().splitlines()
        proposals.append({"kind": "question", "text": "The previous run stopped on a blocker: %s" % (blocked[0][:200] if blocked else "see fable/BLOCKED.md"), "source": "fable/BLOCKED.md"})
    for task in still_open[:10]:
        proposals.append({"kind": "trap", "text": "The previous run did not finish the task: %s" % task[:200], "source": "fable/STATE.md"})
    for row in unproven[:10]:
        proposals.append({"kind": "question", "text": "The previous run checked off '%s' but no commit or changed file matches it. Was it really done?" % row["task"][:160], "source": "fable/STATE.md"})
    if "weakened" in names or "deleted" in names:
        proposals.append({"kind": "trap", "text": "The previous run weakened or deleted tests to get them to pass.", "instead": "Protect the test directories in protected_paths and fix the code instead.", "source": "post_run_report"})
    for issue in (conversation or {}).get("issues", []):
        if issue.get("source") == "failing output" and issue.get("count", 1) >= 2:
            proposals.append({"kind": "trap", "text": "The previous run hit the same failure %d times: %s" % (issue["count"], issue["text"][:200]),
                              "instead": None, "source": "fable/.run transcripts" + (" (rerun: %s)" % issue["command"] if issue.get("command") else "")})
    for name in ("Made during the run", "Left for the owner"):
        for line in section_body(read_text(fable / "DECISIONS.md") or "", name).splitlines():
            if line.strip().startswith(("-", "*")):
                kind = "decision" if name == "Made during the run" else "question"
                proposals.append({"kind": kind, "text": line.strip().lstrip("-* ").strip()[:240], "source": "fable/DECISIONS.md (%s)" % name})
    return proposals


def main():
    parser = argparse.ArgumentParser(
        description="Review a project after an unattended run. Prints a Markdown review with a verdict; exit 0 only when the verdict is clean.",
        epilog="A clean verdict does not replace reading fable/REPORT.md and the diff.",
    )
    parser.add_argument("--project", required=True, help="path to the project root")
    parser.add_argument("--out", metavar="FILE", help="also write the review to FILE (choose a place outside the project, or under fable/.run/)")
    parser.add_argument("--skip-verify", action="store_true", help="do not run the verify command again")
    args = parser.parse_args()

    project = Path(args.project).expanduser().resolve()
    fable = project / "fable"
    config = load_json(fable / "handoff.json", None)
    if not isinstance(config, dict):
        sys.stderr.write("post_run_report: %s has no readable fable/handoff.json, so there is no handoff run to review here.\n" % project)
        return 2

    problems = []  # (short name, one sentence)
    body = []      # Markdown lines after the verdict

    # State of the tree, taken before the verify command can add files to it.
    status_lines = [line for line in git(project, "status", "--porcelain").stdout.splitlines() if line.strip()]
    readiness = load_json(fable / ".run" / "readiness.json", {})
    base = readiness.get("base_commit") if isinstance(readiness, dict) else None
    head = git(project, "rev-parse", "--short", "HEAD").stdout.strip()

    # Verify
    command = str(config.get("verify_command") or "").strip()
    body += ["## Verify", ""]
    if args.skip_verify:
        body += ["Command: `%s`" % command, "Result: not run (--skip-verify)."]
    elif not command:
        problems.append(("verify", "no verify command is configured, so nothing proves the result"))
        body += ["No verify command in fable/handoff.json."]
    else:
        timeout = config.get("verify_timeout_seconds") or 1800
        code, output, seconds = run_shell(command, project, timeout)
        body += ["Command: `%s`" % command]
        if code == 0:
            body += ["Result: passed (exit 0, %s s)." % seconds]
        else:
            result = "timed out after %s s" % timeout if code is None else "exit %d" % code
            problems.append(("verify", "the verify command fails (%s)" % result))
            body += ["Result: failed (%s, %s s). Last lines of output:" % (result, seconds), "", "```"]
            body += output.strip().splitlines()[-25:] + ["```"]
    body.append("")

    # Ledger
    state = read_text(fable / "STATE.md")
    done, still_open = tasks(state)
    body += ["## Ledger", ""]
    if state is None:
        problems.append(("task", "the task ledger fable/STATE.md is missing"))
        body += ["fable/STATE.md is missing."]
    else:
        body += ["%d task(s) done, %d open." % (len(done), len(still_open))]
        if still_open:
            problems.append(("task", "%d unchecked task(s) in fable/STATE.md" % len(still_open)))
            body += ["", "Open tasks:"] + ["- " + task for task in still_open]
    body.append("")

    # Changes
    body += ["## Changes since the readiness check", ""]
    if not base:
        problems.append(("diff", "no base commit is recorded in fable/.run/readiness.json, so the changes could not be compared"))
        body += ["No base commit recorded. The diff checks (deleted tests, weakened checks, protected files) were not run."]
    elif git(project, "merge-base", "--is-ancestor", base, "HEAD").returncode != 0:
        problems.append(("history", "the base commit %s is not an ancestor of HEAD, so history was rewritten or the branch changed" % base[:10]))
        body += ["Base commit %s is not an ancestor of HEAD. The diff checks were not run." % base[:10]]
    else:
        changed = []  # (status letter, path)
        for line in git(project, "diff", "--name-status", "--no-renames", base).stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                changed.append((parts[0][:1], parts[-1]))
        commits = git(project, "log", "--oneline", "%s..HEAD" % base).stdout.splitlines()
        body += ["Base commit %s, head %s: %d commit(s), %d file(s) changed." % (base[:10], head, len(commits), len(changed)), ""]
        names = {"A": "added", "M": "modified", "D": "deleted", "T": "type changed"}
        body += ["- %s: `%s`" % (names.get(letter, letter), path) for letter, path in changed[:200]]
        if len(changed) > 200:
            body += ["- ... and %d more" % (len(changed) - 200)]
        if commits:
            body += ["", "Commits:"] + ["- " + line for line in commits[:50]]

        deleted_tests = [path for letter, path in changed if letter == "D" and TEST_FILE.search(path)]
        if deleted_tests:
            problems.append(("deleted", "%d test file(s) were deleted: %s" % (len(deleted_tests), ", ".join(deleted_tests[:10]))))

        weakened = weakened_lines(git(project, "diff", "-U0", "--no-renames", base).stdout)
        if weakened:
            problems.append(("weakened", "%d added line(s) skip tests or silence checks (weakened checks)" % len(weakened)))
            body += ["", "Added lines that weaken checks:"]
            body += ["- `%s:%d` %s: `%s`" % item for item in weakened[:40]]

        regexes = protected_regexes(list(config.get("protected_paths") or []) + CORE_PROTECTED)
        touched = [path for _, path in changed if any(regex.match(path) for regex in regexes)]
        if touched:
            problems.append(("protected", "protected file(s) were changed: %s" % ", ".join(touched[:10])))
    body.append("")

    if status_lines:
        problems.append(("uncommitted", "%d uncommitted change(s) in the working tree" % len(status_lines)))
        body += ["## Uncommitted changes", "", "```"] + status_lines[:40] + ["```", ""]

    # Evidence for each checked task
    evidence = []
    if base and git(project, "merge-base", "--is-ancestor", base, "HEAD").returncode == 0:
        subjects = git(project, "log", "--format=%s", "%s..HEAD" % base).stdout.splitlines()
        paths = git(project, "diff", "--name-only", "--no-renames", base).stdout.split()
        evidence = task_evidence(done, subjects, paths)
    unproven = [row for row in evidence if not row["proven"]]
    if evidence:
        body += ["## Evidence for checked tasks", "",
                 "%d of %d checked task(s) match a commit or a changed file. A checked box with no match is not wrong by itself, but read it." % (len(evidence) - len(unproven), len(evidence)), ""]
        for row in evidence:
            if row["proven"]:
                body.append("- proven: %s (%s)" % (row["task"], "; ".join(row["commits"] or ["`%s`" % f for f in row["files"]])))
            else:
                body.append("- unproven: %s" % row["task"])
        body.append("")

    # Gate, blocker, report
    exhausted = read_text(fable / ".run" / "stop_gate_exhausted.txt")
    if exhausted is not None:
        problems.append(("gate", "the stop gate gave up and let the run stop unfinished"))
        body += ["## Stop gate", "", "fable/.run/stop_gate_exhausted.txt says:", ""] + quote(exhausted) + [""]
    blocker = read_text(fable / "BLOCKED.md")
    if blocker and blocker.strip():
        problems.append(("blocker", "the run recorded a blocker in fable/BLOCKED.md"))
        body += ["## Blocker", "", "fable/BLOCKED.md says:", ""] + quote(blocker) + [""]
    report = read_text(fable / "REPORT.md")
    if not report or not report.strip():
        problems.append(("report", "fable/REPORT.md is missing or empty"))

    # Launches
    log = load_json(fable / ".run" / "launch_log.json", [])
    if isinstance(log, list) and log:
        body += ["## Launches", ""]
        for entry in log:
            if isinstance(entry, dict):
                budget = entry.get("budget_usd")
                body.append("- attempt %s (%s): exit %s after %s s%s%s%s" % (
                    entry.get("attempt"), entry.get("mode"), entry.get("exit_code"), entry.get("seconds"),
                    "" if budget is None else ", budget $%.2f" % budget,
                    ", finished" if entry.get("finished") else "",
                    ", blocked" if entry.get("blocked") else "",
                ))
        body.append("")

    # What the model wrote down for the owner
    decisions = read_text(fable / "DECISIONS.md")
    for title in ("Made during the run", "Left for the owner"):
        text = section_body(decisions, title)
        body += ["## %s (from fable/DECISIONS.md)" % title, ""] + (quote(text, 60) if text else ["Nothing recorded."]) + [""]

    # Lessons for the next run
    blocks = guard_blocks(fable / ".run")
    if blocks:
        body += ["## Guard blocks", ""] + ["- %d x `%s`" % (n, rule) for rule, n in sorted(blocks.items(), key=lambda kv: -kv[1])] + [""]
    conversation = run_conversation(fable)
    if conversation:
        issues = conversation.get("issues", [])
        body += ["## What the run's conversation shows", "",
                 "From the run's transcripts: %d issue(s), %d success(es), %d fork(s), %d subagent(s), %d compaction(s)." % (
                     len(issues), len(conversation.get("successes", [])), len(conversation.get("forks", [])),
                     len(conversation.get("subagents", [])), conversation.get("compactions", 0)), ""]
        for issue in sorted(issues, key=lambda i: -i.get("count", 1))[:8]:
            body.append("- %s%s: %s%s" % (issue["source"], " x%d" % issue["count"] if issue.get("count", 1) > 1 else "", issue["text"],
                                         " (rerun: `%s`)" % issue["command"] if issue.get("command") else ""))
        body.append("")
    proposals = lessons_for_next_run(project, fable, blocks, problems, still_open, unproven, conversation)
    (fable / ".run").mkdir(parents=True, exist_ok=True)
    (fable / ".run" / "lessons.json").write_text(json.dumps({"head": head, "proposals": proposals}, indent=2) + "\n", encoding="utf-8")
    if proposals:
        body += ["## Proposed for the next run", "",
                 "Written to fable/.run/lessons.json. Preflight offers each one in the next spec as a decision, trap or open question; nothing is applied on its own.", ""]
        body += ["- %s: %s" % (p["kind"], p["text"]) for p in proposals[:30]] + [""]

    body += ["## Next", ""]
    if report and report.strip():
        body.append("- Read fable/REPORT.md. It is the model's own account of the run.")
    if base:
        body.append("- Read the diff: `git diff %s..HEAD`" % base[:10])
    if problems:
        body.append("- Resolve each problem above before you merge. If you relaunch, rerun the readiness check first.")
    else:
        body.append("- If the diff matches the report, merge the run branch.")

    if problems:
        verdict = "Verdict: NEEDS REVIEW. Reasons: %s." % ", ".join(dict.fromkeys(name for name, _ in problems))
    elif args.skip_verify:
        verdict = "Verdict: CLEAN, with the verify command not re-run."
    else:
        verdict = "Verdict: CLEAN. No sign of an unfinished or weakened run was found."
    lines = ["# Post-run review", "", verdict, "", "Project: `%s`" % project, ""]
    if problems:
        lines += ["## Problems", ""] + ["%d. **%s**: %s." % (i, name, text) for i, (name, text) in enumerate(problems, start=1)] + [""]
    text = "\n".join(lines + body) + "\n"

    sys.stdout.write(text)
    if args.out:
        Path(args.out).expanduser().write_text(text, encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
