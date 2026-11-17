#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Prove that a handoff package is ready for an unattended run.

Runs every check, prints one row per check (PASS, WARN or FAIL) and exits 0
only when no row is FAIL. The result is saved to fable/.run/readiness.json
together with a hash of the mission, the operating rules and the config.
fable/launch.py refuses to start unless that record says ok and the hash
still matches, so run this again after any change to those three files.

The check runs the verify command once to record the baseline. Before the
run that command is expected to fail, because the mission is not done yet.

Example:
    uv run --script readiness_check.py --project ~/code/shop --extra /path/to/global-instructions.md
"""
from __future__ import annotations

# Every script in this skill runs under uv, never a bare interpreter.
UV_SCRIPT = ["uv", "run", "--quiet", "--script"]

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

REQUIRED_KEYS = [
    "version", "model", "effort", "permission_mode", "branch", "verify_command",
    "verify_timeout_seconds", "ownership", "protected_paths", "blocked_bash_patterns",
    "allow_writes_outside_project", "max_stop_blocks", "max_total_stop_blocks",
    "max_relaunches", "max_budget_usd", "max_turns", "audit_accept", "extra_cli_args",
]
HASHED_FILES = ["MISSION.md", "OPERATING_RULES.md", "handoff.json"]
MISSION_SECTIONS = ["Job", "Why", "Guardrails", "Decisions", "Done"]
RELEASE_BRANCHES = {"main", "master", "production", "prod", "release"}
HOOKS = [
    ("fable_guard.py", "PreToolUse"),
    ("fable_stop_gate.py", "Stop"),
    ("fable_session_context.py", "SessionStart"),
]
GUARDED_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit"]

# Wording in a mission that assumes somebody is there to answer.
HUMAN_WORDING = [
    r"\bask (?:me|us|the user|the owner)\b",
    r"\bask (?:first|before)\b",
    r"\bcheck (?:in )?with (?:me|us|the user|the owner)\b",
    r"\bconfirm with (?:me|us|the user|the owner)\b",
    r"\bwait(?:ing)? for (?:my|our|the owner'?s?|the user'?s?|human|a human'?s?|further)? ?(?:approval|confirmation|sign[- ]?off|go[- ]ahead|reply|answer|input|feedback|instructions|review)\b",
    r"\b(?:get|with|after|until|without) my (?:approval|permission|sign[- ]?off|ok|okay|confirmation)\b",
    r"\b(?:stop|pause) and (?:ask|wait)\b",
    r"\blet me know\b",
    r"\bi(?:'ll| will) (?:review|check|confirm|answer|reply|decide|approve)\b",
]
NEGATION = re.compile(r"(?:\bnot\b|n't\b|\bnever\b|\bnobody\b|\bno one\b|\bcannot\b|\binstead of\b|\brather than\b|\bwithout\b)[^.;\n]{0,30}$", re.IGNORECASE)

# "never" and "always" used as an order: at the start of a list item or a
# sentence, or after must, should or you. Fable 5.2 applies such a word to
# every case, so each one deserves a second look. In "has never seen" or
# "was always slow" the word describes something, and that is not matched.
# (?i:...) ignores case for the part inside the brackets only.
ABSOLUTE_DIRECTIVES = [
    r"^\s*(?:[-*+]|\d+[.)])\s+[*_]*(?i:never|always)\b",  # opens a list item
    r"^\s*[*_]*(?:Never|Always|NEVER|ALWAYS)\b",          # opens a line with a capital, so it opens a sentence
    r"[.!?:]\s+[*_]*(?i:never|always)\b",                 # opens a later sentence on the line
    r"(?i:\b(?:must|should|you)\s+(?:never|always)\b)",   # "must never", "should always", "you always"
]

SECRET_NAMES = {"id_rsa", "id_ed25519", "credentials.json"}
SECRET_SUFFIXES = (".pem", ".p12")
ENV_EXAMPLES = (".example", ".sample", ".template")


# --------------------------------------------------------------- helpers

def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def without_comments(text):
    """Markdown with HTML comments removed. Comments hold notes, not content."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def section_body(text, title):
    """Text under the heading `title`, up to the next heading of the same or a higher level.

    Returns None when the heading is missing.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        found = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if found and found.group(2).strip().lower() == title.lower():
            level = len(found.group(1))
            body = []
            for later in lines[index + 1:]:
                heading = re.match(r"^(#{1,6})\s", later)
                if heading and len(heading.group(1)) <= level:
                    break
                body.append(later)
            return "\n".join(body).strip()
    return None


def git(project, *args):
    try:
        return subprocess.run(["git", *args], cwd=project, capture_output=True, text=True)
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


def run_hook(project, name, payload, dry_run=False):
    """Run one installed hook the way Claude Code would. Returns the finished process, or None."""
    if not (project / ".claude" / "hooks" / name).is_file():
        return None
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
    if dry_run:
        env["FABLE_GATE_DRY_RUN"] = "1"
    try:
        return subprocess.run(
            [*UV_SCRIPT, str(project / ".claude" / "hooks" / name)],
            input=json.dumps(payload), capture_output=True, text=True, cwd=project, env=env, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def package_hash(project):
    """SHA-256 over the three files that define the run. Must match fable/launch.py."""
    digest = hashlib.sha256()
    for name in HASHED_FILES:
        digest.update(name.encode("utf-8"))
        path = project / "fable" / name
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def open_task_count(state_text):
    count, in_fence = 0, False
    for line in state_text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        elif not in_fence and re.match(r"^\s*[-*+]\s+\[ \]\s+\S", line):
            count += 1
    return count


def short_list(items, limit=5):
    items = list(items)
    extra = "" if len(items) <= limit else " and %d more" % (len(items) - limit)
    return ", ".join(items[:limit]) + extra


# --------------------------------------------------------------- checks
# Each check returns a list of (status, check name, detail) rows.

def check_config(project):
    path = project / "fable" / "handoff.json"
    text = read_text(path)
    if text is None:
        return {}, [("FAIL", "config", "fable/handoff.json is missing. Run init_handoff.py --project %s first." % project)]
    try:
        config = json.loads(text)
    except ValueError as error:
        return {}, [("FAIL", "config", "fable/handoff.json is not valid JSON: %s" % error)]
    if not isinstance(config, dict):
        return {}, [("FAIL", "config", "fable/handoff.json must hold a JSON object.")]
    problems = []
    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        problems.append("missing keys: %s (see the handoff.json table in references/claude-code-setup.md)" % ", ".join(missing))
    for key in ("protected_paths", "blocked_bash_patterns", "audit_accept", "extra_cli_args"):
        if key in config and not isinstance(config[key], list):
            problems.append("%s must be a list" % key)
    patterns = config.get("blocked_bash_patterns")
    for pattern in patterns if isinstance(patterns, list) else []:
        try:
            re.compile(pattern)
        except (re.error, TypeError) as error:
            problems.append("invalid regex %r in blocked_bash_patterns: %s" % (pattern, error))
    if problems:
        return config, [("FAIL", "config", "; ".join(problems))]
    return config, [("PASS", "config", "fable/handoff.json has every key and its patterns compile")]


def check_settings_rows(config):
    """Rows that warn about risky but allowed settings."""
    rows = []
    model = str(config.get("model") or "")
    if model in ("fable", "opus", "sonnet", "haiku"):
        rows.append(("WARN", "model", "model is the alias '%s'. On the Claude API an alias can resolve to an older version (the `fable` alias to Fable 5.1 unless ANTHROPIC_DEFAULT_FABLE_MODEL is set). Pin the full ID, such as claude-fable-5-2." % model))
    elif model:
        rows.append(("PASS", "model", model))
    effort = config.get("effort")
    if effort == "high":
        rows.append(("PASS", "effort", "high"))
    elif effort in ("low", "medium"):
        rows.append(("WARN", "effort", "effort is %s. Below high the model is more likely to stop early on long work. Use high for an unattended run." % effort))
    else:
        rows.append(("WARN", "effort", "effort is %s. Above high costs many more tokens for a small gain. Use it only where a gain was measured." % effort))

    mode = config.get("permission_mode")
    if mode == "bypassPermissions":
        rows.append(("WARN", "permission mode", "bypassPermissions runs everything without review. Use it only inside a container or VM that holds nothing you cannot lose."))
    elif mode in ("acceptEdits", "dontAsk"):
        rows.append(("WARN", "permission mode", "%s denies shell commands that no allow rule covers. Add narrow allow rules to .claude/settings.json for the verify command, the package manager and git commit." % mode))
    else:
        rows.append(("PASS", "permission mode", str(mode)))

    if not isinstance(config.get("max_budget_usd"), (int, float)):
        rows.append(("WARN", "budget", "max_budget_usd is not set, so nothing caps what the run spends. Set it in fable/handoff.json."))
    else:
        rows.append(("PASS", "budget", "capped at $%.2f across all launches" % config["max_budget_usd"]))
    return rows


def check_mission(project, config):
    raw = read_text(project / "fable" / "MISSION.md")
    if raw is None:
        return [("FAIL", "mission", "fable/MISSION.md is missing.")]
    text = without_comments(raw)
    problems = []
    if "{{FILL" in text:
        problems.append("%d {{FILL}} marker(s) left to replace" % text.count("{{FILL"))
    bodies = {}
    for title in MISSION_SECTIONS:
        body = section_body(text, title)
        bodies[title] = body
        if body is None:
            problems.append('no "## %s" section' % title)
        elif not re.sub(r"(?m)^#.*$", "", body).strip():
            problems.append('the "%s" section is empty' % title)
    for title, minimum in (("Job", 40), ("Why", 20)):
        words = len((bodies.get(title) or "").split())
        if bodies.get(title) and words < minimum:
            problems.append('"%s" has %d words and needs at least %d: describe the whole %s' % (title, words, minimum, "outcome" if title == "Job" else "purpose and what matters most"))
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern in HUMAN_WORDING:
            found = re.search(pattern, line, re.IGNORECASE)
            if found and not NEGATION.search(line[:found.start()]):
                problems.append('line %d assumes a person is there ("%s"): decide it now, or make it pre-approved, forbidden or left for the owner' % (number, found.group(0)))
                break
    verify = str(config.get("verify_command") or "").strip()
    if verify and verify not in text:
        problems.append("the verify command `%s` is not quoted in the mission: put it in the Done section exactly as in fable/handoff.json" % verify)
    if problems:
        return [("FAIL", "mission", "; ".join(problems))]
    return [("PASS", "mission", "all sections present, Job %d words, Why %d words" % (len(bodies["Job"].split()), len(bodies["Why"].split())))]


def check_mission_wording(project):
    """A WARN row that quotes each mission line using never or always as an order."""
    raw = read_text(project / "fable" / "MISSION.md")
    if raw is None:
        return []  # the mission row already reports the missing file
    quoted = []
    for number, line in enumerate(without_comments(raw).splitlines(), start=1):
        if any(re.search(pattern, line) for pattern in ABSOLUTE_DIRECTIVES):
            quoted.append('line %d "%s"' % (number, line.strip()))
    if quoted:
        detail = (
            "%d line(s) use never or always as an order: %s. The model applies such a word to every case, "
            "including the ones you did not think of. Say when the rule applies and why, or keep the line if it truly has no exception."
            % (len(quoted), "; ".join(quoted))
        )
        return [("WARN", "mission wording", detail)]
    return [("PASS", "mission wording", "never and always are not used as orders")]


def check_operating_rules(project):
    text = read_text(project / "fable" / "OPERATING_RULES.md")
    if text is None:
        return [("FAIL", "operating rules", "fable/OPERATING_RULES.md is missing. Run init_handoff.py again to restore it.")]
    if "{{" in text:
        return [("FAIL", "operating rules", "fable/OPERATING_RULES.md still holds a {{...}} marker. Create it with init_handoff.py, which fills the marker in.")]
    return [("PASS", "operating rules", "present, no markers")]


def check_ledger(project):
    raw = read_text(project / "fable" / "STATE.md")
    if raw is None:
        return 0, [("FAIL", "ledger", "fable/STATE.md is missing.")]
    text = without_comments(raw)
    count = open_task_count(text)
    if "{{FILL" in text:
        return count, [("FAIL", "ledger", "fable/STATE.md has %d {{FILL}} marker(s) left to replace" % text.count("{{FILL"))]
    if count == 0:
        return count, [("FAIL", "ledger", 'fable/STATE.md has no unchecked "- [ ]" task. Seed the task list from the mission, or the run has nothing to do.')]
    return count, [("PASS", "ledger", "%d open task(s)" % count)]


def check_decisions(project):
    raw = read_text(project / "fable" / "DECISIONS.md")
    if raw is None:
        return [("FAIL", "decisions", "fable/DECISIONS.md is missing.")]
    text = without_comments(raw)
    if "{{FILL" in text:
        return [("FAIL", "decisions", "fable/DECISIONS.md has %d {{FILL}} marker(s) left to replace" % text.count("{{FILL"))]
    body = section_body(text, "Open questions for the owner")
    if body is None:
        return [("FAIL", "decisions", 'fable/DECISIONS.md has no "## Open questions for the owner" section.')]
    if body.strip() != "None.":
        return [("FAIL", "decisions", '"Open questions for the owner" must read "None." Put each open question to the owner now and move the answer to "Made before the run", because nobody can answer during the run.')]
    return [("PASS", "decisions", "no open questions")]


def load_questions_module(project):
    """The project's fable/questions.py, or the skill's copy when init has not installed it yet."""
    import importlib.util
    path = project / "fable" / "questions.py"
    if not path.exists():
        path = SCRIPTS.parent / "assets" / "templates" / "questions.py"
    spec = importlib.util.spec_from_file_location("fable_questions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_questions(project, config):
    """Every open question passes the judgment test; answered ones are imported."""
    questions = load_questions_module(project)
    rows = []
    if not isinstance(config.get("evidence_ladder"), list) or not config.get("evidence_ladder"):
        rows.append(("WARN", "evidence ladder", "fable/handoff.json has no evidence_ladder, so the default six rungs apply. Name where each rung lives in this project."))
    try:
        records = questions.system(project, config).load()
    except Exception as error:
        return rows + [("FAIL", "questions", "the question system in fable/handoff.json could not be read: %s" % str(error)[:200])]
    rungs = questions.rung_names(config)
    open_q = [q for q in records if q.get("status", "open") == "open"]
    refused = [(q, questions.record_problems(q, rungs)) for q in open_q]
    refused = [(q, p) for q, p in refused if p]
    answered = [q.get("topic") for q in records if q.get("status") == "answered"]
    if refused:
        detail = "; ".join('"%s": %s' % (q.get("question", "")[:60], p[0]) for q, p in refused[:3])
        return rows + [("FAIL", "questions", "%d open question(s) fail the judgment test: %s. Search the evidence ladder; settle what the evidence decides (questions.py settle) and record the full search for the rest." % (len(refused), detail))]
    if answered:
        return rows + [("FAIL", "questions", "the owner answered %d question(s) not imported yet (%s). Run: uv run --script fable/questions.py import" % (len(answered), ", ".join(answered[:5])))]
    if open_q:
        return rows + [("WARN", "questions", "%d judgment call(s) wait on the owner, each with a full record. Tasks that depend on them must be parked; the rest of the run continues." % len(open_q))]
    return rows + [("PASS", "questions", "no open questions in the question system")]


def check_detective(project, config):
    """The function registry is complete, every case is valid, and adjudication is calibrated before it settles anything."""
    import importlib.util
    path = project / "fable" / "detective.py"
    if not path.exists():
        path = SCRIPTS.parent / "assets" / "templates" / "detective.py"
    spec = importlib.util.spec_from_file_location("fable_detective", path)
    dm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dm)
    problems = dm.registry_problems(config, project)
    if problems:
        return [("FAIL", "detective functions", "%d problem(s): %s. The registry must be this project's own, derived from analysing it (references/detective-standard.md, section 7)." % (len(problems), "; ".join(problems[:4])))]
    rows = [("PASS", "detective functions", "%d registered: %s" % (len(dm.registry(config)), short_list(dm.registry(config))))]
    cases = dm.load_cases(project)
    if not cases:
        return rows
    results = [(c, dm.verdict(c, config, project)) for c in cases]
    invalid = [(c, r) for c, r in results if r["verdict"] == "invalid"]
    if invalid:
        return rows + [("FAIL", "cases", "%d case(s) rest on unregistered, planned or unsourced evidence: %s" % (len(invalid), invalid[0][1]["why"][:200]))]
    adjudicated = [c for c, r in results if r["verdict"] == "settled by adjudication"]
    _, basis = dm.threshold(project, config)
    if adjudicated and basis.startswith("uncalibrated"):
        return rows + [("WARN", "cases", "%d case(s) settled by adjudication against an uncalibrated threshold. Run detective_backtest.py on decided cases with --write-calibration." % len(adjudicated))]
    counts = {}
    for _, r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return rows + [("PASS", "cases", ", ".join("%d %s" % (n, v) for v, n in sorted(counts.items())))]


def check_launch_requires(project, config):
    """What the mission depends on: functions that must be built before launch,
    functions the run builds as its first tasks, and files that must exist."""
    req = config.get("launch_requires") or {}
    if not req:
        return []
    funcs = {f.get("name"): f for f in config.get("detective_functions") or [] if isinstance(f, dict)}
    problems = []
    for name in req.get("functions_built") or []:
        f = funcs.get(name)
        if f is None:
            problems.append("the mission depends on the function '%s', which is not registered" % name)
        elif f.get("status") != "built":
            problems.append("the mission depends on '%s', which is only %s; build it before launch" % (name, f.get("status")))
    state = (project / "fable" / "STATE.md").read_text(encoding="utf-8", errors="replace").lower() if (project / "fable" / "STATE.md").exists() else ""
    tasks = [line for line in state.splitlines() if line.strip().startswith("- [")]
    for name in req.get("functions_first_tasks") or []:
        if name not in funcs:
            problems.append("the run must build '%s', which is not registered" % name)
        elif funcs[name].get("status") != "built" and not any(name.lower() in t for t in tasks):
            problems.append("'%s' is planned and no task in fable/STATE.md builds it; add it as one of the first tasks" % name)
    for rel in req.get("files") or []:
        path = Path(os.path.expanduser(rel))
        if not (path if path.is_absolute() else project / rel).exists():
            problems.append("the mission starts from %s, which does not exist yet" % rel)
    if problems:
        return [("FAIL", "launch requires", "%d problem(s): %s" % (len(problems), "; ".join(problems)))]
    return [("PASS", "launch requires", "every function and file the mission depends on is in place or planned as a first task")]


def check_model_calls(project, config):
    """No language model call inside the calculation code (deterministic_code)."""
    if not (config.get("deterministic_code") or {}).get("paths"):
        return []
    import importlib.util
    spec = importlib.util.spec_from_file_location("fable_stop_gate_scan", SCRIPTS.parent / "assets" / "hooks" / "fable_stop_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    calls = gate.model_call_findings(str(project), config)
    if calls:
        return [("FAIL", "no model calls", "%d model call(s) in calculation code: %s. Calculations are plain, tested code; Jev only in the allowed files." % (
            len(calls), "; ".join("%s:%d" % (f, n) for f, n, _ in calls[:5])))]
    return [("PASS", "no model calls", "no language model call in the calculation code")]


def check_owner_decisions(project, config):
    """Decisions the owner must answer before launch (pre_launch_decisions), in plain words."""
    rel = config.get("pre_launch_decisions")
    if not rel:
        return []
    path = project / rel
    try:
        records = json.loads(path.read_text(encoding="utf-8")).get("open_questions", [])
    except (OSError, ValueError, AttributeError):
        return [("FAIL", "owner decisions", "%s cannot be read" % rel)]
    shape = config.get("shape")
    # A decision may name the shapes that need it ("needed_for"); other shapes launch without it.
    needed = [q for q in records if not q.get("needed_for") or shape in q["needed_for"]]
    waiting = [q.get("topic") or q.get("question") for q in needed if q.get("status", "open") == "open"]
    later = [q.get("topic") for q in records if q not in needed and q.get("status", "open") == "open"]
    if waiting:
        return [("FAIL", "owner decisions", "%d decision(s) wait on the owner: %s. Ask them in one sitting: uv run --script <skill>/scripts/decision_interview.py --project . --file %s" % (
            len(waiting), "; ".join(waiting), rel))]
    return [("PASS", "owner decisions", "%d answered%s" % (len(needed) - len(waiting) if needed else 0,
            "; waiting for a later shape: %s" % "; ".join(later) if later else ""))]


def check_standards(project, config):
    """Each standards check (a named command that gates done) can run here; it may fail until the run is done."""
    rows = []
    for check in config.get("standards_checks") or []:
        name = str((check or {}).get("name") or "?")
        command = str((check or {}).get("command") or "").strip()
        if not command:
            rows.append(("FAIL", "standards check", "'%s' names no command" % name))
            continue
        code, output, _ = run_shell(command, project, int(check.get("timeout_seconds") or 1800))
        if code is None:
            rows.append(("FAIL", "standards check", "'%s' did not finish in time" % name))
        elif cannot_run(code, output):
            cause = next((l.strip() for l in output.splitlines() if CANNOT_RUN.search(l)), (output.strip().splitlines() or [""])[-1])[:160]
            rows.append(("FAIL", "standards check", "'%s' cannot run here (%s), so it could never pass and done would never be reached" % (name, cause)))
        else:
            rows.append(("PASS", "standards check", "'%s' runs (%s now); it must pass before the run may stop" % (name, "passing" if code == 0 else "failing")))
    return rows


def check_companions(config):
    """Each companion repository exists, is on its own run branch (never a release branch) and is clean."""
    rows = []
    for c in config.get("companion_repositories") or []:
        root = Path(os.path.expanduser(str(c.get("path", ""))))
        label = "companion %s" % root.name
        if not (root / ".git").exists():
            rows.append(("FAIL", label, "%s is not a git repository on this machine" % root))
            continue
        branch = git(root, "branch", "--show-current").stdout.strip()
        wanted = str(c.get("branch") or "")
        if not wanted:
            rows.append(("FAIL", label, "no branch is named for it in companion_repositories"))
        elif branch.lower() in RELEASE_BRANCHES or branch != wanted:
            rows.append(("FAIL", label, "on %s; the run writes it only on its own branch. Switch first: git -C %s switch -c %s" % (branch or "a detached HEAD", root, wanted)))
        elif dirty_paths(root):
            rows.append(("FAIL", label, "uncommitted changes: %s. Commit them first, so the run's diff there shows only its work." % short_list(dirty_paths(root))))
        else:
            rows.append(("PASS", label, "on %s, clean; tests: %s" % (branch, c.get("test_command") or "none named")))
        if c.get("map"):
            # A preparation map that must exist for the very commit the run starts from.
            commit = git(root, "rev-parse", "--short=9", "HEAD").stdout.strip()
            pattern = str(c["map"]).replace("{commit}", commit)
            if not list(root.glob(pattern)):
                rows.append(("FAIL", label + " map", "no map for commit %s (%s). Map a clean copy at that commit first, for example with the preset's desk_map.py" % (commit, pattern)))
            else:
                rows.append(("PASS", label + " map", "mapped at commit %s" % commit))
    return rows


def check_git_branch(project, config):
    if git(project, "rev-parse", "--is-inside-work-tree").returncode != 0:
        return False, [("FAIL", "git branch", "the project is not a git repository. Run git init and commit, so that the run can be reviewed and undone.")]
    branch = git(project, "branch", "--show-current").stdout.strip()
    wanted = str(config.get("branch") or "")
    if not branch:
        return True, [("FAIL", "git branch", "HEAD is detached. Switch to the run branch: git switch -c %s" % (wanted or "fable/run-1"))]
    if branch.lower() in RELEASE_BRANCHES:
        return True, [("FAIL", "git branch", "on %s. An unattended run must not commit to a release branch. Switch first: git switch -c %s" % (branch, wanted or "fable/run-1"))]
    if wanted and branch != wanted:
        return True, [("WARN", "git branch", "on %s, but fable/handoff.json names %s. Switch branches or correct the config." % (branch, wanted))]
    return True, [("PASS", "git branch", "on " + branch)]


def dirty_paths(project):
    lines = git(project, "status", "--porcelain").stdout.splitlines()
    return [line[3:] for line in lines if line.strip()]


def check_git_clean(before, after, allow_dirty):
    left_behind = [path for path in after if path not in before]
    if before:
        detail = "uncommitted changes: %s. Commit them, so that the run starts from a known state and its diff shows only its own work." % short_list(before)
        if any(path.startswith("fable/.run") for path in before):
            detail += " Add fable/.run/ to .gitignore."
        return [("WARN" if allow_dirty else "FAIL", "git clean", detail)]
    if left_behind:
        return [("WARN" if allow_dirty else "FAIL", "git clean", "the verify command leaves files behind: %s. Add them to .gitignore, or every review will report uncommitted changes." % short_list(left_behind))]
    return [("PASS", "git clean", "nothing uncommitted")]


def check_secrets(project):
    tracked = git(project, "ls-files").stdout.splitlines()
    found = []
    for path in tracked:
        name = path.rsplit("/", 1)[-1]
        is_env = (name == ".env" or name.startswith(".env.")) and not name.endswith(ENV_EXAMPLES)
        if is_env or name in SECRET_NAMES or name.endswith(SECRET_SUFFIXES):
            found.append(path)
    if found:
        return [("FAIL", "secrets", "git tracks files that look like secrets: %s. Remove them from the index (git rm --cached), ignore them, and rotate any key that was ever pushed." % short_list(found))]
    return [("PASS", "secrets", "no secret files tracked by git")]


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

def check_verify(project, config, allow_passing):
    command = str(config.get("verify_command") or "").strip()
    baseline = {"command": command, "exit_code": None, "seconds": 0.0}
    if not command:
        return baseline, [("FAIL", "verify", "verify_command is empty. Set one shell command in fable/handoff.json that exits 0 only when the mission is complete.")]
    timeout = config.get("verify_timeout_seconds")
    timeout = timeout if isinstance(timeout, (int, float)) and timeout > 0 else 1800
    code, output, seconds = run_shell(command, project, timeout)
    baseline.update(exit_code=code, seconds=seconds)
    last_line = (output.strip().splitlines() or [""])[-1][:160]
    if code is None:
        return baseline, [("FAIL", "verify", "`%s` did not finish within %s seconds. Make it faster or raise verify_timeout_seconds." % (command, timeout))]
    if cannot_run(code, output):
        cause = next((l.strip() for l in output.splitlines() if CANNOT_RUN.search(l)), last_line)[:160]
        return baseline, [("FAIL", "verify", "`%s` cannot run here (exit %d: %s), so it can never pass and the stop gate would never release the run. Fix how it runs; for Python, run it through uv, for example `uv run pytest`." % (command, code, cause))]
    if code == 0:
        detail = "`%s` already passes, so it cannot tell a finished mission from an untouched one. Add failing tests or checks for the new work first." % command
        return baseline, [("WARN" if allow_passing else "FAIL", "verify", detail)]
    return baseline, [("PASS", "verify", "`%s` fails now (exit %d, %s s), as it should before the run" % (command, code, seconds))]


def check_hooks_installed(project):
    missing = [name for name, _ in HOOKS if not (project / ".claude" / "hooks" / name).is_file()]
    if missing:
        return [("FAIL", "hooks installed", "missing from .claude/hooks/: %s. Run init_handoff.py again; it restores missing files and leaves the rest alone." % ", ".join(missing))]
    return [("PASS", "hooks installed", "all three hooks are in .claude/hooks/")]


def check_hooks_registered(project):
    text = read_text(project / ".claude" / "settings.json")
    try:
        settings = json.loads(text or "")
        hooks = settings.get("hooks", {}) if isinstance(settings, dict) else {}
    except ValueError:
        return [("FAIL", "hooks registered", ".claude/settings.json is missing or is not valid JSON. Run init_handoff.py again.")]
    problems = []
    for name, event in HOOKS:
        groups = hooks.get(event, []) if isinstance(hooks, dict) else []
        mine = [g for g in groups if isinstance(g, dict) and name in json.dumps(g.get("hooks", []))]
        if not mine:
            problems.append("%s is not registered under %s" % (name, event))
        elif event == "PreToolUse":
            matcher = str(mine[0].get("matcher", ""))
            uncovered = [tool for tool in GUARDED_TOOLS if matcher not in ("", "*") and tool not in matcher.split("|")]
            if uncovered:
                problems.append("the guard's matcher does not cover %s" % ", ".join(uncovered))
    if problems:
        return [("FAIL", "hooks registered", "; ".join(problems) + ". Run init_handoff.py again to add what is missing to .claude/settings.json.")]
    return [("PASS", "hooks registered", "all three hooks are registered in .claude/settings.json")]


def check_guard(project, config):
    outside = str(project.parent / "fable-readiness-probe.txt")
    outside_code = 0 if config.get("allow_writes_outside_project") else 2
    cases = [
        # (what is tried, tool, tool_input, exit code a working guard gives)
        ("a write to fable/handoff.json", "Write", {"file_path": "fable/handoff.json"}, 2),
        ("an edit of fable/MISSION.md", "Edit", {"file_path": str(project / "fable" / "MISSION.md")}, 2),
        ("a write outside the project", "Write", {"file_path": outside}, outside_code),
        ("a write to fable/STATE.md", "Write", {"file_path": "fable/STATE.md"}, 0),
        ("a write to fable/DECISIONS.md", "Write", {"file_path": "fable/DECISIONS.md"}, 0),
        ("a write to fable/REPORT.md", "Write", {"file_path": "fable/REPORT.md"}, 0),
        ("a write to fable/BLOCKED.md", "Write", {"file_path": "fable/BLOCKED.md"}, 0),
        ("the command `git push --force origin HEAD`", "Bash", {"command": "git push --force origin HEAD"}, 2),
        ("the command `git status`", "Bash", {"command": "git status"}, 0),
    ]
    wrong = []
    for label, tool, tool_input, expected in cases:
        payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(project)}
        result = run_hook(project, "fable_guard.py", payload)
        if result is None:
            return [("FAIL", "guard self-test", ".claude/hooks/fable_guard.py is missing or did not finish. Run init_handoff.py again to restore it.")]
        if result.returncode != expected:
            outcomes = {0: "allowed", 2: "blocked"}
            got = outcomes.get(result.returncode, "an error (exit %d)" % result.returncode)
            wrong.append("%s was %s but should be %s" % (label, got, outcomes[expected]))
    if wrong:
        return [("FAIL", "guard self-test", "; ".join(wrong) + ". Check protected_paths and blocked_bash_patterns in fable/handoff.json, and that .claude/hooks/fable_guard.py is the copy from the skill.")]
    return [("PASS", "guard self-test", "%d test tool calls were blocked or allowed as expected" % len(cases))]


def check_stop_gate(project, open_tasks):
    if has_content(project / "fable" / "BLOCKED.md"):
        return [("FAIL", "stop gate self-test", "fable/BLOCKED.md has content, which lets the run stop at once. It is left over from an earlier run: record the answer in fable/DECISIONS.md and delete the file.")]
    if open_tasks == 0:
        return [("FAIL", "stop gate self-test", "not run, because fable/STATE.md has no open task for the gate to block on.")]
    result = run_hook(project, "fable_stop_gate.py", {"hook_event_name": "Stop", "cwd": str(project)}, dry_run=True)
    if result is None or result.returncode != 2:
        return [("FAIL", "stop gate self-test", "the stop gate allowed a stop while tasks are open (exit %s). Check that .claude/hooks/fable_stop_gate.py is the copy from the skill." % (result.returncode if result else "none"))]
    return [("PASS", "stop gate self-test", "blocks a stop while tasks are open")]


def check_session_context(project):
    result = run_hook(project, "fable_session_context.py", {"hook_event_name": "SessionStart", "source": "startup"})
    if result is None or result.returncode != 0 or "fable/MISSION.md" not in result.stdout:
        return [("FAIL", "session context self-test", "the hook failed or did not name fable/MISSION.md. Check that .claude/hooks/fable_session_context.py is the copy from the skill.")]
    return [("PASS", "session context self-test", "prints the pointer to the mission, ledger and decisions")]


def check_audit(project, extras):
    command = [*UV_SCRIPT, str(SCRIPTS / "audit_rules.py"), "--project", str(project), "--json"]
    if extras:
        command += ["--extra", *extras]
    result = subprocess.run(command, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
        findings = data["findings"]
        owners = data.get("owner_rules", [])
    except (ValueError, KeyError, TypeError):
        return [("FAIL", "rules audit", "audit_rules.py did not produce a result: %s" % (result.stderr.strip() or "no output")[:200])]
    rows = check_owner_rules(owners)
    open_findings = [f for f in findings if not f["accepted"]]
    fixes = [f for f in open_findings if f["severity"] == "FIX"]
    reviews = [f for f in open_findings if f["severity"] == "REVIEW"]

    def where(items):
        return short_list("%s:%d [%s]" % (f["file"], f["line"], f["rule"]) for f in items)

    if fixes:
        return rows + [("FAIL", "rules audit", "%d instruction line(s) would stall the run: %s. Run audit_rules.py for the reason and the rewrite of each." % (len(fixes), where(fixes)))]
    if reviews:
        return rows + [("WARN", "rules audit", "%d instruction line(s) to review: %s. Run audit_rules.py, then rewrite each or add it to audit_accept." % (len(reviews), where(reviews)))]
    return rows + [("PASS", "rules audit", "no instruction lines need attention")]


def check_owner_rules(owners):
    """Owner rules are never rewritten. One the run cannot work under stops the launch."""
    blocking = [o for o in owners if o.get("effect") == "blocks"]
    if blocking:
        detail = "; ".join('%s:%d "%s": %s' % (o["file"], o["line"], o["text"][:80], o["how"]) for o in blocking[:3])
        return [("FAIL", "owner rules", "%d owner rule(s) cannot be followed by an unattended run, so it will not launch: %s. "
                 "The skill never rewrites an owner rule. The owner can change the rule themselves, or do this job interactively." % (len(blocking), detail))]
    if owners:
        return [("PASS", "owner rules", "%d owner rule(s) kept as written and honored by the run: %s"
                 % (len(owners), short_list("%s:%d [%s]" % (o["file"], o["line"], o["kind"]) for o in owners)))]
    return []


def check_spec(project):
    """When the package was rendered from a structured spec, the spec must be valid and in step with the files."""
    if not (project / "fable" / "handoff_spec.json").exists():
        return []
    scripts = Path(__file__).resolve().parent
    proc = subprocess.run([*UV_SCRIPT, str(scripts / "spec_tool.py"), "check", "--project", str(project), "--json"],
                          capture_output=True, text=True, timeout=120)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [("FAIL", "handoff spec", "spec_tool.py could not check fable/handoff_spec.json: %s" % proc.stderr.strip()[:200])]
    if not result["ok"]:
        bad = ["%s %s" % (e["path"], e["message"]) for e in result.get("schema_errors", [])]
        bad += ["%s %s" % (p["path"], p["message"]) for p in result.get("problems", []) if p["severity"] == "FAIL"]
        return [("FAIL", "handoff spec", "fable/handoff_spec.json is not ready: " + short_list(bad or [result.get("load_error", "")]) + ". Run spec_tool.py check for the full list.")]
    signoff = subprocess.run([*UV_SCRIPT, str(scripts / "spec_tool.py"), "status", "--project", str(project)],
                             capture_output=True, text=True, timeout=60)
    if signoff.returncode != 0:
        return [("FAIL", "handoff spec", "the spec is valid, but " + signoff.stdout.strip().split(": ", 1)[-1] + ".")]
    drift = subprocess.run([*UV_SCRIPT, str(scripts / "render_handoff.py"), "--project", str(project), "--check"],
                           capture_output=True, text=True, timeout=120)
    if drift.returncode != 0:
        return [("WARN", "handoff spec", drift.stdout.strip() or drift.stderr.strip())]
    return [("PASS", "handoff spec", "valid, and the package matches what it renders")]


def check_agents(project):
    unpinned = []
    for path in sorted((project / ".claude" / "agents").glob("*.md")):
        text = read_text(path) or ""
        header = text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""
        model = re.search(r"(?m)^model:\s*(\S+)", header)
        if not model or model.group(1) == "inherit":
            unpinned.append(".claude/agents/" + path.name)
    if unpinned:
        return [("WARN", "subagent models", "no pinned model in %s. An unpinned subagent may run on the session's model at its price. Add a `model:` line (haiku, sonnet or opus) to the frontmatter." % short_list(unpinned))]
    return [("PASS", "subagent models", "every project subagent pins a model")]


def check_cli(config):
    binary = str(config.get("claude_binary") or "claude")
    if shutil.which(binary) is None:
        return [("WARN", "claude cli", "%r was not found on this machine. fable/launch.py will refuse to start until it is installed or claude_binary in fable/handoff.json points at it." % binary)]
    rows = [("PASS", "claude cli", "found " + binary)]
    # The launcher depends on these flags. Interfaces change between Claude Code
    # versions, so confirm them against the installed CLI's own help.
    needed = ["--print", "--model", "--effort", "--permission-mode", "--append-system-prompt-file",
              "--output-format", "--verbose", "--continue", "--max-budget-usd"]
    if config.get("max_turns"):
        needed.append("--max-turns")
    if config.get("mcp_config"):
        needed.append("--mcp-config")
    try:
        help_text = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        help_text = ""
    if "Usage" in help_text:
        # Documented in the CLI reference but not printed by --help in Claude Code 2.1.325,
        # and used successfully by real runs. See references/sources.md.
        documented_hidden = {"--append-system-prompt-file", "--max-turns"}
        missing = [flag for flag in needed if flag not in help_text and flag not in documented_hidden]
        if missing:
            rows.append(("WARN", "cli flags", "the installed CLI's --help does not list %s. Check the CLI reference before launching." % ", ".join(missing)))
        else:
            rows.append(("PASS", "cli flags", "every flag the launcher uses is in the installed CLI's help"))
    return rows


def check_mcp(project, config):
    """An MCP config the run should load, such as one for InfraNodus."""
    name = config.get("mcp_config")
    if not name:
        return []
    path = project / str(name)
    try:
        servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers")
    except (OSError, ValueError, AttributeError):
        return [("FAIL", "mcp config", "%s is missing or is not valid JSON." % name)]
    if not isinstance(servers, dict) or not servers:
        return [("FAIL", "mcp config", "%s has no mcpServers entries." % name)]
    return [("PASS", "mcp config", "%d server(s): %s. The launcher passes --mcp-config and logs any server that fails to connect." % (len(servers), ", ".join(sorted(servers))))]


def has_content(path):
    text = read_text(path)
    return bool(text and text.strip())


# --------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(
        description="Check that a fable-handoff package is ready for an unattended run. Exit 0 only when no check fails.",
        epilog="The result is saved to fable/.run/readiness.json. fable/launch.py refuses to start without a passing record for the current mission, operating rules and config.",
    )
    parser.add_argument("--project", required=True, help="path to the project root")
    parser.add_argument("--extra", nargs="+", default=[], metavar="PATH", help="more instruction files or directories for the rules audit: instructions or memory files outside the project that every session loads")
    parser.add_argument("--allow-dirty", action="store_true", help="report uncommitted changes as WARN instead of FAIL")
    parser.add_argument("--allow-passing-baseline", action="store_true", help="report a verify command that already passes as WARN instead of FAIL")
    parser.add_argument("--json", action="store_true", help="print {\"ok\": bool, \"rows\": [...]} instead of a table")
    args = parser.parse_args()

    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        sys.stderr.write("readiness_check: %s is not a directory. Pass the project root with --project.\n" % project)
        return 2

    config, config_rows = check_config(project)
    is_repo, branch_rows = check_git_branch(project, config)
    open_tasks, ledger_rows = check_ledger(project)
    dirty_before = dirty_paths(project) if is_repo else []
    baseline, verify_rows = check_verify(project, config, args.allow_passing_baseline)
    dirty_after = dirty_paths(project) if is_repo else []

    rows = []
    rows += config_rows
    rows += check_mission(project, config)
    rows += check_mission_wording(project)
    rows += check_operating_rules(project)
    rows += ledger_rows
    rows += check_decisions(project)
    rows += check_questions(project, config)
    rows += check_detective(project, config)
    rows += check_launch_requires(project, config)
    rows += check_companions(config)
    rows += check_model_calls(project, config)
    rows += check_owner_decisions(project, config)
    rows += check_standards(project, config)
    rows += branch_rows
    if is_repo:
        rows += check_git_clean(dirty_before, dirty_after, args.allow_dirty)
        rows += check_secrets(project)
    else:
        rows += [("FAIL", "git clean", "not checked: not a git repository"), ("FAIL", "secrets", "not checked: not a git repository")]
    rows += verify_rows
    rows += check_hooks_installed(project)
    rows += check_hooks_registered(project)
    rows += check_guard(project, config)
    rows += check_stop_gate(project, open_tasks)
    rows += check_session_context(project)
    rows += check_audit(project, args.extra)
    rows += check_settings_rows(config)
    rows += check_mcp(project, config)
    rows += check_spec(project)
    rows += check_agents(project)
    rows += check_cli(config)

    row_dicts = [{"status": status, "check": check, "detail": detail} for status, check, detail in rows]
    ok = not any(status == "FAIL" for status, _, _ in rows)

    if (project / "fable").is_dir():
        record = {
            "ok": ok,
            "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "package_hash": package_hash(project),
            "base_commit": (git(project, "rev-parse", "HEAD").stdout.strip() or None) if is_repo else None,
            "baseline": baseline,
            "rows": row_dicts,
        }
        run_dir = project / "fable" / ".run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "readiness.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps({"ok": ok, "rows": row_dicts}, indent=2))
    else:
        width = max(len(check) for _, check, _ in rows)
        for status, check, detail in rows:
            print("%-4s  %-*s  %s" % (status, width, check, detail))
        print()
        failed = sum(1 for status, _, _ in rows if status == "FAIL")
        warned = sum(1 for status, _, _ in rows if status == "WARN")
        if ok:
            note = " Read the %d WARN row(s) and decide whether each is acceptable." % warned if warned else ""
            print("READY: no check failed.%s Next, read fable/MISSION.md once as if you knew nothing else, then start with: uv run --script fable/launch.py" % note)
        else:
            print("NOT READY: %d check(s) failed. Fix each FAIL row above, commit, and run this check again." % failed)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
