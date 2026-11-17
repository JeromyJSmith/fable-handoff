"""The MARPA preset and the Jev decision framework on the marpa branch.

The preset lives in fable-handoff/assets/presets/marpa/. The tests that read
MARPA's own repository (its file layout, its CLAUDE.md, its exported decided
cases) run when that repository is on this machine; set FABLE_MARPA_REPO to
point at it elsewhere.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import SKILL, UV_SCRIPT, bare_project, commit_all, git, init, read_cfg, readiness, run, script, statuses, write_cfg

PRESET_DIR = SKILL / "assets" / "presets" / "marpa"
PRESET = json.loads((PRESET_DIR / "preset.json").read_text())
MARPA = Path(os.environ.get("FABLE_MARPA_REPO", "/Volumes/MARPA/_New_APP/data/external/marpa-desk/sources/ontology-duckdb"))
DECIDED = PRESET_DIR / "decided_cases.json"
needs_marpa = pytest.mark.skipif(not (MARPA / "detective_functions.yaml").exists(), reason="MARPA's repository is not on this machine")


def detective():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fable_detective_marpa", SKILL / "assets/templates/detective.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def marpa_config():
    return json.loads(json.dumps(PRESET["config"]))


def layout_like_marpa(project: Path) -> None:
    """Create one file for every path or glob the preset's functions read."""
    for f in PRESET["config"]["detective_functions"]:
        for src in f["project_sources"]:
            if src.lower().startswith(detective().EXTERNAL):
                continue
            target = project / src.replace("*", "x")
            if "." in target.name or target.name.endswith("x"):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("{}\n")
            else:
                target.mkdir(parents=True, exist_ok=True)
                (target / "keep.txt").write_text("x\n")


# --------------------------------------------------------------------------- init --preset

def test_init_with_the_marpa_preset_writes_marpas_configuration(tmp_path):
    project = bare_project(tmp_path)
    proc = init(project, "--preset", "marpa")
    assert proc.returncode == 0, proc.stderr
    cfg = read_cfg(project)
    names = [f["name"] for f in cfg["detective_functions"]]
    assert names == ["name match", "drawing content", "text on the drawing", "spatial relationships", "budget match",
                     "takeoff from geometry", "rules and precedent", "the firm's own words", "outside standards", "back-test", "gap analysis", "adjudication"]
    assert not any(f.get("generic") for f in cfg["detective_functions"])
    planned = {f["name"] for f in cfg["detective_functions"] if f["status"] == "planned"}
    assert planned == {"spatial relationships", "takeoff from geometry", "the firm's own words", "outside standards", "back-test", "gap analysis"}
    assert [r["rung"] for r in cfg["evidence_ladder"]] == ["drawings and models", "the project's budget", "the standard and class vocabulary",
                                                          "rulings and decisions", "the firm's own words", "outside standards", "back-tests on past projects"]
    assert cfg["question_system"] == {"type": "bcf", "path": "bcf/fable-questions.bcf"}
    assert cfg["decisions_log"] == "DECISIONS.md"
    assert cfg["adjudication_policy"]["schemas"]["class_slot"]["post_checks"] == ["existing_is_never_proposed_work"]
    assert cfg["adjudication_policy"]["abstain_ids"] == ["OTHER"] and cfg["adjudication_policy"]["review_floor"] == 0.5
    # the guard keeps every default and adds MARPA's
    for path in [".env", ".git/**", "fable/handoff.json", "class_rulings.yaml", "jev_schemas.yaml", ".writer.lock", "*.duckdb", "bcf/marpa-questions.bcf"]:
        assert path in cfg["protected_paths"]
    assert any("sudo" in p for p in cfg["blocked_bash_patterns"]) and r"\bpxt\b" in cfg["blocked_bash_patterns"]
    assert cfg["writable_outside_paths"] == ["/Volumes/MARPA/apps/marpa-desk/TASKS.md"]
    # the command line wins over the preset: conftest's init passed its own verify command
    assert cfg["verify_command"] != PRESET["config"]["verify_command"]
    mission = (project / "fable/MISSION.md").read_text()
    assert mission.index("## MARPA") < mission.index("\n## Done") and "Class-word grammar" in (project / "fable/OPERATING_RULES.md").read_text()
    # the owner's product direction: takeoff, the back-test against real budgets, Solomon, intake to budget, two repositories
    for words in ["marpa_solomon_2605", "Allowances, spread top-down", "Held-out estimates", "DEFINITION_OF_DONE.md", "budgetLoad.ts", "AEC-ALLOWANCE-METHOD.md", "s01_decode", "Passing tests alone is not done"]:
        assert words in mission, words
    rules = (project / "fable/OPERATING_RULES.md").read_text()
    assert rules.rstrip().endswith("Never a bare decision number.") and "writer_lock.py take" in rules


