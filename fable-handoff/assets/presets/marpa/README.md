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

1. Single decisions: one yes or no question as a smart if statement.
2. Multiple choice: one option from a declared list, several questions in one call.
3. Composite scoring: one score per factor, weights kept in code.
4. Confidence gating: the answer says what, the confidence says whether. A floor below which a person decides, a bar above which the action runs.
5. Intent and model routing: one cheap decision in front of expensive work.
6. Guardrail hooks: Jev in the tool call hook.
7. Should I compact: questions after every turn.
8. Cheap reads: a judgment about a file, never the file.
9. Files at scale: the same questions over many files in parallel.
10. Agentic Jev: the agent writes its own questions.

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

| Jev cutoff | Accepted | Right | Accuracy |
| --- | --- | --- | --- |
| 0.50 | 37 | 32 | 0.865 |
| 0.70 | 36 | 32 | 0.889 |
| 0.90 | 34 | 31 | 0.912 |

Calibrated threshold: **0.88**, the lowest confidence at which at least 10 answers were at least 90% right. MARPA's own blind test, which steps in tenths, gives 0.90; both accept the same answers above 0.90.

Verdicts: 29 right (all settled by adjudication), 1 wrong, 7 open. The wrong one is the class whose name and project document both say groundcovers, which the owner ruled flatwork; MARPA's own blind test gets it wrong the same way. MARPA's test reports 28 of 29; the one extra right answer here is a case Jev answered between 0.88 and 0.90.

## Rebuilding the decided cases

`decided_cases.json` names client projects, so it is not in this public repository. Rebuild it on the owner's machine, read only:

```bash
uv run --script assets/presets/marpa/export_decided_cases.py --marpa <MARPA repo> --out assets/presets/marpa/decided_cases.json
uv run --script scripts/detective_backtest.py --project <project> --cases assets/presets/marpa/decided_cases.json --min-accepted 10 --target 0.9 --write-calibration
```

## Two repositories

A handoff prepares one project. This preset's project is the standard repository (API, takeoff, pricing, back-test). The desk app (`/Volumes/MARPA/apps/marpa-desk`) is its own repository, so its screens are a second run, prepared with this preset on that repository once the API holds; the mission lists it as out of scope. A preset variant for the desk repository is planned.

## Still planned

- Spatial relationships, the firm's own words, outside standards for cases, the estimating back-test and gap analysis are planned functions in MARPA too.
- Writing cases to MARPA's `detective_case` and `detective_evidence` tables through the pipe.
- Opening `bcf/fable-questions.bcf` in a real BCF tool, and merging its topics into MARPA's own question file.
- A Jev bash gate in the guard hook (level 6).
