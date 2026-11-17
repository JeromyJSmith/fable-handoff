"""Presets, adjudication under a written schema, launch gates, run output and intent.

These test the general features with the example preset in
fable-handoff/assets/presets/example/ and inline configuration. Every file a
test writes is under its own tmp_path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import SKILL, UV_SCRIPT, bare_project, commit_all, git, init, read_cfg, readiness, run, script, statuses, write_cfg

EXAMPLE = json.loads((SKILL / "assets/presets/example/preset.json").read_text())


def load(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def detective():
    return load("fable_detective_general", SKILL / "assets/templates/detective.py")


def example_config():
    return json.loads(json.dumps(EXAMPLE["config"]))


def example_layout(project: Path) -> None:
    for f in EXAMPLE["config"]["detective_functions"]:
        for src in f["project_sources"]:
            target = project / src.replace("**", "x").replace("*", "x")
            if "." not in target.name:
                target = target / "x.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n")


# --------------------------------------------------------------------------- init --preset and --shape

def test_init_with_a_preset_merges_it_and_never_loosens_the_guard(tmp_path):
    project = bare_project(tmp_path)
    proc = init(project, "--preset", "example")
    assert proc.returncode == 0, proc.stderr
    cfg = read_cfg(project)
    assert cfg["preset"] == "example" and cfg["shape"] == "stage1" and cfg["branch"] == "fable/example-stage1"
    assert [f["name"] for f in cfg["detective_functions"]] == ["name match", "rules and precedent", "quantity match", "adjudication"]
    for path in [".env", ".git/**", "fable/handoff.json", "data/originals/**"]:
        assert path in cfg["protected_paths"]
    assert any("sudo" in p for p in cfg["blocked_bash_patterns"]) and r"\bsendmail\b" in cfg["blocked_bash_patterns"]
    assert cfg["verify_command"] != EXAMPLE["shapes"]["stage1"]["config"]["verify_command"], "the command line wins over the preset"
    mission = (project / "fable/MISSION.md").read_text()
    assert mission.index("## Example firm") < mission.index("\n## Done") and "stage 1 of 2" in mission
    assert "Agents never mine old runs" in (project / "fable/OPERATING_RULES.md").read_text()
    assert json.loads((project / "fable/owner_decisions.json").read_text())["open_questions"][0]["topic"] == "How the run is split"


def test_a_shape_sets_its_own_branch_verify_and_requirements(tmp_path):
    project = bare_project(tmp_path)
    proc = run([*script("init_handoff.py"), "--project", str(project), "--preset", "example", "--shape", "stage2", "--apply-settings"])
    assert proc.returncode == 0, proc.stderr
    cfg = read_cfg(project)
    assert cfg["shape"] == "stage2" and cfg["branch"] == "fable/example-stage2" and cfg["verify_command"].endswith("--stage 2")
    assert "fable/done/stage1.json" in cfg["launch_requires"]["files"] and "stage 2 of 2" in (project / "fable/MISSION.md").read_text()


def test_an_unknown_preset_or_shape_is_refused_and_writes_nothing(tmp_path):
    project = bare_project(tmp_path)
    proc = init(project, "--preset", "nosuchfirm")
    assert proc.returncode != 0 and "no preset 'nosuchfirm'" in proc.stderr and "example" in proc.stderr
    proc = init(project, "--preset", "example", "--shape", "stage9")
    assert proc.returncode != 0 and "no mission shape 'stage9'" in proc.stderr
    assert init(project, "--shape", "stage1").returncode != 0
    assert not (project / "fable").exists()


# --------------------------------------------------------------------------- units and tolerances

def test_weight_flats_pallets_and_lump_sums_are_never_compared_like_measured_quantities():
    dm, cfg = detective(), example_config()
    q = lambda a, ua, b, ub: dm.quantity_agrees({"measured": a, "measured_unit": ua, "stated": b, "stated_unit": ub}, cfg)
    assert q(900, "sf", 100, "sy")[0] is True and q(1000, "sf", 1070, "sf")[0] is False
    ok, why = q(4, "tons", 4, "tons")
    assert not ok and "never compared" in why
    assert "measure different things" in q(18, "each", 1, "flat")[1]
    assert q(3, "flats", 3, "flat")[0] is True and q(2, "pallets", 1, "pallet")[0] is False
    assert "lump sum" in q(1, "ls", 1, "ls")[1]


def test_a_source_outside_the_project_is_checked_by_its_absolute_path(tmp_path):
    outside = tmp_path / "elsewhere" / "SPEC.md"
    outside.parent.mkdir()
    outside.write_text("x\n")
    cfg = {"detective_functions": [{"name": "back-test", "looks_at": "a", "returns": "b", "strength": "decisive", "status": "planned",
                                    "test": "t", "project_sources": [str(outside), str(tmp_path / "elsewhere" / "MISSING.md")]}]}
    problems = detective().registry_problems(cfg, tmp_path / "proj")
    assert problems == ["'back-test' reads %s, which matches nothing in this project" % (tmp_path / "elsewhere" / "MISSING.md")]


# --------------------------------------------------------------------------- adjudication under a written schema

OPTIONS = ["Paving", "Planting", "Walls", "OTHER"]


def adjudicated_case(**adj):
    record = {"by": "adjudicator", "schema": "category", "answer": "Planting", "confidence": 0.95, "offered": OPTIONS,
              "companions": {"evidence_insufficient": 0.1}, "post_checks": {"answer_is_listed": True}, "receipt": "receipts/r.jsonl",
              "reasoning": "the name and a label both say planting"}
    record.update(adj)
    return {"id": "c1", "subject": "Layer PLANT-1", "question": "Which category?", "candidates": OPTIONS[:3],
            "evidence": [{"function": "name match", "source": "the layer name", "strength": "strong", "supports": "Planting"}],
            "adjudication": {k: v for k, v in record.items() if v is not None}}


def test_adjudication_settles_a_likely_case_only_under_its_written_schema(tmp_path):
    dm, cfg = detective(), example_config()
    result = dm.verdict(adjudicated_case(), cfg, tmp_path)
    assert result["verdict"] == "settled by adjudication" and result["adjudication"]["band"] == "auto"
    refused = {
        "it names no schema": dict(schema=None),
        "schema 'free_text' is not one of the written schemas": dict(schema="free_text"),
        "not one of the options offered": dict(offered=["Paving", "Walls"]),
        "companion 'evidence_insufficient' answered 0.8": dict(companions={"evidence_insufficient": 0.8}),
        "post-check 'answer_is_listed' did not pass": dict(post_checks={"answer_is_listed": False}),
        "post-check 'answer_is_listed' of schema 'category' was not run": dict(post_checks={}),
        "names no receipt": dict(receipt=None),
    }
    for reason, change in refused.items():
        result = dm.verdict(adjudicated_case(**change), cfg, tmp_path)
        assert result["verdict"] == "likely" and reason in result["why"], (reason, result["why"])
    assert dm.verdict(adjudicated_case(companions={"same_concept": 0.99}), cfg, tmp_path)["verdict"] == "settled by adjudication"
    review = dm.verdict(adjudicated_case(confidence=0.7), cfg, tmp_path)
    assert review["verdict"] == "likely" and review["adjudication"]["band"] == "review" and "kept as the suggestion" in review["why"]
    assert dm.verdict(adjudicated_case(confidence=0.3), cfg, tmp_path)["adjudication"]["band"] == "low"


def test_without_a_policy_the_original_adjudication_rule_is_unchanged(tmp_path):
    case = adjudicated_case()
    case["adjudication"] = {"by": "reviewer", "answer": "Planting", "confidence": 0.8, "reasoning": "label and name agree"}
    cfg = {"detective_functions": example_config()["detective_functions"]}
    assert detective().verdict(case, cfg, tmp_path)["verdict"] == "settled by adjudication"


def test_backtest_needs_enough_accepted_answers_and_uses_blind_adjudications(tmp_path):
    project = bare_project(tmp_path)
    assert init(project, "--preset", "example").returncode == 0
    cases = []
    for i in range(13):
        right = i < 11
        case = adjudicated_case(confidence=0.95 if right else 0.6, answer="Planting" if right else "Walls", blind=True)
        case.update(id="case-%d" % i, owner_answer="Planting", ruling_sources=["ruling:%d" % i])
        case["evidence"].append({"function": "rules and precedent", "source": "ruling:%d" % i, "strength": "decisive", "supports": "Planting"})
        cases.append(case)
    decided = tmp_path / "decided.json"
    decided.write_text(json.dumps(cases))
    bt = lambda *extra: json.loads(run([*script("detective_backtest.py"), "--project", str(project), "--cases", str(decided), "--json", *extra]).stdout)
    report = bt("--min-accepted", "10", "--write-calibration")
    assert report["evidence_removed_as_the_cases_own_ruling"] == 13 and report["calibration"]["threshold"] == 0.95
    assert report["settled_by_adjudication"] == {"right": 11, "wrong": 0}
    assert {c["cutoff"] for c in report["calibration"]["cutoffs"]} == {0.5, 0.6, 0.7, 0.8, 0.9}
    (project / "fable/calibration.json").unlink()
    report = bt("--min-accepted", "20")
    assert report["calibration"]["threshold"] is None and report["settled_by_adjudication"]["right"] == 0


# --------------------------------------------------------------------------- triage and owner rules from configuration

def test_project_triage_words_sort_firm_choices_from_facts(tmp_path):
    pf = load("fable_preflight_general", SKILL / "scripts/preflight.py")
    assert pf.triage_question("What tolerance does the budget use?")["kind"] == "judgment"
    pf.load_triage_cues(tmp_path, "example")
    assert pf.triage_question("What tolerance does the budget use?")["kind"] == "evidence"
    assert pf.triage_question("What is the design intent for the court?")["kind"] == "judgment"


def test_owner_rules_from_configuration_are_honored_or_block(tmp_path):
    from conftest import prepared_project
    project = prepared_project(tmp_path)
    rules = "# Team rules\n\n1. One writer at a time: take the lock first.\n2. Only the owner sends client mail.\n"
    (project / "CLAUDE.md").write_text(rules)
    write_cfg(project, owner_rule_headings=["team rules"], owner_rules=EXAMPLE["config"]["owner_rules"] + [
        {"kind": "client-mail-by-owner", "effect": "blocks", "patterns": [r"only the owner sends client mail"], "how": "A run cannot send it."}])
    commit_all(project, "rules")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "owner rules")
    assert row["status"] == "FAIL" and "Only the owner sends client mail" in row["detail"]
    (project / "CLAUDE.md").write_text("# Team rules\n\n1. One writer at a time: take the lock first.\n")
    commit_all(project, "rules")
    _, data = readiness(project)
    assert statuses(data)["owner rules"] == "PASS"


# --------------------------------------------------------------------------- launch gates

def test_readiness_refuses_a_launch_whose_required_functions_or_files_are_missing(tmp_path):
    from conftest import prepared_project
    project = prepared_project(tmp_path)
    funcs = [dict(f, project_sources=["src/*.py"]) for f in EXAMPLE["config"]["detective_functions"]]
    req = EXAMPLE["shapes"]["stage1"]["config"]["launch_requires"]
    write_cfg(project, detective_functions=funcs, launch_requires=req)
    commit_all(project, "requires")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "launch requires")
    assert row["status"] == "FAIL" and "docs/GOALS.md, which does not exist yet" in row["detail"]
    assert "'quantity match' is planned and no task in fable/STATE.md builds it" in row["detail"]
    write_cfg(project, launch_requires=EXAMPLE["shapes"]["stage2"]["config"]["launch_requires"])
    commit_all(project, "stage 2")
    _, data = readiness(project)
    assert "'quantity match', which is only planned; build it before launch" in next(r for r in data["rows"] if r["check"] == "launch requires")["detail"]
    (project / "docs").mkdir(exist_ok=True)
    (project / "docs/GOALS.md").write_text("x\n")
    state = (project / "fable/STATE.md").read_text().replace("## Tasks\n", "## Tasks\n\n- [ ] Build quantity match\n", 1)
    (project / "fable/STATE.md").write_text(state)
    write_cfg(project, launch_requires=req)
    commit_all(project, "ready")
    _, data = readiness(project)
    assert statuses(data)["launch requires"] == "PASS"


def test_a_companion_repository_must_be_on_its_branch_clean_and_mapped_and_the_guard_covers_it(tmp_path):
    from conftest import hook, prepared_project
    project = prepared_project(tmp_path)
    app = bare_project(tmp_path, "app")
    (app / "tokens.css").write_text(":root{}\n")
    (app / ".gitignore").write_text((app / ".gitignore").read_text() + "var/\n")
    commit_all(app, "tokens")
    write_cfg(project, companion_repositories=[{"path": str(app), "branch": "fable/app-1", "map": "var/map/*_{commit}/keep-cut.json"}],
              protected_paths=read_cfg(project)["protected_paths"] + ["tokens.css"])
    commit_all(project, "companion")
    _, data = readiness(project)
    assert "on main" in next(r for r in data["rows"] if r["check"] == "companion app")["detail"]
    git(app, "switch", "-qc", "fable/app-1")
    (app / "loose.txt").write_text("x\n")
    _, data = readiness(project)
    assert "uncommitted changes" in next(r for r in data["rows"] if r["check"] == "companion app")["detail"]
    (app / "loose.txt").unlink()
    commit = git(app, "rev-parse", "--short=9", "HEAD").stdout.strip()
    _, data = readiness(project)
    assert statuses(data)["companion app"] == "PASS" and statuses(data)["companion app map"] == "FAIL"
    (app / ("var/map/2026-01-01_%s" % commit)).mkdir(parents=True)
    (app / ("var/map/2026-01-01_%s/keep-cut.json" % commit)).write_text("{}")
    _, data = readiness(project)
    assert statuses(data)["companion app map"] == "PASS"
    assert hook(project, "fable_guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(app / "src/a.ts")}, "cwd": str(project)}).returncode == 0
    no = hook(project, "fable_guard.py", {"tool_name": "Edit", "tool_input": {"file_path": str(app / "tokens.css")}, "cwd": str(project)})
    assert no.returncode == 2 and "companion repository" in no.stderr


def test_the_guard_allows_named_files_outside_the_project_and_nothing_else(tmp_path):
    from conftest import hook
    project = bare_project(tmp_path)
    assert init(project).returncode == 0
    log = tmp_path / "shared" / "TASKS.md"
    write_cfg(project, writable_outside_paths=[str(log)])
    assert hook(project, "fable_guard.py", {"tool_name": "Edit", "tool_input": {"file_path": str(log)}, "cwd": str(project)}).returncode == 0
    no = hook(project, "fable_guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "shared" / "OTHER.md")}, "cwd": str(project)})
    assert no.returncode == 2 and "outside the project" in no.stderr


def test_readiness_and_the_stop_gate_refuse_a_model_call_in_calculation_code(tmp_path):
    from conftest import hook, prepared_project
    project = prepared_project(tmp_path)
    (project / "calc").mkdir()
    (project / "calc/total.py").write_text("def total(lines):\n    return sum(l['qty'] * l['rate'] for l in lines)\n")
    (project / "calc/category_adjudicator.py").write_text("from jev_client import client\n")
    write_cfg(project, deterministic_code=EXAMPLE["config"]["deterministic_code"])
    commit_all(project, "plain")
    _, data = readiness(project)
    assert statuses(data)["no model calls"] == "PASS"
    (project / "calc/rate.py").write_text("import anthropic\n\ndef rate(c):\n    return anthropic.Anthropic().messages.create(model='x')\n")
    commit_all(project, "model")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "no model calls")
    assert row["status"] == "FAIL" and "calc/rate.py:1" in row["detail"] and "adjudicator" not in row["detail"]
    (project / "fable/STATE.md").write_text((project / "fable/STATE.md").read_text().replace("- [ ]", "- [x]"))
    (project / "fable/REPORT.md").write_text("Done.\n")
    write_cfg(project, verify_command="true")
    proc = hook(project, "fable_stop_gate.py", {"session_id": "s", "stop_hook_active": False})
    assert "calls a language model" in proc.stdout + proc.stderr


def test_decisions_before_launch_hold_only_the_shape_that_needs_them(tmp_path):
    project = bare_project(tmp_path)
    assert init(project, "--preset", "example").returncode == 0
    check = run([*script("decision_interview.py"), "--project", str(project), "--file", "fable/owner_decisions.json", "--check"])
    assert check.returncode == 0 and "2 open decision(s), 2 ready to ask" in check.stdout, check.stdout + check.stderr
    git(project, "switch", "-qc", "fable/example-stage1")
    commit_all(project, "package")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "owner decisions")
    assert row["status"] == "FAIL" and "1 decision(s) wait on the owner: How the run is split" in row["detail"]
    packet = json.loads((project / "fable/owner_decisions.json").read_text())["open_questions"]
    (tmp_path / "a.json").write_text(json.dumps({packet[0]["question"]: {"choice": "Two stages", "reason": "test"}}))
    proc = run([*script("decision_interview.py"), "--project", str(project), "--file", "fable/owner_decisions.json", "--answers", str(tmp_path / "a.json")])
    assert "1 decision(s) recorded, 1 skipped" in proc.stdout, proc.stdout + proc.stderr
    commit_all(project, "answered")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "owner decisions")
    assert row["status"] == "PASS" and "waiting for a later shape: The accuracy target" in row["detail"]
    write_cfg(project, shape="stage2")
    commit_all(project, "stage 2")
    _, data = readiness(project)
    assert statuses(data)["owner decisions"] == "FAIL"


# --------------------------------------------------------------------------- run output is never a source

def test_the_guard_blocks_reading_run_output_and_allows_everything_else(tmp_path):
    from conftest import hook
    project = bare_project(tmp_path)
    assert init(project, "--preset", "example").returncode == 0
    assert "Read|Grep|Glob" in json.dumps(json.loads((project / ".claude/settings.json").read_text())["hooks"]["PreToolUse"])
    (project / "runs/r1").mkdir(parents=True)
    (project / "runs/r1/report.json").write_text("{}")
    g = lambda tool, inp: hook(project, "fable_guard.py", {"tool_name": tool, "tool_input": inp, "cwd": str(project)})
    for tool, inp in [("Read", {"file_path": "runs/r1/report.json"}), ("Grep", {"pattern": "x", "path": "runs"}),
                      ("Glob", {"pattern": "runs/**/*.json"}), ("Bash", {"command": "cat runs/r1/report.json | jq ."}),
                      ("Bash", {"command": "cd src && grep -r x ../runs"})]:
        proc = g(tool, inp)
        assert proc.returncode == 2 and "run output that this run may not read" in proc.stderr, (tool, inp)
    for tool, inp in [("Read", {"file_path": "src/slug.py"}), ("Grep", {"pattern": "x"}), ("Glob", {"pattern": "**/*.py"}),
                      ("Bash", {"command": "grep -rn x src"}), ("Bash", {"command": "echo runs are kept elsewhere"})]:
        assert g(tool, inp).returncode == 0, (tool, inp)


def test_the_outside_write_guard_sees_a_change():
    import conftest
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "watched.md"
        target.write_text("method\n")
        before = conftest.fingerprint([target])
        assert conftest.changed(before, conftest.fingerprint([target])) == []
        target.write_text("x\n")
        assert conftest.changed(before, conftest.fingerprint([target])) == [str(target)]


# --------------------------------------------------------------------------- intent

def test_intent_finds_lost_data_and_its_resolution(tmp_path):
    msg = lambda role, text, ts: {"type": role, "timestamp": ts, "sessionId": "s1", "message": {"role": role, "content": text}}
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "a.jsonl").write_text("\n".join(json.dumps(r) for r in [
        msg("user", "I want every line placed. Never edit a test to make it pass.", "2026-01-01T10:00:00Z"),
        msg("user", "The pipeline changed more: the note \"KEEP 2 INCH JOINTS\" and the 12.5% grade are gone.", "2026-01-02T09:00:00Z"),
        msg("assistant", "The `fee_layer` table was rebuilt empty and dropped 40 rows.", "2026-01-02T09:05:00Z"),
        msg("assistant", "The `fee_layer` table is back: restored from the archive.", "2026-01-02T10:00:00Z"),
        msg("user", "Still missing: \"KEEP 2 INCH JOINTS\" was not found in the database.", "2026-01-03T09:00:00Z"),
    ]) + "\n")
    out = tmp_path / "out" / "INTENT.md"
    proc = run([*script("intent.py"), "--project", str(tmp_path / "proj"), "--logs", str(logs), "--out", str(out), "--json"])
    assert proc.returncode == 0, proc.stderr
    found = {" ".join(f["items"]): f["status"] for f in json.loads(proc.stdout)["lost_or_regressed"]}
    assert found["12.5% KEEP 2 INCH JOINTS"] == "still open" and found["40 rows fee_layer"] == "resolved"
    assert "Never edit a test to make it pass." in out.read_text()
    again = run([*script("intent.py"), "--project", str(tmp_path / "proj"), "--logs", str(logs), "--out", str(out)])
    assert again.returncode == 2 and "never overwritten" in again.stderr


# --------------------------------------------------------------------------- standards checks and answer rules

def test_a_standards_check_gates_done_and_must_be_runnable(tmp_path):
    from conftest import hook, prepared_project
    project = prepared_project(tmp_path)
    write_cfg(project, standards_checks=[{"name": "naming standard", "command": "test -f checks/naming_ok", "why": "every entry follows the naming standard"}])
    commit_all(project, "standards check")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "standards check")
    assert row["status"] == "PASS" and "failing now" in row["detail"]
    write_cfg(project, standards_checks=[{"name": "broken", "command": "uv run --script checks/missing.py"}])
    commit_all(project, "broken check")
    _, data = readiness(project)
    assert next(r for r in data["rows"] if r["check"] == "standards check")["status"] == "FAIL"
    write_cfg(project, standards_checks=[{"name": "naming standard", "command": "test -f checks/naming_ok", "why": "every entry follows the naming standard"}], verify_command="true")
    (project / "fable/STATE.md").write_text((project / "fable/STATE.md").read_text().replace("- [ ]", "- [x]"))
    (project / "fable/REPORT.md").write_text("Done.\n")
    proc = hook(project, "fable_stop_gate.py", {"session_id": "s", "stop_hook_active": False})
    assert "the standards check \"naming standard\" fails" in proc.stdout + proc.stderr
    (project / "checks").mkdir()
    (project / "checks/naming_ok").write_text("")
    proc = hook(project, "fable_stop_gate.py", {"session_id": "s", "stop_hook_active": False})
    assert "standards check" not in proc.stdout + proc.stderr


def test_an_adjudicated_answer_may_not_break_a_rule_of_the_standard(tmp_path):
    cfg = example_config()
    case = adjudicated_case(answer="n/a", offered=OPTIONS + ["n/a"])
    case["candidates"] = OPTIONS + ["n/a"]
    case["evidence"][0]["supports"] = "n/a"
    result = detective().verdict(case, cfg, tmp_path)
    assert result["verdict"] == "likely" and "breaks a rule of the standard: every entry has a real name" in result["why"]
    assert detective().verdict(adjudicated_case(), cfg, tmp_path)["verdict"] == "settled by adjudication"
    # a rule scoped to other schemas does not apply
    cfg["adjudication_policy"]["answer_rules"][0]["schemas"] = ["item_name"]
    assert detective().verdict(case, cfg, tmp_path)["verdict"] == "settled by adjudication"


# --------------------------------------------------------------------------- install

def test_install_takes_a_branch_a_tag_or_a_commit(tmp_path):
    import subprocess
    repo = tmp_path / "origin"
    subprocess.run(["git", "clone", "-q", str(SKILL.parent), str(repo)], check=True)
    for cmd in (["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    first = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (repo / "fable-handoff" / "MARKER.txt").write_text("later\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "later"], check=True)
    subprocess.run(["git", "-C", str(repo), "tag", "t1"], check=True)
    branch = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    env = {"FABLE_HANDOFF_REPO": "file://%s" % repo}
    for ref, marker in ((branch, True), ("t1", True), (first, False), (first[:7], False)):
        dest = tmp_path / ("dest-" + ref[:7])
        proc = run(["bash", str(SKILL.parent / "install.sh"), "--ref", ref, "--dest", str(dest)], env=env)
        assert proc.returncode == 0, (ref, proc.stderr)
        installed = (dest / "fable-handoff" / ".installed-from").read_text()
        assert ("ref=%s" % ref) in installed and (dest / "fable-handoff" / "MARKER.txt").exists() is marker, ref
        if not marker:
            assert ("commit=%s" % first) in installed
    proc = run(["bash", str(SKILL.parent / "install.sh"), "--ref", "nosuchref", "--dest", str(tmp_path / "x")], env=env)
    assert proc.returncode == 1 and "no branch, tag or commit named nosuchref" in proc.stderr


def test_a_standards_check_that_names_a_missing_file_fails(tmp_path):
    from conftest import prepared_project
    project = prepared_project(tmp_path)
    write_cfg(project, standards_checks=[{"name": "numbering", "command": "uv run pytest -q tests/test_numbering.py"}])
    commit_all(project, "check")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "standards check")
    assert row["status"] == "FAIL" and "tests/test_numbering.py, which does not exist" in row["detail"]
    (project / "tests").mkdir()
    (project / "tests/test_numbering.py").write_text("def test_x():\n    assert False\n")
    commit_all(project, "test file")
    _, data = readiness(project)
    assert statuses(data)["standards check"] == "PASS"


def test_init_can_create_and_switch_to_the_runs_branch(tmp_path):
    project = bare_project(tmp_path)
    proc = run([*script("init_handoff.py"), "--project", str(project), "--preset", "example", "--shape", "stage2", "--apply-settings", "--create-branch"])
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["branch"] == "on fable/example-stage2"
    assert git(project, "branch", "--show-current").stdout.strip() == "fable/example-stage2"


def test_a_worktree_links_the_shared_data_from_the_main_checkout_without_overwriting(tmp_path):
    main = tmp_path / "main"
    (main / "data/loaded").mkdir(parents=True)
    (main / "data/loaded/rows.ndjson").write_text("{}\n")
    (main / "store.duckdb").write_text("db")
    project = bare_project(tmp_path, "worktree")
    assert init(project).returncode == 0
    (project / "kept.txt").write_text("mine\n")
    write_cfg(project, shared_data={"from": str(main), "paths": ["data/loaded", "store.duckdb", "kept.txt", "absent.json"]})
    commit_all(project, "shared data")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "shared data")
    assert row["status"] == "FAIL" and "link_shared_data.py" in row["detail"]
    proc = run([*script("link_shared_data.py"), "--project", str(project)])
    report = {p["path"]: p["state"] for p in json.loads(proc.stdout)["paths"]}
    assert report == {"data/loaded": "linked now", "store.duckdb": "linked now", "kept.txt": "present", "absent.json": "missing in the main checkout too"}
    assert proc.returncode == 1 and (project / "kept.txt").read_text() == "mine\n"
    assert (project / "data/loaded/rows.ndjson").read_text() == "{}\n" and (project / "store.duckdb").is_symlink()
    assert "/data/loaded" in (project / ".git/info/exclude").read_text() and "data/loaded" not in git(project, "status", "--porcelain").stdout
    write_cfg(project, shared_data={"from": str(main), "paths": ["data/loaded", "store.duckdb", "kept.txt"]})
    commit_all(project, "fewer")
    _, data = readiness(project)
    assert statuses(data)["shared data"] == "PASS" and "2 linked" in next(r for r in data["rows"] if r["check"] == "shared data")["detail"]


def test_shared_data_can_take_every_ignored_path_of_the_main_checkout(tmp_path):
    main = bare_project(tmp_path, "main")
    (main / ".gitignore").write_text((main / ".gitignore").read_text() + "data/\nstore.duckdb\n.venv/\nscratch/\n")
    commit_all(main, "ignore data")
    (main / "data").mkdir()
    (main / "data/rows.ndjson").write_text("{}\n")
    (main / "store.duckdb").write_text("db")
    (main / ".venv").mkdir()
    (main / "scratch").mkdir()
    (main / "scratch/tmp.txt").write_text("x")
    project = bare_project(tmp_path, "worktree")
    assert init(project).returncode == 0
    write_cfg(project, shared_data={"from": str(main), "all_ignored": True, "exclude": ["scratch"]})
    commit_all(project, "shared")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "shared data")
    assert row["status"] == "FAIL" and "data" in row["detail"] and ".venv" not in row["detail"] and "scratch" not in row["detail"]
    proc = run([*script("link_shared_data.py"), "--project", str(project)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(p["path"] for p in json.loads(proc.stdout)["paths"]) == ["data", "store.duckdb"]
    _, data = readiness(project)
    assert statuses(data)["shared data"] == "PASS"
