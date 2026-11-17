# Run ledger

## Current focus

Not started.

## Next step

Read fable/MISSION.md and the documents it names first, then confirm or extend the task list below.

## Tasks

- [ ] Every budget file loaded, including inputs/owner-import-2026-11-16 and Mallett's drawing, each line accounted for
- [ ] The component digit kept in every code; no item named only by a component word
- [ ] The 153 uncoded lines worked out: slot, item and component, or an open case with what would settle it
- [ ] The line_measure and item_measure tables built, with their unit rules tested
- [ ] The finance formula check done for every workbook
- [ ] Every budgeted project's .vwx decoded with vwx/run_vwx.sh
- [ ] Write done_check.py with --stage 1; on success it writes fable/done/stage1.json
- [ ] Full verify command passes and fable/REPORT.md is written

## Notes for a resuming session

Run the allocation engine with UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation uv run --no-sync; a plain uv run makes a new environment there.
