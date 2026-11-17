#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Prepare a handoff package by running phases 0 to 7 in order, with receipts.

Every phase is code, not a description:
- needs: preconditions, checked on the real state (files, git, earlier receipts);
- run: the scripts it calls, each checked by valid() before it runs;
- leaves: the files it must leave, each with a check.

After every phase the driver re-reads the real state; it never trusts what a
step said about itself. It stops at the first failed check and names it. Each
phase writes fable/receipts/<n>-<name>.json: the commands with their exit codes
and times, a sha256 of each input, a sha256 of each output, the checks and the
result. The readiness check requires every receipt and refuses a stale one (an
input changed after the phase ran).

Phase 8, the launch, is never run here: that is the owner's.

    uv run --script scripts/prepare.py --project . --preset NAME --shape NAME --apply-settings
    uv run --script scripts/prepare.py --project . --from 4          # resume at a phase
    uv run --script scripts/prepare.py --project . --until 3         # stop after a phase

prepare.marimo.py runs the same phases as a notebook the owner can watch.
Standard library only.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"
TEMPLATES = SKILL / "assets" / "templates"
UV = ["uv", "run", "--quiet", "--script"]
DRAFT = "<!-- draft: prepare.py phase 6 completes this -->"
NAMES = ["decide", "discover", "interview", "done-check", "scaffold", "rules", "mission", "readiness"]
CHECK = re.compile(r"\(check:\s*`([^`]+)`\)")
DESTRUCTIVE = re.compile(r"(^|[\s;&|(])(rm|rmdir|mv|shred|truncate)\s|\bgit\s+(restore|clean|reset\s+--hard|checkout\s+--\s)|\bchflags\b")


# --------------------------------------------------------------------------- state and receipts

def sha(path: Path) -> str | None:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if path.is_dir():
        h = hashlib.sha256()
        for p in sorted(path.rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(path)).encode())
                h.update(p.read_bytes())
        return h.hexdigest()
    return None


def receipt_path(project: Path, n: int) -> Path:
    return project / "fable" / "receipts" / ("%d-%s.json" % (n, NAMES[n]))


