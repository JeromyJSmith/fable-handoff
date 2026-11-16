#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Prove the detective standard on cases the owner already decided.

Input: a JSON list of decided cases, each a normal case (question,
candidates, evidence from registered functions) plus:

- "owner_answer": what the owner actually decided;
- "ruling_sources": the sources that hold that ruling (the decision log line,
  the email, the rule). These are removed before the verdict is computed, so
  the test is blind: no function may "find" the very ruling it is tested on.
- "adjudication" (optional): an adjudicator's answer and confidence, to
  calibrate the threshold.

Output (fable/BACKTEST.md and fable/backtest.json):

- per function: how often the candidate it supported was the owner's answer;
- overall: how often the verdict reached the owner's answer, how often it
  settled wrongly, and how often it stayed open;
- every wrong verdict, with the evidence that led to it;
- adjudication calibration: accuracy by confidence band, and the lowest
  confidence at which adjudications were right at least --target of the time.
  With --write-calibration that threshold goes to fable/calibration.json,
  which the verdict rules then use instead of the uncalibrated default.

A function that is often wrong is weakened in the registry or fixed, never
trusted.

    uv run --script scripts/detective_backtest.py --project . --cases decided_cases.json
    uv run --script scripts/detective_backtest.py --project . --cases decided_cases.json --write-calibration
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import sys
from pathlib import Path


def load_detective(project: Path):
    path = project / "fable" / "detective.py"
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "assets" / "templates" / "detective.py"
    spec = importlib.util.spec_from_file_location("fable_detective", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def blind(case: dict) -> tuple[dict, int]:
    """The case without any evidence drawn from its own ruling."""
    ruling = {str(s).strip() for s in case.get("ruling_sources") or []}
    kept = [e for e in case.get("evidence") or [] if str(e.get("source") or "").strip() not in ruling]
    return dict(case, evidence=kept, adjudication=None), len(case.get("evidence") or []) - len(kept)


def calibrate(pairs: list[tuple[float, bool]], target: float) -> dict:
    bands = {}
    for conf, right in pairs:
        band = min(int(conf * 10), 9) / 10
        bands.setdefault(band, [0, 0])
        bands[band][0] += 1
        bands[band][1] += int(right)
    table = [{"from": b, "to": round(b + 0.1, 1), "n": n, "right": r, "accuracy": round(r / n, 3)} for b, (n, r) in sorted(bands.items())]
    threshold = None
    for cut in sorted({c for c, _ in pairs}):
        above = [right for c, right in pairs if c >= cut]
        if above and sum(above) / len(above) >= target:
            threshold = cut
            break
    return {"bands": table, "threshold": threshold, "target": target, "n": len(pairs)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the detective standard blind on decided cases and score it.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--cases", required=True, help="JSON list of decided cases")
    parser.add_argument("--target", type=float, default=0.9, help="accuracy an adjudication threshold must reach (default 0.9)")
    parser.add_argument("--write-calibration", action="store_true", help="write the calibrated threshold to fable/calibration.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    dm = load_detective(project)
    config = dm.load_config(project)
    decided = json.loads(Path(args.cases).read_text(encoding="utf-8"))

    per_function: dict[str, list[int]] = {}
    outcome = {"right": 0, "wrong": 0, "open": 0, "invalid": 0}
    wrong, removed_total, adjudications = [], 0, []
    for case in decided:
        truth = case.get("owner_answer")
        test, removed = blind(case)
        removed_total += removed
        for item in test["evidence"]:
            if item.get("supports"):
                per_function.setdefault(item.get("function"), [0, 0])
                per_function[item["function"]][0] += 1
                per_function[item["function"]][1] += int(item["supports"] == truth)
        result = dm.verdict(test, config, project)
        if result["verdict"] == "invalid":
            outcome["invalid"] += 1
            wrong.append({"case": case.get("id") or case.get("question"), "verdict": "invalid", "why": result["why"]})
        elif result.get("answer") is None or result["verdict"] in ("likely", "open, fact", "open, policy"):
            outcome["open"] += 1
        elif result["answer"] == truth:
            outcome["right"] += 1
        else:
            outcome["wrong"] += 1
            wrong.append({"case": case.get("id") or case.get("question"), "verdict": result["verdict"], "answer": result["answer"],
                          "owner_answer": truth, "why": result["why"]})
        adj = case.get("adjudication")
        if isinstance(adj, dict) and isinstance(adj.get("confidence"), (int, float)):
            adjudications.append((float(adj["confidence"]), adj.get("answer") == truth))

    functions = [{"function": f, "used": n, "right": r, "accuracy": round(r / n, 3) if n else None}
                 for f, (n, r) in sorted(per_function.items(), key=lambda kv: (kv[1][1] / kv[1][0]) if kv[1][0] else 0)]
    calibration = calibrate(adjudications, args.target) if adjudications else None
    report = {"date": datetime.date.today().isoformat(), "cases": len(decided), "outcome": outcome,
              "settled_accuracy": round(outcome["right"] / (outcome["right"] + outcome["wrong"]), 3) if outcome["right"] + outcome["wrong"] else None,
              "evidence_removed_as_the_cases_own_ruling": removed_total, "functions": functions, "wrong": wrong, "calibration": calibration}
    fable = project / "fable"
    fable.mkdir(exist_ok=True)
    (fable / "backtest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Detective back-test", "",
             "%d decided case(s), run blind: %d piece(s) of evidence drawn from each case's own ruling were removed first." % (len(decided), removed_total), "",
             "Verdicts: %d reached the owner's answer, %d settled on a different answer, %d stayed open, %d were invalid." % (
                 outcome["right"], outcome["wrong"], outcome["open"], outcome["invalid"]), "", "## Functions", "",
             "| Function | Used | Right | Accuracy |", "| --- | --- | --- | --- |"]
    lines += ["| %s | %d | %d | %s |" % (f["function"], f["used"], f["right"], f["accuracy"]) for f in functions]
    lines += ["", "A function that is often wrong is weakened in the registry or fixed, never trusted.", ""]
    if wrong:
        lines += ["## Where it went wrong", ""] + ["- %s: %s gave %s, the owner decided %s. %s" % (
            w["case"], w["verdict"], w.get("answer"), w.get("owner_answer"), w["why"]) for w in wrong] + [""]
    if calibration:
        lines += ["## Adjudication calibration", "", "| Confidence | Cases | Right | Accuracy |", "| --- | --- | --- | --- |"]
        lines += ["| %.1f to %.1f | %d | %d | %.3f |" % (b["from"], b["to"], b["n"], b["right"], b["accuracy"]) for b in calibration["bands"]]
        lines += ["", "Lowest confidence with at least %.0f%% right: %s." % (args.target * 100, calibration["threshold"] if calibration["threshold"] is not None else "none; do not let adjudication settle cases yet"), ""]
        if args.write_calibration and calibration["threshold"] is not None:
            (fable / "calibration.json").write_text(json.dumps({"threshold": calibration["threshold"], "target": args.target,
                                                                "cases": calibration["n"], "date": report["date"]}, indent=2) + "\n", encoding="utf-8")
            lines.append("Written to fable/calibration.json; the verdict rules now use it.")
    (fable / "BACKTEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2) if args.json else "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
