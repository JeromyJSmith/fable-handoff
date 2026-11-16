#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Look back over everything gathered for a handoff and propose improvements.

    python3 scripts/system_review.py --project .
    python3 scripts/system_review.py --project . --json
    python3 scripts/system_review.py --project . --strict    # exit 1 if anything should change before launch

Run it once the readiness check says READY, before you launch. Everything
the earlier phases produced is on disk by then: the preflight report, the
structured spec, the readiness record, the conversation context and any
lessons from an earlier run. This script reads all of it and sorts what it
finds by who should act:

  before launch   cheap to fix now, expensive to discover at hour three
  the project     its instructions, tests and documents, so the next
                  person or run starts from a better place
  the skill       patterns that suggest the fable-handoff skill itself
                  should check or do more

It writes fable/IMPROVEMENTS.md and prints it. Every item says where it came
from. Nothing is changed: each proposal is for you and the owner to accept,
adapt or drop. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def review(project: Path) -> dict:
    fable = project / "fable"
    before, proj, skill = [], [], []

    def add(bucket, text, source):
        bucket.append({"text": text, "source": source})

    preflight = load(fable / "preflight.json") or {}
    for row in preflight.get("inputs", []):
        if row.get("status") in ("THIN", "MISSING"):
            add(proj, f"The {row['input']} input is {row['status']}: {(row.get('fix') or row.get('detail') or '').rstrip('.')}. "
                      "Writing it down once helps every later run and every new person.", "fable/preflight.json")
    for gap in preflight.get("gaps", []):
        if gap.get("severity") == "BLOCKING":
            add(before, f"Preflight reported a blocking gap that may still be open: {gap['text']}", "fable/preflight.json")

    spec = load(fable / "handoff_spec.json")
    if isinstance(spec, dict):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import spec_tool  # noqa: E402

        warns: dict[str, list[str]] = {}
        for p in spec_tool.problems(spec):
            if p["severity"] == "WARN":
                warns.setdefault(p["message"], []).append(p["path"])
        for message, paths in warns.items():
            where = ", ".join(paths[:6]) + (f" and {len(paths) - 6} more" if len(paths) > 6 else "")
            add(before, f"Spec warning ({where}): {message}.", "fable/handoff_spec.json")
        tasks = spec.get("tasks", [])
        unrouted = [t["text"] for t in tasks if not t.get("route")]
        if tasks and len(unrouted) == len(tasks):
            add(before, "No task carries a route, so the lead will decide every delegation itself. Route the mechanical "
                        "tasks to fable-worker and the specified larger ones to fable-builder, so Fable's own context goes "
                        "to the hard parts.", "fable/handoff_spec.json")
        heavy = [t["text"] for t in tasks if t.get("route") == "fable-specialist"]
        if tasks and len(heavy) > max(2, len(tasks) // 2):
            add(before, f"{len(heavy)} of {len(tasks)} tasks are routed to fable-specialist. If most of the work needs the "
                        "strongest model, check whether some of it can be split into specified pieces.", "fable/handoff_spec.json")
        traps = [t for t in spec.get("traps", []) if not t.get("instead")]
        if traps:
            add(proj, f"{len(traps)} trap(s) say what went wrong but not what to do instead. Record the fix in the "
                      "project's own lessons document too, not only in the handoff.", "fable/handoff_spec.json")

    readiness = load(fable / ".run" / "readiness.json") or {}
    for row in readiness.get("rows", []):
        status, check, detail = (row if isinstance(row, list) else [row.get("status"), row.get("check"), row.get("detail")])[:3]
        if status == "WARN":
            add(before, f"Readiness warning ({check}): {detail}", "fable/.run/readiness.json")

    config = load(fable / "handoff.json") or {}
    for accepted in config.get("audit_accept", []) or []:
        add(proj, f"The instruction finding '{accepted}' was accepted rather than fixed. Revisit it when the owner next "
                  "edits that file.", "fable/handoff.json")

    context = load(fable / "context.json") or {}
    recurring = [i for i in context.get("issues", []) if i.get("count", 1) >= 3]
    for issue in recurring[:8]:
        rerun = f" (rerun: {issue['command']})" if issue.get("command") else ""
        add(proj, f"A failure recurred {issue['count']} times in earlier sessions: {issue['text']}{rerun}. A test, a script "
                  "or a note in the project's instructions would stop the next run from rediscovering it.", "fable/context.json")
    failed_research = [r for r in context.get("research_topics", []) if r.get("failed")]
    for r in failed_research[:5]:
        add(proj, f"Research on '{r['topic']}' failed {r['failed']} time(s). If the answer matters to the job, save it "
                  "in the project's documents so the run does not depend on reaching that source.", "fable/context.json")
    if context.get("forks"):
        add(before, f"The conversations branched {len(context['forks'])} time(s). Each fork is a change of mind; check "
                    "that the branch that won is the one recorded in the decisions.", "fable/context.json")

    lessons = (load(fable / ".run" / "lessons.json") or {}).get("proposals", [])
    blocked_rules = [p for p in lessons if p.get("kind") == "question" and "guard blocked" in p.get("text", "")]
    for p in blocked_rules:
        add(skill, "A guard rule blocked many calls in an earlier run. If the calls were legitimate, the default pattern "
                   "in init_handoff.py may be too broad: " + p["text"], "fable/.run/lessons.json")
    unproven = [p for p in lessons if "no commit or changed file matches" in p.get("text", "")]
    if unproven:
        add(skill, f"{len(unproven)} task(s) were checked off in an earlier run with no evidence. Giving every task a "
                   "check command makes the stop gate verify them during the run.", "fable/.run/lessons.json")

    gaps_by_hand = [g for g in preflight.get("gaps", []) if g.get("severity") == "REVIEW"]
    if len(gaps_by_hand) >= 3:
        add(skill, f"Preflight left {len(gaps_by_hand)} items to human review. If the same kinds come up in every "
                   "project, they are candidates for a new automatic check.", "fable/preflight.json")

    return {"before_launch": before, "project": proj, "skill": skill}


def to_markdown(result: dict) -> str:
    out = ["# Improvements found while preparing this handoff", "",
           "Proposals only. Each one names where it came from. Accept, adapt or drop each with the owner.", ""]
    titles = [("before_launch", "Before launch", "Cheaper to fix now than to discover in the middle of the run."),
              ("project", "For the project", "So the next run and the next person start from a better place."),
              ("skill", "For the fable-handoff skill", "Patterns that suggest the skill itself should check or do more.")]
    for key, title, why in titles:
        out += [f"## {title}", "", why, ""]
        items = result[key]
        out += [f"- {i['text']} ({i['source']})" for i in items] or ["Nothing found."]
        out.append("")
    out += ["## Look for what the files cannot show", "",
            "Read the mission, the brief and this list together and ask what a reader would still be missing. "
            "If a knowledge-graph tool such as InfraNodus is connected, run a content-gap analysis on the mission "
            "and the brief: gaps between clusters of ideas often mark a decision nobody made.", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit 1 when anything is proposed before launch")
    args = ap.parse_args()
    project = Path(args.project).expanduser().resolve()
    if not (project / "fable").is_dir():
        print(f"{project} has no fable/ folder. Run preflight.py or init_handoff.py first.", file=sys.stderr)
        return 2
    result = review(project)
    text = to_markdown(result)
    if not args.no_write:
        (project / "fable" / "IMPROVEMENTS.md").write_text(text, encoding="utf-8")
    print(json.dumps(result, indent=2) if args.json else text)
    return 1 if (args.strict and result["before_launch"]) else 0


if __name__ == "__main__":
    sys.exit(main())
