# Writing the mission

## Contents

1. What the mission is and who reads it
2. Three rules for every sentence
3. Job
4. Why
5. Where things are
6. Guardrails
7. Decisions
8. Done, and the verify command
9. The ledger and the decisions file
10. The cold read
11. A complete sample mission

## 1. What the mission is and who reads it

`fable/MISSION.md` is the prompt for the whole run. `fable/launch.py` sends its
full text to the model as the first message. After that nobody is there to add
to it, correct it or answer a question about it. The only other message a run
can receive is the launcher's own short note after a relaunch, which tells the
model to resume from the ledger.

The reader is Fable 5.2. It reads closely and applies what it reads almost
word for word. It does its best work when it is given a whole outcome and the
reason for it, and is left to find the steps. It has never seen the project,
the owner or the conversation in which you prepared the handoff. Whatever you
learned in the interview and did not write down does not exist for it.

The mission has six sections with fixed headings: Job, Why, Where things are,
Guardrails, Decisions, Done. Keep the headings as they are. The readiness
check looks for all of them except "Where things are" and fails when one is
missing or empty. Init copies a template to `fable/MISSION.md`. It holds a
`{{FILL: ...}}` marker wherever you have to write something.

## 2. Three rules for every sentence

**Write the outcome and the reason, not the steps.** A list of steps tells the
model what to do when everything goes as you expected. An outcome with its
reason tells it what to do when something does not. Over a long run, something
always does not.

**Write what you mean literally.** If a rule has an exception, write the
exception. If a word such as "never" is stronger than you mean, use a weaker
one and give the reason. The model will not guess that you meant less than you
wrote.

**Write nothing that needs a person.** No "ask me", no "check with the
owner", no "wait for approval". Each of these either stalls the run or is
ignored, and you do not control which. Decide now, and write the decision down.

One more thing to leave out: do not ask the model to write out its reasoning,
for example by telling it to think in steps and show them. Such a request can
be refused (see `fable-behaviors.md`, section 11). Ask for evidence: commands,
outputs and sources.

## 3. Job

The Job is one paragraph that states the whole outcome: what will exist and
work when the run is over, for whom, and how far it goes. Name the parts that
have to be delivered. Describe what "good" means in the places where a correct
but poor result is possible.

The readiness check requires at least 40 words. That is a floor that catches
one-liners, not a target. Most good Jobs are 80 to 200 words.

Weak:

> Fix the import feature.

This gives no outcome to aim for. The model cannot tell a finished job from a
started one, so it will either stop early or keep polishing.

Weak in a different way:

> 1. Open importer.py. 2. Add a function parse_row. 3. Call it from run().
> 4. Add tests.

These are steps. If `importer.py` turns out to be the wrong place, the model
has instructions that no longer fit and no goal to fall back on.

Strong:

> Make the CSV import in the invoicing app reliable for real bank exports.
> When the run is over, `invoicer import <file>` accepts the export formats of
> the three banks in samples/bank-exports/, creates one invoice payment per
> row, skips rows it has already imported, and reports every row it could not
> read with the line number and the reason, without stopping the import. Each
> of those four behaviors is covered by tests that use the sample files. The
> command's help text and the Import section of the README describe the
> formats that are supported.

This names the result, its four parts, the evidence for each and the edges of
the job.

## 4. Why

The Why says what the result is for and what matters most when two goals pull
apart. The model uses it to settle every question you did not foresee: which
of two designs, whether an edge case matters, when to stop improving.

The readiness check requires at least 20 words.

Weak:

> This is important for the business.

It is true of every job, so it decides nothing.

Strong:

> The bookkeeper imports about 400 rows every Monday and today fixes a dozen
> duplicates by hand. A wrong or doubled payment costs more to find later than
> a rejected row costs now, so when in doubt the import should reject a row
> and say why. Speed does not matter at this size. The bookkeeper is not a
> developer, so every message has to make sense without reading the code.

This gives the model an order of priorities (correct, then clear, and not
fast) and a reader to write messages for.

## 5. Where things are

