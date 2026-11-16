#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Validate and inspect fable/handoff_spec.json, the structured handoff spec.

    uv run --script scripts/spec_tool.py check   --project .          # schema + readiness problems
    uv run --script scripts/spec_tool.py check   --project . --json   # same, as JSON
    uv run --script scripts/spec_tool.py schema                       # print the JSON Schema path
    uv run --script scripts/spec_tool.py new     --project .          # write an empty spec to fill in
    uv run --script scripts/spec_tool.py brief   --project .          # one page for the owner to approve
    uv run --script scripts/spec_tool.py signoff --project . --by "Jane Owner"   # after the owner says yes

The spec is the single source for the mission, ledger, decisions and run
settings. preflight.py drafts it, you and the owner complete it, this script
checks it, and render_handoff.py turns it into the package files.

`check` reports two kinds of finding:

  schema    the file does not match assets/schema/handoff_spec.schema.json
            (wrong type, missing key, unknown key, bad enum value)
  problem   the file is well formed but not ready for an unattended run
            (FAIL) or worth a look (WARN), such as an open question, an
            acceptance criterion with no test, or a forbidden action that no
            hook enforces

The same problem rules exist as jq in assets/jq/handoff.jq, so you can query
a spec with jq and get the same answer:

    jq -L SKILL/assets/jq 'include "handoff"; problems' fable/handoff_spec.json

Exit codes: 0 no schema errors and no FAIL problems, 1 otherwise, 2 bad usage.
Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL / "assets" / "schema" / "handoff_spec.schema.json"
DEFAULT_SPEC = Path("fable") / "handoff_spec.json"
PROTECTED_BRANCHES = {"main", "master", "production", "prod", "release"}
# Wording that assumes a person will answer during the run. Kept simple so the
# jq module can use the identical regular expression.
HUMAN_WORDS = r"ask me|wait for (my|the owner'?s?|the user'?s?) (approval|answer|reply|confirmation)|check with me|let me know|i will review|i'll review"

TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


# --------------------------------------------------------------------------- schema

def type_ok(value, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, TYPES[name])


