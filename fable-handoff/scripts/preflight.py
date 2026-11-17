#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Preflight: map what a project already has onto what a Fable takeover needs.

    uv run --script scripts/preflight.py --project /path/to/project
    uv run --script scripts/preflight.py --project . --goal docs/GOAL.md --run-tests
    uv run --script scripts/preflight.py --project . --source docs/ --source notes/lessons.md --json

Use it on a project that is already close: it has a goal, specification
documents, standards, notes on its current state, a record of what went wrong
and what worked, and tests or evals. Preflight finds those materials, sorts
them into six inputs, measures how ready each one is, and lists exactly what
must be added or fixed before init_handoff.py and the mission.

The six inputs:

  goal        what the run must achieve                  (required)
  spec        what the result must do, in detail
  standards   rules for how the work is done
  state       what exists and works today
  history     past errors and successes, lessons
  evals       tests, evals or checks that prove "done"   (required)

Outputs:
  fable/PREFLIGHT.md    the report, for you and the owner
  fable/preflight.json  the same data, for scripts and later phases

The report also drafts material for later phases: candidate tasks from
unchecked acceptance criteria, a verify command, paths to protect, open
questions for the owner interview, and lessons from history worth carrying
into the mission. Drafts are suggestions. Read every one before using it.

Exit codes: 0 every input is at least THIN and nothing blocks, 1 a required
input is MISSING or a blocking gap exists. Standard library only.
"""
from __future__ import annotations

# Every script in this skill runs under uv, never a bare interpreter.
UV_SCRIPT = ["uv", "run", "--quiet", "--script"]

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build",
             "target", ".next", ".cache", ".pytest_cache", ".mypy_cache", ".tox", "fable", ".run", "worktrees"}
DOC_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".adoc"}
INSTRUCTION_NAMES = {"claude.md", "claude.local.md", "agents.md", "agent.md", ".cursorrules"}
MAX_DOC_BYTES = 400_000

# Each input is recognised by words in the file path and by words in its headings.
CATEGORIES = {
    "goal": {
        "path": r"\b(goal|goals|objective|objectives|vision|north[-_ ]?star|mission|brief|okr)s?\b",
        "head": r"\b(goal|goals|objective|vision|north star|success criteria|what we are building|purpose)\b",
    },
    "spec": {
        "path": r"\b(spec|specs|specification|prd|requirements?|rfc|design|architecture|adr|feature|user[-_ ]?stories)\b",
        "head": r"\b(requirements?|specification|acceptance criteria|user stories|functional|interface|api|architecture|design)\b",
    },
    "standards": {
        "path": r"\b(standards?|conventions?|style|guidelines?|contributing|coding|lint|rules|principles)\b",
        "head": r"\b(standards?|conventions?|style guide|guidelines|code style|naming|principles|definition of done)\b",
    },
    "state": {
        "path": r"\b(status|state|progress|current|roadmap|todo|backlog|handoff|changelog|readme|notes)\b",
        "head": r"\b(status|current state|progress|what works|known issues|limitations|next steps|todo|roadmap)\b",
    },
    "history": {
        "path": r"\b(history|lessons?|learnings?|retro|retrospective|postmortem|post[-_ ]mortem|incidents?|errors?|mistakes|decisions?|adr|log|journal)\b",
        "head": r"\b(lessons|learned|what went wrong|what worked|mistakes|errors|failures|successes|retrospective|postmortem|incident|decision)\b",
    },
}

CHECKBOX_OPEN = re.compile(r"^\s*[-*]\s+\[ \]\s+(.+?)\s*$")
CHECKBOX_DONE = re.compile(r"^\s*[-*]\s+\[[xX]\]\s+(.+?)\s*$")
REQUIREMENT = re.compile(r"\b(must|shall|required to|has to|needs to)\b", re.IGNORECASE)
OPEN_QUESTION = re.compile(r"(\bTBD\b|\bTODO\b|\bFIXME\b|\bopen question|\bundecided\b|\bto be decided\b|\?\s*$)", re.IGNORECASE)
ERROR_WORDS = re.compile(r"\b(failed|fails|broke|broken|regress\w*|bug|crash\w*|did not work|didn't work|mistake|wrong|lost|timed out|flaky|rolled back|avoid|do not repeat|don't repeat)\b", re.IGNORECASE)
SUCCESS_WORDS = re.compile(r"\b(worked|works well|succeeded|success|fixed by|solved|what helped|keep doing|proven|reliable)\b", re.IGNORECASE)
EVAL_PATH = re.compile(r"(^|/)([\w.]*[_-])?(tests?|__tests__|spec|specs|evals?|benchmarks?|e2e|acceptance|qa)(/|$)|(^|/)(test_[^/]+|[^/]+_test\.[a-z]+|[^/]+\.(test|spec)\.[a-z]+|[^/]*evals?[^/]*\.(json|jsonl|ya?ml|py))$", re.IGNORECASE)
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java", ".kt", ".cs", ".php", ".swift", ".c", ".cpp", ".json", ".jsonl", ".yaml", ".yml"}


# --------------------------------------------------------------------------- discovery

def walk(project: Path):
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") or d == ".claude")
        for name in sorted(filenames):
            yield Path(dirpath) / name


def rel(project: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project).as_posix()
    except ValueError:
        return str(path)


def read_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_DOC_BYTES:
            return path.read_bytes()[:MAX_DOC_BYTES].decode("utf-8", errors="replace")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def headings(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^\s{0,3}#{1,4}\s+(.+?)\s*#*\s*$", text, flags=re.M)]


def classify(relpath: str, text: str) -> list[str]:
    """Return the inputs a document serves, strongest first. A document can serve several."""
    path_words = re.sub(r"[/_.\-]", " ", relpath.lower())
    heads = " ".join(headings(text)).lower()
    scores = {}
    for cat, rx in CATEGORIES.items():
        score = 0
        if re.search(rx["path"], path_words):
            score += 3
        score += min(len(re.findall(rx["head"], heads)), 3)
        if score:
            scores[cat] = score
    if not scores:
        return []
    top = max(scores.values())
    # Keep categories reasonably close to the best match, so a README that is
    # mostly state is not also called a spec because of one heading.
    return [c for c, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s >= max(2, top - 2)]


def discover(project: Path, sources: list[Path], goal_arg: str | None):
    docs: dict[str, dict] = {}
    eval_files: list[str] = []
    instructions: list[str] = []
    roots = sources or [project]
    seen: set[Path] = set()
    for root in roots:
        files = [root] if root.is_file() else list(walk(root)) if root.is_dir() else []
        for path in files:
            path = path.resolve()
            if path in seen:
                continue
            seen.add(path)
            r = rel(project, path)
            if path.name.lower() in INSTRUCTION_NAMES or "/.claude/" in "/" + r:
                if path.suffix.lower() in DOC_SUFFIXES or path.name.lower() in INSTRUCTION_NAMES:
                    instructions.append(r)
                continue
            if EVAL_PATH.search(r) and path.suffix.lower() in CODE_SUFFIXES:
                eval_files.append(r)
                continue
            if path.suffix.lower() in DOC_SUFFIXES:
                text = read_text(path)
                # Classify by the path inside the project, or for an outside
                # source by its last two parts, so temp or home directory
                # names do not count as signals.
                cats = classify(r if not r.startswith("/") else "/".join(path.parts[-2:]), text)
                docs[r] = {"path": r, "categories": cats, "words": len(text.split()), "text": text}
    # Sources given explicitly may live outside the project, but evals are
    # always looked for inside it as well.
    if sources:
        for path in walk(project):
            r = rel(project, path)
            if EVAL_PATH.search(r) and path.suffix.lower() in CODE_SUFFIXES and r not in eval_files:
                eval_files.append(r)
    goal_doc = None
    if goal_arg:
        # An explicit goal is the only goal. Other documents keep their other roles.
        for doc in docs.values():
            doc["categories"] = [c for c in doc["categories"] if c != "goal"]
        candidate = Path(goal_arg).expanduser()
        if not candidate.is_absolute():
            candidate = project / candidate
        if candidate.is_file():
            r = rel(project, candidate.resolve())
            text = read_text(candidate)
            docs.setdefault(r, {"path": r, "categories": [], "words": len(text.split()), "text": text})
            if "goal" not in docs[r]["categories"]:
                docs[r]["categories"].insert(0, "goal")
            goal_doc = r
        else:
            goal_doc = "(given on the command line)"
            docs[goal_doc] = {"path": goal_doc, "categories": ["goal"], "words": len(goal_arg.split()), "text": goal_arg}
    return docs, sorted(eval_files), sorted(instructions), goal_doc


# --------------------------------------------------------------------------- test commands

def detect_test_commands(project: Path, eval_files: list[str]) -> list[str]:
    found: list[str] = []
    pyproject = project / "pyproject.toml"
    py_tests = any(re.search(r"(^|/)test_[^/]+\.py$|_test\.py$", f) for f in eval_files)
    if pyproject.exists() or (project / "pytest.ini").exists() or (project / "setup.cfg").exists() or py_tests:
        text = read_text(pyproject)
        if pyproject.exists() and ("[project]" in text or "[tool.uv]" in text or (project / "uv.lock").exists()):
            found.append("uv run pytest -q")
        else:
            found.append("uv run --with pytest pytest -q")
    pkg = project / "package.json"
    if pkg.exists():
        try:
            scripts = json.loads(read_text(pkg)).get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        runner = "pnpm" if (project / "pnpm-lock.yaml").exists() else "yarn" if (project / "yarn.lock").exists() else "npm"
        for name in ("verify", "check", "test", "test:e2e", "eval", "evals"):
            if name in scripts:
                found.append(f"{runner} run {name}" if name != "test" else f"{runner} test")
    makefile = project / "Makefile"
    if makefile.exists():
        targets = set(re.findall(r"^([A-Za-z][\w-]*):", read_text(makefile), flags=re.M))
        for name in ("verify", "check", "test", "eval", "evals", "ci"):
            if name in targets:
                found.append(f"make {name}")
    if (project / "Cargo.toml").exists():
        found.append("cargo test")
    if (project / "go.mod").exists():
        found.append("go test ./...")
    out: list[str] = []
    for cmd in found:
        if cmd not in out:
            out.append(cmd)
    return out


def summarize_test_output(output: str) -> dict:
    """Pull pass and fail counts from common runners' summary lines."""
    counts: dict[str, int] = {}
    for number, word in re.findall(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|pending|passing|failing)\b", output):
        key = {"error": "errors", "passing": "passed", "failing": "failed"}.get(word, word)
        counts[key] = counts.get(key, 0) + int(number)
    m = re.search(r"Tests:\s+(?:(\d+) failed, )?(?:(\d+) skipped, )?(\d+) passed", output)
    if m and not counts:
        counts = {"failed": int(m.group(1) or 0), "skipped": int(m.group(2) or 0), "passed": int(m.group(3))}
    return counts


