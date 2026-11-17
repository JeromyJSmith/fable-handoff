#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Render the MARPA mission, ledger and decisions for each mission shape.

Each shape (single, stage1, stage2) gets shapes/<shape>/MISSION.md, STATE.md
and DECISIONS.md, written from preset.json, so the verify command in the
mission is always the shape's own, character for character. Init installs
them in place of the templates; the MARPA section and the shape's note are
added to the mission as before. Run this after any change to preset.json:

    uv run --script build_shape_files.py          # write
    uv run --script build_shape_files.py --check  # exit 1 when a file is out of date
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent.parent / "templates" / "MISSION.md"

JOB = {
    "stage1": "Load the data for the MARPA standard, stage 1 of 3. Every past project that has a budget is loaded with its own budget as the truth, through the JSON and jq processes, until everything needed to allocate and estimate is in: every budget file, every line coded with its item and component, the measurement tables built, the finance formulas checked and every budgeted drawing decoded. Nothing is estimated in this stage.",
    "stage2": "Compute the MARPA weighted averages, stage 2 of 3, on the data stage 1 loaded. Each project's allowances are spread top-down onto its drawn classes through the allocation engine with every cent conserved, takeoff from geometry gives the compatible quantities, and the weighted average cost per class unit, the category shares and the benchmarks with cohort and spread are computed and tested against their equations. Nothing is estimated for a project yet.",
    "stage3": "Benchmark the MARPA estimating, stage 3 of 3. Every budgeted project is rerun with its own budget held out and estimated from the others through the stage 2 averages, Ulm is estimated the way Solomon will be with its own budget and cost to complete held back as the answer, Solomon gets its first estimate with a source for every number, and the held-out error is reported per category and in total for the owner to set the targets.",
}
WHY = ("MARPA must run without its founder: anyone at the firm should turn a drawing into a priced, editable budget the same way the founder would. "
       "The data comes first and is the truth; correct, conserved money and plain, tested calculations come before speed or new features.")
T = lambda text, check: "%s (check: `%s`)" % (text, check)
DONE = "test -f done_check.py && uv run done_check.py --check --stage %d"
TASKS = {
    "stage1": [T("Every budget file loaded, including inputs/owner-import-2026-11-16 and Mallett's drawing, each line accounted for", "uv run pytest -q tests/test_audit_stage1.py"),
               T("The numbering standard holds in every slot: the component digit kept in every code, no item named only by a component word", "uv run pytest -q tests/test_numbering_standard.py"),
               T("The 153 uncoded lines worked out: slot, item and component, or an open case with what would settle it", "uv run pytest -q tests/test_audit_stage1.py"),
               T("The line_measure and item_measure tables built, with their unit rules tested", "uv run pytest -q tests/test_measure.py"),
               T("The finance formula check done for every workbook", "uv run pytest -q tests/test_calculations.py"),
               T("Every budgeted project's .vwx decoded with vwx/run_vwx.sh", "uv run pytest -q tests/test_vwx_pipeline.py"),
               T("Full accounting: every drawn class homed or listed as unhomed, every line's money placed, labelled as spread, or shown as unplaced with its amount", DONE % 1),
               T("Write done_check.py with --stage 1; on success it writes fable/done/stage1.json", DONE % 1),
               T("Full verify command passes and fable/REPORT.md is written", "VERIFY")],
    "stage2": [T("Build takeoff from geometry: compatible quantities per class from the decoded polygons and paths, with tests", DONE % 2),
               T("Allowances spread top-down through the allocation engine: 0 unexplained cents, 0 duplicated money", DONE % 2),
               T("Weighted averages and sliders match their equations, with tests on fixed inputs", "uv run pytest -q tests/test_calculations.py"),
               T("Category shares where the evidence is short; lump sums and fees counted once", DONE % 2),
               T("Benchmarks with cohort and spread for every class unit", DONE % 2),
               T("Extend done_check.py with --stage 2; on success it writes fable/done/stage2.json", DONE % 2),
               T("Full verify command passes and fable/REPORT.md is written", "VERIFY")],
    "stage3": [T("Build the back-test: every budgeted project rerun held out through calc.held_out", "uv run pytest -q tests/test_calculations.py"),
               T("Ulm estimated like Solomon, its answer held out by calc.ANSWER_ONLY, compared with its budget and cost to complete", DONE % 3),
               T("Solomon's first estimate with a source for every number and unknowns unpriced", DONE % 3),
               T("Held-out error per category and in total, with coverage and bias, written for the owner", DONE % 3),
               T("Extend done_check.py with --stage 3", DONE % 3),
               T("Full verify command passes and fable/REPORT.md is written", "VERIFY")],
}
DECISIONS_BEFORE = [
    "Three data-first stages: the data, the weighted averages, the benchmark; each its own run. Reason: the owner's decision of 2026-11-16; nothing is estimated before the data is in.",
    "Allowances first: each category allowance from the project settings is spread top-down onto that category's drawn classes. Reason: this is how MARPA budgets (the allocation method).",
    "The allocation engine is read and run through its own commands; the run integrates with it and does not rebuild it. Reason: it already conserves every dollar on six projects.",
    "Every calculation is plain code with tests; Jev answers only bounded decisions under the written schemas. Reason: the owner's rule for deterministic calculations.",
    "A project's own budget is never used to estimate it. Reason: held-out validation.",
    "The desk app is left alone until stage 1 is through. Reason: the owner's decision of 2026-11-16.",
    "Quantity tolerances stay as they are: area and length 5 percent, counts exact, volume 10 percent, weight never compared. Reason: the owner's decision of 2026-11-16.",
    "The answers in fable/owner_decisions.json, once given, are the owner's decisions for this run.",
]


