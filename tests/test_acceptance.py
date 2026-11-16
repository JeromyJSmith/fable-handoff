"""Acceptance tests for the fable-handoff skill. See SPEC.md for the contract."""
from __future__ import annotations

import json
import shutil
import py_compile
import re
import sys

import pytest

from conftest import (
    UV_SCRIPT,
    DECISIONS, MISSION, SKILL, SOLUTION, STATE, VERIFY, bare_project, commit_all, git, hook, init,
    make_stub, prepared_project, read_cfg, readiness, run, script, statuses, stub_calls, write_cfg,
)

PACKAGE_FILES = [
    "fable/handoff.json", "fable/MISSION.md", "fable/OPERATING_RULES.md", "fable/STATE.md",
    "fable/DECISIONS.md", "fable/launch.py", ".claude/hooks/fable_guard.py",
    ".claude/hooks/fable_stop_gate.py", ".claude/hooks/fable_session_context.py",
    ".claude/agents/fable-scout.md", ".claude/agents/fable-builder.md",
    ".claude/agents/fable-worker.md", ".claude/agents/fable-specialist.md",
]


# --------------------------------------------------------------------------- structure

def frontmatter(text: str) -> dict:
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    block = text.split("---\n", 2)[1]
    out = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def test_skill_md_frontmatter_and_size():
    text = (SKILL / "SKILL.md").read_text()
    meta = frontmatter(text)
    assert meta.get("name") == "fable-handoff"
    assert 200 <= len(meta.get("description", "")) <= 1024
    assert "<" not in meta["description"] and ">" not in meta["description"]
    assert len(text.splitlines()) < 500


def test_skill_md_points_at_every_script_and_reference():
    text = (SKILL / "SKILL.md").read_text()
    for name in ["init_handoff.py", "audit_rules.py", "readiness_check.py", "post_run_report.py", "launch.py"]:
        assert name in text, f"SKILL.md never mentions {name}"
    refs = sorted(p.name for p in (SKILL / "references").glob("*.md"))
    assert len(refs) >= 3
    for name in refs:
        assert name in text, f"SKILL.md never points at references/{name}"


def test_required_files_exist_and_compile():
    for rel in [
        "scripts/init_handoff.py", "scripts/audit_rules.py", "scripts/readiness_check.py",
        "scripts/post_run_report.py", "assets/templates/launch.py", "assets/hooks/fable_guard.py",
        "assets/hooks/fable_stop_gate.py", "assets/hooks/fable_session_context.py",
    ]:
        path = SKILL / rel
        assert path.exists(), rel
        py_compile.compile(str(path), doraise=True)
    for rel in ["assets/templates/MISSION.md", "assets/templates/OPERATING_RULES.md", "assets/templates/STATE.md", "assets/templates/DECISIONS.md"]:
        assert (SKILL / rel).exists(), rel


def test_python_is_stdlib_only():
    # Standard library, plus the skill's own scripts importing each other.
    allowed = set(sys.stdlib_module_names) | {"__future__"} | {p.stem for p in SKILL.glob("scripts/*.py")}
    sources = [*SKILL.glob("scripts/*.py"), *SKILL.glob("assets/**/*.py")]
    assert len(sources) >= 8
    for path in sources:
        for match in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", path.read_text(), flags=re.M):
            assert match.group(1) in allowed, f"{path.name} imports {match.group(1)}"


def test_no_em_dashes_anywhere():
    files = [p for p in SKILL.rglob("*") if p.is_file() and p.suffix in {".md", ".py", ".json"}]
    assert len(files) >= 15
    for path in files:
        if True:
            assert "—" not in path.read_text(), f"em dash in {path.relative_to(SKILL)}"


def test_scripts_have_help():
    for name in ["init_handoff.py", "audit_rules.py", "readiness_check.py", "post_run_report.py"]:
        proc = run([*script(name), "--help"])
        assert proc.returncode == 0 and "--project" in proc.stdout


def test_templates_carry_fill_markers_and_required_sections():
    mission = (SKILL / "assets/templates/MISSION.md").read_text()
    for heading in ["## Job", "## Why", "## Guardrails", "## Decisions", "## Done"]:
        assert heading in mission
    assert "{{FILL" in mission
    decisions = (SKILL / "assets/templates/DECISIONS.md").read_text()
    for heading in ["## Made before the run", "## Open questions for the owner", "## Made during the run", "## Left for the owner"]:
        assert heading in decisions
    assert "- [ ]" in (SKILL / "assets/templates/STATE.md").read_text()


def test_operating_rules_cover_the_unattended_behaviors():
    rules = (SKILL / "assets/templates/OPERATING_RULES.md").read_text().lower()
    for needle in ["fable/state.md", "fable/decisions.md", "fable/blocked.md", "fable/report.md", "subagent", "unattended"]:
        assert needle in rules, needle
    # Asking for written-out reasoning can be refused, so the rules must not ask for it.
    assert not re.search(r"step[- ]by[- ]step|explain your reasoning|show your reasoning", rules)


def test_subagents_pin_a_cheaper_model():
    agents = sorted((SKILL / "assets/agents").glob("*.md"))
    assert {a.name for a in agents} >= {"fable-scout.md", "fable-builder.md", "fable-worker.md", "fable-specialist.md"}
    for agent in agents:
        meta = frontmatter(agent.read_text())
        assert meta.get("name") and meta.get("description")
        assert meta.get("model") in {"haiku", "sonnet", "opus", "fable"}, f"{agent.name} must pin a model"
    models = {a.stem: frontmatter(a.read_text())["model"] for a in agents}
    assert models["fable-scout"] == "haiku" and models["fable-worker"] == "sonnet"
    assert models["fable-builder"] == "opus" and models["fable-specialist"] == "fable"


# --------------------------------------------------------------------------- init

def test_init_creates_the_package(tmp_path):
    project = bare_project(tmp_path)
    proc = init(project)
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert len(summary["created"]) == len(PACKAGE_FILES)
    for rel in PACKAGE_FILES:
        assert (project / rel).exists(), rel
    cfg = read_cfg(project)
    assert cfg["model"] == "claude-fable-5-2" and cfg["effort"] == "high" and cfg["permission_mode"] == "auto"
    assert cfg["verify_command"] == VERIFY and cfg["branch"] == "fable/run-1" and cfg["max_budget_usd"] == 40
    for key in ["protected_paths", "blocked_bash_patterns", "max_stop_blocks", "max_total_stop_blocks", "max_relaunches", "audit_accept"]:
        assert key in cfg, key
    for protected in ["fable/handoff.json", "fable/MISSION.md", ".claude/settings.json", ".env"]:
        assert protected in cfg["protected_paths"]
    assert "fable/.run/" in (project / ".gitignore").read_text().splitlines()


def test_init_registers_hooks_and_deny_rules(tmp_path):
    project = bare_project(tmp_path)
    init(project)
    settings = json.loads((project / ".claude/settings.json").read_text())
    for event, name in [("PreToolUse", "fable_guard.py"), ("Stop", "fable_stop_gate.py"), ("SessionStart", "fable_session_context.py")]:
        groups = settings["hooks"][event]
        commands = [h["command"] for g in groups for h in g["hooks"] if h["type"] == "command"]
        assert any(name in c and "CLAUDE_PROJECT_DIR" in c for c in commands), event
    matcher = settings["hooks"]["PreToolUse"][0]["matcher"]
    for tool in ["Bash", "Write", "Edit"]:
        assert tool in matcher
    assert "Read(./.env)" in settings["permissions"]["deny"]


def test_init_preserves_existing_settings_and_is_idempotent(tmp_path):
    project = bare_project(tmp_path)
    (project / ".claude").mkdir()
    (project / ".claude/settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(git status)"]}, "env": {"A": "1"}}))
    assert init(project).returncode == 0
    settings = json.loads((project / ".claude/settings.json").read_text())
    assert settings["permissions"]["allow"] == ["Bash(git status)"] and settings["env"] == {"A": "1"}
    assert list((project / ".claude").glob("settings.json.bak-*")), "existing settings must be backed up"
    (project / "fable/MISSION.md").write_text("edited by the agent")
    second = init(project)
    summary = json.loads(second.stdout)
    assert summary["created"] == [] and len(summary["skipped_existing"]) == len(PACKAGE_FILES)
    assert (project / "fable/MISSION.md").read_text() == "edited by the agent"
    again = json.loads((project / ".claude/settings.json").read_text())
    assert len(again["hooks"]["Stop"]) == 1 and again["permissions"]["deny"].count("Read(./.env)") == 1


def test_init_force_overwrites(tmp_path):
    project = bare_project(tmp_path)
    init(project)
    (project / "fable/MISSION.md").write_text("edited")
    assert init(project, "--force").returncode == 0
    assert "{{FILL" in (project / "fable/MISSION.md").read_text()


def test_init_ownership_flag(tmp_path):
    without = bare_project(tmp_path, "a")
    init(without)
    assert "{{" not in (without / "fable/OPERATING_RULES.md").read_text()
    assert read_cfg(without)["ownership"] is False
    with_flag = bare_project(tmp_path, "b")
    init(with_flag, "--ownership")
    extra = (with_flag / "fable/OPERATING_RULES.md").read_text().replace((without / "fable/OPERATING_RULES.md").read_text(), "")
    assert read_cfg(with_flag)["ownership"] is True
    assert re.search(r"codebase is yours|own(er)? .*codebase", (with_flag / "fable/OPERATING_RULES.md").read_text(), flags=re.I)
    assert len((with_flag / "fable/OPERATING_RULES.md").read_text()) > len((without / "fable/OPERATING_RULES.md").read_text())


def test_init_rejects_broken_settings_without_touching_them(tmp_path):
    project = bare_project(tmp_path)
    (project / ".claude").mkdir()
    (project / ".claude/settings.json").write_text("{not json")
    assert (SKILL / "scripts/init_handoff.py").exists()
    assert init(project).returncode != 0
    assert (project / ".claude/settings.json").read_text() == "{not json"


# --------------------------------------------------------------------------- audit

RULES_FILE = """# Rules
- Never assume or fabricate outputs.
- Do not implement anything until a concrete plan is written and approved.
- Think step by step and explain your reasoning.
- Always use subagents for research. Spawn parallel agents when possible.
- Keep answers under 20 words per sentence.
- Ask me when anything is unclear instead of guessing.
- Answer directly, don't overthink it.
- You have a token budget of 50000 tokens.
- Be proactive and use your best judgment.
```
never stop and ask for approval inside a code fence
```
"""


def audit(project, *extra):
    proc = run([*script("audit_rules.py"), "--project", str(project), "--json", *extra])
    return proc, json.loads(proc.stdout)["findings"]


def test_audit_finds_each_rule_family(tmp_path):
    project = bare_project(tmp_path)
    (project / "CLAUDE.md").write_text(RULES_FILE)
    proc, findings = audit(project)
    assert proc.returncode == 0
    by_line = {}
    for f in findings:
        assert f["file"] == "CLAUDE.md" and f["severity"] in {"FIX", "REVIEW"} and f["why"] and f["fix"]
        by_line.setdefault(f["line"], set()).add((f["rule"], f["severity"]))
    assert ("absolute", "REVIEW") in by_line[2]
    assert ("needs-human", "FIX") in by_line[3]
    assert ("reasoning-out", "FIX") in by_line[4]
    assert ("delegation", "REVIEW") in by_line[5]
    assert ("style-cap", "REVIEW") in by_line[6]
    assert ("asks-human", "REVIEW") in by_line[7]
    assert ("think-less", "FIX") in by_line[8]
    assert ("token-budget", "REVIEW") in by_line[9]
    assert ("vague-autonomy", "REVIEW") in by_line[10]
    assert not any(line >= 11 for line in by_line), "lines inside a code fence must be ignored"


def test_audit_scans_claude_dir_agents_md_and_extra(tmp_path):
    project = bare_project(tmp_path)
    (project / ".claude/skills/x").mkdir(parents=True)
    (project / ".claude/skills/x/SKILL.md").write_text("Think step by step.\n")
    (project / "sub").mkdir()
    (project / "sub/AGENTS.md").write_text("Answer directly, don't overthink.\n")
    (project / "node_modules/pkg").mkdir(parents=True)
    (project / "node_modules/pkg/CLAUDE.md").write_text("Think step by step.\n")
    outside = tmp_path / "global.md"
    outside.write_text("Wait for approval before continuing.\n")
    _, findings = audit(project, "--extra", str(outside))
    files = {f["file"] for f in findings}
    assert ".claude/skills/x/SKILL.md" in files and "sub/AGENTS.md" in files
    assert any(f.endswith("global.md") for f in files)
    assert not any("node_modules" in f for f in files)


def test_audit_ignores_the_package_it_installed(tmp_path):
    project = bare_project(tmp_path)
    init(project)
    _, findings = audit(project)
    assert findings == [], "the skill's own templates, rules and agents must not be flagged"


def test_audit_strict_and_accept(tmp_path):
    project = bare_project(tmp_path)
    init(project)
    (project / "CLAUDE.md").write_text("- Think step by step.\n")
    assert run([*script("audit_rules.py"), "--project", str(project), "--strict"]).returncode == 1
    assert run([*script("audit_rules.py"), "--project", str(project)]).returncode == 0
    write_cfg(project, audit_accept=["CLAUDE.md:reasoning-out"])
    proc, findings = audit(project, "--strict")
    assert proc.returncode == 0 and findings[0]["accepted"] is True


def test_audit_markdown_report(tmp_path):
    project = bare_project(tmp_path)
    (project / "CLAUDE.md").write_text("- Think step by step.\n")
    out = tmp_path / "audit.md"
    proc = run([*script("audit_rules.py"), "--project", str(project), "--out", str(out)])
    assert "CLAUDE.md:1" in proc.stdout and "reasoning-out" in proc.stdout
    assert out.read_text().strip() == proc.stdout.strip()


# --------------------------------------------------------------------------- guard hook

def guard(project, tool, **tool_input):
    return hook(project, "fable_guard.py", {"tool_name": tool, "tool_input": tool_input, "cwd": str(project), "hook_event_name": "PreToolUse"})


@pytest.fixture(scope="module")
def guarded(tmp_path_factory):
    project = bare_project(tmp_path_factory.mktemp("guard"))
    init(project)
    cfg = read_cfg(project)
    write_cfg(project, protected_paths=cfg["protected_paths"] + ["locked/**", "migrations/"])
    return project


@pytest.mark.parametrize(
    "path",
    ["services/api/.env", ".env.production", "fable/MISSION.md", "fable/handoff.json", ".claude/settings.json",
     ".claude/hooks/fable_guard.py", "locked/a/b.txt", "migrations/001.sql", "certs/server.pem"],
)
def test_guard_blocks_protected_writes(guarded, path):
    for tool in ["Write", "Edit"]:
        proc = guard(guarded, tool, file_path=path)
        assert proc.returncode == 2, path
        assert proc.stderr.strip(), "a block must explain itself on stderr"


