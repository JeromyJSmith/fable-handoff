---
name: fable-handoff
compatibility: Designed for Claude Code (hooks, subagents, the claude CLI). Needs uv (it supplies Python 3.11 or later; no other Python manager is used) and git; jq for the conversation and spec queries. Written for Claude Fable 5.2; see references/sources.md when models or Claude Code change.
description: Prepares a software project for Claude Fable 5.2 to finish in one long unattended run, and reviews the result afterwards. Use it when the user wants to hand a project or a large task to Fable, start a long-horizon, overnight or walk-away run, get autonomous completion with nobody watching, write a mission brief or build a handoff package, make CLAUDE.md, skills or other instruction files safe for Fable 5.2, or review what an unattended run produced. Covers discovery, a single owner interview, a checkable definition of done, guard and stop hooks, a readiness check, the launcher and the post-run review.
---

# Fable handoff

This skill gets a software project ready for Claude Fable 5.2 to take over and
finish in one long run with no person available. There are three roles. You
are the preparing agent. Fable 5.2 does the work. The owner, who is the person
you are talking to, answers questions once, before launch, and reviews the
result afterwards.

Three facts about Fable 5.2 shape everything below:

1. It applies instructions almost to the letter. A stale or careless rule can
   stall a run that nobody is watching.
2. It does its best work when given a whole outcome and the reason for it, not
   a list of steps.
3. Nobody is there during the run. So every question has to be answered in
   advance, "done" has to be something a program can check, and hard limits
   have to be enforced by code, not by a request.

Your work is to turn what the owner wants into a package that meets those
three facts, to prove that it does, and to start the run.

## Words used in this skill

- **Package**: the files this skill installs (table below). **Mission**:
  `fable/MISSION.md`, the run's prompt. **Ledger**: `fable/STATE.md`, the task
  list the model keeps and resumes from.
- **Hooks**: the **guard** blocks forbidden writes and commands; the **stop
  gate** sends the model back to work until the mission is finished; the
  **session note** re-points it at the mission and ledger after a restart or
  compaction.
- **Permission mode**: the Claude Code setting for which tool calls run
  without approval.
- **Subagents**: Fable leads a small team: `fable-scout` (Haiku) for search
  and reading, `fable-worker` (Sonnet) for many independent exact changes,
  `fable-builder` (Opus) for specified independent pieces, `fable-specialist`
  (Fable) for a large isolated problem. Connected work stays with the lead,
  which verifies every result. Spec tasks can carry a `route`.

## What is in this skill

Scripts are in `${CLAUDE_SKILL_DIR}/scripts/` (outside Claude Code, the
directory this file is in). Run each with `uv run --script` and `--project`; each has
`--help`. In order of use: `preflight.py` and `conversation_context.py`
(phase 1), `init_handoff.py` (4), `audit_rules.py` (5), `spec_tool.py` and
`render_handoff.py` (6), `readiness_check.py` and `system_review.py` (7), and
`post_run_report.py` (9). Init copies `fable/launch.py` and
`fable/questions.py` (judgment test, parking, question systems) into the project.

Read each reference at the point this file names it:
`references/preflight.md` and `references/conversation-context.md` (phase 1),
`references/fable-behaviors.md` (phase 2), `references/writing-the-mission.md`
(phases 3 and 6), `references/handoff-spec.md` (phase 6),
`references/claude-code-setup.md` (phases 4 and 8, and after a surprising
run), and `references/sources.md` when Claude Code or the model changes.
`assets/` holds what init copies; you need not read it.

## What the package looks like in the project

