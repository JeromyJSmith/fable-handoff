#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Map the MARPA desk app so the slimmed release can be cut without breaking anything.

Runs on a clean copy of the desk repository at one commit, never on the
owner's working checkout. The copy holds the pinned dev tools
(dependency-cruiser, knip, @swc/core as its parser, added with bun). Every
output goes to --out; only a short summary is printed.

Steps, in order:

1. The keep/cut list (the authority): dependency-cruiser over src/ with the
   desk's tsconfig.json. The desk mounts every view statically in
   src/components/worksheet/AppShell.tsx and switches on `view`, so the map
   reads which component each view renders there, and walks the graph twice:
   starting at the shell and the kept views (AppShell's edges to cut-only views
   removed), and starting at the cut views. Three sets come out: needed by the kept
   features, shared with cut features, and safe to remove. The feature list
   and each feature's group come from src/lib/desk/featureRegistry.ts.
   knip then reports unused files and exports; the map says where it and
   dependency-cruiser disagree, and checks one route file first.
2. The cross-language links: Tauri invoke/listen/emit calls in the front end
   against the Rust #[tauri::command] functions, the Rust module tree
   (cargo-modules), and unused Python (vulture).
3. The overview: graphify, code only, GRAPHIFY_BACKEND=none (no model,
   nothing uploaded), with its import counts compared with
   dependency-cruiser's on the most imported files.

    uv run --script desk_map.py --desk <clean copy> --out <desk>/var/reference/desk-map/<date>_<commit>
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KEEP_GROUPS = ("documents", "standards")
CUT_GROUPS = ("database", "diagnostics", "lab", "site")
SHELL_ROOTS = ("src/router.tsx", "src/routeTree.gen.ts", "src/routes")
APP_SHELL = "src/components/worksheet/AppShell.tsx"
VULTURE = "vulture==2.16"


def run(cmd, cwd, env=None, timeout=1800):
    full = dict(os.environ, **(env or {}))
    return subprocess.run(cmd, cwd=cwd, env=full, capture_output=True, text=True, timeout=timeout)


def features(desk: Path) -> dict[str, str]:
    """{view: group} from featureRegistry.ts."""
    text = (desk / "src/lib/desk/featureRegistry.ts").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"\n  (\w+): \{(.*?)\n  \}", text, re.S):
        g = re.search(r'group: "(\w+)"', m.group(2))
        if g:
            out[m.group(1)] = g.group(1)
    return out


def view_components(desk: Path) -> dict[str, set[str]]:
    """{component name: views that render it} from AppShell's view switch."""
    text = (desk / APP_SHELL).read_text(encoding="utf-8")
    out: dict[str, set[str]] = collections.defaultdict(set)
    for m in re.finditer(r"((?:view === \"\w+\"\s*(?:\|\|\s*)?)+)\s*\?\s*\(?\s*<(\w+)", text):
        for v in re.findall(r'view === "(\w+)"', m.group(1)):
            out[m.group(2)].add(v)
    return out


def imports_of(desk: Path, file: str) -> dict[str, str]:
    """{imported name: module specifier} for one file."""
    text = (desk / file).read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r'import\s+(?:type\s+)?(?:(\w+)\s*,?\s*)?(?:\{([^}]*)\})?\s*from\s*"([^"]+)"', text):
        default, named, spec = m.groups()
        if default:
            out[default] = spec
        for n in (named or "").split(","):
            n = n.strip().split(" as ")[-1].strip()
            if n:
                out[n] = spec
    return out


def depcruise(desk: Path, out: Path) -> dict:
    cfg = desk / ".dependency-cruiser.cjs"
    if not cfg.exists():
        cfg.write_text('module.exports = { options: { tsConfig: { fileName: "tsconfig.json" }, parser: "swc", tsPreCompilationDeps: true,\n'
                       '  enhancedResolveOptions: { extensions: [".ts", ".tsx", ".js", ".jsx", ".mjs", ".json"] }, doNotFollow: { path: "node_modules" } } };\n')
    proc = run([str(desk / "node_modules/.bin/depcruise"), "src", "--config", str(cfg), "--output-type", "json"], desk)
    if proc.returncode not in (0,) or not proc.stdout.strip():
        raise SystemExit("dependency-cruiser failed: " + proc.stderr[-400:])
    (out / "dependency-cruiser.json").write_text(proc.stdout, encoding="utf-8")
    return json.loads(proc.stdout)


