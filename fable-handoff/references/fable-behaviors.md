# How Fable 5.2 behaves, and what each behavior means for a handoff

## Contents

1. How to use this file
2. Effort
3. Early stopping
4. Literal rule following and approvals
5. Code ownership
6. Silence during long turns
7. Subagents
8. Caution that accumulates
9. Instructions written for older models
10. Final reports
11. Refusals
12. Model choice and switching
13. Quick map: behavior to package part
14. Detective work before judgment calls

## 1. How to use this file

Read this before you interview the owner, and again when a line in an
instructions file makes you unsure whether it will hurt the run. Each section
states what the model does, then what you should do about it, then which part
of the handoff package already deals with it.

The facts come from Anthropic's "Prompting Claude Fable 5.2" guide
(https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-2).
The figures are from Anthropic's own testing as reported there. They describe
tendencies, not guarantees, and the guide may have changed since this file was
written. Check it before you quote a number to the owner.

## 2. Effort

Effort is a setting, not a prompt. It controls how much the model thinks, how
many tool calls it makes, how long a turn takes and how many tokens it uses.
It does not change how long or how formal the replies are. If you want shorter
replies, you have to ask for them in words.

| Level | Suited to | What to expect |
| --- | --- | --- |
| low | quick exchanges, tasks that are fully specified, subagents run in bulk | the level most likely to stop early |
| medium | interactive coding, chat, planning together with the model | |
| high | hard coding, research, agentic work, long unattended runs | the API default, and where most of the gain is |
| xhigh | the hardest long-running work, where a gain was measured | a small gain in scores for many more tokens |
| max | finding the ceiling, open-ended science and math | slow, and far more tokens again |

At medium effort and above, the model thinks before it replies even when the
prompt tells it not to. A line such as "answer directly" no longer switches
thinking off. At high and above it thinks before nearly every reply.

**What to do:** set `effort` to `high` for the run. Do your own preparation
work interactively at medium. Move to `xhigh` only if the owner has seen `high`
fall short on this kind of work, because the extra cost is large and the gain
is small.

**In the package:** `effort` in `fable/handoff.json`, passed to the CLI by
`fable/launch.py`. The readiness check warns when it is not `high`.
`audit_rules.py` reports "think less" lines as `think-less`.

## 3. Early stopping

On long work with many steps, the model sometimes ends its turn before the
work is done. It does this in three ways: it lists what is left, it offers to
continue, or it stops at an ordinary obstacle such as a timeout. This happens
more at low and medium effort.

A persistence instruction in the system prompt roughly halved the sessions
that ended with doable work left, at a cost of about 30 percent more output
tokens. It removed most endings that ask for permission or offer to continue.
It did not remove endings that list the remaining work and then stop.

**What to do:** do not rely on words alone. Tell the model to keep going, and
also make "done" something a program checks, so that a stop that comes too
early is caught and reversed. Tell it the difference between an ordinary
obstacle, which it should work through, and a deliberate blocker, which it
should leave alone. Without that distinction, "keep going" can turn into
"force your way past the limit".

Because the persistence instruction makes the model ask less, do not protect
irreversible actions with "ask first". Nobody is there, and the model has been
told not to wait. Protect them with code.

**In the package:** `fable/OPERATING_RULES.md` carries the persistence
instruction and the obstacle and blocker distinction. The Stop hook
(`fable_stop_gate.py`) enforces completion: it blocks a stop while tasks are
open, the verify command fails or the report is missing. The PreToolUse hook
(`fable_guard.py`) blocks writes to protected paths and forbidden shell
commands.

## 4. Literal rule following and approvals

The model applies rules very close to the letter. "Never" is treated as
absolute. A broad approval rule holds back routine work that its author never
meant to cover. In one test, a rule that messages to people outside the
conversation need approval made the model hold back about half of its routine
requests to colleagues.

Approvals are read just as literally. In a conversation, an approval works
when it names the action: "Yes, run the migration on the staging database",
not "go".

**What to do:**

- List pre-approved actions by name.
- List forbidden actions by name, each with its reason. The reason lets the
  model tell what the rule protects, so that it applies the rule to the cases
  you meant.
- Do not write "ask before" anywhere. Every action that would have needed
  approval must be sorted in advance into one of three groups: pre-approved,
  forbidden, or "skip it and leave it for the owner".
- Read every existing rule as the model will: literally, with nobody to ask.

**In the package:** the three Guardrails lists in `fable/MISSION.md`, the
Decisions section, and `fable/DECISIONS.md`. `audit_rules.py` reports
`needs-human`, `asks-human` and `absolute` lines. The readiness check fails a
mission that says "ask me" or "wait for my approval".

## 5. Code ownership

How the model treats code depends on whose it thinks the code is. With no
statement of ownership, or when the code is presented as someone else's, it
adds to the existing structure even when that duplicates code, and it reports
problems nearby without fixing them.