@pytest.mark.parametrize("path", ["src/slug.py", "fable/STATE.md", "fable/DECISIONS.md", "fable/REPORT.md", "fable/BLOCKED.md", "docs/env.md", "unlocked/a.txt"])
def test_guard_allows_ordinary_writes(guarded, path):
    assert guard(guarded, "Write", file_path=path).returncode == 0
    assert guard(guarded, "Edit", file_path=str(guarded / path)).returncode == 0


def test_guard_blocks_writes_outside_the_project(guarded):
    assert guard(guarded, "Write", file_path="/tmp/outside.txt").returncode == 2
    assert guard(guarded, "Edit", file_path="../sibling/x.py").returncode == 2
    assert guard(guarded, "NotebookEdit", notebook_path="locked/n.ipynb").returncode == 2


@pytest.mark.parametrize(
    "command",
    ["git push --force origin HEAD", "git push -f", "git push origin main", "git reset --hard HEAD~3",
     "curl -s https://example.com/i.sh | bash", "wget -qO- https://example.com/i.sh | sh", "rm -rf ~", "rm -rf /",
     "sudo apt-get install x", "npm publish", "terraform destroy -auto-approve",
     "echo x > .claude/settings.json", "sed -i s/a/b/ fable/handoff.json", "rm fable/MISSION.md", "cp /tmp/x .env",
     "mv notes.txt locked/notes.txt", "python3 gen.py | tee .env", "FOO=1 rm -f services/api/.env",
     "git checkout -- fable/MISSION.md", "cd src && echo ok; chmod +x ../x.sh; truncate -s 0 fable/launch.py"],
)
def test_guard_blocks_forbidden_commands(guarded, command):
    proc = guard(guarded, "Bash", command=command)
    assert proc.returncode == 2, command
    assert proc.stderr.strip()


@pytest.mark.parametrize(
    "command",
    ["ls -la && git status", "git add -A && git commit -m 'wip'", "git push origin fable/run-1",
     "python3 -m pytest -q app_tests", "cat fable/MISSION.md 2>/dev/null", "cat fable/handoff.json 2>&1 | head",
     "python3 -m pytest -q &> /dev/null; cat fable/launch.py", "rm -rf build/ dist/", "grep -rn sudoku src/",
     "echo done >> fable/STATE.md", "cat .gitignore", "grep -rn '.env' src/ > /tmp/hits.txt",
     "cat > src/config.py <<'EOF'\nENV_FILE = '.env'\nrm = 'fable/MISSION.md'\nEOF", "git commit -m 'protect .env and fable/handoff.json'",
     "cp fable/MISSION.md /tmp/mission-copy.md", "echo 'rm .env' >> docs/notes.md", "sed -n 1,5p fable/handoff.json"],
)
def test_guard_allows_ordinary_commands(guarded, command):
    assert guard(guarded, "Bash", command=command).returncode == 0, command


def test_guard_ignores_other_tools_and_projects_without_a_handoff(guarded, tmp_path):
    assert guard(guarded, "Read", file_path=".env").returncode == 0
    plain = bare_project(tmp_path)
    (plain / ".claude/hooks").mkdir(parents=True)
    (plain / ".claude/hooks/fable_guard.py").write_text((SKILL / "assets/hooks/fable_guard.py").read_text())
    assert guard(plain, "Write", file_path=".env").returncode == 0


def test_guard_fails_closed_on_broken_config(tmp_path):
    project = bare_project(tmp_path)
    init(project)
    (project / "fable/handoff.json").write_text("{broken")
    assert guard(project, "Write", file_path="src/slug.py").returncode == 2


# --------------------------------------------------------------------------- stop gate

def gate(project, dry=False):
    return hook(project, "fable_stop_gate.py", {"hook_event_name": "Stop", "cwd": str(project)}, env={"FABLE_GATE_DRY_RUN": "1"} if dry else None)


def check_tasks(project, count=None):
    state = project / "fable/STATE.md"
    text = state.read_text()
    state.write_text(text.replace("- [ ]", "- [x]", count if count is not None else -1))


def test_stop_gate_lifecycle(tmp_path):
    project = prepared_project(tmp_path)
    first = gate(project)
    assert first.returncode == 2 and "Implement slugify" in first.stderr
    check_tasks(project)
    second = gate(project)
    assert second.returncode == 2 and VERIFY in second.stderr, "with tasks done the gate must run verify and show it failing"
    (project / "src/slug.py").write_text(SOLUTION)
    third = gate(project)
    assert third.returncode == 2 and "REPORT.md" in third.stderr
    (project / "fable/REPORT.md").write_text("done\n")
    assert gate(project).returncode == 0
    assert not (project / "fable/.run/stop_gate_exhausted.txt").exists()


def test_stop_gate_blocked_file_allows_stop(tmp_path):
    project = prepared_project(tmp_path)
    (project / "fable/BLOCKED.md").write_text("")
    assert gate(project).returncode == 2, "an empty BLOCKED.md is not a blocker"
    (project / "fable/BLOCKED.md").write_text("Need the vendor API key.\n")
    assert gate(project).returncode == 0


def test_stop_gate_gives_up_after_consecutive_blocks_without_progress(tmp_path):
    project = prepared_project(tmp_path, max_stop_blocks=3, max_total_stop_blocks=50)
    codes = [gate(project).returncode for _ in range(4)]
    assert codes == [2, 2, 2, 0]
    assert (project / "fable/.run/stop_gate_exhausted.txt").read_text().strip()


def test_stop_gate_progress_resets_the_consecutive_count(tmp_path):
    project = prepared_project(tmp_path, max_stop_blocks=2, max_total_stop_blocks=50)
    assert [gate(project).returncode for _ in range(2)] == [2, 2]
    check_tasks(project, 1)  # progress: one task fewer
    assert [gate(project).returncode for _ in range(2)] == [2, 2]
    assert gate(project).returncode == 0


def test_stop_gate_total_cap(tmp_path):
    project = prepared_project(tmp_path, max_stop_blocks=50, max_total_stop_blocks=2)
    assert [gate(project).returncode for _ in range(3)] == [2, 2, 0]


def test_stop_gate_dry_run_keeps_no_count(tmp_path):
    project = prepared_project(tmp_path, max_stop_blocks=1, max_total_stop_blocks=50)
    assert [gate(project, dry=True).returncode for _ in range(4)] == [2, 2, 2, 2]
    assert not (project / "fable/.run/stop_gate_exhausted.txt").exists()


def test_stop_gate_is_inert_without_a_handoff(tmp_path):
    plain = bare_project(tmp_path)
    (plain / ".claude/hooks").mkdir(parents=True)
    (plain / ".claude/hooks/fable_stop_gate.py").write_text((SKILL / "assets/hooks/fable_stop_gate.py").read_text())
    assert gate(plain).returncode == 0


def test_stop_gate_survives_empty_stdin(tmp_path):
    project = prepared_project(tmp_path)
    assert hook(project, "fable_stop_gate.py", "").returncode == 2


# --------------------------------------------------------------------------- session context

def test_session_context_reports_the_ledger(tmp_path):
    project = prepared_project(tmp_path)
    check_tasks(project, 1)
    proc = hook(project, "fable_session_context.py", {"hook_event_name": "SessionStart", "source": "compact"})
    assert proc.returncode == 0
    for needle in ["fable/MISSION.md", "fable/STATE.md", "fable/DECISIONS.md", "compact"]:
        assert needle in proc.stdout
    assert re.search(r"\b1\b.*done", proc.stdout) and re.search(r"\b1\b.*remaining", proc.stdout)


def test_session_context_is_silent_without_a_handoff(tmp_path):
    plain = bare_project(tmp_path)
    (plain / ".claude/hooks").mkdir(parents=True)
    (plain / ".claude/hooks/fable_session_context.py").write_text((SKILL / "assets/hooks/fable_session_context.py").read_text())
    proc = hook(plain, "fable_session_context.py", {"source": "startup"})
    assert proc.returncode == 0 and proc.stdout.strip() == ""


# --------------------------------------------------------------------------- readiness

def test_readiness_passes_on_a_prepared_project(tmp_path):
    project = prepared_project(tmp_path)
    proc, data = readiness(project)
    assert proc.returncode == 0 and data["ok"] is True, data
    assert "FAIL" not in statuses(data).values()
    for check in ["config", "mission", "ledger", "decisions", "git branch", "git clean", "secrets", "verify",
                  "hooks registered", "guard self-test", "stop gate self-test", "rules audit"]:
        assert statuses(data).get(check) == "PASS", check
    record = json.loads((project / "fable/.run/readiness.json").read_text())
    assert record["ok"] is True and record["package_hash"] and record["base_commit"]
    assert record["baseline"]["exit_code"] != 0
    assert git(project, "status", "--porcelain").stdout.strip() == "", "the check must leave the tree clean"
    assert not (project / "fable/.run/stop_gate.json").exists(), "the self-test must not count as a real block"


def test_readiness_human_table(tmp_path):
    project = prepared_project(tmp_path)
    proc = run([*script("readiness_check.py"), "--project", str(project)])
    assert proc.returncode == 0 and "READY" in proc.stdout and "NOT READY" not in proc.stdout
    assert re.search(r"^PASS\s+verify", proc.stdout, flags=re.M)


def test_readiness_fails_on_a_fresh_scaffold(tmp_path):
    project = bare_project(tmp_path)
    init(project)
    proc, data = readiness(project)
    assert proc.returncode == 1 and data["ok"] is False
    s = statuses(data)
    for check in ["mission", "ledger", "decisions", "git branch", "git clean"]:
        assert s[check] == "FAIL", check
    assert json.loads((project / "fable/.run/readiness.json").read_text())["ok"] is False


def test_readiness_without_a_package(tmp_path):
    project = bare_project(tmp_path)
    proc, data = readiness(project)
    assert proc.returncode == 1 and statuses(data)["config"] == "FAIL"


def break_and_check(tmp_path, mutate, failing_check, *flags, commit=True, **cfg):
    project = prepared_project(tmp_path, **cfg)
    mutate(project)
    if commit:
        commit_all(project, "mutate")
    proc, data = readiness(project, *flags)
    assert proc.returncode == 1, f"expected a failure on '{failing_check}'"
    assert statuses(data)[failing_check] == "FAIL", statuses(data)
    return data


def test_readiness_fails_on_placeholder_in_mission(tmp_path):
    break_and_check(tmp_path, lambda p: (p / "fable/MISSION.md").write_text(MISSION + "\n{{FILL: something}}\n"), "mission")


def test_readiness_fails_on_missing_section(tmp_path):
    break_and_check(tmp_path, lambda p: (p / "fable/MISSION.md").write_text(MISSION.replace("## Why", "## Background")), "mission")


def test_readiness_fails_on_human_in_the_loop_wording(tmp_path):
    break_and_check(tmp_path, lambda p: (p / "fable/MISSION.md").write_text(MISSION + "\nAsk me before changing the schema and wait for my approval.\n"), "mission")


def test_readiness_fails_when_done_does_not_quote_verify(tmp_path):
    break_and_check(tmp_path, lambda p: (p / "fable/MISSION.md").write_text(MISSION.replace(VERIFY, "make test")), "mission")


def test_readiness_fails_on_thin_job(tmp_path):
    thin = re.sub(r"## Job\n\n.*?\n\n## Why", "## Job\n\nMake slugify work.\n\n## Why", MISSION, flags=re.S)
    break_and_check(tmp_path, lambda p: (p / "fable/MISSION.md").write_text(thin), "mission")


def test_readiness_fails_on_open_questions(tmp_path):
    break_and_check(tmp_path, lambda p: (p / "fable/DECISIONS.md").write_text(DECISIONS.replace("None.", "- Which database should it use?")), "decisions")


def test_readiness_fails_on_empty_ledger(tmp_path):
    break_and_check(tmp_path, lambda p: (p / "fable/STATE.md").write_text(STATE.replace("- [ ]", "- [x]")), "ledger")


def test_readiness_fails_on_main_branch(tmp_path):
    break_and_check(tmp_path, lambda p: git(p, "switch", "-q", "main") and git(p, "merge", "-q", "fable/run-1"), "git branch", commit=False)


def test_readiness_fails_on_dirty_tree_unless_allowed(tmp_path):
    project = prepared_project(tmp_path)
    (project / "src/extra.py").write_text("x = 1\n")
    proc, data = readiness(project)
    assert proc.returncode == 1 and statuses(data)["git clean"] == "FAIL"
    proc, data = readiness(project, "--allow-dirty")
    assert proc.returncode == 0 and statuses(data)["git clean"] == "WARN"


def test_readiness_fails_on_tracked_secrets(tmp_path):
    break_and_check(tmp_path, lambda p: (p / "deploy.pem").write_text("key"), "secrets")


def test_readiness_allows_env_example(tmp_path):
    project = prepared_project(tmp_path)
    (project / ".env.example").write_text("A=\n")
    commit_all(project)
    proc, data = readiness(project)
    assert proc.returncode == 0, statuses(data)


def test_readiness_fails_when_verify_already_passes_unless_allowed(tmp_path):
    project = prepared_project(tmp_path)
    (project / "src/slug.py").write_text(SOLUTION)
    commit_all(project)
    proc, data = readiness(project)
    assert proc.returncode == 1 and statuses(data)["verify"] == "FAIL"
    proc, data = readiness(project, "--allow-passing-baseline")
    assert proc.returncode == 0 and statuses(data)["verify"] == "WARN"


def test_readiness_fails_when_verify_cannot_run(tmp_path):
    def mutate(p):
        text = (p / "fable/MISSION.md").read_text().replace(VERIFY, "no-such-binary-xyz --check")
        (p / "fable/MISSION.md").write_text(text)
        write_cfg(p, verify_command="no-such-binary-xyz --check")
    break_and_check(tmp_path, mutate, "verify")


def test_readiness_fails_on_empty_verify(tmp_path):
    break_and_check(tmp_path, lambda p: write_cfg(p, verify_command=""), "verify")


def test_readiness_fails_when_a_hook_is_missing_or_unregistered(tmp_path):
    break_and_check(tmp_path, lambda p: (p / ".claude/hooks/fable_stop_gate.py").unlink(), "hooks installed")

    def unregister(p):
        settings = json.loads((p / ".claude/settings.json").read_text())
        del settings["hooks"]["Stop"]
        (p / ".claude/settings.json").write_text(json.dumps(settings))
    (tmp_path / "second").mkdir()
    break_and_check(tmp_path / "second", unregister, "hooks registered")


def test_readiness_fails_when_the_guard_does_not_guard(tmp_path):
    break_and_check(tmp_path, lambda p: (p / ".claude/hooks/fable_guard.py").write_text("import sys\nsys.exit(0)\n"), "guard self-test")


def test_readiness_fails_on_stale_blocked_file(tmp_path):
    break_and_check(tmp_path, lambda p: (p / "fable/BLOCKED.md").write_text("left over from an earlier run\n"), "stop gate self-test")


def test_readiness_fails_on_rules_that_need_a_human(tmp_path):
    data = break_and_check(tmp_path, lambda p: (p / "CLAUDE.md").write_text("- Do not implement anything until the plan is approved.\n"), "rules audit")
    assert any("CLAUDE.md" in row["detail"] for row in data["rows"] if row["check"] == "rules audit")