def test_the_preset_verify_command_is_used_when_none_is_given(tmp_path):
    project = bare_project(tmp_path)
    proc = run([*script("init_handoff.py"), "--project", str(project), "--preset", "marpa", "--apply-settings"])
    assert proc.returncode == 0, proc.stderr
    cfg = read_cfg(project)
    assert cfg["verify_command"].startswith("test -f docs/standard/DEFINITION_OF_DONE.md && uv run pytest -q tests")
    assert "(cd /Volumes/MARPA/method/allocation && UV_PROJECT_ENVIRONMENT=$HOME/worktrees/_env/marpa-allocation uv run --no-sync pytest -q)" in cfg["verify_command"]
    assert "bun run test" in cfg["verify_command"] and cfg["verify_command"].endswith("test -f done_check.py && uv run done_check.py --check")
    assert cfg["verify_timeout_seconds"] == 7200
    done = cfg["definition_of_done"]
    assert done["source"] == "docs/standard/DEFINITION_OF_DONE.md" and done["endpoint"] == "GET /done" and len(done["rows"]) == 15
    assert cfg["budget_tolerance"]["held_out_total_pct"] == 10.0 and cfg["budget_tolerance"]["allocation_unexplained_cents"] == 0
    assert cfg["related_locations"][0]["path"] == "/Volumes/MARPA/method/allocation" and cfg["related_locations"][0]["role"] == "read and run"


def test_an_unknown_preset_is_refused_and_writes_nothing(tmp_path):
    project = bare_project(tmp_path)
    proc = init(project, "--preset", "nosuchfirm")
    assert proc.returncode != 0 and "no preset 'nosuchfirm'" in proc.stderr and "marpa" in proc.stderr
    assert not (project / "fable").exists()


# --------------------------------------------------------------------------- the registry is MARPA's own

def test_the_marpa_registry_passes_where_its_sources_exist_and_fails_where_they_do_not(tmp_path):
    dm = detective()
    cfg = marpa_config()
    empty = tmp_path / "empty"
    empty.mkdir()
    problems = dm.registry_problems(cfg, empty)
    assert any("'name match' reads class_vocabulary.yaml, which matches nothing" in p for p in problems)
    # connectors and outside standards are written as such and never need a file
    assert not any("connector: Gmail" in p or "external: bSDD" in p for p in problems)
    layout = tmp_path / "marpa"
    layout_like_marpa(layout)
    assert dm.registry_problems(cfg, layout) == []


def test_readiness_accepts_the_marpa_registry_in_a_marpa_shaped_project(tmp_path):
    project = bare_project(tmp_path)
    assert init(project, "--preset", "marpa").returncode == 0
    layout_like_marpa(project)
    git(project, "switch", "-qc", "fable/run-1")
    commit_all(project, "MARPA layout")
    _, data = readiness(project)
    assert statuses(data)["detective functions"] == "PASS", data


@needs_marpa
def test_every_marpa_source_exists_in_marpas_repository():
    assert detective().registry_problems(marpa_config(), MARPA) == []
    for rung in PRESET["config"]["evidence_ladder"]:
        assert rung["look_in"].strip()
    assert (MARPA / PRESET["config"]["decisions_log"]).exists()
    assert (MARPA / "bcf").is_dir()


# --------------------------------------------------------------------------- landscape units and tolerances

@pytest.mark.parametrize("measured,mu,stated,su,agrees", [
    (900, "sf", 100, "sy", True),        # 900 sf is 100 sy
    (1000, "sf", 1040, "sf", True),      # 4% apart, area tolerance 5%
    (1000, "sf", 1070, "sf", False),     # 7% apart
    (100, "lf", 104, "lf", True),
    (27, "cf", 1, "cy", True),           # volume in cubic feet against cubic yards
    (10, "cy", 10.9, "cy", True),        # 9% apart, volume tolerance 10%
    (10, "cy", 11.5, "cy", False),
    (12, "each", 12, "ea", True),
    (12, "each", 13, "ea", False),       # a count is exact
])
def test_landscape_quantities_agree_within_marpas_tolerances(measured, mu, stated, su, agrees):
    ok, why = detective().quantity_agrees({"measured": measured, "measured_unit": mu, "stated": stated, "stated_unit": su}, marpa_config())
    assert ok is agrees, why


def test_tons_flats_pallets_and_lump_sums_are_never_compared_like_measured_quantities():
    dm, cfg = detective(), marpa_config()
    q = lambda a, ua, b, ub: dm.quantity_agrees({"measured": a, "measured_unit": ua, "stated": b, "stated_unit": ub}, cfg)
    ok, why = q(4, "tons", 4, "tons")
    assert not ok and "never compared" in why
    assert dm.UNITS["ton"] == ("weight", 907.18474) and dm.UNITS["lb"][0] == "weight"
    ok, why = q(18, "each", 1, "flat")
    assert not ok and "measure different things" in why
    assert q(3, "flats", 3, "flat")[0] is True and q(3, "flats", 4, "flat")[0] is False
    assert q(2, "pallets", 1, "pallet")[0] is False
    ok, why = q(1, "ls", 1, "ls")
    assert not ok and "lump sum" in why
    # a strong budget match whose quantity fails is counted as supporting
    item = {"function": "budget match", "strength": "strong", "source": "budget line 12", "supports": "4.0 FLATWORK / HARDSCAPE",
            "quantity": {"measured": 4, "measured_unit": "tons", "stated": 4, "stated_unit": "tons"}}
    level, note = dm.effective_strength(item, cfg)
    assert level == dm.STRENGTH["supporting"] and "counted as supporting" in note


