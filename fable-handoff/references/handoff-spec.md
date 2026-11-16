# The structured handoff spec, and querying it with jq

Read this in phase 6 when you build the package from a spec instead of
editing the mission by hand. That is the recommended route after preflight.

## Contents

1. Why a spec
2. The flow
3. Fields
4. Checking it
5. Querying it with jq
6. Editing it with jq
7. Rendering the package
8. Owner sign-off
9. jq notes

## 1. Why a spec

Without a spec, the material from preflight and the interview is copied by
hand into four files: the mission, the ledger, the decisions and the config.
Copies drift, and nothing checks that every open acceptance criterion has a
test or that every forbidden action has a hook behind it.

`fable/handoff_spec.json` holds all of it once, in a fixed structure
(`assets/schema/handoff_spec.schema.json`). A program checks it, jq queries
it, and `render_handoff.py` writes the four files from it. Each list item can
record the document and line it came from, so any line of the mission can be
traced back to the owner's sources.

The Job and Why stay free prose, written once. A mission stitched together
from small fields reads stiffly, and Fable reads it literally. Everything that
is naturally a list (criteria, tasks, traps, decisions, guardrails) is
structured.

## 2. The flow

```bash
python3 scripts/preflight.py --project . --run-tests      # drafts fable/handoff_spec.json
python3 scripts/spec_tool.py check --project .            # what is missing
jq -L SKILL/assets/jq 'include "handoff"; summary' fable/handoff_spec.json
#   ... complete the spec with the owner, check again until READY TO RENDER ...
python3 scripts/init_handoff.py --project . --from-preflight --branch fable/my-job
python3 scripts/render_handoff.py --project .             # writes the package
git switch -c fable/my-job && git add -A && git commit -m "Add handoff package"
python3 scripts/readiness_check.py --project .
```

Preflight never overwrites an existing spec. When one exists, it writes its
fresh draft to `fable/handoff_spec.preflight.json` so you can compare.

Without preflight, `spec_tool.py new --project .` writes an empty spec.

## 3. Fields

| Field | Holds | Rendered into |
| --- | --- | --- |
| `project.name` | Short name of the job | Mission title |
| `goal.job`, `goal.why` | Prose, at least 40 and 20 words | Job, Why |
| `current_state` | Summary, works, half done, broken, measured baseline | Where things are |
| `where_things_are` | Paths and what each is for | Where things are |
| `commands` | `verify` (required), `fast_check`, `build`, `run` | Where things are, Done, `verify_command` |
| `acceptance_criteria` | `id`, `text`, `status` open or done, `verified_by`, `source` | Where things are |
| `tasks` | Checkable results, a `check` command, the criteria ids they deliver, and a `route`: `fable-worker`, `fable-builder`, `fable-specialist`, `fable-scout` or `lead` | STATE.md tasks, with `(check: ...)` and `[route: ...]` |
| `guardrails.pre_approved` | Routine actions, named | Guardrails |
| `guardrails.forbidden` | `action`, `reason`, `enforced_by` paths or command patterns | Guardrails, `protected_paths`, `blocked_bash_patterns` |
| `guardrails.out_of_scope` | `text`, `reason` | Guardrails |
| `decisions` | `decision`, `reason`, `source` | DECISIONS.md |
| `defaults` | Defaults beyond the standard three | DECISIONS.md |
| `open_questions` | Must be empty before rendering | (blocks rendering) |
| `traps` | What failed, what to do `instead`, `source` | Where things are |
| `practices_to_keep` | What worked | DECISIONS.md |
| `done_extra` | Conditions a program cannot check | Done |
| `run` | `branch`, `model`, `effort`, `permission_mode`, `max_budget_usd`, `max_relaunches` | `handoff.json` |
| `sources` | Every document used, with its role | (provenance) |

## 4. Checking it

`spec_tool.py check` reports schema errors (wrong type, missing or unknown
key, bad enum value) and readiness problems. FAIL problems block rendering:

- Job under 40 words, Why under 20, or either assuming a person will answer.
- No verify command.
- An open question.
- An open acceptance criterion that no test or eval checks (`verified_by`).
- No tasks, or a task naming an unknown criterion id.
- No pre-approved actions.
- A forbidden action that no protected path or blocked pattern enforces.
- A run branch such as main.

WARN problems are worth a look: nothing out of scope, no budget, a trap with
no "instead", no history, no decisions.

## 5. Querying it with jq

`assets/jq/handoff.jq` is a jq module. Point `-L` at its directory and
`include` it. These queries exist:

| Query | Output |
| --- | --- |
| `summary` | Counts, readiness and the verify command |
| `problems` | The same problems as `spec_tool.py`, as JSON |
| `problems_text` | One tab-separated line per problem (use `-r`) |
| `ready` | true or false. With `-e`, exit 0 when ready and 1 when not |
| `fails` | The FAIL problems only |
| `open_questions` | Questions with their source, for the interview |
| `unverified` | Open criteria with no test |
| `criteria_without_task` | Open criteria no task delivers |
| `unenforced` | Forbidden actions with nothing enforcing them |
| `enforcement` | Every protected path and blocked pattern, merged |
| `provenance` | Each criterion, decision, trap and question with its source |
| `sources_by_role` | Documents grouped by role |
| `routing` | Tasks grouped by route, so you can see how much goes to each model |
| `tasks_md`, `traps_md` | Markdown lines (use `-r`) |
| `criteria_tsv` | id, status, verified_by, text as TSV (use `-r`) |

