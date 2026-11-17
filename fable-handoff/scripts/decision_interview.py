#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Walk the owner through open decisions, one at a time, in plain words.

This needs no unattended run and launches nothing. Each open decision is
shown with what the thing is, why it matters, every option and what happens
if it is chosen, and a recommendation. Each answer is written to
fable/DECISIONS.md and to fable/handoff_spec.json (or fable/open_decisions.json
when the project has no spec), and the question is closed.

Only judgment calls reach the owner. Each question must pass the judgment
test in fable/questions.py: every rung of the evidence ladder searched and
recorded, and a matter of policy or preference, not of fact. Questions the
evidence settles are answered with --settle and recorded "by evidence".

Open decisions come from the project's question system when fable/handoff.json
names one, else from `open_questions` in fable/handoff_spec.json, else from
fable/open_decisions.json. Answers go to the project's decisions log
(decisions_log) when set, else fable/DECISIONS.md. Each needs: question, topic, what, why_it_matters,
options (two or more, each with choice and what_happens), recommendation and
recommendation_reason. The text may not lean on bare decision numbers or IDs
such as "D3", "Q-12" or "#4"; the owner should not have to look anything up.

    uv run --script scripts/decision_interview.py --project .            # ask, one at a time
    uv run --script scripts/decision_interview.py --project . --check    # are they written up well enough?
    uv run --script scripts/decision_interview.py --project . --list     # show them, ask nothing
    uv run --script scripts/decision_interview.py --project . --answers answers.json