def run_tests(project: Path, command: str, timeout: int) -> dict:
    started = time.time()
    try:
        proc = subprocess.run(command, shell=True, cwd=project, capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"command": command, "exit_code": None, "seconds": timeout, "timed_out": True, "counts": {}, "tail": ""}
    output = proc.stdout + "\n" + proc.stderr
    return {
        "command": command,
        "exit_code": proc.returncode,
        "seconds": round(time.time() - started, 1),
        "timed_out": False,
        "counts": summarize_test_output(output),
        "tail": "\n".join(output.strip().splitlines()[-12:]),
    }


# --------------------------------------------------------------------------- extraction

def strip_code(text: str) -> list[tuple[int, str]]:
    lines, in_code = [], False
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            lines.append((number, line))
    return lines


def clean(line: str) -> str:
    line = re.sub(r"^\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?", "", line).strip()
    return line[:220]


def extract(docs: dict[str, dict]) -> dict:
    criteria_open, criteria_done, requirements, questions, errors, successes = [], [], [], [], [], []
    for path, doc in docs.items():
        cats = set(doc["categories"])
        for number, line in strip_code(doc["text"]):
            where = f"{path}:{number}"
            if CHECKBOX_OPEN.match(line):
                criteria_open.append({"where": where, "text": clean(line)})
            elif CHECKBOX_DONE.match(line):
                criteria_done.append({"where": where, "text": clean(line)})
            elif cats & {"spec", "goal"} and REQUIREMENT.search(line) and len(line.split()) >= 4:
                requirements.append({"where": where, "text": clean(line)})
            if OPEN_QUESTION.search(line) and len(line.split()) >= 3 and not line.strip().startswith("#"):
                questions.append({"where": where, "text": clean(line)})
            if "history" in cats or "state" in cats:
                if ERROR_WORDS.search(line) and len(line.split()) >= 4:
                    errors.append({"where": where, "text": clean(line)})
                elif SUCCESS_WORDS.search(line) and len(line.split()) >= 4:
                    successes.append({"where": where, "text": clean(line)})
    return {
        "criteria_open": criteria_open,
        "criteria_done": criteria_done,
        "requirements": requirements,
        "open_questions": questions,
        "past_errors": errors,
        "past_successes": successes,
    }


