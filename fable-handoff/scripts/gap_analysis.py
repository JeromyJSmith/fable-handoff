#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["networkx==3.7"]
# ///
"""Gap analysis and bridging: find concepts in the project that nothing connects.

Detective work often fails because two things that belong together are never
read side by side: a label in the drawings and a line item in the budget, a
rule in the spec and a column in the data. This builds a concept graph from
the project's specs, open questions, code comments and data descriptions,
then reports:

- disconnected components: groups of terms that share no sentence with the
  main body of the project's text;
- gaps between clusters: communities in the main graph with few links between
  them, each with a suggested bridge;
- weakly linked terms: frequent terms with almost no neighbours.

Every bridge is a lead to verify against the evidence, never a decision.
Record how each gap was closed with --close.

When the InfraNodus connector is available, run its content-gap analysis on
the same text (--corpus-out writes it) and add its gaps with --add, so both
methods end up in one record. See references/gap-analysis.md.

    uv run --script scripts/gap_analysis.py --project .
    uv run --script scripts/gap_analysis.py --project . --corpus-out fable/.run/gap_corpus.txt
    uv run --script scripts/gap_analysis.py --project . --add "drawing labels | budget lines" --lead "Do the labels match budget items?" --source infranodus
    uv run --script scripts/gap_analysis.py --project . --close gap-2 --how "Matched 40 of 41 labels to budget lines; the last one is an allowance."

Writes fable/gaps.json and fable/GAPS.md.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".pytest_cache", ".claude"}
DOC_SUFFIXES = {".md", ".txt", ".rst"}
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".sh", ".c", ".cpp", ".h", ".cs", ".swift", ".kt"}
DATA_SUFFIXES = {".csv", ".tsv"}
STOP = set("""a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her here
hers him his how i if in into is it its itself just me more most my no nor not now of off on once only or other our
ours out over own same she should so some such than that the their them then there these they this those through to too
under until up very was we were what when where which while who whom why will with would you your yours must may might
shall use used using one two three per via etc e.g i.e eg ie yes see each every new also file files line lines todo
fixme note make made like get set run runs""".split())
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n{2,}|\n[-*]\s")
COMMENT = re.compile(r"^\s*(?:#|//|/\*|\*|--)\s?(.*)$")


def collect(project: Path, limit_bytes: int = 400_000) -> list[tuple[str, str]]:
    """(source, text) pairs: documents, open questions, code comments and data descriptions."""
    out, total = [], 0
    for path in sorted(project.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(project).parts) or not path.is_file():
            continue
        rel = path.relative_to(project).as_posix()
        if rel.startswith("fable/") and path.name not in ("open_decisions.json",):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        suffix = path.suffix.lower()
        if suffix in DOC_SUFFIXES:
            piece = text
        elif suffix in CODE_SUFFIXES:
            piece = "\n".join(m.group(1) for m in map(COMMENT.match, text.splitlines()) if m and m.group(1).strip())
        elif suffix in DATA_SUFFIXES:
            header = text.splitlines()[0] if text else ""
            piece = "Data %s has columns: %s." % (path.stem, ", ".join(re.split(r"[,\t]", header)))
        elif path.name == "open_decisions.json" or path.name.endswith(".schema.json"):
            try:
                doc = json.loads(text)
            except ValueError:
                continue
            piece = "\n\n".join(str(v) for v in _strings(doc))
        else:
            continue
        if piece.strip():
            out.append((rel, piece))
            total += len(piece)
            if total > limit_bytes:
                break
    return out


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def norm(word: str) -> str | None:
    w = word.lower().strip("-_")
    if len(w) < 3 or w in STOP or w.isdigit():
        return None
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        w = w[:-1]
    return w


def build_graph(texts: list[tuple[str, str]], max_terms: int = 150):
    sentences = []
    for source, text in texts:
        for chunk in SENTENCE.split(text):
            terms = sorted({t for t in (norm(w) for w in WORD.findall(chunk)) if t})
            if terms:
                sentences.append((source, terms))
    freq = Counter(t for _, terms in sentences for t in terms)
    keep = {t for t, _ in freq.most_common(max_terms) if freq[t] >= 2}
    graph = nx.Graph()
    graph.add_nodes_from((t, {"freq": freq[t]}) for t in keep)
    for _, terms in sentences:
        kept = [t for t in terms if t in keep][:15]
        for a, b in combinations(kept, 2):
            weight = graph.get_edge_data(a, b, {"weight": 0})["weight"] + 1
            graph.add_edge(a, b, weight=weight)
    return graph, freq


def top_terms(graph, nodes, n=4):
    return sorted(nodes, key=lambda t: (-graph.degree(t, weight="weight"), -graph.nodes[t]["freq"], t))[:n]


def analyse(graph) -> list[dict]:
    gaps = []
    if graph.number_of_nodes() == 0:
        return gaps
    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    main = components[0]
    for comp in components[1:]:
        if len(comp) >= 2:
            terms = top_terms(graph, comp)
            gaps.append({"kind": "disconnected", "between": [", ".join(terms), ", ".join(top_terms(graph, main, 3))],
                         "lead": "Nothing in the project's text links %s to the rest. Look for the evidence that connects them, or confirm they are separate." % ", ".join(terms)})
    isolated = sorted((t for comp in components[1:] if len(comp) == 1 for t in comp), key=lambda t: -graph.nodes[t]["freq"])
    sub = graph.subgraph(main)
    if sub.number_of_nodes() >= 6:
        communities = [c for c in greedy_modularity_communities(sub, weight="weight") if len(c) >= 2]
        for a, b in combinations(range(len(communities)), 2):
            ca, cb = communities[a], communities[b]
            links = sum(d["weight"] for u, v, d in sub.edges(ca, data=True) if v in cb)
            density = links / (len(ca) * len(cb))
            if density < 0.05:
                ta, tb = top_terms(sub, ca, 3), top_terms(sub, cb, 3)
                gaps.append({"kind": "weak link between clusters", "between": [", ".join(ta), ", ".join(tb)],
                             "lead": "Bridge to check: does %s relate to %s? Find the document, label or data that ties them, or record that they are independent." % (ta[0], tb[0])})
    weak = [t for t in graph.nodes if graph.nodes[t]["freq"] >= 3 and graph.degree(t) <= 1] + isolated
    for term in weak[:10]:
        gaps.append({"kind": "weakly linked term", "between": [term, ""],
                     "lead": "'%s' is used often but appears with almost nothing else. Check what it refers to and where it belongs." % term})
    return gaps


def load_record(project: Path) -> dict:
    path = project / "fable" / "gaps.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"gaps": []}


def save_record(project: Path, record: dict) -> None:
    fable = project / "fable"
    fable.mkdir(exist_ok=True)
    (fable / "gaps.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    lines = ["# Gaps and bridges", "",
             "Each bridge is a lead to verify against the evidence, never a decision. Close a gap with the evidence that settled it.", ""]
    for g in record["gaps"]:
        state = "closed: " + g["how_closed"] if g.get("status") == "closed" else "open"
        lines.append("- **%s** (%s, from %s): %s" % (g["id"], g["kind"], g.get("source", "built-in"), g["lead"]))
        if g.get("between"):
            lines.append("  - Between: %s" % " | ".join(x for x in g["between"] if x))
        lines.append("  - Status: " + state)
    if not record["gaps"]:
        lines.append("No gaps found.")
    (fable / "GAPS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge(record: dict, found: list[dict], source: str) -> None:
    known = {(g["kind"], tuple(g.get("between", []))) for g in record["gaps"]}
    for g in found:
        key = (g["kind"], tuple(g.get("between", [])))
        if key in known:
            continue
        g.update(id="gap-%d" % (len(record["gaps"]) + 1), source=source, status="open", how_closed=None,
                 found=datetime.date.today().isoformat())
        record["gaps"].append(g)
        known.add(key)


def main() -> int:
    parser = argparse.ArgumentParser(description="Find unconnected concepts in the project and suggest bridges to verify.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--corpus-out", metavar="FILE", help="write the text analysed, for the InfraNodus connector")
    parser.add_argument("--add", metavar="A | B", help="record a gap found another way, such as by InfraNodus")
    parser.add_argument("--lead", help="with --add: the suggested bridge to verify")
    parser.add_argument("--source", default="infranodus", help="with --add: where the gap came from")
    parser.add_argument("--close", metavar="ID", help="mark a gap closed")
    parser.add_argument("--how", help="with --close: the evidence that settled it")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    record = load_record(project)

    if args.close:
        if not (args.how or "").strip():
            parser.error("--close needs --how: the evidence that settled the gap")
        gap = next((g for g in record["gaps"] if g["id"] == args.close), None)
        if gap is None:
            sys.stderr.write("gap_analysis: no gap %s in fable/gaps.json\n" % args.close)
            return 2
        gap.update(status="closed", how_closed=args.how.strip(), closed=datetime.date.today().isoformat())
        save_record(project, record)
        print("Closed %s." % args.close)
        return 0
    if args.add:
        merge(record, [{"kind": "reported gap", "between": [x.strip() for x in args.add.split("|")], "lead": args.lead or "Verify how these connect."}], args.source)
        save_record(project, record)
        print("Recorded %s." % record["gaps"][-1]["id"])
        return 0

    texts = collect(project)
    if args.corpus_out:
        out = Path(args.corpus_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n\n".join("[%s]\n%s" % (s, t) for s, t in texts), encoding="utf-8")
    graph, _ = build_graph(texts)
    found = analyse(graph)
    record["method"] = "built-in concept co-occurrence graph (networkx)"
    record["graph"] = {"terms": graph.number_of_nodes(), "links": graph.number_of_edges(),
                       "components": nx.number_connected_components(graph) if graph.number_of_nodes() else 0,
                       "sources": len(texts)}
    merge(record, found, "built-in")
    save_record(project, record)
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        open_gaps = [g for g in record["gaps"] if g["status"] == "open"]
        print("%d terms, %d links, %d component(s) from %d source(s). %d open gap(s); see fable/GAPS.md."
              % (record["graph"]["terms"], record["graph"]["links"], record["graph"]["components"], len(texts), len(open_gaps)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
