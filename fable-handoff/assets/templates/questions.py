#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Questions for the owner: the judgment test, parking, and the project's question system.

Most of what looks like a judgment call is detective work. A question may go
to the owner only when both hold:

  (a) the evidence cannot decide it: every rung of the evidence ladder in
      fable/handoff.json was searched, and what was found is recorded;
  (b) it is a matter of policy or preference, not a fact.

Each question carries a record: the evidence searched on every rung, what was
found, why that does not decide it, and what answer would settle it. A
question without that record is refused.

Commands (run from the project root):

    uv run --script fable/questions.py check                 # every open question passes the judgment test?
    uv run --script fable/questions.py park --record q.json --task "Task text from STATE.md"
    uv run --script fable/questions.py settle                # answer evidence questions, recorded "by evidence"
    uv run --script fable/questions.py import                # bring in the owner's answers, resume parked tasks
    uv run --script fable/questions.py status

Where questions live is set by "question_system" in fable/handoff.json:
    {"type": "json", "path": "fable/open_decisions.json"}      (default)
    {"type": "bcf", "path": "coordination/questions.bcf"}       BCF 3.0, one topic per question
    {"type": "markdown", "path": "docs/decisions.md"}          a table in the project's decisions file
    {"type": "github", "repo": "owner/name", "label": "fable-question"}   GitHub issues, through gh
Decisions go to "decisions_log" when set, else fable/DECISIONS.md.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

DEFAULT_LADDER = [
    {"rung": "project files and data", "look_in": "drawings, models, schedules, data files, code, labels and titles in the project"},
    {"rung": "specs and standards", "look_in": "the project's specifications, standards and design criteria"},
    {"rung": "past decisions and rulings", "look_in": "the decisions log, earlier answers, meeting notes with rulings"},
    {"rung": "owner notes and communications", "look_in": "notes, email and messages the connectors and files allow"},
    {"rung": "outside standards and references", "look_in": "codes, published standards, manufacturer data, references"},
    {"rung": "back-tests against earlier work", "look_in": "earlier projects or runs where the same question came up, checked against this one"},
]
DEFAULT_SYSTEM = {"type": "json", "path": "fable/open_decisions.json"}
NATURES = ("policy", "preference")
PARKED = re.compile(r"\(waiting on owner: ([^)]+)\)")
REQUIRED_TEXT = ["question", "topic", "why_not_decided", "would_settle"]


# --------------------------------------------------------------------------- config

def project_root(start: Path | None = None) -> Path:
    here = Path(start or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "fable" / "handoff.json").exists():
            return candidate
    return here