| Path | Purpose | Who writes it |
| --- | --- | --- |
| `fable/MISSION.md` | The prompt for the whole run | You |
| `fable/STATE.md` | Task ledger, and the run's memory | You seed it, the model keeps it |
| `fable/DECISIONS.md` | Decisions made in advance and during the run | You, then the model |
| `fable/OPERATING_RULES.md` | How to work unattended. Appended to the system prompt | Init |
| `fable/handoff.json` | Model, limits, verify command, protected paths | Init, then you tune it |
| `fable/launch.py` | Starts the run and relaunches it if it stops early | Init |
| `.claude/hooks/fable_*.py` | Guard, stop gate, session note | Init |
| `.claude/agents/fable-*.md` | The team Fable leads: scout, worker, builder, specialist | Init |
| `fable/REPORT.md`, `fable/BLOCKED.md` | The final report, or the reason the run could not finish | The model |

Work through the phases in order. Each one depends on the one before.

## Phase 0: Decide whether this is a Fable job

Decide this first, because preparing the package takes real effort from you
and the owner, and the run itself costs real money.

A job suits an unattended Fable run when it is long, when it is open-ended
enough to need judgment along the way, and when it is beyond what Opus does
well at high effort. Typical cases are building a feature set against a spec,
a migration across many files, or getting a large failing test suite to pass.

Tell the owner plainly, and suggest another route, when:

- The job is short or fully specified. An interactive session on Opus at
  medium effort is cheaper and just as good. Raising effort one level is the
  first thing to try before moving up a model.
- Nobody can say what "done" means in a way a program could check. Help the
  owner narrow the job until someone can, or do it interactively.
- The heart of the job is an action that cannot be undone and faces outward,
  such as a production deploy or a mass email. Those need a person.
- The owner wants to steer as it goes. That is an interactive session.

If the job is security work or touches biology, tell the owner now that
safety classifiers may refuse some steps even when the work is harmless.
`references/fable-behaviors.md` section 11 has the details.

## Phase 1: Discover

Detective work comes before judgment calls: most questions that look like
the owner's are answered somewhere in the project. Ask the owner only what
passes the judgment test in `references/fable-behaviors.md` section 14.

Start with preflight. Most takeovers happen when the work is already close,
and the project holds a goal, specs, standards, status notes, lessons from
past errors and successes, and tests or evals. Preflight sorts these into the
six inputs a takeover needs and reports what is missing:

```bash
uv run --script "${CLAUDE_SKILL_DIR}/scripts/preflight.py" --project /path/to/project --run-tests
```

Close every BLOCKING gap before going further. The usual one in a project that
is nearly done is a test suite that already passes: turn the open acceptance
criteria into failing tests first, because the stop gate trusts the verify
command. Preflight sorts each open question as "evidence can settle" or
"judgment" and reports the counts. Settle the evidence ones yourself from the
evidence ladder in `fable/handoff.json` and record them (`kind: "evidence"`,
then `decision_interview.py --settle`); only judgment calls, each with its full
record, go to the interview. Where facts should connect and do not, run
`gap_analysis.py` (`references/gap-analysis.md`). `references/preflight.md`
explains the report. When earlier sessions hold the story, add
`--project-logs` (or `--conversations PATH`) so preflight also rebuilds
`fable/CONTEXT.md` from the conversation logs; read its forks and issues
before the interview (`references/conversation-context.md`). If an earlier
handoff run left lessons, decisions or a report in `fable/`, preflight carries
them into the new spec as decisions to confirm, traps and open questions.
Then check what preflight cannot judge:

1. Read the README, the build and dependency files, the CI configuration and
   the layout of the source and test directories.
2. Read every instructions file that a session in this project will load:
   `CLAUDE.md`, `CLAUDE.local.md` and `AGENTS.md` at every level, everything
   under `.claude/` (commands, skills, agents, rules), and any instructions,
   notes or memory files outside the project that the owner's setup loads
   into every session. Ask the owner whether such files exist and where they
   are. The model will apply every line in these files to the letter, so you
   need to know what they say.
3. Run the build and the tests yourself. Note the exact commands and what
   fails today.
4. Look at the git state: current branch, uncommitted work, remotes.

Then report your understanding to the owner in a few short paragraphs before
the interview: what the project is, its state, the job, and what surprised you.

## Phase 2: Interview the owner once

