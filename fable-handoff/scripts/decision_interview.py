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

Open decisions come from `open_questions` in fable/handoff_spec.json, or from
fable/open_decisions.json. Each needs: question, topic, what, why_it_matters,
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


def load(project: Path):
    """(questions, where they came from, the whole document)."""
    for rel in ("fable/handoff_spec.json", "fable/open_decisions.json"):
        path = project / rel
        if path.exists():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as error:
                sys.exit("decision_interview: %s is not valid JSON (%s)." % (rel, error))
            questions = doc.get("open_questions", []) if isinstance(doc, dict) else []
            return questions, path, doc
    return [], None, None


def problems(q: dict) -> list[str]:
    """What keeps a question from being asked in plain words."""
    out = ["missing %s" % key.replace("_", " ") for key in REQUIRED if not q.get(key)]
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


def record(project: Path, source: Path, doc: dict, q: dict, choice: str, reason: str) -> None:
    today = datetime.date.today().isoformat()
    match = next((o for o in q["options"] if o["choice"] == choice), None)
    full_reason = reason.rstrip(". ") + "." + (" What it means: " + match["what_happens"] if match else "")
    # The spec, or the open decisions file.
    doc["open_questions"] = [x for x in doc.get("open_questions", []) if x.get("question") != q["question"]]
    if source.name == "handoff_spec.json":
        doc.setdefault("decisions", []).append({"decision": decision_text(q, choice), "reason": full_reason, "source": "owner, decision interview, %s" % today})
    else:
        doc.setdefault("answered", []).append({**q, "answer": choice, "reason": full_reason, "answered": today})
    source.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    # DECISIONS.md: add under "Made before the run", drop the line from the open questions.
    path = project / "fable" / "DECISIONS.md"
    text = path.read_text(encoding="utf-8") if path.exists() else "# Decisions\n\n## Made before the run\n\n## Open questions for the owner\n\nNone.\n"
    entry = "- %s. Reason: %s (owner, decision interview, %s)\n" % (decision_text(q, choice), full_reason, today)
    marker = "## Made before the run\n"
    if marker in text:
        head, tail = text.split(marker, 1)
        nxt = tail.find("\n## ")
        body, rest = (tail, "") if nxt < 0 else (tail[: nxt + 1], tail[nxt + 1 :])
        text = head + marker + body.rstrip("\n") + "\n" + entry + "\n" + rest
    else:
        text = text.rstrip("\n") + "\n\n" + marker + "\n" + entry
    # Rewrite the open questions section from what is still open.
    heading = "## Open questions for the owner"
    still_open = [x.get("question") for x in doc.get("open_questions", []) if x.get("question")]
    listed = "\n".join("- " + x for x in still_open) if still_open else "None."
    if heading in text:
        head, tail = text.split(heading, 1)
        nxt = tail.find("\n## ")
        rest = "" if nxt < 0 else tail[nxt + 1 :]
        text = head + heading + "\n\n" + listed + "\n" + ("\n" + rest if rest else "")
    else:
        text = text.rstrip("\n") + "\n\n" + heading + "\n\n" + listed + "\n"
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk the owner through open decisions one at a time, in plain words. Launches nothing.")
    parser.add_argument("--project", required=True, help="path to the project root")
    parser.add_argument("--check", action="store_true", help="report questions not yet written up well enough to ask; exit 1 if any")
    parser.add_argument("--list", action="store_true", help="show every open decision as it would be asked; ask nothing")
    parser.add_argument("--answers", metavar="FILE", help="take answers from a JSON file instead of asking")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args()

    project = Path(args.project).expanduser().resolve()
    questions, source, doc = load(project)
    if source is None:
        print("No open decisions: neither fable/handoff_spec.json nor fable/open_decisions.json exists.")
        return 0
    not_ready = [(q, problems(q)) for q in questions if problems(q)]
    ready = [q for q in questions if not problems(q)]

    if args.check or args.json and not args.answers and not args.list:
        report = {"source": str(source.relative_to(project)), "open": len(questions), "ready": len(ready),
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
        record(project, source, doc, q, *result)
        recorded.append({"question": q["question"], "decision": decision_text(q, result[0]), "reason": result[1]})
        if not args.answers:
            print("Recorded in fable/DECISIONS.md and %s." % source.relative_to(project))
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
