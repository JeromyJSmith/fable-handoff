# Run ledger

## Current focus

Not started.

## Next step

Read fable/MISSION.md and the documents it names first, then confirm or extend the task list below.

## Tasks

- [ ] Build takeoff from geometry: compatible quantities per class from the decoded polygons and paths, with tests
- [ ] Build spatial relationships: nearness and containment as evidence for placement, with tests
- [ ] Drawing intake hands every decoded, placed class to the allocation engine (intake 100% decoded, every class placed)
- [ ] Allowances from project settings spread top-down: 0 unexplained cents, 0 duplicated money, full dispositions
- [ ] Weighted averages and sliders match their equations, with benchmarks showing cohort and spread
- [ ] Build the back-test: every past project estimated held out, total error within the target
- [ ] Solomon's first estimate with a source for every number and unknowns unpriced
- [ ] Write done_check.py with --stage 1; on success it writes runs/done/stage1.json
- [ ] Full verify command passes and fable/REPORT.md is written

## Notes for a resuming session

Run the allocation engine with UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation uv run --no-sync; a plain uv run makes a new environment there.