def test_readiness_audits_extra_files(tmp_path):
    project = prepared_project(tmp_path)
    outside = tmp_path / "global.md"
    outside.write_text("Think step by step.\n")
    proc, data = readiness(project, "--extra", str(outside))
    assert proc.returncode == 1 and statuses(data)["rules audit"] == "FAIL"


def test_readiness_warns_on_risky_config(tmp_path):
    project = prepared_project(tmp_path, effort="medium", permission_mode="bypassPermissions", max_budget_usd=None)
    proc, data = readiness(project)
    assert proc.returncode == 0
    warned = " ".join(row["check"] + " " + row["detail"] for row in data["rows"] if row["status"] == "WARN").lower()
    for needle in ["effort", "bypasspermissions", "budget"]:
        assert needle in warned, needle


def test_readiness_warns_on_unpinned_subagent(tmp_path):
    project = prepared_project(tmp_path)
    (project / ".claude/agents/helper.md").write_text("---\nname: helper\ndescription: helps\n---\nHelp.\n")
    commit_all(project)
    proc, data = readiness(project)
    assert proc.returncode == 0
    assert any(row["status"] == "WARN" and "helper.md" in row["detail"] for row in data["rows"])


# --------------------------------------------------------------------------- launcher

def launch(project, *args):
    return run([*UV_SCRIPT, str(project / "fable/launch.py"), *args], cwd=project)


def ready_with_stub(tmp_path, plan, **cfg):
    stub = make_stub(tmp_path, plan)
    project = prepared_project(tmp_path, claude_binary=str(stub), **cfg)
    proc, data = readiness(project)
    assert proc.returncode == 0, statuses(data)
    return project, stub


def flag(call, name):
    return call[call.index(name) + 1]


def test_launch_dry_run_shows_the_command(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["work"])
    proc = launch(project, "--dry-run")
    assert proc.returncode == 0
    for needle in ["-p", "--model claude-fable-5-2", "--effort high", "--permission-mode auto", "--append-system-prompt-file fable/OPERATING_RULES.md",
                   "--output-format stream-json", "--verbose", "--max-budget-usd 40.00"]:
        assert needle in proc.stdout, needle
    assert "## Job" not in proc.stdout, "the dry run should not dump the whole mission"
    assert stub_calls(stub) == [], "a dry run must not start anything"


def test_launch_refuses_without_readiness(tmp_path):
    stub = make_stub(tmp_path, ["work"])
    project = prepared_project(tmp_path, claude_binary=str(stub))
    proc = launch(project)
    assert proc.returncode == 2 and stub_calls(stub) == []


@pytest.mark.parametrize("target", ["fable/MISSION.md", "fable/OPERATING_RULES.md", "fable/handoff.json"])
def test_launch_refuses_after_the_package_changed(tmp_path, target):
    project, stub = ready_with_stub(tmp_path, ["work"])
    path = project / target
    path.write_text(path.read_text() + "\n")
    assert launch(project).returncode == 2
    assert launch(project, "--dry-run").returncode == 2
    assert stub_calls(stub) == []


def test_launch_refuses_after_failed_readiness(tmp_path):
    stub = make_stub(tmp_path, ["work"])
    project = prepared_project(tmp_path, claude_binary=str(stub))
    (project / "src/extra.py").write_text("x = 1\n")  # dirty tree
    assert readiness(project)[0].returncode == 1
    assert launch(project).returncode == 2 and stub_calls(stub) == []


def test_launch_single_successful_run(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["work"])
    proc = launch(project)
    assert proc.returncode == 0, proc.stderr
    calls = stub_calls(stub)
    assert len(calls) == 1
    call = calls[0]
    assert flag(call, "-p") == (project / "fable/MISSION.md").read_text()
    assert flag(call, "--model") == "claude-fable-5-2" and flag(call, "--effort") == "high" and flag(call, "--permission-mode") == "auto"
    assert flag(call, "--append-system-prompt-file") == "fable/OPERATING_RULES.md"
    assert float(flag(call, "--max-budget-usd")) == 40.0
    assert "--continue" not in call
    log = json.loads((project / "fable/.run/launch_log.json").read_text())
    assert len(log) == 1 and log[0]["finished"] is True and log[0]["exit_code"] == 0
    assert "total_cost_usd" in (project / "fable/.run/transcript-0.jsonl").read_text()


def test_launch_starts_fresh_after_a_crash(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["crash", "work"])
    assert launch(project).returncode == 0
    calls = stub_calls(stub)
    assert len(calls) == 2
    assert "--continue" not in calls[1], "a crashed session is not continued"
    assert "## Job" in flag(calls[1], "-p"), "a fresh session needs the mission again"
    assert "fable/STATE.md" in flag(calls[1], "-p")
    assert "simulated crash" in (project / "fable/.run/stderr-0.log").read_text()
    log = json.loads((project / "fable/.run/launch_log.json").read_text())
    assert [entry["finished"] for entry in log] == [False, True]


def test_launch_continues_after_a_clean_exit_with_work_left(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["idle", "work"])
    assert launch(project).returncode == 0
    calls = stub_calls(stub)
    assert len(calls) == 2
    assert "--continue" in calls[1]
    assert "fable/STATE.md" in flag(calls[1], "-p") and "## Job" not in flag(calls[1], "-p")


def test_launch_passes_the_remaining_budget(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["idle", "idle", "work"])
    assert launch(project).returncode == 0
    budgets = [float(flag(call, "--max-budget-usd")) for call in stub_calls(stub)]
    assert budgets == [40.0, 37.5, 35.0], "each launch gets the cap minus what earlier launches reported spending"


def test_launch_stops_when_the_budget_is_spent(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["idle"], max_budget_usd=4, max_relaunches=5)
    assert launch(project).returncode == 1
    assert len(stub_calls(stub)) == 2, "2.5 + 2.5 exceeds a cap of 4, so there is no third launch"


def test_launch_gives_up_after_max_relaunches(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["idle"], max_relaunches=2)
    proc = launch(project)
    assert proc.returncode == 1
    assert len(stub_calls(stub)) == 3
    log = json.loads((project / "fable/.run/launch_log.json").read_text())
    assert len(log) == 3 and not any(entry["finished"] for entry in log)


def test_launch_does_not_relaunch_into_a_blocker(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["idle"])
    stub.write_text(stub.read_text().replace("sys.exit(0)", "pathlib.Path('fable/BLOCKED.md').write_text('need a key\\n'); sys.exit(0)"))
    proc = launch(project)
    assert len(stub_calls(stub)) == 1, "a recorded blocker ends the run"
    assert proc.returncode == 3, "exit 3 means the run stopped on a recorded blocker"
    log = json.loads((project / "fable/.run/launch_log.json").read_text())
    assert log[0]["blocked"] is True


def test_launch_without_budget_and_with_extra_args(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["work"], max_budget_usd=None, max_turns=50, extra_cli_args=["--fallback-model", "opus"], effort="xhigh", model="claude-fable-5-2")
    assert launch(project).returncode == 0
    call = stub_calls(stub)[0]
    assert "--max-budget-usd" not in call
    assert flag(call, "--max-turns") == "50" and flag(call, "--fallback-model") == "opus"
    assert flag(call, "--effort") == "xhigh" and flag(call, "--model") == "claude-fable-5-2"


# --------------------------------------------------------------------------- post-run review

def review(project, *extra):
    return run([*script("post_run_report.py"), "--project", str(project), *extra])


def finished_run(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["work"])
    assert launch(project).returncode == 0
    return project


def test_post_run_clean(tmp_path):
    project = finished_run(tmp_path)
    out = project / "fable/REVIEW.md"
    proc = review(project, "--out", str(out))
    assert proc.returncode == 0, proc.stdout
    assert "CLEAN" in proc.stdout and "NEEDS REVIEW" not in proc.stdout
    assert "src/slug.py" in proc.stdout and VERIFY in proc.stdout
    assert out.read_text().strip() == proc.stdout.strip()


def needs_review(tmp_path, mutate, *needles, commit=True):
    project = finished_run(tmp_path)
    mutate(project)
    if commit:
        commit_all(project, "after the run")
    proc = review(project)
    assert proc.returncode == 1
    verdict = proc.stdout.lower()
    assert "needs review" in verdict
    for needle in needles:
        assert needle in verdict, needle
    return proc.stdout


def test_post_run_flags_unfinished_tasks(tmp_path):
    needs_review(tmp_path, lambda p: (p / "fable/STATE.md").write_text(STATE), "task")


def test_post_run_flags_failing_verify(tmp_path):
    needs_review(tmp_path, lambda p: (p / "src/slug.py").write_text("def slugify(s):\n    return ''\n"), "verify")


def test_post_run_flags_skipped_tests(tmp_path):
    needs_review(tmp_path, lambda p: (p / "app_tests/test_more.py").write_text("import pytest\n\n@pytest.mark.skip\ndef test_x():\n    assert False\n"), "weaken")


def test_post_run_flags_deleted_tests(tmp_path):
    def mutate(p):
        (p / "app_tests/test_slug.py").unlink()
        (p / "app_tests/test_other.py").write_text("def test_ok():\n    assert True\n")
    needs_review(tmp_path, mutate, "deleted")


def test_post_run_flags_changed_protected_files(tmp_path):
    out = needs_review(tmp_path, lambda p: (p / "fable/MISSION.md").write_text(MISSION + "\nedited\n"), "protected")
    assert "fable/MISSION.md" in out


def test_post_run_flags_uncommitted_changes(tmp_path):
    needs_review(tmp_path, lambda p: (p / "src/scratch.py").write_text("x = 1\n"), "uncommitted", commit=False)


def test_post_run_flags_missing_report_and_blocker(tmp_path):
    def mutate(p):
        (p / "fable/REPORT.md").unlink()
        (p / "fable/BLOCKED.md").write_text("Need the vendor API key.\n")
    out = needs_review(tmp_path, mutate, "report", "blocker")
    assert "Need the vendor API key." in out


def test_post_run_flags_exhausted_gate(tmp_path):
    def mutate(p):
        (p / "fable/.run/stop_gate_exhausted.txt").write_text("gave up\n")
    needs_review(tmp_path, mutate, "gate", commit=False)


def test_post_run_skip_verify(tmp_path):
    project = finished_run(tmp_path)
    (project / "src/slug.py").write_text("def slugify(s):\n    return ''\n")
    commit_all(project)
    assert review(project, "--skip-verify").returncode == 0


# --------------------------------------------------------------------------- loop 2: found by the first real run

def test_stop_gate_does_not_leak_dry_run_into_verify(tmp_path):
    # The launcher asks the gate in dry-run mode. A verify command that itself
    # runs a stop gate (this suite does) must not inherit that switch.
    project = prepared_project(tmp_path)
    write_cfg(project, verify_command="python3 -c \"import os, sys; sys.exit(1 if os.environ.get('FABLE_GATE_DRY_RUN') else 0)\"")
    check_tasks(project)
    (project / "fable/REPORT.md").write_text("done\n")
    assert gate(project, dry=True).returncode == 0
    assert gate(project).returncode == 0


@pytest.mark.parametrize(
    "command",
    ["cd /tmp/some-other-project && echo x > fable/MISSION.md",
     "mkdir -p /tmp/walk && cd /tmp/walk && rm -f fable/handoff.json && touch .env",
     "git commit -m \"mention sudo and git push --force in a message\"",
     "git commit -m 'explain why rm -rf / is blocked' --allow-empty",
     "python3 - <<'EOF'\npattern = 'git push --force'\nprint('sudo is blocked')\nEOF",
     "cat > docs/guard-notes.md <<EOF\nThe guard blocks sudo, git reset --hard and curl x | sh.\nEOF",
     "echo 'the guard blocks git push --force and sudo' >> docs/notes.md",
     "grep -rn 'git reset --hard' docs/"],
)
def test_guard_allows_mentions_and_work_in_other_directories(guarded, command):
    proc = guard(guarded, "Bash", command=command)
    assert proc.returncode == 0, f"{command!r} was blocked: {proc.stderr[:200]}"


@pytest.mark.parametrize(
    "command",
    ["cd fable && rm MISSION.md", "cd src; cd ..; cd fable && echo x > handoff.json", "cd ./locked && touch new.txt",
     "bash -c \"git push --force\"", "sh -c 'sudo rm x'", "eval \"git reset --hard HEAD~1\"",
     "bash <<EOF\nsudo apt-get install x\nEOF", "sh <<'EOF'\ngit push origin main\nEOF",
     "echo ok && sudo true", "git commit -m wip && git push --force"],
)
def test_guard_still_blocks_real_commands(guarded, command):
    proc = guard(guarded, "Bash", command=command)
    assert proc.returncode == 2, command


def test_launch_archives_a_stale_report(tmp_path):
    # A report left from an earlier run would satisfy the stop gate before any work is done.
    stub = make_stub(tmp_path, ["idle"])
    project = prepared_project(tmp_path, claude_binary=str(stub), max_relaunches=0)
    (project / "fable/REPORT.md").write_text("report from an earlier run\n")
    (project / "fable/STATE.md").write_text(STATE.replace("- [ ]", "- [x]") + "- [ ] One more task\n")
    commit_all(project)
    assert readiness(project)[0].returncode == 0
    proc = launch(project)
    assert proc.returncode == 1
    assert not (project / "fable/REPORT.md").exists(), "the stale report must be moved out of the way before the first launch"
    archived = list((project / "fable/.run").glob("REPORT-previous*.md"))
    assert len(archived) == 1 and "earlier run" in archived[0].read_text()


def test_launch_keeps_the_report_written_during_the_run(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["idle", "work"])
    assert launch(project).returncode == 0
    assert (project / "fable/REPORT.md").exists()
    assert list((project / "fable/.run").glob("REPORT-previous*.md")) == []


def test_init_refresh_hooks_updates_only_code(tmp_path):
    project = bare_project(tmp_path)
    init(project)
    edited = {rel: f"edited {rel}\n" for rel in ["fable/MISSION.md", "fable/STATE.md", "fable/DECISIONS.md", "fable/OPERATING_RULES.md"]}
    for rel, text in edited.items():
        (project / rel).write_text(text)
    cfg_before = write_cfg(project, protected_paths=["only-this"])
    code = [".claude/hooks/fable_guard.py", ".claude/hooks/fable_stop_gate.py", ".claude/hooks/fable_session_context.py", "fable/launch.py"]
    for rel in code:
        (project / rel).write_text("# old version\n")
    proc = run([*script("init_handoff.py"), "--project", str(project), "--refresh-hooks"])
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    for rel in code:
        assert (project / rel).read_text() != "# old version\n", rel
        assert any(entry.endswith(rel) for entry in summary["created"]), rel
    for rel, text in edited.items():
        assert (project / rel).read_text() == text, f"{rel} must not be touched by --refresh-hooks"
    assert read_cfg(project) == cfg_before