# --------------------------------------------------------------------------- assessment

def git_state(project: Path) -> dict:
    def g(*args):
        p = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True)
        return p.returncode, p.stdout.strip()
    code, _ = g("rev-parse", "--is-inside-work-tree")
    if code != 0:
        return {"repo": False}
    _, branch = g("rev-parse", "--abbrev-ref", "HEAD")
    _, dirty = g("status", "--porcelain")
    _, last = g("log", "-1", "--format=%h %s")
    noise = re.compile(r"(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|node_modules)(/|$)|^fable/")
    changes = [l for l in dirty.splitlines() if l.strip() and not noise.search(l[3:].strip('"'))]
    return {"repo": True, "branch": branch, "uncommitted": len(changes), "last_commit": last}


def assess(docs, evals, test_runs, extracted, goal_doc, git) -> tuple[list[dict], list[dict]]:
    by_cat: dict[str, list[dict]] = {c: [] for c in ("goal", "spec", "standards", "state", "history")}
    for doc in docs.values():
        for cat in doc["categories"]:
            by_cat[cat].append(doc)

    def words(cat):
        return sum(d["words"] for d in by_cat[cat])

    inputs, gaps = [], []

    def add(name, status, sources, detail, fix=""):
        inputs.append({"input": name, "status": status, "sources": sources, "detail": detail, "fix": fix})

    # goal
    goal_sources = [d["path"] for d in by_cat["goal"]]
    if goal_doc:
        goal_sources = [goal_doc] + [s for s in goal_sources if s != goal_doc]
    gw = words("goal")
    if not goal_sources:
        add("goal", "MISSING", [], "No goal document found.",
            "Write the goal in one place: the outcome, who it is for, and how anyone would check it is reached. Pass it with --goal.")
        gaps.append({"severity": "BLOCKING", "input": "goal", "text": "There is no written goal. The mission's Job and Why are built from it."})
    elif gw < 40:
        add("goal", "THIN", goal_sources, f"{gw} words.", "Expand to the outcome, the audience, and what wins when goals conflict.")
        gaps.append({"severity": "FIX", "input": "goal", "text": f"The goal is only {gw} words. The Job needs 40 or more and the Why 20 or more."})
    else:
        add("goal", "READY", goal_sources, f"{gw} words in {len(goal_sources)} file(s).")
    if len(goal_sources) > 2:
        gaps.append({"severity": "FIX", "input": "goal", "text": f"The goal is spread over {len(goal_sources)} files. Settle which one is current before writing the mission: {', '.join(goal_sources[:5])}"})

    # spec
    spec_sources = [d["path"] for d in by_cat["spec"]]
    criteria = len(extracted["criteria_open"]) + len(extracted["criteria_done"]) + len(extracted["requirements"])
    if not spec_sources:
        add("spec", "MISSING", [], "No specification found.",
            "Without a spec, the evals are the only definition of the result. Write the behaviors that matter, or confirm the evals cover them.")
        gaps.append({"severity": "FIX", "input": "spec", "text": "No specification document. Either write one or confirm in DECISIONS.md that the evals are the full definition."})
    elif criteria < 3:
        add("spec", "THIN", spec_sources, f"{criteria} checkable criteria found.", "Add acceptance criteria as checkbox lines or 'must' statements.")
        gaps.append({"severity": "FIX", "input": "spec", "text": "The spec has fewer than three checkable criteria. Each criterion becomes a task or a test."})
    else:
        add("spec", "READY", spec_sources, f"{criteria} criteria: {len(extracted['criteria_open'])} open, {len(extracted['criteria_done'])} done, {len(extracted['requirements'])} requirement lines.")

    # standards
    std_sources = [d["path"] for d in by_cat["standards"]]
    if not std_sources:
        add("standards", "MISSING", [], "No standards found.", "List the conventions the run must follow, or record that the codebase's own conventions are the standard.")
        gaps.append({"severity": "REVIEW", "input": "standards", "text": "No written standards. The operating rules tell the model to follow the codebase's conventions; record anything beyond that in DECISIONS.md."})
    else:
        add("standards", "READY" if words("standards") >= 80 else "THIN", std_sources, f"{words('standards')} words.",
            "" if words("standards") >= 80 else "Expand, or confirm the codebase itself is the standard.")

    # state
    st_sources = [d["path"] for d in by_cat["state"]]
    measured = [r for r in test_runs if r.get("exit_code") is not None]
    if not st_sources and not measured:
        add("state", "MISSING", [], "No state notes and no measured test run.",
            "Run with --run-tests to measure the current state, and write what works, what is half done and what is known to be broken.")
        gaps.append({"severity": "FIX", "input": "state", "text": "The current state is not written down. The mission's 'Where things are' and the first tasks in STATE.md depend on it."})
    else:
        detail = f"{len(st_sources)} file(s)"
        if measured:
            r = measured[0]
            detail += f"; `{r['command']}` exit {r['exit_code']}, {r['counts'] or 'no counts parsed'}"
        add("state", "READY" if st_sources and measured else "THIN", st_sources, detail,
            "" if st_sources and measured else ("Run with --run-tests." if not measured else "Write down what works and what is known broken."))
    if git.get("repo") is False:
        gaps.append({"severity": "BLOCKING", "input": "state", "text": "The project is not a git repository. The run needs a rollback point and a diff to review."})
    elif git.get("uncommitted"):
        gaps.append({"severity": "FIX", "input": "state", "text": f"{git['uncommitted']} uncommitted change(s). Commit or stash them so the run starts from a known point."})

    # history
    h_sources = [d["path"] for d in by_cat["history"]]
    if not h_sources:
        add("history", "MISSING", [], "No record of past errors or successes.",
            "Ask the owner what was tried and failed, and what worked. Each answer becomes a decision or a trap note.")
        gaps.append({"severity": "REVIEW", "input": "history", "text": "No history of errors and successes. Ask about it in the interview: a repeated mistake is the most expensive thing a long run can do."})
    else:
        n = len(extracted["past_errors"]) + len(extracted["past_successes"])
        add("history", "READY" if n >= 2 else "THIN", h_sources,
            f"{len(extracted['past_errors'])} error line(s), {len(extracted['past_successes'])} success line(s).",
            "" if n >= 2 else "Few concrete lessons found. Ask the owner directly.")

    # evals
    if not evals and not test_runs:
        add("evals", "MISSING", [], "No tests, evals or test command found.",
            "Build the verify command first. A run without one cannot be told when it is done.")
        gaps.append({"severity": "BLOCKING", "input": "evals", "text": "No tests or evals. 'Done' must be checkable by a program before an unattended run."})
    else:
        detail = f"{len(evals)} test or eval file(s)"
        status = "READY"
        if test_runs:
            r = test_runs[0]
            if r.get("timed_out"):
                status = "THIN"
                detail += f"; `{r['command']}` timed out"
                gaps.append({"severity": "BLOCKING", "input": "evals", "text": f"`{r['command']}` timed out. The verify command has to finish reliably."})
            elif r.get("exit_code") in (126, 127):
                status = "THIN"
                detail += f"; `{r['command']}` could not run"
                gaps.append({"severity": "BLOCKING", "input": "evals", "text": f"`{r['command']}` could not be executed (exit {r['exit_code']})."})
            elif r.get("exit_code") == 0:
                status = "THIN"
                detail += f"; `{r['command']}` already passes"
                gaps.append({"severity": "BLOCKING", "input": "evals",
                             "text": "The test command already passes, so it cannot tell done from not done. Turn the goal's remaining criteria into failing acceptance tests or evals before the takeover."})
            else:
                detail += f"; `{r['command']}` fails today ({r['counts'] or 'exit ' + str(r['exit_code'])}), which is right before the run"
        else:
            detail += "; not run (use --run-tests)"
        if extracted["criteria_open"] and len(evals) < 2:
            gaps.append({"severity": "FIX", "input": "evals", "text": f"{len(extracted['criteria_open'])} open criteria but few test files. Make sure each criterion is checked by a test or eval."})
        add("evals", status, evals[:12], detail)

    for q in extracted["open_questions"][:40]:
        gaps.append({"severity": "QUESTION", "input": "open question", "text": f"{q['text']} ({q['where']})"})
    return inputs, gaps


