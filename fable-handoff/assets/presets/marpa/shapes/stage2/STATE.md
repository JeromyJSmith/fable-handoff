<!-- draft: prepare.py phase 6 completes this -->
# Run ledger

## Current focus

Not started.

## Next step

Read fable/MISSION.md and the documents it names first, then confirm or extend the task list below.

## Tasks

- [ ] Build takeoff from geometry: compatible quantities per class from the decoded polygons and paths, with tests (check: `test -f done_check.py && uv run done_check.py --check --stage 2`)
- [ ] Allowances spread top-down through the allocation engine: 0 unexplained cents, 0 duplicated money (check: `test -f done_check.py && uv run done_check.py --check --stage 2`)
- [ ] Weighted averages and sliders match their equations, with tests on fixed inputs (check: `uv run pytest -q tests/test_calculations.py`)
- [ ] Category shares where the evidence is short; lump sums and fees counted once (check: `test -f done_check.py && uv run done_check.py --check --stage 2`)
- [ ] Benchmarks with cohort and spread for every class unit (check: `test -f done_check.py && uv run done_check.py --check --stage 2`)
- [ ] Extend done_check.py with --stage 2; on success it writes fable/done/stage2.json (check: `test -f done_check.py && uv run done_check.py --check --stage 2`)
- [ ] Full verify command passes and fable/REPORT.md is written (check: `uv run pytest -q tests && (cd /Volumes/MARPA/method/allocation && UV_PROJECT_ENVIRONMENT=$HOME/worktrees/_env/marpa-allocation uv run --no-sync pytest -q) && test -f done_check.py && uv run done_check.py --check --stage 2`)

## Notes for a resuming session

Run the allocation engine with UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation uv run --no-sync; a plain uv run makes a new environment there.