def validate(value, schema: dict, path: str = "$") -> list[dict]:
    """A small JSON Schema validator for the keywords the spec schema uses."""
    errors: list[dict] = []
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(type_ok(value, n) for n in names):
            return [{"path": path, "message": f"expected {' or '.join(names)}, got {type(value).__name__}"}]
    if "enum" in schema and value not in schema["enum"]:
        errors.append({"path": path, "message": f"must be one of {schema['enum']}, got {value!r}"})
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append({"path": path, "message": "must not be empty"})
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append({"path": path, "message": f"must match {schema['pattern']}"})
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "minimum" in schema and value < schema["minimum"]:
        errors.append({"path": path, "message": f"must be at least {schema['minimum']}"})
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append({"path": f"{path}.{key}", "message": "is required"})
        for key, item in value.items():
            if key in props:
                errors += validate(item, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append({"path": f"{path}.{key}", "message": "is not a known key"})
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append({"path": path, "message": f"needs at least {schema['minItems']} item(s)"})
        if "items" in schema:
            for i, item in enumerate(value):
                errors += validate(item, schema["items"], f"{path}[{i}]")
    return errors


# --------------------------------------------------------------------------- problems

def words(text) -> int:
    return len(str(text or "").split())


def problems(spec: dict) -> list[dict]:
    """Readiness rules for a well-formed spec. Mirrored by `problems` in assets/jq/handoff.jq."""
    out: list[dict] = []

    def add(severity, path, message):
        out.append({"severity": severity, "path": path, "message": message})

    goal = spec.get("goal", {})
    if words(goal.get("job")) < 40:
        add("FAIL", "goal.job", f"is {words(goal.get('job'))} words; state the whole outcome in at least 40")
    if words(goal.get("why")) < 20:
        add("FAIL", "goal.why", f"is {words(goal.get('why'))} words; say who it is for and what wins in a tradeoff, in at least 20")
    for key in ("job", "why"):
        if re.search(HUMAN_WORDS, str(goal.get(key) or ""), flags=re.IGNORECASE):
            add("FAIL", f"goal.{key}", "assumes a person will answer during the run")
    if not str(spec.get("commands", {}).get("verify") or "").strip():
        add("FAIL", "commands.verify", "is empty; the run needs one command that passes only when the job is done")
    for i, q in enumerate(spec.get("open_questions", [])):
        add("FAIL", f"open_questions[{i}]", "is still open: " + str(q.get("question")))
    for i, c in enumerate(spec.get("acceptance_criteria", [])):
        if c.get("status") == "open" and not str(c.get("verified_by") or "").strip():
            add("FAIL", f"acceptance_criteria[{i}]", f"'{c.get('id')}' is open but no test or eval checks it")
    if not spec.get("tasks"):
        add("FAIL", "tasks", "is empty; seed the ledger with the first checkable results")
    criteria_ids = {c.get("id") for c in spec.get("acceptance_criteria", [])}
    for i, t in enumerate(spec.get("tasks", [])):
        for cid in t.get("criteria", []) or []:
            if cid not in criteria_ids:
                add("FAIL", f"tasks[{i}]", f"refers to unknown criterion '{cid}'")
    verified = {c.get("id") for c in spec.get("acceptance_criteria", []) if str(c.get("verified_by") or "").strip()}
    for i, t in enumerate(spec.get("tasks", [])):
        if not str(t.get("check") or "").strip() and not (set(t.get("criteria") or []) & verified):
            add("WARN", f"tasks[{i}]", "names no check and no verified criterion, so only the checkbox says it is done")
    guard = spec.get("guardrails", {})
    if not guard.get("pre_approved"):
        add("FAIL", "guardrails.pre_approved", "is empty; name the routine actions the run may take without asking")
    for i, f in enumerate(guard.get("forbidden", [])):
        enf = f.get("enforced_by", {}) or {}
        if not (enf.get("protected_paths") or enf.get("blocked_bash_patterns")):
            add("FAIL", f"guardrails.forbidden[{i}]", "no protected path or blocked command enforces it")
    if not guard.get("out_of_scope"):
        add("WARN", "guardrails.out_of_scope", "is empty; name adjacent work to leave alone")
    branch = str(spec.get("run", {}).get("branch") or "")
    if branch in PROTECTED_BRANCHES:
        add("FAIL", "run.branch", f"'{branch}' is a protected branch; use a run branch such as fable/my-job")
    if spec.get("run", {}).get("max_budget_usd") is None:
        add("WARN", "run.max_budget_usd", "is not set, so nothing caps the spend")
    for i, t in enumerate(spec.get("traps", [])):
        if not str(t.get("instead") or "").strip():
            add("WARN", f"traps[{i}]", "says what went wrong but not what to do instead")
    if not spec.get("traps") and not spec.get("practices_to_keep"):
        add("WARN", "traps", "no history recorded; ask the owner what failed and what worked")
    if not spec.get("decisions"):
        add("WARN", "decisions", "none recorded; every question the run might ask should be answered here")
    return sorted(out, key=lambda p: (p["path"], p["message"]))


# --------------------------------------------------------------------------- owner sign-off

def spec_hash(spec: dict) -> str:
    """SHA-256 of the spec without its sign-off, in a canonical form, so formatting does not matter."""
    body = {k: v for k, v in spec.items() if k != "owner_signoff"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def signoff_status(spec: dict) -> tuple[str, str]:
    """('ok' | 'missing' | 'stale', message)."""
    so = spec.get("owner_signoff")
    if not so:
        return "missing", "the owner has not signed off. Run spec_tool.py brief, have the owner read it, then spec_tool.py signoff --by NAME"
    if so.get("spec_sha256") != spec_hash(spec):
        return "stale", f"the spec changed after {so.get('by')} signed off on {so.get('at')}. Show the owner the new brief and sign off again"
    return "ok", f"signed off by {so.get('by')} on {so.get('at')}"


def brief(spec: dict) -> str:
    """One page the owner can read and approve: what will happen without them."""
    g, gr, run = spec["goal"], spec["guardrails"], spec["run"]
    lines = [f"# Owner brief: {spec['project']['name']}", "",
             "Read this before the run starts. Nobody will be able to ask you anything once it does. "
             "If any line is wrong, say so now; if everything is right, say yes and the sign-off is recorded.", "",
             "## The job", "", g["job"].strip(), "", "## Why, and what wins in a tradeoff", "", g["why"].strip(), "",
             "## How done is decided", "", f"The run ends when every task is checked off, `{spec['commands']['verify']}` exits 0, and a report is written.", ""]
    open_c = [c for c in spec["acceptance_criteria"] if c["status"] == "open"]
    if open_c:
        lines += ["Still to deliver:", ""] + [f"- {c['text']} (checked by {c.get('verified_by') or 'nothing yet'})" for c in open_c] + [""]
    lines += ["## It may do this without asking", ""] + [f"- {a}" for a in gr["pre_approved"]] + [""]
    lines += ["## It is blocked from doing this", ""] + [f"- {f['action']}. {f['reason']}" for f in gr["forbidden"]] + [""]
    lines += ["## It will leave this alone", ""] + ([f"- {o['text']}" for o in gr["out_of_scope"]] or ["- Nothing listed."]) + [""]
    lines += ["## Decided in advance on your behalf", ""] + ([f"- {d['decision']}. Reason: {d['reason']}" for d in spec["decisions"]] or ["- Nothing."]) + [""]
    lines += ["## When something is not covered", "",
              "It picks the option that is easiest to undo and closest to the Why, records the choice, and keeps going. "
              "Anything that cannot be undone and is not listed above is skipped and left for you.", "",
              "## Limits", "",
              f"- Model {run.get('model', 'fable')} at {run.get('effort', 'high')} effort, permission mode {run.get('permission_mode', 'auto')}.",
              f"- Spending cap: {('$%.2f' % run['max_budget_usd']) if run.get('max_budget_usd') is not None else 'none set'}. Relaunches: up to {run.get('max_relaunches', 3)}.",
              f"- Branch: {run['branch']}. Nothing is merged, pushed or deployed for you.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- commands

def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"{path} does not exist. Run preflight.py, or spec_tool.py new, to create it."
    except json.JSONDecodeError as exc:
        return None, f"{path} is not valid JSON: {exc}"


def check(spec_path: Path) -> dict:
    spec, err = load_json(spec_path)
    if err:
        return {"ok": False, "file": str(spec_path), "load_error": err, "schema_errors": [], "problems": []}
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_errors = validate(spec, schema)
    # Problems are listed even when the schema fails, so one pass shows everything.
    found = problems(spec) if isinstance(spec, dict) else []
    ok = not schema_errors and not any(p["severity"] == "FAIL" for p in found)
    return {"ok": ok, "file": str(spec_path), "schema_errors": schema_errors, "problems": found}


def empty_spec() -> dict:
    return {
        "schema_version": 1,
        "project": {"name": "", "repository": None},
        "goal": {"job": "", "why": "", "sources": []},
        "current_state": {"summary": "", "works": [], "half_done": [], "broken": [], "baseline": None},
        "where_things_are": [],
        "commands": {"verify": "", "fast_check": None, "build": None, "run": None},
        "acceptance_criteria": [],
        "tasks": [],
        "guardrails": {"pre_approved": [], "forbidden": [], "out_of_scope": []},
        "decisions": [],
        "defaults": [],
        "open_questions": [],
        "traps": [],
        "practices_to_keep": [],
        "done_extra": [],
        "run": {"branch": "fable/run-1", "model": "claude-fable-5-2", "effort": "high", "permission_mode": "auto", "max_budget_usd": None, "max_relaunches": 3},
        "sources": [],
    }


def report_text(result: dict) -> str:
    if result.get("load_error"):
        return "NOT VALID: " + result["load_error"]
    lines = []
    for e in result["schema_errors"]:
        lines.append(f"SCHEMA {e['path']}: {e['message']}")
    for p in result["problems"]:
        lines.append(f"{p['severity']:<6} {p['path']}: {p['message']}")
    fails = sum(1 for p in result["problems"] if p["severity"] == "FAIL")
    warns = sum(1 for p in result["problems"] if p["severity"] == "WARN")
    head = "READY TO RENDER" if result["ok"] else "NOT READY"
    lines.append(f"\n{head}: {len(result['schema_errors'])} schema error(s), {fails} fail, {warns} warn.")
    if not result["ok"]:
        lines.append("Fix the spec, then run this again. Query it with jq: include \"handoff\"; problems")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate the spec and list readiness problems")
    c.add_argument("--project", default=".")
    c.add_argument("--spec", help="spec path (default fable/handoff_spec.json in the project)")
    c.add_argument("--json", action="store_true")
    n = sub.add_parser("new", help="write an empty spec to fill in")
    n.add_argument("--project", default=".")
    n.add_argument("--force", action="store_true")
    b = sub.add_parser("brief", help="write fable/OWNER_BRIEF.md for the owner to approve")
    b.add_argument("--project", default=".")
    so = sub.add_parser("signoff", help="record that the owner approved the current spec")
    so.add_argument("--project", default=".")
    so.add_argument("--by", required=True, help="the owner's name, as they gave it")
    so.add_argument("--note", default=None)
    st = sub.add_parser("status", help="show whether the sign-off matches the current spec")
    st.add_argument("--project", default=".")
    sub.add_parser("schema", help="print the path of the JSON Schema")
    args = ap.parse_args()

    if args.cmd == "schema":
        print(SCHEMA_PATH)
        return 0
    project = Path(args.project).resolve()
    if args.cmd == "new":
        path = project / DEFAULT_SPEC
        if path.exists() and not args.force:
            print(f"{path} already exists. Pass --force to replace it.", file=sys.stderr)
            return 2
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(empty_spec(), indent=2) + "\n", encoding="utf-8")
        print(path)
        return 0
    if args.cmd in ("brief", "signoff", "status"):
        path = project / DEFAULT_SPEC
        result = check(path)
        if result.get("load_error"):
            print(result["load_error"], file=sys.stderr)
            return 1
        spec = json.loads(path.read_text(encoding="utf-8"))
        if args.cmd == "status":
            state, message = signoff_status(spec)
            print(f"{state.upper()}: {message}")
            return 0 if state == "ok" else 1
        if not result["ok"]:
            print("The spec is not ready, so there is nothing to approve yet:\n\n" + report_text(result), file=sys.stderr)
            return 1
        if args.cmd == "brief":
            out = project / "fable" / "OWNER_BRIEF.md"
            out.write_text(brief(spec) + "\n", encoding="utf-8")
            print(out)
            return 0
        spec["owner_signoff"] = {"by": args.by, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "spec_sha256": spec_hash(spec), "note": args.note}
        path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        print(f"Recorded sign-off by {args.by}. Any later edit to the spec voids it.")
        return 0
    spec_path = Path(args.spec).resolve() if args.spec else project / DEFAULT_SPEC
    result = check(spec_path)
    print(json.dumps(result, indent=2) if args.json else report_text(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