def graph(dc: dict) -> dict[str, set[str]]:
    g = collections.defaultdict(set)
    for m in dc["modules"]:
        if not m["source"].startswith("src/"):
            continue
        g[m["source"]]
        for d in m.get("dependencies", []):
            if d.get("resolved", "").startswith("src/"):
                g[m["source"]].add(d["resolved"])
    return g


def reach(g, roots, skip_edges=frozenset()):
    seen, todo = set(), list(roots)
    while todo:
        f = todo.pop()
        if f in seen or f not in g:
            continue
        seen.add(f)
        todo += [t for t in g[f] if (f, t) not in skip_edges]
    return seen


def keep_cut(desk: Path, dc: dict, keep_groups, cut_groups) -> dict:
    g = graph(dc)
    groups = features(desk)
    comps = view_components(desk)
    imp = imports_of(desk, APP_SHELL)
    resolved = {d["module"]: d["resolved"] for m in dc["modules"] if m["source"] == APP_SHELL for d in m.get("dependencies", [])}
    def file_of(comp):
        return resolved.get(imp.get(comp, ""), None)
    keep_files, cut_files, unknown = set(), set(), []
    for comp, views in sorted(comps.items()):
        f = file_of(comp)
        gs = {groups.get(v, "unregistered") for v in views}
        if f is None:
            unknown.append({"component": comp, "views": sorted(views)})
        elif gs & set(keep_groups):
            keep_files.add(f)
        elif gs <= set(cut_groups):
            cut_files.add(f)
        else:
            unknown.append({"component": comp, "views": sorted(views), "groups": sorted(gs)})
    roots = [f for f in g if any(f == r or f.startswith(r + "/") for r in SHELL_ROOTS)] + [APP_SHELL] + sorted(keep_files)
    skip = {(APP_SHELL, f) for f in cut_files}
    needed = reach(g, roots, skip)
    cut_reach = reach(g, sorted(cut_files))
    shared = needed & cut_reach
    removable = cut_reach - needed
    unreached = set(g) - needed - cut_reach
    indeg = collections.Counter(t for f in g for t in g[f])
    largest_shared = sorted(shared, key=lambda f: (-indeg[f], f))[:15]
    return {"keep_groups": list(keep_groups), "cut_groups": list(cut_groups),
            "kept_view_components": sorted(keep_files), "cut_view_components": sorted(cut_files), "unmapped_components": unknown,
            "needed": sorted(needed), "shared": sorted(shared), "safe_to_remove": sorted(removable), "reached_by_neither": sorted(unreached),
            "largest_shared": [{"file": f, "imported_by": indeg[f]} for f in largest_shared], "indegree": dict(indeg)}


