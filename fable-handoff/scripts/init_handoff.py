#!/usr/bin/env python3
"""Scaffold a fable-handoff package in a project.

Creates eleven files (the config, four Markdown files, the launcher, three
hooks and two subagents), registers the hooks in .claude/settings.json and
adds fable/.run/ to .gitignore. Existing files are left alone unless --force
is given. Prints a JSON summary of what it did.

With --refresh-hooks it only replaces the code that came from the skill (the
three hooks and fable/launch.py) in a project that already has a package.

Examples:
    python3 init_handoff.py --project ~/code/shop \\
        --verify-command "npm test" --branch fable/checkout --max-budget-usd 60
    python3 init_handoff.py --project ~/code/shop --refresh-hooks
"""
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / "assets"

# Paths the run may never write. Gitignore-style globs, read by fable_guard.py.
# The first group keeps secrets and git internals safe. The second group stops
# the run from loosening its own limits.
DEFAULT_PROTECTED_PATHS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    ".git/**",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/hooks/**",
    "fable/handoff.json",
    "fable/MISSION.md",
    "fable/OPERATING_RULES.md",
    "fable/launch.py",
    "fable/handoff_spec.json",
    "fable/.run/**",
]

# Shell commands the run may never execute. Regular expressions, matched
# without regard to case anywhere in the command, read by fable_guard.py.
DEFAULT_BLOCKED_BASH_PATTERNS = [
    # force push, including the "+branch" form
    r"\bgit\s+push\b[^;&|\n]*\s(--force\S*|-[a-z]*f[a-z]*|\+\S+)(\s|$)",
    # push to a release branch
    r"\bgit\s+push\b[^;&|\n]*(\s|:|\+|refs/heads/)(main|master|production)(?![\w./-])",
    r"\bgit\s+reset\b[^;&|\n]*\s--hard\b",
    r"\bgit\s+clean\b[^;&|\n]*\s(-[a-z]*f|--force)",
    # rm with flags aimed at /, ~ or $HOME themselves
    r"\brm\s+-[^;&|\n]*?(?<=\s)[\"']?(/|~|\$HOME|\$\{HOME\})/?\*?[\"']?(?=\s|$|[;&|])",
    # a download piped into, or substituted into, a shell
    r"\b(curl|wget)\b[^;&\n]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b",
    r"\b(ba|z|da|k)?sh\b[^;&|\n]*(<\(|\$\()\s*(curl|wget)\b",
    r"\bsudo\b",
    r"\b(terraform|tofu)\b[^;&|\n]*\s(apply|destroy)\b",
    r"\bpulumi\b[^;&|\n]*\s(up|apply|destroy)\b",
    r"\bkubectl\b[^;&|\n]*\s(apply|delete)\b",
    # package publishing
    r"\b(npm|pnpm|yarn|bun|cargo|uv|poetry|flit|hatch)\s+publish\b",
    r"\btwine\s+upload\b",
    r"\bgem\s+push\b",
    r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b",
]

OWNERSHIP_BLOCK = """
## Ownership

This codebase is yours for the length of this run. You are responsible for its design as well as for the task. When you find duplicated or tangled code in the area you are working in, consolidate it instead of adding another copy, and fix nearby problems you come across instead of only reporting them. Stay inside the Guardrails of the mission while you do. Keep existing behavior the same unless the mission asks for a change. List every change the mission did not ask for in fable/REPORT.md, including the small ones.
"""

# (file in .claude/hooks, hook event, matcher or None)
HOOKS = [
    ("fable_guard.py", "PreToolUse", "Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit"),
    ("fable_stop_gate.py", "Stop", None),
    ("fable_session_context.py", "SessionStart", None),
]
DENY_RULES = ["Read(./.env)", "Read(./.env.*)"]

# The code that the skill installs in a project: target path -> file to copy.
# --refresh-hooks replaces exactly these files and nothing else.
CODE_FILES = {
    "fable/launch.py": ASSETS / "templates" / "launch.py",
    ".claude/hooks/fable_guard.py": ASSETS / "hooks" / "fable_guard.py",
    ".claude/hooks/fable_stop_gate.py": ASSETS / "hooks" / "fable_stop_gate.py",
    ".claude/hooks/fable_session_context.py": ASSETS / "hooks" / "fable_session_context.py",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scaffold a fable-handoff package (config, mission templates, hooks, launcher, subagents) in a project.",
        epilog="Next: fill in fable/MISSION.md, fable/STATE.md and fable/DECISIONS.md, tune fable/handoff.json, then run readiness_check.py.",
    )
    parser.add_argument("--project", required=True, help="path to the project root (the directory that holds .git)")
    parser.add_argument("--verify-command", default="", help="one shell command that exits 0 only when the mission is complete")
    parser.add_argument("--verify-timeout", type=int, default=None, metavar="SECONDS", help="time limit for the verify command (default 1800)")
    parser.add_argument("--branch", default="fable/run-1", help="git branch the run will work on (default fable/run-1). This script does not create it.")
    parser.add_argument("--model", default="claude-fable-5-2", help="full model ID (default claude-fable-5-2). The alias `fable` can resolve to an older Fable version on the API, so pin the ID")
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"], help="default high")
    parser.add_argument("--permission-mode", default="auto", choices=["auto", "acceptEdits", "dontAsk", "bypassPermissions"], help="default auto")
    parser.add_argument("--max-budget-usd", type=float, default=None, metavar="USD", help="spend cap across all launches (default: no cap)")
    parser.add_argument("--ownership", action="store_true", help="tell the model the codebase is its own, so that it refactors as it goes. Leave off for client or shared code.")
    parser.add_argument("--force", action="store_true", help="overwrite existing package files, including a mission and ledger you have filled in. Commit first.")
    parser.add_argument("--from-preflight", action="store_true", help="use fable/preflight.json from preflight.py: its verify command when --verify-command is not given, its paths to protect, and its open acceptance criteria as the first tasks in fable/STATE.md. Check each before launch.")
    parser.add_argument("--refresh-hooks", action="store_true", help="in a project that already has a package, replace the three hooks and fable/launch.py with the skill's current copies and touch nothing else. The other options are ignored.")
    return parser.parse_args()


def fail(message):
    sys.stderr.write("init_handoff: " + message + "\n")
    sys.exit(2)


def load_settings(path):
    """Read .claude/settings.json. Stops the script when the file cannot be merged into."""
    if not path.exists():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        fail(
            "%s is not valid JSON (%s). Nothing was changed. Fix the file by hand, then run this script again."
            % (path, error)
        )
    if not isinstance(settings, dict):
        fail("%s does not hold a JSON object. Nothing was changed. Fix the file by hand, then run this script again." % path)
    hooks = settings.get("hooks", {})
    permissions = settings.get("permissions", {})
    hooks_ok = isinstance(hooks, dict) and all(isinstance(groups, list) for groups in hooks.values())
    permissions_ok = isinstance(permissions, dict) and isinstance(permissions.get("deny", []), list)
    if not (hooks_ok and permissions_ok):
        fail('%s has "hooks" or "permissions" in a shape this script does not understand. Nothing was changed. Fix the file by hand, then run this script again.' % path)
    return settings


def merge_settings(settings, stop_timeout):
    """Add the hook registrations and deny rules that are missing. Returns a list of what was added."""
    added = []
    hooks = settings.setdefault("hooks", {})
    for name, event, matcher in HOOKS:
        groups = hooks.setdefault(event, [])
        if name in json.dumps(groups):
            continue  # already registered
        hook = {"type": "command", "command": 'python3 "${CLAUDE_PROJECT_DIR}/.claude/hooks/%s"' % name}
        if event == "Stop":
            # The stop gate runs the verify command, so it needs that long plus a margin.
            hook["timeout"] = stop_timeout
        group = {"hooks": [hook]}
        if matcher:
            group = {"matcher": matcher, "hooks": [hook]}
        groups.append(group)
        added.append("hooks.%s: %s" % (event, name))
    deny = settings.setdefault("permissions", {}).setdefault("deny", [])
    for rule in DENY_RULES:
        if rule not in deny:
            deny.append(rule)
            added.append("permissions.deny: " + rule)
    return added


def load_preflight(project):
    """Return the drafts section of fable/preflight.json, or stop with a message."""
    path = project / "fable" / "preflight.json"
    if not path.exists():
        fail("--from-preflight needs fable/preflight.json. Run scripts/preflight.py --project %s first. Nothing was changed." % project)
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("drafts", {})
    except json.JSONDecodeError as exc:
        fail("fable/preflight.json is not valid JSON (%s). Run preflight.py again. Nothing was changed." % exc)


def seed_state(template, tasks):
    """Replace the template's placeholder task lines with tasks taken from preflight."""
    if not tasks:
        return template
    lines = template.splitlines()
    out, placed = [], False
    for line in lines:
        if line.startswith("- [ ] {{FILL"):
            if not placed:
                out.extend("- [ ] " + t for t in tasks)
                placed = True
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def build_config(args, verify_timeout, extra_protected=()):
    protected = list(DEFAULT_PROTECTED_PATHS) + [p for p in extra_protected if p not in DEFAULT_PROTECTED_PATHS]
    return {
        "version": 1,
        "model": args.model,
        "effort": args.effort,
        "permission_mode": args.permission_mode,
        "branch": args.branch,
        "verify_command": args.verify_command,
        "verify_timeout_seconds": verify_timeout,
        "ownership": bool(args.ownership),
        "protected_paths": protected,
        "blocked_bash_patterns": DEFAULT_BLOCKED_BASH_PATTERNS,
        "allow_writes_outside_project": False,
        "max_stop_blocks": 8,
        "max_total_stop_blocks": 60,
        "max_relaunches": 3,
        "max_budget_usd": args.max_budget_usd,
        "max_turns": None,
        "audit_accept": [],
        "extra_cli_args": [],
    }


def refresh_hooks(project):
    """Replace the hooks and the launcher with the skill's copies. Returns the paths written."""
    if not (project / "fable" / "handoff.json").exists():
        fail(
            "%s has no fable/handoff.json, so there is no package to refresh. Nothing was changed. "
            "Run this script without --refresh-hooks to create the package first." % project
        )
    for rel, source in CODE_FILES.items():
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return list(CODE_FILES)


def main():
    args = parse_args()
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        fail("%s is not a directory. Pass the project root with --project." % project)

    if args.refresh_hooks:
        # Only code is replaced. The mission, the operating rules, the ledger,
        # the decisions, the config, the agents and the settings stay as they are.
        created = refresh_hooks(project)
        print(json.dumps({"project": str(project), "created": created, "skipped_existing": [], "settings_added": [], "backups": []}, indent=2))
        return 0

    # Check the settings file before writing anything, so that a broken file
    # does not leave a half-installed package behind.
    settings_path = project / ".claude" / "settings.json"
    settings = load_settings(settings_path)

    config_path = project / "fable" / "handoff.json"
    verify_timeout = args.verify_timeout
    if verify_timeout is None:
        verify_timeout = 1800
        if config_path.exists() and not args.force:
            try:
                verify_timeout = int(json.loads(config_path.read_text(encoding="utf-8"))["verify_timeout_seconds"])
            except (ValueError, KeyError, TypeError):
                pass

    draft = load_preflight(project) if args.from_preflight else {}
    if draft and not args.verify_command and draft.get("verify_command"):
        args.verify_command = draft["verify_command"]
    state_text = seed_state((ASSETS / "templates" / "STATE.md").read_text(encoding="utf-8"), draft.get("seed_tasks", []))

    rules = (ASSETS / "templates" / "OPERATING_RULES.md").read_text(encoding="utf-8")
    rules = rules.replace("{{OWNERSHIP_BLOCK}}", OWNERSHIP_BLOCK if args.ownership else "").rstrip() + "\n"

    # Target path in the project -> text to write, or the file to copy.
    package = {
        "fable/handoff.json": json.dumps(build_config(args, verify_timeout, draft.get("protected_paths", [])), indent=2) + "\n",
        "fable/MISSION.md": ASSETS / "templates" / "MISSION.md",
        "fable/OPERATING_RULES.md": rules,
        "fable/STATE.md": state_text,
        "fable/DECISIONS.md": ASSETS / "templates" / "DECISIONS.md",
        **CODE_FILES,
        ".claude/agents/fable-scout.md": ASSETS / "agents" / "fable-scout.md",
        ".claude/agents/fable-builder.md": ASSETS / "agents" / "fable-builder.md",
        ".claude/agents/fable-worker.md": ASSETS / "agents" / "fable-worker.md",
        ".claude/agents/fable-specialist.md": ASSETS / "agents" / "fable-specialist.md",
    }
    created, skipped = [], []
    for rel, source in package.items():
        target = project / rel
        if target.exists() and not args.force:
            skipped.append(rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(source, Path):
            shutil.copyfile(source, target)
        else:
            target.write_text(source, encoding="utf-8")
        created.append(rel)

    backups = []
    settings_added = merge_settings(settings, verify_timeout + 120)
    if settings_added:
        if settings_path.exists():
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = settings_path.with_name("settings.json.bak-" + stamp)
            shutil.copyfile(settings_path, backup)
            backups.append(str(backup.relative_to(project)))
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    gitignore = project / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if "fable/.run/" not in existing.splitlines():
        separator = "" if existing == "" or existing.endswith("\n") else "\n"
        gitignore.write_text(existing + separator + "fable/.run/\n", encoding="utf-8")

    print(json.dumps({
        "project": str(project),
        "created": created,
        "skipped_existing": skipped,
        "settings_added": settings_added,
        "backups": backups,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
