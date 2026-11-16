"""Shared fixtures for the fable-handoff acceptance suite.

The suite tests behavior through the public interface only (files, flags,
exit codes, JSON keys), so it can be pointed at any implementation:

    FABLE_HANDOFF_SKILL_DIR=/path/to/fable-handoff python3 -m pytest -q tests
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SKILL = Path(os.environ.get("FABLE_HANDOFF_SKILL_DIR", Path(__file__).resolve().parent.parent / "fable-handoff")).resolve()
VERIFY = "python3 -m pytest -q -p no:cacheprovider app_tests"

MISSION = textwrap.dedent(
    """\
    # Mission: slugify

    ## Job

    Implement `slugify` in src/slug.py so that it turns any human-readable title
    into a lowercase URL slug made of ASCII letters, digits and single hyphens.
    It has to handle accents, punctuation, repeated whitespace and empty input,
    and each of those cases has to be covered by a test in app_tests/.

    ## Why

    The blog generator uses slugs as file names and URLs, so two different
    titles must not silently produce an empty slug. Correctness matters more
    than speed.

    ## Where things are

    Code is in src/, tests in app_tests/.

    ## Guardrails

    Pre-approved: create and edit files under src/ and app_tests/, commit to the run branch.

    Forbidden: editing .env files or the handoff configuration, because they define the run.

    Out of scope: packaging and publishing.

    ## Decisions

    Nobody can answer questions during this run. Use fable/DECISIONS.md.

    ## Done

    - Every task in fable/STATE.md is checked off.
    - `{verify}` exits 0.
    - fable/REPORT.md is written.
    """
).format(verify=VERIFY)

STATE = "# Run ledger\n\n## Current focus\n\nNot started.\n\n## Next step\n\nRead the mission.\n\n## Tasks\n\n- [ ] Implement slugify\n- [ ] Add edge case tests\n"

DECISIONS = textwrap.dedent(
    """\
    # Decisions

    ## Made before the run

    - Transliterate accents with unicodedata. Reason: no third-party dependency.

    ## Defaults for anything not listed

    - Prefer the reversible option.

    ## Open questions for the owner

    None.

    ## Made during the run

    ## Left for the owner
    """
)

SOLUTION = (
    "import re, unicodedata\n"
    "def slugify(s):\n"
    "    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()\n"
    "    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')\n"
)


def run(cmd, cwd=None, env=None, stdin=None, timeout=180):
    full_env = dict(os.environ)
    full_env.pop("CLAUDE_PROJECT_DIR", None)
    if env:
        full_env.update(env)
    return subprocess.run(cmd, cwd=cwd, env=full_env, input=stdin, capture_output=True, text=True, timeout=timeout)


def script(name: str) -> list[str]:
    return [sys.executable, str(SKILL / "scripts" / name)]


def git(project: Path, *args: str):
    return run(["git", *args], cwd=project)


def commit_all(project: Path, message: str = "wip") -> None:
    git(project, "add", "-A")
    git(project, "commit", "-qm", message)


def read_cfg(project: Path) -> dict:
    return json.loads((project / "fable" / "handoff.json").read_text())


def write_cfg(project: Path, **changes) -> dict:
    cfg = read_cfg(project)
    cfg.update(changes)
    (project / "fable" / "handoff.json").write_text(json.dumps(cfg, indent=2))
    return cfg


def bare_project(tmp_path: Path, name: str = "proj") -> Path:
    """A small git repo on main with one failing test and nothing from the skill."""
    project = tmp_path / name
    (project / "src").mkdir(parents=True)
    (project / "app_tests").mkdir()
    (project / "src" / "slug.py").write_text("def slugify(s):\n    raise NotImplementedError\n")
    (project / "app_tests" / "test_slug.py").write_text(
        "import sys; sys.path.insert(0, 'src')\nfrom slug import slugify\n\n"
        "def test_basic():\n    assert slugify('Hello World') == 'hello-world'\n"
    )
    (project / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    git(project, "init", "-q", "-b", "main")
    git(project, "config", "user.email", "t@example.com")
    git(project, "config", "user.name", "t")
    commit_all(project, "init")
    return project


def init(project: Path, *extra: str):
    return run([*script("init_handoff.py"), "--project", str(project), "--verify-command", VERIFY, "--branch", "fable/run-1", "--max-budget-usd", "40", *extra])


def prepared_project(tmp_path: Path, name: str = "proj", **cfg_changes) -> Path:
    """A project carried through every preparation phase and committed on the run branch."""
    project = bare_project(tmp_path, name)
    assert init(project).returncode == 0
    (project / "fable" / "MISSION.md").write_text(MISSION)
    (project / "fable" / "STATE.md").write_text(STATE)
    (project / "fable" / "DECISIONS.md").write_text(DECISIONS)
    if cfg_changes:
        write_cfg(project, **cfg_changes)
    for backup in (project / ".claude").glob("settings.json.bak-*"):
        backup.unlink()
    git(project, "switch", "-qc", "fable/run-1")
    commit_all(project, "Add handoff package")
    return project


def readiness(project: Path, *extra: str):
    proc = run([*script("readiness_check.py"), "--project", str(project), "--json", *extra])
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"ok": None, "rows": [], "raw": proc.stdout + proc.stderr}
    return proc, data


def statuses(data: dict) -> dict[str, str]:
    return {row["check"]: row["status"] for row in data["rows"]}


def hook(project: Path, name: str, payload, env=None):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    full = {"CLAUDE_PROJECT_DIR": str(project)}
    if env:
        full.update(env)
    return run([sys.executable, str(project / ".claude" / "hooks" / name)], cwd=project, env=full, stdin=stdin)


def make_stub(tmp_path: Path, plan: list[str]) -> Path:
    """A stand-in for the Claude CLI.

    `plan` lists what each successive call does:
      crash  exit 1 without doing anything
      idle   exit 0 without doing anything
      work   implement the job, check the ledger, write the report, commit, exit 0
    Every call appends its argv to calls.jsonl and prints a stream-json result
    line with a cost of 2.5.
    """
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    (stub_dir / "plan.json").write_text(json.dumps(plan))
    stub = stub_dir / "claude"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json, pathlib, subprocess, sys
            here = pathlib.Path({str(stub_dir)!r})
            if sys.argv[1:] in (["--version"], ["--help"]):
                print("0.0.0 (stub)")
                sys.exit(0)
            calls = here / "calls.jsonl"
            n = len(calls.read_text().splitlines()) if calls.exists() else 0
            with calls.open("a") as fh:
                fh.write(json.dumps(sys.argv[1:]) + "\\n")
            plan = json.loads((here / "plan.json").read_text())
            step = plan[min(n, len(plan) - 1)]
            print(json.dumps({{"type": "result", "subtype": "success", "total_cost_usd": 2.5}}))
            if step == "crash":
                sys.stderr.write("simulated crash\\n")
                sys.exit(1)
            if step == "work":
                pathlib.Path("src/slug.py").write_text({SOLUTION!r})
                state = pathlib.Path("fable/STATE.md")
                state.write_text(state.read_text().replace("- [ ]", "- [x]"))
                pathlib.Path("fable/REPORT.md").write_text("slugify implemented and verified.\\n")
                subprocess.run(["git", "add", "-A"]); subprocess.run(["git", "commit", "-qm", "Implement slugify"])
            sys.exit(0)
            """
        )
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


def stub_calls(stub: Path) -> list[list[str]]:
    calls = stub.parent / "calls.jsonl"
    return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


@pytest.fixture
def skill() -> Path:
    return SKILL