This is the only time anyone can ask the owner anything. Whatever you do not
ask now, the model will have to guess during the run. Read
`references/fable-behaviors.md` first, so that you know which answers matter.

Ask in one sitting, and cover all of this:

- **Outcome.** What should exist and work when the run is over? What does a
  good result look like, beyond a correct one?
- **Why.** What is it for? When two goals pull apart, which one wins?
- **Scope edges.** What is in? What looks related but is not wanted?
- **Authority.** Is the codebase the model's own to reshape, or is it client
  or shared code where it should change as little as possible? This sets the
  `--ownership` switch in phase 4. Ownership produces refactoring and a larger
  diff, so it has to be the owner's choice.
- **Every irreversible or outward-facing action** the job could involve:
  pushing, deploying, publishing, running migrations, deleting data, sending
  messages, calling paid or external services. Sort each one, with the owner,
  into exactly one of three groups: pre-approved, forbidden, or "skip it and
  leave it for the owner". There is no fourth group. "Ask first" does not
  work, because nobody will be there.
- **Limits.** Spending cap, where the run happens (the owner's machine or a
  container), which permission mode, how many relaunches.
- **Traps.** Flaky tests, slow commands, areas that are known to be broken,
  approaches that were tried and failed.
- **The decisions you can foresee** from phase 1. For each, get an answer or
  a default.

Record every answer with its reason, in the form "decision, then reason". A
reason lets the model apply a decision to cases you did not think of.
Approvals have to name the action: "may commit to the branch fable/checkout",
not "has full access". At the end of the interview, show the owner the list
and have it confirmed. The list goes into `fable/DECISIONS.md` under "Made
before the run" in phase 4, when that file exists.

For decisions, write each into `open_questions` (the spec, or
`fable/open_decisions.json`): topic, what it is, why it matters, options with
what happens, and a recommendation with its reason, in plain words with no
bare numbers or IDs. The decision interview asks the owner one at a time and
records each answer; it launches nothing:

```bash
uv run --script "${CLAUDE_SKILL_DIR}/scripts/decision_interview.py" --project . --check
uv run --script "${CLAUDE_SKILL_DIR}/scripts/decision_interview.py" --project .
```

Do not leave the interview with an open question. If the owner cannot decide
something, agree on a default that is safe and reversible, and record it as a
default.

## Phase 3: Make "done" checkable

The stop gate lets the run end when every task in the ledger is checked off,
the report is written and a single shell command, the verify command, exits 0.
The model writes the first two itself. The verify command is the only
independent proof, so choose it with care. Section 8 of
`references/writing-the-mission.md` goes through this in detail.

The verify command has to meet four conditions:

1. **It fails now.** Otherwise it cannot tell a finished job from an untouched
   one.
2. **It passes only when the mission is complete.** If it covers half the job,
   the run can end half done.
3. **It runs without a person.** No prompts, no browser, no service that
   someone has to start by hand.
4. **It cannot be satisfied by deleting tests.** The tests that define the job
   have to be protected from the run.

Usually this is the project's test command plus tests for the new work. If
those tests do not exist yet, write them with the owner's agreement, or ask
the owner for them, and put them in a directory of their own so that it can be
protected in phase 4. Run the command yourself and note how long it takes.

If no such command can be found, the job is not ready for an unattended run.
Say so, and go back to phase 0 with the owner.

## Phase 4: Scaffold with init_handoff.py, then tune handoff.json

```bash
uv run --script "${CLAUDE_SKILL_DIR}/scripts/init_handoff.py" --project . \
  --verify-command "uv run pytest -q" --branch fable/checkout --max-budget-usd 60 \
  [--from-preflight] [--ownership]
```