Told that the codebase is its own, it consolidated duplicated code in about 75
percent of runs, against under 10 percent without the statement. That came
with costs. Output tokens rose 70 to 80 percent. It made changes nobody asked
for, many of them tests and documentation, and sometimes changed how an
existing feature behaves. Its closing summary often left out the small
changes. A "no drive-by refactors" rule earlier in the prompt did not cancel
the ownership sentence.

**What to do:** treat ownership as a switch that the owner sets on purpose.
Turn it on for greenfield work and for refactors the owner wants. Leave it off
for client code, shared code and any job where the owner wants as little
changed as possible. If it is on, expect a larger diff and review it for
changed behavior.

**In the package:** `init_handoff.py --ownership` adds an ownership paragraph
to `fable/OPERATING_RULES.md` and records `"ownership": true` in
`fable/handoff.json`. The paragraph also tells the model to list every change
the mission did not ask for, because its summaries tend to leave those out.

## 6. Silence during long turns

The model may write little between tool calls, and it may start working
without saying what it is about to do. A one-line instruction to give an
update every few tool calls removes most long silent stretches. An opening
line plus a closing recap adds about 20 percent to output tokens. Anthropic
recommends the model for asynchronous work, where nobody needs frequent
updates.

**What to do:** do not ask for chat updates in an unattended run. Nobody reads
them, and they cost tokens. Ask for progress to be written to a file instead,
where it is useful after the run and survives context compaction.

**In the package:** the ledger `fable/STATE.md`, which the operating rules
tell the model to update after each task.

## 7. Subagents

How much the model delegates depends on the harness around it. Where prompts
invite delegation, it delegates readily. At xhigh and max it has used
subagents to review its own work. Subagents can be a large part of what a
session costs. A subagent tool description that states what a subagent costs
roughly halved the number started at high effort. Early testers had good
results with Fable as planner and orchestrator over other models.

**What to do:** remove standing orders to delegate from the instructions the
run will load. Say what a subagent costs and when one is worth it. Pin a
cheaper model on each project subagent, so that delegated work does not run at
Fable's price.

**What the measurements say.** Anthropic's cost guide
(`optimizing-for-cost-and-intelligence`, see `sources.md`) compared set-ups on
one defect-search task:

| Set-up | Score (F1) | Cost per run |
| --- | --- | --- |
| Fable 5.2 alone, high effort | 0.909 | $563 |
| Fable 5.2 leading Sonnet 5.5 subagents | 0.833 | $165 |
| Opus 5.5 leading Haiku 5.5 subagents | 0.677 | $47 |

Delegation cut the cost by about two thirds and gave up some accuracy. On
chains of dependent work, the lead's model alone at lower effort did best.
Sonnet was the worker in every set-up that came close to Fable alone. No
official page recommends Haiku for anything beyond search, and none
recommends a general "route everything" team-lead pattern.

**In the package:** the "Work as a team lead" section of
`fable/OPERATING_RULES.md` follows these results. The lead keeps connected
work, fans independent pieces out to `fable-worker` (Sonnet), gives specified
independent pieces to `fable-builder` (Opus), uses `fable-scout` (Haiku) only
for reading and checks what it reports, and uses `fable-specialist` (Fable,
same price as the lead) only to keep a large isolated problem out of its own
context. The lead verifies every result. `audit_rules.py` reports standing
orders to delegate in other instruction files as `delegation`, and the
readiness check warns about any project agent without a pinned model.

## 8. Caution that accumulates

Cautious instructions build up over time in memory files, notes and
instruction files. Some were written by the model itself in earlier sessions.
Followed literally, they cause approval requests that nobody needs and stalls
that nobody sees.

The fixes that work:

- Delete notes that no longer apply.
- Name the steps that need no approval. Telling the model to "act more freely"
  is too vague to change what it does.
- Narrow stop conditions such as "stop at the first error" to the case they
  were written for.
- Write the exceptions to a rule out in full.

**What to do:** read every instructions file that will load during the run,
including instructions and memory files outside the project, and resolve each
cautious line. Do not delete a rule that matters in interactive use. Scope it
instead: "In interactive sessions, ...".

**In the package:** `audit_rules.py` finds these lines, and phase 5 of
SKILL.md resolves them. The `vague-autonomy` rule catches "be proactive" and
"use your best judgment".

## 9. Instructions written for older models

When a project's instructions were written for an earlier model, reconsider
these:

- **Standing instructions to delegate.** See section 7.
- **A token budget shown to the model.** Its size changes how much the model
  spends. Removing a large one lowered cost with equal results. Cap spending
  outside the prompt.
- **Harness code that edits earlier turns.** Fable 5.2 keeps its thinking
  across turns. Changing the system prompt, the tools or an earlier message
  invalidates it. Make instruction changes in a new conversation. This is why
  the package is fixed before launch and protected during the run.
- **"Treat that answer as done" lines** from the Opus 5.5 guide. They reduced
  thinking on follow-ups and made the model far less likely to point out its
  own earlier mistakes.
