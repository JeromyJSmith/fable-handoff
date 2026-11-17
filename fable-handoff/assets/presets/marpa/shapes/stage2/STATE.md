# Run ledger

## Current focus

Not started.

## Next step

Read fable/MISSION.md and the documents it names first, then confirm or extend the task list below.

## Tasks

- [ ] Build takeoff from geometry: compatible quantities per class from the decoded polygons and paths, with tests
- [ ] Allowances spread top-down through the allocation engine: 0 unexplained cents, 0 duplicated money
- [ ] Weighted averages and sliders match their equations, with tests on fixed inputs
- [ ] Category shares where the evidence is short; lump sums and fees counted once
- [ ] Benchmarks with cohort and spread for every class unit
- [ ] Extend done_check.py with --stage 2; on success it writes fable/done/stage2.json
- [ ] Full verify command passes and fable/REPORT.md is written

## Notes for a resuming session

Run the allocation engine with UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation uv run --no-sync; a plain uv run makes a new environment there.