def section(text: str, title: str, body: str) -> str:
    start = text.index("## %s\n" % title)
    end = text.find("\n## ", start + 1)
    return text[:start] + "## %s\n\n%s\n" % (title, body.strip()) + (text[end:] if end != -1 else "")


def mission(shape: str, config: dict) -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace(text.splitlines()[0], "# Mission: MARPA, %s" % {"stage1": "the data (stage 1 of 3)", "stage2": "the weighted averages (stage 2 of 3)", "stage3": "the benchmark (stage 3 of 3)"}[shape], 1)
    text = re.sub(r"<!--.*?-->\n*", "", text, count=1, flags=re.S)
    text = section(text, "Job", JOB[shape])
    text = section(text, "Why", WHY)
    text = section(text, "Where things are", "The MARPA section below names every place. Build and test commands are in the Done section.")
    allowed = ["Commit to the branch %s in this repository" % config["branch"]]
    if config.get("companion_repositories"):
        allowed.append("Commit to the branch %s in the desk repository (%s)" % (config["companion_repositories"][0]["branch"], config["companion_repositories"][0]["path"]))
    allowed += ["Run the allocation engine's own commands (read and run only)", "Install a missing package with uv or bun, pinned exactly"]
    forbidden = ["Do not edit the allocation engine's code, guide or adjustments, because it is the firm's working system",
                 "Do not push, and do not touch main, because the owner merges",
                 "Do not send client mail or touch the desk's Pixeltable home, because both reach outside this run"]
    out_of_scope = ["New standard entries from old drawings beyond what the budget needs"]
    out_of_scope.insert(0, "Any change to the desk app (deferred until the owner decides after stage 1)")
    if config.get("shape") == "stage1":
        out_of_scope.insert(1, "Estimating anything (stages 2 and 3)")
    guard = ("Allowed without asking:\n\n" + "\n".join("- " + a for a in allowed) + "\n\nNot allowed:\n\n" + "\n".join("- " + f for f in forbidden) +
             "\n\nOut of scope, leave these alone even though nothing blocks them:\n\n" + "\n".join("- " + o for o in out_of_scope))
    text = section(text, "Guardrails", guard)
    done_start = text.index("## Done\n")
    done = text[done_start:]
    done = done.replace("`{{FILL: the verify command, character for character as in fable/handoff.json}}` exits 0.", "`%s` exits 0." % config["verify_command"])
    done = re.sub(r"- \{\{FILL: any further condition.*?\n", "- Every row of the definition of done for this shape meets its target (listed in the MARPA section).\n", done, flags=re.S)
    return DRAFT + "\n" + text[:done_start] + done


DRAFT = "<!-- draft: prepare.py phase 6 completes this -->"


def state(shape: str, verify: str) -> str:
    return (DRAFT + "\n# Run ledger\n\n## Current focus\n\nNot started.\n\n## Next step\n\nRead fable/MISSION.md and the documents it names first, then confirm or extend the task list below.\n\n"
            "## Tasks\n\n" + "\n".join("- [ ] " + t.replace("`VERIFY`", "`%s`" % verify) for t in TASKS[shape]) + "\n\n## Notes for a resuming session\n\n"
            "Run the allocation engine with UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation uv run --no-sync; a plain uv run makes a new environment there.\n")


def decisions() -> str:
    return (DRAFT + "\n# Decisions\n\n## Made before the run\n\n" + "\n".join("- " + d for d in DECISIONS_BEFORE) +
            "\n\n## Defaults for anything not listed\n\n- Prefer the option that is easiest to undo.\n- Prefer the smallest change that satisfies the mission.\n"
            "- Follow the conventions already in the codebase over personal preference.\n\n## Open questions for the owner\n\nNone.\n\n"
            "## Made during the run\n\n## Left for the owner\n")


def render(preset: dict) -> dict[str, str]:
    out = {}
    for shape, spec in (preset.get("shapes") or {}).items():
        config = dict(preset["config"], **(spec.get("config") or {}), shape=shape)
        config.setdefault("branch", "fable/run-1")
        out["shapes/%s/MISSION.md" % shape] = mission(shape, config)
        out["shapes/%s/STATE.md" % shape] = state(shape, config["verify_command"])
        out["shapes/%s/DECISIONS.md" % shape] = decisions()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    files = render(json.loads((HERE / "preset.json").read_text(encoding="utf-8")))
    stale = [rel for rel, text in files.items() if not (HERE / rel).exists() or (HERE / rel).read_text(encoding="utf-8") != text]
    if args.check:
        print("\n".join(stale) or "all shape files are current")
        return 1 if stale else 0
    for rel, text in files.items():
        (HERE / rel).parent.mkdir(parents=True, exist_ok=True)
        (HERE / rel).write_text(text, encoding="utf-8")
    print("wrote %d file(s)" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
