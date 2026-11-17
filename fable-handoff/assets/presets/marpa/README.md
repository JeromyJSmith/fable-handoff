# The MARPA preset

The MARPA preset makes a Fable 5.2 run follow MARPA's detective standard. MARPA Design Studios is a landscape architecture and design-build construction firm in Boulder. The project root for a run is MARPA's budget standard repository (`ontology-duckdb`). Every path below is relative to that root.

```bash
uv run --script scripts/init_handoff.py --project <MARPA repo> --preset marpa --branch fable/marpa-1
```

## Contents

- What the preset sets
- The Jev decision framework, and where it applies
- The back-test on the owner's ruled cases
- Rebuilding the decided cases
- Still planned

## What the preset sets

| Area | In preset.json | MARPA source |
| --- | --- | --- |
| Detective functions | `detective_functions`: MARPA's eleven functions plus takeoff from geometry (`vwx/out/vwx_geometry.duckdb`), six of them planned | `detective_functions.yaml`, `docs/standard/DETECTIVE_STANDARD.md` |
| Evidence ladder | `evidence_ladder`: drawings and models, the project's budget, the standard and class vocabulary, rulings and decisions, the firm's own words, outside standards, back-tests | CLAUDE.md rule 12 |
| Units and tolerances | `quantity_tolerance`: area 5%, length 5%, count exact, volume 10%, weight never compared, flats and pallets counted only | `detective_functions.yaml` |
| Questions for the firm | `question_system`: BCF 3.0 at `bcf/fable-questions.bcf` | MARPA's own `bcf/marpa-questions.bcf` is written only by `bcf_questions.py`, so the run keeps its own file |
| Decisions log | `decisions_log`: `DECISIONS.md` | |
| Adjudication | `adjudication_policy`: Jev, every schema in `jev_schemas.yaml` with its companions and post-checks, abstain answer `OTHER`, review floor 0.50, escalation at 0.50, receipts required | `jev_schemas.yaml`, `jev_schema.py` |
| Threshold | `adjudication_threshold` 0.90 until a back-test writes `fable/calibration.json` | `detective_cutoff.json` |
| Question triage | `question_triage`: firm-choice words (design intent, client preference, allowance, fee policy, insurance rate) and fact words (dimensions, labels, quantities, species, units, slots) | |
| Owner rules | `owner_rule_headings` and `owner_rules`: all thirteen rules of MARPA's CLAUDE.md are recognised and honored | CLAUDE.md |
| Guard | `protected_paths` (rulings, Jev schemas, the cutoff file, the writer lock, DuckDB files, the budget workbooks, MARPA's BCF file, CLAUDE.md, AGENTS.md, archives, Jev receipts); `blocked_bash_patterns` (the desk app's Pixeltable, mail, GitHub issues and pull requests, breaking the writer lock); `writable_outside_paths` (the firm's task log) | CLAUDE.md rules 1, 7 and 10 |
| Verify command | `uv run pytest -q tests && uv run budget_backtest.py --check`: the run writes `budget_backtest.py`, which generates each past project's budget from its drawing and compares it with the real one; it fails until that holds | The owner's direction, 2026-11-16 |
| Mission and rules | `MISSION_MARPA.md`: the product (a dropped drawing becomes a priced, editable budget), the five steps (takeoff from geometry, the back-test against real budgets, Solomon's first estimate, intake ending in the budget, the API for the desk), what is out of scope, where things are, and MARPA's definition of done. `OPERATING_RULES_MARPA.md` | The owner's direction, 2026-11-16 |

The standard files (MARPA_STANDARD.md, the class vocabulary, the master slots) are not protected, because the owner's rule 4 says a fix goes into them in the same task.

## The Jev decision framework, and where it applies

The framework is [disler/ten-levels-of-jev](https://github.com/disler/ten-levels-of-jev): Jev answers one typed question (yes or no, a choice among listed options, or a score), returns a probability, and code owns the threshold. Its ten levels:

| Level | In one sentence | Where it lives in the skill now |
| --- | --- | --- |
| 1. Single decisions | One yes or no question, with the threshold in code. | Companion questions in an adjudication record (`detective.py` `adjudication_problems`, `escalate_noul`). |
| 2. Multiple choice | One option from a declared list; several questions in one call. | The adjudication answer must be one of `offered`; the abstain exit `OTHER` is never applied (`adjudication_problems`). MARPA asks the choice and its companions in one call (`jev_schema.ask`). |
| 3. Composite scoring | One score per factor, weights kept in code. | Not used: a case's verdict comes from written rules over evidence strength (`detective.verdict`), not a weighted score. The handoff keeps those rules fixed. |
| 4. Confidence gating | The answer says what, the confidence says whether: a floor and a bar. | `detective.py` `adjudication_band` (auto, review, low) and `threshold`; the bar is measured by `detective_backtest.py` `calibrate` with `--min-accepted`. |
| 5. Intent and model routing | One cheap decision in front of expensive work. | The verdict routes each case: settled and fact cases stay in the queue, only open policy reaches the BCF file (`detective.verdict`, `questions.py` routing); `preflight.py` `triage_question` sorts questions first. The subagent models in `assets/agents/` route work by cost. |
| 6. Guardrail hooks | Jev in the tool call hook, unseen by the agent. | The guard hook `fable_guard.py` is rule based (protected paths, blocked commands, companion repositories). A Jev judgment there is planned, not built: hooks must stay standard library only. |
| 7. Should I compact | Questions after every turn about whether the context moved on. | Does not apply: Claude Code compacts on its own, and `fable_session_context.py` restores the mission after compaction. |
| 8. Cheap reads | A judgment about a file without loading it. | Not built. It would fit the evidence ladder (asking whether a sheet export names a class); planned. |
| 9. Files at scale | The same questions over many files in parallel. | Not built in the skill; MARPA's own `preflight_jev.py` asks Jev per class over every project. |
| 10. Agentic Jev | The agent writes its own questions. | Deliberately not allowed for decisions: no schema, no call (MARPA rule 5). A run may only ask schemas written in `jev_schemas.yaml`, which the guard protects. |

Its rules: one snap judgment per question; ask every question in one call (fan out); numbers stay in code; confidence is a second axis; give the model an exit option; describe situations, not degrees; questions and thresholds in one reviewable file; send only the state the question needs; a second call only for a real dependency; prune options in code.

| Place in fable-handoff | What the framework changes | What was done |
| --- | --- | --- |
| Adjudication in `detective.py` | The answer must come from a written schema, be one of the options offered, and pass a confidence gate | `adjudication_problems` checks schema, offered options, the abstain exit, companions, post-checks and receipt when `adjudication_policy` is set (generic engine; MARPA's values in the preset) |
| Threshold and bands | Level 4: floor, bar and the middle | `adjudication_band`: auto, review, low. Only auto settles; review and low keep the answer as the suggestion, like MARPA's firm section |
| Companions | Level 2 fan-out: yes or no questions asked in the same call | An escalating companion at or above 0.50 sends the answer to review; MARPA's `same_concept` and `covers_term` never escalate |
| Post-checks | Numbers and rules stay in code | Each schema's post-checks must have run and passed |
| Receipts | The full request and response kept | `require_receipt` |
| Back-test calibration in `detective_backtest.py` | The threshold is measured, never assumed | `--min-accepted` (MARPA: 10 answers at 90% right); a cutoff table; blind adjudications take part in the verdicts under the measured threshold |
| Verdict rules | Unchanged (the handoff's do-not-change list) | Adjudication only lifts a likely case whose one strong source it agrees with |
| Settled versus policy routing | Level 5: a cheap decision in front of the expensive one | Already the case: settled, likely and open fact stay in the queue; only open policy reaches the BCF file. No change |
| Question triage in `preflight.py` | Describe situations, not degrees; give an exit | Project and preset cue words; a fact word overrides a generic preference word, a firm-choice word always wins |
| Schema-first questions in `questions.py` and the decision interview | Every question has declared options with what each does, and an exit | Already required: options with consequences, a recommendation, plain words, no bare codes. No change |
| Guardrails (level 6) | A check in the tool call hook | The guard hook stays rule based; the preset adds MARPA's paths and commands. A Jev bash gate is planned, not built |

## The back-test on the owner's ruled cases

Run on 2026-11-16 against the 37 classes the owner has ruled on, exported from MARPA's data at commit 42b30c1. Each case's own ruling was removed before the verdict. Jev's answers were asked by MARPA with the ruling left out of the evidence (schema `class_slot`, model jev-1.13.0).

| Function | Pieces of evidence | Right | Accuracy |
| --- | --- | --- | --- |
| name match | 114 | 102 | 0.895 |
| drawing content | 3 | 2 | 0.667 |
| budget match | 28 | 5 | 0.179 |
| rules and precedent (other rules, once the case's own ruling is hidden) | 20 | 2 | 0.100 |

| Jev cutoff | Accepted | Right | Wrong | Accuracy | 95% lower bound |
| --- | --- | --- | --- | --- | --- |
| 0.50 | 37 | 32 | 5 | 0.865 | 0.72 |
| 0.60 | 37 | 32 | 5 | 0.865 | 0.72 |
| 0.70 | 36 | 32 | 4 | 0.889 | 0.75 |
| 0.80 | 36 | 32 | 4 | 0.889 | 0.75 |
| 0.88 | 35 | 32 | 3 | 0.914 | 0.78 |
| 0.90 | 34 | 31 | 3 | 0.912 | 0.77 |

**Is 37 enough?** No. At 0.90, 31 of 34 right is 91%, but with so few cases the true rate could be as low as 77% (95% Wilson interval). The difference between 0.88 and 0.90 is one answer at exactly 0.88. To show at least 90% with confidence needs about 100 accepted answers with no more than 5 wrong. No class has been ruled since the 37 (class_rulings.yaml still holds 37 on 2026-11-17); each new ruling is added by running the export again.

Calibrated threshold: **0.88**, the lowest confidence at which at least 10 answers were at least 90% right. MARPA's own blind test, which steps in tenths, gives 0.90; both accept the same answers above 0.90.

Verdicts: 29 right (all settled by adjudication), 1 wrong, 7 open. The wrong one is the class whose name and project document both say groundcovers, which the owner ruled flatwork; MARPA's own blind test gets it wrong the same way. MARPA's test reports 28 of 29; the one extra right answer here is a case Jev answered between 0.88 and 0.90.

## Rebuilding the decided cases

`decided_cases.json` names client projects, so it is not in this public repository. Rebuild it on the owner's machine, read only:

```bash
uv run --script assets/presets/marpa/export_decided_cases.py --marpa <MARPA repo> --out assets/presets/marpa/decided_cases.json
uv run --script scripts/detective_backtest.py --project <project> --cases assets/presets/marpa/decided_cases.json --min-accepted 10 --target 0.9 --write-calibration
```

## Two repositories

The run's home is the standard repository: decoding, takeoff, pricing, the API and the back-test, on the run branch. The desk app is a companion repository (`companion_repositories` in handoff.json):

- the readiness check refuses to launch unless the desk repository is on its own run branch (`fable/marpa-1`, never main) and has no uncommitted changes;
- the guard allows writes inside it and applies the protected paths there too, for file tools and shell commands;
- the verify command runs both test suites: `uv run pytest -q tests`, then `bun run test` in the desk, then the budget back-test.

What is still missing for two repositories: the stop gate and the post-run review look only at the home repository's commits and diff; the desk's own CLAUDE.md is not audited unless it is passed with `audit_rules.py --extra`; and the launcher creates no branch, so the desk branch is made by hand before launch.

## Launch requirements

`launch_requires` in handoff.json makes the readiness check refuse a launch that depends on something missing:

- must be built before launch: name match, drawing content, text on the drawing, budget match, rules and precedent, adjudication (all built in MARPA);
- built by the run as its first tasks, each named in fable/STATE.md: takeoff from geometry, spatial relationships, the back-test against real budgets;
- files the mission starts from: PRODUCT_GOALS.md, SYSTEM.md, the VWX workflow, format notes and runner, intake.py, the estimating design and the desk revision plan.

## Budget tolerances

`budget_tolerance` in handoff.json, proposed from MARPA's quantity tolerances; the owner confirms or changes them:

| Level | Tolerance | Why |
| --- | --- | --- |
| A line's quantity | area 5%, length 5%, count exact, volume 10% | budgets round to whole units and add waste |
| A line's total | 10% | quantity within 5% times the project's own rate, plus rounding |
| A slot's total | 7.5% | over and under on lines in one slot partly cancel |
| The project total | 5% | the firm prices to the total; more than 5% would change a bid |

## Trial on a copy (2026-11-17)

Init with `--preset marpa` and the readiness check on a scratch copy of the MARPA repository (the real one untouched). Passed: the configuration, the detective functions (every source found), the owner rules (all 13 honored), the guard, the hooks, the git branch. Failed, each for a real reason:

- the mission, ledger and decisions files still hold their fill-in markers (the preparing agent writes them);
- launch requirements: takeoff, spatial relationships and the back-test are not yet tasks in STATE.md, and PRODUCT_GOALS.md does not exist yet;
- the desk repository is on main with uncommitted changes, so the companion check refuses;
- the verify command could not run on the copy, because the copy left out the archive and vendor folders some tests read; on the real repository it fails until budget_backtest.py exists, as it should. The trial showed that a missing script reads as "cannot run" and would block the launch, so the verify command now checks `test -f budget_backtest.py` first: it fails quietly until the run writes the script.

Warnings: ten lines in AGENTS.md name absolute paths (review, not a block), and no spending cap is set.

## Still planned

- Spatial relationships, the firm's own words, outside standards for cases, the estimating back-test and gap analysis are planned functions in MARPA too.
- Writing cases to MARPA's `detective_case` and `detective_evidence` tables through the pipe.
- Opening `bcf/fable-questions.bcf` in a real BCF tool, and merging its topics into MARPA's own question file.
- A Jev bash gate in the guard hook (level 6).
