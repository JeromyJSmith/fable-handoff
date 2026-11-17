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
    "single": "Build the MARPA preflight and the slimmed desk app in one run. A drawing dropped in the desk app is decoded, its classes placed, the project's allowances spread onto its drawn classes through the allocation engine with every cent conserved, the weighted averages and sliders kept from past projects, every past project estimated held out, Solomon's first estimate made with a source for every number, and a budget in the standard's form handed to the desk's budget section, which keeps its bids, subcontractors and administration markup unchanged.",
    "stage1": "Build the MARPA preflight, stage 1 of 2. A drawing is decoded, its classes placed, the project's allowances spread onto its drawn classes through the allocation engine with every cent conserved, the weighted averages and sliders kept from past projects, every past project estimated held out, and Solomon's first estimate made with a source for every number and every unknown left unpriced. The desk app is not changed in this stage.",
    "stage2": "Build the slimmed MARPA desk app, stage 2 of 2, on the preflight stage 1 built. Cut the desk by its map's work order to the budget features, Docs, Standards and the MARPA Standard tab, feed its budget section the preflight's budget in the standard's form without changing how bids, subcontractors and the administration markup work, and add the analysis views and the guided tour for someone new.",
}
WHY = ("MARPA must run without its founder: anyone at the firm should turn a drawing into a priced, editable budget the same way the founder would. "
       "Correct, conserved money and plain, tested calculations come before speed or new features.")
TASKS = {
    "single": ["Build takeoff from geometry: compatible quantities per class from the decoded polygons and paths, with tests",
               "Build spatial relationships: nearness and containment as evidence for placement, with tests",
               "Drawing intake hands every decoded, placed class to the allocation engine (intake 100% decoded, every class placed)",
               "Allowances from project settings spread top-down: 0 unexplained cents, 0 duplicated money, full dispositions",
               "Weighted averages and sliders match their equations, with benchmarks showing cohort and spread",
               "Build the back-test: every past project estimated held out, total error within the target",
               "Solomon's first estimate with a source for every number and unknowns unpriced",
               "Write done_check.py, reading the same rows as GET /done",
               "Cut the desk by its map's work order; its budget section works unchanged; brand tokens only",
               "Feed the desk's budget section the preflight's budget and add the analysis views",
               "Full verify command passes and fable/REPORT.md is written"],
    "stage1": ["Build takeoff from geometry: compatible quantities per class from the decoded polygons and paths, with tests",
               "Build spatial relationships: nearness and containment as evidence for placement, with tests",
               "Drawing intake hands every decoded, placed class to the allocation engine (intake 100% decoded, every class placed)",
               "Allowances from project settings spread top-down: 0 unexplained cents, 0 duplicated money, full dispositions",
               "Weighted averages and sliders match their equations, with benchmarks showing cohort and spread",
               "Build the back-test: every past project estimated held out, total error within the target",
               "Solomon's first estimate with a source for every number and unknowns unpriced",
               "Write done_check.py with --stage 1; on success it writes runs/done/stage1.json",
               "Full verify command passes and fable/REPORT.md is written"],
    "stage2": ["Cut the desk by its map's work order, one step at a time, with the desk's tests after each",
               "The desk's budget section works unchanged: bids, attaching subcontractors, the administration markup",
               "Feed the budget section the stage 1 budget in the standard's form through the Standards API",
               "Analysis views: plan by slot or class, allowance flow summing to the ledger, allocated dollars and quantities by item, intake match, cross-project comparison with slider weights",
               "Extend done_check.py with --stage 2",
               "Full verify command passes and fable/REPORT.md is written"],
}
DECISIONS_BEFORE = [
    "Allowances first: each category allowance from the project settings is spread top-down onto that category's drawn classes. Reason: this is how MARPA budgets (the allocation method).",
    "The allocation engine is read and run through its own commands; the run integrates with it and does not rebuild it. Reason: it already conserves every dollar on six projects.",
    "Every calculation is plain code with tests; Jev answers only bounded decisions under the written schemas. Reason: the owner's rule for deterministic calculations.",
    "A project's own budget is never used to estimate it. Reason: held-out validation.",
    "The desk's budget section is fed, not duplicated. Reason: bids, subcontractors and the administration markup are the firm's working tools and main income.",
    "The answers in fable/owner_decisions.json, once given, are the owner's decisions for this run.",
]


def section(text: str, title: str, body: str) -> str:
    start = text.index("## %s\n" % title)
    end = text.find("\n## ", start + 1)
    return text[:start] + "## %s\n\n%s\n" % (title, body.strip()) + (text[end:] if end != -1 else "")


def mission(shape: str, config: dict) -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace(text.splitlines()[0], "# Mission: MARPA, %s" % {"single": "drawing to priced budget in one run",
                                                                     "stage1": "the preflight (stage 1 of 2)", "stage2": "the slimmed desk app (stage 2 of 2)"}[shape], 1)
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
    out_of_scope = ["Restyling the desk beyond the cut and the new views", "New standard entries from old drawings beyond what the budget needs"]
    if config.get("shape") == "stage1":
        out_of_scope.insert(0, "Any change to the desk app (stage 2)")
    guard = ("Allowed without asking:\n\n" + "\n".join("- " + a for a in allowed) + "\n\nNot allowed:\n\n" + "\n".join("- " + f for f in forbidden) +
             "\n\nOut of scope, leave these alone even though nothing blocks them:\n\n" + "\n".join("- " + o for o in out_of_scope))
    text = section(text, "Guardrails", guard)
    done_start = text.index("## Done\n")
    done = text[done_start:]
    done = done.replace("`{{FILL: the verify command, character for character as in fable/handoff.json}}` exits 0.", "`%s` exits 0." % config["verify_command"])
    done = re.sub(r"- \{\{FILL: any further condition.*?\n", "- Every row of the definition of done for this shape meets its target (listed in the MARPA section).\n", done, flags=re.S)
    return text[:done_start] + done


def state(shape: str) -> str:
    return ("# Run ledger\n\n## Current focus\n\nNot started.\n\n## Next step\n\nRead fable/MISSION.md and the documents it names first, then confirm or extend the task list below.\n\n"
            "## Tasks\n\n" + "\n".join("- [ ] " + t for t in TASKS[shape]) + "\n\n## Notes for a resuming session\n\n"
            "Run the allocation engine with UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation uv run --no-sync; a plain uv run makes a new environment there.\n")


def decisions() -> str:
    return ("# Decisions\n\n## Made before the run\n\n" + "\n".join("- " + d for d in DECISIONS_BEFORE) +
            "\n\n## Defaults for anything not listed\n\n- Prefer the option that is easiest to undo.\n- Prefer the smallest change that satisfies the mission.\n"
            "- Follow the conventions already in the codebase over personal preference.\n\n## Open questions for the owner\n\nNone.\n\n"
            "## Made during the run\n\n## Left for the owner\n")


def render(preset: dict) -> dict[str, str]:
    out = {}
    for shape, spec in (preset.get("shapes") or {}).items():
        config = dict(preset["config"], **(spec.get("config") or {}), shape=shape)
        config.setdefault("branch", "fable/run-1")
        if shape == "single":
            config["branch"] = "fable/run-1"
        out["shapes/%s/MISSION.md" % shape] = mission(shape, config)
        out["shapes/%s/STATE.md" % shape] = state(shape)
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
