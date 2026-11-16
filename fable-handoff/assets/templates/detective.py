#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""The detective standard: cases, registered functions, strength of evidence and verdicts.

A detective pass is not a slogan. Every investigation is a case:

- the subject (a class, layer, budget line, term, fee, setting, file, function);
- the question (where does it go, what is it, what is its value);
- the candidate answers;
- the evidence: each item from a registered detective function, naming the
  underlying source it read, its strength, and the candidate it supports;
- the verdict, computed by the rules below, never chosen by hand;
- the record: fable/cases.json and fable/CASES.md.

Functions are described before they are used: "detective_functions" in
fable/handoff.json names each one, what it looks at, what it returns, how
strong its evidence is, whether it is built or planned, and its test.
Evidence from an unregistered function is refused.

Strength, from weakest: lead < supporting < strong < decisive. A lead (gap
analysis) points where to look and never counts toward a verdict.

Verdict rules:
- conflict: decisive sources disagree. The rules themselves conflict, so it
  is the owner's call which wins: open, policy.
- settled: a decisive source and no decisive source against it; or two
  INDEPENDENT strong sources that agree (different underlying sources, not two
  functions reading the same label) and no strong source against them.
- likely: strong but single, or contradicted only by supporting evidence. An
  adjudicator may settle it with a written confidence at or above the
  calibrated threshold; the verdict is then "settled by adjudication", kept
  apart from settled by evidence.
- open, fact: the evidence is missing or strong sources disagree. The case
  names what would settle it and goes back to the queue.
- open, policy: only for the firm's or owner's choice. It goes to the question
  system with the full case, and the work continues.

No verdict rests on leads alone or on one weak source. A quantity counts as
strong only when it agrees within the tolerance in "quantity_tolerance", after
unit conversion.

    uv run --script fable/detective.py verdicts          # recompute every case, write fable/CASES.md
    uv run --script fable/detective.py show <case id>
    uv run --script fable/detective.py functions         # the registry
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

STRENGTH = {"lead": 0, "supporting": 1, "strong": 2, "decisive": 3}
DEFAULT_THRESHOLD = 0.70

# Generic examples only. Every project must replace them with its own
# functions, derived from analysing that project (see
# references/detective-standard.md, section 7). The readiness check refuses a
# registry that still holds a generic example, or a function whose
# project_sources name nothing that exists in the project.
DEFAULT_FUNCTIONS = [
    {"name": "name match", "looks_at": "the normalized name against the project's vocabulary, terms and aliases",
     "returns": "candidates whose name or alias matches", "strength": "strong", "weak_when": "only a single common word matches", "status": "built", "test": "known names map to their class"},
    {"name": "content", "looks_at": "what the thing contains: object types, counts, sizes, fields, code paths",
     "returns": "candidates consistent with the content", "strength": "supporting", "status": "built", "test": "content profiles of decided cases"},
    {"name": "text in documents", "looks_at": "labels, callouts, titles, notes, comments and docs that name it",
     "returns": "candidates a label or title names", "strength": "strong", "weak_when": "the text only mentions it in passing", "status": "built", "test": "labelled examples"},
    {"name": "relationships", "looks_at": "nearness, containment, references and imports to things already placed",
     "returns": "candidates implied by what it sits inside or next to", "strength": "supporting", "strong_when": "contained in a titled section or detail", "status": "built", "test": "placed neighbours of decided cases"},
    {"name": "quantity match", "looks_at": "the project's budget, schedule or data: matching words and quantities that agree with what was measured",
     "returns": "candidates whose quantity agrees", "strength": "strong", "weak_when": "the quantity disagrees beyond the tolerance", "status": "built", "test": "quantities of decided cases within tolerance"},
    {"name": "rules and precedent", "looks_at": "the project's standards, the owner's rulings and recorded decisions",
     "returns": "the answer a rule or ruling gives", "strength": "decisive", "status": "built", "test": "rulings reproduce on their own cases"},
    {"name": "owner's own words", "looks_at": "notes, email, messages and memos the connectors and files reach",
     "returns": "what the owner said", "strength": "strong", "weak_when": "the remark is indirect", "status": "planned", "test": "quotes linked to decided cases"},
    {"name": "outside standards", "looks_at": "published standards, classifications, codes and references",
     "returns": "definitions and codes", "strength": "strong", "status": "built", "test": "known codes resolve"},
    {"name": "back-test", "looks_at": "earlier work: estimate or decide a past case from the others and compare with what happened",
     "returns": "parameters and answers that held up before", "strength": "decisive", "status": "planned", "test": "detective_backtest.py"},
    {"name": "gap analysis", "looks_at": "unconnected concept clusters across the project's text (InfraNodus or the built-in graph)",
     "returns": "leads to follow, never answers", "strength": "lead", "status": "built", "test": "gap_analysis.py"},
]


