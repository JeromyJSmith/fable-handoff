# MARPA rehearsal: the package as it would launch

Made on 2026-11-17 on scratch copies of the three locations (the MARPA standard repository, the desk app at commit e50a89362 on fable/marpa-1 with its map, and the allocation engine with its three method documents taken from their committed text). Nothing was launched. The real repositories were only read.

**The six owner decisions are stand-ins.** Each was answered with the preparing agent's recommendation and the reason "STAND-IN for the rehearsal: the preparing agent recommendation, not the owner answer." They are not the owner's answers. Before a real launch the owner answers them with `decision_interview.py --project . --file fable/owner_decisions.json`.

**Client names.** The first new project's name is replaced here by `[first new project]`. The exact text, with the name, is in the shared notes folder outside git.

## Contents

- `single/`, `stage1/`, `stage2/`: for each shape, the files a launch would read:
  - `MISSION.md`, `OPERATING_RULES.md`, `STATE.md` (the ledger) and `DECISIONS.md`;
  - `handoff.json`;
  - `owner_decisions.json` (with the stand-in answers);
  - `cases.json`: empty, because no case exists before the run;
  - `decisions_log_appended.md`: the lines the stand-in answers added to MARPA's DECISIONS.md.
- Readiness, per shape (below)
- Expected effort (an estimate)
- Review checklist for the owner

## Readiness

With the stand-in answers in place, the readiness check gave:

| Shape | Passed | Failed | Warned |
| --- | --- | --- | --- |
| Single run | 29 | git clean | rules audit |
| Stage 1 | 27 | git clean | rules audit |
| Stage 2 | 29 | launch requires (by design: stage 1 must build takeoff and the back-test and write runs/done/stage1.json first) | rules audit |

New finding, **git clean**: MARPA's own test suite rewrites two tracked files, `docs/standard/evidence/accessibility/lines-dark-375.png` and `lines-light-375.png`. Each verify run leaves the repository changed, which the readiness check refuses, because the run's diff would show changes it did not make. One of these is needed, in MARPA's repository:
- the test writes those screenshots elsewhere;
- or they are ignored by git.

The rules-audit warning is ten lines in MARPA's AGENTS.md that name absolute paths. They are for review, and they do not block a launch.

The verify command (the three test suites, then the done check) took about 106 seconds and fails quietly until the run writes done_check.py, as intended.

## Expected effort (an estimate)

Basis:
- The ledger's tasks: 11 for the single run, 9 for stage 1, 6 for stage 2. Takeoff from geometry, the back-test and the desk cut are each large tasks.
- The settings: model claude-fable-5-2 at effort high, up to 3 relaunches, the verify command at about 2 minutes.
- Experience in this work: large tasks of this kind took about one to two hours of agent time each.

There is no measured Fable 5.2 run on this repository, and the skill's references give no per-token price. Treat every number below as an estimate.

| Shape | Run time | Relaunches | Tokens (input, mostly cached / output) | Spending cap set in the rehearsal |
| --- | --- | --- | --- | --- |
| Single run | 10 to 24 hours | 1 to 3 | 40M to 120M / 1.5M to 5M | 300 dollars |
| Stage 1 | 7 to 16 hours | 1 to 2 | 25M to 80M / 1M to 3M | 200 dollars |
| Stage 2 | 4 to 10 hours | 0 to 2 | 15M to 50M / 0.5M to 2M | 120 dollars |

The two stages together cost about the same as the single run. A stage 1 problem is found before any desk work starts. The spending caps (`max_budget_usd`) are stand-ins too; the owner sets them, and the run stops at the cap.

## Review checklist for the owner

The ten points in the mission most likely to go wrong, and what the system does about each:

1. **The allocation engine is changed.** The mission forbids it, and the guard blocks file edits outside the run's repositories. A shell command can still write there; the guard does not block shell writes outside the project. Check the engine folder's `git status` after the run.
2. **A calculation calls a language model.** The readiness check and the stop gate both scan the calculation code (`deterministic_code`) and refuse a model call.
3. **A gap is closed by changing the real budget or a tolerance.**
   - The guard protects the budget workbooks (`inputs/Financials`), the owner's rulings, the Jev schemas, the cutoff file and handoff.json, where the tolerances live.
   - The operating rules forbid it.
4. **A test is weakened to pass.** MARPA's rule is recognised as an owner rule, and the stop gate's message says to fix the work, not the check. Tests are not protected paths, so review the test diff.
5. **A project's own budget is used to estimate it.** No guard can see this. The done check's held-out row and its tests must prove it, so read the back-test code first.
6. **The desk's budget section stops working.**
   - The verify command runs the desk's tests.
   - The definition of done needs the walkthrough to pass.
   - No automated walkthrough exists yet: done_check.py must include it, so check that it does.
7. **The working database is written without the lock.** MARPA's owner rule is honored, `.writer.lock` and the DuckDB files are protected from file edits, and writes go through run_pipeline.sh.
8. **Something reaches outside: client mail, the desk's Pixeltable home, a push or a pull request.** The guard blocks these commands. The budget therefore cannot be published through the desk's Pixeltable projection; the mission feeds it through the Standards API.
9. **The run stops early, or waits for an answer.**
   - The stop gate keeps it going until every task is done and verify passes.
   - It is relaunched up to 3 times.
   - A true policy question is parked as a BCF topic with its evidence while the work continues.
10. **The run's diff includes files the tests rewrote** (the two screenshots above). The readiness check refuses until MARPA's repository stops rewriting them. Review the diff for generated files.
