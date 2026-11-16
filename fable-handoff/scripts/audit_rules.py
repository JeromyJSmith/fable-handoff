#!/usr/bin/env python3
"""Find instruction lines that will hurt an unattended Fable 5.2 run.

Fable 5.2 applies instructions almost literally, so a line that was harmless
for an older model or for interactive use can stall a run that nobody is
watching. This script scans every instructions file a session in the project
would load and reports the lines to rewrite (FIX) and the lines to judge
(REVIEW), each with the reason and what to write instead.

Scanned: CLAUDE.md, CLAUDE.local.md and AGENTS.md at any depth, Markdown under
any .claude/ directory, and whatever --extra names. Lines inside fenced code
blocks are ignored. A line that says it applies "in interactive sessions" is
not reported for asking or waiting for a person.

Example:
    python3 audit_rules.py --project ~/code/shop --extra /path/to/global-instructions.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

INSTRUCTION_FILES = {"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md"}
# Never scanned: version control, dependencies, virtual environments, caches.
SKIP_ALWAYS = {".git", "node_modules", ".venv", "venv", "site-packages", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache"}
# Build output is skipped too, except inside .claude/, where "build" or "dist"
# may be the name of a skill or command.
SKIP_BUILD = {"build", "dist", "out", "target", ".next", ".nuxt", "coverage", "vendor"}
# Agents installed by this skill. They are written for unattended runs already.
OWN_AGENTS = {"fable-scout.md", "fable-builder.md", "fable-worker.md", "fable-specialist.md"}

PEOPLE = r"(?:me|us|the user|the owner|the human|a human|the team|the developer|your manager|someone)"
APPROVAL = r"(?:approv\w+|sign(?:ed|s)?[- ]?off|go[- ]ahead|permission|confirmation|consent)"

# Each rule: id, severity, patterns, why it matters, what to write instead.
RULES = [
    {
        "id": "think-less",
        "severity": "FIX",
        "patterns": [
            r"\banswer (?:directly|immediately|right away|without thinking)\b",
            r"\b(?:don'?t|do not|avoid|never|no need to|without) (?:overthink\w*|over-think\w*|overanaly[sz]\w*|deliberat\w+)",
            r"\b(?:think|reason|deliberate) (?:less|briefly|quickly|as little)\b",
            r"\b(?:skip|minimi[sz]e|limit|keep) (?:the |your )?(?:thinking|reasoning|deliberation)\b",
            r"\bno (?:extended |long |deep )?(?:thinking|deliberation)\b",
        ],
        "why": "Fable 5.2 thinks at medium effort and above whatever the prompt says, so this line does nothing during the run. If it was meant to keep replies short, it does not say so.",
        "fix": "Delete the line. If you want short replies, ask for that directly, for example \"Keep replies to a few sentences unless detail is requested.\" How much the model thinks is set by `effort` in fable/handoff.json.",
    },
    {
        "id": "reasoning-out",
        "severity": "FIX",
        "patterns": [
            r"\b(?:think|reason|work|proceed|go|walk)\w*\b(?: \w+){0,3} step[- ]by[- ]step\b",
            r"\bstep[- ]by[- ]step (?:reasoning|thinking|analysis|explanation)\b",
            r"\b(?:explain|show|share|write out|write down|describe|output|print|reveal|include|document|narrate|walk (?:me |us )?through) (?:all (?:of )?)?(?:your|the|its|their) (?:\w+ ){0,2}(?:reasoning|thinking|thought process|thoughts|chain of thought)\b",
            r"\bchain[- ]of[- ]thought\b",
            r"\bthink(?:ing)? (?:out loud|aloud)\b",
            r"\bshow your work\b",
        ],
        "why": "A request to reproduce the model's internal reasoning in its reply can be declined by a safety classifier. In an unattended run a refusal costs a turn or stalls the work.",
        "fix": "Ask for evidence instead of reasoning, for example \"For each result, give the command you ran, what it returned, and any assumption you made.\"",
    },
    {
        "id": "needs-human",
        "severity": "FIX",
        "patterns": [
            r"\bwait(?:ing|s)? (?:for|until|on) (?:\w+ ){0,3}(?:%s|review|feedback|response|reply|answer|input|instructions?)\b" % APPROVAL,
            r"\b(?:until|unless|before)\b[^.;\n]{0,80}\b(?:signed off|confirmed by|reviewed by|okayed|greenlit)\b",
            r"\b(?:until|unless|before|without)\b[^.;\n]{0,60}\b%s\b" % APPROVAL,
            r"\b(?:stop|pause|halt) (?:and|to|then) (?:ask|wait|check in|confirm|get)\b",
            r"\bask (?:%s |first |for (?:permission|approval|confirmation) )?before\b" % PEOPLE,
            r"\b(?:get|obtain|seek|request|requires?|needs?|needing|pending|subject to) (?:\w+ ){0,3}%s\b" % APPROVAL,
            r"\b(?:confirm|check|verify) with %s (?:before|first|prior)\b" % PEOPLE,
            r"\bask (?:for )?(?:permission|approval)\b",
        ],
        "why": "Nobody can approve anything during an unattended run. Fable 5.2 follows a rule like this to the letter, so it holds back the work behind it or stops and waits for a reply that never comes.",
        "fix": "Decide now. Make the action pre-approved by name (\"You may run the migrations against the local database\"), forbid it by name with the reason, or tell the model to skip it and record it for the owner. If the rule is only meant for interactive sessions, say so in the rule: \"In interactive sessions, ...\".",
    },
    {
        "id": "absolute",
        "severity": "REVIEW",
        "patterns": [
            r"\b(?:never|always|must not|mustn'?t|under no circumstances?|at all times|without exception|no exceptions?|in all cases|in every case)\b",
        ],
        "why": "Fable 5.2 treats an absolute as absolute, including in cases its author did not have in mind. A broad one can hold back routine work.",
        "fix": "Keep it if it truly has no exceptions, and consider enforcing it with `protected_paths` or `blocked_bash_patterns` in fable/handoff.json. Otherwise give the reason and write the exceptions out, for example \"Do not edit generated files under api/gen/, because they are overwritten on build. Edit the templates instead.\"",
    },
    {
        "id": "delegation",
        "severity": "REVIEW",
        "patterns": [
            r"\b(?:use|using|spawn\w*|launch\w*|dispatch\w*|start|run|invoke|spin up|fan out(?: to)?|parallelize (?:\w+ )?with)\b(?: \w+){0,3} (?:sub-?agents?\b|(?:parallel|multiple|background|separate|several|specialized|specialised|dedicated) (?:sub-?)?agents?\b|the (?:task|agent) tool\b)",
            r"\bdelegate\b(?: \w+){0,4} to\b(?: \w+){0,3} (?:sub-?)?agents?\b",
        ],
        "why": "Where a prompt invites delegation, Fable 5.2 delegates readily, and subagents can become a large part of what a run costs.",
        "fix": "Remove the standing order, or say when a subagent is worth it, for example \"Use a subagent only for broad searches or for independent, fully specified build tasks.\" Pin a cheaper model on each project subagent.",
    },
    {
        "id": "style-cap",
        "severity": "REVIEW",
        "patterns": [
            r"\b(?:under|below|fewer than|less than|no more than|not more than|at most|maximum(?: of)?|max(?: of)?|up to|within|limit(?:ed)? to|keep (?:\w+ ){0,3}to|not exceed|shorter than|no longer than)\s*\d+\s*(?:words?|sentences?|lines?|characters?|chars?|paragraphs?|bullets?)\b",
            r"\b\d+[- ](?:words?|sentences?|lines?|characters?|chars?) (?:limit|max(?:imum)?|cap|or (?:less|fewer))\b",
            r"\b(?:one|two|three|a single|single)[- ](?:sentence|line|paragraph|word)s? (?:answers?|repl(?:y|ies)|responses?|summar(?:y|ies)|max(?:imum)?|only|limit)\b",
        ],
        "why": "Fable 5.2 keeps to hard style limits closely, which makes prose choppy. During a run the limit also applies to the final report, where it can squeeze out what the owner needs to read.",
        "fix": "If the limit is about code, keep it. If it is about prose, describe the reader and the purpose instead of a number (\"short enough to read in a minute\"), or scope it: \"In chat replies, ...\".",
    },
    {
        "id": "token-budget",
        "severity": "REVIEW",
        "patterns": [
            r"\btoken budget\b",
            r"\bbudget of [\d,._]+\s*k?\s*tokens?\b",
            r"\b[\d,._]+\s*k?\s*tokens? (?:budget|limit|cap|remaining|left|available|to spend)\b",
            r"\b(?:you have|limit(?:ed)? (?:of|to)|max(?:imum)?(?: of)?|at most|up to|within|under|spend) [\d,._]+\s*k?\s*tokens?\b",
        ],
        "why": "A token budget shown to the model changes how much it spends. In Anthropic's testing, removing a large one lowered cost with equal results.",
        "fix": "Delete the line. Cap spending outside the prompt with `max_budget_usd` in fable/handoff.json.",
    },
    {
        "id": "vague-autonomy",
        "severity": "REVIEW",
        "patterns": [
            r"\bbe (?:more |very |extremely )?(?:proactive|autonomous|independent|decisive|bold|self-directed)\b",
            r"\buse (?:your |your own |good |sound )?(?:best |own |good )?(?:judge?ment|discretion)\b",
            r"\bact (?:more )?(?:freely|autonomously|independently)\b",
            r"\btake (?:the )?initiative\b",
            r"\bdo what(?:ever)? (?:you think|you feel|seems|is) (?:is )?(?:best|right|necessary|needed)\b",
            r"\bas you see fit\b",
        ],
        "why": "This is too vague to change what Fable 5.2 does. It acts on named permissions and reads a general invitation narrowly.",
        "fix": "Name the steps that need no approval, for example \"You may create branches, run tests and edit files under src/ without asking.\"",
    },
    {
        "id": "answer-is-done",
        "severity": "REVIEW",
        "patterns": [
            r"\btreat (?:that|the|this|your|an|each|every|any) (?:\w+ )?(?:answer|response|reply|conclusion) as (?:done|final|complete|settled|finished)\b",
            r"\b(?:do not|don'?t|never|avoid) (?:revisit\w*|second[- ]guess\w*|re-?examin\w+|reconsider\w*|re-?open\w*) (?:your |an? |the |any )?(?:\w+ )?(?:answers?|responses?|conclusions?|decisions?)\b",
            r"\bonce (?:you(?:'ve| have)? )?answered,? (?:you are |you're |it is |it's |consider it )?(?:done|finished|final)\b",
        ],
        "why": "Lines like this were advice for an older model. With Fable 5.2 they reduce thinking on follow-ups and make it far less likely to point out its own earlier mistakes.",
        "fix": "Delete the line.",
    },
    {
        "id": "asks-human",
        "severity": "REVIEW",
        "patterns": [
            r"\bask %s\b" % PEOPLE,
            r"\b(?:check|check in|confirm|verify|clarify|consult|follow up|raise (?:it|this|them)) with %s\b" % PEOPLE,
            r"\b(?:when|if) (?:in doubt|unsure|uncertain|unclear|anything is unclear|something is unclear)[, ]+(?:ask|check|confirm|stop)\b",
            r"\bask (?:for )?clarif\w+",
            r"\bask (?:a |any |clarifying |follow[- ]up )?questions?\b",
        ],
        "why": "Nobody can answer during an unattended run. A question ends the turn, or the model carries on without the answer it was told to get.",
        "fix": "Answer the likely questions now in fable/DECISIONS.md and give a default for the rest, for example \"When something is unclear, choose the option that is easiest to undo and record it.\" If the rule is for interactive sessions, say so in the rule.",
    },
]

# A line that limits itself to interactive sessions is not a problem for an
# unattended run, so the two "needs a person" rules skip it.
INTERACTIVE_ONLY = re.compile(
    r"\b(?:in|during|for) (?:an? |all )?interactive (?:sessions?|use|work|mode|chats?)\b|\bwhen (?:working |used |running )?interactive(?:ly)?\b",
    re.IGNORECASE,
)
PERSON_RULES = {"needs-human", "asks-human"}

for _rule in RULES:
    _rule["compiled"] = [re.compile(pattern, re.IGNORECASE) for pattern in _rule["patterns"]]


def find_files(project, extras):
    """Instruction files to scan, in a stable order, as absolute paths."""
    found = []
    for root, dirs, files in os.walk(project):
        relative = Path(root).relative_to(project)
        inside_claude = ".claude" in relative.parts
        skip = SKIP_ALWAYS if inside_claude else SKIP_ALWAYS | SKIP_BUILD
        dirs[:] = sorted(d for d in dirs if d not in skip and not (relative == Path(".") and d == "fable"))
        for name in sorted(files):
            if inside_claude:
                wanted = name.endswith(".md") and not (Path(root).name == "agents" and name in OWN_AGENTS)
            else:
                wanted = name in INSTRUCTION_FILES
            if wanted:
                found.append(Path(root) / name)
    for extra in extras:
        path = Path(extra).expanduser().resolve()
        if path.is_dir():
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_ALWAYS)
                found += [Path(root) / name for name in sorted(files) if name.endswith(".md")]
        elif path.is_file():
            found.append(path)
        else:
            sys.stderr.write("audit_rules: --extra path %s does not exist and was skipped.\n" % extra)
    unique = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return unique


def display_name(path, project):
    try:
        return path.relative_to(project).as_posix()
    except ValueError:
        return str(path)


def scan_file(path, name, accepted):
    findings = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        sys.stderr.write("audit_rules: could not read %s (%s).\n" % (path, error))
        return findings
    in_fence = False
    for number, line in enumerate(lines, start=1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip():
            continue
        for rule in RULES:
            if rule["id"] in PERSON_RULES and INTERACTIVE_ONLY.search(line):
                continue
            match = next((m for m in (regex.search(line) for regex in rule["compiled"]) if m), None)
            if match:
                text = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line.strip())  # drop the list marker
                findings.append({
                    "file": name,
                    "line": number,
                    "rule": rule["id"],
                    "severity": rule["severity"],
                    "match": match.group(0),
                    "text": text if len(text) <= 200 else text[:197] + "...",
                    "why": rule["why"],
                    "fix": rule["fix"],
                    "accepted": "%s:%s" % (name, rule["id"]) in accepted,
                })
    return findings


def load_accepted(project):
    try:
        config = json.loads((project / "fable" / "handoff.json").read_text(encoding="utf-8"))
        accepted = config.get("audit_accept", [])
    except (OSError, ValueError, AttributeError):
        return set()
    return set(accepted) if isinstance(accepted, list) else set()


def render_markdown(files, findings):
    open_fix = [f for f in findings if f["severity"] == "FIX" and not f["accepted"]]
    open_review = [f for f in findings if f["severity"] == "REVIEW" and not f["accepted"]]
    accepted = [f for f in findings if f["accepted"]]
    lines = [
        "# Rules audit",
        "",
        "Scanned %d instructions file(s). %d line(s) to fix, %d to review, %d accepted."
        % (len(files), len(open_fix), len(open_review), len(accepted)),
        "",
    ]

    def section(title, intro, items):
        if not items:
            return
        lines.extend(["## " + title, "", intro, ""])
        for f in items:
            lines.append("- `%s:%d` [%s] %s" % (f["file"], f["line"], f["rule"], f["text"]))
            lines.append("  - Why: " + f["why"])
            lines.append("  - Write instead: " + f["fix"])
        lines.append("")

    section("Fix before launch", "Each of these stalls or derails an unattended run. Rewrite the line, or scope it to interactive sessions. The readiness check fails while one is left.", open_fix)
    section("Review", "Each of these may be fine. Read the line and decide. To keep one as it is, add \"<file>:<rule>\" to `audit_accept` in fable/handoff.json.", open_review)
    section("Accepted", "Listed in `audit_accept`, so they do not count against readiness.", accepted)
    if not findings:
        lines.extend(["No findings.", ""])
    lines.append("## Files scanned")
    lines.append("")
    lines.extend("- `%s`" % name for name in files)
    if not files:
        lines.append("None found.")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Find instruction lines (in CLAUDE.md, AGENTS.md and .claude/ Markdown) that will stall or derail an unattended Fable 5.2 run.",
        epilog="FIX findings must be rewritten or scoped before launch. REVIEW findings need a decision: rewrite, or accept by adding \"<file>:<rule>\" to audit_accept in fable/handoff.json.",
    )
    parser.add_argument("--project", required=True, help="path to the project root")
    parser.add_argument("--extra", nargs="+", default=[], metavar="PATH", help="more files or directories to scan, such as instructions or memory files outside the project that every session loads")
    parser.add_argument("--json", action="store_true", help="print {\"files\": [...], \"findings\": [...]} instead of Markdown")
    parser.add_argument("--out", metavar="FILE", help="also write the Markdown report to FILE")
    parser.add_argument("--strict", action="store_true", help="exit 1 when a FIX finding is not accepted")
    args = parser.parse_args()

    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        sys.stderr.write("audit_rules: %s is not a directory. Pass the project root with --project.\n" % project)
        return 2

    accepted = load_accepted(project)
    paths = find_files(project, args.extra)
    names = [display_name(path, project) for path in paths]
    findings = []
    for path, name in zip(paths, names):
        findings += scan_file(path, name, accepted)

    markdown = render_markdown(names, findings)
    if args.out:
        Path(args.out).expanduser().write_text(markdown, encoding="utf-8")
    if args.json:
        print(json.dumps({"files": names, "findings": findings}, indent=2))
    else:
        sys.stdout.write(markdown)

    unaccepted_fix = any(f["severity"] == "FIX" and not f["accepted"] for f in findings)
    return 1 if args.strict and unaccepted_fix else 0


if __name__ == "__main__":
    sys.exit(main())