This section saves the model the first hour. Give it the map and the commands:
which directories matter and what each holds, how to build, how to run the
tests, how to run the fast subset, and anything about the project that would
surprise a newcomer.

Run each command yourself during the Discover phase before you write it here.
A command that does not work on this machine sends the run down the wrong path
from the first minute.

Weak:

> Standard Python project layout.

Strong:

> - Code is in src/invoicer/. The import code is in src/invoicer/importer.py
>   and src/invoicer/banks/.
> - Sample bank exports are in samples/bank-exports/. They are real exports.
> - The acceptance tests are in tests/acceptance/ and fail today. Your own
>   tests and fixtures go in tests/unit/.
> - Full check: `uv run pytest -q` (about 40 seconds). Fast loop:
>   `uv run pytest -q -k import`.
> - The database in tests is SQLite in memory. No service has to be started.
> - src/invoicer/legacy/ is dead code that is still imported by one script.
>   Leave it alone.

## 6. Guardrails

Guardrails has three lists. Keep them apart, because the model treats them
differently.

**Pre-approved.** Actions the model may take without asking. Name them. The
model reads approvals narrowly, so "you have full access" approves less than
you think, and "Commit to the branch fable/import" approves exactly what you
mean.

**Forbidden.** Actions and paths that are off limits, each with a reason. This
list has to match what the guard hook enforces: every forbidden path belongs
in `protected_paths` in `fable/handoff.json`, and every forbidden command
should be caught by `blocked_bash_patterns`. Say in the mission that a hook
enforces the list, so that the model treats a block as a decision and not as a
fault to work around.

**Out of scope.** Work that looks related and is not wanted. Nothing blocks
it. The list exists because the model will otherwise see nearby problems and
may spend the run on them.

Go through every irreversible or outward-facing action the job could involve:
pushing, deploying, publishing, sending messages, deleting data, running
migrations, spending money. Put each into exactly one place: pre-approved,
forbidden, or the "skip and leave for the owner" rule in the Decisions section.

Weak:

> Be careful with the database. Ask before doing anything risky.

"Careful" and "risky" are not defined, and nobody can be asked.

Strong:

> Pre-approved, do these without asking:
>
> - Create, edit and delete files under src/invoicer/ and tests/unit/.
> - Commit to the branch fable/import.
>
> Forbidden, enforced by a hook that will block the tool call:
>
> - Do not edit anything under migrations/. Released migrations are immutable,
>   and the job needs no schema change.
> - Do not edit anything under tests/acceptance/. Those tests define the job.
>   If one looks wrong, leave it, build to it, and describe the problem in the
>   report.
> - Do not change anything under samples/bank-exports/. They are real exports,
>   and the tests have to pass against them as they are. Put new sample files
>   in tests/unit/fixtures/.
> - Do not push, and do not publish the package.
>
> Out of scope, leave these alone even though nothing blocks them:
>
> - The export feature and the PDF templates.
> - Upgrading dependencies.
> - Removing src/invoicer/legacy/.

## 7. Decisions

This section tells the model what to do when it meets a question. The template
text is complete and usually needs no change. It says three things: nobody can
answer, decisions made in advance are in `fable/DECISIONS.md`, and for
anything else the model should choose the reversible option closest to the
Why, record it and keep going. It also gives the rule for irreversible actions
that are not pre-approved: skip, record under "Left for the owner", continue.

Add to it only when the job has a decision rule of its own.

Weak:

> If you are unsure about anything, stop and ask.

Strong, as an addition to the template text:

> Where a bank's format is ambiguous, follow what the sample file does, not
> what the bank's documentation says, and note the difference in
> fable/DECISIONS.md.

## 8. Done, and the verify command

Done lists the conditions that end the run. Three are fixed, and a hook checks
them every time the model tries to stop:

- every task in `fable/STATE.md` is checked off,
- the verify command exits 0,
- `fable/REPORT.md` is written.

Quote the verify command in this section exactly as it appears in
`fable/handoff.json`. The readiness check compares the two, because a mission
that names one command while the hook runs another sends the model after the
wrong target.