# --------------------------------------------------------------------------- Jev adjudication under a written schema

SLOTS = ["4.0 FLATWORK / HARDSCAPE", "5.0 GROUNDCOVERS", "9.0 PLANT MATERIAL", "OTHER"]


def jev_case(**adj):
    record = {"by": "jev", "schema": "class_slot", "answer": "5.0 GROUNDCOVERS", "confidence": 0.95, "offered": SLOTS,
              "companions": {}, "post_checks": {"existing_is_never_proposed_work": True}, "receipt": "jev-20261116.jsonl",
              "reasoning": "the class name and the planting plan label both say groundcover"}
    record.update(adj)
    return {"id": "class:project-a|l-lawn", "subject": "L-Lawn", "question": "Which slot pays for what this class draws?",
            "candidates": SLOTS[:3],
            "evidence": [{"function": "name match", "source": "classname:l-lawn", "strength": "strong", "supports": "5.0 GROUNDCOVERS"},
                         {"function": "budget match", "source": "budget slot 5.0 lines", "strength": "supporting", "supports": "5.0 GROUNDCOVERS"}],
            "adjudication": {k: v for k, v in record.items() if v is not None}}


def test_jev_settles_a_likely_case_only_under_its_written_schema(tmp_path):
    dm, cfg = detective(), marpa_config()
    result = dm.verdict(jev_case(), cfg, tmp_path)
    assert result["verdict"] == "settled by adjudication" and result["answer"] == "5.0 GROUNDCOVERS"
    assert result["adjudication"]["band"] == "auto" and result["threshold"]["value"] == 0.90
    refused = {
        "it names no schema": dict(schema=None),
        "schema 'free_text' is not one of the written schemas": dict(schema="free_text"),
        "not one of the options offered": dict(offered=["4.0 FLATWORK / HARDSCAPE", "9.0 PLANT MATERIAL"]),
        "does not list the options it was offered": dict(offered=None),
        "companion 'evidence_insufficient' answered 0.8": dict(companions={"evidence_insufficient": 0.8}),
        "post-check 'existing_is_never_proposed_work' did not pass": dict(post_checks={"existing_is_never_proposed_work": False}),
        "post-check 'existing_is_never_proposed_work' of schema 'class_slot' was not run": dict(post_checks={}),
        "names no receipt": dict(receipt=None),
        "no written reasoning": dict(reasoning=None),
    }
    for reason, change in refused.items():
        result = dm.verdict(jev_case(**change), cfg, tmp_path)
        assert result["verdict"] == "likely", reason
        assert reason in result["why"] and "adjudication not accepted" in result["why"], (reason, result["why"])


def test_the_abstain_answer_is_never_applied_and_quiet_companions_never_escalate(tmp_path):
    dm, cfg = detective(), marpa_config()
    case = jev_case(answer="OTHER")
    case["candidates"] = SLOTS
    case["evidence"][0]["supports"] = "OTHER"
    case["evidence"][1]["supports"] = "OTHER"
    result = dm.verdict(case, cfg, tmp_path)
    assert result["verdict"] == "likely" and "abstained (OTHER), which is never applied" in result["why"]
    # same_concept and covers_term are information, not warnings (MARPA's escalates: false)
    result = dm.verdict(jev_case(companions={"same_concept": 0.99, "covers_term": 0.1}), cfg, tmp_path)
    assert result["verdict"] == "settled by adjudication"


def test_confidence_is_gated_in_bands_and_a_low_answer_is_kept_as_the_suggestion(tmp_path):
    dm, cfg = detective(), marpa_config()
    review = dm.verdict(jev_case(confidence=0.75), cfg, tmp_path)
    assert review["verdict"] == "likely" and review["adjudication"]["band"] == "review"
    assert "kept as the suggestion" in review["why"]
    low = dm.verdict(jev_case(confidence=0.3), cfg, tmp_path)
    assert low["adjudication"]["band"] == "low" and low["verdict"] == "likely"
    # the calibrated threshold replaces the preset's 0.90
    (tmp_path / "fable").mkdir()
    (tmp_path / "fable/calibration.json").write_text(json.dumps({"threshold": 0.74, "cases": 37, "date": "2026-11-16"}))
    assert dm.verdict(jev_case(confidence=0.75), cfg, tmp_path)["verdict"] == "settled by adjudication"
    # Jev disagreeing with the one strong source leaves it likely
    other = dm.verdict(jev_case(answer="9.0 PLANT MATERIAL"), cfg, tmp_path)
    assert other["verdict"] == "likely" and "chose 9.0 PLANT MATERIAL instead" in other["why"]


