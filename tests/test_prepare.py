"""prepare.py and prepare.marimo.py: phases 0 to 7 with receipts, the validity check, and what readiness enforces.

Every test works in its own tmp_path.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from conftest import SKILL, UV_SCRIPT, git, read_cfg, readiness, run, script, statuses, write_cfg


def load_prepare():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("fable_prepare_test", SKILL / "scripts/prepare.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample(tmp_path: Path, name: str = "p") -> Path:
    """A small project shaped for the example preset: goals, decisions, data, one failing test, pinned pytest."""
    p = tmp_path / name
    for d in ("docs", "data", "tests"):
        (p / d).mkdir(parents=True)
    (p / "docs/GOALS.md").write_text("# goals\n")
    (p / "DECISIONS.md").write_text("# Decisions\n")
    (p / "data/rows.json").write_text("{}\n")
    (p / "schemas.yaml").write_text("x: 1\n")
    (p / "tests/test_load.py").write_text("def test_loaded():\n    assert False\n")
    (p / "pyproject.toml").write_text('[project]\nname = "sample"\nversion = "0.1.0"\nrequires-python = ">=3.11"\ndependencies = ["pytest==8.4.2"]\n')
    (p / ".gitignore").write_text(".venv/\nuv.lock\n__pycache__/\n.pytest_cache/\n")
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *cmd], cwd=p, check=True)
    return p


def prepare(project: Path, *extra: str):
    return run([*script("prepare.py"), "--project", str(project), "--preset", "example", "--no-logs", "--apply-settings", "--max-budget-usd", "50", *extra], timeout=1800)


def test_prepare_runs_every_phase_and_stops_at_the_owners_sign_off(tmp_path):
    project = sample(tmp_path)
    proc = prepare(project)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    names = ["0-decide", "1-discover", "2-interview", "3-done-check", "4-scaffold", "5-rules", "6-mission", "7-readiness"]
    receipts = [json.loads((project / "fable/receipts" / (n + ".json")).read_text()) for n in names]
    assert [r["result"] for r in receipts] == ["passed"] * 7 + ["awaiting owner sign-off"]
    for r in receipts[1:]:
        assert r["checks"] and all(c["ok"] for c in r["checks"]) and r["started"] and r["ended"]
    assert receipts[3]["data"]["exit_now"] != 0, "the done check fails before the work"
    cfg = read_cfg(project)
    assert cfg["require_receipts"] is True and git(project, "branch", "--show-current").stdout.strip() == "fable/example-stage1"
    state = (project / "fable/STATE.md").read_text()
    assert "<!-- draft" not in state and all("(check: `" in l for l in state.splitlines() if l.startswith("- [ ]"))
    assert (project / "fable/findings.json").exists() and (project / "fable/handoff_spec.json").exists()
    assert "Launching (phase 8) is the owner's" in proc.stdout
    # the owner answers, signs and commits: readiness then passes the prepared package
    packet = json.loads((project / "fable/owner_decisions.json").read_text())["open_questions"]
    answers = {q["question"]: {"choice": q["recommendation"], "reason": "test"} for q in packet if "stage2" not in (q.get("needed_for") or [])}
    (tmp_path / "a.json").write_text(json.dumps(answers))
    run([*script("decision_interview.py"), "--project", str(project), "--file", "fable/owner_decisions.json", "--answers", str(tmp_path / "a.json")])
    assert run([*script("spec_tool.py"), "signoff", "--project", str(project), "--by", "Test Owner"]).returncode == 0
    git(project, "add", "-A")
    git(project, "commit", "-qm", "signed")
    _, data = readiness(project)
    st = statuses(data)
    assert st["receipts"] == "PASS" and st["ledger coverage"] == "PASS" and st["owner decisions"] == "PASS", data["rows"]
    assert not [r for r in data["rows"] if r["status"] == "FAIL"], [r for r in data["rows"] if r["status"] == "FAIL"]
    # a skipped phase fails readiness
    receipt = project / "fable/receipts/3-done-check.json"
    kept = receipt.read_text()
    receipt.unlink()
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "receipts")
    assert row["status"] == "FAIL" and "phase 3 (done-check) has no receipt" in row["detail"]
    receipt.write_text(kept)
    # a phase whose input changed afterwards is stale
    (project / "fable/preflight.json").write_text((project / "fable/preflight.json").read_text() + " ")
    _, data = readiness(project)
    assert "phase 4 (scaffold) is stale: fable/preflight.json changed" in next(r for r in data["rows"] if r["check"] == "receipts")["detail"]


def test_prepare_stops_on_a_failed_precondition_and_writes_why(tmp_path):
    project = sample(tmp_path)
    proc = prepare(project, "--from", "1")
    assert proc.returncode == 1 and "phase 1 discover   stopped" in proc.stdout
    receipt = json.loads((project / "fable/receipts/1-discover.json").read_text())
    assert receipt["result"] == "stopped" and "phase 0 (decide) has no receipt" in receipt["reason"]
    not_git = tmp_path / "plain"
    not_git.mkdir()
    proc = prepare(not_git)
    assert proc.returncode == 1 and "the project is a git repository" in proc.stdout


def test_a_done_check_that_already_passes_stops_phase_three(tmp_path):
    project = sample(tmp_path)
    proc = prepare(project, "--until", "3", "--verify-command", "true")
    assert proc.returncode == 1 and "the verify command fails now" in proc.stdout


def test_the_validity_check_refuses_each_broken_rule(tmp_path):
    prep = load_prepare()
    project = sample(tmp_path)
    (project / "fable/done").mkdir(parents=True)
    state = {"project": project, "config": {"unreadable_paths": ["runs", "runs/**"],
                                            "writer_lock": {"file": ".writer.lock", "protects": ["*.duckdb"], "agent_env": "TEST_AGENT"},
                                            "held_out": {"answer_paths": ["answers/held/*"]}}, "shape": "stage2"}
    v = lambda **a: prep.valid(state, dict({"argv": ["true"], "writes": [], "reads": [], "phase": 1}, **a))
    assert v() is None
    assert "no overwrite or delete" in v(argv=["bash", "-c", "rm -rf data"])
    assert "no overwrite or delete" in v(argv=["git", "restore", "data/rows.json"])
    assert "run output is never a source" in v(reads=["runs/2026/report.json"])
    assert "run output is never a source" in v(argv=["cat", "runs/x.json"])
    assert "held-out project's answer" in v(reads=["answers/held/ulm.json"])
    assert "no overwrite: data/rows.json already exists" in v(writes=["data/rows.json"])
    assert v(writes=["fable/STATE.md"]) is None
    assert "writer lock" in v(writes=["store.duckdb"])
    assert "stage order: stage2 starts only after fable/done/stage1.json exists" in v(phase=4)
    (project / "fable/done/stage1.json").write_text("{}")
    assert v(phase=4) is None


def test_readiness_refuses_a_draft_a_task_without_a_check_and_an_uncovered_finding(tmp_path):
    project = sample(tmp_path)
    assert prepare(project).returncode == 0
    git(project, "add", "-A")
    git(project, "commit", "-qm", "package")
    state = (project / "fable/STATE.md").read_text()
    (project / "fable/STATE.md").write_text(state.replace("## Tasks\n", "## Tasks\n\n- [ ] Something without a check\n", 1))
    findings = json.loads((project / "fable/findings.json").read_text())
    findings.append({"id": "F99", "kind": "gap", "key": "gap:x", "text": "a gap", "status": "open", "evidence": None})
    (project / "fable/findings.json").write_text(json.dumps(findings))
    (project / "fable/DECISIONS.md").write_text(load_prepare().DRAFT + "\n" + (project / "fable/DECISIONS.md").read_text())
    _, data = readiness(project)
    ledger = next(r for r in data["rows"] if r["check"] == "ledger coverage")
    assert ledger["status"] == "FAIL" and "without a (check" in ledger["detail"] and "F99" in ledger["detail"]
    assert next(r for r in data["rows"] if r["check"] == "drafts")["status"] == "FAIL"


def test_a_hand_built_package_gets_a_warning_and_a_missing_spec_fails_when_receipts_are_required(tmp_path):
    from conftest import prepared_project
    project = prepared_project(tmp_path)
    _, data = readiness(project)
    assert statuses(data)["receipts"] == "WARN"
    write_cfg(project, require_receipts=True)
    git(project, "add", "-A")
    git(project, "commit", "-qm", "require")
    _, data = readiness(project)
    st = statuses(data)
    assert st["receipts"] == "FAIL" and st["handoff spec"] == "FAIL" and st["ledger coverage"] == "FAIL"


def test_the_findings_ledger_builds_checks_and_resolves(tmp_path):
    project = tmp_path / "p"
    (project / "fable").mkdir(parents=True)
    (project / "fable/INTENT.json").write_text(json.dumps({"lost_or_regressed": [
        {"items": ["10.5%", "slope"], "status": "still open", "first": "the slope is gone", "status_from": None},
        {"items": ["fee_layer"], "status": "resolved", "first": "emptied", "status_from": "restored from the archive"}]}))
    (project / "fable/cases.json").write_text(json.dumps([{"id": "c1", "question": "Which slot?", "result": {"verdict": "open, fact"}},
                                                        {"id": "c2", "question": "Which slot?", "result": {"verdict": "settled"}}]))
    (project / "fable/gaps.json").write_text(json.dumps({"gaps": [{"id": "gap-1", "kind": "disconnected", "between": ["a", "b"], "status": "open"}]}))
    f = lambda *a: run([*UV_SCRIPT, str(SKILL / "assets/templates/findings.py"), *a, "--project", str(project)])
    assert f("build").stdout.strip() == "4 finding(s), 3 open"
    ledger = json.loads((project / "fable/findings.json").read_text())
    assert [x["kind"] for x in ledger] == ["data lost or regressed", "data lost or regressed", "detective case", "gap"]
    assert f("check", "F2").returncode == 0 and f("check", "F1").returncode == 1
    assert f("resolve", "F1").returncode == 2
    assert f("resolve", "F1", "--evidence", "the slope is in project_settings at 10.5%").returncode == 0
    assert f("check", "F1").returncode == 0
    assert f("build").stdout.strip() == "4 finding(s), 2 open", "a rebuild keeps ids and resolutions"


def test_the_notebook_runs_headless_and_writes_the_same_receipts(tmp_path):
    project = sample(tmp_path)
    proc = run([*UV_SCRIPT, str(SKILL / "scripts/prepare.marimo.py"), "--project", str(project), "--preset", "example", "--no-logs",
                "--apply-settings", "--max-budget-usd", "50"], timeout=1800)
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert json.loads((project / "fable/receipts/7-readiness.json").read_text())["result"] == "awaiting owner sign-off"
    text = (SKILL / "scripts/prepare.marimo.py").read_text()
    assert '"marimo==0.25.2", "wigglystuff==0.5.40"' in text and "ProgressBar" in text and "TraceView" in text and "mo.stop(" in text
