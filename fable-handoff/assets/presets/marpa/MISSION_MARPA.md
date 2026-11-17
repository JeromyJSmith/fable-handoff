## MARPA: the product

Start here, in this order:

1. docs/standard/PRODUCT_GOALS.md in this repository: the authority for what the product is.
2. docs/standard/DEFINITION_OF_DONE.md: the measured targets. They are this run's definition of done and its stop condition.
3. /Volumes/MARPA/method/allocation/AEC-ALLOWANCE-METHOD.md, then its README.md, SPEC.md, DESIGN-TO-COST-SPEC.md and STATE-OF-SYSTEM-20261111.md: how MARPA budgets.
4. docs/standard/SYSTEM.md, vwx/WORKFLOW.md, vwx/FORMAT_NOTES.md, vwx/run_vwx.sh and intake.py: how a drawing becomes data.

Where this mission and those documents differ, the documents win; record the difference in DECISIONS.md.

**The product.** MARPA Design Studios (landscape architecture and design-build construction, Boulder) budgets by allowances: project settings hold an allowance per budget category, and subcontractors do the work. Someone at MARPA drops a project's Vectorworks drawing into the slimmed desk app. The system spreads each allowance onto the drawn classes of its category, keeps running averages from past projects, and hands a budget in the standard's form to the desk app's budget section. There the firm takes subcontractor bids, attaches subcontractors and sets the administration markup, the firm's main income. The purpose is that the firm runs without its founder. The standard is the means, not the product.

### Three stages, data first (the owner's decision of 2026-11-16)

1. **Stage 1, the data.** Every past project that has a budget is loaded with its own budget as the truth, through the JSON and jq processes, until everything needed to allocate and estimate is in. Nothing is estimated in stage 1.
2. **Stage 2, the weighted averages.** Computed over all budgeted projects through the allocation engine: rate = Σ w·A ÷ Σ w·Q over compatible quantities, with recency and similarity weights, and category shares where the evidence is short.
3. **Stage 3, the benchmark.** The same projects rerun, each held out. Ulm and Solomon are the two use cases: Solomon has no budget; Ulm is estimated the same way, with its own budget and cost to complete held out as the answer (calc.held_out, calc.ANSWER_ONLY). The held-out target and the evidence minimum are set by the owner from these results.

Each stage is its own run. A stage launches only after the one before has written fable/done/stage<n>.json. The desk app waits until stage 1 is through (no decision about it before then).

### The numbering standard (binding; the owner's decision of 2026-11-16)

Every budget line has one code: slot, item, component and role. The run keeps six rules, and tests enforce them:

1. **One item per kind of thing in a slot.** The stone type, size, place and maker are the item's spec, never separate items. "Boulder", "granite boulders" and "moss rock boulders" are one item, boulder.
2. **A component is never part of an item name.** Delivery, install, equipment, service and maintenance are component digits on the item they serve.
3. **Credits, add options, revisions, value engineering and change orders are flags on a line,** never items.
4. **Every item has a real name,** never "n/a" or a placeholder.
5. **Every line is coded** with an item and a component.
6. **Tests enforce these** in every slot (tests/test_numbering_standard.py). A slot passes only when all its items pass, and the run cannot stop until they pass.

### Three places

| Place | Role | How the run uses it |
| --- | --- | --- |
| This repository (the MARPA standard) | The run's home | Loading, the audit, measurement, the averages, the benchmark and the done check, committed on the stage's branch |
| /Volumes/MARPA/method/allocation | The allocation engine: read and run, from stage 2 | Its own commands only, as its README gives them, always with `UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation uv run --no-sync`. Integrate with it; never rebuild or edit it |
| /Volumes/MARPA/apps/marpa-desk | The desk app: deferred | Not touched in stages 1 to 3 |

### How a drawing becomes data

The .vwx format is undocumented and compressed. `bash vwx/run_vwx.sh <project_id> <file.vwx>` decodes it: `s01_decode` (header and Snappy block stream) → `s02_records` (records, classes, layers, symbols, texts, geometry as NDJSON) → `s03_filter.jq` (only what the budget reads) → `s04_transform` (Polars, geometry as GeoParquet) → `s05_load` (DuckDB staging and the geometry store), then the class mapping and text stages.

### Starting from a worktree

A run works on its own branch, often in a fresh worktree. A worktree has only what git tracks, so the git-ignored data stage 1 reads (the loaded NDJSON, the working database, the owner's import, the budget workbooks, the decoded drawings, the archives and the Jev receipts) is linked from the main checkout before launch: `uv run --script <skill>/scripts/link_shared_data.py --project .`. It only adds links and never overwrites. The readiness check refuses a launch while any of it is missing. Database writes still go through the writer lock, so the one working database stays the only one.

### Run output

Output of test and pipeline runs goes to a git-ignored runs/ folder and is never committed. It is read only to find what went wrong; each finding goes into one troubleshooting document and is worked with the detective method; once solved, its run output is deleted. Earlier runs are never mined as a source of information.

### Context from the conversations (supporting; the goals document is the authority)

In sessions on this repository the owner said: the app must last a long time; it should be easy, not a pile of options; reuse the patterns of the Jev skills; never delete project files the work pulls from.