def test_without_a_policy_the_original_adjudication_rule_is_unchanged(tmp_path):
    dm = detective()
    case = jev_case()
    case["adjudication"] = {"by": "reviewer", "answer": "5.0 GROUNDCOVERS", "confidence": 0.8, "reasoning": "label and name agree"}
    cfg = {"detective_functions": marpa_config()["detective_functions"]}
    assert dm.verdict(case, cfg, tmp_path)["verdict"] == "settled by adjudication"


# --------------------------------------------------------------------------- back-test calibration

def synthetic_decided(n_right=11, n_wrong=2):
    cases = []
    for i in range(n_right + n_wrong):
        right = i < n_right
        case = jev_case(confidence=0.95 if right else 0.6, answer="5.0 GROUNDCOVERS" if right else "9.0 PLANT MATERIAL", blind=True)
        case["id"] = "case-%d" % i
        case["owner_answer"] = "5.0 GROUNDCOVERS"
        case["evidence"].append({"function": "rules and precedent", "source": "ruling:%d" % i, "strength": "decisive", "supports": "5.0 GROUNDCOVERS"})
        case["ruling_sources"] = ["ruling:%d" % i]
        cases.append(case)
    return cases


def backtest(project, cases_path, *extra):
    return run([*script("detective_backtest.py"), "--project", str(project), "--cases", str(cases_path), "--json", *extra])


def test_backtest_needs_enough_accepted_answers_and_uses_blind_adjudications(tmp_path):
    project = bare_project(tmp_path)
    assert init(project, "--preset", "marpa").returncode == 0
    decided = tmp_path / "decided.json"
    decided.write_text(json.dumps(synthetic_decided()))
    proc = backtest(project, decided, "--min-accepted", "10", "--write-calibration")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["evidence_removed_as_the_cases_own_ruling"] == 13
    assert report["calibration"]["threshold"] == 0.95 and report["calibration"]["min_accepted"] == 10
    assert report["settled_by_adjudication"] == {"right": 11, "wrong": 0} and report["outcome"]["wrong"] == 0
    assert json.loads((project / "fable/calibration.json").read_text())["threshold"] == 0.95
    # with too few answers nothing is calibrated, and adjudication settles nothing
    (project / "fable/calibration.json").unlink()
    report = json.loads(backtest(project, decided, "--min-accepted", "20", "--write-calibration").stdout)
    assert report["calibration"]["threshold"] is None and report["settled_by_adjudication"]["right"] == 0
    assert not (project / "fable/calibration.json").exists()
    # an adjudication that was not asked blind never takes part in a verdict
    cases = synthetic_decided()
    for c in cases:
        c["adjudication"]["blind"] = False
    decided.write_text(json.dumps(cases))
    report = json.loads(backtest(project, decided, "--min-accepted", "10").stdout)
    assert report["settled_by_adjudication"]["right"] == 0 and report["calibration"]["threshold"] == 0.95


@pytest.mark.skipif(not DECIDED.exists(), reason="decided_cases.json is exported from MARPA's repository on the owner's machine")
def test_marpas_decided_cases_reproduce_the_blind_test(tmp_path):
    project = bare_project(tmp_path)
    assert init(project, "--preset", "marpa").returncode == 0
    report = json.loads(backtest(project, DECIDED, "--min-accepted", "10", "--target", "0.9").stdout)
    assert report["cases"] == 37 and report["evidence_removed_as_the_cases_own_ruling"] == 37
    assert report["outcome"] == {"right": 29, "wrong": 1, "open": 7, "invalid": 0}
    assert report["settled_by_adjudication"] == {"right": 29, "wrong": 0}
    # the one wrong verdict is the class the name and the project's own document both place under groundcovers,
    # which the owner ruled flatwork (the same case MARPA's own blind test gets wrong)
    assert len(report["wrong"]) == 1 and report["wrong"][0]["answer"] == "5.0 GROUNDCOVERS"
    assert report["wrong"][0]["owner_answer"] == "4.0 FLATWORK / HARDSCAPE"
    cut = {c["cutoff"]: (c["accepted"], c["right"]) for c in report["calibration"]["cutoffs"]}
    assert cut[0.5] == (37, 32) and cut[0.7] == (36, 32) and cut[0.9] == (34, 31)   # MARPA's own detective_cutoff.json
    assert report["calibration"]["threshold"] == 0.88


# --------------------------------------------------------------------------- question triage

def test_marpa_triage_words_sort_firm_choices_from_facts(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("fable_preflight_marpa", SKILL / "scripts/preflight.py")
    pf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pf)
    generic = pf.triage_question("What tolerance does the budget use for paver area?")
    assert generic["kind"] == "judgment"   # the generic words read "tolerance" as a preference
    pf.load_triage_cues(tmp_path, "marpa")
    assert pf.triage_question("What tolerance does the budget use for paver area?")["kind"] == "evidence"
    assert pf.triage_question("How many linear feet of steel edging does sheet L1.01 show?")["kind"] == "evidence"
    assert pf.triage_question("Which species is labelled at the north bed?")["kind"] == "evidence"
    for q in ["Should the irrigation allowance stay at 8% on this project?", "What is the design intent for the entry court?",
              "Does the client preference for flagstone override the budget?", "What fee policy applies to change orders?"]:
        assert pf.triage_question(q)["kind"] == "judgment", q


