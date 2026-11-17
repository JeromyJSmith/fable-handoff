# Mission: MARPA, the slimmed desk app (stage 2 of 2)

## Job

Build the slimmed MARPA desk app, stage 2 of 2, on the preflight stage 1 built. Cut the desk by its map's work order to the budget features, Docs, Standards and the MARPA Standard tab, feed its budget section the preflight's budget in the standard's form without changing how bids, subcontractors and the administration markup work, and add the analysis views and the guided tour for someone new.

## Why

MARPA must run without its founder: anyone at the firm should turn a drawing into a priced, editable budget the same way the founder would. Correct, conserved money and plain, tested calculations come before speed or new features.

## Where things are

The MARPA section below names every place. Build and test commands are in the Done section.

## Guardrails

Allowed without asking:

- Commit to the branch fable/marpa-stage2 in this repository
- Commit to the branch fable/marpa-1 in the desk repository (/Volumes/MARPA/apps/marpa-desk)
- Run the allocation engine's own commands (read and run only)
- Install a missing package with uv or bun, pinned exactly

Not allowed:

- Do not edit the allocation engine's code, guide or adjustments, because it is the firm's working system
- Do not push, and do not touch main, because the owner merges
- Do not send client mail or touch the desk's Pixeltable home, because both reach outside this run

Out of scope, leave these alone even though nothing blocks them:

- Restyling the desk beyond the cut and the new views
- New standard entries from old drawings beyond what the budget needs

## Decisions

The judgment test. Most questions that look like judgment calls are detective work: the answer is already in the project, its specs, past decisions, the owner's notes, outside standards or earlier work. Asking instead of searching is not allowed. A question may wait on the owner only if both hold: (a) the evidence cannot decide it, after you searched every rung of the evidence ladder in fable/handoff.json and recorded what each rung gave; and (b) it is a matter of policy or preference, not a fact. Settle everything else yourself and record it in the decisions log as decided by evidence, with the evidence.

Nobody can answer questions during this run. Decisions made in advance are in fable/DECISIONS.md. For anything not covered there, choose the option that is easiest to undo and closest to the Why above, record it in fable/DECISIONS.md with your reason, and keep going. If an action cannot be undone and is not pre-approved, skip it, record it under "Left for the owner", and continue with everything else. When a true judgment call stops a task, park that task with its question (fable/questions.py park) and continue with the others.

## Done

The run is finished when all of these are true:

- Every task in fable/STATE.md is checked off.
- `test -f docs/standard/DEFINITION_OF_DONE.md && uv run pytest -q tests && (cd /Volumes/MARPA/apps/marpa-desk && bun run test) && test -f done_check.py && uv run done_check.py --check --stage 2` exits 0.
- Every row of the definition of done for this shape meets its target (listed in the MARPA section).
- fable/REPORT.md is written.

A stop hook checks the tasks, the verify command and the report, and sends you back to work if they do not hold. Stop when they hold. Do not add features, refactors or documentation beyond what the Job asks for.
