#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Write the handoff package from fable/handoff_spec.json.

    python3 scripts/render_handoff.py --project .            # write the files
    python3 scripts/render_handoff.py --project . --check    # report drift, write nothing
    python3 scripts/render_handoff.py --project . --stdout MISSION.md

Renders, from the spec:

  fable/MISSION.md      job, why, where things are, guardrails, decisions, done
  fable/STATE.md        the task ledger
  fable/DECISIONS.md    decisions, defaults, practices to keep
  fable/handoff.json    run settings and enforcement, merged into the
                        existing file (init_handoff.py must have run first)

It refuses to write while spec_tool.py check reports a schema error or a FAIL
problem, because a package rendered from an unfinished spec would pass for a
finished one. The spec stays the source: edit it and render again instead of
editing the rendered files, and --check shows when the two have drifted apart.

Exit codes: 0 written (or no drift with --check), 1 the spec is not ready or
the files have drifted, 2 bad usage or no package. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_tool  # noqa: E402

TEMPLATE_DEFAULTS = [
    "Prefer the option that is easiest to undo.",
    "Prefer the smallest change that satisfies the mission.",
    "Follow the conventions already in the codebase over personal preference.",
]
GENERATED = "<!-- Rendered from fable/handoff_spec.json by render_handoff.py. Edit the spec and render again. -->"


def bullets(items) -> list[str]:
    return [f"- {i}" for i in items]


def sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?", ":")) else text + "."


def render_mission(spec: dict) -> str:
    s, g, c = spec, spec["goal"], spec["commands"]
    out = [f"# Mission: {s['project']['name']}", "", GENERATED, "", "## Job", "", g["job"].strip(), "", "## Why", "", g["why"].strip(), "",
           "## Where things are", ""]
    state = s["current_state"]
    if state.get("summary", "").strip():
        out += [state["summary"].strip(), ""]
    for label, key in (("Works today", "works"), ("Half done", "half_done"), ("Known broken", "broken")):
        if state.get(key):
            out += [f"{label}:", ""] + bullets(state[key]) + [""]
    if s.get("where_things_are"):
        out += [f"- `{w['path']}`: {sentence(w['purpose'])}" for w in s["where_things_are"]] + [""]
    out.append(f"- Full check: `{c['verify']}`")
    if c.get("fast_check"):
        out.append(f"- Fast check for the inner loop: `{c['fast_check']}`")
    if c.get("build"):
        out.append(f"- Build: `{c['build']}`")
    if c.get("run"):
        out.append(f"- Run: `{c['run']}`")
    out.append("")
    open_criteria = [x for x in s["acceptance_criteria"] if x["status"] == "open"]
    done_criteria = [x for x in s["acceptance_criteria"] if x["status"] == "done"]
    if open_criteria or done_criteria:
        out += ["Acceptance criteria:", ""]
        out += [f"- [ ] {x['text']} (checked by {x['verified_by']})" for x in open_criteria]
        out += [f"- [x] {x['text']}" for x in done_criteria]
        out.append("")
    if s["traps"]:
        out += ["Traps from earlier work. Do not repeat these:", ""]
        out += [f"- {sentence(t['text'])}" + (f" Instead: {sentence(t['instead'])}" if t.get("instead") else "") for t in s["traps"]]
        out.append("")
    gr = s["guardrails"]
    out += ["## Guardrails", "", "Pre-approved, do these without asking:", ""] + bullets(sentence(a) for a in gr["pre_approved"]) + [""]
    out += ["Forbidden, enforced by a hook that will block the tool call:", ""]
    out += [f"- {sentence(f['action'])} Reason: {sentence(f['reason'])}" for f in gr["forbidden"]] or ["- Editing the handoff package itself (fable/MISSION.md, fable/handoff.json, .claude/)."]
    out += ["", "Out of scope, leave these alone even though nothing blocks them:", ""]
    out += [f"- {sentence(o['text'])} Reason: {sentence(o['reason'])}" for o in gr["out_of_scope"]] or ["- Work the Job does not ask for."]
    out += ["", "## Decisions", "",
            "Nobody can answer questions during this run. Decisions made in advance are in fable/DECISIONS.md. "
            "For anything not covered there, choose the option that is easiest to undo and closest to the Why above, "
            "record it in fable/DECISIONS.md with your reason, and keep going. If an action cannot be undone and is not "
            "pre-approved, skip it, record it under \"Left for the owner\", and continue with everything else.",
            "", "## Done", "", "The run is finished when all of these are true:", "",
            "- Every task in fable/STATE.md is checked off.",
            f"- `{c['verify']}` exits 0."]
    out += [f"- {sentence(d)}" for d in s.get("done_extra", [])]
    out += ["- fable/REPORT.md is written.", "",
            "A stop hook checks the tasks, the verify command and the report, and sends you back to work if they do not hold. "
            "Stop when they hold. Do not add features, refactors or documentation beyond what the Job asks for."]
    return "\n".join(out) + "\n"