def test_init_refresh_hooks_needs_an_existing_package(tmp_path):
    project = bare_project(tmp_path)
    proc = run([*script("init_handoff.py"), "--project", str(project), "--refresh-hooks"])
    assert proc.returncode != 0
    assert not (project / "fable").exists()


def wording_rows(tmp_path, extra_line):
    project = prepared_project(tmp_path)
    (project / "fable/MISSION.md").write_text(MISSION.replace("Out of scope:", extra_line + "\n\nOut of scope:"))
    commit_all(project)
    proc, data = readiness(project)
    assert proc.returncode == 0, statuses(data)
    return [row for row in data["rows"] if row["check"] == "mission wording"]


def test_readiness_warns_on_absolute_directives_and_quotes_them(tmp_path):
    rows = wording_rows(tmp_path, "- Never edit the schema.\n- You must always run the linter.")
    assert len(rows) == 1 and rows[0]["status"] == "WARN"
    assert "Never edit the schema" in rows[0]["detail"] and "always run the linter" in rows[0]["detail"]


def test_readiness_does_not_warn_on_descriptive_never_or_always(tmp_path):
    rows = wording_rows(tmp_path, "The preparing agent has never seen this repository, and the importer was always slow.")
    assert [row for row in rows if row["status"] != "PASS"] == []


# --------------------------------------------------------------------------- preflight

def full_inputs_project(tmp_path):
    """A project that is close to done and has all six kinds of input."""
    project = bare_project(tmp_path, "close")
    docs = project / "docs"
    docs.mkdir()
    (docs / "GOAL.md").write_text(
        "# Goal\n\nShip slugify for the blog generator so that every title becomes a unique, readable URL. "
        "It handles accents, punctuation, repeated whitespace and empty input, and two different titles never "
        "silently produce the same empty slug. Correctness matters more than speed because broken links cost readers.\n")
    (docs / "SPEC.md").write_text(
        "# Specification\n\n## Acceptance criteria\n\n- [x] Lowercase ASCII output\n- [ ] Accents are transliterated\n"
        "- [ ] Empty input raises ValueError\n- [ ] Repeated separators collapse\n\nThe function must never return an empty string.\n"
        "Should numbers be kept? TBD\n")
    (docs / "STANDARDS.md").write_text("# Coding standards\n\n" + "Plain functions, type hints and docstrings on every public function. " * 8 + "\n- Never use regex lookbehind.\n")
    (docs / "LESSONS.md").write_text("# Lessons learned\n\n- Using the slugify package failed: it broke on emoji.\n"
                                      "- Normalizing with unicodedata worked well.\n")
    (project / "STATUS.md").write_text("# Current status\n\nBasic lowercase works. Accents are not handled yet.\n")
    (project / "CLAUDE.md").write_text("- Do not implement anything until the plan is approved.\n")
    commit_all(project, "docs")
    return project


def preflight(project, *extra):
    proc = run([*script("preflight.py"), "--project", str(project), "--json", *extra])
    return proc, json.loads(proc.stdout)


def by_input(data):
    return {row["input"]: row for row in data["inputs"]}


def test_preflight_maps_all_six_inputs(tmp_path):
    project = full_inputs_project(tmp_path)
    proc, data = preflight(project, "--run-tests")
    assert proc.returncode == 0, data["gaps"]
    rows = by_input(data)
    assert set(rows) == {"goal", "spec", "standards", "state", "history", "evals"}
    assert "docs/GOAL.md" in rows["goal"]["sources"] and rows["goal"]["status"] == "READY"
    assert "docs/SPEC.md" in rows["spec"]["sources"] and rows["spec"]["status"] == "READY"
    assert "docs/STANDARDS.md" in rows["standards"]["sources"]
    assert "docs/LESSONS.md" in rows["history"]["sources"]
    assert "STATUS.md" in rows["state"]["sources"]
    assert "app_tests/test_slug.py" in rows["evals"]["sources"]
    assert data["test_runs"][0]["exit_code"] not in (0, None)
    assert (project / "fable/PREFLIGHT.md").exists() and (project / "fable/preflight.json").exists()


def test_preflight_drafts(tmp_path):
    project = full_inputs_project(tmp_path)
    _, data = preflight(project, "--run-tests")
    d = data["drafts"]
    assert d["seed_tasks"] == ["Accents are transliterated", "Empty input raises ValueError", "Repeated separators collapse"]
    assert d["verify_command"] and "pytest" in d["verify_command"]
    assert "app_tests/**" in d["protected_paths"] and "docs/SPEC.md" in d["protected_paths"]
    assert any("slugify package failed" in t for t in d["traps_for_mission"])
    assert any("unicodedata worked" in t for t in d["what_worked"])
    assert any("numbers be kept" in q for q in d["decision_candidates"])


def test_preflight_reports_instruction_problems_and_questions(tmp_path):
    project = full_inputs_project(tmp_path)
    _, data = preflight(project)
    texts = " ".join(g["severity"] + " " + g["text"] for g in data["gaps"])
    assert "FIX" in texts and "CLAUDE.md:1" in texts
    assert "docs/STANDARDS.md" in texts, "standards are audited too"
    assert any(g["severity"] == "QUESTION" and "numbers" in g["text"] for g in data["gaps"])


def test_preflight_blocks_without_goal_evals_or_git(tmp_path):
    project = tmp_path / "empty"
    project.mkdir()
    (project / "README.md").write_text("# app\n")
    proc, data = preflight(project, "--no-write")
    assert proc.returncode == 1 and data["ready"] is False
    blocking = {g["input"] for g in data["gaps"] if g["severity"] == "BLOCKING"}
    assert {"goal", "evals", "state"} <= blocking
    assert not (project / "fable").exists(), "--no-write writes nothing"


def test_preflight_blocks_when_tests_already_pass(tmp_path):
    project = full_inputs_project(tmp_path)
    (project / "src/slug.py").write_text(SOLUTION)
    commit_all(project)
    proc, data = preflight(project, "--run-tests")
    assert proc.returncode == 1
    assert any(g["severity"] == "BLOCKING" and "already passes" in g["text"] for g in data["gaps"])


def test_preflight_goal_argument_and_sources(tmp_path):
    project = full_inputs_project(tmp_path)
    outside = tmp_path / "notes"
    outside.mkdir()
    (outside / "retro.md").write_text("# Retrospective\n\n- The first deploy broke because of a missing migration.\n- Pairing on reviews worked.\n")
    _, data = preflight(project, "--goal", "Make slugify correct.", "--source", str(outside))
    rows = by_input(data)
    assert rows["goal"]["sources"] == ["(given on the command line)"] and rows["goal"]["status"] == "THIN"
    assert any(s.endswith("retro.md") for s in rows["history"]["sources"])
    assert rows["evals"]["sources"], "evals are found in the project even when --source points elsewhere"
    assert run([*script("preflight.py"), "--project", str(project), "--source", str(tmp_path / "nope")]).returncode == 2


def test_preflight_ignores_its_own_cache_files_in_git_state(tmp_path):
    project = full_inputs_project(tmp_path)
    preflight(project, "--run-tests")
    _, data = preflight(project, "--run-tests")
    assert data["git"]["uncommitted"] == 0


def test_init_from_preflight(tmp_path):
    project = full_inputs_project(tmp_path)
    preflight(project, "--run-tests")
    proc = run([*script("init_handoff.py"), "--project", str(project), "--from-preflight", "--branch", "fable/run-1"])
    assert proc.returncode == 0, proc.stderr
    cfg = read_cfg(project)
    assert "pytest" in cfg["verify_command"]
    assert "app_tests/**" in cfg["protected_paths"] and "fable/MISSION.md" in cfg["protected_paths"]
    state = (project / "fable/STATE.md").read_text()
    assert "- [ ] Accents are transliterated" in state and "- [ ] {{FILL" not in state


def test_init_from_preflight_needs_the_file(tmp_path):
    project = bare_project(tmp_path)
    proc = run([*script("init_handoff.py"), "--project", str(project), "--from-preflight"])
    assert proc.returncode != 0 and "preflight" in (proc.stderr + proc.stdout).lower()
    assert not (project / "fable/handoff.json").exists()


def test_skill_md_documents_preflight():
    text = (SKILL / "SKILL.md").read_text()
    assert "preflight.py" in text and "--from-preflight" in text


# --------------------------------------------------------------------------- structured spec and jq

import copy
import shutil

JQ = shutil.which("jq")
needs_jq = pytest.mark.skipif(JQ is None, reason="jq is not installed")

GOOD_SPEC = {
    "schema_version": 1,
    "project": {"name": "slugify", "repository": None},
    "goal": {
        "job": "Implement slugify in src/slug.py so that it turns any human-readable title into a lowercase URL slug made of "
               "ASCII letters, digits and single hyphens. It handles accents, punctuation, repeated whitespace and empty input, "
               "and each of those cases is covered by a test in app_tests/.",
        "why": "The blog generator uses slugs as file names and URLs, so two different titles must not silently produce an empty "
               "slug. Correctness matters more than speed.",
        "sources": ["docs/GOAL.md"],
    },
    "current_state": {"summary": "slugify raises NotImplementedError.", "works": [], "half_done": [], "broken": ["slugify"], "baseline": None},
    "where_things_are": [{"path": "src/slug.py", "purpose": "the function"}],
    "commands": {"verify": VERIFY, "fast_check": None, "build": None, "run": None},
    "acceptance_criteria": [
        {"id": "c1", "text": "Accents are transliterated", "status": "open", "verified_by": "app_tests/test_slug.py", "source": "docs/SPEC.md:3"},
        {"id": "c2", "text": "Lowercase output", "status": "done", "verified_by": None, "source": None},
    ],
    "tasks": [{"text": "Implement slugify", "check": "pytest -k slug", "criteria": ["c1"]}, {"text": "Add edge case tests", "check": "pytest -k edge", "criteria": []}],
    "guardrails": {
        "pre_approved": ["Create and edit files under src/ and app_tests/", "Commit to the run branch"],
        "forbidden": [{"action": "Do not edit docs/SPEC.md", "reason": "it defines the job", "enforced_by": {"protected_paths": ["docs/SPEC.md"]}},
                      {"action": "Do not deploy", "reason": "production is out of reach", "enforced_by": {"blocked_bash_patterns": ["\\bmake\\s+deploy\\b"]}}],
        "out_of_scope": [{"text": "Packaging", "reason": "separate release"}],
    },
    "decisions": [{"decision": "Transliterate with unicodedata", "reason": "no third-party dependency", "source": "interview"}],
    "defaults": ["Keep functions small"],
    "open_questions": [],
    "traps": [{"text": "The slugify package broke on emoji", "instead": "Use unicodedata", "source": "docs/LESSONS.md:3"}],
    "practices_to_keep": [{"text": "Normalizing with NFKD worked", "source": None}],
    "done_extra": [],
    "run": {"branch": "fable/run-1", "model": "fable", "effort": "high", "permission_mode": "auto", "max_budget_usd": 40, "max_relaunches": 3},
    "sources": [{"path": "docs/GOAL.md", "role": "goal"}],
}


def write_spec(project, spec):
    (project / "fable").mkdir(exist_ok=True)
    path = project / "fable/handoff_spec.json"
    path.write_text(json.dumps(spec, indent=2))
    return path


def spec_check(project):
    proc = run([*script("spec_tool.py"), "check", "--project", str(project), "--json"])
    return proc, json.loads(proc.stdout)


def jq_query(path, expr, *flags):
    return run([JQ, "-L", str(SKILL / "assets/jq"), *flags, f'include "handoff"; {expr}', str(path)])


def broken_specs():
    """Spec variants, each breaking or warning on something different."""
    out = {"good": copy.deepcopy(GOOD_SPEC)}
    s = copy.deepcopy(GOOD_SPEC); s["goal"]["job"] = "Make slugify work."; out["thin job"] = s
    s = copy.deepcopy(GOOD_SPEC); s["goal"]["why"] = "Because."; out["thin why"] = s
    s = copy.deepcopy(GOOD_SPEC); s["goal"]["why"] += " Ask me before changing the public API, and wait for my approval."; out["human"] = s
    s = copy.deepcopy(GOOD_SPEC); s["commands"]["verify"] = "  "; out["no verify"] = s
    s = copy.deepcopy(GOOD_SPEC); s["open_questions"] = [{"question": "Keep numbers?", "source": "docs/SPEC.md:9"}]; out["open question"] = s
    s = copy.deepcopy(GOOD_SPEC); s["acceptance_criteria"][0]["verified_by"] = None; out["unverified"] = s
    s = copy.deepcopy(GOOD_SPEC); s["tasks"] = []; out["no tasks"] = s
    s = copy.deepcopy(GOOD_SPEC); s["tasks"][0]["criteria"] = ["c9"]; out["unknown criterion"] = s
    s = copy.deepcopy(GOOD_SPEC); s["guardrails"]["pre_approved"] = []; out["no pre-approved"] = s
    s = copy.deepcopy(GOOD_SPEC); s["guardrails"]["forbidden"][0]["enforced_by"] = {}; out["unenforced"] = s
    s = copy.deepcopy(GOOD_SPEC); s["guardrails"]["out_of_scope"] = []; out["no scope"] = s
    s = copy.deepcopy(GOOD_SPEC); s["run"]["branch"] = "main"; out["main"] = s
    s = copy.deepcopy(GOOD_SPEC); s["run"]["max_budget_usd"] = None; out["no budget"] = s
    s = copy.deepcopy(GOOD_SPEC); s["traps"][0]["instead"] = None; out["trap no instead"] = s
    s = copy.deepcopy(GOOD_SPEC); s["traps"] = []; s["practices_to_keep"] = []; s["decisions"] = []; out["no history"] = s
    s = copy.deepcopy(GOOD_SPEC); s["tasks"][1]["check"] = None; out["task without check"] = s
    s = copy.deepcopy(GOOD_SPEC); s["tasks"][0]["check"] = None; out["task proven by criterion"] = s
    return out


EXPECTED_PATHS = {
    "good": set(), "thin job": {"goal.job"}, "thin why": {"goal.why"}, "human": {"goal.why"}, "no verify": {"commands.verify"},
    "open question": {"open_questions[0]"}, "unverified": {"acceptance_criteria[0]"}, "no tasks": {"tasks"},
    "unknown criterion": {"tasks[0]"}, "no pre-approved": {"guardrails.pre_approved"}, "unenforced": {"guardrails.forbidden[0]"},
    "no scope": {"guardrails.out_of_scope"}, "main": {"run.branch"}, "no budget": {"run.max_budget_usd"},
    "trap no instead": {"traps[0]"}, "no history": {"traps", "decisions"},
    "task without check": {"tasks[1]"}, "task proven by criterion": set(),
}
WARN_ONLY = {"good", "no scope", "no budget", "trap no instead", "no history", "task without check", "task proven by criterion"}


def test_spec_schema_file_is_valid_json_schema():
    schema = json.loads((SKILL / "assets/schema/handoff_spec.schema.json").read_text())
    assert schema["type"] == "object" and "goal" in schema["required"] and "guardrails" in schema["properties"]
    assert run([*script("spec_tool.py"), "schema"]).stdout.strip().endswith("handoff_spec.schema.json")