# --------------------------------------------------------------------------- owner rules

MARPA_RULES = """# Rules for every agent in this repository (Claude Code reads this file first)

These are the owner's rules. The tests enforce them; a rule here that a test does not enforce is still a rule.

1. **One writer at a time.** Several agents share this folder. Before writing the working database:
   If `take` says another agent holds it, do not write: wait, or tell the owner. Never delete or edit `.writer.lock`
2. **Never edit a test to make it pass.** A failing test means the rule, the data or the standard is wrong.
5. **Jev** is called only for a decision with a written schema in `jev_schemas.yaml`; no schema, no call.
10. **Record every task** in `/Volumes/MARPA/apps/marpa-desk/TASKS.md` (commit, test result, state). Report only
11. **Ask clearly (D131).** Every question to the owner, in chat, a BCF topic or the living page, stands on its own.
12. **Detective work before judgment calls (D147).** Ask the owner or the firm only when the evidence cannot decide it and it is a
13. **The owner's word is the rule (D148).** When the owner states a rule or decision, record and adopt it as stated; never ask
"""


def audit(project):
    proc = run([*script("audit_rules.py"), "--project", str(project), "--json"])
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_marpas_rules_are_recognised_as_owner_rules_and_honored(tmp_path):
    project = bare_project(tmp_path)
    assert init(project, "--preset", "marpa").returncode == 0
    (project / "CLAUDE.md").write_text(MARPA_RULES)
    data = audit(project)
    kinds = {o["kind"] for o in data["owner_rules"]}
    assert {"marpa-one-writer", "marpa-tests-not-edited", "marpa-jev-schema-first", "marpa-record-every-task",
            "marpa-ask-clearly", "marpa-detective-first", "marpa-owner-word"} <= kinds
    assert all(o["effect"] == "honored" for o in data["owner_rules"]) and data["findings"] == []
    # without the preset, "wait, or tell the owner" would be read as a rule that needs a person
    write_cfg(project, owner_rules=[], owner_rule_headings=[])
    data = audit(project)
    assert not any(o["kind"].startswith("marpa-") for o in data["owner_rules"])


def test_a_blocking_owner_rule_from_the_preset_stops_the_launch(tmp_path):
    from conftest import prepared_project
    project = prepared_project(tmp_path)
    cfg = read_cfg(project)
    rules = marpa_config()["owner_rules"] + [{"kind": "marpa-client-mail-by-owner", "effect": "blocks",
                                              "patterns": [r"only the owner sends (?:client )?mail"],
                                              "how": "A run cannot send or wait for the owner's client mail."}]
    write_cfg(project, owner_rules=rules, owner_rule_headings=PRESET["config"]["owner_rule_headings"])
    (project / "CLAUDE.md").write_text(MARPA_RULES + "14. Only the owner sends client mail about a budget.\n")
    commit_all(project, "rules")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "owner rules")
    assert row["status"] == "FAIL" and "Only the owner sends client mail" in row["detail"]
    (project / "CLAUDE.md").write_text(MARPA_RULES)
    commit_all(project, "rules without the blocking line")
    _, data = readiness(project)
    assert statuses(data)["owner rules"] == "PASS"


@needs_marpa
def test_marpas_own_claude_md_is_fully_honored(tmp_path):
    project = bare_project(tmp_path)
    assert init(project, "--preset", "marpa").returncode == 0
    (project / "CLAUDE.md").write_text((MARPA / "CLAUDE.md").read_text())
    data = audit(project)
    assert data["owner_rules"] and all(o["effect"] == "honored" for o in data["owner_rules"])
    assert data["findings"] == []


# --------------------------------------------------------------------------- guard: the one file outside the project