def render_state(spec: dict) -> str:
    tasks = []
    for t in spec["tasks"]:
        line = f"- [ ] {t['text']}"
        if t.get("check"):
            line += f" (check: `{t['check']}`)"
        if t.get("route"):
            line += f" [route: {t['route']}]"
        tasks.append(line)
    tasks.append("- [ ] Full verify command passes and fable/REPORT.md is written")
    return "\n".join([
        "# Run ledger", "", GENERATED, "", "## Current focus", "", "Not started.", "", "## Next step", "",
        "Read fable/MISSION.md and fable/DECISIONS.md, then confirm or extend the task list below.", "",
        "## Tasks", "", *tasks, "", "## Notes for a resuming session", "", "None yet.", ""])


def render_decisions(spec: dict) -> str:
    made = [f"- {sentence(d['decision'])} Reason: {sentence(d['reason'])}" for d in spec["decisions"]]
    made += [f"- Keep doing: {sentence(p['text'])}" for p in spec["practices_to_keep"]]
    defaults = TEMPLATE_DEFAULTS + [sentence(d) for d in spec.get("defaults", []) if sentence(d) not in TEMPLATE_DEFAULTS]
    return "\n".join([
        "# Decisions", "", GENERATED, "", "## Made before the run", "", *(made or ["- None beyond the defaults below."]), "",
        "## Defaults for anything not listed", "", *bullets(defaults), "",
        "## Open questions for the owner", "", "None.", "",
        "## Made during the run", "", "<!-- The model appends here. One or two lines each: the choice, the alternatives, the reason. -->", "",
        "## Left for the owner", "", "<!-- The model appends here: skipped actions that cannot be undone, blocked items, follow-ups. -->", ""])


def merged_config(spec: dict, config: dict) -> dict:
    cfg = dict(config)
    run = spec["run"]
    cfg["verify_command"] = spec["commands"]["verify"]
    cfg["branch"] = run["branch"]
    for key in ("model", "effort", "permission_mode", "max_relaunches"):
        if key in run:
            cfg[key] = run[key]
    if "max_budget_usd" in run:
        cfg["max_budget_usd"] = run["max_budget_usd"]
    for key in ("protected_paths", "blocked_bash_patterns"):
        merged = list(cfg.get(key, []))
        for f in spec["guardrails"]["forbidden"]:
            for item in (f.get("enforced_by") or {}).get(key, []) or []:
                if item not in merged:
                    merged.append(item)
        cfg[key] = merged
    return cfg


def outputs(spec: dict, project: Path) -> dict[str, str]:
    config = json.loads((project / "fable" / "handoff.json").read_text(encoding="utf-8"))
    return {
        "fable/MISSION.md": render_mission(spec),
        "fable/STATE.md": render_state(spec),
        "fable/DECISIONS.md": render_decisions(spec),
        "fable/handoff.json": json.dumps(merged_config(spec, config), indent=2) + "\n",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--spec", help="spec path (default fable/handoff_spec.json)")
    ap.add_argument("--check", action="store_true", help="compare the rendered text with the files on disk and write nothing")
    ap.add_argument("--stdout", metavar="NAME", choices=["MISSION.md", "STATE.md", "DECISIONS.md", "handoff.json"],
                    help="print one rendered file and write nothing")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    spec_path = Path(args.spec).resolve() if args.spec else project / spec_tool.DEFAULT_SPEC
    if not (project / "fable" / "handoff.json").exists():
        print("fable/handoff.json is missing. Run init_handoff.py first; rendering fills in an existing package.", file=sys.stderr)
        return 2
    result = spec_tool.check(spec_path)
    if not result["ok"]:
        print("The spec is not ready to render:\n\n" + spec_tool.report_text(result), file=sys.stderr)
        return 1
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    rendered = outputs(spec, project)

    if args.stdout:
        print(rendered[f"fable/{args.stdout}"], end="")
        return 0
    if args.check:
        drift = [rel for rel, text in rendered.items()
                 if not (project / rel).exists() or (project / rel).read_text(encoding="utf-8") != text]
        if drift:
            print("These files differ from what the spec renders: " + ", ".join(drift) +
                  ". Either the spec changed (render again) or a file was edited by hand (move the edit into the spec).")
            return 1
        print("The package matches the spec.")
        return 0
    for rel, text in rendered.items():
        (project / rel).write_text(text, encoding="utf-8")
    warns = [p for p in result["problems"] if p["severity"] == "WARN"]
    print("Rendered " + ", ".join(rendered) + " from " + str(spec_path.relative_to(project) if spec_path.is_relative_to(project) else spec_path) + ".")
    for w in warns:
        print(f"WARN {w['path']}: {w['message']}")
    print("Next: commit, then run readiness_check.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
