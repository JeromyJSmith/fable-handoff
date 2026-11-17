<!-- draft: prepare.py phase 6 completes this -->
# Run ledger

## Current focus

Not started.

## Next step

Read fable/MISSION.md and the documents it names first, then confirm or extend the task list below.

## Tasks

- [ ] Every budget file loaded, including inputs/owner-import-2026-11-16 and Mallett's drawing, each line accounted for (check: `uv run pytest -q tests/test_audit_stage1.py`)
- [ ] The numbering standard holds in every slot: the component digit kept in every code, no item named only by a component word (check: `uv run pytest -q tests/test_numbering_standard.py`)
- [ ] The 153 uncoded lines worked out: slot, item and component, or an open case with what would settle it (check: `uv run pytest -q tests/test_audit_stage1.py`)
- [ ] The line_measure and item_measure tables built, with their unit rules tested (check: `uv run pytest -q tests/test_measure.py`)
- [ ] The finance formula check done for every workbook (check: `uv run pytest -q tests/test_calculations.py`)
- [ ] Every budgeted project's .vwx decoded with vwx/run_vwx.sh (check: `uv run pytest -q tests/test_vwx_pipeline.py`)
- [ ] Full accounting: every drawn class homed or listed as unhomed, every line's money placed, labelled as spread, or shown as unplaced with its amount (check: `test -f done_check.py && uv run done_check.py --check --stage 1`)
- [ ] Write done_check.py with --stage 1; on success it writes fable/done/stage1.json (check: `test -f done_check.py && uv run done_check.py --check --stage 1`)
- [ ] Full verify command passes and fable/REPORT.md is written (check: `uv run pytest -q tests && test -f done_check.py && uv run done_check.py --check --stage 1`)

## Notes for a resuming session

Run the allocation engine with UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation uv run --no-sync; a plain uv run makes a new environment there.