```bash
J="jq -L SKILL/assets/jq"
$J -r 'include "handoff"; open_questions' fable/handoff_spec.json      # interview agenda
$J -r 'include "handoff"; unverified' fable/handoff_spec.json          # tests still to write
$J -e 'include "handoff"; ready' fable/handoff_spec.json && echo ready # gate in a script or CI
$J -r 'include "handoff"; criteria_tsv' fable/handoff_spec.json | column -t -s $'\t'
```

Plain jq works on the spec too, with no module:

```bash
jq -r '.traps[] | select(.instead == null) | .text' fable/handoff_spec.json
jq '[.acceptance_criteria[] | select(.status == "open")] | length' fable/handoff_spec.json
jq -r '.decisions[] | "\(.decision) (\(.source // "no source"))"' fable/handoff_spec.json
```

`spec_tool.py` is the authority. The jq module repeats its rules so you can
ask questions from the shell, and the skill's tests keep the two identical.

## 6. Editing it with jq

jq writes to stdout, so edit through a temporary file and check afterwards:

```bash
jq --arg why "Finance reconciles by hand when an order is dropped, so a loud failure beats a guess." \
   '.goal.why = $why
    | .acceptance_criteria |= map(if .id == "c1" then .verified_by = "tests/test_import.py::test_2025" else . end)
    | .open_questions |= map(select(.question | test("staging database") | not))
    | .decisions += [{decision: "Staging uses SQLite", reason: "owner answer", source: "interview"}]
    | .run.max_budget_usd = 30' \
   fable/handoff_spec.json > fable/handoff_spec.tmp && mv fable/handoff_spec.tmp fable/handoff_spec.json
python3 scripts/spec_tool.py check --project .
```

Use `--arg` for strings and `--argjson` for numbers, booleans and objects, so
quoting inside the text cannot break the program. Answering a question means
two edits: remove it from `open_questions` and add the answer to `decisions`.

Editing the JSON in any editor is just as good. jq is convenient for small,
repeatable changes and for scripts.

## 7. Rendering the package

`render_handoff.py --project .` needs an existing package (run
`init_handoff.py` first) and a spec that passes `check`. It writes
`MISSION.md`, `STATE.md` and `DECISIONS.md`, and merges the verify command,
run settings and enforcement into `handoff.json` without removing anything
already there. It runs any number of times with the same result.

Treat the spec as the source. To change the mission, change the spec and
render again. `render_handoff.py --check` reports any rendered file that no
longer matches, and the readiness check shows the same as a WARN. A spec that
fails `check` makes readiness FAIL.

During the run the spec is protected like the mission, so the run cannot
change its own definition of done.

## 8. Owner sign-off

The owner approves the spec, not the rendered files, and approves it once it
is complete:

```bash
python3 scripts/spec_tool.py brief --project .      # writes fable/OWNER_BRIEF.md
#   ... the owner reads it and says yes, or asks for changes ...
python3 scripts/spec_tool.py signoff --project . --by "Jane Owner"
python3 scripts/spec_tool.py status --project .     # OK, MISSING or STALE
```

The brief is one page: the job and why, how done is decided, what the run may
do without asking, what it is blocked from, what is out of scope, what was
decided on the owner's behalf, and the limits. Both commands refuse a spec
that fails `check`, so there is nothing to approve until it is complete.

`signoff` stores the owner's name, the time and a SHA-256 of the spec without
its sign-off, in a canonical form, so reformatting does not matter and any
real edit does. The readiness check fails while the sign-off is missing or
stale. Run `signoff` only after the owner has said yes in their own words.

## 9. jq notes

- The module is tested with jq 1.7. It avoids builtins added in 1.7 and 1.8
  (`pick`, `abs`, `trim`) so that it should also run on jq 1.6, but that has
  not been tested.
- `-L DIR` replaces the default search path, so module and data files must be
  in `DIR`. `include` brings definitions into the program's scope; a module
  included by another module is not visible at the top level.
- `-e` sets the exit status from the last output: 0 for anything but `false`
  or `null`, 1 for those, 4 for no output. Errors exit 5.
- In jq, `|` binds more loosely than `,`. In a list such as
  `[ (a | select(x) | f), (b | ...) ]`, each item needs its parentheses, or a
  `select` that drops its input also drops every item after it.
- `//` replaces `null` and `false` with its right side. Use it for optional
  fields: `.verified_by // "none"`.
- jq is not needed to run the skill. The hooks, scripts and launcher use only
  Python. Install jq (`brew install jq`, `apt install jq`) to use the queries.