End the section by telling the model to stop when the conditions hold, and not
to add features, refactors or documentation beyond the Job. Without this, a
model that was told to keep going may keep going.

### Choosing the verify command

The verify command is the one thing a program can check about the whole job.
It has to have four properties:

1. **It fails now.** If it passes before the run, it cannot tell a finished
   job from an untouched one. If the job is new behavior, write the failing
   tests or checks first, or have the owner agree to the acceptance tests you
   write. The readiness check runs it and fails if it already passes.
2. **It passes only when the mission is complete.** A command that covers a
   third of the Job lets the run end with a third done. Where tests cannot
   cover a part, put that part into the ledger as a task and into Done as a
   written condition.
3. **It runs without a person.** No prompts, no browser, no credentials that
   are not on the machine, no service that someone has to start by hand.
4. **It cannot be satisfied by deleting tests.** Protect the acceptance tests
   by adding their path to `protected_paths`, and say so in the Forbidden list.
   If the model has to add tests of its own, keep the protected acceptance
   tests in a separate directory from the ones it may edit.

It also has to be one shell command. If the check has several parts, join them
with `&&` or put them in a script and protect the script.

Weak:

> Done when the import works well and the code is clean.

Strong:

> The run is finished when all of these are true:
>
> - Every task in fable/STATE.md is checked off.
> - `uv run pytest -q` exits 0.
> - You have run `invoicer import --help` and read the Import section of the
>   README once as the bookkeeper would, and fixed whatever was unclear.
> - fable/REPORT.md is written.
>
> A stop hook checks the tasks, the verify command and the report, and sends
> you back to work if they do not hold. Stop when they hold. Do not add
> features, refactors or documentation beyond what the Job asks for.

## 9. The ledger and the decisions file

Two more files are written together with the mission.

**`fable/STATE.md`** is the task ledger. Seed it with the parts of the Job as
unchecked `- [ ]` items, each a result that can be checked, with the fast test
for it where there is one. Five to fifteen tasks suit most runs. Tasks that
are too fine turn the ledger into a list of steps. Tasks that are too coarse
leave nothing to check off until the end, and the ledger is what a relaunched
session resumes from. The model adds tasks of its own as it learns more. Fill
in "Next step" so that the first action is clear.

Weak task: `- [ ] Work on importer`

Strong task: `- [ ] Rows already imported are skipped on a second import (tests: pytest -k duplicate)`

**`fable/DECISIONS.md`** holds what the owner decided in the interview, each
with its reason, plus the defaults for everything else. Write each decision so
that it answers a question the model might otherwise want to ask. The section
"Open questions for the owner" has to read `None.` before launch. If a question
is still open, put it to the owner now. If the owner cannot decide, write a
default that is safe and reversible, and record that it is a default.

Weak decision: `- Use best practices for dates.`

Strong decision: `- Dates in bank files are day-first (31/01/2026). Reason: all three banks are European, and month-first parsing would silently swap days and months.`

## 10. The cold read

After the readiness check passes, read the mission once from top to bottom as
if you knew nothing else: not the project, not the owner, not the interview.
The check can tell that the sections are filled in. It cannot tell whether
they are true or sufficient.

Ask these questions as you read:

- If this text were all I had, would I know what to build and when to stop?
- Is there a sentence I would want to ask about? Then the answer is missing.
  Add it to the mission or to `fable/DECISIONS.md`.
- Does any rule say more than the owner meant if it is applied to the letter?
- Is every path and command real? Did I run each command?
- Does every forbidden item have a reason and a matching entry in
  `fable/handoff.json`?
- Could the verify command pass with part of the Job undone?
- Did anything from the interview stay in my head and not reach the page?

Any edit to the mission changes the package, so run the readiness check again
afterwards. The launcher refuses to start otherwise.

## 11. A complete sample mission