def drafts(project, inputs, extracted, evals, test_cmds, test_runs, docs, goal_doc) -> dict:
    tasks = [c["text"] for c in extracted["criteria_open"]][:15]
    verify = None
    for r in test_runs:
        if r.get("exit_code") not in (None, 0, 126, 127) and not r.get("timed_out"):
            verify = r["command"]
            break
    if verify is None and test_cmds:
        verify = test_cmds[0]
    protect = set()
    for e in evals:
        top = e.split("/")[0]
        protect.add(f"{top}/**" if "/" in e else e)
    for doc in docs.values():
        if set(doc["categories"]) & {"goal", "spec", "standards"} and not doc["path"].startswith("("):
            protect.add(doc["path"])
    lessons = [e["text"] for e in extracted["past_errors"]][:10]
    keep = [s["text"] for s in extracted["past_successes"]][:6]
    return {
        "verify_command": verify,
        "seed_tasks": tasks,
        "protected_paths": sorted(protect),
        "traps_for_mission": lessons,
        "what_worked": keep,
        "question_triage": [triage_question(q["text"]) for q in extracted["open_questions"]],
        "decision_candidates": [q["text"] for q in extracted["open_questions"] if triage_question(q["text"])["kind"] == "judgment"][:15],
        "goal_source": goal_doc,
    }