def knip(desk: Path, out: Path, sets: dict) -> dict:
    proc = run([str(desk / "node_modules/.bin/knip"), "--reporter", "json", "--no-exit-code", "--no-progress"], desk)
    (out / "knip.json").write_text(proc.stdout or "{}", encoding="utf-8")
    (out / "knip.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return {"error": (proc.stderr or proc.stdout)[-400:]}
    issues = data.get("issues", [])
    files = sorted({i["file"] for i in issues if i.get("files")} | set(data.get("files", [])))
    files = [f for f in files if f.startswith("src/")]
    exports = sum(len(i.get("exports") or []) + len(i.get("types") or []) for i in issues)
    route = next((f for f in sets["needed"] if f.startswith("src/routes/") and f.endswith(".tsx") and "__root" not in f), None)
    needed = set(sets["needed"])
    neither = {f for f in sets["reached_by_neither"] if not re.search(r"\.(test|spec)\.[tj]sx?$", f)}
    return {"unused_files": len(files), "unused_exports_and_types": exports,
            "route_checked": route, "route_reported_unused": route in files,
            "unused_but_needed_by_depcruise": sorted(set(files) & needed)[:30],
            "orphans_depcruise_not_in_knip": sorted(neither - set(files))[:30],
            "agree_unused": len(set(files) & neither)}


def tauri_links(desk: Path, sets: dict) -> dict:
    front = collections.defaultdict(set)
    for path in (desk / "src").rglob("*"):
        if path.suffix in (".ts", ".tsx", ".js", ".mjs") and path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"\binvoke(?:<[^>]*>)?\(\s*[\"'](\w+)[\"']", text):
                front[("command", m.group(1))].add(str(path.relative_to(desk)))
            for m in re.finditer(r"\b(?:listen|once)(?:<[^>]*>)?\(\s*[\"']([\w:./-]+)[\"']", text):
                front[("event", m.group(1))].add(str(path.relative_to(desk)))
    rust_cmds, rust_events = {}, collections.defaultdict(set)
    for path in (desk / "src-tauri").rglob("*.rs"):
        if "target" in path.parts or "gen" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"#\[tauri::command[^\]]*\]\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)", text):
            rust_cmds[m.group(1)] = str(path.relative_to(desk))
        for m in re.finditer(r"\.emit(?:_to|_all)?\(\s*(?:[^,]*,\s*)?\"([\w:./-]+)\"", text):
            rust_events[m.group(1)].add(str(path.relative_to(desk)))
    needed, removable = set(sets["needed"]), set(sets["safe_to_remove"])
    rows = []
    for (kind, name), files in sorted(front.items()):
        users_kept = sorted(files & needed)
        users_cut = sorted(files & removable)
        rows.append({"kind": kind, "name": name, "rust": rust_cmds.get(name) if kind == "command" else sorted(rust_events.get(name, [])),
                     "used_by_kept": users_kept, "used_only_by_cut": not users_kept and bool(users_cut)})
    called = {n for (k, n) in front if k == "command"}
    return {"commands_called": len(called), "rust_commands": len(rust_cmds),
            "rust_commands_never_called": sorted(set(rust_cmds) - called),
            "called_but_not_in_rust": sorted(called - set(rust_cmds)),
            "commands_only_for_cut_features": sorted(r["name"] for r in rows if r["kind"] == "command" and r["used_only_by_cut"]),
            "links": rows}


def rust_modules(desk: Path, out: Path) -> dict:
    if not shutil.which("cargo-modules"):
        return {"error": "cargo-modules is not installed (cargo install cargo-modules --locked)"}
    proc = run(["cargo", "modules", "structure", "--lib", "--no-fns", "--no-types", "--no-traits"], desk / "src-tauri", timeout=3600)
    if proc.returncode != 0:
        proc = run(["cargo", "modules", "structure", "--bin", desk.name, "--no-fns", "--no-types", "--no-traits"], desk / "src-tauri", timeout=3600)
    plain = re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout)
    (out / "cargo-modules.txt").write_text(plain + proc.stderr, encoding="utf-8")
    mods = [l for l in plain.splitlines() if re.search(r"\bmod \w+", l)]
    return {"modules": len(mods), "ok": proc.returncode == 0, "error": None if proc.returncode == 0 else proc.stderr[-300:]}