# --------------------------------------------------------------------------- config and registry

def project_root() -> Path:
    here = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "fable" / "handoff.json").exists():
            return candidate
    return here


def load_config(project: Path) -> dict:
    try:
        return json.loads((project / "fable" / "handoff.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def registry(config: dict) -> dict[str, dict]:
    functions = config.get("detective_functions")
    functions = functions if isinstance(functions, list) and functions else DEFAULT_FUNCTIONS
    return {f["name"]: f for f in functions if isinstance(f, dict) and f.get("name")}


for _f in DEFAULT_FUNCTIONS:
    _f["generic"] = True

EXTERNAL = ("connector:", "http://", "https://", "mcp:", "api:", "external:", "owner:")


def registry_problems(config: dict, project: Path | None = None) -> list[str]:
    """A function is described before it is used, and it is this project's own.

    With `project`, each function must name in `project_sources` the concrete
    places in this project it reads (paths or globs that match at least one
    file, or a connector or outside source written as "connector: ...",
    "https://...", "external: ..."), and no generic example may remain.
    """
    out = []
    for name, f in registry(config).items():
        if project is not None:
            if f.get("generic"):
                out.append("'%s' is still the generic example; analyse this project and replace it with a function of its own, or remove it" % name)
                continue
            sources = f.get("project_sources")
            if not isinstance(sources, list) or not [x for x in sources if str(x).strip()]:
                out.append("'%s' names no project_sources: the concrete files, data or systems in this project it reads" % name)
            else:
                for src in sources:
                    src = str(src).strip()
                    if src.lower().startswith(EXTERNAL):
                        continue
                    if not any(project.glob(src)) and not (project / src).exists():
                        out.append("'%s' reads %s, which matches nothing in this project" % (name, src))
        for key in ("looks_at", "returns", "strength", "status", "test"):
            if not str(f.get(key) or "").strip():
                out.append("detective function '%s' has no %s" % (name, key.replace("_", " ")))
        if f.get("strength") not in STRENGTH:
            out.append("detective function '%s' has strength %r; use lead, supporting, strong or decisive" % (name, f.get("strength")))
        if f.get("status") not in ("built", "planned"):
            out.append("detective function '%s' must be built or planned" % name)
    return out


def threshold(project: Path, config: dict) -> tuple[float, str]:
    """The adjudication threshold: calibrated by detective_backtest.py when it has run."""
    path = project / "fable" / "calibration.json"
    try:
        cal = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(cal.get("threshold"), (int, float)):
            return float(cal["threshold"]), "calibrated on %s against %s decided case(s)" % (cal.get("date", "?"), cal.get("cases", "?"))
    except (OSError, ValueError):
        pass
    value = config.get("adjudication_threshold", DEFAULT_THRESHOLD)
    return float(value), "uncalibrated: run detective_backtest.py on decided cases before trusting it"


# --------------------------------------------------------------------------- quantities

# Each unit: (dimension, factor to the base unit). Base units: m2, m, m3, each.
UNITS = {
    "sf": ("area", 0.09290304), "sqft": ("area", 0.09290304), "ft2": ("area", 0.09290304), "sq ft": ("area", 0.09290304),
    "sy": ("area", 0.83612736), "m2": ("area", 1.0), "sqm": ("area", 1.0), "ac": ("area", 4046.8564224), "acre": ("area", 4046.8564224),
    "lf": ("length", 0.3048), "ft": ("length", 0.3048), "in": ("length", 0.0254), "m": ("length", 1.0), "mm": ("length", 0.001), "yd": ("length", 0.9144),
    "cy": ("volume", 0.764554858), "yd3": ("volume", 0.764554858), "cf": ("volume", 0.0283168466), "ft3": ("volume", 0.0283168466), "m3": ("volume", 1.0),
    "ea": ("count", 1.0), "each": ("count", 1.0), "count": ("count", 1.0),
}


def quantity_agrees(q: dict, config: dict) -> tuple[bool, str]:
    """{measured, measured_unit, stated, stated_unit} -> (agrees, explanation)."""
    try:
        a, b = float(q["measured"]), float(q["stated"])
    except (KeyError, TypeError, ValueError):
        return False, "quantity incomplete"
    ua, ub = str(q.get("measured_unit", "")).lower().strip(), str(q.get("stated_unit", "")).lower().strip()
    if ua not in UNITS or ub not in UNITS:
        return False, "unknown unit %s or %s" % (ua or "?", ub or "?")
    (da, fa), (db, fb) = UNITS[ua], UNITS[ub]
    if da != db:
        return False, "%s and %s measure different things" % (ua, ub)
    tolerances = config.get("quantity_tolerance") or {}
    pct = float(tolerances.get(da, tolerances.get("default_pct", 2.0)))
    base_a, base_b = a * fa, b * fb
    if base_a == base_b == 0:
        return True, "both zero"
    off = abs(base_a - base_b) / max(abs(base_a), abs(base_b)) * 100
    return off <= pct, "%.4g %s against %.4g %s: %.2f%% apart, tolerance %.4g%%" % (a, ua, b, ub, off, pct)


# --------------------------------------------------------------------------- evidence and verdicts

def effective_strength(item: dict, config: dict) -> tuple[int, str]:
    """The strength an item really carries, after the quantity check."""
    level = STRENGTH.get(item.get("strength"), STRENGTH.get(registry(config).get(item.get("function"), {}).get("strength"), 0))
    note = ""
    if isinstance(item.get("quantity"), dict):
        agrees, note = quantity_agrees(item["quantity"], config)
        if not agrees and level >= STRENGTH["strong"]:
            level, note = STRENGTH["supporting"], note + "; counted as supporting"
    return level, note


def evidence_problems(case: dict, config: dict) -> list[str]:
    funcs = registry(config)
    out = []
    for i, item in enumerate(case.get("evidence") or []):
        name = item.get("function")
        if name not in funcs:
            out.append("evidence %d comes from '%s', which is not a registered detective function" % (i + 1, name))
        elif funcs[name].get("status") == "planned":
            out.append("evidence %d comes from '%s', which is only planned, not built" % (i + 1, name))
        if not str(item.get("source") or "").strip():
            out.append("evidence %d names no underlying source, so its independence cannot be judged" % (i + 1))
        if item.get("supports") and case.get("candidates") and item["supports"] not in case["candidates"]:
            out.append("evidence %d supports '%s', which is not one of the candidates" % (i + 1, item["supports"]))
    return out


def verdict(case: dict, config: dict, project: Path | None = None) -> dict:
    """Apply the verdict rules. Returns {verdict, answer, why, ...}."""
    problems = evidence_problems(case, config)
    if problems:
        return {"verdict": "invalid", "answer": None, "why": "; ".join(problems)}
    by_candidate: dict[str, dict[int, set]] = {}
    for item in case.get("evidence") or []:
        cand = item.get("supports")
        if not cand:
            continue
        level, _ = effective_strength(item, config)
        if level == STRENGTH["lead"]:
            continue  # leads never count
        by_candidate.setdefault(cand, {}).setdefault(level, set()).add(str(item["source"]).strip())

    def sources(cand, at_least):
        return set().union(*[s for lvl, s in by_candidate.get(cand, {}).items() if lvl >= at_least]) if by_candidate.get(cand) else set()

    decisive = [c for c in by_candidate if STRENGTH["decisive"] in by_candidate[c]]
    if len(decisive) > 1:
        return {"verdict": "open, policy", "answer": None,
                "why": "decisive sources disagree (%s): the rules themselves conflict, so the owner decides which applies" % ", ".join(sorted(decisive))}
    if decisive:
        return {"verdict": "settled", "answer": decisive[0], "why": "decisive source: %s" % ", ".join(sorted(by_candidate[decisive[0]][STRENGTH["decisive"]]))}

    strong = {c: sources(c, STRENGTH["strong"]) for c in by_candidate}
    strong = {c: s for c, s in strong.items() if s}
    if len(strong) > 1:
        return {"verdict": "open, fact", "answer": None,
                "why": "strong sources disagree (%s); more evidence is needed" % "; ".join("%s: %s" % (c, ", ".join(sorted(s))) for c, s in sorted(strong.items())),
                "would_settle": case.get("would_settle") or "a decisive source, or another independent strong source"}
    if strong:
        cand, srcs = next(iter(strong.items()))
        if len(srcs) >= 2:
            return {"verdict": "settled", "answer": cand, "why": "%d independent strong sources agree: %s" % (len(srcs), ", ".join(sorted(srcs)))}
        result = {"verdict": "likely", "answer": cand, "why": "one strong source (%s)%s" % (
            next(iter(srcs)), "; others only support" if any(c != cand for c in by_candidate) else "")}
        adj = case.get("adjudication")
        if isinstance(adj, dict) and adj.get("answer") == cand and isinstance(adj.get("confidence"), (int, float)):
            limit, basis = threshold(project or Path("."), config)
            result["threshold"] = {"value": limit, "basis": basis}
            if adj["confidence"] >= limit and str(adj.get("reasoning") or "").strip():
                result.update(verdict="settled by adjudication",
                              why=result["why"] + "; adjudicated by %s at %.2f (threshold %.2f, %s)" % (adj.get("by", "?"), adj["confidence"], limit, basis))
        return result
    if case.get("nature") in ("policy", "preference"):
        return {"verdict": "open, policy", "answer": None, "why": "no strong evidence, and it is a matter of %s" % case["nature"]}
    return {"verdict": "open, fact", "answer": None, "why": "the evidence is missing or only supports",
            "would_settle": case.get("would_settle") or "evidence from a strong or decisive function"}


# --------------------------------------------------------------------------- the case file

def cases_path(project: Path) -> Path:
    return project / "fable" / "cases.json"


def load_cases(project: Path) -> list[dict]:
    path = cases_path(project)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def save_cases(project: Path, cases: list[dict], config: dict) -> None:
    path = cases_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    lines = ["# Cases", "",
             "Every investigation, in plain words: what was asked, what each detective function found, and the verdict the rules give.", ""]
    for c in cases:
        v = c.get("result", {})
        lines += ["## %s" % (c.get("subject") or c.get("question")), "",
                  "- Question: %s" % c.get("question"),
                  "- Candidates: %s" % (", ".join(c.get("candidates") or []) or "none listed"),
                  "- Verdict: **%s**%s" % (v.get("verdict", "not computed"), (": " + str(v["answer"])) if v.get("answer") else ""),
                  "- Why: %s" % v.get("why", "")]
        if v.get("would_settle"):
            lines.append("- What would settle it: %s" % v["would_settle"])
        lines.append("- Evidence:")
        for item in c.get("evidence") or []:
            _, note = effective_strength(item, config)
            lines.append("  - %s found %s (%s, from %s%s)%s" % (
                item.get("function"), item.get("found") or "nothing", item.get("strength") or registry(config).get(item.get("function"), {}).get("strength", "?"),
                item.get("source"), ", " + item["link"] if item.get("link") else "",
                (" supports " + item["supports"]) if item.get("supports") else "") + ("; " + note if note else ""))
        lines.append("")
    (project / "fable" / "CASES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def recompute(project: Path, config: dict) -> list[dict]:
    cases = load_cases(project)
    for c in cases:
        c["result"] = verdict(c, config, project)
        c["result"]["computed"] = datetime.datetime.now().isoformat(timespec="seconds")
    save_cases(project, cases, config)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="The detective standard: cases, registered functions and verdicts.")
    parser.add_argument("command", choices=["verdicts", "show", "functions"])
    parser.add_argument("case_id", nargs="?")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve() if args.project else project_root()
    config = load_config(project)
    if args.command == "functions":
        problems = registry_problems(config, project)
        print(json.dumps({"functions": list(registry(config).values()), "problems": problems}, indent=2))
        return 1 if problems else 0
    if args.command == "show":
        case = next((c for c in load_cases(project) if c.get("id") == args.case_id), None)
        if case is None:
            sys.stderr.write("detective: no case %s in fable/cases.json\n" % args.case_id)
            return 2
        print(json.dumps({**case, "result": verdict(case, config, project)}, indent=2))
        return 0
    cases = recompute(project, config)
    counts = {}
    for c in cases:
        counts[c["result"]["verdict"]] = counts.get(c["result"]["verdict"], 0) + 1
    print(json.dumps(counts, indent=2) if args.json else ", ".join("%d %s" % (n, v) for v, n in sorted(counts.items())) or "no cases")
    return 1 if counts.get("invalid") else 0


if __name__ == "__main__":
    sys.exit(main())