@pytest.mark.parametrize("name", sorted(EXPECTED_PATHS))
def test_spec_tool_problems(tmp_path, name):
    project = tmp_path / "p"
    project.mkdir()
    write_spec(project, broken_specs()[name])
    proc, data = spec_check(project)
    assert data["schema_errors"] == []
    assert {p["path"] for p in data["problems"]} == EXPECTED_PATHS[name], data["problems"]
    assert (proc.returncode == 0) == (name in WARN_ONLY)
    assert data["ok"] is (name in WARN_ONLY)


@needs_jq
@pytest.mark.parametrize("name", sorted(EXPECTED_PATHS))
def test_jq_problems_match_python(tmp_path, name):
    project = tmp_path / "p"
    project.mkdir()
    path = write_spec(project, broken_specs()[name])
    _, data = spec_check(project)
    proc = jq_query(path, "problems")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == data["problems"]
    ready = jq_query(path, "ready", "-e")
    assert ready.returncode == (0 if name in WARN_ONLY else 1)


def test_spec_tool_schema_errors(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    bad = copy.deepcopy(GOOD_SPEC)
    bad["acceptance_criteria"][0]["status"] = "pending"
    bad["run"]["effort"] = 3
    bad["surprise"] = True
    del bad["guardrails"]["forbidden"][0]["reason"]
    write_spec(project, bad)
    proc, data = spec_check(project)
    assert proc.returncode == 1 and data["ok"] is False
    paths = {e["path"] for e in data["schema_errors"]}
    assert {"$.acceptance_criteria[0].status", "$.run.effort", "$.surprise", "$.guardrails.forbidden[0].reason"} <= paths
    text = run([*script("spec_tool.py"), "check", "--project", str(project)]).stdout
    assert "SCHEMA $.run.effort" in text and "NOT READY" in text


def test_spec_tool_missing_and_invalid_file(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    proc, data = spec_check(project)
    assert proc.returncode == 1 and "does not exist" in data["load_error"]
    (project / "fable").mkdir()
    (project / "fable/handoff_spec.json").write_text("{nope")
    proc, data = spec_check(project)
    assert proc.returncode == 1 and "not valid JSON" in data["load_error"]


def test_spec_tool_new(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    assert run([*script("spec_tool.py"), "new", "--project", str(project)]).returncode == 0
    spec = json.loads((project / "fable/handoff_spec.json").read_text())
    assert spec["schema_version"] == 1 and spec["open_questions"] == []
    assert run([*script("spec_tool.py"), "new", "--project", str(project)]).returncode == 2


@needs_jq
def test_jq_queries(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    spec = copy.deepcopy(GOOD_SPEC)
    spec["acceptance_criteria"].append({"id": "c3", "text": "Empty input raises", "status": "open", "verified_by": None, "source": None})
    spec["guardrails"]["forbidden"].append({"action": "Do not email", "reason": "x", "enforced_by": {}})
    spec["open_questions"] = [{"question": "Keep numbers?", "source": "docs/SPEC.md:9"}]
    path = write_spec(project, spec)
    summary = json.loads(jq_query(path, "summary").stdout)
    assert summary["ready"] is False and summary["criteria"] == {"open": 2, "done": 1} and summary["open_questions"] == 1
    assert jq_query(path, "unverified", "-r").stdout.strip() == "c3\tEmpty input raises"
    assert jq_query(path, "unenforced", "-r").stdout.strip() == "Do not email"
    assert jq_query(path, "open_questions", "-r").stdout.strip() == "Keep numbers?  (docs/SPEC.md:9)"
    assert jq_query(path, "criteria_without_task", "-r").stdout.strip() == "c3\tEmpty input raises"
    enforcement = json.loads(jq_query(path, "enforcement").stdout)
    assert enforcement == {"protected_paths": ["docs/SPEC.md"], "blocked_bash_patterns": ["\\bmake\\s+deploy\\b"]}
    assert "- [ ] Implement slugify (check: `pytest -k slug`)" in jq_query(path, "tasks_md", "-r").stdout
    assert "Instead: Use unicodedata" in jq_query(path, "traps_md", "-r").stdout
    assert jq_query(path, "criteria_tsv", "-r").stdout.splitlines()[0] == "c1\topen\tapp_tests/test_slug.py\tAccents are transliterated"
    lines = jq_query(path, "problems_text", "-r").stdout.splitlines()
    assert any(l.startswith("FAIL\topen_questions[0]\t") for l in lines)
    assert any(item["source"] == "docs/LESSONS.md:3" for item in json.loads(jq_query(path, "provenance").stdout))
    assert json.loads(jq_query(path, "sources_by_role").stdout) == {"goal": ["docs/GOAL.md"]}


def rendered_project(tmp_path, spec=None):
    project = bare_project(tmp_path)
    init(project)
    write_spec(project, spec or copy.deepcopy(GOOD_SPEC))
    return project


def render(project, *flags):
    return run([*script("render_handoff.py"), "--project", str(project), *flags])


def test_render_writes_the_package(tmp_path):
    project = rendered_project(tmp_path)
    proc = render(project)
    assert proc.returncode == 0, proc.stderr
    mission = (project / "fable/MISSION.md").read_text()
    for needle in ["# Mission: slugify", GOOD_SPEC["goal"]["job"], GOOD_SPEC["goal"]["why"], f"`{VERIFY}` exits 0",
                   "Do not edit docs/SPEC.md. Reason: it defines the job.", "Instead: Use unicodedata.",
                   "(checked by app_tests/test_slug.py)", "Create and edit files under src/ and app_tests/.", "Packaging. Reason: separate release."]:
        assert needle in mission, needle
    for heading in ["## Job", "## Why", "## Where things are", "## Guardrails", "## Decisions", "## Done"]:
        assert heading in mission
    state = (project / "fable/STATE.md").read_text()
    assert "- [ ] Implement slugify (check: `pytest -k slug`)" in state and "- [ ] Add edge case tests (check: `pytest -k edge`)" in state
    decisions = (project / "fable/DECISIONS.md").read_text()
    assert "Transliterate with unicodedata. Reason: no third-party dependency." in decisions
    assert "Keep doing: Normalizing with NFKD worked." in decisions and "- Keep functions small." in decisions
    assert re.search(r"## Open questions for the owner\s+None\.", decisions)
    cfg = read_cfg(project)
    assert cfg["verify_command"] == VERIFY and cfg["max_budget_usd"] == 40 and cfg["branch"] == "fable/run-1"
    assert "docs/SPEC.md" in cfg["protected_paths"] and "fable/handoff_spec.json" in cfg["protected_paths"]
    assert "\\bmake\\s+deploy\\b" in cfg["blocked_bash_patterns"]
    assert render(project, "--check").returncode == 0
    assert render(project).returncode == 0 and read_cfg(project)["protected_paths"].count("docs/SPEC.md") == 1, "rendering twice adds nothing twice"


def test_render_refuses_an_unready_spec(tmp_path):
    spec = copy.deepcopy(GOOD_SPEC)
    spec["open_questions"] = [{"question": "Keep numbers?", "source": None}]
    project = rendered_project(tmp_path, spec)
    before = (project / "fable/MISSION.md").read_text()
    proc = render(project)
    assert proc.returncode == 1 and "open_questions[0]" in proc.stderr
    assert (project / "fable/MISSION.md").read_text() == before


def test_render_needs_a_package(tmp_path):
    project = bare_project(tmp_path)
    write_spec(project, copy.deepcopy(GOOD_SPEC))
    assert render(project).returncode == 2


def test_render_check_and_stdout(tmp_path):
    project = rendered_project(tmp_path)
    render(project)
    (project / "fable/MISSION.md").write_text((project / "fable/MISSION.md").read_text() + "hand edit\n")
    proc = render(project, "--check")
    assert proc.returncode == 1 and "fable/MISSION.md" in proc.stdout
    out = render(project, "--stdout", "STATE.md")
    assert out.returncode == 0 and out.stdout.startswith("# Run ledger")


def signoff(project, by="Jane Owner"):
    return run([*script("spec_tool.py"), "signoff", "--project", str(project), "--by", by])


def test_rendered_package_passes_readiness(tmp_path):
    project = rendered_project(tmp_path)
    assert render(project).returncode == 0
    assert signoff(project).returncode == 0
    git(project, "switch", "-qc", "fable/run-1")
    commit_all(project, "package")
    proc, data = readiness(project)
    assert proc.returncode == 0, statuses(data)
    assert statuses(data)["handoff spec"] == "PASS"


def test_readiness_checks_the_spec(tmp_path):
    project = rendered_project(tmp_path)
    render(project)
    signoff(project)
    git(project, "switch", "-qc", "fable/run-1")
    commit_all(project, "package")
    (project / "fable/MISSION.md").write_text((project / "fable/MISSION.md").read_text() + "\nA hand edit.\n")
    commit_all(project, "drift")
    proc, data = readiness(project, "--allow-dirty")
    assert statuses(data)["handoff spec"] == "WARN"
    spec = copy.deepcopy(GOOD_SPEC)
    spec["open_questions"] = [{"question": "Keep numbers?", "source": None}]
    write_spec(project, spec)
    commit_all(project, "reopen")
    proc, data = readiness(project)
    assert proc.returncode == 1 and statuses(data)["handoff spec"] == "FAIL"


def test_readiness_without_a_spec_has_no_spec_row(tmp_path):
    project = prepared_project(tmp_path)
    _, data = readiness(project)
    assert "handoff spec" not in statuses(data)


def test_preflight_drafts_a_spec_and_never_overwrites_it(tmp_path):
    project = full_inputs_project(tmp_path)
    _, data = preflight(project, "--run-tests")
    path = project / "fable/handoff_spec.json"
    spec = json.loads(path.read_text())
    assert data["spec_written"] == "fable/handoff_spec.json"
    assert "every title becomes a unique" in spec["goal"]["job"] and "#" not in spec["goal"]["job"]
    open_ids = [c for c in spec["acceptance_criteria"] if c["status"] == "open"]
    assert [c["text"] for c in open_ids] == ["Accents are transliterated", "Empty input raises ValueError", "Repeated separators collapse"]
    assert all(c["source"].startswith("docs/SPEC.md:") for c in open_ids)
    assert spec["tasks"][0]["criteria"] == [open_ids[0]["id"]]
    assert any("numbers be kept" in q["question"] for q in spec["open_questions"])
    assert any("slugify package failed" in t["text"] for t in spec["traps"])
    assert spec["current_state"]["baseline"]["exit_code"] not in (0, None)
    assert any(f["enforced_by"]["protected_paths"] == ["app_tests/**"] for f in spec["guardrails"]["forbidden"])
    _, check = spec_check(project)
    assert check["schema_errors"] == [], "a preflight draft is schema-valid even before it is complete"
    path.write_text(path.read_text().replace('"why": ""', '"why": "edited"'))
    _, data = preflight(project)
    assert data["spec_written"] == "fable/handoff_spec.preflight.json"
    assert '"why": "edited"' in path.read_text()


# --------------------------------------------------------------------------- conversation logs

def _line(**kw):
    return json.dumps(kw)


def _user(uuid, parent, text, ts, session="sess-main", **extra):
    return _line(type="user", uuid=uuid, parentUuid=parent, sessionId=session, timestamp=ts, isSidechain=False,
                 message={"role": "user", "content": text}, **extra)


def _assistant(uuid, parent, blocks, ts, session="sess-main", **extra):
    return _line(type="assistant", uuid=uuid, parentUuid=parent, sessionId=session, timestamp=ts, isSidechain=False,
                 message={"role": "assistant", "content": blocks}, **extra)


def _result(uuid, parent, tool_id, text, ts, is_error=False, session="sess-main", **extra):
    return _line(type="user", uuid=uuid, parentUuid=parent, sessionId=session, timestamp=ts, isSidechain=False,
                 message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": is_error}]}, **extra)


def _bash(tool_id, command):
    return {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}


def write_logs(tmp_path):
    """A main session with a fork, an interrupt, a correction and an approval; a subagent with its meta file;
    a second, resumed session; and print-mode output."""
    logs = tmp_path / "logs"
    (logs / "sess-main" / "subagents").mkdir(parents=True)
    main = [
        _user("u1", None, "<system-reminder>ignore me</system-reminder>", "2026-01-01T10:00:00Z", isMeta=True),
        _user("u2", "u1", "I want the importer to accept the 2025 vendor export.", "2026-01-01T10:00:01Z"),
        _assistant("a1", "u2", [{"type": "text", "text": "Reading the parser."}, _bash("t1", "python3 -m pytest -q")], "2026-01-01T10:00:02Z"),
        _result("r1", "a1", "t1", "....F\nFAILED tests/test_parse.py::test_2025\n1 failed, 4 passed in 0.2s", "2026-01-01T10:00:03Z"),
        _assistant("a2", "r1", [{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "src/parse.py"}}], "2026-01-01T10:00:04Z"),
        _result("r2", "a2", "t2", "1\traise ValueError('bad')\n2\t# 3 failed attempts", "2026-01-01T10:00:05Z"),
        _assistant("a3", "r2", [_bash("t3", "rm -rf /")], "2026-01-01T10:00:06Z"),
        _result("r3", "a3", "t3", "Permission denied by the guard", "2026-01-01T10:00:07Z", is_error=True),
        _user("u3", "r3", "[Request interrupted by user for tool use]", "2026-01-01T10:00:08Z"),
        # The fork: two different human replies to the same message.
        _user("u4", "u3", "No, that's wrong. Do not touch the CSV path.", "2026-01-01T10:01:00Z"),
        _user("u5", "u3", "Let's keep the CSV path and add a JSON parser instead.", "2026-01-01T10:02:00Z"),
        _assistant("a4", "u5", [_bash("t4", "git add -A && git commit -qm \"Add the 2025 JSON parser\"")], "2026-01-01T10:03:00Z"),
        _result("r4", "a4", "t4", "", "2026-01-01T10:03:01Z"),
        _assistant("a5", "r4", [_bash("t5", "git commit -m \"$(cat <<'EOF'\nKeep per-line currency\n\nCo-Authored-By: x\nEOF\n)\"")], "2026-01-01T10:03:30Z"),
        _result("r5", "a5", "t5", "", "2026-01-01T10:03:31Z"),
        _assistant("a6", "r5", [{"type": "tool_use", "id": "t6", "name": "Agent", "input": {"description": "Search for currency code", "subagent_type": "fable-scout", "prompt": "find it"}}], "2026-01-01T10:04:00Z"),
        _result("r6", "a6", "t6", "Found it in src/money.py", "2026-01-01T10:05:00Z"),
        _assistant("a7", "r6", [_bash("t7", "python3 -m pytest -q"), {"type": "tool_use", "id": "t8", "name": "Write", "input": {"file_path": "src/parse_2025.py", "content": "x"}}], "2026-01-01T10:06:00Z"),
        _result("r7", "a7", "t7", "......\n6 passed in 0.3s", "2026-01-01T10:06:01Z"),
        _result("r8", "r7", "t8", "File created successfully", "2026-01-01T10:06:02Z"),
        _user("u6", "r8", "Perfect, that works. My key is sk-ant-abcdefghijklmnopqrstuvwxyz0123", "2026-01-01T10:07:00Z"),
        _assistant("a8", "u6", [{"type": "tool_use", "id": "t9", "name": "TaskCreate", "input": {"subject": "Write the JSON parser"}},
                                {"type": "tool_use", "id": "t10", "name": "TaskUpdate", "input": {"taskId": "1", "status": "completed"}},
                                {"type": "text", "text": "Done. The JSON parser is in and all 6 tests pass."}], "2026-01-01T10:08:00Z"),
        # The abandoned branch under u4 got one reply, earlier.
        _assistant("a9", "u4", [{"type": "text", "text": "Understood, reverting."}], "2026-01-01T10:01:30Z"),
        _line(type="system", subtype="compact_boundary", uuid="c1", parentUuid="a8", sessionId="sess-main", timestamp="2026-01-01T10:09:00Z"),
        "not json at all",
    ]
    (logs / "sess-main.jsonl").write_text("\n".join(l for l in main if l != "not json at all") + "\n")
    agent = [
        _line(type="user", uuid="s1", parentUuid=None, sessionId="sess-main", agentId="abc123", isSidechain=True, timestamp="2026-01-01T10:04:01Z",
              message={"role": "user", "content": "find the currency code"}),
        _line(type="assistant", uuid="s2", parentUuid="s1", sessionId="sess-main", agentId="abc123", isSidechain=True, timestamp="2026-01-01T10:04:30Z",
              message={"role": "assistant", "content": [{"type": "tool_use", "id": "st1", "name": "SubagentHandback", "input": {"message": "Currency codes live in src/money.py."}}]}),
    ]
    (logs / "sess-main" / "subagents" / "agent-abc123.jsonl").write_text("\n".join(agent) + "\n")
    (logs / "sess-main" / "subagents" / "agent-abc123.meta.json").write_text(json.dumps({"agentType": "fable-scout", "description": "Search for currency code", "toolUseId": "t6"}))
    resumed = [
        _user("v1", None, "Continue: add tests for unknown currency codes.", "2026-01-02T09:00:00Z", session="sess-two"),
        _assistant("w1", "v1", [_bash("x1", "npm test")], "2026-01-02T09:00:10Z", session="sess-two"),
        _result("y1", "w1", "x1", "Error: Cannot find module 'jest'", "2026-01-02T09:00:11Z", session="sess-two"),
    ]
    (logs / "-dash-named-sess-two.jsonl").write_text("\n".join(resumed) + "\n")
    stream = [
        _line(type="system", subtype="init", session_id="sess-print", uuid="p0"),
        _line(type="assistant", session_id="sess-print", uuid="p1", parent_tool_use_id=None,
              message={"role": "assistant", "content": [_bash("pt1", "make test")]}),
        _line(type="user", session_id="sess-print", uuid="p2", parent_tool_use_id=None,
              message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "pt1", "content": "All tests passed", "is_error": False}]}),
        _line(type="assistant", session_id="sess-print", uuid="p3", parent_tool_use_id="pt9",
              message={"role": "assistant", "content": [{"type": "text", "text": "subagent says hi"}]}),
        _line(type="stream_event", session_id="sess-print", uuid="p4", event={"x": 1}),
        _line(type="result", subtype="success", session_id="sess-print", total_cost_usd=1.0),
    ]
    (logs / "transcript-0.jsonl").write_text("\n".join(stream) + "\n")
    return logs


def conversation_context(project, *args, env=None):
    return run([*script("conversation_context.py"), "--project", str(project), *args], env=env)


@needs_jq
def test_conversation_context_extracts_everything(tmp_path):
    logs = write_logs(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    proc = conversation_context(project, "--logs", str(logs), "--json", "--no-write")
    assert proc.returncode == 0, proc.stderr
    c = json.loads(proc.stdout)
    assert len(c["files"]) == 5
    sessions = {s["session"]: s for s in c["sessions"]}
    assert set(sessions) == {"sess-main", "sess-two", "sess-print"}
    assert sessions["sess-main"]["interrupts"] == 1 and sessions["sess-main"]["errors"] == 1
    # intent
    main_intent = next(i for i in c["intent"] if i["session"] == "sess-main")
    assert main_intent["opening"].startswith("I want the importer"), "reminders are not intent"
    assert any("JSON parser" in g["text"] for g in main_intent["later_goals"])
    # forks
    assert len(c["forks"]) == 1 and c["forks"][0]["at"] == "u3"
    assert [b["uuid"] for b in c["forks"][0]["branches"]] == ["u4", "u5"]
    # subagents, linked to the call that started them
    agents = {a["agent"]: a for a in c["subagents"]}
    assert agents["abc123"]["type"] == "fable-scout" and agents["abc123"]["description"] == "Search for currency code"
    assert agents["abc123"]["result"] == "Currency codes live in src/money.py." and agents["abc123"]["parent_session"] == "sess-main"
    assert "pt9" in agents, "print-mode subagent output is grouped by the call that started it"
    # issues
    sources = {(i["source"], i["text"][:30]) for i in c["issues"]}
    assert ("failing output", "FAILED tests/test_parse.py::te") in sources
    assert any(i["source"] == "tool error" and i["tool"] == "Bash" for i in c["issues"])
    assert any(i["source"] == "interrupted by the user" for i in c["issues"])
    assert any(i["source"] == "user correction" and "Do not touch the CSV" in i["text"] for i in c["issues"])
    assert any(i["text"].startswith("Error: Cannot find module") for i in c["issues"])
    assert not any(i["tool"] == "Read" for i in c["issues"]), "file contents are not failures"
    # successes
    assert any(s["source"] == "passing output" and s["text"] == "6 passed in 0.3s" for s in c["successes"])
    assert any(s["text"] == "All tests passed" for s in c["successes"]), "print-mode output is read too"
    assert not any("1 failed" in s["text"] or "4 passed" in s["text"] for s in c["successes"]), "a run with failures is not a success"
    assert any(s["source"] == "user approval" for s in c["successes"])
    # achievements and progress
    assert [x["message"] for x in c["achievements"]["commits"]] == ["Add the 2025 JSON parser", "Keep per-line currency"]
    assert c["achievements"]["files_written"] == [{"path": "src/parse_2025.py", "edits": 1}]
    assert c["progress"]["tasks_created"] == ["Write the JSON parser"] and c["progress"]["tasks_completed"] == 1
    assert c["compactions"] == 1
    # the active branch ends on the newest reply, not on the abandoned branch
    assert c["latest"]["text"].startswith("Done. The JSON parser is in")
    # secrets
    assert "sk-ant-abc" not in proc.stdout and "[REDACTED]" in proc.stdout


@needs_jq
def test_conversation_context_markdown_and_files(tmp_path):
    logs = write_logs(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    proc = conversation_context(project, "--logs", str(logs))
    assert proc.returncode == 0, proc.stderr
    md = (project / "fable/CONTEXT.md").read_text()
    for heading in ["# Conversation context", "## Intent", "## Where it stands", "## Achievements", "## Progress",
                    "## Successes", "## Issues", "## Forks", "## Subagents", "## Sessions"]:
        assert heading in md, heading
    assert "the conversation branched" in md and "Let's keep the CSV path" in md
    assert "fable-scout, Search for currency code" in md
    assert "commit: Add the 2025 JSON parser" in md
    assert json.loads((project / "fable/context.json").read_text())["forks"]
    assert len(md.splitlines()) < 150, "the document stays concise"


@needs_jq
def test_conversation_context_finds_project_logs(tmp_path):
    logs = write_logs(tmp_path)
    project = tmp_path / "my.app"
    project.mkdir()
    home = tmp_path / "claude-home"
    encoded = re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve()))
    (home / "projects").mkdir(parents=True)
    shutil.copytree(logs, home / "projects" / encoded)
    proc = conversation_context(project, "--project-logs", "--json", "--no-write", env={"CLAUDE_CONFIG_DIR": str(home)})
    assert proc.returncode == 0, proc.stderr
    assert len(json.loads(proc.stdout)["sessions"]) == 3


def test_conversation_context_errors(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    if JQ:
        assert conversation_context(project, "--logs", str(tmp_path / "empty")).returncode == 1
        assert conversation_context(project).returncode == 1
    bare_path = tmp_path / "nojq"
    bare_path.mkdir()
    (bare_path / "uv").symlink_to(shutil.which("uv"))
    proc = run([*UV_SCRIPT, str(SKILL / "scripts/conversation_context.py"), "--project", str(project), "--logs", str(tmp_path)],
               env={"PATH": str(bare_path)})
    assert proc.returncode == 2 and "jq is not installed" in proc.stderr


@needs_jq
def test_preflight_reads_conversations(tmp_path):
    logs = write_logs(tmp_path)
    project = full_inputs_project(tmp_path)
    proc, data = preflight(project, "--conversations", str(logs))
    rows = by_input(data)
    assert "fable/CONTEXT.md" in rows["history"]["sources"] and "fable/CONTEXT.md" in rows["state"]["sources"]
    assert data["conversations"]["sessions"] == 3 and data["conversations"]["forks"] == 1
    assert (project / "fable/CONTEXT.md").exists()
    assert "## Conversations" in (project / "fable/PREFLIGHT.md").read_text()
    spec = json.loads((project / "fable/handoff_spec.json").read_text())
    assert {"path": "fable/CONTEXT.md", "role": "history"} in spec["sources"]
    assert any((t["source"] or "").startswith("fable/CONTEXT.md:") for t in spec["traps"]), "issues from the logs become trap candidates"


def test_preflight_reports_unreadable_conversations(tmp_path):
    project = full_inputs_project(tmp_path)
    _, data = preflight(project, "--conversations", str(tmp_path / "missing-logs"))
    assert any(g["input"] == "history" and "not read" in g["text"] for g in data["gaps"])


# --------------------------------------------------------------------------- improvement loop 1: owner sign-off, previous run, lessons, evidence

def test_owner_brief_and_signoff(tmp_path):
    project = rendered_project(tmp_path)
    assert run([*script("spec_tool.py"), "status", "--project", str(project)]).returncode == 1
    proc = run([*script("spec_tool.py"), "brief", "--project", str(project)])
    assert proc.returncode == 0, proc.stderr
    brief = (project / "fable/OWNER_BRIEF.md").read_text()
    for needle in ["# Owner brief: slugify", GOOD_SPEC["goal"]["job"], "It may do this without asking", "It is blocked from doing this",
                   "Do not edit docs/SPEC.md", "Decided in advance", "Transliterate with unicodedata", "$40.00", "fable/run-1", f"`{VERIFY}` exits 0"]:
        assert needle in brief, needle
    assert signoff(project, "Jane Owner").returncode == 0
    spec = json.loads((project / "fable/handoff_spec.json").read_text())
    assert spec["owner_signoff"]["by"] == "Jane Owner" and len(spec["owner_signoff"]["spec_sha256"]) == 64
    status = run([*script("spec_tool.py"), "status", "--project", str(project)])
    assert status.returncode == 0 and "Jane Owner" in status.stdout
    _, data = spec_check(project)
    assert data["schema_errors"] == [], "the sign-off is part of the schema"
    # Reformatting does not void it; a real edit does.
    (project / "fable/handoff_spec.json").write_text(json.dumps(spec, indent=4, sort_keys=True))
    assert run([*script("spec_tool.py"), "status", "--project", str(project)]).returncode == 0
    spec["goal"]["why"] += " Speed is irrelevant."
    write_spec(project, spec)
    stale = run([*script("spec_tool.py"), "status", "--project", str(project)])
    assert stale.returncode == 1 and stale.stdout.startswith("STALE")


def test_brief_and_signoff_refuse_an_unready_spec(tmp_path):
    spec = copy.deepcopy(GOOD_SPEC)
    spec["open_questions"] = [{"question": "Keep numbers?", "source": None}]
    project = rendered_project(tmp_path, spec)
    assert run([*script("spec_tool.py"), "brief", "--project", str(project)]).returncode == 1
    assert signoff(project).returncode == 1
    assert "owner_signoff" not in json.loads((project / "fable/handoff_spec.json").read_text())


def test_readiness_requires_a_current_signoff(tmp_path):
    project = rendered_project(tmp_path)
    render(project)
    git(project, "switch", "-qc", "fable/run-1")
    commit_all(project, "package")
    proc, data = readiness(project)
    assert proc.returncode == 1 and statuses(data)["handoff spec"] == "FAIL"
    assert "signed off" in next(r["detail"] for r in data["rows"] if r["check"] == "handoff spec")
    signoff(project)
    commit_all(project, "signoff")
    assert readiness(project)[0].returncode == 0
    spec = json.loads((project / "fable/handoff_spec.json").read_text())
    spec["run"]["max_budget_usd"] = 400
    write_spec(project, spec)
    render(project)
    commit_all(project, "edit after signoff")
    proc, data = readiness(project)
    assert proc.returncode == 1 and "changed after" in next(r["detail"] for r in data["rows"] if r["check"] == "handoff spec")


def test_post_run_task_evidence(tmp_path):
    project = finished_run(tmp_path)
    out = review(project).stdout
    assert "## Evidence for checked tasks" in out
    assert "- proven: Implement slugify" in out
    assert "- unproven: Add edge case tests" in out, "no commit or file mentions edge cases"


def test_post_run_writes_lessons(tmp_path):
    project = finished_run(tmp_path)
    (project / "fable/DECISIONS.md").write_text(DECISIONS.replace("## Made during the run\n", "## Made during the run\n\n- Kept the regex simple. Reason: speed is irrelevant.\n")
                                                .replace("## Left for the owner\n", "## Left for the owner\n\n- Publishing to PyPI was skipped.\n"))
    commit_all(project, "decisions")
    transcript = project / "fable/.run/transcript-0.jsonl"
    blocked = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "is_error": True,
               "content": "Blocked by the handoff guard: the command contains `sudo x`, which matches the pattern `\\bsudo\\b` in blocked_bash_patterns."}]}}
    transcript.write_text(transcript.read_text() + "\n".join(json.dumps(blocked) for _ in range(3)) + "\n")
    out = review(project).stdout
    assert "## Guard blocks" in out and "3 x `\\bsudo\\b`" in out
    assert "## Proposed for the next run" in out
    lessons = json.loads((project / "fable/.run/lessons.json").read_text())["proposals"]
    kinds = {(p["kind"], p["text"][:40]) for p in lessons}
    assert ("decision", "Kept the regex simple. Reason: speed is ") in kinds
    assert ("question", "Publishing to PyPI was skipped.") in kinds
    assert any(p["kind"] == "question" and "guard blocked 3" in p["text"] for p in lessons)
    assert any(p["kind"] == "question" and "Add edge case tests" in p["text"] for p in lessons), "unproven tasks become questions"


