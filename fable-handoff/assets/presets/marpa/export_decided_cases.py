#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["duckdb==2.0.0", "pyyaml==6.0.3", "pydantic==2.14.3"]
# ///
"""Build the MARPA decided-case set for detective_backtest.py from MARPA's own data.

Read only. It imports the MARPA budget standard repository's detective.py and
jev_schema.py and opens its DuckDB database read-only, the same way MARPA's
own blind test does. It writes nothing in that repository.

Each of the owner's class rulings (class_rulings.yaml) becomes one decided
case. The evidence is what MARPA's detective functions find for that class,
with the owner's ruling included as decisive evidence and listed in
"ruling_sources", so detective_backtest.py removes it before the verdict (the
test is blind). The adjudication is Jev's answer under the class_slot schema
asked with the ruling left out of its evidence (MARPA's
detective_blind_jev__*.ndjson), marked "blind": true, with the options it
was offered, its companions, its post-check and its receipt.

It pins the same duckdb, pyyaml and pydantic versions as MARPA's pyproject.toml:

    uv run --script export_decided_cases.py --marpa <MARPA repo> --out decided_cases.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# MARPA's function ids -> the preset's function names.
FUNCTION_NAMES = {
    "name_match": "name match", "drawing_content": "drawing content", "drawing_text": "text on the drawing",
    "spatial": "spatial relationships", "budget_match": "budget match", "rules_precedent": "rules and precedent",
    "firm_words": "the firm's own words", "outside_standards": "outside standards", "backtest": "back-test",
    "gap_analysis": "gap analysis",
}
# MARPA has a "weak" rung below supporting. Neither can settle a case alone,
# so the skill's ladder reads it as supporting; the original is kept.
STRENGTHS = {"decisive": "decisive", "strong": "strong", "supporting": "supporting", "weak": "supporting", "lead": "lead"}


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--marpa", required=True, help="the MARPA budget standard repository (ontology-duckdb)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    root = Path(args.marpa).resolve()
    sys.path[:0] = [str(root), str(root / "vwx")]
    md = load(root / "detective.py", "marpa_detective")  # MARPA's own modules, read from its repository, read only
    jev_schema = load(root / "jev_schema.py", "marpa_jev_schema")
    name_key = md.name_key

    ctx = md.Context()
    out = []
    for (project, key), ruling in sorted(ctx.rulings.items()):
        cls = next((c for (pp, c) in ctx.classes if pp == project and name_key(c) == key), ruling["class"])
        truth = ctx.canon(ruling["slot"]) or md.NO_SLOT
        case = md.Case("decided:%s|%s" % (project, key), "class", project, cls, "Which slot pays for what this class draws?", truth=truth)
        evidence = md.rules_precedent(ctx, case, hide_own=False)
        for function in md.FUNCTIONS:
            evidence += function(ctx, case)
        items, ruling_sources = [], []
        for e in evidence:
            if e.candidate is None:
                continue
            items.append({"function": FUNCTION_NAMES[e.function], "found": e.detail, "strength": STRENGTHS[e.strength],
                          "marpa_strength": e.strength, "source": e.source, "supports": e.candidate})
            if e.source.startswith("ruling:"):
                ruling_sources.append(e.source)
        record = {"id": case.case_id, "project": project, "subject": cls, "question": case.question, "nature": "fact",
                  "owner_answer": truth, "ruling": ruling.get("ruling"), "ruling_sources": ruling_sources, "evidence": items}
        jev = ctx.jev_blind.get((project, key))
        if jev:
            answer = ctx.canon(jev["choice"]) or (md.NO_SLOT if jev["choice"] == "EXISTING" else jev["choice"])
            offered = sorted({ctx.canon(o) or (md.NO_SLOT if o == "EXISTING" else o) for o in jev.get("offered") or []})
            record["adjudication"] = {
                "by": "jev", "schema": "class_slot", "schema_hash": jev.get("schema_hash"), "model": jev.get("model"),
                "policy_version": jev.get("policy_version"), "answer": answer, "raw_choice": jev["choice"],
                "confidence": float(jev.get("confidence") or jev.get("p_max") or 0.0), "band": jev.get("band"),
                "offered": offered, "companions": jev.get("companions") or {},
                "post_checks": {"existing_is_never_proposed_work": jev_schema.existing_is_never_proposed_work(jev, {"drawn_class": cls})},
                "receipt": Path(jev["receipt"]).name if jev.get("receipt") else None,
                "reasoning": "Jev chose %s under the class_slot schema with the owner's ruling left out of its evidence" % jev["choice"],
                "blind": True}
        candidates = sorted({i["supports"] for i in items} | {truth} | ({record["adjudication"]["answer"]} if jev else set()))
        record["candidates"] = candidates
        out.append(record)
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("%d decided case(s), %d with a blind Jev answer, written to %s" % (len(out), sum(1 for r in out if "adjudication" in r), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