def test_the_guard_lets_the_run_write_marpas_task_log_and_nothing_else_outside(tmp_path):
    from conftest import hook
    project = bare_project(tmp_path)
    assert init(project, "--preset", "marpa").returncode == 0
    tasks = tmp_path / "desk" / "TASKS.md"
    write_cfg(project, writable_outside_paths=[str(tasks)])
    ok = hook(project, "fable_guard.py", {"tool_name": "Edit", "tool_input": {"file_path": str(tasks)}, "cwd": str(project)})
    assert ok.returncode == 0, ok.stderr
    blocked = hook(project, "fable_guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "desk" / "OTHER.md")}, "cwd": str(project)})
    assert blocked.returncode == 2 and "outside the project" in blocked.stderr
    for path in ["class_rulings.yaml", "jev_schemas.yaml", ".writer.lock", "working.duckdb"]:
        proc = hook(project, "fable_guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(project / path)}, "cwd": str(project)})
        assert proc.returncode == 2 and "protected" in proc.stderr, path
    proc = hook(project, "fable_guard.py", {"tool_name": "Bash", "tool_input": {"command": "pxt schema update"}, "cwd": str(project)})
    assert proc.returncode == 2


# --------------------------------------------------------------------------- launch requirements and the companion repository

def test_readiness_refuses_a_launch_whose_required_functions_or_files_are_missing(tmp_path):
    from conftest import prepared_project
    project = prepared_project(tmp_path)
    funcs = [dict(f, project_sources=["src/*.py"]) for f in marpa_config()["detective_functions"]]
    req = marpa_config()["launch_requires"]
    write_cfg(project, detective_functions=funcs, launch_requires=req)
    commit_all(project, "requires")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "launch requires")
    assert row["status"] == "FAIL"
    assert "docs/standard/PRODUCT_GOALS.md, which does not exist yet" in row["detail"]
    assert "'takeoff from geometry' is planned and no task in fable/STATE.md builds it" in row["detail"]
    # a required function that is only planned stops the launch
    write_cfg(project, launch_requires=dict(req, functions_built=["spatial relationships"], files=[], functions_first_tasks=[]))
    commit_all(project, "planned required")
    _, data = readiness(project)
    assert "'spatial relationships', which is only planned; build it before launch" in next(r for r in data["rows"] if r["check"] == "launch requires")["detail"]
    # files in place and the planned functions as first tasks: it passes
    for rel in req["files"]:
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / rel).write_text("x\n")
    state = (project / "fable/STATE.md").read_text().replace("## Tasks\n", "## Tasks\n\n- [ ] Build takeoff from geometry\n- [ ] Build spatial relationships\n- [ ] Build back-test against real budgets\n", 1)
    (project / "fable/STATE.md").write_text(state)
    write_cfg(project, launch_requires=req)
    commit_all(project, "ready")
    _, data = readiness(project)
    assert statuses(data)["launch requires"] == "PASS", next(r for r in data["rows"] if r["check"] == "launch requires")


def test_the_companion_repository_must_be_on_its_run_branch_and_clean_and_the_guard_covers_it(tmp_path):
    from conftest import hook, prepared_project
    project = prepared_project(tmp_path)
    desk = bare_project(tmp_path, "desk")
    (desk / "tokens.css").write_text(":root{}\n")
    commit_all(desk, "tokens")
    write_cfg(project, companion_repositories=[{"path": str(desk), "branch": "fable/marpa-1", "test_command": "bun run test"}],
              protected_paths=read_cfg(project)["protected_paths"] + ["tokens.css"])
    commit_all(project, "companion")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "companion desk")
    assert row["status"] == "FAIL" and "on main" in row["detail"] and "switch -c fable/marpa-1" in row["detail"]
    git(desk, "switch", "-qc", "fable/marpa-1")
    (desk / "loose.txt").write_text("x\n")
    _, data = readiness(project)
    assert "uncommitted changes" in next(r for r in data["rows"] if r["check"] == "companion desk")["detail"]
    (desk / "loose.txt").unlink()
    _, data = readiness(project)
    assert statuses(data)["companion desk"] == "PASS"
    ok = hook(project, "fable_guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(desk / "src" / "Budget.tsx")}, "cwd": str(project)})
    assert ok.returncode == 0, ok.stderr
    for target in [desk / "tokens.css", desk / ".git" / "config"]:
        no = hook(project, "fable_guard.py", {"tool_name": "Edit", "tool_input": {"file_path": str(target)}, "cwd": str(project)})
        assert no.returncode == 2 and "companion repository" in no.stderr, target
    no = hook(project, "fable_guard.py", {"tool_name": "Bash", "tool_input": {"command": "echo x > %s" % (desk / "tokens.css")}, "cwd": str(project)})
    assert no.returncode == 2


# --------------------------------------------------------------------------- no language model in a calculation

def test_readiness_and_the_stop_gate_refuse_a_model_call_in_calculation_code(tmp_path):
    from conftest import hook, prepared_project
    project = prepared_project(tmp_path)
    (project / "calc.py").write_text("def total(lines):\n    return sum(l['qty'] * l['rate'] for l in lines)\n")
    (project / "jev_schema.py").write_text("from jev_client import client\ndef ask(q):\n    return client().system_one({}, q)\n")
    write_cfg(project, deterministic_code=marpa_config()["deterministic_code"])
    commit_all(project, "plain calc")
    _, data = readiness(project)
    assert statuses(data)["no model calls"] == "PASS"
    (project / "budget_estimate.py").write_text("import anthropic\n\ndef rate(c):\n    return anthropic.Anthropic().messages.create(model='x')\n")
    commit_all(project, "a model in a calculation")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "no model calls")
    assert row["status"] == "FAIL" and "budget_estimate.py:1" in row["detail"] and "jev_schema.py" not in row["detail"]
    # the stop gate holds the run on the same finding once the tasks and the verify command pass
    state = (project / "fable/STATE.md").read_text().replace("- [ ]", "- [x]")
    (project / "fable/STATE.md").write_text(state)
    (project / "fable/REPORT.md").write_text("Done.\n")
    write_cfg(project, verify_command="true")
    proc = hook(project, "fable_stop_gate.py", {"session_id": "s", "stop_hook_active": False})
    assert "calls a language model" in (proc.stdout + proc.stderr) and "budget_estimate.py:4" in (proc.stdout + proc.stderr)
    (project / "budget_estimate.py").write_text("def rate(a, q):\n    return sum(a) / sum(q)\n")
    proc = hook(project, "fable_stop_gate.py", {"session_id": "s", "stop_hook_active": False})
    assert "calls a language model" not in (proc.stdout + proc.stderr)