def test_preflight_carries_the_previous_run_into_the_next_spec(tmp_path):
    project = full_inputs_project(tmp_path)
    (project / "fable/.run").mkdir(parents=True)
    (project / "fable/.run/lessons.json").write_text(json.dumps({"proposals": [
        {"kind": "decision", "text": "Kept the regex simple", "source": "fable/DECISIONS.md (Made during the run)"},
        {"kind": "trap", "text": "The previous run weakened tests", "instead": "Protect the tests", "source": "post_run_report"},
        {"kind": "question", "text": "Publishing was skipped. Publish now?", "source": "fable/DECISIONS.md (Left for the owner)"}]}))
    (project / "fable/REPORT.md").write_text("# Report\n\nThe parser failed on emoji; fixed with NFKD.\n")
    _, data = preflight(project)
    spec = json.loads((project / "fable/handoff_spec.json").read_text())
    assert any(d["decision"] == "Kept the regex simple" and "previous run" in d["reason"] for d in spec["decisions"])
    assert any(t["text"] == "The previous run weakened tests" and t["instead"] == "Protect the tests" for t in spec["traps"])
    assert any(q["question"] == "Publishing was skipped. Publish now?" for q in spec["open_questions"])
    assert data["previous_run"]["lessons"] == 3 and "fable/REPORT.md" in data["previous_run"]["documents"]
    assert "fable/REPORT.md" in by_input(data)["history"]["sources"]
    assert "## Previous run" in (project / "fable/PREFLIGHT.md").read_text()
    _, again = preflight(project, "--no-previous-run")
    assert "previous_run" not in again


