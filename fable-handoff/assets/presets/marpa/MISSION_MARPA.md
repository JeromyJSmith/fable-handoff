## MARPA: the product

Start here: docs/standard/PRODUCT_GOALS.md in this repository is the authority for what the product is. Read it first, then docs/standard/SYSTEM.md, vwx/WORKFLOW.md, vwx/FORMAT_NOTES.md, vwx/run_vwx.sh and intake.py. Where this mission and the goals document differ, the goals document wins; record the difference in DECISIONS.md.

**The product.** Someone at MARPA Design Studios (landscape architecture and design-build construction, Boulder) opens the slimmed desk app, drops in a project's Vectorworks drawing, and gets a priced, editable budget in the MARPA standard's form: slot, group, item, cost component, line, each line with quantity, unit, rate and total, and fees from the project settings. The purpose is that the firm runs without its founder. The standard is the means, not the product.

### How a drawing becomes data

The .vwx format is undocumented and compressed. It is decoded by a scripted sequence, `bash vwx/run_vwx.sh <project_id> <file.vwx>`:

1. `vwx/pipeline/s01_decode.py`: the header and the Snappy-compressed block stream, checked to end on its last block.
2. `vwx/pipeline/s02_records.py`: records, classes, layers, symbols, texts and geometry as NDJSON in ndjson/raw/.
3. `vwx/pipeline/s03_filter.jq`: jq keeps only what the budget reads.
4. `vwx/pipeline/s04_transform.py`: Polars tables, and the geometry as GeoParquet.
5. `vwx/pipeline/s05_load.py`: DuckDB staging (vwx/out/vwx_stage.duckdb) and the geometry store (vwx/out/vwx_geometry.duckdb, spatial).
6. Then the class mapping (`s06_class_map.py`) and the text stages (`s06_text_chunks`, `s07_text_functions`, `s08_text_functions.jq`).

Most objects are stored as bounding boxes today. Real polygons and paths are the first thing takeoff needs.

### The work, in this order

1. **Takeoff from geometry.** Measure areas, lengths and counts per class and per standard item from the decoded polygons and paths, in the budget's units, within quantity_tolerance. The drawing's geometry is the budget's quantities: a paver polygon's area is the paver line's square footage. Nearness and containment place a class; the polygons give its quantity. Build the takeoff and spatial relationships functions here and mark them built in the registry with their tests.
2. **The back-test against real budgets.** Write budget_backtest.py. For every past project with a real budget, generate its budget from its drawing (takeoff times that project's own rates, fees from project_settings.yaml) and compare it with the firm's real budget per line, per slot and in total, within budget_tolerance in fable/handoff.json. Write every gap in plain words to runs/budget_backtest/REPORT.md: a class not drawn, a rate, a rounding, a line the drawing cannot show. Each gap is explained or parked as a BCF question. `budget_backtest.py --check` exits 0 only when that holds.
3. **Solomon, the first new project.** A first estimate from Solomon's drawing (marpa_solomon_2605) by docs/standard/ESTIMATING_DESIGN.md: the most similar past projects, weighted rates, the slope rule, fees from the project settings, with the source of every number. Solomon has no project settings yet; add them from the firm's records or park the missing fee.
4. **Intake ends in the budget.** Dropping a drawing runs decode, standard mapping, takeoff and pricing (intake.py, POST /intake), not only a match report. A class new to the standard from an old drawing is settled only as far as the budget needs it, by the detective standard; true policy calls go to the BCF file while the run continues. The firm's 2027 template matches 78 of 85 classes, so new projects arrive mostly clean. Old drawings are calibration data (drawn against budgeted), not a source of new standard entries.
5. **The desk app shows it** (the companion repository, below): intake, the budget and editing through the Standards API, laid out by docs/standard/DESK_REVISION_PLAN.md, with the same look and design tokens.
6. **Analysis and visualization of the drawing results** (goals document, item 8): a plan view coloured by slot, quantities by slot and item, drawn against budgeted with the tolerance band, intake match charts, and comparisons across projects. The drawn-against-budgeted view is also the visible proof of the back-test.

### Two repositories

This repository is the run's home: the API, decoding, takeoff, pricing and the back-test, committed on the run branch. The desk app, /Volumes/MARPA/apps/marpa-desk, is a companion repository: the run works there only on its own branch (fable/marpa-1, checked by the readiness check), commits there under the same commit rules, and runs its tests with `bun run test`. The guard allows writes inside it and applies the protected paths there too. The verify command runs both test suites and the back-test.

### Context from the conversations (supporting; the goals document is the authority)

In sessions on this repository the owner said: the app must last a long time; it should be easy, not a pile of options; reuse the patterns of the Jev skills (hyper-jev, ten levels of Jev); never delete project files the work pulls from. The retail and vendor workbook was once proposed as a widget inside the app.

### Done, for MARPA

- `uv run pytest -q tests`, the desk's `bun run test`, and `uv run budget_backtest.py --check` all exit 0. The back-test passes when every past project with a real budget agrees within budget_tolerance per line, per slot and in total, and every gap is explained in runs/budget_backtest/REPORT.md or parked as a BCF question.
- Solomon's first estimate exists with a source for every number.
- A drawing dropped in the desk app produces a priced, editable budget through intake and the API, and the drawn-against-budgeted view shows it.
- The detective back-test on the owner's ruled cases gives no new wrong verdict.

### Where things are

The standard (MARPA_STANDARD.md, master_categories.yaml, budget_standard.yaml, standard_terms.yaml, class_vocabulary.yaml); the owner's rulings and decisions (class_rulings.yaml, DECISIONS.md; a ruling is decisive for its own project only); the detective standard (docs/standard/DETECTIVE_STANDARD.md, detective_functions.yaml); Jev schemas (jev_schemas.yaml; no schema, no call); budgets and fees (ndjson/raw/budget_line.ndjson, inputs/Financials, project_settings.yaml, calc.py); questions for the firm (bcf/fable-questions.bcf; MARPA's own bcf/marpa-questions.bcf is written only by bcf_questions.py).