Keep the defaults for model (the pinned ID `claude-fable-5-2`, because the
`fable` alias can resolve to an older version), effort (`high`) and permission
mode (`auto` on the owner's machine). Add `--ownership` only if the owner said
the codebase is the model's to reshape. Point at the project's own systems
with `--question-system bcf:<file>|markdown:<file>|github:<repo>` and
`--decisions-log <file>`; set `evidence_ladder` in handoff.json to where each
rung lives. `--from-preflight` reuses preflight's
verify command, protected paths and open criteria. Init never overwrites a
file without `--force` (which resets a filled-in mission too).  It prints the
`.claude/settings.json` diff and writes it only on the owner's yes (prompt or
`--apply-settings`); `--uninstall` removes the hooks and restores the backup. For an older package, `--refresh-hooks`
replaces only the hooks and the launcher.

Then create the run branch (never main), write the interview answers into
`fable/DECISIONS.md`, and tune `fable/handoff.json` with
`references/claude-code-setup.md` sections 2, 6 and 7: a `protected_paths`
glob for every forbidden path and for the tests that define the job, a
`blocked_bash_patterns` entry for every forbidden command the defaults miss,
and the budget, relaunch and permission settings the owner chose. Leave about
a fifth of the budget as headroom: the cap is an estimate that includes
subagents and can be overshot. To give the run an MCP server such as
InfraNodus, set `mcp_config` to a JSON file in the project. Limits belong here
because code enforces this file. A limit written only in the mission is a request.

## Phase 5: Propose instruction changes; edit nothing before the owner's yes

```bash
uv run --script "${CLAUDE_SKILL_DIR}/scripts/audit_rules.py" --project . --extra ~/.claude/CLAUDE.md
uv run --script "${CLAUDE_SKILL_DIR}/scripts/audit_rules.py" --project . --propose
```

Never edit an instructions file by hand. `--propose` writes the rewrite of
every **FIX** finding as a diff in `fable/RULES_PROPOSAL.md` and changes
nothing. Show the owner the diff and wait; only after a yes, run `--apply
--approved-by "<name>"`. **REVIEW** findings are the owner's call (a new
proposal, or `audit_accept`). **Owner rules are never rewritten** (marked
"(owner rule)", under an "Owner rules" heading, or rules like commit only when
the owner says, never edit a test to pass, one writer at a time, record every
decision). Each is HONORED or BLOCKS; a blocking one fails readiness, so tell
the owner which and leave the change to them.

## Phase 6: Write the mission and seed the ledger

Read `references/writing-the-mission.md` now. It has a weak and a strong
example for each section and one complete mission.

After preflight, build these files from the structured spec instead of by
hand. Complete `fable/handoff_spec.json`, run `spec_tool.py check` until it
says READY TO RENDER, then `render_handoff.py`, which writes the mission,
ledger, decisions and run settings. The checks are the same as in the steps
below, and the spec keeps each line tied to its source document. Query it with
jq (`include "handoff"; summary`). `references/handoff-spec.md` has the fields,
the jq queries and the editing recipes. Without a spec, write the files by hand:

1. **`fable/MISSION.md`.** Replace every `{{FILL: ...}}` marker. Write the Job
   as a whole outcome and the Why as the reason and the priorities. Put the
   commands you ran in phase 1 under "Where things are". Fill the three
   Guardrails lists from the interview, and make sure every forbidden item is
   also enforced in `fable/handoff.json`. Quote the verify command in Done
   exactly as it stands in `fable/handoff.json`.
2. **`fable/STATE.md`.** Seed the task list with the parts of the Job, each as
   an unchecked `- [ ]` item that names its proof: ``(check: `command`)``.
   The stop gate runs that command for each checked task, so a checkbox alone
   cannot end the run. A relaunched session resumes from this file.
3. **`fable/DECISIONS.md`.** Check that every interview answer is there with
   its reason, and that "Open questions for the owner" reads `None.` If a
   question is still open, put it to the owner now.
4. **Commit** the package and your instruction edits on the run branch.

Do not write anything in these files that needs a person, such as "ask me",
"check with the owner" or "wait for approval", and do not ask the model to
explain its reasoning. The first stalls the run, and the second can be
refused.