def test_preflight_reads_previous_decisions_without_lessons(tmp_path):
    project = full_inputs_project(tmp_path)
    (project / "fable").mkdir(exist_ok=True)
    (project / "fable/DECISIONS.md").write_text(DECISIONS.replace("## Left for the owner\n", "## Left for the owner\n\n- Deploy was skipped.\n"))
    _, data = preflight(project)
    spec_name = data["spec_written"]
    spec = json.loads((project / spec_name).read_text())
    assert any(q["question"] == "Deploy was skipped." for q in spec["open_questions"])


# --------------------------------------------------------------------------- improvement loop 2: checks that prove tasks

def test_stop_gate_runs_each_checked_tasks_own_check(tmp_path):
    project = prepared_project(tmp_path)
    (project / "fable/STATE.md").write_text(STATE.replace("- [ ] Implement slugify", "- [x] Implement slugify (check: `python3 -c 'import sys; sys.exit(3)'`)")
                                            .replace("- [ ] Add edge case tests", "- [x] Add edge case tests (check: plain words are not run)"))
    (project / "src/slug.py").write_text(SOLUTION)
    (project / "fable/REPORT.md").write_text("done\n")
    proc = gate(project, dry=True)
    assert proc.returncode == 2
    assert "checked task fails its own check" in proc.stderr and "Implement slugify" in proc.stderr and "exit code 3" in proc.stderr
    assert "plain words" not in proc.stderr, "a check without backticks is not run"
    state = (project / "fable/STATE.md").read_text().replace("sys.exit(3)", "sys.exit(0)")
    (project / "fable/STATE.md").write_text(state)
    assert gate(project, dry=True).returncode == 0


def test_stop_gate_ignores_checks_on_open_tasks_and_in_code_fences(tmp_path):
    project = prepared_project(tmp_path)
    (project / "fable/STATE.md").write_text(STATE.replace("- [ ] Implement slugify", "- [ ] Implement slugify (check: `false`)")
                                            .replace("## Notes for a resuming session", "## Notes for a resuming session\n\n```\n- [x] example (check: `false`)\n```"))
    proc = gate(project, dry=True)
    assert proc.returncode == 2 and "unchecked task" in proc.stderr and "own check" not in proc.stderr


@needs_jq
def test_conversation_signals_carry_the_command_to_rerun(tmp_path):
    logs = write_logs(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    c = json.loads(conversation_context(project, "--logs", str(logs), "--json", "--no-write").stdout)
    failing = next(i for i in c["issues"] if i["source"] == "failing output" and i["text"].startswith("FAILED"))
    assert failing["command"] == "python3 -m pytest -q"
    passing = next(s for s in c["successes"] if s["text"] == "6 passed in 0.3s")
    assert passing["command"] == "python3 -m pytest -q"
    md = conversation_context(project, "--logs", str(logs), "--no-write").stdout
    assert "rerun: `python3 -m pytest -q`" in md


# --------------------------------------------------------------------------- improvement loop 3: conversations feed the launcher and the review

def _say_and_fail_stub(stub):
    """Make the stand-in CLI print an assistant message and a failing tool result before idling."""
    text = stub.read_text()
    extra = (
        'print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Halfway: the parser handles ASCII, accents are next."}]}}))\n'
        'print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}}, {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "pytest -q"}}]}}))\n'
        'print(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "..F\\nFAILED tests/test_slug.py::test_accents\\n1 failed, 2 passed"}]}}))\n'
    )
    stub.write_text(text.replace('if step == "crash":', extra + 'if step == "crash":'))


def test_relaunch_tells_the_next_session_where_the_last_stopped(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["idle", "work"])
    _say_and_fail_stub(stub)
    assert launch(project).returncode == 0
    prompt = flag(stub_calls(stub)[1], "-p")
    assert "--continue" in stub_calls(stub)[1]
    assert "Where the previous session stopped (attempt 0)" in prompt
    assert "Halfway: the parser handles ASCII" in prompt
    assert "FAILED tests/test_slug.py::test_accents" in prompt
    assert "## Job" not in prompt


def test_relaunch_after_a_crash_includes_the_error_log(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["crash", "work"])
    assert launch(project).returncode == 0
    prompt = flag(stub_calls(stub)[1], "-p")
    assert "simulated crash" in prompt and "## Job" in prompt


@needs_jq
def test_post_run_reads_the_runs_conversation(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["idle", "work"])
    _say_and_fail_stub(stub)
    assert launch(project).returncode == 0
    # A second identical failure in the first transcript makes it recurring.
    t0 = project / "fable/.run/transcript-0.jsonl"
    t0.write_text(t0.read_text() + json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2",
                  "content": "FAILED tests/test_slug.py::test_accents\n1 failed, 2 passed"}]}}) + "\n")
    out = review(project).stdout
    assert "## What the run's conversation shows" in out
    assert "FAILED tests/test_slug.py::test_accents" in out
    lessons = json.loads((project / "fable/.run/lessons.json").read_text())["proposals"]
    assert any(p["kind"] == "trap" and "same failure" in p["text"] for p in lessons)


# --------------------------------------------------------------------------- team lead, research, look-back

def test_operating_rules_make_fable_the_team_lead():
    rules = (SKILL / "assets/templates/OPERATING_RULES.md").read_text()
    for needle in ["## Work as a team lead", "fable-scout", "fable-worker", "fable-builder", "fable-specialist",
                   "[route: fable-worker]", "Verify every result yourself", "## Cross-check before you finish", "mcp__infranodus"]:
        assert needle in rules, needle


def test_routes_render_into_the_ledger(tmp_path):
    spec = copy.deepcopy(GOOD_SPEC)
    spec["tasks"][0]["route"] = "fable-specialist"
    spec["tasks"][1]["route"] = "fable-worker"
    project = rendered_project(tmp_path, spec)
    assert render(project).returncode == 0, render(project).stderr
    state = (project / "fable/STATE.md").read_text()
    assert "- [ ] Implement slugify (check: `pytest -k slug`) [route: fable-specialist]" in state
    assert "[route: fable-worker]" in state
    bad = copy.deepcopy(GOOD_SPEC)
    bad["tasks"][0]["route"] = "intern"
    write_spec(project, bad)
    assert any(e["path"] == "$.tasks[0].route" for e in spec_check(project)[1]["schema_errors"])


@needs_jq
def test_jq_routing(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    spec = copy.deepcopy(GOOD_SPEC)
    spec["tasks"][0]["route"] = "fable-worker"
    path = write_spec(project, spec)
    assert json.loads(jq_query(path, "routing").stdout) == {"fable-worker": ["Implement slugify"], "unrouted": ["Add edge case tests"]}
    assert "[route: fable-worker]" in jq_query(path, "tasks_md", "-r").stdout


def _research_logs(tmp_path):
    logs = tmp_path / "rlogs"
    logs.mkdir()
    lines = [
        _user("h1", None, "Find out how jq modules are loaded.", "2026-02-01T10:00:00Z"),
        _assistant("a1", "h1", [{"type": "tool_use", "id": "w1", "name": "WebSearch", "input": {"query": "jq module search path -L import"}}], "2026-02-01T10:00:01Z"),
        _result("r1", "a1", "w1", "Web search results\njq modules are found on the -L search path and loaded with include or import.", "2026-02-01T10:00:02Z"),
        _assistant("a2", "r1", [{"type": "tool_use", "id": "w2", "name": "WebFetch", "input": {"url": "https://jqlang.org/manual/", "prompt": "modules"}}], "2026-02-01T10:00:03Z"),
        _result("r2", "a2", "w2", "Request failed with status 503", "2026-02-01T10:00:04Z", is_error=True),
        _assistant("a3", "r2", [{"type": "text", "text": "Conclusion: use -L with the module directory and include it."}], "2026-02-01T10:00:05Z"),
        _assistant("a4", "a3", [{"type": "tool_use", "id": "w3", "name": "mcp__exa__web_search_exa", "input": {"query": "jq module search path -L import"}}], "2026-02-01T10:01:00Z"),
        _result("r3", "a4", "w3", "Exa results: the -L option prepends a directory to the module search list", "2026-02-01T10:01:01Z"),
        _assistant("a5", "r3", [{"type": "tool_use", "id": "w4", "name": "Agent", "input": {"description": "Research competing tools", "prompt": "compare jq and yq"}}], "2026-02-01T10:02:00Z"),
        _result("r4", "a5", "w4", "yq wraps jq syntax for YAML documents and works on JSON too", "2026-02-01T10:03:00Z"),
        _assistant("a6", "r4", [{"type": "tool_use", "id": "w5", "name": "Read", "input": {"file_path": "README.md"}}], "2026-02-01T10:04:00Z"),
    ]
    (logs / "s.jsonl").write_text("\n".join(lines) + "\n")
    return logs


@needs_jq
def test_conversation_research_topics(tmp_path):
    logs = _research_logs(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    c = json.loads(conversation_context(project, "--logs", str(logs), "--json", "--no-write").stdout)
    tools = [r["tool"] for r in c["research"]]
    assert tools == ["WebSearch", "WebFetch", "mcp__exa__web_search_exa", "Agent"], "Read is not research"
    search = c["research"][0]
    assert search["query"] == "jq module search path -L import" and search["ok"] is True
    assert search["result"].startswith("jq modules are found on the -L search path")
    assert search["concluded"].startswith("Conclusion: use -L")
    assert c["research"][1]["ok"] is False
    topics = {t["topic"]: t for t in c["research_topics"]}
    assert topics["module search path import"]["lookups"] == 2, "the same query through two tools is one topic"
    assert topics["jqlang.org manual"]["failed"] == 1
    md = conversation_context(project, "--logs", str(logs), "--no-write").stdout
    assert "## Research" in md and "found: yq wraps jq syntax" in md and "1 failed" in md


def test_system_review(tmp_path):
    project = rendered_project(tmp_path)
    (project / "fable/.run").mkdir(exist_ok=True)
    (project / "fable/preflight.json").write_text(json.dumps({
        "inputs": [{"input": "history", "status": "MISSING", "fix": "Ask the owner what failed.", "detail": ""}],
        "gaps": [{"severity": "BLOCKING", "input": "evals", "text": "The test command already passes."},
                 {"severity": "REVIEW", "input": "x", "text": "a"}, {"severity": "REVIEW", "input": "y", "text": "b"},
                 {"severity": "REVIEW", "input": "z", "text": "c"}]}))
    (project / "fable/.run/readiness.json").write_text(json.dumps({"rows": [{"status": "WARN", "check": "budget", "detail": "no cap"}]}))
    (project / "fable/context.json").write_text(json.dumps({
        "issues": [{"source": "failing output", "count": 4, "text": "FAILED test_x", "command": "pytest -q"}],
        "research_topics": [{"topic": "vendor api docs", "failed": 2}], "forks": [{"at": "u1"}]}))
    (project / "fable/.run/lessons.json").write_text(json.dumps({"proposals": [
        {"kind": "question", "text": "The guard blocked 5 tool calls with the rule 'x'."},
        {"kind": "question", "text": "The previous run checked off 'y' but no commit or changed file matches it."}]}))
    write_cfg(project, audit_accept=["CLAUDE.md:absolute"])
    proc = run([*script("system_review.py"), "--project", str(project), "--json"])
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout)
    before = " ".join(i["text"] for i in r["before_launch"])
    assert "already passes" in before and "budget" in before and "branched 1 time" in before and "No task carries a route" in before
    proj = " ".join(i["text"] for i in r["project"])
    assert "history input is MISSING" in proj and "recurred 4 times" in proj and "rerun: pytest -q" in proj
    assert "vendor api docs" in proj and "CLAUDE.md:absolute" in proj
    skill = " ".join(i["text"] for i in r["skill"])
    assert "guard rule blocked" in skill and "no evidence" in skill and "3 items to human review" in skill
    assert all(i["source"] for k in r for i in r[k])
    md = (project / "fable/IMPROVEMENTS.md").read_text()
    for heading in ["## Before launch", "## For the project", "## For the fable-handoff skill", "## Look for what the files cannot show"]:
        assert heading in md
    assert run([*script("system_review.py"), "--project", str(project), "--strict"]).returncode == 1
    assert run([*script("system_review.py"), "--project", str(tmp_path / "nowhere")]).returncode == 2


# --------------------------------------------------------------------------- cross-checked against the official docs

def test_guard_checks_powershell_and_notebook_file_path(guarded):
    assert guard(guarded, "PowerShell", command="Remove-Item -Force fable/MISSION.md; rm fable/MISSION.md").returncode == 2
    assert guard(guarded, "PowerShell", command="git push --force").returncode == 2
    assert guard(guarded, "PowerShell", command="Get-ChildItem src").returncode == 0
    assert guard(guarded, "NotebookEdit", file_path="locked/n.ipynb").returncode == 2


def test_init_registers_powershell(tmp_path):
    project = bare_project(tmp_path)
    init(project)
    matcher = json.loads((project / ".claude/settings.json").read_text())["hooks"]["PreToolUse"][0]["matcher"]
    assert "PowerShell" in matcher.split("|")


def test_readiness_warns_on_a_model_alias(tmp_path):
    project = prepared_project(tmp_path, model="fable")
    proc, data = readiness(project)
    assert proc.returncode == 0
    row = next(r for r in data["rows"] if r["check"] == "model")
    assert row["status"] == "WARN" and "Fable 5.1" in row["detail"]
    project2 = prepared_project(tmp_path, "p2")
    assert statuses(readiness(project2)[1])["model"] == "PASS"


@pytest.mark.skipif(shutil.which("claude") is None, reason="the Claude CLI is not installed")
def test_readiness_checks_cli_flags_against_the_installed_cli(tmp_path):
    project = prepared_project(tmp_path)
    assert statuses(readiness(project)[1]).get("cli flags") == "PASS"


def test_readiness_validates_mcp_config(tmp_path):
    project = prepared_project(tmp_path, mcp_config="fable/mcp.json")
    proc, data = readiness(project)
    assert proc.returncode == 1 and statuses(data)["mcp config"] == "FAIL"
    (project / "fable/mcp.json").write_text(json.dumps({"mcpServers": {"infranodus": {"type": "http", "url": "https://mcp.example/infranodus"}}}))
    commit_all(project, "mcp")
    proc, data = readiness(project)
    assert proc.returncode == 0 and statuses(data)["mcp config"] == "PASS"


def test_launch_refuses_without_hook_scripts(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["work"])
    (project / ".claude/hooks/fable_stop_gate.py").unlink()
    proc = launch(project)
    assert proc.returncode == 2 and "fable_stop_gate.py" in (proc.stderr + proc.stdout)
    assert stub_calls(stub) == []


def test_launch_passes_mcp_config_and_logs_failed_servers(tmp_path):
    stub = make_stub(tmp_path, ["work"])
    stub.write_text(stub.read_text().replace('if step == "crash":', 'print(json.dumps({"type": "system", "subtype": "init", "mcp_servers": [{"name": "infranodus", "status": "failed"}, {"name": "ok", "status": "connected"}]}))\nif step == "crash":'))
    project = prepared_project(tmp_path, claude_binary=str(stub), mcp_config="fable/mcp.json")
    (project / "fable/mcp.json").write_text(json.dumps({"mcpServers": {"infranodus": {"type": "http", "url": "https://mcp.example"}}}))
    commit_all(project, "mcp")
    assert readiness(project)[0].returncode == 0
    proc = launch(project)
    assert proc.returncode == 0
    assert flag(stub_calls(stub)[0], "--mcp-config") == "fable/mcp.json"
    log = json.loads((project / "fable/.run/launch_log.json").read_text())
    assert log[0]["mcp_failed"] == ["infranodus"]
    assert "infranodus" in proc.stdout + proc.stderr


def test_launch_starts_fresh_when_the_context_changed(tmp_path):
    project, stub = ready_with_stub(tmp_path, ["idle", "work"])
    text = stub.read_text().replace('if step == "crash":', 'if n == 0:\n    pathlib.Path("CLAUDE.md").write_text("changed during the run\\n")\nif step == "crash":')
    stub.write_text(text)
    assert launch(project).returncode == 0
    second = stub_calls(stub)[1]
    assert "--continue" not in second, "a changed instruction file means the old conversation cannot continue"
    assert "## Job" in flag(second, "-p")


def test_skill_md_uses_skill_dir_and_stays_short():
    text = (SKILL / "SKILL.md").read_text()
    assert '"${CLAUDE_SKILL_DIR}/scripts/' in text
    assert "python3 scripts/" not in text
    assert len(text) / 4 < 5500, "keep SKILL.md near the 5,000-token guidance"
    assert "compatibility:" in text.split("---")[1]
    assert "references/sources.md" in text


def test_sources_reference_names_the_official_pages():
    text = (SKILL / "references/sources.md").read_text()
    for url in ["code.claude.com/docs/en/hooks", "code.claude.com/docs/en/cli-reference", "code.claude.com/docs/en/sub-agents",
                "code.claude.com/docs/en/permission-modes", "prompting-claude-fable-5-2", "optimizing-for-cost-and-intelligence",
                "agent-skills/best-practices"]:
        assert url in text, url


# --------------------------------------------------------------------------- 1.1: uv, owner rules, interview, opt-in settings

BROKEN_VERIFY = "uv run --quiet --no-project python -c 'import no_such_module_for_fable_handoff'"


def test_every_script_is_a_uv_script_and_nothing_calls_bare_python():
    sources = [*SKILL.glob("scripts/*.py"), *SKILL.glob("assets/**/*.py")]
    for path in sources:
        text = path.read_text()
        assert text.startswith("#!/usr/bin/env -S uv run --script\n# /// script\n"), path.name
        assert 'requires-python = ">=3.11"' in text.split("# ///", 2)[1], path.name
        assert "sys.executable" not in text, path.name
    docs = [*SKILL.rglob("*.md"), SKILL.parent / "README.md", SKILL.parent / "install.sh"]
    for path in docs:
        if "evals" in path.parts:
            continue
        text = path.read_text()
        assert not re.search(r"(?<![\w-])python3? (?:-m |\S+\.py)", text), path.name
        assert not re.search(r"(?<![\w-])pip3? install", text), path.name


def test_hooks_are_registered_through_uv(tmp_path):
    project = bare_project(tmp_path)
    init(project)
    settings = json.loads((project / ".claude/settings.json").read_text())
    commands = [h["command"] for groups in settings["hooks"].values() for g in groups for h in g["hooks"]]
    assert len(commands) == 3 and all(c.startswith("uv run --quiet --script ") for c in commands)


def test_readiness_fails_when_verify_cannot_run(tmp_path):
    project = prepared_project(tmp_path, verify_command=BROKEN_VERIFY)
    commit_all(project, "broken verify")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "verify")
    assert row["status"] == "FAIL" and "cannot run here" in row["detail"], row