answers.json maps each question (its exact text) to {"choice": "<an option's
choice or your own words>", "reason": "<optional>"}.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

REQUIRED = ["question", "topic", "what", "why_it_matters", "options", "recommendation", "recommendation_reason"]
# Codes like D3, Q-12 or AB-104, words like "decision 4", and "#4". A version
# such as v1.2 is not a code.
BARE_ID = re.compile(
    r"(?<![\w.])[A-Z]{1,3}-?\d{1,4}(?![\w.])|(?i:\b(?:decision|question|item|option|issue|ticket)\s*#?\d+\b)|(?<![\w&])#\d+\b"
)
LETTERS = "abcdefghij"


def questions_module(project: Path):
    """The project's fable/questions.py, or the skill's copy."""
    import importlib.util
    path = project / "fable" / "questions.py"
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "assets" / "templates" / "questions.py"
    spec = importlib.util.spec_from_file_location("fable_questions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SpecSource:
    """open_questions in fable/handoff_spec.json; answers become spec decisions."""

    def __init__(self, path: Path):
        self.path, self.doc = path, json.loads(path.read_text(encoding="utf-8"))
        self.label = "fable/handoff_spec.json"

    def open(self):
        return list(self.doc.get("open_questions", []))

    def answer(self, q, choice, full_reason, today):
        self.doc["open_questions"] = [x for x in self.doc.get("open_questions", []) if x.get("question") != q["question"]]
        self.doc.setdefault("decisions", []).append({"decision": decision_text(q, choice), "reason": full_reason, "source": "owner, decision interview, %s" % today})
        self.path.write_text(json.dumps(self.doc, indent=2) + "\n", encoding="utf-8")


class SystemSource:
    """The project's question system (fable/open_decisions.json by default)."""

    def __init__(self, project, config, qm):
        self.project, self.qm, self.store = project, qm, qm.system(project, config)
        spec = config.get("question_system") or qm.DEFAULT_SYSTEM
        self.label = spec.get("path") or "%s issues in %s" % (spec.get("type"), spec.get("repo"))
        self.records = self.store.load()

    def open(self):
        return [q for q in self.records if q.get("status", "open") == "open"]

    def answer(self, q, choice, full_reason, today):
        for r in self.records:
            if r is q or (r.get("question") == q.get("question") and r.get("topic") == q.get("topic")):
                r.update(status="imported", answer=choice, answer_reason=full_reason, answered=today)
        self.store.save(self.records)
        self.qm.resume_task(self.project, q.get("topic", ""), choice)


def pick_source(project: Path, config: dict, qm):
    spec = config.get("question_system")
    if spec and spec != qm.DEFAULT_SYSTEM:
        return SystemSource(project, config, qm)
    spec_path = project / "fable" / "handoff_spec.json"
    if spec_path.exists():
        return SpecSource(spec_path)
    return SystemSource(project, config, qm)


def problems(q: dict, qm=None, rungs=None) -> list[str]:
    """What keeps a question from going to the owner: the judgment test, then plain words."""
    out = qm.record_problems(q, rungs) if qm is not None else []
    if q.get("kind") == "evidence":
        return out
    out += ["missing %s" % key.replace("_", " ") for key in REQUIRED if not q.get(key)]
    options = q.get("options") or []
    if options and len(options) < 2:
        out.append("needs at least two options")
    for o in options:
        if not (isinstance(o, dict) and o.get("choice") and o.get("what_happens")):
            out.append("every option needs a choice and what happens if it is chosen")
            break
    if q.get("recommendation") and options and q["recommendation"] not in [o.get("choice") for o in options if isinstance(o, dict)]:
        out.append("the recommendation must be one of the options")
    texts = [q.get(k) or "" for k in REQUIRED if k != "options"] + [
        "%s %s" % (o.get("choice", ""), o.get("what_happens", "")) for o in options if isinstance(o, dict)]
    ids = sorted({m.group(0) for t in texts for m in BARE_ID.finditer(str(t))})
    if ids:
        out.append("uses bare numbers or IDs instead of words: %s" % ", ".join(ids))
    return out


def render(q: dict, remaining: int) -> str:
    lines = ["", "=" * 70, q["topic"], "=" * 70, "",
             "The question: " + q["question"], "",
             "What this is: " + q["what"], "",
             "Why it matters: " + q["why_it_matters"], "",
             "Your options:"]
    for letter, o in zip(LETTERS, q["options"]):
        mark = "  (recommended)" if o["choice"] == q["recommendation"] else ""
        lines.append("  %s) %s%s" % (letter, o["choice"], mark))
        lines.append("     If you choose this: " + o["what_happens"])
    lines += ["", "My recommendation: %s. %s" % (q["recommendation"], q["recommendation_reason"]), ""]
    lines.append("%s after this one." % ("No more decisions" if remaining == 0 else "%d more decision%s" % (remaining, "" if remaining == 1 else "s")))
    return "\n".join(lines)


def ask(q: dict, remaining: int):
    """Returns (decision, reason) or None to skip."""
    print(render(q, remaining))
    letters = LETTERS[: len(q["options"])]
    while True:
        try:
            raw = input('Answer with a letter (%s), "r" to take the recommendation, "s" to skip, or type your own decision: ' % ", ".join(letters)).strip()
        except EOFError:
            return None
        if not raw:
            continue
        low = raw.lower()
        if low == "s":
            return None
        if low == "r":
            return q["recommendation"], q["recommendation_reason"]
        if len(low) == 1 and low in letters:
            choice = q["options"][letters.index(low)]["choice"]
            default = q["recommendation_reason"] if choice == q["recommendation"] else "The owner's choice."
        else:
            choice, default = raw, "The owner's choice."
        try:
            reason = input("Why? Press Enter to use: %s\n> " % default).strip()
        except EOFError:
            reason = ""
        return choice, reason or default


def decision_text(q: dict, choice: str) -> str:
    return "%s: %s" % (q["topic"], choice)


def record(project: Path, config: dict, qm, source, q: dict, choice: str, reason: str) -> None:
    today = datetime.date.today().isoformat()
    match = next((o for o in q["options"] if o["choice"] == choice), None)
    full_reason = reason.rstrip(". ") + "." + (" What it means: " + match["what_happens"] if match else "")
    source.answer(q, choice, full_reason, today)
    log = qm.write_decision(project, config, "- %s. Reason: %s (owner, decision interview, %s)" % (decision_text(q, choice), full_reason, today))
    if log != project / "fable" / "DECISIONS.md":
        return
    # In fable/DECISIONS.md, rewrite the open questions section from what is still open.
    text = log.read_text(encoding="utf-8")
    heading = "## Open questions for the owner"
    still_open = [x.get("question") for x in source.open() if x.get("question")]
    listed = "\n".join("- " + x for x in still_open) if still_open else "None."
    if heading in text:
        head, tail = text.split(heading, 1)
        nxt = tail.find("\n## ")
        rest = "" if nxt < 0 else tail[nxt + 1 :]
        text = head + heading + "\n\n" + listed + "\n" + ("\n" + rest if rest else "")
    else:
        text = text.rstrip("\n") + "\n\n" + heading + "\n\n" + listed + "\n"
    log.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk the owner through open decisions one at a time, in plain words. Launches nothing.")
    parser.add_argument("--project", required=True, help="path to the project root")
    parser.add_argument("--check", action="store_true", help="report questions not yet written up well enough to ask; exit 1 if any")
    parser.add_argument("--list", action="store_true", help="show every open decision as it would be asked; ask nothing")
    parser.add_argument("--answers", metavar="FILE", help="take answers from a JSON file instead of asking")
    parser.add_argument("--file", metavar="PATH", help="read and answer the decisions in this JSON file (for example fable/owner_decisions.json, the decisions a preset asks before launch) instead of the question system")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--settle", action="store_true", help="answer the questions the evidence settles (kind \"evidence\" with an answer and its evidence), recorded as decisions by evidence")
    args = parser.parse_args()

    project = Path(args.project).expanduser().resolve()
    qm = questions_module(project)
    config = qm.load_config(project)
    if args.settle:
        return qm.cmd_settle(project, config)
    rungs = qm.rung_names(config)
    if args.file:
        source = SystemSource(project, dict(config, question_system={"type": "json", "path": args.file}), qm)
    else:
        source = pick_source(project, config, qm)
    questions = source.open()
    not_ready = [(q, problems(q, qm, rungs)) for q in questions if problems(q, qm, rungs)]
    ready = [q for q in questions if not problems(q, qm, rungs)]

    if args.check or args.json and not args.answers and not args.list:
        report = {"source": source.label, "open": len(questions), "ready": len(ready),
                  "needs_writing_up": [{"question": q.get("question"), "problems": p} for q, p in not_ready]}
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("%d open decision(s), %d ready to ask." % (len(questions), len(ready)))
            for item in report["needs_writing_up"]:
                print("- %s\n  %s" % (item["question"], "; ".join(item["problems"])))
        return 1 if not_ready else 0

    if args.list:
        for i, q in enumerate(ready):
            print(render(q, len(ready) - i - 1))
        for q, p in not_ready:
            print("\nNot ready to ask: %s (%s)" % (q.get("question"), "; ".join(p)))
        return 0

    answers = {}
    if args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    recorded, skipped = [], []
    for i, q in enumerate(ready):
        if args.answers:
            given = answers.get(q["question"])
            if not given:
                skipped.append(q["question"])
                continue
            choice = given.get("choice") or ""
            if choice.lower() in ("r", "recommendation"):
                choice = q["recommendation"]
            reason = given.get("reason") or (q["recommendation_reason"] if choice == q["recommendation"] else "The owner's choice.")
            result = (choice, reason)
        else:
            result = ask(q, len(ready) - i - 1)
        if result is None:
            skipped.append(q["question"])
            continue
        record(project, config, qm, source, q, *result)
        recorded.append({"question": q["question"], "decision": decision_text(q, result[0]), "reason": result[1]})
        if not args.answers:
            print("Recorded in %s and %s." % (qm.decisions_path(project, config).relative_to(project), source.label))
    summary = {"recorded": recorded, "skipped": skipped, "not_ready": [q.get("question") for q, _ in not_ready]}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("\n%d decision(s) recorded, %d skipped, %d not written up well enough to ask." % (len(recorded), len(skipped), len(not_ready)))
        for q, p in not_ready:
            print("- %s: %s" % (q.get("question"), "; ".join(p)))
    return 0 if not skipped and not not_ready else 1


if __name__ == "__main__":
    sys.exit(main())