# Detective work first. Most questions that look like judgment calls are
# questions of fact the project can answer. A question is sorted as a judgment
# call only when it asks for a policy or a preference; everything else starts
# as "evidence can settle", to be searched on the evidence ladder. This is a
# first sort, from wording only: the preparing agent confirms each one.
JUDGMENT_CUES = re.compile(
    r"\b(?:prefer\w*|want|wish|like (?:it|us|to)|should (?:we|i|you|the team)|do we (?:want|need)|policy|priorit\w+|"
    r"trade-?offs?|acceptable|tolerance|taste|style|worth (?:it|the)|ok(?:ay)? (?:to|with)|willing|allowed to|"
    r"which (?:approach|option|direction|look)|go with|risk appetite|brand|tone)\b",
    re.IGNORECASE,
)


# A project or preset may add its own cue words in "question_triage" of
# fable/handoff.json or of assets/presets/<name>/preset.json:
#   judgment_cues: words that mean the firm's own choice (for MARPA: design
#     intent, client preference, allowance, fee policy). These win.
#   fact_cues: words that mean a fact the drawings, budget or standard can
#     answer (for MARPA: dimensions, labels, quantities, species). A fact cue
#     overrides a generic judgment cue, so "what tolerance does the budget
#     use" is searched, not asked.
PROJECT_CUES: dict[str, re.Pattern | None] = {"judgment": None, "fact": None}


def _cue_regex(words) -> re.Pattern | None:
    words = [str(w).strip() for w in words or [] if str(w).strip()]
    return re.compile(r"\b(?:%s)\b" % "|".join(words), re.IGNORECASE) if words else None


def load_triage_cues(project: Path, preset: str | None = None) -> dict:
    """Read the project's or preset's cue words into PROJECT_CUES. Returns the raw lists."""
    found: dict = {}
    sources = []
    if preset:
        sources.append(Path(__file__).resolve().parent.parent / "assets" / "presets" / preset / "preset.json")
    sources.append(project / "fable" / "handoff.json")
    for path in sources:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            block = data.get("question_triage") or (data.get("config") or {}).get("question_triage") or {}
        except (OSError, ValueError, AttributeError):
            continue
        for key in ("judgment_cues", "fact_cues"):
            for word in block.get(key) or []:
                found.setdefault(key, [])
                if word not in found[key]:
                    found[key].append(word)
    PROJECT_CUES["judgment"] = _cue_regex(found.get("judgment_cues"))
    PROJECT_CUES["fact"] = _cue_regex(found.get("fact_cues"))
    return found


def triage_question(text: str) -> dict:
    own = PROJECT_CUES["judgment"].search(text) if PROJECT_CUES["judgment"] else None
    if own:
        return {"question": text, "kind": "judgment", "why": "asks for the firm's own choice (\"%s\")" % own.group(0)}
    fact = PROJECT_CUES["fact"].search(text) if PROJECT_CUES["fact"] else None
    if fact:
        return {"question": text, "kind": "evidence", "why": "asks for a fact the project holds (\"%s\"); search the evidence ladder first" % fact.group(0)}
    cue = JUDGMENT_CUES.search(text)
    if cue:
        return {"question": text, "kind": "judgment", "why": "asks for a policy or preference (\"%s\")" % cue.group(0)}
    return {"question": text, "kind": "evidence", "why": "asks for a fact; search the evidence ladder before anyone asks the owner"}


def previous_run(project: Path) -> dict:
    """What an earlier handoff run left behind, so the next one starts from it.

    Reads fable/.run/lessons.json (written by post_run_report.py), the run's
    decisions and items left for the owner, its report and blocker, and lists
    its transcripts. Returns {} when there was no earlier run.
    """
    fable = project / "fable"
    out: dict = {"documents": {}, "lessons": [], "transcripts": []}
    lessons = fable / ".run" / "lessons.json"
    if lessons.exists():
        try:
            out["lessons"] = json.loads(lessons.read_text(encoding="utf-8")).get("proposals", [])
        except (ValueError, AttributeError):
            pass
    decisions = fable / "DECISIONS.md"
    if decisions.exists():
        text = decisions.read_text(encoding="utf-8", errors="replace")
        body = re.findall(r"^## (Made during the run|Left for the owner)\s*$(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
        items = [(title, l.strip().lstrip("-* ").strip()) for title, b in body for l in re.sub(r"<!--.*?-->", "", b, flags=re.S).splitlines() if l.strip().startswith(("-", "*"))]
        if items:
            out["documents"]["fable/DECISIONS.md"] = text
            if not out["lessons"]:
                out["lessons"] = [{"kind": "decision" if t == "Made during the run" else "question", "text": i[:240],
                                   "source": f"fable/DECISIONS.md ({t})"} for t, i in items]
    for name in ("REPORT.md", "BLOCKED.md"):
        path = fable / name
        if path.exists() and path.read_text(encoding="utf-8", errors="replace").strip():
            out["documents"][f"fable/{name}"] = path.read_text(encoding="utf-8", errors="replace")
    run_dir = fable / ".run"
    if run_dir.is_dir():
        out["transcripts"] = [str(p) for p in sorted(run_dir.glob("transcript-*.jsonl"))]
    return out if (out["documents"] or out["lessons"] or out["transcripts"]) else {}


def read_conversations(project: Path, paths: list[str], project_logs: bool, no_write: bool) -> dict:
    """Run conversation_context.py and return its Markdown and data, or an error to report."""
    script = Path(__file__).resolve().parent / "conversation_context.py"
    cmd = [*UV_SCRIPT, str(script), "--project", str(project), "--json"]
    if paths:
        cmd += ["--logs", *paths]
    if project_logs:
        cmd.append("--project-logs")
    if no_write:
        cmd.append("--no-write")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"error": "Conversation logs were not read: " + (proc.stderr.strip().splitlines() or ["unknown error"])[0]}
    data = json.loads(proc.stdout)
    path = project / "fable" / "CONTEXT.md"
    markdown_text = path.read_text(encoding="utf-8") if path.exists() and not no_write else ""
    if no_write:
        md_proc = subprocess.run([c for c in cmd if c != "--json"], capture_output=True, text=True)
        markdown_text = md_proc.stdout
    return {"data": data, "markdown": markdown_text}