def test_a_source_outside_the_project_is_checked_by_its_absolute_path(tmp_path):
    dm = detective()
    outside = tmp_path / "allocation" / "SPEC.md"
    outside.parent.mkdir()
    outside.write_text("x\n")
    cfg = {"detective_functions": [{"name": "back-test", "looks_at": "a", "returns": "b", "strength": "decisive", "status": "planned",
                                    "test": "t", "project_sources": [str(outside), str(tmp_path / "allocation" / "MISSING.md")]}]}
    problems = dm.registry_problems(cfg, tmp_path / "proj")
    assert problems == ["'back-test' reads %s, which matches nothing in this project" % (tmp_path / "allocation" / "MISSING.md")]


# --------------------------------------------------------------------------- the desk map

def desk_map_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("marpa_desk_map", PRESET_DIR / "desk_map.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_desk(tmp_path):
    desk = tmp_path / "desk"
    (desk / "src/lib/desk").mkdir(parents=True)
    (desk / "src/components/worksheet").mkdir(parents=True)
    (desk / "src-tauri/src").mkdir(parents=True)
    (desk / "src/lib/desk/featureRegistry.ts").write_text(
        'export const FEATURES = {\n  sheet: {\n    group: "documents",\n  },\n  docs: {\n    group: "documents",\n  },\n'
        '  database: {\n    group: "database",\n  },\n  pipeline: {\n    group: "diagnostics",\n  },\n};\n')
    (desk / "src/components/worksheet/AppShell.tsx").write_text(
        'import { Sheet } from "./Sheet";\nimport Docs from "./Docs";\nimport { DatabaseView } from "../db/DatabaseView";\nimport { Pipeline } from "../pipe/Pipeline";\n'
        'export const AppShell = ({ view }) => view === "database" ? (<DatabaseView />) : view === "pipeline" ? (<Pipeline />)'
        ' : view === "docs" ? (<Docs />) : view === "sheet" ? (<Sheet />) : null;\n')
    (desk / "src/components/worksheet/Sheet.tsx").write_text('import { invoke } from "@tauri-apps/api/core";\ninvoke("save_budget");\n')
    (desk / "src/components/db/DatabaseView.tsx").parent.mkdir(parents=True)
    (desk / "src/components/db/DatabaseView.tsx").write_text('invoke("pxt_query");\n')
    (desk / "src-tauri/src/lib.rs").write_text('#[tauri::command]\npub fn save_budget() {}\n#[tauri::command]\nasync fn pxt_query() {}\n#[tauri::command]\nfn unused_cmd() {}\n')
    mods = {
        "src/router.tsx": ["src/components/worksheet/AppShell.tsx"],
        "src/components/worksheet/AppShell.tsx": ["src/components/worksheet/Sheet.tsx", "src/components/worksheet/Docs.tsx",
                                                  "src/components/db/DatabaseView.tsx", "src/components/pipe/Pipeline.tsx"],
        "src/components/worksheet/Sheet.tsx": ["src/lib/workbook/types.ts"],
        "src/components/worksheet/Docs.tsx": [],
        "src/components/db/DatabaseView.tsx": ["src/lib/workbook/types.ts", "src/lib/db/query.ts"],
        "src/components/pipe/Pipeline.tsx": ["src/lib/db/query.ts"],
        "src/lib/workbook/types.ts": [], "src/lib/db/query.ts": [], "src/lib/old/orphan.ts": [],
    }
    spec = {"./Sheet": "src/components/worksheet/Sheet.tsx", "./Docs": "src/components/worksheet/Docs.tsx",
            "../db/DatabaseView": "src/components/db/DatabaseView.tsx", "../pipe/Pipeline": "src/components/pipe/Pipeline.tsx"}
    dc = {"modules": []}
    for src, deps in mods.items():
        entry = {"source": src, "dependencies": [{"resolved": d, "module": d} for d in deps]}
        if src.endswith("AppShell.tsx"):
            entry["dependencies"] = [{"resolved": r, "module": m} for m, r in spec.items()]
        dc["modules"].append(entry)
    return desk, dc


def test_the_desk_map_sorts_files_into_needed_shared_and_safe_to_remove(tmp_path):
    dm = desk_map_module()
    desk, dc = fake_desk(tmp_path)
    sets = dm.keep_cut(desk, dc, ["documents"], ["database", "diagnostics"])
    assert sets["kept_view_components"] == ["src/components/worksheet/Docs.tsx", "src/components/worksheet/Sheet.tsx"]
    assert sets["cut_view_components"] == ["src/components/db/DatabaseView.tsx", "src/components/pipe/Pipeline.tsx"]
    assert sets["shared"] == ["src/lib/workbook/types.ts"]
    assert sets["safe_to_remove"] == ["src/components/db/DatabaseView.tsx", "src/components/pipe/Pipeline.tsx", "src/lib/db/query.ts"]
    assert "src/components/worksheet/AppShell.tsx" in sets["needed"] and "src/lib/db/query.ts" not in sets["needed"]
    assert sets["reached_by_neither"] == ["src/lib/old/orphan.ts"]
    assert sets["largest_shared"][0] == {"file": "src/lib/workbook/types.ts", "imported_by": 2}
    links = dm.tauri_links(desk, sets)
    assert links["rust_commands"] == 3 and links["rust_commands_never_called"] == ["unused_cmd"]
    assert links["commands_only_for_cut_features"] == ["pxt_query"] and links["called_but_not_in_rust"] == []
    order = dm.work_order({"commit": "abc123456", "date": "2026-11-17", "needed": 4, "shared": 1, "safe_to_remove": 3, "reached_by_neither": 1,
                           "largest_shared": sets["largest_shared"], "tauri": links}, sets)
    assert "Desk cut work order (desk commit abc123456" in order and "`pxt_query`" in order and "`src/lib/db/query.ts`" in order


def test_readiness_refuses_a_desk_that_has_no_map_for_its_commit(tmp_path):
    from conftest import prepared_project
    project = prepared_project(tmp_path)
    desk = bare_project(tmp_path, "desk")
    git(desk, "switch", "-qc", "fable/marpa-1")
    (desk / ".gitignore").write_text((desk / ".gitignore").read_text() + "var/\n")
    commit_all(desk, "ignore var")
    write_cfg(project, companion_repositories=[{"path": str(desk), "branch": "fable/marpa-1", "map": "var/reference/desk-map/*_{commit}/keep-cut.json"}])
    commit_all(project, "companion with map")
    _, data = readiness(project)
    row = next(r for r in data["rows"] if r["check"] == "companion desk map")
    commit = git(desk, "rev-parse", "--short=9", "HEAD").stdout.strip()
    assert row["status"] == "FAIL" and commit in row["detail"]
    (desk / "var/reference/desk-map/2026-11-17_0000000aa").mkdir(parents=True)
    (desk / "var/reference/desk-map/2026-11-17_0000000aa/keep-cut.json").write_text("{}")
    _, data = readiness(project)
    assert statuses(data)["companion desk map"] == "FAIL", "a map of another commit does not count"
    (desk / ("var/reference/desk-map/2026-11-17_%s" % commit)).mkdir(parents=True)
    (desk / ("var/reference/desk-map/2026-11-17_%s/keep-cut.json" % commit)).write_text("{}")
    _, data = readiness(project)
    assert statuses(data)["companion desk map"] == "PASS" and statuses(data)["companion desk"] == "PASS"


# --------------------------------------------------------------------------- mission shapes

@pytest.mark.parametrize("shape", ["single", "stage1", "stage2"])
def test_each_mission_shape_has_its_own_done_check(tmp_path, shape):
    project = bare_project(tmp_path)
    proc = run([*script("init_handoff.py"), "--project", str(project), "--preset", "marpa", "--shape", shape, "--apply-settings"])
    assert proc.returncode == 0, proc.stderr
    cfg = read_cfg(project)
    mission = (project / "fable/MISSION.md").read_text()
    assert cfg["shape"] == shape
    if shape == "single":
        assert cfg["branch"] == "fable/run-1" and len(cfg["definition_of_done"]["rows"]) == 15 and "stage" not in cfg["verify_command"]
        assert cfg["companion_repositories"] and "stage 1 of 2" not in mission
    if shape == "stage1":
        assert cfg["branch"] == "fable/marpa-stage1" and cfg["companion_repositories"] == []
        assert cfg["verify_command"].endswith("done_check.py --check --stage 1") and "bun run test" not in cfg["verify_command"]
        assert not any(r.startswith("the desk app") for r in cfg["definition_of_done"]["rows"]) and "stage 1 of 2" in mission
    if shape == "stage2":
        assert cfg["branch"] == "fable/marpa-stage2" and cfg["verify_command"].endswith("done_check.py --check --stage 2")
        assert "bun run test" in cfg["verify_command"] and "runs/done/stage1.json" in cfg["launch_requires"]["files"]
        assert {"takeoff from geometry", "back-test"} <= set(cfg["launch_requires"]["functions_built"]) and "stage 2 of 2" in mission


def test_an_unknown_shape_is_refused(tmp_path):
    project = bare_project(tmp_path)
    proc = init(project, "--preset", "marpa", "--shape", "stage3")
    assert proc.returncode != 0 and "no mission shape 'stage3'" in proc.stderr and "stage1" in proc.stderr
    assert init(project, "--shape", "stage1").returncode != 0
