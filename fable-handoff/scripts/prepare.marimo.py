#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo==0.25.2", "wigglystuff==0.5.40"]
# ///
"""Prepare a handoff package, phase by phase, in a marimo notebook the owner can watch.

The same phases as prepare.py (0 to 7), one cell each. Each cell takes the
previous phase's receipt, checks it against the real state, runs its phase,
writes fable/receipts/<n>-<name>.json, and stops the notebook (mo.stop) with
the reason when a check fails. The top shows a progress bar and the trace of
every command. It stops at the owner's sign-off; the launch is the owner's.

    uv run --script scripts/prepare.marimo.py -- --project <project> --preset NAME --shape NAME
    uv run --with marimo==0.25.2 --with wigglystuff==0.5.40 marimo edit scripts/prepare.marimo.py -- --project <project> ...
    uv run --with marimo==0.25.2 --with wigglystuff==0.5.40 marimo export html scripts/prepare.marimo.py -o prepare.html -- --project <project> ...
"""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="Prepare the handoff")


@app.cell
def setup():
    import argparse
    import importlib.util
    import sys
    from pathlib import Path

    import marimo as mo
    import wigglystuff

    _here = Path(__file__).resolve().parent
    _spec = importlib.util.spec_from_file_location("fable_prepare", _here / "prepare.py")
    prep = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = prep
    _spec.loader.exec_module(prep)

    _ap = argparse.ArgumentParser()
    _ap.add_argument("--project", required=True)
    _ap.add_argument("--preset")
    _ap.add_argument("--shape")
    _ap.add_argument("--logs", nargs="*", default=[])
    _ap.add_argument("--no-logs", action="store_true")
    _ap.add_argument("--goal")
    _ap.add_argument("--verify-command")
    _ap.add_argument("--apply-settings", action="store_true")
    _ap.add_argument("--max-budget-usd", type=float)
    _argv = [a for a in sys.argv[1:] if a != "--"]
    _cli = mo.cli_args()
    if _cli:
        _argv = []
        for _k, _v in _cli.items():
            if _v is True or _v == "":   # a flag given with no value
                _argv.append("--" + _k)
            elif isinstance(_v, list):
                _argv += ["--" + _k, *map(str, _v)]
            elif _v not in (None, False):
                _argv += ["--" + _k, str(_v)]
    args = _ap.parse_args(_argv)
    ctx = prep.Ctx(project=Path(args.project).expanduser().resolve(), preset=args.preset, shape=args.shape, logs=args.logs,
                   no_logs=args.no_logs, goal=args.goal, verify_command=args.verify_command, apply_settings=args.apply_settings,
                   max_budget_usd=args.max_budget_usd)
    progress = wigglystuff.ProgressBar(value=0, max_value=8)
    trace = wigglystuff.TraceView(spans=[], title="Preparation")
    return ctx, mo, prep, progress, trace


@app.cell
def header(ctx, mo, progress, trace):
    mo.vstack([
        mo.md("# Prepare the handoff\n\nProject: `%s`  \nPreset: `%s`, shape: `%s`\n\nEach phase below runs only when the one before it passed. "
              "The launch (phase 8) is the owner's." % (ctx.project, ctx.preset or "none", ctx.shape or "the preset's default")),
        progress, trace,
    ])
    return