def run_audit(project: Path, standards: list[str]) -> dict:
    """Run audit_rules.py on the instruction files and the standards documents."""
    script = Path(__file__).resolve().parent / "audit_rules.py"
    cmd = [*UV_SCRIPT, str(script), "--project", str(project), "--json"]
    extra = [str(project / s) for s in standards]
    if extra:
        cmd += ["--extra", *extra]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        findings = json.loads(proc.stdout).get("findings", [])
    except Exception:
        return {"fix": [], "review": [], "error": "audit_rules.py could not be run"}
    pick = lambda sev: sorted({"%s:%s" % (f["file"], f["line"]) for f in findings if f["severity"] == sev and not f.get("accepted")})
    return {"fix": pick("FIX"), "review": pick("REVIEW")}


def goal_prose(text: str) -> str:
    """The goal document without headings and list markers, as one block of prose."""
    lines = [l.strip() for _, l in strip_code(text) if l.strip() and not l.lstrip().startswith("#")]
    return " ".join(clean(l) if re.match(r"^\s*([-*+]|\d+[.)])\s", l) else l for l in lines)


def build_spec(project, docs, extracted, draft, test_runs, goal_doc, git) -> dict:
    """Draft fable/handoff_spec.json from what preflight found. The agent completes it."""
    goal_text = docs[goal_doc]["text"] if goal_doc in docs else next(
        (d["text"] for d in docs.values() if "goal" in d["categories"]), "")
    criteria = []
    for n, c in enumerate(extracted["criteria_open"], 1):
        criteria.append({"id": f"c{n}", "text": c["text"], "status": "open", "verified_by": None, "source": c["where"]})
    for n, c in enumerate(extracted["criteria_done"], len(criteria) + 1):
        criteria.append({"id": f"c{n}", "text": c["text"], "status": "done", "verified_by": None, "source": c["where"]})
    by_text = {c["text"]: c["id"] for c in criteria}
    baseline = None
    if test_runs and test_runs[0].get("exit_code") is not None:
        r = test_runs[0]
        baseline = {"command": r["command"], "exit_code": r["exit_code"], "counts": r["counts"]}
    forbidden = [{"action": f"Do not edit {p}", "reason": "it defines the job; the run must not pass by changing its own definition of done",
                  "enforced_by": {"protected_paths": [p]}} for p in draft["protected_paths"]]
    roles = []
    for d in docs.values():
        if d["path"].startswith("("):
            continue
        for cat in d["categories"] or ["other"]:
            roles.append({"path": d["path"], "role": cat})
    return {
        "schema_version": 1,
        "project": {"name": project.name, "repository": None},
        "goal": {"job": goal_prose(goal_text), "why": "",
                 "sources": [goal_doc] if goal_doc else [d["path"] for d in docs.values() if "goal" in d["categories"]]},
        "current_state": {"summary": "", "works": [], "half_done": [], "broken": [], "baseline": baseline},
        "where_things_are": [{"path": s["path"], "purpose": f"{s['role']} document"} for s in roles if s["role"] in ("spec", "standards", "state", "history")],
        "commands": {"verify": draft["verify_command"] or "", "fast_check": None, "build": None, "run": None},
        "acceptance_criteria": criteria,
        "tasks": [{"text": t, "check": None, "criteria": [by_text[t]] if t in by_text else []} for t in draft["seed_tasks"]],
        "guardrails": {"pre_approved": [], "forbidden": forbidden, "out_of_scope": []},
        "decisions": [],
        "defaults": [],
        "open_questions": [{"question": q["text"], "source": q["where"], "kind": triage_question(q["text"])["kind"]} for q in extracted["open_questions"]],
        "traps": [{"text": e["text"], "instead": None, "source": e["where"]} for e in extracted["past_errors"]],
        "practices_to_keep": [{"text": e["text"], "source": e["where"]} for e in extracted["past_successes"]],
        "done_extra": [],
        "run": {"branch": "fable/run-1", "model": "claude-fable-5-2", "effort": "high", "permission_mode": "auto",
                "max_budget_usd": None, "max_relaunches": 3},
        "sources": roles,
    }


# --------------------------------------------------------------------------- report