- **Instructions to think less.** No effect at medium and above.
- **Hard style rules** such as a word limit per sentence. The model keeps to
  them closely, which makes prose choppy.
- **Accumulated rules, notes and memories.** See section 8.

**In the package:** `audit_rules.py` has a rule for each: `delegation`,
`token-budget`, `answer-is-done`, `think-less`, `style-cap`. The spending cap
is `max_budget_usd` in `fable/handoff.json`.

## 10. Final reports

After long work, the reader has seen none of the tool calls or files, so the
report has to stand on its own. In testing, reports became less dense when the
model was asked to write for an intelligent reader with no context, to put the
key points first, to use plain words and to avoid terms it had invented during
the work.

**What to do:** ask for exactly that, and require the report to exist before
the run may end.

**In the package:** the Final report section of `fable/OPERATING_RULES.md`
gives the format. The stop gate requires `fable/REPORT.md`.
`post_run_report.py` flags a run without one.

## 11. Refusals

Safety classifiers can decline a request. The categories include cyber,
biology, help with developing competing AI models, and requests to reproduce
the model's internal reasoning in its reply. Benign security work and benign
life-science work can trigger the first two.

**What to do:**

- Do not ask for the model's reasoning anywhere: not in the mission, not in
  the rules, not in a skill the run will load. Ask for evidence instead: the
  commands run, their output, the sources and the assumptions.
- If the job is security work or touches biology, tell the owner before launch
  that some steps may be refused. Frame each task around its defensive purpose.

**In the package:** `audit_rules.py` reports requests for reasoning as
`reasoning-out`, a FIX finding. The operating rules ask for evidence and do
not ask for reasoning.

## 12. Model choice and switching

This section comes from early users, not from the prompting guide, so treat it
as guidance.

- Start most work on Opus 5.5 at medium effort.
- Use Fable 5.2 where Opus at high effort falls short, or for long unattended
  runs.
- Raise effort by one level before you move up a model.
- A common split is Fable for planning and deciding, and Opus for carrying out
  a written plan.
- Switch models at a natural break, in a new session, with a handoff file. A
  switch loses the earlier thinking and the prompt cache.

**What to do:** use this in phase 0 of SKILL.md to decide whether the job
should go to Fable at all. A short, well-specified task does not need this
package.

## 13. Quick map: behavior to package part

| Behavior | Risk in an unattended run | Part of the package that handles it |
| --- | --- | --- |
| Stops early with work left | Run ends half done | Persistence text in the operating rules, stop gate, relaunch by `launch.py` |
| Follows rules to the letter | Stalls on "ask first" or a broad "never" | Rules audit, named Guardrails, decisions made in advance |
| Asks less once told to persist | An irreversible action runs unasked | Guard hook, permission mode |
| Adds to code it does not own | Duplication, or unwanted refactors when it does own it | The `--ownership` switch |
| Works silently | No trace of progress | Ledger in `fable/STATE.md`, commit per task |
| Delegates when invited | Cost | Subagent section of the rules, pinned models |
| Dense reports | Owner cannot review | Report format, review script |
| Refuses reasoning requests | Lost turns | Audit rule `reasoning-out` |
| Asks instead of searching | The owner gets questions the project already answers; the run stalls | Judgment test in the mission and rules, `questions.py` refusing unsearched questions, readiness and stop gate checks |
| Treats a judgment call as a blocker | All work stops for one decision | Park and continue: the question goes to the project's question system, the task waits, the rest of the run goes on |

## 14. Detective work before judgment calls

In real projects most of what looks like a judgment call is detective work.
In one project, 175 of 183 open questions could be settled from evidence
already there: drawing text, detail titles, labels, the project's own budget,
existing rules, outside standards and back-tests against earlier work. A model
that asks instead of searching hands the owner work the project already did,
and an unattended run that waits on those answers stops for nothing.

**The judgment test.** A question may go to the owner only if both hold:

- (a) the evidence cannot decide it. The run searched every rung of the
  evidence ladder in `fable/handoff.json` (the project's files and data, its
  specs and standards, past decisions and rulings, the owner's notes and
  communications, outside standards and references, back-tests against
  earlier work) and recorded what each gave;
- (b) it is a matter of policy or preference, not a fact.

Every question raised records the evidence searched, what was found, why that
does not decide it, and what answer would settle it. `fable/questions.py`,
`decision_interview.py --check` and the readiness check refuse a question
without that record. A question the evidence settles is answered by the
preparing agent or the run and recorded as a decision "by evidence".

**Park and continue.** A true judgment call during the run goes to the
project's own question system (a BCF 3.0 topic, a row in the decisions table,
a GitHub issue, or `fable/open_decisions.json`). The task is marked "waiting
on owner" and the run continues with independent work. BLOCKED.md is only for
problems that stop all work. The next run imports the answers and resumes.

When concepts that should connect do not, run the gap analysis in
`references/gap-analysis.md`. Its bridges are leads to check, never answers.