def read_receipt(project: Path, n: int) -> dict | None:
    try:
        return json.loads(receipt_path(project, n).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def receipt_problems(project: Path, n: int) -> list[str]:
    """Why phase n's receipt does not stand: missing, not passed, or stale."""
    r = read_receipt(project, n)
    if r is None:
        return ["phase %d (%s) has no receipt: prepare.py did not run it" % (n, NAMES[n])]
    if r.get("result") not in ("passed", "awaiting owner sign-off"):
        return ["phase %d (%s) stopped: %s" % (n, NAMES[n], r.get("reason") or r.get("result"))]
    stale = [rel for rel, digest in (r.get("inputs") or {}).items() if sha(project / rel) != digest]
    if stale:
        return ["phase %d (%s) is stale: %s changed after it ran; run prepare.py again from phase %d" % (n, NAMES[n], ", ".join(stale), n)]
    return []


def load_config(project: Path) -> dict:
    try:
        return json.loads((project / "fable" / "handoff.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def preset_config(name: str | None, shape: str | None) -> dict:
    if not name:
        return {}
    preset = json.loads((SKILL / "assets" / "presets" / name / "preset.json").read_text(encoding="utf-8"))
    shape = shape or preset.get("default_shape")
    return dict(preset.get("config") or {}, **(((preset.get("shapes") or {}).get(shape) or {}).get("config") or {}))


# --------------------------------------------------------------------------- the validity check

def valid(state: dict, action: dict) -> str | None:
    """None when the action may run, else the rule it would break.

    action: {"argv": [...], "writes": [paths], "reads": [paths], "phase": n}
    state:  {"project": Path, "config": dict, "shape": str|None}
    """
    project, config = state["project"], state.get("config") or {}
    text = " ".join(str(a) for a in action.get("argv") or [])
    if DESTRUCTIVE.search(text):
        return "no overwrite or delete: the driver never removes, moves or restores files (%s)" % text[:120]
    unreadable = config.get("unreadable_paths") or ["runs", "runs/**"]
    for path in list(action.get("reads") or []) + [a for a in action.get("argv") or [] if isinstance(a, str) and not a.startswith("-")]:
        rel = os.path.relpath(os.path.abspath(os.path.join(project, path)), project) if not str(path).startswith("/") or str(path).startswith(str(project)) else None
        if rel and any(fnmatch.fnmatch(rel, pat) or rel == pat for pat in unreadable):
            return "run output is never a source: %s is in unreadable_paths" % rel
    held = config.get("held_out") or {}
    for path in action.get("reads") or []:
        if any(fnmatch.fnmatch(str(path), pat) for pat in held.get("answer_paths") or []):
            return "a held-out project's answer is never read while preparing its estimate: %s" % path
    for path in action.get("writes") or []:
        target = project / path
        if target.exists() and not str(path).startswith(("fable/", ".claude/", ".gitignore")):
            return "no overwrite: %s already exists and is not part of the handoff package" % path
        lock = config.get("writer_lock") or {}
        if lock and any(fnmatch.fnmatch(str(path), pat) for pat in lock.get("protects") or []):
            holder = (project / lock.get("file", ".writer.lock")).read_text(encoding="utf-8", errors="replace") if (project / lock.get("file", ".writer.lock")).exists() else ""
            me = os.environ.get(lock.get("agent_env", "AGENT_NAME"), "")
            if not me or me not in holder:
                return "writer lock: %s is written only while this agent (%s) holds %s" % (path, lock.get("agent_env", "AGENT_NAME"), lock.get("file", ".writer.lock"))
    shape = state.get("shape") or ""
    m = re.match(r"stage(\d+)$", shape)
    if action.get("phase") == 4 and m and int(m.group(1)) > 1:
        before = project / "fable" / "done" / ("stage%d.json" % (int(m.group(1)) - 1))
        if not before.exists():
            return "stage order: %s starts only after %s exists" % (shape, before.relative_to(project))
    return None


# --------------------------------------------------------------------------- running

@dataclass
class Ctx:
    project: Path
    preset: str | None = None
    shape: str | None = None
    shared_from: str | None = None
    logs: list = field(default_factory=list)
    no_logs: bool = False
    goal: str | None = None
    verify_command: str | None = None
    apply_settings: bool = False
    max_budget_usd: float | None = None
    spans: list = field(default_factory=list)

    def state(self) -> dict:
        return {"project": self.project, "config": load_config(self.project) or preset_config(self.preset, self.shape), "shape": self.shape or load_config(self.project).get("shape")}


class Stop(Exception):
    pass


def run(ctx: Ctx, phase: int, argv: list, writes=(), reads=(), ok_codes=(0,), timeout=3600) -> dict:
    rule = valid(ctx.state(), {"argv": argv, "writes": list(writes), "reads": list(reads), "phase": phase})
    if rule:
        raise Stop("refused by the validity check: " + rule)
    started = time.time()
    proc = subprocess.run(argv, cwd=ctx.project, capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=str(ctx.project)))
    ended = time.time()
    record = {"command": " ".join(str(a) for a in argv), "exit": proc.returncode, "seconds": round(ended - started, 2),
              "started": datetime.datetime.fromtimestamp(started).isoformat(timespec="seconds"),
              "stdout_tail": proc.stdout[-1500:], "stderr_tail": proc.stderr[-1500:]}
    ctx.spans.append({"phase": phase, "name": record["command"][:80], "start": started, "end": ended, "exit": proc.returncode})
    if proc.returncode not in ok_codes:
        raise Stop("%s exited %d: %s" % (record["command"][:160], proc.returncode, (proc.stderr or proc.stdout).strip()[-400:]), record)
    return record


def script(name: str) -> list:
    return [*UV, str(SCRIPTS / name)]


def check(checks: list, what: str, ok: bool, detail: str = "") -> None:
    checks.append({"what": what, "ok": bool(ok), "detail": detail})
    if not ok:
        raise Stop("check failed: %s%s" % (what, (": " + detail) if detail else ""))


def need(n: int, ctx: Ctx, checks: list) -> None:
    for earlier in range(n):
        problems = receipt_problems(ctx.project, earlier)
        check(checks, "phase %d (%s) passed and is current" % (earlier, NAMES[earlier]), not problems, "; ".join(problems))


def enforcement(action: str, config: dict) -> dict:
    """The protected paths and blocked command patterns of fable/handoff.json that enforce a forbidden action."""
    low = action.lower()
    paths = [p for p in config.get("protected_paths") or [] if p.split("/**")[0].split("*")[0].strip("/").lower() and p.split("/**")[0].split("*")[0].strip("/").lower() in low]
    words = {w for w in re.findall(r"[a-z]{3,}", low)} - {"the", "and", "not", "any", "its", "for", "with", "this", "that", "edit", "code", "file", "files"}
    blocked = [b for b in config.get("blocked_bash_patterns") or [] if any(w in b.lower() for w in words)]
    if not paths and re.search(r"(^|\s)/|outside the project|another repository|engine", low):
        paths = ["(outside the project: the guard refuses file writes outside it)"]
    out = {}
    if paths:
        out["protected_paths"] = paths
    if blocked:
        out["blocked_bash_patterns"] = blocked
    return out


def sections(text: str) -> dict:
    out, current = {}, None
    for line in text.splitlines():
        m = re.match(r"^## (.+)$", line)
        if m:
            current = m.group(1).strip()
            out[current] = []
        elif current:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def bullets(text: str) -> list[str]:
    return [re.sub(r"^\s*-\s+", "", l).strip() for l in text.splitlines() if re.match(r"^\s*-\s+\S", l)]


# --------------------------------------------------------------------------- the phases

def phase_0(ctx: Ctx, outputs: dict) -> dict:
    checks, commands = [], []
    check(checks, "the project is a git repository", (ctx.project / ".git").exists(), str(ctx.project))
    for tool in ("uv", "git", "jq"):
        check(checks, "%s is installed" % tool, subprocess.run(["which", tool], capture_output=True).returncode == 0)
    head = subprocess.run(["git", "-C", str(ctx.project), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    check(checks, "the repository has a commit to start from", bool(head))
    if ctx.preset:
        check(checks, "the preset %s exists" % ctx.preset, (SKILL / "assets/presets" / ctx.preset / "preset.json").exists())
    # A fresh worktree lacks the git-ignored data the project's tests read: link it before discovery runs them.
    shared = (load_config(ctx.project) or preset_config(ctx.preset, ctx.shape)).get("shared_data") or {}
    if shared:
        argv = [*script("link_shared_data.py"), "--project", "."] + (["--preset", ctx.preset] if ctx.preset and not load_config(ctx.project) else [])
        argv += ["--from", ctx.shared_from] if ctx.shared_from else []
        commands.append(run(ctx, 0, argv, ok_codes=(0, 1)))
        report = json.loads(commands[-1]["stdout_tail"] or "{}") if commands[-1]["stdout_tail"].strip().startswith("{") else {}
        missing = [p["path"] for p in report.get("paths", []) if p["state"].startswith("missing")]
        check(checks, "the shared data is present or linked", not missing and commands[-1]["exit"] == 0, ", ".join(missing[:8]) or commands[-1]["stderr_tail"][-300:])
    return {"checks": checks, "commands": commands, "inputs": [], "leaves": [], "data": {"head": head}}


def phase_1(ctx: Ctx, outputs: dict) -> dict:
    checks, commands = [], []
    need(1, ctx, checks)
    (ctx.project / "fable").mkdir(exist_ok=True)
    pre = [*script("preflight.py"), "--project", ".", "--run-tests"]
    pre += ["--project-logs"] if not ctx.no_logs else []
    pre += ["--conversations", *ctx.logs] if ctx.logs else []
    pre += ["--preset", ctx.preset] if ctx.preset else []
    pre += ["--goal", ctx.goal] if ctx.goal else []
    commands.append(run(ctx, 1, pre, writes=["fable/preflight.json", "fable/PREFLIGHT.md"]))
    if ctx.no_logs:
        (ctx.project / "fable/CONTEXT.md").write_text("# Conversation context\n\nNo conversation logs were read: prepare.py ran with --no-logs.\n", encoding="utf-8")
        (ctx.project / "fable/INTENT.json").write_text(json.dumps({"logs": 0, "lost_or_regressed": [], "note": "--no-logs"}) + "\n", encoding="utf-8")
        (ctx.project / "fable/INTENT.md").write_text("# Intent\n\nNo conversation logs were read: prepare.py ran with --no-logs.\n", encoding="utf-8")
    else:
        logs = ["--project-logs"] + (["--logs", *ctx.logs] if ctx.logs else [])
        commands.append(run(ctx, 1, [*script("conversation_context.py"), "--project", ".", *logs], writes=["fable/CONTEXT.md"]))
        out = ctx.project / "fable" / "INTENT.md"
        for stale in (out, out.with_suffix(".json")):
            if stale.exists():   # a re-run keeps the earlier intent beside it, never overwritten
                stale.rename(stale.with_name(stale.stem + ".%s%s" % (datetime.datetime.now().strftime("%Y%m%dT%H%M%S"), stale.suffix)))
        commands.append(run(ctx, 1, [*script("intent.py"), "--project", ".", *logs, "--out", "fable/INTENT.md", "--json"], writes=["fable/INTENT.md"]))
    commands.append(run(ctx, 1, [*script("gap_analysis.py"), "--project", "."], writes=["fable/gaps.json", "fable/GAPS.md"]))
    commands.append(run(ctx, 1, [*script("decision_interview.py"), "--project", ".", "--settle"], ok_codes=(0, 1)))
    detective = ctx.project / "fable" / "detective.py"
    det = [*UV, str(detective if detective.exists() else TEMPLATES / "detective.py"), "verdicts", "--project", "."]
    commands.append(run(ctx, 1, det, ok_codes=(0, 1)))
    leaves = ["fable/preflight.json", "fable/PREFLIGHT.md", "fable/CONTEXT.md", "fable/INTENT.md", "fable/INTENT.json", "fable/gaps.json", "fable/GAPS.md", "fable/cases.json"]
    for rel in leaves:
        check(checks, "%s exists" % rel, (ctx.project / rel).exists())
    intent = json.loads((ctx.project / "fable/INTENT.json").read_text(encoding="utf-8"))
    pre_json = json.loads((ctx.project / "fable/preflight.json").read_text(encoding="utf-8"))
    check(checks, "preflight measured the project (drafts, documents, git state)", all(k in pre_json for k in ("drafts", "documents", "git")), "keys: %s" % ", ".join(sorted(pre_json)[:8]))
    check(checks, "preflight ran the project's tests", bool(pre_json.get("test_runs")) or not pre_json.get("detected_test_commands"), "a test command was found but not run")
    inputs = [p for p in ("CLAUDE.md", "AGENTS.md") if (ctx.project / p).exists()]
    return {"checks": checks, "commands": commands, "inputs": inputs, "leaves": leaves,
            "data": {"lost_or_regressed": intent.get("lost_or_regressed") or [], "logs": intent.get("logs"),
                     "open_gaps": sum(1 for g in json.loads((ctx.project / "fable/gaps.json").read_text()).get("gaps", []) if g.get("status", "open") == "open")}}


def phase_2(ctx: Ctx, outputs: dict) -> dict:
    checks, commands = [], []
    need(2, ctx, checks)
    # The project's real question system (from the config, or the preset's), never preflight's drafted spec:
    # judgment questions must be written up to ask; evidence questions are detective work for the run.
    import importlib.util
    _spec = importlib.util.spec_from_file_location("fable_decision_interview", SCRIPTS / "decision_interview.py")
    di = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(di)
    qm = di.questions_module(ctx.project)
    config = load_config(ctx.project) or preset_config(ctx.preset, ctx.shape)
    system_records = [q for q in qm.system(ctx.project, config).load() if q.get("status", "open") == "open"]
    judgment = [q for q in system_records if q.get("kind") != "evidence"]
    evidence = [q for q in system_records if q.get("kind") == "evidence"]
    bad_system = [(q.get("topic") or q.get("question", "")[:60], di.problems(q, qm, qm.rung_names(config))) for q in judgment if di.problems(q, qm, qm.rung_names(config))]
    check(checks, "every open judgment question in the question system is written up well enough to ask (%d)" % len(judgment), not bad_system,
          "; ".join("%s: %s" % (t, ", ".join(p)) for t, p in bad_system[:3]))
    (ctx.project / "fable" / "questions_to_settle.json").write_text(json.dumps(evidence, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    commands.append({"command": "the question system's open questions: %d judgment, %d evidence (to settle from evidence, fable/questions_to_settle.json)" % (len(judgment), len(evidence)), "exit": 0})
    packet = None
    if ctx.preset:
        preset = json.loads((SKILL / "assets/presets" / ctx.preset / "preset.json").read_text(encoding="utf-8"))
        packet = preset.get("owner_decisions")
    inputs = []
    if packet or (ctx.project / "fable/owner_decisions.json").exists():
        target = ctx.project / "fable/owner_decisions.json"
        if not target.exists():
            target.write_text((SKILL / "assets/presets" / ctx.preset / packet).read_text(encoding="utf-8"), encoding="utf-8")
        # checked in-process against the ladder the run will use (the preset's), before init writes the config
        import importlib.util
        spec = importlib.util.spec_from_file_location("fable_decision_interview", SCRIPTS / "decision_interview.py")
        di = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(di)
        qm = di.questions_module(ctx.project)
        config = load_config(ctx.project) or preset_config(ctx.preset, ctx.shape)
        rungs = qm.rung_names(config)
        records = json.loads(target.read_text(encoding="utf-8")).get("open_questions", [])
        open_q = [q for q in records if q.get("status", "open") == "open"]
        bad = [(q.get("topic"), di.problems(q, qm, rungs)) for q in open_q if di.problems(q, qm, rungs)]
        check(checks, "every open owner decision is written up well enough to ask (%d open)" % len(open_q), not bad,
              "; ".join("%s: %s" % (t, ", ".join(p)) for t, p in bad[:3]))
        commands.append({"command": "decision_interview.problems on fable/owner_decisions.json with the preset's ladder", "exit": 0 if not bad else 1})
        # not an input: the owner's answers are expected to change this file; readiness checks them directly
    return {"checks": checks, "commands": commands, "inputs": inputs, "leaves": ["fable/questions_to_settle.json"], "data": {"judgment": len(judgment), "evidence": len(evidence)}}


def phase_3(ctx: Ctx, outputs: dict) -> dict:
    checks, commands = [], []
    need(3, ctx, checks)
    verify = ctx.verify_command or preset_config(ctx.preset, ctx.shape).get("verify_command") or load_config(ctx.project).get("verify_command")
    check(checks, "a verify command is named", bool(verify))
    record = run(ctx, 3, ["bash", "-c", verify], ok_codes=tuple(range(0, 256)))
    commands.append(record)
    cannot = re.search(r"No module named|command not found|: not found\b|No such file or directory|Failed to spawn|file or directory not found", record["stdout_tail"] + record["stderr_tail"])
    check(checks, "the verify command can run here", record["exit"] not in (126, 127) and not (record["exit"] and cannot), (cannot.group(0) if cannot else ""))
    check(checks, "the verify command fails now (the work is not done yet)", record["exit"] != 0, "it already passes")
    out = ctx.project / "fable" / "prepare" / "verify-now.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"command": verify, "exit": record["exit"], "at": record["started"]}, indent=1) + "\n", encoding="utf-8")
    return {"checks": checks, "commands": commands, "inputs": [], "leaves": ["fable/prepare/verify-now.json"], "data": {"verify": verify, "exit_now": record["exit"]}}


def phase_4(ctx: Ctx, outputs: dict) -> dict:
    checks, commands = [], []
    need(4, ctx, checks)
    argv = [*script("init_handoff.py"), "--project", ".", "--create-branch"]
    argv += ["--preset", ctx.preset] if ctx.preset else []
    argv += ["--shape", ctx.shape] if ctx.shape else []
    argv += ["--apply-settings"] if ctx.apply_settings else []
    argv += ["--verify-command", ctx.verify_command] if ctx.verify_command else []
    argv += ["--max-budget-usd", str(ctx.max_budget_usd)] if ctx.max_budget_usd else []
    commands.append(run(ctx, 4, argv))
    cfg = load_config(ctx.project)
    cfg["require_receipts"] = True
    (ctx.project / "fable/handoff.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    for rel in ("fable/handoff.json", "fable/MISSION.md", "fable/STATE.md", "fable/DECISIONS.md", "fable/detective.py", "fable/findings.py"):
        check(checks, "%s exists" % rel, (ctx.project / rel).exists())
    branch = subprocess.run(["git", "-C", str(ctx.project), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    check(checks, "on the run's branch %s" % cfg.get("branch"), branch == cfg.get("branch"), "on %s" % branch)
    reg = subprocess.run([*UV, str(ctx.project / "fable/detective.py"), "functions", "--project", "."], cwd=ctx.project, capture_output=True, text=True)
    problems = []
    try:
        problems = json.loads(reg.stdout).get("problems", [])
    except ValueError:
        problems = [reg.stderr.strip()[:300] or "detective.py functions gave no result"]
    check(checks, "the detective functions are the project's own (no template examples, every source found)", not problems,
          "; ".join(problems[:4]) + (" Write this project's own functions into detective_functions of fable/handoff.json (references/detective-standard.md, section 7), then run prepare.py --from 4." if problems else ""))
    return {"checks": checks, "commands": commands, "inputs": ["fable/preflight.json"], "leaves": ["fable/handoff.json", "fable/detective.py"],
            "data": {"branch": branch, "functions": len(cfg.get("detective_functions") or [])}}


def phase_5(ctx: Ctx, outputs: dict) -> dict:
    checks, commands = [], []
    need(5, ctx, checks)
    commands.append(run(ctx, 5, [*script("audit_rules.py"), "--project", ".", "--propose"], writes=["fable/RULES_PROPOSAL.md"]))
    check(checks, "fable/RULES_PROPOSAL.md exists", (ctx.project / "fable/RULES_PROPOSAL.md").exists())
    audit = subprocess.run([*script("audit_rules.py"), "--project", ".", "--json"], cwd=ctx.project, capture_output=True, text=True)
    data = json.loads(audit.stdout or "{}")
    blocking = [o for o in data.get("owner_rules", []) if o.get("effect") == "blocks"]
    check(checks, "no owner rule blocks an unattended run", not blocking, "; ".join("%s:%d %s" % (o["file"], o["line"], o["text"][:80]) for o in blocking))
    inputs = [p for p in ("CLAUDE.md", "AGENTS.md") if (ctx.project / p).exists()]
    return {"checks": checks, "commands": commands, "inputs": inputs, "leaves": ["fable/RULES_PROPOSAL.md"],
            "data": {"fix_findings": sum(1 for f in data.get("findings", []) if f.get("severity") == "FIX" and not f.get("accepted")), "owner_rules": len(data.get("owner_rules", []))}}


def phase_6(ctx: Ctx, outputs: dict) -> dict:
    checks, commands = [], []
    need(6, ctx, checks)
    fable = ctx.project / "fable"
    commands.append(run(ctx, 6, [*UV, str(fable / "findings.py"), "build", "--project", "."]))
    findings = json.loads((fable / "findings.json").read_text(encoding="utf-8"))
    open_findings = [f for f in findings if f["status"] == "open"]
    # the ledger: the draft's tasks, then one task per open finding, each with its check
    state = (fable / "STATE.md").read_text(encoding="utf-8").replace(DRAFT + "\n", "").replace(DRAFT, "")
    added = []
    for f in open_findings:
        if ("finding %s:" % f["id"]) not in state:
            added.append("- [ ] Resolve finding %s: %s (check: `uv run --script fable/findings.py check %s`)" % (f["id"], f["text"].replace("`", "'")[:240], f["id"]))
    if added:
        marker = "- [ ] Full verify command passes"
        if marker in state:
            state = state.replace(marker, "\n".join(added) + "\n" + marker, 1)
        else:
            state = state.replace("## Tasks\n", "## Tasks\n\n" + "\n".join(added) + "\n", 1)
    (fable / "STATE.md").write_text(state, encoding="utf-8")
    mission = (fable / "MISSION.md").read_text(encoding="utf-8").replace(DRAFT + "\n", "").replace(DRAFT, "")
    if "## Findings to resolve" not in mission and "\n## Done" in mission:
        block = ("## Findings to resolve\n\nDiscovery found %d finding(s) the run must resolve: data lost or regressed in the conversations, open detective cases and open gaps. "
                 "Each is a task in fable/STATE.md, checked by `uv run --script fable/findings.py check <id>`, which passes only when it is resolved with written evidence "
                 "(`findings.py resolve <id> --evidence \"...\"`). The full list is fable/findings.json.\n\n" % len(open_findings))
        mission = mission.replace("\n## Done", "\n" + block + "## Done", 1)
    (fable / "MISSION.md").write_text(mission, encoding="utf-8")
    decisions_file = fable / "DECISIONS.md"
    decisions_file.write_text(decisions_file.read_text(encoding="utf-8").replace(DRAFT + "\n", "").replace(DRAFT, ""), encoding="utf-8")
    tasks = [l for l in state.splitlines() if l.strip().startswith("- [ ]")]
    no_check = [t for t in tasks if not CHECK.search(t)]
    check(checks, "every task in the ledger has a check command", not no_check, "; ".join(t[6:90] for t in no_check[:5]))
    first = (load_config(ctx.project).get("launch_requires") or {}).get("functions_first_tasks") or []
    missing_first = [name for name in first if not any(name.lower() in t.lower() for t in tasks)]
    check(checks, "every function the run must build first is a task in the ledger", not missing_first, ", ".join(missing_first))
    uncovered = [f["id"] for f in open_findings if ("finding %s:" % f["id"]) not in state]
    check(checks, "every open finding is a task in the ledger", not uncovered, ", ".join(uncovered))
    for rel in ("fable/MISSION.md", "fable/STATE.md", "fable/DECISIONS.md"):
        text = (ctx.project / rel).read_text(encoding="utf-8")
        check(checks, "%s is complete (no draft or FILL marker)" % rel, DRAFT not in text and "{{FILL" not in text)
    # the structured spec, completed from the package and checked
    spec_path = fable / "handoff_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.exists() else {}
    cfg = load_config(ctx.project)
    sec = sections(mission)
    guard = sections(mission).get("Guardrails", "")
    parts = re.split(r"\n(?=[A-Z][^\n]*:\s*\n)", guard)
    pre, forb, scope = [], [], []
    for part in parts:
        head = part.strip().splitlines()[0].lower() if part.strip() else ""
        items = bullets(part)
        if head.startswith("allowed"):
            pre = items
        elif head.startswith("not allowed"):
            forb = [{"action": re.split(r",? because ", i)[0], "reason": (re.split(r",? because ", i) + ["the owner's rule"])[1],
                     "enforced_by": enforcement(re.split(r",? because ", i)[0], load_config(ctx.project))} for i in items]
        elif head.startswith("out of scope"):
            scope = [{"text": i, "reason": "the owner left it out of this run"} for i in items]
    decisions_text = sections((fable / "DECISIONS.md").read_text(encoding="utf-8")).get("Made before the run", "")
    drafted = spec.get("open_questions") or []
    if drafted:
        # preflight drafts every question it finds in documents and logs; most are not open decisions.
        # They are kept for review, never asked as they are; the owner's questions live in the question system.
        (fable / "drafted_questions.json").write_text(json.dumps(drafted, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    spec["open_questions"] = []
    # acceptance: the definition of done, each row verified by the done check (or the verify command);
    # preflight's drafted criteria are kept for review
    dod = cfg.get("definition_of_done") or {}
    verifier = (dod.get("check") or "").split(";")[0].strip() or cfg.get("verify_command") or ""
    drafted_criteria = spec.get("acceptance_criteria") or []
    if dod.get("rows"):
        if drafted_criteria:
            (fable / "drafted_criteria.json").write_text(json.dumps(drafted_criteria, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        spec["acceptance_criteria"] = [{"id": "d%d" % (i + 1), "text": row, "status": "open", "verified_by": verifier, "source": "definition_of_done"}
                                       for i, row in enumerate(dod["rows"])]
    else:
        for c in drafted_criteria:
            c.setdefault("verified_by", None)
            if c.get("status") == "open" and not c.get("verified_by"):
                c["verified_by"] = cfg.get("verify_command")
    spec.update({
        "goal": dict(spec.get("goal") or {}, job=sec.get("Job", ""), why=sec.get("Why", "")),
        "commands": dict(spec.get("commands") or {}, verify=cfg.get("verify_command") or ""),
        "guardrails": {"pre_approved": pre, "forbidden": forb, "out_of_scope": scope},
        "tasks": [{"text": CHECK.sub("", t[6:]).strip(), "check": (CHECK.search(t).group(1) if CHECK.search(t) else "")} for t in tasks],
        "decisions": [{"decision": d.split(" Reason: ")[0], "reason": (d.split(" Reason: ") + ["recorded before the run"])[1], "source": "fable/DECISIONS.md"} for d in bullets(decisions_text)],
    })
    spec.setdefault("run", {})["max_budget_usd"] = cfg.get("max_budget_usd")
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    result = subprocess.run([*script("spec_tool.py"), "check", "--project", ".", "--json"], cwd=ctx.project, capture_output=True, text=True)
    commands.append({"command": "spec_tool.py check --project . --json", "exit": result.returncode})
    data = json.loads(result.stdout or "{}")
    fails = ["%s %s" % (p["path"], p["message"]) for p in data.get("problems", []) if p["severity"] == "FAIL"] + ["%s %s" % (e["path"], e["message"]) for e in data.get("schema_errors", [])]
    check(checks, "the handoff spec is complete and valid", data.get("ok") is True, "; ".join(fails[:5]))
    return {"checks": checks, "commands": commands,
            "inputs": [p for p in ("fable/INTENT.json", "fable/cases.json", "fable/gaps.json") if (ctx.project / p).exists()],
            "leaves": ["fable/findings.json", "fable/STATE.md", "fable/MISSION.md", "fable/handoff_spec.json"],
            "data": {"findings": len(findings), "open_findings": len(open_findings), "tasks": len(tasks), "tasks_added": len(added), "drafted_questions_kept_for_review": len(drafted)}}


def phase_7(ctx: Ctx, outputs: dict) -> dict:
    checks, commands = [], []
    need(7, ctx, checks)
    record = run(ctx, 7, [*script("readiness_check.py"), "--project", ".", "--json"], ok_codes=(0, 1))
    commands.append(record)
    rd = subprocess.run([*script("readiness_check.py"), "--project", ".", "--json"], cwd=ctx.project, capture_output=True, text=True)
    try:
        rows = json.loads(rd.stdout).get("rows", [])
    except ValueError:
        rows = []
    check(checks, "the readiness check ran and gave its rows", bool(rows), (rd.stderr or rd.stdout).strip()[-300:])
    owner_only = {"handoff spec", "owner decisions", "git clean"}
    fails = [r for r in rows if r["status"] == "FAIL" and not (r["check"] in owner_only and ("sign" in r["detail"].lower() or "wait on the owner" in r["detail"] or "fable/" in r["detail"]))]
    check(checks, "readiness has no failure except the owner's sign-off and answers", not fails, "; ".join("%s: %s" % (r["check"], r["detail"][:160]) for r in fails[:5]))
    commands.append(run(ctx, 7, [*script("system_review.py"), "--project", "."], writes=["fable/IMPROVEMENTS.md"]))
    return {"checks": checks, "commands": commands, "inputs": ["fable/MISSION.md", "fable/STATE.md", "fable/DECISIONS.md", "fable/handoff.json"],
            "leaves": ["fable/IMPROVEMENTS.md"], "data": {"rows": rows}, "result": "awaiting owner sign-off",
            "next": "The owner reads fable/MISSION.md, fable/STATE.md and fable/DECISIONS.md, answers fable/owner_decisions.json "
                    "(decision_interview.py --file fable/owner_decisions.json), signs the spec (spec_tool.py signoff --project . --by <name>), "
                    "commits the package, and runs readiness_check.py. Launching (phase 8) is the owner's."}


PHASES = [phase_0, phase_1, phase_2, phase_3, phase_4, phase_5, phase_6, phase_7]


def run_phase(ctx: Ctx, n: int, outputs: dict | None = None) -> dict:
    """Run one phase, check it, write its receipt. Returns the receipt (result passed, stopped or awaiting owner sign-off)."""
    outputs = outputs or {}
    started = datetime.datetime.now().isoformat(timespec="seconds")
    result = {"phase": n, "name": NAMES[n], "started": started, "project": str(ctx.project), "preset": ctx.preset, "shape": ctx.shape}
    try:
        done = PHASES[n](ctx, outputs)
        for rel in done.get("leaves", []):
            if not (ctx.project / rel).exists():
                raise Stop("check failed: %s was not left by phase %d" % (rel, n))
        result.update(result=done.get("result", "passed"), reason=None, checks=done["checks"], commands=done["commands"],
                      inputs={rel: sha(ctx.project / rel) for rel in done.get("inputs", [])},
                      outputs={rel: sha(ctx.project / rel) for rel in done.get("leaves", [])}, data=done.get("data", {}), next=done.get("next"))
    except Stop as stop:
        result.update(result="stopped", reason=str(stop.args[0]), commands=[stop.args[1]] if len(stop.args) > 1 else [])
    except subprocess.TimeoutExpired as error:
        result.update(result="stopped", reason="timed out: %s" % error)
    result["ended"] = datetime.datetime.now().isoformat(timespec="seconds")
    path = receipt_path(ctx.project, n)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--preset")
    ap.add_argument("--shape")
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--until", type=int, default=7)
    ap.add_argument("--logs", nargs="*", default=[], help="more conversation logs (files or folders) beside the project's own")
    ap.add_argument("--no-logs", action="store_true", help="the project has no conversation logs; recorded in the receipt")
    ap.add_argument("--goal")
    ap.add_argument("--verify-command")
    ap.add_argument("--apply-settings", action="store_true")
    ap.add_argument("--max-budget-usd", type=float)
    ap.add_argument("--shared-from", help="the main checkout to link shared_data from, in place of the preset's shared_data.from")
    args = ap.parse_args()
    ctx = Ctx(project=Path(args.project).expanduser().resolve(), preset=args.preset, shape=args.shape, logs=args.logs, no_logs=args.no_logs,
              goal=args.goal, verify_command=args.verify_command, apply_settings=args.apply_settings, max_budget_usd=args.max_budget_usd,
              shared_from=args.shared_from)
    outputs = {}
    for n in range(args.start, min(args.until, 7) + 1):
        r = run_phase(ctx, n, outputs)
        outputs[n] = r
        print("phase %d %-10s %s%s" % (n, NAMES[n], r["result"], (": " + r["reason"]) if r.get("reason") else ""))
        if r["result"] == "stopped":
            return 1
        if r["result"] == "awaiting owner sign-off":
            print(r["next"])
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
