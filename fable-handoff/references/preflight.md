# Preflight: preparing a project that is already close

Read this in phase 1 when the project already has a goal, specification
documents, standards, notes on its state, a record of past errors and
successes, or tests and evals. That is the usual case for a takeover: a person
has carried the work most of the way, and Fable is to finish it.

## Contents

1. What preflight does
2. The six inputs
3. Running it
4. Reading the report
5. Closing gaps
6. From preflight to the package
7. After an earlier run
8. Limits

## 1. What preflight does

`scripts/preflight.py` reads the project, sorts its documents into six inputs,
measures how ready each one is, and lists what must be added or fixed before
the package is built. It writes `fable/PREFLIGHT.md` for people and
`fable/preflight.json` for the next scripts.

It turns a pile of existing material into the shape the handoff needs. The
mission, the ledger and the decisions are not written from scratch: they are
distilled from documents the owner already trusts, and those documents stay
the authority.

## 2. The six inputs

| Input | Becomes | Required |
| --- | --- | --- |
| goal | the mission's Job and Why | yes |
| spec | tasks in `STATE.md`, the Done list, acceptance tests | no, but the evals must then be the full definition |
| standards | Guardrails and decisions; protected from edits | no |
| state | "Where things are" and the first tasks | no, but measure it with `--run-tests` |
| history | traps in "Where things are" and decisions in `DECISIONS.md` | no, but ask the owner |
| evals | the verify command; protected from edits | yes |

Documents are recognized by words in their path (`GOAL.md`, `docs/spec/`,
`LESSONS.md`, `STATUS.md`) and by their headings ("Acceptance criteria",
"Lessons learned", "Current status"). One document can serve several inputs.
Tests and evals are recognized by their directories and file names
(`tests/`, `app_tests/`, `evals/`, `test_*.py`, `*.spec.ts`, `*eval*.json`).

Each input gets a status: READY, THIN (present but too small to rely on) or
MISSING.

## 3. Running it

```bash
uv run --script scripts/preflight.py --project /path/to/project --run-tests
```

Options:

- `--goal PATH` names the goal document. `--goal "text"` gives the goal
  itself. An explicit goal is the only goal: other documents that look like
  goals are not used for it.
- `--source PATH` (repeatable) limits the document search to these files or
  directories, which may be outside the project. Tests and evals are still
  looked for inside the project.
- `--run-tests` runs the detected test command once to measure the current
  state. `--test-command "..."` names the command instead. Without either,
  nothing is executed.
- `--json` prints the data instead of the report. `--no-write` writes nothing.

Exit 0 means no blocking gap. Exit 1 means at least one, or a missing goal or
evals. Exit 2 means bad arguments.

## 4. Reading the report

Gaps come in four kinds:

- **BLOCKING**: the takeover cannot start. No goal, no tests or evals, a test
  command that already passes (it cannot tell done from not done), one that
  times out or cannot run, or no git repository.
- **FIX**: the run would be worse for it. A thin goal or spec, unrecorded
  current state, uncommitted work, instruction lines that need a human.
- **REVIEW**: judge in context. Missing standards or history, absolutes and
  style caps in standards files.
- **QUESTION**: an open question found in the documents (TBD, TODO, a line
  ending in a question mark). Take each one into the owner interview.

The drafts section proposes a verify command, paths to protect, seed tasks
from unchecked acceptance criteria, traps from past errors, and practices that
worked. These come from pattern matching, so read each one against its source
before you use it. A "trap" may be a solved problem, and a criterion may be
out of date.

## 5. Closing gaps

Close the gaps with the owner, in the documents themselves, and rerun
preflight until it says READY FOR PREPARATION.

- **No goal**: write one document with the outcome, who it is for, how anyone
  would check it, and what wins when goals conflict.
- **Tests already pass**: the remaining work is not under test. Turn each open
  acceptance criterion into a failing test or eval first. This is the most
  common blocking gap in a project that is "nearly done", and it is the one
  that matters most, because the stop gate trusts the verify command.
- **Goal in several files**: settle which one is current. A run given two
  goals follows both.
- **Thin history**: ask what was tried and failed, and what worked. A repeated
  mistake is the most expensive thing a long run can do.
- **Standards with absolutes**: decide per line whether it is a hard limit
  (keep it, and enforce it with a hook) or a habit (rewrite it with its scope).

## 6. From preflight to the package

```bash
uv run --script scripts/init_handoff.py --project /path/to/project --from-preflight \
  --branch fable/my-job --max-budget-usd 40
```

`--from-preflight` reads `fable/preflight.json` and:

- uses its verify command when `--verify-command` is not given;
- adds its paths to protect (spec, standards, goal, test and eval
  directories) to `protected_paths`, so the run cannot pass by editing its own
  definition of done;
- seeds `fable/STATE.md` with the open acceptance criteria as tasks.

Then, while writing the mission in phase 6:

- build Job and Why from the goal document, in its words where they are good;
- point "Where things are" at the spec and standards by path, and add the real
  traps from history with what to do instead;
- record each interview answer and each practice that worked in
  `DECISIONS.md`.

Commit `fable/PREFLIGHT.md` with the package. It shows the reviewer what the
takeover started from.

## 7. After an earlier run

When the project has been through a handoff run before, its `fable/` folder
holds what that run learned. Preflight reads it unless you pass
`--no-previous-run`:

- `fable/.run/lessons.json`, written by `post_run_report.py`: proposals such
  as unfinished tasks, tasks checked off with no evidence, guard rules that
  blocked many calls, a stop gate that gave up, decisions the run made and
  items it left for the owner.
- `fable/DECISIONS.md`, `fable/REPORT.md` and `fable/BLOCKED.md`, as history
  and state documents.
- The run's transcripts in `fable/.run/`, through the conversation context
  step, when jq is installed.

Each lesson lands in the draft spec: a decision the run made becomes a
decision to confirm, a trap stays a trap, and everything else becomes an open
question. Rendering stays blocked until each question is answered, so nothing
learned is lost between runs and nothing is adopted without the owner.

## 8. Limits

Preflight recognizes documents by names and headings. It can miss a goal
written inside a long README, and it can call a general notes file "history".
Check the Sources column before you trust a status. It does not judge whether
the spec is right or the tests are good: that is the owner interview and
phase 3.
