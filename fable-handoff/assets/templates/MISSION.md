# Mission: {{FILL: a short name for the job, for example "move billing to the new invoice API"}}

<!-- For the preparing agent. Replace every FILL marker, braces included.
     The readiness check fails while one is left. How to write each section, with
     weak and strong examples, is in references/writing-the-mission.md of the
     fable-handoff skill. The checks ignore HTML comments, so delete this one
     when you are done or leave it. -->

## Job

{{FILL: The whole outcome in one paragraph of at least 40 words. Say what will exist and work when the run is over, for whom, and how far it goes. Describe the result and its parts, not the steps to get there.}}

## Why

{{FILL: At least 20 words. Say what the result is for and what matters most when two goals pull apart, for example correctness before speed, or the smallest change before the cleanest design. The model uses this to settle everything you did not foresee.}}

## Where things are

{{FILL: The files and directories that matter and what each is for. The commands to build, test and run, including the fast test loop. Anything surprising about the project that would cost an hour to find out.}}

## Guardrails

Pre-approved, do these without asking:

- {{FILL: one named action per line, for example "Commit to the branch fable/run-1" or "Run the migration against the local test database". Name actions, because a general "go ahead" is read narrowly.}}

Forbidden, enforced by a hook that will block the tool call:

- {{FILL: one named action or path per line, each with its reason, for example "Do not edit anything under migrations/, because released migrations are immutable". Every path here must also be in protected_paths in fable/handoff.json.}}

Out of scope, leave these alone even though nothing blocks them:

- {{FILL: work that looks related but is not wanted, for example "Upgrading dependencies" or "Restyling pages the job does not touch".}}

## Decisions

Nobody can answer questions during this run. Decisions made in advance are in fable/DECISIONS.md. For anything not covered there, choose the option that is easiest to undo and closest to the Why above, record it in fable/DECISIONS.md with your reason, and keep going. If an action cannot be undone and is not pre-approved, skip it, record it under "Left for the owner", and continue with everything else.

## Done

The run is finished when all of these are true:

- Every task in fable/STATE.md is checked off.
- `{{FILL: the verify command, character for character as in fable/handoff.json}}` exits 0.
- {{FILL: any further condition a program cannot check, such as "you have read the new README once from top to bottom as a first-time user". Delete this line if there is none.}}
- fable/REPORT.md is written.

A stop hook checks the tasks, the verify command and the report, and sends you back to work if they do not hold. Stop when they hold. Do not add features, refactors or documentation beyond what the Job asks for.