def markdown(project, inputs, gaps, draft, test_runs, instructions, git) -> str:
    blocking = [g for g in gaps if g["severity"] == "BLOCKING"]
    verdict = "READY FOR PREPARATION" if not blocking and not any(i["status"] == "MISSING" and i["input"] in ("goal", "evals") for i in inputs) else "NOT READY"
    out = [
        "# Preflight for a Fable takeover",
        "",
        f"**{verdict}.** {sum(1 for i in inputs if i['status'] == 'READY')} of 6 inputs ready, "
        f"{len(blocking)} blocking gap(s), {sum(1 for g in gaps if g['severity'] == 'FIX')} to fix, "
        f"{sum(1 for g in gaps if g['severity'] == 'QUESTION')} open question(s).",
        "",
        "Preflight sorts what the project already has into the six inputs a takeover needs. "
        "Close the blocking gaps first, take the open questions into the owner interview, "
        "then run init_handoff.py and write the mission from the drafts below.",
        "",
        "## The six inputs",
        "",
        "| Input | Status | Sources | Detail | To do |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i in inputs:
        src = ", ".join(f"`{s}`" for s in i["sources"][:4]) + (f" and {len(i['sources']) - 4} more" if len(i["sources"]) > 4 else "")
        out.append(f"| {i['input']} | {i['status']} | {src or 'none'} | {i['detail']} | {i['fix']} |")
    out += ["", "## Gaps", ""]
    order = {"BLOCKING": 0, "FIX": 1, "REVIEW": 2, "QUESTION": 3}
    if gaps:
        for g in sorted(gaps, key=lambda g: order[g["severity"]]):
            out.append(f"- **{g['severity']}** ({g['input']}): {g['text']}")
    else:
        out.append("None found.")
    out += ["", "## Current state", ""]
    out.append(f"Git: {'not a repository' if not git.get('repo') else git.get('branch') + ', ' + str(git.get('uncommitted')) + ' uncommitted, last commit ' + git.get('last_commit', '')}.")
    for r in test_runs:
        out += ["", f"`{r['command']}`: exit {r['exit_code']}, {r['seconds']} s, {r['counts'] or 'no counts parsed'}.", "", "```", r["tail"], "```"]
    if not test_runs:
        out.append("Tests were not run. Pass --run-tests to measure the current state.")
    if instructions:
        out += ["", f"Instruction files that will load during the run ({len(instructions)}): " + ", ".join(f"`{p}`" for p in instructions[:10]) + ". Phase 5 audits them."]
    out += ["", "## Drafts for the next phases", "",
            "Suggestions only. Check each against the sources before you use it.", ""]
    out.append(f"- **Verify command** (handoff.json, phase 3): `{draft['verify_command']}`" if draft["verify_command"] else "- **Verify command**: none found. Build one in phase 3.")
    if draft["protected_paths"]:
        out.append("- **Paths to protect** (handoff.json): " + ", ".join(f"`{p}`" for p in draft["protected_paths"][:15]) +
                   ". The run must not be able to pass by editing its own tests, evals or spec.")
    if draft["seed_tasks"]:
        out += ["- **Seed tasks** (STATE.md), from open acceptance criteria:"] + [f"  - [ ] {t}" for t in draft["seed_tasks"]]
    if draft["traps_for_mission"]:
        out += ["- **Traps for 'Where things are'**, from past errors. Carry the real ones into the mission with what to do instead:"] + [f"  - {t}" for t in draft["traps_for_mission"]]
    if draft["what_worked"]:
        out += ["- **What worked**, worth keeping as decisions:"] + [f"  - {t}" for t in draft["what_worked"]]
    triage = draft.get("question_triage") or []
    if triage:
        evidence = [t for t in triage if t["kind"] == "evidence"]
        judgment = [t for t in triage if t["kind"] == "judgment"]
        out += [f"- **Open questions: {len(evidence)} evidence can settle, {len(judgment)} judgment** (a first sort by wording; confirm each).",
                "  Settle the evidence ones yourself from the evidence ladder and record them by evidence. Only judgment calls go to the owner in phase 2."]
        out += [f"  - evidence: {t['question']}" for t in evidence[:20]]
        out += [f"  - judgment: {t['question']} ({t['why']})" for t in judgment[:20]]
    out += ["", "## Next", "",
            "1. Close every BLOCKING gap and rerun preflight until it says READY FOR PREPARATION.",
            "2. Interview the owner with the questions above (phase 2).",
            "3. Confirm or build the verify command (phase 3), then run init_handoff.py (phase 4) with it.",
            "4. Write the mission from the goal, spec and drafts (phase 6), keeping the sources as the authority."]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="project root")
    ap.add_argument("--goal", help="path to the goal document, or the goal itself as text")
    ap.add_argument("--source", action="append", default=[], metavar="PATH",
                    help="file or directory holding project documents; repeatable. Default: the whole project")
    ap.add_argument("--run-tests", action="store_true", help="run the detected test command to measure the current state")
    ap.add_argument("--test-command", help="test command to run instead of the detected one (implies --run-tests)")
    ap.add_argument("--test-timeout", type=int, default=1800, metavar="SECONDS")
    ap.add_argument("--conversations", nargs="*", default=[], metavar="PATH",
                    help="Claude Code conversation logs (JSONL files or directories) to mine for intent, issues and successes; needs jq")
    ap.add_argument("--project-logs", action="store_true",
                    help="also read the conversation logs Claude Code keeps for this project (~/.claude/projects/...); needs jq")
    ap.add_argument("--no-previous-run", action="store_true",
                    help="ignore what an earlier handoff run left in fable/ (lessons, decisions, report, transcripts)")
    ap.add_argument("--preset", help="a preset in assets/presets/ (for example marpa) whose question triage words to use")
    ap.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    ap.add_argument("--no-write", action="store_true", help="do not write fable/PREFLIGHT.md and fable/preflight.json")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"{project} is not a directory", file=sys.stderr)
        return 2
    sources = [Path(s).expanduser().resolve() if Path(s).expanduser().is_absolute() else (project / s).resolve() for s in args.source]
    missing = [str(s) for s in sources if not s.exists()]
    if missing:
        print("These --source paths do not exist: " + ", ".join(missing), file=sys.stderr)
        return 2

    load_triage_cues(project, args.preset)
    git = git_state(project)  # before any test run creates cache files
    docs, evals, instructions, goal_doc = discover(project, sources, args.goal)
    previous = {} if args.no_previous_run else previous_run(project)
    if previous.get("transcripts") and shutil.which("jq"):
        # The last run's own transcripts are conversations too.
        args.conversations = list(args.conversations) + previous["transcripts"]
    for rel, text in previous.get("documents", {}).items():
        docs[rel] = {"path": rel, "categories": ["history", "state"], "words": len(text.split()), "text": text}
    conversation = None
    if args.conversations or args.project_logs:
        conversation = read_conversations(project, args.conversations, args.project_logs, args.no_write)
        if conversation.get("markdown"):
            # The context document joins the other documents as a history and state source.
            docs["fable/CONTEXT.md"] = {"path": "fable/CONTEXT.md", "categories": ["history", "state"],
                                        "words": len(conversation["markdown"].split()), "text": conversation["markdown"]}
    test_cmds = detect_test_commands(project, evals)
    test_runs = []
    if args.test_command or args.run_tests:
        command = args.test_command or (test_cmds[0] if test_cmds else None)
        if command:
            test_runs.append(run_tests(project, command, args.test_timeout))
    extracted = extract(docs)
    inputs, gaps = assess(docs, evals, test_runs, extracted, goal_doc, git)
    if conversation and conversation.get("error"):
        gaps.append({"severity": "REVIEW", "input": "history", "text": conversation["error"]})
    audit = run_audit(project, [d["path"] for d in docs.values() if "standards" in d["categories"] and not d["path"].startswith("(")])
    if audit["fix"]:
        gaps.append({"severity": "FIX", "input": "instructions",
                     "text": "%d instruction line(s) will stall or mislead an unattended run: %s. Phase 5 rewrites them." % (len(audit["fix"]), ", ".join(audit["fix"][:6]))})
    if audit["review"]:
        gaps.append({"severity": "REVIEW", "input": "instructions",
                     "text": "%d line(s) to judge in context (absolutes, delegation, style caps): %s." % (len(audit["review"]), ", ".join(audit["review"][:6]))})
    draft = drafts(project, inputs, extracted, evals, test_cmds, test_runs, docs, goal_doc)
    ready = not any(g["severity"] == "BLOCKING" for g in gaps) and not any(
        i["status"] == "MISSING" and i["input"] in ("goal", "evals") for i in inputs)

    data = {
        "ready": ready,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "inputs": inputs,
        "gaps": gaps,
        "detected_test_commands": test_cmds,
        "test_runs": test_runs,
        "documents": [{"path": d["path"], "categories": d["categories"], "words": d["words"]} for d in docs.values()],
        "eval_files": evals,
        "instruction_files": instructions,
        "git": git,
        "audit": audit,
        "extracted": extracted,
        "drafts": draft,
    }
    report = markdown(project, inputs, gaps, draft, test_runs, instructions, git)
    spec = build_spec(project, docs, extracted, draft, test_runs, goal_doc, git)
    if previous.get("lessons"):
        for item in previous["lessons"]:
            src = item.get("source")
            if item["kind"] == "decision":
                spec["decisions"].append({"decision": item["text"], "reason": "made by the previous run; confirm it with the owner or remove it", "source": src})
            elif item["kind"] == "trap":
                spec["traps"].append({"text": item["text"], "instead": item.get("instead"), "source": src})
            else:
                spec["open_questions"].append({"question": item["text"], "source": src})
        data["previous_run"] = {"lessons": len(previous["lessons"]), "documents": sorted(previous["documents"]), "transcripts": len(previous["transcripts"])}
        report += ("\n## Previous run\n\nAn earlier handoff run left {n} lesson(s). They are in the draft spec: decisions it made "
                   "(confirm or remove each), traps, and open questions for the owner. Rendering stays blocked until every "
                   "question is answered.\n\n").format(n=len(previous["lessons"]))
        report += "\n".join(f"- {i['kind']}: {i['text']}" for i in previous["lessons"][:20]) + "\n"
    if conversation and conversation.get("data"):
        c = conversation["data"]
        data["conversations"] = {"files": len(c["files"]), "sessions": len(c["sessions"]), "subagents": len(c["subagents"]),
                                 "forks": len(c["forks"]), "issues": len(c["issues"]), "successes": len(c["successes"]),
                                 "commits": len(c["achievements"]["commits"])}
        spec["sources"].append({"path": "fable/CONTEXT.md", "role": "history"})
        opening = [i["opening"] for i in c["intent"]][:3]
        report += ("\n## Conversations\n\n"
                   f"Read {len(c['files'])} log file(s): {len(c['sessions'])} session(s), {len(c['subagents'])} subagent(s), "
                   f"{len(c['forks'])} fork(s), {len(c['issues'])} issue(s), {len(c['successes'])} success(es), "
                   f"{len(c['achievements']['commits'])} commit(s). The context document is `fable/CONTEXT.md`; it counts as a "
                   "history and state source above. Read its Issues and Forks sections before the interview: a fork is "
                   "where someone changed their mind, and that is usually a decision to record.\n")
        if opening:
            report += "\nWhat the sessions set out to do:\n\n" + "\n".join(f"- {o}" for o in opening) + "\n"
    if not args.no_write:
        (project / "fable").mkdir(exist_ok=True)
        (project / "fable" / "PREFLIGHT.md").write_text(report, encoding="utf-8")
        (project / "fable" / "preflight.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        # Never overwrite a spec someone has been completing.
        spec_name = "handoff_spec.json" if not (project / "fable" / "handoff_spec.json").exists() else "handoff_spec.preflight.json"
        (project / "fable" / spec_name).write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        data["spec_written"] = f"fable/{spec_name}"
        report += (f"\nA draft structured spec is in `fable/{spec_name}`. Complete it, check it with "
                   "`spec_tool.py check`, query it with jq (`include \"handoff\"; problems`), "
                   "then write the package with `render_handoff.py`.\n")
    print(json.dumps(data, indent=2) if args.json else report)
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