def test_stop_gate_names_a_verify_that_cannot_run(tmp_path):
    project = prepared_project(tmp_path, verify_command=BROKEN_VERIFY)
    check_tasks(project)
    (project / "fable/REPORT.md").write_text("done\n")
    proc = gate(project)
    assert proc.returncode == 2 and "could not even start" in proc.stderr and "No module named" in proc.stderr


OWNER_CLAUDE = """# Rules

- Do not implement anything until the plan is approved by me.
- Think step by step and explain your reasoning.
- Never edit a test to make it pass.
- One writer at a time; take the writer lock first.
- Record every decision.
- Use type hints. (owner rule)
"""


def audit_cmd(project, *extra):
    return run([*script("audit_rules.py"), "--project", str(project), *extra])


def test_owner_rules_are_found_and_never_proposed(tmp_path):
    project = bare_project(tmp_path)
    (project / "CLAUDE.md").write_text(OWNER_CLAUDE + "- Commit only when I say so.\n")
    data = json.loads(audit_cmd(project, "--json").stdout)
    kinds = {o["kind"]: o["effect"] for o in data["owner_rules"]}
    assert kinds == {"tests-are-not-edited-to-pass": "honored", "one-writer": "honored", "record-decisions": "honored",
                     "marked": "honored", "commit-by-owner": "blocks"}
    owner_lines = {o["line"] for o in data["owner_rules"]}
    assert not any(f["line"] in owner_lines for f in data["findings"])
    proc = audit_cmd(project, "--propose")
    assert proc.returncode == 0 and "Nothing was edited" in proc.stdout
    proposal = json.loads((project / "fable/rules_proposal.json").read_text())
    assert {e["line"] for e in proposal["edits"]} == {3, 4}
    assert not owner_lines & {e["line"] for e in proposal["edits"]}


def test_audit_edits_nothing_until_the_owner_approves(tmp_path):
    project = bare_project(tmp_path)
    (project / "CLAUDE.md").write_text(OWNER_CLAUDE)
    audit_cmd(project, "--propose")
    assert (project / "CLAUDE.md").read_text() == OWNER_CLAUDE
    assert "-- Think step by step" in (project / "fable/RULES_PROPOSAL.md").read_text().replace("- -", "--")
    assert audit_cmd(project, "--apply").returncode == 2, "applying needs the approver's name"
    assert (project / "CLAUDE.md").read_text() == OWNER_CLAUDE
    proc = audit_cmd(project, "--apply", "--approved-by", "Jane Owner")
    assert proc.returncode == 0, proc.stderr
    after = (project / "CLAUDE.md").read_text()
    assert "- In interactive sessions, do not implement anything until the plan is approved by me." in after
    assert "Think step by step" not in after
    for kept in ["Never edit a test to make it pass.", "One writer at a time", "Record every decision.", "Use type hints. (owner rule)"]:
        assert kept in after
    assert json.loads((project / "fable/rules_proposal.json").read_text())["approved_by"] == "Jane Owner"


def test_apply_refuses_when_the_file_changed_after_the_proposal(tmp_path):
    project = bare_project(tmp_path)
    (project / "CLAUDE.md").write_text(OWNER_CLAUDE)
    audit_cmd(project, "--propose")
    (project / "CLAUDE.md").write_text(OWNER_CLAUDE + "- New line.\n")
    proc = audit_cmd(project, "--apply", "--approved-by", "Jane Owner")
    assert proc.returncode == 2 and "changed after the proposal" in proc.stderr
    assert (project / "CLAUDE.md").read_text() == OWNER_CLAUDE + "- New line.\n"


def test_readiness_refuses_an_owner_rule_the_run_cannot_follow(tmp_path):
    project = prepared_project(tmp_path)
    (project / "CLAUDE.md").write_text("# Rules\n\n- Commit only when I say so.\n")
    commit_all(project, "owner rule")
    proc, data = readiness(project)
    assert statuses(data)["owner rules"] == "FAIL" and proc.returncode != 0
    assert (project / "CLAUDE.md").read_text() == "# Rules\n\n- Commit only when I say so.\n"


def test_readiness_passes_owner_rules_the_run_honors(tmp_path):
    project = prepared_project(tmp_path)
    (project / "CLAUDE.md").write_text("# Rules\n\n- Never edit a test to make it pass.\n- One writer at a time.\n")
    commit_all(project, "owner rules")
    _, data = readiness(project)
    assert statuses(data)["owner rules"] == "PASS"


QUESTION = {
    "question": "Should slugs keep numbers?",
    "topic": "Numbers in URL slugs",
    "what": "A slug is the readable part of a post's web address, made from its title.",
    "why_it_matters": "Titles like '10 tips' lose meaning without the number, and changing it later breaks shared links.",
    "options": [{"choice": "Keep numbers", "what_happens": "'10 Tips' becomes 10-tips."},
                {"choice": "Drop numbers", "what_happens": "'10 Tips' becomes tips, and two posts can collide."}],
    "recommendation": "Keep numbers",
    "recommendation_reason": "It keeps titles distinct and readable.",
}


def interview(project, *extra, stdin=None):
    return run([*script("decision_interview.py"), "--project", str(project), *extra], stdin=stdin)


def test_interview_refuses_questions_not_in_plain_words(tmp_path):
    project = bare_project(tmp_path)
    (project / "fable").mkdir()
    bad = {**QUESTION, "question": "Settle D3 before Q-12?"}
    (project / "fable/open_decisions.json").write_text(json.dumps({"open_questions": [bad, {"question": "Which database?"}]}))
    proc = interview(project, "--check", "--json")
    data = json.loads(proc.stdout)
    assert proc.returncode == 1 and data["ready"] == 0
    assert "D3" in " ".join(data["needs_writing_up"][0]["problems"])
    assert "missing what" in data["needs_writing_up"][1]["problems"]


def test_interview_asks_one_at_a_time_and_records_in_spec_and_decisions(tmp_path):
    project = prepared_project(tmp_path)
    spec = {"open_questions": [QUESTION, {**QUESTION, "question": "Should slugs keep dots?", "topic": "Dots in URL slugs",
                                           "options": [{"choice": "Keep dots", "what_happens": "v1.2 stays v1.2."},
                                                       {"choice": "Replace dots", "what_happens": "v1.2 becomes v1-2."}],
                                           "recommendation": "Replace dots"}], "decisions": []}
    (project / "fable/handoff_spec.json").write_text(json.dumps(spec))
    proc = interview(project, stdin="b\nCollisions are fine for now\nr\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    for words in ["What this is:", "Why it matters:", "If you choose this:", "My recommendation: Keep numbers", "1 more decision after this one"]:
        assert words in out
    assert not re.search(r"\b(?:decision|question) \d", out, re.I)
    saved = json.loads((project / "fable/handoff_spec.json").read_text())
    assert saved["open_questions"] == []
    assert [d["decision"] for d in saved["decisions"]] == ["Numbers in URL slugs: Drop numbers", "Dots in URL slugs: Replace dots"]
    decisions = (project / "fable/DECISIONS.md").read_text()
    assert "Numbers in URL slugs: Drop numbers. Reason: Collisions are fine for now." in decisions
    assert "Dots in URL slugs: Replace dots" in decisions
    assert "## Open questions for the owner\n\nNone." in decisions


def test_init_shows_the_settings_change_and_writes_nothing_without_opt_in(tmp_path):
    project = bare_project(tmp_path)
    (project / ".claude").mkdir()
    original = json.dumps({"permissions": {"allow": ["Bash(git status)"]}})
    (project / ".claude/settings.json").write_text(original)
    proc = run([*script("init_handoff.py"), "--project", str(project), "--verify-command", VERIFY])
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["settings_written"] is False and "+++ b/.claude/settings.json" in out["settings_diff"]
    assert "fable_guard.py" in proc.stderr and "NOT changed" in proc.stderr
    assert (project / ".claude/settings.json").read_text() == original
    assert "fable_stop_gate.py" in (project / "fable/settings.proposed.json").read_text()
    _, data = readiness(project, "--allow-dirty")
    assert statuses(data)["hooks registered"] == "FAIL"


def test_uninstall_restores_the_backup(tmp_path):
    project = bare_project(tmp_path)
    (project / ".claude").mkdir()
    original = json.dumps({"permissions": {"allow": ["Bash(git status)"]}})
    (project / ".claude/settings.json").write_text(original)
    assert init(project).returncode == 0
    proc = run([*script("init_handoff.py"), "--project", str(project), "--uninstall"])
    assert proc.returncode == 0, proc.stderr
    assert (project / ".claude/settings.json").read_text() == original
    assert not list((project / ".claude/hooks").glob("fable_*.py"))
    assert not list((project / ".claude/agents").glob("fable-*.md"))
    assert (project / "fable/MISSION.md").exists(), "the owner's package stays"


def test_uninstall_after_later_edits_removes_only_the_skills_entries(tmp_path):
    project = bare_project(tmp_path)
    assert init(project).returncode == 0
    settings = json.loads((project / ".claude/settings.json").read_text())
    settings["env"] = {"KEEP": "1"}
    settings["permissions"]["deny"].append("Read(./secrets/**)")
    (project / ".claude/settings.json").write_text(json.dumps(settings))
    assert run([*script("init_handoff.py"), "--project", str(project), "--uninstall"]).returncode == 0
    after = json.loads((project / ".claude/settings.json").read_text())
    assert after["env"] == {"KEEP": "1"} and after["permissions"]["deny"] == ["Read(./secrets/**)"]
    assert "hooks" not in after


def test_defaults_keep_the_run_off_main_and_permissions_unbypassed(tmp_path):
    project = bare_project(tmp_path)
    init(project)
    cfg = read_cfg(project)
    assert cfg["permission_mode"] != "bypassPermissions" and cfg["branch"] not in ("main", "master")
