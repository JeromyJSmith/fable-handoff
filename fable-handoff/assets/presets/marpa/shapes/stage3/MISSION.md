<!-- draft: prepare.py phase 6 completes this -->
# Mission: MARPA, the benchmark (stage 3 of 3)

## Job

Benchmark the MARPA estimating, stage 3 of 3. Every budgeted project is rerun with its own budget held out and estimated from the others through the stage 2 averages, Ulm is estimated the way Solomon will be with its own budget and cost to complete held back as the answer, Solomon gets its first estimate with a source for every number, and the held-out error is reported per category and in total for the owner to set the targets.

## Why

MARPA must run without its founder: anyone at the firm should turn a drawing into a priced, editable budget the same way the founder would. The data comes first and is the truth; correct, conserved money and plain, tested calculations come before speed or new features.

## Where things are

The MARPA section below names every place. Build and test commands are in the Done section.

## Guardrails

Allowed without asking:

- Commit to the branch fable/marpa-stage3 in this repository
- Run the allocation engine's own commands (read and run only)
- Install a missing package with uv or bun, pinned exactly

Not allowed:

- Do not edit the allocation engine's code, guide or adjustments, because it is the firm's working system
- Do not push, and do not touch main, because the owner merges
- Do not send client mail or touch the desk's Pixeltable home, because both reach outside this run

Out of scope, leave these alone even though nothing blocks them:

- Any change to the desk app (deferred until the owner decides after stage 1)
- New standard entries from old drawings beyond what the budget needs

## Decisions

The judgment test. Most questions that look like judgment calls are detective work: the answer is already in the project, its specs, past decisions, the owner's notes, outside standards or earlier work. Asking instead of searching is not allowed. A question may wait on the owner only if both hold: (a) the evidence cannot decide it, after you searched every rung of the evidence ladder in fable/handoff.json and recorded what each rung gave; and (b) it is a matter of policy or preference, not a fact. Settle everything else yourself and record it in the decisions log as decided by evidence, with the evidence.

Nobody can answer questions during this run. Decisions made in advance are in fable/DECISIONS.md. For anything not covered there, choose the option that is easiest to undo and closest to the Why above, record it in fable/DECISIONS.md with your reason, and keep going. If an action cannot be undone and is not pre-approved, skip it, record it under "Left for the owner", and continue with everything else. When a true judgment call stops a task, park that task with its question (fable/questions.py park) and continue with the others.

## Done

The run is finished when all of these are true:

- Every task in fable/STATE.md is checked off.
- `uv run pytest -q tests && (cd /Volumes/MARPA/method/allocation && UV_PROJECT_ENVIRONMENT=$HOME/worktrees/_env/marpa-allocation uv run --no-sync pytest -q) && test -f done_check.py && uv run done_check.py --check --stage 3` exits 0.
- Every row of the definition of done for this shape meets its target (listed in the MARPA section).
- fable/REPORT.md is written.

A stop hook checks the tasks, the verify command and the report, and sends you back to work if they do not hold. Stop when they hold. Do not add features, refactors or documentation beyond what the Job asks for.
