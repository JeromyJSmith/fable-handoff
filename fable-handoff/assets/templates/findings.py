#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""The findings ledger: what discovery found that the run must resolve.

Built by prepare.py phase 6 from:
- fable/INTENT.json: data lost or regressed, from the conversation logs;
- fable/cases.json: detective cases that are still open or only likely;
- fable/gaps.json: open gaps from gap analysis.

Each finding gets an id (F1, F2, ...), its kind, its text, and a status. A
finding the logs already show as resolved keeps that evidence. Every open
finding is a task in fable/STATE.md whose check is `findings.py check <id>`,
which passes only when the finding is resolved with written evidence.

    uv run --script fable/findings.py build              # write fable/findings.json (keeps earlier resolutions)
    uv run --script fable/findings.py list
    uv run --script fable/findings.py check F3           # exit 0 only when F3 is resolved with evidence
    uv run --script fable/findings.py resolve F3 --evidence "..."
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path


def project_root() -> Path:
    here = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "fable").is_dir():
            return candidate
    return here


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def collect(project: Path) -> list[dict]:
    fable = project / "fable"
    out = []
    intent = read_json(fable / "INTENT.json", {})
    for f in intent.get("lost_or_regressed") or []:
        resolved = f.get("status") == "resolved"
        out.append({"kind": "data lost or regressed", "key": "intent:" + "|".join(sorted(f.get("items") or [])),
                    "text": "Data lost or regressed: %s. First reported: %s" % (", ".join(f.get("items") or []), (f.get("first") or "")[:300]),
                    "status": "resolved" if resolved else "open", "evidence": f.get("status_from") if resolved else None})
    for c in read_json(fable / "cases.json", []):
        verdict = (c.get("result") or {}).get("verdict", "")
        if verdict.startswith("open") or verdict == "likely":
            out.append({"kind": "detective case", "key": "case:%s" % (c.get("id") or c.get("subject")),
                        "text": "Detective case %s: %s (%s)" % (c.get("id") or "", c.get("question") or c.get("subject") or "", verdict),
                        "status": "open", "evidence": None})
    for g in (read_json(fable / "gaps.json", {}) or {}).get("gaps", []):
        if g.get("status", "open") == "open":
            out.append({"kind": "gap", "key": "gap:%s" % g.get("id"), "text": "Gap %s (%s): %s" % (g.get("id"), g.get("kind", ""), " | ".join(x for x in g.get("between") or [] if x)),
                        "status": "open", "evidence": None})
    return out


def load(project: Path) -> list[dict]:
    return read_json(project / "fable" / "findings.json", [])


def save(project: Path, findings: list[dict]) -> None:
    (project / "fable" / "findings.json").write_text(json.dumps(findings, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def build(project: Path) -> list[dict]:
    """Merge newly found items into the ledger; earlier ids and resolutions are kept."""
    current = load(project)
    by_key = {f["key"]: f for f in current}
    n = max([int(f["id"][1:]) for f in current if str(f.get("id", "")).startswith("F")] or [0])
    for item in collect(project):
        if item["key"] in by_key:
            continue
        n += 1
        item["id"] = "F%d" % n
        current.append(item)
        by_key[item["key"]] = item
    save(project, current)
    return current


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["build", "list", "check", "resolve"])
    ap.add_argument("id", nargs="?")
    ap.add_argument("--evidence")
    ap.add_argument("--project")
    args = ap.parse_args()
    project = Path(args.project).resolve() if args.project else project_root()
    if args.command == "build":
        findings = build(project)
        print("%d finding(s), %d open" % (len(findings), sum(1 for f in findings if f["status"] == "open")))
        return 0
    findings = load(project)
    if args.command == "list":
        for f in findings:
            print("%s [%s] %s" % (f["id"], f["status"], f["text"]))
        return 0
    f = next((x for x in findings if x.get("id") == args.id), None)
    if f is None:
        print("no finding %s in fable/findings.json" % args.id, file=sys.stderr)
        return 2
    if args.command == "check":
        ok = f["status"] == "resolved" and str(f.get("evidence") or "").strip()
        print("%s is %s" % (f["id"], "resolved: " + f["evidence"] if ok else "still open"))
        return 0 if ok else 1
    if not str(args.evidence or "").strip():
        print("resolve needs --evidence: what shows it is resolved (a file, a query, a commit)", file=sys.stderr)
        return 2
    f.update(status="resolved", evidence=args.evidence.strip(), resolved=datetime.datetime.now().isoformat(timespec="seconds"))
    save(project, findings)
    print("%s resolved" % f["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
