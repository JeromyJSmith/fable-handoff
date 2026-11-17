#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write a condensed INTENT.md from every related conversation log.

    uv run --script scripts/intent.py --project <project> --project-logs
    uv run --script scripts/intent.py --project <project> --logs a.jsonl dir/ --out runs/<date>_<name>/INTENT.md

Reads Claude Code JSONL logs (sessions and subagents) and keeps, in the
people's own words:

- goals and rules: the owner's sentences that state what is wanted or how to
  work (want, goal, must, never, always, rule, should, do not, the purpose);
- decisions: sentences that record a decision or a ruling;
- open problems: sentences that say something is open, blocked or not done;
- data lost or regressed: every sentence, from the owner or an agent, that
  says a concrete item was lost, dropped, gone, missing, emptied or
  regressed. A concrete item is a quoted text, a number with a unit or a
  percent, or a code name in backticks. Each finding is grouped by its
  items, with its first report and a resolution status taken from the later
  sentences that name the same item: resolved (restored, back, repaired,
  fixed, found again) or still open (still missing, not found, neither found).

The default output is the skill package's runs/ folder (the owner's rule: run
output goes under runs/ in this package). It never writes inside the project.
Standard library only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
RUNS = SKILL.parent / "runs"

LOSS = re.compile(r"\b(?:are gone|is gone|was gone|gone missing|dropped|lost|disappeared|went missing|rebuilt [\w`]+ empty|"
                  r"emptied|regress(?:ed|ion)|data loss|wiped|overwritten|no longer (?:there|in|present))\b", re.I)
RESOLVED = re.compile(r"\b(?:restored|is back|are back|tables back|now back|repaired|recovered|fixed|found again|put back|reinstated)\b", re.I)
STILL = re.compile(r"\b(?:still missing|still gone|still lost|found neither|neither found|found nothing|not found|still absent|confirm they're still missing|or say that they are still missing)\b", re.I)
GOAL = re.compile(r"\b(?:i want|we want|the goal|goal is|the purpose|must|never|always|the rule|rule:|should|do not|don't|needs to|has to)\b", re.I)
DECISION = re.compile(r"\b(?:decided|decision|ruling|ruled|adopted|we will|the owner's word|chosen)\b", re.I)
OPEN = re.compile(r"\b(?:open question|still open|blocked|blocker|not done|not yet|to do|todo|unresolved|waiting on)\b", re.I)
ITEM = re.compile(r"\"([^\"\n]{2,60})\"|“([^”\n]{2,60})”|`([^`\n]{2,60})`|(\b\d[\d,]*(?:\.\d+)?\s?%)|(\b\d[\d,]*(?:\.\d+)?\s?(?:sf|lf|cy|ft|tons?|weeks?|days?|rows?)\b)", re.I)
NOISE = re.compile(r"^(?:<|\{|\[)|tool_use_error|system-reminder")


def claude_log_dir(project: Path) -> Path:
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(project))


def collect(paths):
    out, seen = [], set()
    for p in paths:
        files = [p] if p.is_file() else sorted(p.rglob("*.jsonl")) if p.is_dir() else []
        for f in files:
            if f.resolve() not in seen:
                seen.add(f.resolve())
                out.append(f.resolve())
    return out


