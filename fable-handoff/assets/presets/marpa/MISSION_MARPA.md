## MARPA

This run works in the MARPA budget standard repository for MARPA Design Studios, a landscape architecture and design-build construction firm in Boulder. Read CLAUDE.md, AGENTS.md, SPEC.md, MARPA_STANDARD.md and HANDOFF.md before the first task. The rules in CLAUDE.md are the owner's rules; they are kept exactly as written.

### What the run builds

The product: someone at MARPA drops a project's Vectorworks drawing into the slimmed desk app and gets a priced, editable budget in the MARPA standard's form (slot, group, item, cost component, line, each line with quantity, unit, rate and total), with fees from the project settings. The purpose is that the firm runs without its founder. The standard is the means, not the product.

The work, in this order:

1. **Takeoff from geometry.** Measure areas, lengths and counts per class and per standard item from the decoded drawing geometry (vwx/out/vwx_geometry.duckdb), in the budget's units and within quantity_tolerance. The drawing's geometry is the budget's quantities: a paver polygon's area is the paver line's square footage. Nearness and containment are evidence for placement; the polygons are the quantities. Where the store holds only bounding boxes, say so and decode the real polygons and paths first.
2. **The back-test that proves it.** Write budget_backtest.py. For every past project with a real budget, generate the budget from its drawing (takeoff times that project's own rates, fees from project_settings.yaml), compare it with the firm's real budget line by line and in total, and report every gap in plain words in runs/budget_backtest/REPORT.md. `budget_backtest.py --check` exits 0 only when each project agrees within the stated tolerances and every gap is explained or parked as a question. This is the run's main measure of done.
3. **Solomon, the first new project.** Produce a first estimate from Solomon's drawing (project marpa_solomon_2605) by docs/standard/ESTIMATING_DESIGN.md: the most similar past projects, weighted rates, the slope rule, fees from the project settings. Show every number's source. Solomon has no entry in project_settings.yaml yet; add it from the firm's records or park the missing fee as a question.
4. **Intake ends in the budget.** Dropping a drawing runs decode, standard mapping, takeoff and pricing, not only a match report (intake.py, POST /intake). A class new to the standard from an old drawing is settled only as far as the budget needs it, by the detective standard; true policy calls go to the BCF file and the run continues. The firm's 2027 template already matches 78 of 85 classes. Old drawings are calibration data (drawn against budgeted), not a source of new standard entries.
5. **The API the desk app uses.** Expose the budget, its lines and their sources, and editing, through the Standards API (docs/standard/STANDARDS_API.md), shaped for the desk revision plan (docs/standard/DESK_REVISION_PLAN.md).

### Out of scope for this run

- The desk app itself (/Volumes/MARPA/apps/marpa-desk, its own repository). A handoff prepares one project, and this run's project is the standard repository: the API, takeoff, pricing and the back-test. The desk's intake, budget and editing screens are a second run, prepared with this preset on the desk repository once the API holds. Record anything the desk will need in HANDOFF.md.
- The standard's documentation and the claude.ai living page belong to the MARPA Standard documentation session. Change them only where a fix must go everywhere it belongs (rule 4).

### Where things are

- The standard: MARPA_STANDARD.md, master_categories.yaml (the budget slots), budget_standard.yaml, standard_terms.yaml and class_vocabulary.yaml.
- The owner's rulings and decisions: class_rulings.yaml and DECISIONS.md. A ruling is decisive for its own project only. Another project's decision is never a vote.
- The detective standard: docs/standard/DETECTIVE_STANDARD.md and detective_functions.yaml.
- Jev decisions: jev_schemas.yaml and jev_schema.py. No schema, no call.
- The drawings: Vectorworks exports listed in inventory/export_inventory.ndjson; decoded by vwx/run_vwx.sh into vwx/out/vwx_stage.duckdb (classes, texts) and vwx/out/vwx_geometry.duckdb (geometry). Read docs/DRAWING_INPUT_METHOD.md first.
- Budgets and fees: ndjson/raw/budget_line.ndjson, inputs/Financials, project_settings.yaml, calc.py.
- The questions for the firm: a BCF 3.0 file, bcf/fable-questions.bcf. MARPA's own bcf/marpa-questions.bcf is written only by bcf_questions.py.

The class-word grammar. A Vectorworks class name is read as family, head word and modifiers. "L-Detail Material-Aggregate" has the family L (landscape), the head word Aggregate and the modifier Detail Material. A modifier changes how the class is read, never what the head word names. A single class word is weak evidence; an exact standard term or alias is strong.

The pipe. A source becomes NDJSON in ndjson/raw/, jq keeps only what the budget system reads, transform.jq shapes it, and it loads into DuckDB through the writer lock. Cases go to detective_case and detective_evidence the same way; fable/cases.json and fable/CASES.md are the run's own record.

### Done, for MARPA

- `uv run pytest -q tests && uv run budget_backtest.py --check` exits 0: every past project with a real budget agrees within tolerance, line by line and in total, and every gap is explained in runs/budget_backtest/REPORT.md or parked as a BCF question.
- Solomon's first estimate exists with a source for every number.
- A dropped drawing produces a priced budget through intake and the API.
- The detective back-test still holds: `uv run --script <skill>/scripts/detective_backtest.py --project . --cases <decided set> --min-accepted 10 --target 0.9` gives no new wrong verdicts.