@app.cell
def show(ctx, mo, prep, progress, trace):
    def show(receipt):
        """Show one phase's receipt as tables, and move the progress bar and the trace on."""
        n = receipt["phase"]
        progress.value = n + 1 if receipt["result"] != "stopped" else n
        spans = []
        for s in ctx.spans:
            spans.append({"span_id": "c%d" % len(spans), "parent_id": "p%d" % s["phase"], "name": s["name"],
                          "start_ms": s["start"] * 1000, "end_ms": s["end"] * 1000, "status": "ok" if s["exit"] in (0, None) else "error"})
        phases = {}
        for s in ctx.spans:
            p = phases.setdefault(s["phase"], [s["start"], s["end"], "ok"])
            p[0], p[1] = min(p[0], s["start"]), max(p[1], s["end"])
        for p, (a, b, st) in sorted(phases.items()):
            spans.insert(0, {"span_id": "p%d" % p, "parent_id": None, "name": "phase %d %s" % (p, prep.NAMES[p]), "start_ms": a * 1000, "end_ms": b * 1000, "status": st})
        trace.spans = spans
        title = "## Phase %d: %s, %s" % (n, prep.NAMES[n], receipt["result"])
        parts = [mo.md(title)]
        if receipt.get("reason"):
            parts.append(mo.callout(mo.md(receipt["reason"]), kind="danger"))
        if receipt.get("checks"):
            parts.append(mo.ui.table([{"check": c["what"], "ok": c["ok"], "detail": c["detail"]} for c in receipt["checks"]], selection=None, label="Checks"))
        if receipt.get("commands"):
            parts.append(mo.ui.table([{"command": c.get("command", "")[:160], "exit": c.get("exit"), "seconds": c.get("seconds")} for c in receipt["commands"]], selection=None, label="Commands"))
        data = receipt.get("data") or {}
        if data.get("lost_or_regressed"):
            parts.append(mo.ui.table([{"items": ", ".join(f["items"]), "status": f["status"]} for f in data["lost_or_regressed"]], selection=None, label="Data lost or regressed"))
        if data.get("rows"):
            parts.append(mo.ui.table([{"status": r["status"], "check": r["check"], "detail": r["detail"][:200]} for r in data["rows"]], selection=None, label="Readiness"))
        if receipt.get("next"):
            parts.append(mo.callout(mo.md(receipt["next"]), kind="info"))
        return mo.vstack(parts)
    return (show,)


@app.cell
def phase0(ctx, prep, show):
    r0 = prep.run_phase(ctx, 0, {})
    show(r0)
    return (r0,)


@app.cell
def phase1(ctx, mo, prep, r0, show):
    mo.stop(r0["result"] != "passed", mo.md("Stopped after phase 0: %s" % r0.get("reason")))
    r1 = prep.run_phase(ctx, 1, {0: r0})
    show(r1)
    return (r1,)


@app.cell
def phase2(ctx, mo, prep, r1, show):
    mo.stop(r1["result"] != "passed", mo.md("Stopped after phase 1: %s" % r1.get("reason")))
    r2 = prep.run_phase(ctx, 2, {1: r1})
    show(r2)
    return (r2,)


@app.cell
def phase3(ctx, mo, prep, r2, show):
    mo.stop(r2["result"] != "passed", mo.md("Stopped after phase 2: %s" % r2.get("reason")))
    r3 = prep.run_phase(ctx, 3, {2: r2})
    show(r3)
    return (r3,)


@app.cell
def phase4(ctx, mo, prep, r3, show):
    mo.stop(r3["result"] != "passed", mo.md("Stopped after phase 3: %s" % r3.get("reason")))
    r4 = prep.run_phase(ctx, 4, {3: r3})
    show(r4)
    return (r4,)


@app.cell
def phase5(ctx, mo, prep, r4, show):
    mo.stop(r4["result"] != "passed", mo.md("Stopped after phase 4: %s" % r4.get("reason")))
    r5 = prep.run_phase(ctx, 5, {4: r4})
    show(r5)
    return (r5,)


@app.cell
def phase6(ctx, mo, prep, r5, show):
    mo.stop(r5["result"] != "passed", mo.md("Stopped after phase 5: %s" % r5.get("reason")))
    r6 = prep.run_phase(ctx, 6, {5: r5})
    show(r6)
    return (r6,)


@app.cell
def phase7(ctx, mo, prep, r6, show):
    mo.stop(r6["result"] != "passed", mo.md("Stopped after phase 6: %s" % r6.get("reason")))
    r7 = prep.run_phase(ctx, 7, {6: r6})
    show(r7)
    return (r7,)


if __name__ == "__main__":
    app.run()
