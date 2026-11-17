<!-- draft: prepare.py phase 6 completes this -->
# Run ledger

## Current focus

Not started.

## Next step

Read fable/MISSION.md and the documents it names first, then confirm or extend the task list below.

## Tasks

- [ ] Build the back-test: every budgeted project rerun held out through calc.held_out (check: `uv run pytest -q tests/test_calculations.py`)
- [ ] Ulm estimated like Solomon, its answer held out by calc.ANSWER_ONLY, compared with its budget and cost to complete (check: `test -f done_check.py && uv run done_check.py --check --stage 3`)
- [ ] Solomon's first estimate with a source for every number and unknowns unpriced (check: `test -f done_check.py && uv run done_check.py --check --stage 3`)
- [ ] Held-out error per category and in total, with coverage and bias, written for the owner (check: `test -f done_check.py && uv run done_check.py --check --stage 3`)
- [ ] Extend done_check.py with --stage 3 (check: `test -f done_check.py && uv run done_check.py --check --stage 3`)
- [ ] Full verify command passes and fable/REPORT.md is written (check: `uv run pytest -q tests && (cd /Volumes/MARPA/method/allocation && UV_PROJECT_ENVIRONMENT=$HOME/worktrees/_env/marpa-allocation uv run --no-sync pytest -q) && test -f done_check.py && uv run done_check.py --check --stage 3`)

## Notes for a resuming session

Run the allocation engine with UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation uv run --no-sync; a plain uv run makes a new environment there.
