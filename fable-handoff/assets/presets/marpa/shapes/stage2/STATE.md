# Run ledger

## Current focus

Not started.

## Next step

Read fable/MISSION.md and the documents it names first, then confirm or extend the task list below.

## Tasks

- [ ] Cut the desk by its map's work order, one step at a time, with the desk's tests after each
- [ ] The desk's budget section works unchanged: bids, attaching subcontractors, the administration markup
- [ ] Feed the budget section the stage 1 budget in the standard's form through the Standards API
- [ ] Analysis views: plan by slot or class, allowance flow summing to the ledger, allocated dollars and quantities by item, intake match, cross-project comparison with slider weights
- [ ] Extend done_check.py with --stage 2
- [ ] Full verify command passes and fable/REPORT.md is written

## Notes for a resuming session

Run the allocation engine with UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation uv run --no-sync; a plain uv run makes a new environment there.