def messages(files):
    """(timestamp, session, role, text) for every user and assistant text, in time order."""
    out = []
    for f in files:
        for line in f.open(encoding="utf-8", errors="replace"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("type") not in ("user", "assistant") or r.get("isMeta"):
                continue
            c = (r.get("message") or {}).get("content")
            texts = [c] if isinstance(c, str) else [x.get("text", "") for x in c or [] if isinstance(x, dict) and x.get("type") == "text"]
            for t in texts:
                if t and not t.lstrip().startswith(("<command", "<local-command", "<system-reminder", "<task-notification", "Caveat:")):
                    out.append((r.get("timestamp") or "", r.get("sessionId") or f.stem, r["type"], t))
    return sorted(out, key=lambda m: m[0])


def sentences(text):
    for line in text.splitlines():
        line = line.strip().lstrip("-*#> ").strip()
        if not line or NOISE.search(line):
            continue
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", line):
            s = s.strip()
            if 12 <= len(s) <= 600:
                yield s


def items(s):
    out = []
    for m in ITEM.finditer(s):
        v = next(g for g in m.groups() if g)
        v = re.sub(r"\s+", " ", v.strip())
        if v.lower() not in {"the", "and", "a"}:
            out.append(v)
    return out


def analyse(msgs):
    goals, decisions, opens, findings = [], [], [], {}
    for ts, session, role, text in msgs:
        for s in sentences(text):
            if role == "user" and GOAL.search(s) and len(goals) < 400:
                goals.append((ts, s))
            if DECISION.search(s) and len(decisions) < 400:
                decisions.append((ts, role, s))
            if OPEN.search(s) and len(opens) < 400:
                opens.append((ts, role, s))
            keys = items(s)
            if LOSS.search(s) and keys:
                key = tuple(sorted({k.lower() for k in keys}))
                f = findings.setdefault(key, {"items": sorted(set(keys)), "first": (ts, role, session, s), "reports": 0, "status": "not recorded as resolved", "status_from": None})
                f["reports"] += 1
    # resolution: the latest sentence naming any item of a finding with a resolution or still-open word
    for f in findings.values():
        names = [k.lower() for k in f["items"]]
        for ts, session, role, text in msgs:
            if ts < f["first"][0]:
                continue
            for s in sentences(text):
                low = s.lower()
                if not any(n in low for n in names):
                    continue
                if STILL.search(s):
                    f["status"], f["status_from"] = "still open", (ts, role, s)
                elif RESOLVED.search(s):
                    f["status"], f["status_from"] = "resolved", (ts, role, s)
    return goals, decisions, opens, list(findings.values())


def dedupe(rows, key=lambda r: r[-1].lower()[:120]):
    seen, out = set(), []
    for r in rows:
        k = key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def markdown(project, files, goals, decisions, opens, findings):
    lines = ["# Intent", "",
             "Condensed from %d conversation log(s) for %s on %s. The people's own words; the project's goals document is the authority, this is supporting context." % (
                 len(files), project.name, datetime.date.today().isoformat()), ""]
    lines += ["## Goals and rules, in the owner's words", ""] + ["- %s (%s)" % (s, ts[:10]) for ts, s in dedupe(goals)[-60:]] + [""]
    lines += ["## Decisions", ""] + ["- %s: %s (%s)" % (role, s, ts[:10]) for ts, role, s in dedupe(decisions)[-60:]] + [""]
    lines += ["## Open problems", ""] + ["- %s: %s (%s)" % (role, s, ts[:10]) for ts, role, s in dedupe(opens)[-40:]] + [""]
    lines += ["## Data lost or regressed", ""]
    if not findings:
        lines.append("None found in these logs.")
    for f in sorted(findings, key=lambda f: f["first"][0]):
        ts, role, session, s = f["first"]
        lines.append("- **%s**: %s" % (", ".join(f["items"]), f["status"]))
        lines.append("  - first reported %s by %s (session %s): %s" % (ts[:16], role, session[:8], s))
        if f["status_from"]:
            lines.append("  - status from %s (%s): %s" % (f["status_from"][0][:16], f["status_from"][1], f["status_from"][2]))
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", default=".")
    ap.add_argument("--project-logs", action="store_true")
    ap.add_argument("--logs", nargs="*", default=[])
    ap.add_argument("--out", help="default: runs/<date>_<project name>/INTENT.md in the skill package")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    project = Path(args.project).expanduser().resolve()
    sources = [Path(p).expanduser() for p in args.logs] + ([claude_log_dir(project)] if args.project_logs else [])
    files = collect(sources)
    if not files:
        print("No conversation logs found.", file=sys.stderr)
        return 1
    goals, decisions, opens, findings = analyse(messages(files))
    out = Path(args.out).expanduser() if args.out else RUNS / ("%s_%s" % (datetime.date.today().isoformat(), re.sub(r"[^A-Za-z0-9]+", "-", project.name))) / "INTENT.md"
    inside = str(out.resolve()).startswith(str(project) + os.sep)
    in_package = str(out.resolve()).startswith(str(project / "fable") + os.sep)
    if inside and not in_package and project != SKILL.parent:
        print("intent.py writes to the package (fable/) or outside the project (runs/ in the skill package), never into project files.", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        print("%s exists; run output is never overwritten. Choose another --out." % out, file=sys.stderr)
        return 2
    out.write_text(markdown(project, files, goals, decisions, opens, findings), encoding="utf-8")
    summary = {"out": str(out), "logs": len(files), "goals": len(goals), "decisions": len(decisions), "open": len(opens),
               "lost_or_regressed": [{"items": f["items"], "status": f["status"], "first": f["first"][3],
                                      "status_from": f["status_from"][2] if f["status_from"] else None} for f in findings]}
    # the same findings as data, for the ledger (prepare.py phase 6, findings.py)
    out.with_suffix(".json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1) if args.json else "Wrote %s: %d finding(s) of lost or regressed data." % (out, len(findings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