This is the mission built from the strong examples above. Its verify command
in `fable/handoff.json` is `uv run pytest -q`. Its `protected_paths` has three
entries added to the defaults, one for each forbidden path: `migrations/**`,
`tests/acceptance/**` and `samples/bank-exports/**`. The default
`blocked_bash_patterns` already stop package publishing and a push to main,
master or production. This owner wants no push at all, so one pattern is
added: `\bgit\s+push\b` (in the JSON file each backslash is written twice).
The run branch `fable/import` was created with `git switch -c fable/import`
and passed to init as `--branch`.

```markdown
# Mission: reliable bank CSV import

## Job

Make the CSV import in the invoicing app reliable for real bank exports. When
the run is over, `invoicer import <file>` accepts the export formats of the
three banks in samples/bank-exports/, creates one invoice payment per row,
skips rows it has already imported, and reports every row it could not read
with the line number and the reason, without stopping the import. Each of
those four behaviors is covered by tests that use the sample files. The
command's help text and the Import section of the README describe the formats
that are supported.

## Why

The bookkeeper imports about 400 rows every Monday and today fixes a dozen
duplicates by hand. A wrong or doubled payment costs more to find later than a
rejected row costs now, so when in doubt the import should reject a row and
say why. Speed does not matter at this size. The bookkeeper is not a
developer, so every message has to make sense without reading the code.

## Where things are

- Code is in src/invoicer/. The import code is in src/invoicer/importer.py and
  src/invoicer/banks/.
- Sample bank exports are in samples/bank-exports/. They are real exports.
- The acceptance tests are in tests/acceptance/ and fail today. Your own tests
  and fixtures go in tests/unit/.
- Full check: `uv run pytest -q` (about 40 seconds). Fast loop:
  `uv run pytest -q -k import`.
- The database in tests is SQLite in memory. No service has to be started.
- src/invoicer/legacy/ is dead code that is still imported by one script.
  Leave it alone.

## Guardrails

Pre-approved, do these without asking:

- Create, edit and delete files under src/invoicer/ and tests/unit/.
- Commit to the branch fable/import.

Forbidden, enforced by a hook that will block the tool call:

- Do not edit anything under migrations/. Released migrations are immutable,
  and the job needs no schema change.
- Do not edit anything under tests/acceptance/. Those tests define the job. If
  one looks wrong, leave it, build to it, and describe the problem in the
  report.
- Do not change anything under samples/bank-exports/. They are real exports,
  and the tests have to pass against them as they are. Put new sample files in
  tests/unit/fixtures/.
- Do not push, and do not publish the package.

Out of scope, leave these alone even though nothing blocks them:

- The export feature and the PDF templates.
- Upgrading dependencies.
- Removing src/invoicer/legacy/.

## Decisions

Nobody can answer questions during this run. Decisions made in advance are in
fable/DECISIONS.md. For anything not covered there, choose the option that is
easiest to undo and closest to the Why above, record it in fable/DECISIONS.md
with your reason, and keep going. If an action cannot be undone and is not
pre-approved, skip it, record it under "Left for the owner", and continue with
everything else.

Where a bank's format is ambiguous, follow what the sample file does, not what
the bank's documentation says, and note the difference in fable/DECISIONS.md.

## Done

The run is finished when all of these are true:

- Every task in fable/STATE.md is checked off.
- `uv run pytest -q` exits 0.
- You have run `invoicer import --help` and read the Import section of the
  README once as the bookkeeper would, and fixed whatever was unclear.
- fable/REPORT.md is written.

A stop hook checks the tasks, the verify command and the report, and sends you
back to work if they do not hold. Stop when they hold. Do not add features,
refactors or documentation beyond what the Job asks for.
```

The ledger that goes with it:

```markdown
## Tasks

- [ ] Each of the three bank formats is parsed into payments (tests: pytest -k format)
- [ ] Rows already imported are skipped on a second import (tests: pytest -k duplicate)
- [ ] Unreadable rows are reported with line number and reason, and the import continues (tests: pytest -k reject)
- [ ] `invoicer import --help` and the README Import section describe the supported formats
- [ ] Full verify command passes and fable/REPORT.md is written
```