def load_config(project: Path) -> dict:
    try:
        return json.loads((project / "fable" / "handoff.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ladder(config: dict) -> list[dict]:
    rungs = config.get("evidence_ladder")
    return rungs if isinstance(rungs, list) and rungs else DEFAULT_LADDER


def rung_names(config: dict) -> list[str]:
    return [r["rung"] if isinstance(r, dict) else str(r) for r in ladder(config)]


# --------------------------------------------------------------------------- the judgment test

def record_problems(q: dict, rungs: list[str]) -> list[str]:
    """Why a question may not go to the owner. Empty when it passes the judgment test."""
    out = []
    if q.get("kind") == "evidence":
        return ["the evidence can settle this, so it is detective work: answer it from the evidence and record it as a decision by evidence"]
    if q.get("kind") != "judgment":
        out.append('kind must be "judgment" (or "evidence" when the evidence settles it)')
    if q.get("nature") not in NATURES:
        out.append("a question of fact is detective work; only policy or preference goes to the owner (set nature to policy or preference)")
    for key in REQUIRED_TEXT:
        if not str(q.get(key) or "").strip():
            out.append("missing %s" % key.replace("_", " "))
    searched = {}
    for item in q.get("evidence") or []:
        if isinstance(item, dict) and str(item.get("searched") or "").strip() and str(item.get("found") or "").strip():
            searched[str(item.get("rung"))] = item
    missing = [r for r in rungs if r not in searched]
    if missing:
        out.append("evidence not searched on: " + "; ".join(missing) + " (record what was searched and what was found on each rung, even when nothing was found)")
    return out


def evidence_problems(q: dict) -> list[str]:
    """For a question the evidence settles: is the answer recorded with its evidence?"""
    out = []
    if not str(q.get("answer") or "").strip():
        out.append("no answer recorded")
    if not [e for e in q.get("evidence") or [] if isinstance(e, dict) and str(e.get("found") or "").strip()]:
        out.append("no evidence recorded for the answer")
    return out


def record_id(q: dict) -> str:
    return q.get("id") or str(uuid.uuid5(uuid.NAMESPACE_URL, "fable-question:%s|%s" % (q.get("topic", ""), q.get("question", ""))))


# --------------------------------------------------------------------------- adapters

class JsonSystem:
    """fable/open_decisions.json: {"open_questions": [...], "answered": [...]}."""

    def __init__(self, project: Path, spec: dict):
        self.path = project / spec.get("path", DEFAULT_SYSTEM["path"])

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        out = [dict(q, status=q.get("status", "open")) for q in doc.get("open_questions", [])]
        out += [dict(q, status=q.get("status", "answered")) for q in doc.get("answered", [])]
        return out

    def save(self, records: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"open_questions": [q for q in records if q.get("status", "open") == "open"],
               "answered": [q for q in records if q.get("status", "open") != "open"]}
        self.path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


class MarkdownSystem:
    """A table under "## Questions for the owner" in the project's decisions file.

    Columns: Topic | Question | Status | Answer | Record. The owner answers by
    writing the answer and setting Status to answered. Record holds the full
    record as JSON; the rest of the file is left as it is.
    """

    HEADING = "## Questions for the owner"
    HEADER = "| Topic | Question | Status | Answer | Record |"

    def __init__(self, project: Path, spec: dict):
        self.path = project / spec["path"]

    @staticmethod
    def _cell(text: str) -> str:
        return str(text or "").replace("\n", " ").replace("|", "\\|")

    @staticmethod
    def _cells(line: str) -> list[str]:
        parts = re.split(r"(?<!\\)\|", line.strip().strip("|"))
        return [p.strip().replace("\\|", "|") for p in parts]

    def _split(self):
        text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        if self.HEADING not in text:
            return text.rstrip("\n") + ("\n\n" if text.strip() else ""), [], ""
        head, tail = text.split(self.HEADING, 1)
        lines = tail.split("\n")
        rows, i = [], 0
        while i < len(lines) and not lines[i].startswith("|"):
            if lines[i].startswith("## "):
                break
            i += 1
        while i < len(lines) and lines[i].startswith("|"):
            rows.append(lines[i])
            i += 1
        return head, rows, "\n".join(lines[i:])

    def load(self) -> list[dict]:
        _, rows, _ = self._split()
        out = []
        for row in rows[2:]:
            topic, question, status, answer, record = (self._cells(row) + [""] * 5)[:5]
            try:
                q = json.loads(record.strip("`")) if record else {}
            except ValueError:
                q = {}
            q.update(topic=topic, question=question, status=(status or "open").lower())
            if answer:
                q["answer"] = answer
            out.append(q)
        return out

    def save(self, records: list[dict]) -> None:
        head, _, rest = self._split()
        rows = [self.HEADER, "| --- | --- | --- | --- | --- |"]
        for q in records:
            record = {k: v for k, v in q.items() if k not in ("topic", "question", "status", "answer")}
            rows.append("| %s | %s | %s | %s | `%s` |" % (
                self._cell(q.get("topic")), self._cell(q.get("question")), self._cell(q.get("status", "open")),
                self._cell(q.get("answer", "")), self._cell(json.dumps(record, ensure_ascii=False))))
        body = self.HEADING + "\n\n" + "\n".join(rows) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(head + body + (rest if rest.startswith("\n") else "\n" + rest if rest else ""), encoding="utf-8")


class BcfSystem:
    """A BCF 3.0 file (.bcf zip): one topic per question.

    The record is written into the topic description, after a plain summary.
    The owner answers in any BCF tool by adding a comment and closing the
    topic; the last comment is taken as the answer.
    """

    CLOSED = {"closed", "resolved", "done", "answered"}

    def __init__(self, project: Path, spec: dict):
        self.path = project / spec["path"]

    @staticmethod
    def _description(q: dict) -> str:
        lines = [q.get("what") or q.get("question", ""), ""]
        if q.get("why_it_matters"):
            lines += ["Why it matters: " + q["why_it_matters"], ""]
        for o in q.get("options") or []:
            lines.append("Option: %s. If chosen: %s" % (o.get("choice"), o.get("what_happens")))
        if q.get("recommendation"):
            lines += ["Recommended: %s. %s" % (q["recommendation"], q.get("recommendation_reason", "")), ""]
        for e in q.get("evidence") or []:
            lines.append("Searched %s: %s. Found: %s" % (e.get("rung"), e.get("searched"), e.get("found")))
        lines += ["Why the evidence does not decide it: " + str(q.get("why_not_decided", "")),
                  "What would settle it: " + str(q.get("would_settle", "")), "",
                  "Record (for fable-handoff): " + json.dumps(q, ensure_ascii=False)]
        return "\n".join(lines)

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with zipfile.ZipFile(self.path) as bcf:
            for name in sorted(n for n in bcf.namelist() if n.endswith("/markup.bcf")):
                topic = ET.fromstring(bcf.read(name)).find("Topic")
                if topic is None:
                    continue
                description = topic.findtext("Description") or ""
                marker = "Record (for fable-handoff): "
                q = {}
                if marker in description:
                    try:
                        q = json.loads(description.split(marker, 1)[1].strip())
                    except ValueError:
                        q = {}
                q.setdefault("topic", topic.findtext("Title") or "")
                q["id"] = topic.get("Guid")
                status = (topic.get("TopicStatus") or "Open").lower()
                comments = topic.find("Comments")
                texts = [c.findtext("Comment") or "" for c in (comments.findall("Comment") if comments is not None else [])]
                if status in self.CLOSED:
                    q["status"] = "imported" if q.get("status") == "imported" else "answered"
                    if texts and not q.get("answer"):
                        q["answer"] = texts[-1].strip()
                else:
                    q["status"] = "open"
                out.append(q)
        return out

    def save(self, records: list[dict]) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        existing = {}
        if self.path.exists():
            with zipfile.ZipFile(self.path) as bcf:
                existing = {n: bcf.read(n) for n in bcf.namelist()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as bcf:
            bcf.writestr("bcf.version", '<?xml version="1.0" encoding="UTF-8"?>\n<Version VersionId="3.0"/>\n')
            bcf.writestr("extensions.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<Extensions><TopicTypes><TopicType>Question</TopicType></TopicTypes>'
                         '<TopicStatuses><TopicStatus>Open</TopicStatus><TopicStatus>Closed</TopicStatus></TopicStatuses>'
                         '<TopicLabels><TopicLabel>fable-handoff</TopicLabel><TopicLabel>policy</TopicLabel><TopicLabel>preference</TopicLabel></TopicLabels></Extensions>\n')
            written = set()
            for q in records:
                guid = record_id(q)
                q = dict(q, id=guid)
                name = "%s/markup.bcf" % guid
                old = ET.fromstring(existing[name]).find("Topic") if name in existing else None
                topic = ET.Element("Topic", Guid=guid, TopicType="Question",
                                   TopicStatus="Open" if q.get("status", "open") == "open" else "Closed")
                ET.SubElement(topic, "Title").text = q.get("topic", "")
                labels = ET.SubElement(topic, "Labels")
                for label in ("fable-handoff", q.get("nature")):
                    if label:
                        ET.SubElement(labels, "Label").text = label
                ET.SubElement(topic, "CreationDate").text = (old.findtext("CreationDate") if old is not None else None) or now
                ET.SubElement(topic, "CreationAuthor").text = "fable-handoff"
                ET.SubElement(topic, "Description").text = self._description(q)
                old_comments = old.find("Comments") if old is not None else None
                if old_comments is not None and len(old_comments):
                    topic.append(old_comments)
                elif q.get("answer"):
                    comments = ET.SubElement(topic, "Comments")
                    c = ET.SubElement(comments, "Comment", Guid=str(uuid.uuid4()))
                    ET.SubElement(c, "Date").text = now
                    ET.SubElement(c, "Author").text = "owner"
                    ET.SubElement(c, "Comment").text = q["answer"]
                markup = ET.Element("Markup")
                markup.append(topic)
                bcf.writestr(name, '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(markup, encoding="unicode"))
                written.add(guid)
            for n, data in existing.items():
                # Keep viewpoints and snapshots, and any topic this run did not write.
                if "/" not in n:
                    continue
                if not n.endswith("/markup.bcf") or n.split("/", 1)[0] not in written:
                    bcf.writestr(n, data)
        tmp.replace(self.path)


class GithubSystem:
    """GitHub issues with a label, through the gh CLI. The record is a fenced block in the issue body."""

    def __init__(self, project: Path, spec: dict):
        self.repo, self.label, self.project = spec["repo"], spec.get("label", "fable-question"), project

    def _gh(self, *args: str) -> str:
        return subprocess.run(["gh", *args, "--repo", self.repo], cwd=self.project, check=True, capture_output=True, text=True).stdout

    def load(self) -> list[dict]:
        issues = json.loads(self._gh("issue", "list", "--label", self.label, "--state", "all", "--limit", "500",
                                     "--json", "number,title,body,state,labels,comments") or "[]")
        out = []
        for issue in issues:
            match = re.search(r"```fable-question\n(.*?)\n```", issue.get("body") or "", re.S)
            q = json.loads(match.group(1)) if match else {"topic": issue["title"]}
            q["github_number"] = issue["number"]
            labels = {l.get("name") for l in issue.get("labels", [])}
            if str(issue.get("state", "")).upper() == "CLOSED":
                q["status"] = "imported" if "fable-imported" in labels else "answered"
                comments = issue.get("comments") or []
                if comments and not q.get("answer"):
                    q["answer"] = (comments[-1].get("body") or "").strip()
            else:
                q["status"] = "open"
            out.append(q)
        return out

    def save(self, records: list[dict]) -> None:
        current = {q.get("github_number"): q for q in self.load()}
        for q in records:
            number = q.get("github_number")
            body_record = {k: v for k, v in q.items() if k not in ("github_number", "status", "answer")}
            if number is None:
                body = BcfSystem._description(q).split("Record (for fable-handoff): ")[0]
                body += "\n```fable-question\n%s\n```\n" % json.dumps(body_record, indent=2, ensure_ascii=False)
                self._gh("issue", "create", "--title", q.get("topic", "Question"), "--label", self.label, "--body", body)
            elif q.get("status") == "imported" and current.get(number, {}).get("status") != "imported":
                self._gh("issue", "edit", str(number), "--add-label", "fable-imported")
            elif q.get("status") == "answered" and current.get(number, {}).get("status") == "open":
                self._gh("issue", "comment", str(number), "--body", q.get("answer", ""))
                self._gh("issue", "close", str(number))


ADAPTERS = {"json": JsonSystem, "markdown": MarkdownSystem, "bcf": BcfSystem, "github": GithubSystem}


def system(project: Path, config: dict | None = None):
    config = load_config(project) if config is None else config
    spec = config.get("question_system") or DEFAULT_SYSTEM
    return ADAPTERS[spec.get("type", "json")](project, spec)


# --------------------------------------------------------------------------- decisions and the ledger

def decisions_path(project: Path, config: dict) -> Path:
    return project / (config.get("decisions_log") or "fable/DECISIONS.md")


def write_decision(project: Path, config: dict, text: str, section: str = "## Made before the run") -> Path:
    path = decisions_path(project, config)
    current = path.read_text(encoding="utf-8") if path.exists() else "# Decisions\n"
    if section in current:
        head, tail = current.split(section, 1)
        nxt = tail.find("\n## ")
        body, rest = (tail, "") if nxt < 0 else (tail[: nxt + 1], tail[nxt + 1:])
        current = head + section + body.rstrip("\n") + "\n" + text + "\n" + ("\n" + rest if rest else "")
    else:
        current = current.rstrip("\n") + "\n" + text + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(current, encoding="utf-8")
    return path


def evidence_summary(q: dict) -> str:
    return "; ".join("%s: %s" % (e.get("rung"), e.get("found")) for e in q.get("evidence") or [] if isinstance(e, dict) and e.get("found"))


def log_evidence_decision(project: Path, q: dict) -> None:
    """fable/evidence_decisions.json: questions settled by evidence, for the review."""
    path = project / "fable" / "evidence_decisions.json"
    items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    items.append({"topic": q.get("topic"), "question": q.get("question"), "answer": q.get("answer"),
                  "evidence": q.get("evidence", []), "settled": datetime.date.today().isoformat()})
    path.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")


def park_task(project: Path, task: str, topic: str) -> bool:
    state = project / "fable" / "STATE.md"
    lines = state.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("- [ ] ") and line[6:].strip().startswith(task.strip()) and not PARKED.search(line):
            lines[i] = line.rstrip() + " (waiting on owner: %s)" % topic
            state.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    return False


def resume_task(project: Path, topic: str, answer: str) -> bool:
    state = project / "fable" / "STATE.md"
    if not state.exists():
        return False
    text = state.read_text(encoding="utf-8")
    marker = " (waiting on owner: %s)" % topic
    if marker not in text:
        return False
    state.write_text(text.replace(marker, " (owner answered %s: %s)" % (topic, answer)), encoding="utf-8")
    return True


def parked_tasks(state_text: str) -> list[tuple[str, str]]:
    out = []
    for line in state_text.splitlines():
        match = PARKED.search(line)
        if line.startswith("- [ ] ") and match:
            out.append((line[6:].strip(), match.group(1).strip()))
    return out


# --------------------------------------------------------------------------- commands

def cmd_check(project: Path, config: dict, as_json: bool) -> int:
    rungs = rung_names(config)
    bad = []
    for q in system(project, config).load():
        if q.get("status", "open") != "open":
            continue
        problems = record_problems(q, rungs) if q.get("kind") != "evidence" else evidence_problems(q) or ["settle it: run questions.py settle"]
        if problems:
            bad.append({"topic": q.get("topic"), "question": q.get("question"), "problems": problems})
    if as_json:
        print(json.dumps({"refused": bad}, indent=2))
    else:
        for b in bad:
            print("- %s: %s" % (b["question"], "; ".join(b["problems"])))
        print("%d open question(s) refused." % len(bad))
    return 1 if bad else 0


def cmd_park(project: Path, config: dict, record_file: str, task: str | None) -> int:
    q = json.loads(Path(record_file).read_text(encoding="utf-8"))
    problems = record_problems(q, rung_names(config))
    if problems:
        sys.stderr.write("questions: refused, the judgment test is not met:\n- " + "\n- ".join(problems) +
                         "\nKeep searching the evidence. If the evidence settles it, decide it and record it by evidence.\n")
        return 2
    q.update(status="open", parked=datetime.date.today().isoformat())
    if task:
        q["task"] = task
    store = system(project, config)
    records = store.load()
    records = [r for r in records if record_id(r) != record_id(q)] + [q]
    store.save(records)
    if task and not park_task(project, task, q["topic"]):
        sys.stderr.write("questions: parked the question, but no open task in fable/STATE.md starts with: %s\n" % task)
        return 1
    print("Parked: %s. Continue with tasks that do not depend on it." % q["topic"])
    return 0


def cmd_settle(project: Path, config: dict) -> int:
    store = system(project, config)
    records, settled, bad = store.load(), [], []
    for q in records:
        if q.get("status", "open") != "open" or q.get("kind") != "evidence":
            continue
        problems = evidence_problems(q)
        if problems:
            bad.append((q.get("question"), problems))
            continue
        write_decision(project, config, "- %s: %s. Reason: settled by evidence (%s)." % (q.get("topic"), q["answer"], evidence_summary(q)))
        log_evidence_decision(project, q)
        q["status"] = "imported"
        settled.append(q.get("topic"))
    store.save(records)
    for question, problems in bad:
        print("- not settled: %s (%s)" % (question, "; ".join(problems)))
    print("%d question(s) settled by evidence." % len(settled))
    return 1 if bad else 0


def cmd_import(project: Path, config: dict) -> int:
    store = system(project, config)
    records, brought = store.load(), []
    for q in records:
        if q.get("status") != "answered" or not str(q.get("answer") or "").strip():
            continue
        reason = q.get("answer_reason") or "the owner's answer"
        write_decision(project, config, "- %s: %s. Reason: %s (owner, answered in the question system)." % (q.get("topic"), q["answer"], reason))
        resume_task(project, q.get("topic", ""), q["answer"])
        q["status"] = "imported"
        brought.append(q.get("topic"))
    store.save(records)
    print("Imported %d answer(s)%s." % (len(brought), (": " + ", ".join(brought)) if brought else ""))
    return 0


def cmd_status(project: Path, config: dict) -> int:
    records = system(project, config).load()
    counts = {}
    for q in records:
        counts[q.get("status", "open")] = counts.get(q.get("status", "open"), 0) + 1
    print(json.dumps({"system": (config.get("question_system") or DEFAULT_SYSTEM), "counts": counts}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Questions for the owner: the judgment test, parking and the project's question system.")
    parser.add_argument("command", choices=["check", "park", "settle", "import", "status"])
    parser.add_argument("--project", help="project root (default: found from the current directory)")
    parser.add_argument("--record", help="park: a JSON file with the question record")
    parser.add_argument("--task", help="park: the start of the task line in fable/STATE.md that waits on this question")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve() if args.project else project_root()
    config = load_config(project)
    if args.command == "check":
        return cmd_check(project, config, args.json)
    if args.command == "park":
        if not args.record:
            parser.error("park needs --record")
        return cmd_park(project, config, args.record, args.task)
    if args.command == "settle":
        return cmd_settle(project, config)
    if args.command == "import":
        return cmd_import(project, config)
    return cmd_status(project, config)


if __name__ == "__main__":
    sys.exit(main())