def python_unused(desk: Path, out: Path) -> dict:
    tracked = run(["git", "ls-files", "*.py"], desk).stdout.splitlines()
    py = [f for f in tracked if not f.startswith(("docs/", '"docs')) and (desk / f).is_file()]
    if not py:
        return {"python_files": 0}
    proc = run(["uv", "tool", "run", "--from", VULTURE, "vulture", *py, "--min-confidence", "80"], desk)
    (out / "vulture.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode not in (0, 1, 3) or "Traceback" in proc.stderr:
        return {"python_files": len(py), "error": proc.stderr[-300:]}
    lines = [l for l in proc.stdout.splitlines() if "% confidence" in l]
    by_file = collections.Counter(l.split(":", 1)[0] for l in lines)
    return {"python_files": len(py), "findings": len(lines), "files_with_most": by_file.most_common(8)}


def graphify(desk: Path, out: Path, sets: dict) -> dict:
    if not shutil.which("graphify"):
        return {"error": "graphify is not installed (uv tool install graphifyy==0.9.111)"}
    env = {k: "" for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "MOONSHOT_API_KEY", "DEEPSEEK_API_KEY")}
    env["GRAPHIFY_BACKEND"] = "none"
    work = out / "graphify"
    work.mkdir(exist_ok=True)
    proc = run(["graphify", "extract", str(desk / "src"), "--code-only"], work, env=env, timeout=3600)
    (out / "graphify.log").write_text(proc.stdout[-20000:] + proc.stderr[-20000:], encoding="utf-8")
    gj = next(iter(sorted(work.rglob("graph.json"))), None) or next(iter(sorted((desk / "src").rglob("graphify-out/graph.json"))), None)
    if gj is None:
        return {"error": "graphify wrote no graph.json", "exit": proc.returncode}
    if not str(gj).startswith(str(out)):
        shutil.copytree(gj.parent, work / "graphify-out", dirs_exist_ok=True)
        gj = work / "graphify-out" / "graph.json"
    data = json.loads(gj.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    edges = data.get("links") or data.get("edges") or []
    file_of = {}
    for n in nodes:
        src = n.get("source_file") or n.get("file") or ""
        file_of[n.get("id")] = src if src.startswith("src/") else "src/" + src if src else ""
    importers = collections.defaultdict(set)
    for e in edges:
        if str(e.get("relation") or e.get("type") or "") in ("imports", "imports_from"):
            t = file_of.get(e.get("target"))
            s_ = e.get("source_file") or ""
            s_ = s_ if s_.startswith("src/") else "src/" + s_
            if t and s_ != t:
                importers[t].add(s_)
    imports = {f: len(v) for f, v in importers.items()}
    indeg = sets["indegree"]
    sample = [f for f, _ in sorted(indeg.items(), key=lambda kv: -kv[1])[:8]]
    compare = [{"file": f, "depcruise_imported_by": indeg[f], "graphify_import_edges": imports.get(f, 0)} for f in sample]
    comm = collections.Counter(n.get("community") for n in nodes if n.get("community") is not None)
    return {"nodes": len(nodes), "edges": len(edges), "communities": len(comm), "largest_communities": comm.most_common(5),
            "import_count_check": compare,
            "import_counts_agree": all(c["graphify_import_edges"] == c["depcruise_imported_by"] for c in compare)}


def work_order(summary: dict, sets: dict) -> str:
    """The keep/cut list in plain words, for the desk revision plan and the run's mission."""
    def section(title, files, limit=None):
        files = files if limit is None else files[:limit]
        return ["## %s" % title, ""] + ["- `%s`" % f for f in files] + [""]
    k, t = summary.get("knip", {}), summary.get("tauri", {})
    lines = ["# Desk cut work order (desk commit %s, mapped %s)" % (summary["commit"], summary["date"]), "",
             "Keep the features in the groups %s; cut %s. Made by desk_map.py from dependency-cruiser (the authority), "
             "checked with knip, the Tauri command scan, cargo-modules, vulture and graphify. Outputs are in this folder." % (
                 ", ".join(sets["keep_groups"]), ", ".join(sets["cut_groups"])), "",
             "| Set | Files |", "| --- | --- |",
             "| Needed by the kept features | %d |" % summary["needed"], "| Shared with cut features (keep) | %d |" % summary["shared"],
             "| Safe to remove | %d |" % summary["safe_to_remove"], "| Reached by neither (tests, scripts, orphans) | %d |" % summary["reached_by_neither"], "",
             "Rules for the cut: remove a file only from the safe-to-remove list; keep every shared file; remove a cut view's branch from "
             "AppShell.tsx and its entry from featureRegistry.ts together; remove a Rust command only when no kept file calls it; run the desk's "
             "tests and the budget section's walkthrough after each step.", ""]
    lines += ["## Largest shared modules", ""] + ["- `%s` (imported by %d files)" % (x["file"], x["imported_by"]) for x in summary["largest_shared"]] + [""]
    lines += section("Safe to remove", sets["safe_to_remove"])
    lines += ["## Rust commands called only by cut features", ""] + ["- `%s`" % c for c in t.get("commands_only_for_cut_features", [])] + [""]
    lines += ["## Checks between tools", "",
              "- knip: %s unused files, %s unused exports and types; route `%s` reported unused: %s." % (
                  k.get("unused_files"), k.get("unused_exports_and_types"), k.get("route_checked"), k.get("route_reported_unused")),
              "- knip flags as unused a file dependency-cruiser says the kept features need: %s." % (", ".join(k.get("unused_but_needed_by_depcruise") or []) or "none"),
              "- Rust commands never called from the front end: %d of %d." % (len(t.get("rust_commands_never_called") or []), t.get("rust_commands", 0)),
              "- Front-end calls with no Rust command: %s." % (", ".join(t.get("called_but_not_in_rust") or []) or "none"),
              "- graphify import counts against dependency-cruiser: %s." % ("; ".join("%s %d/%d" % (c["file"], c["graphify_import_edges"], c["depcruise_imported_by"])
                                                                              for c in summary.get("graphify", {}).get("import_count_check", [])) or "not run"), ""]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--desk", required=True, help="a clean copy of the desk repository at the commit the run starts from")
    ap.add_argument("--out", help="output folder (default <desk>/var/reference/desk-map/<date>_<commit>)")
    ap.add_argument("--keep", default=",".join(KEEP_GROUPS))
    ap.add_argument("--cut", default=",".join(CUT_GROUPS))
    ap.add_argument("--skip", default="", help="comma list of steps to skip: knip,tauri,rust,python,graphify")
    args = ap.parse_args()
    desk = Path(args.desk).resolve()
    commit = run(["git", "rev-parse", "--short=9", "HEAD"], desk).stdout.strip()
    dirty = [l for l in run(["git", "status", "--porcelain", "--untracked-files=no"], desk).stdout.splitlines() if l.strip()
             and not l[3:].startswith(("package.json", "bun.lock", ".dependency-cruiser.cjs"))]
    if dirty:
        sys.stderr.write("desk_map: the copy has changes to tracked files (%s); map a clean copy at a named commit\n" % ", ".join(dirty[:5]))
        return 2
    out = Path(args.out or desk / "var/reference/desk-map" / ("%s_%s" % (datetime.date.today().isoformat(), commit))).resolve()
    out.mkdir(parents=True, exist_ok=True)
    skip = set(filter(None, args.skip.split(",")))
    dc = depcruise(desk, out)
    sets = keep_cut(desk, dc, args.keep.split(","), args.cut.split(","))
    summary = {"commit": commit, "date": datetime.date.today().isoformat(), "modules": len(graph(dc)),
               "unresolved_local_imports": sum(1 for m in dc["modules"] for d in m.get("dependencies", []) if d.get("couldNotResolve") and d["module"].startswith(("@/", "."))),
               "needed": len(sets["needed"]), "shared": len(sets["shared"]), "safe_to_remove": len(sets["safe_to_remove"]),
               "reached_by_neither": len(sets["reached_by_neither"]), "largest_shared": sets["largest_shared"][:10],
               "unmapped_components": sets["unmapped_components"]}
    (out / "keep-cut.json").write_text(json.dumps({k: v for k, v in sets.items() if k != "indegree"}, indent=1) + "\n", encoding="utf-8")
    steps = {"knip": lambda: knip(desk, out, sets), "tauri": lambda: tauri_links(desk, sets), "rust": lambda: rust_modules(desk, out),
             "python": lambda: python_unused(desk, out), "graphify": lambda: graphify(desk, out, sets)}
    for name, fn in steps.items():
        if name in skip:
            summary[name] = {"skipped": True}
            continue
        try:
            result = fn()
        except Exception as error:  # a tool failure is reported, never hidden
            result = {"error": "%s: %s" % (type(error).__name__, error)}
        if name == "tauri":
            (out / "tauri-links.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
            result = {k: v for k, v in result.items() if k != "links"}
        summary[name] = result
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    (out / "CUT_WORK_ORDER.md").write_text(work_order(summary, sets), encoding="utf-8")
    print(json.dumps({"out": str(out), **{k: summary[k] for k in ("commit", "modules", "needed", "shared", "safe_to_remove", "reached_by_neither")}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