## Phase 7: Prove readiness, get the owner's sign-off, look back

```bash
uv run --script "${CLAUDE_SKILL_DIR}/scripts/readiness_check.py" --project . --extra ~/.claude/CLAUDE.md
```

The check tests the config, mission, ledger, decisions, branch, git state,
secrets, instructions and the installed CLI's flags. It runs the verify
command once (it must fail) and feeds the hooks made-up tool calls. Fix every
`FAIL` row, commit, rerun. Settle every `WARN` with the owner where it concerns
cost or risk. A `mission wording` WARN quotes each "never" or "always" used as
an order: give it scope and reason, or keep it only if it has no exception.
`--allow-dirty` and `--allow-passing-baseline` are for cases the owner understands.

With a spec, run `spec_tool.py brief`, give the owner `fable/OWNER_BRIEF.md`,
and only after they say yes run `spec_tool.py signoff --by NAME`. The sign-off
is bound to a hash of the spec, so any later edit voids it.

Then read `fable/MISSION.md` cold, as if it were all you had (checklist in
section 10 of `references/writing-the-mission.md`). The launcher refuses a
mission, rules file or config changed after the last passing check.

Last, look back: `system_review.py` reads everything gathered (preflight,
spec, readiness, conversation context, earlier lessons) and writes
`fable/IMPROVEMENTS.md` (fix before launch, keep in the project, improve the
skill). Settle the first list with the owner. If InfraNodus is connected, run
a gap analysis on the mission and brief too.

## Phase 8: Launch with fable/launch.py and hand back

Show the owner `uv run --script fable/launch.py --dry-run`, and start only when they
say so, so that it outlives the terminal:

```bash
nohup uv run --script fable/launch.py > fable/.run/launch.out 2>&1 &
```

The launcher refuses to start if a hook script is missing or the owner has
answers not yet imported (`fable/questions.py import`). It relaunches an
unfinished run within `max_relaunches` and the budget, continues a
conversation only when its context is unchanged, and logs MCP servers that
failed to connect. Never add `--bare`: it skips the hooks. Details are in
section 5 of `references/claude-code-setup.md`.

Hand back: what was launched, on which branch and budget; how to watch it
(`git log`, `fable/STATE.md`, `fable/.run/`); the exit codes (0 finished,
1 unfinished, 2 refused, 3 blocker, 4 parked: the rest waits on answers in the
question system); that phase 9 follows; and,
on a laptop, to prevent sleep.

## Phase 9: Review with post_run_report.py and the diff

```bash
uv run --script "${CLAUDE_SKILL_DIR}/scripts/post_run_report.py" --project .
```

It re-runs the verify command and prints `CLEAN` or `NEEDS REVIEW` with
reasons: unchecked tasks, failing verify, uncommitted changes, deleted or
weakened tests, changed protected files, an exhausted stop gate, a blocker, a
missing report. It lists evidence for each checked task, reads the run's
transcripts, counts guard blocks, and writes `fable/.run/lessons.json`, which
the next preflight turns into decisions, traps and questions.

Then read `fable/REPORT.md`, the diff from the base commit, and the "Made
during the run" and "Left for the owner" sections of `fable/DECISIONS.md`.
Report to the owner: outcome, proof, decisions to review, unrequested changes,
what is left. `CLEAN` means no warning sign, not that the work is right. Do
not merge, push or deploy unless the owner names that action. After a blocker
or an unfinished run, follow section 9 of `references/claude-code-setup.md`:
record the answer, delete `fable/BLOCKED.md`, commit, recheck, relaunch.

## Keeping this skill correct

The skill depends on interfaces that change: Claude Code's hooks, CLI flags,
permission modes and subagent settings, and Fable's documented behavior.
`references/sources.md` lists each official page, what the skill relies on
from it, and when that was last verified. When Claude Code or the model
changes, or a run behaves unexpectedly, re-read those pages, fix what moved,
and record the date. The readiness check confirms the launcher's flags
against the installed CLI on every run.

