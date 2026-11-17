<!-- draft: prepare.py phase 6 completes this -->
# Mission: example firm, stage 1 of 2

## Job

Load every entry of the example data into the store with its own record as the truth, so that every entry is coded, every total reconciles with the recorded totals, and nothing is computed or estimated before the data is complete and checked by the tests named in the ledger.

## Why

The firm must run without its founder: anyone should get the same answer from the same data. Correct, reconciled data comes before speed or new features.

## Where things are

The data is under data/, the decisions in DECISIONS.md, the goals in docs/GOALS.md.

## Guardrails

Allowed without asking:

- Commit to the run's branch
- Install a missing package with uv, pinned exactly

Not allowed:

- Do not edit data/originals/, because the originals are the evidence
- Do not push, because the owner merges

Out of scope, leave these alone even though nothing blocks them:

- Any change to the firm's app

## Decisions

The judgment test: a question reaches the owner only after every rung of the evidence ladder is searched and it is a matter of policy. Settle everything else from the evidence and record it.

## Done

The run is finished when all of these are true:

- Every task in fable/STATE.md is checked off.
- `uv run pytest -q && test -f done_check.py && uv run done_check.py --stage 1` exits 0.
- fable/REPORT.md is written.
