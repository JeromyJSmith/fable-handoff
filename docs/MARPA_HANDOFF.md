# Handoff: developing fable-handoff for MARPA

You are taking over development of the **fable-handoff** skill on the
`marpa` branch. The goal of the branch is a MARPA-specific configuration of the
skill: MARPA's detective functions, evidence ladder, question system, owner
rules and units, so that a Claude Fable 5.2 run on a MARPA project follows
MARPA's detective standard. Read this whole file before changing anything.

## 1. Where things are

| Item | Value |
| --- | --- |
| Repository | https://github.com/JeromyJSmith/fable-handoff (public, MIT) |
| Default branch | `main`, at v1.3.1 (commit 2c0700c) |
| This branch | `marpa`, created from main at v1.3.1 |
| Releases | tags `v1.1.0`, `v1.2.0`, `v1.3.0`, `v1.3.1` (each a GitHub release) |
| Owner | Jero (GitHub JeromyJSmith), Technical Strategy Partner at MARPA Design Studios, Boulder, CO |
| Skill folder | `fable-handoff/` (this is what gets installed) |
| Live user guide | https://claude.ai/artifact/SuJs4jg2YGcp7kqd1qGbQU (`docs/USER_GUIDE.md` summarises it) |
| Install a ref | `curl -fsSL https://raw.githubusercontent.com/JeromyJSmith/fable-handoff/<ref>/install.sh \| bash -s -- --ref <ref>` |

## 2. Working rules (the owner's, not optional)

- **uv is the only Python manager.** Every script and hook starts with
  `#!/usr/bin/env -S uv run --script` and a PEP 723 block
  (`requires-python = ">=3.11"`), and runs as `uv run --script <file>`. Never
  write a bare `python3` or `pip` command anywhere, code or docs. A
  third-party package is allowed only pinned exactly (`networkx==3.7` in
  `gap_analysis.py`); hooks stay standard library only. A test enforces all
  of this.
- **Tests:** `uv run pytest` from the repo root (287 tests, about 3.5
  minutes). Run them after every change. Fix the code, never weaken a test;
  change a test only when the requirement changed, and say so.
- **No CI and no pull requests.** The owner removed CI and does not want PRs.
  Commit straight to the branch you are working on. Merge to `main` only when
  the owner says so.
- **Writing style for docs and messages:** plain words, direct, no em dashes
  (a test fails on any em dash in the skill). Owner-facing questions never
  lean on bare codes like "D121" or "rule 12".
- **Commit attribution:** end commit messages with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and the session
  line your environment gives you.
- **Do not stop for go-ahead on agreed work**; the owner checks results. Do
  not assign tasks to the owner.

### Pushing

In the previous session the cloud workspace had no working GitHub token, so
every push went through the owner's logged-in Chrome using GitHub's upload
page (`/upload/<branch>`) with a scripted file attach that keeps folder paths,
then a fetch to confirm the remote matched the local commit byte for byte.
If your environment has `git push` or `gh` credentials, use them instead. If
it does not, the same browser route works; deletions go through
`/delete/<branch>/<path>`.

Known account state: GitHub showed a billing problem on the account, which
blocks Actions (irrelevant now that CI is gone). Dependabot pull request #2
(a pytest security bump) is still open; the owner has not decided on it.

## 3. How the skill is built

```
fable-handoff/
  SKILL.md                       the procedure, phases 0 to 9 (kept under about 5,500 tokens; a test enforces it)
  references/                    deeper guides, each with Contents
    detective-standard.md        cases, functions, strength, verdicts, back-test, deriving a project's functions (section 7)
    fable-behaviors.md           how Fable 5.2 behaves; section 14 is detective work and park and continue
    gap-analysis.md              InfraNodus or the built-in graph; gaps are leads, never decisions
    claude-code-setup.md         hooks, permission modes, every handoff.json key
    preflight.md, conversation-context.md, handoff-spec.md, writing-the-mission.md, sources.md
  scripts/                       run by the preparing agent
    preflight.py                 maps goal, spec, standards, state, history, evals; sorts questions into evidence or judgment
    conversation_context.py      rebuilds context from Claude Code JSONL logs (jq module assets/jq/conversations.jq)
    decision_interview.py        owner interview on judgment calls only; --settle records evidence answers
    gap_analysis.py              concept graph gaps and bridges (networkx 3.7)
    detective_backtest.py        blind scoring of the detective standard on decided cases; calibrates adjudication
    init_handoff.py              writes the package; settings diff opt-in; --uninstall
    audit_rules.py               instruction audit; owner rules never rewritten; --propose / --apply --approved-by
    spec_tool.py, render_handoff.py   structured spec (JSON Schema) and rendering into the mission files
    readiness_check.py           the READY gate before launch
    post_run_report.py, system_review.py   review and look-back
  assets/
    templates/                   copied into each project's fable/
      MISSION.md, OPERATING_RULES.md, STATE.md, DECISIONS.md
      launch.py                  the unattended launcher (exit 0 done, 1 unfinished, 2 refused, 3 blocker, 4 parked)
      questions.py               judgment test, park, settle, import, route; json/markdown/BCF 3.0/GitHub adapters
      detective.py               case model, registry check, quantity tolerance, verdict rules, CASES.md
    hooks/                       fable_guard.py (PreToolUse), fable_stop_gate.py (Stop), fable_session_context.py
    agents/                      fable-scout (Haiku), fable-worker (Sonnet), fable-builder (Opus), fable-specialist (Fable)
    jq/, schema/handoff_spec.schema.json
  evals/                         three behaviour cases for claude plugin eval
tests/                           acceptance suite (conftest.py has the sample slug project and SLUG_FUNCTIONS)
docs/SPEC.md                     build contract, with sections for 1.2 and 1.3
```

Per project, init writes `fable/handoff.json` (the run's configuration),
the templates above, the hooks into `.claude/hooks/` and the four agents into
`.claude/agents/`. Everything MARPA-specific should live in configuration
that init writes, not in forks of the engine.

## 4. What MARPA needs (from the owner's MARPA detective standard)

The owner's MARPA standard, which this branch must serve:

- Every investigation is a case: subject (a class, layer, budget line, term,
  fee or setting, in one project), question, candidates, evidence, verdict,
  record.
- Eleven detective functions, each in a registry with what it looks at, what
  it returns, strength, built or planned, and a test:
  1. Name match: normalized name against the class vocabulary, terms and
     aliases, using the class-word grammar (family, head, modifiers). Strong
     for an exact term, weak for a single word.
  2. Drawing content: object types in the class, counts, sizes, areas and
     lengths, layers and sheets. Supporting.
  3. Text on the drawing: labels in the class, callouts, labels whose leader
     or position points at its objects, detail titles, sheet notes. Strong
     when a label names it.
  4. Spatial relationships: nearness, containment and adjacency to placed
     classes (a wall beside a pool; a material inside a detail frame).
     Supporting; strong for containment in a titled detail.
  5. Budget match: the same project's budget lines, matching words and
     quantities that agree with drawn geometry. Strong when the quantity
     agrees.
  6. Rules and precedent: the standard's rules, the owner's rulings and
     recorded decisions. Decisive.
  7. The firm's own words: email, Notion, voice memos through connectors.
     Strong when explicit.
  8. Outside standards: IFC/bSDD, Wikidata, NAICS, MasterFormat through the
     source registry. Strong for definitions and codes.
  9. Back-test: estimate a past project from the others and compare with its
     cost (for estimating settings). Decides parameters.
  10. Gap analysis: InfraNodus content gaps and bridges. Leads only.
  11. Adjudication: Jev, under a written schema, when evidence leans but does
      not settle. Needs 0.70 or more (calibrate it; see below).
- Verdicts: settled, likely, open fact, open policy (to the BCF file with the
  full case; the work continues).
- Case storage in MARPA's own pipe: `detective_case` and `detective_evidence`
  tables, served by `GET /cases` and `GET /cases/{id}`; the standard written
  as `docs/standard/DETECTIVE_STANDARD.md` in MARPA's repo (also in its Docs
  tab and CXML).
- Proof: a test set of cases already decided by the owner's rulings, run
  blind, scored per function. Then the 183 open questions (in one project,
  175 were settleable from evidence), then the VWX intake on top.

The skill already implements the generic version of all of this in
`detective.py`, `questions.py` and `detective_backtest.py`, including six
fixes the owner accepted: independence by underlying source, a calibrated
adjudication threshold kept apart from evidence verdicts, conflicting
decisive sources go to the owner as policy, quantity tolerance with unit
conversion, the back-test hides each case's own ruling, and plain-words
owner questions.

## 5. What can be made MARPA-specific, and where

Prefer a MARPA preset (configuration plus small adapters) over changing the
engine. Suggested shape: `fable-handoff/assets/presets/marpa/` holding the
pieces below, and an `init_handoff.py --preset marpa` flag that merges them
into `fable/handoff.json` and copies the extra files. Keep `main` generic.

| Area | File and place | MARPA change |
| --- | --- | --- |
| Detective functions | `handoff.json` `detective_functions`; defaults in `assets/templates/detective.py` `DEFAULT_FUNCTIONS` | The eleven functions above, each with `project_sources` pointing at real MARPA locations (VWX exports, sheet text exports, budget worksheets, decisions log, Notion/email/voice memo connectors written as `connector: ...`, IFC/bSDD and MasterFormat as `external: ...`). Mark unbuilt ones `planned`. The readiness check refuses generic examples and sources that match nothing |
| Adjudication | `detective.py` `verdict()` reads `case["adjudication"]` (`by`, `answer`, `confidence`, `reasoning`); threshold from `fable/calibration.json` or `adjudication_threshold` | Jev as the adjudicator; Jev's written schema as the required shape of `adjudication`; calibrate with `detective_backtest.py --write-calibration` on MARPA's decided cases before trusting 0.70 |
| Units and tolerances | `detective.py` `UNITS`; `handoff.json` `quantity_tolerance` | Landscape units the budgets use (sf, sy, lf, cy, tons, each, possibly pallets or flats for plants); per-dimension tolerances matching how MARPA budgets round |
| Evidence ladder | `handoff.json` `evidence_ladder`; defaults in `questions.py` `DEFAULT_LADDER` | Rungs in MARPA terms: drawings and models, the project's budget, the standard and class vocabulary, rulings and decisions, the firm's own words, outside standards, back-tests on past projects |
| Question system | `handoff.json` `question_system`; adapters in `questions.py` (`BcfSystem`, `MarkdownSystem`, `GithubSystem`, `JsonSystem`) | MARPA uses a BCF file for policy questions: `--question-system bcf:<path>`. Check the BCF 3.0 output in MARPA's real BCF tool (it was only tested against files the code wrote). If MARPA wants viewpoints or IFC GUID references on topics, extend `BcfSystem._description` and `save` |
| Case storage | `detective.py` `load_cases` / `save_cases` (`fable/cases.json`, `fable/CASES.md`) | Optional adapter that also writes cases and evidence to MARPA's `detective_case` / `detective_evidence` tables or reads `GET /cases`. Keep the JSON file as the run's local record |
| Decisions log | `handoff.json` `decisions_log`; `questions.py` `write_decision` | Point at MARPA's existing decisions record so there is no parallel copy |
| Owner rules | `scripts/audit_rules.py` `OWNER_RULES`, `OWNER_MARK`, `OWNER_HEADING` | MARPA's numbered rules (for example the rule that the run continues past policy questions, and that the owner's direction is adopted as stated) recognized as owner rules; add any that block an unattended run so readiness refuses to launch |
| Mission and run rules | `assets/templates/MISSION.md`, `OPERATING_RULES.md` | A MARPA section: the class-word grammar, where the standard lives, how to read VWX text exports, the pipe tables |
| Question triage | `scripts/preflight.py` `JUDGMENT_CUES`, `triage_question` | Landscape-specific policy words (design intent, client preference, allowance, fee policy) versus fact words (dimensions, labels, quantities, species) |
| Gap analysis | `scripts/gap_analysis.py` `collect`, `STOP`, `norm` | Include VWX text exports, budget CSVs and the class vocabulary in the corpus; landscape stop words; keep networkx pinned |
| Back-test set | `scripts/detective_backtest.py` input | Build `decided.json` from MARPA's rulings and recorded decisions, each with `owner_answer` and `ruling_sources` |
| Protected paths and blocked commands | `handoff.json` `protected_paths`, `blocked_bash_patterns`; defaults in `init_handoff.py` | Protect the standard, the class vocabulary, rulings and budgets; block anything that writes to the production pipe or sends client mail |
| Verify command | `handoff.json` `verify_command` | MARPA's own check, run through uv |

## 6. Do not change

- The judgment test (a question reaches the owner only after every rung is
  searched and recorded, and only for policy or preference).
- The verdict rules and their order in `detective.verdict()`; leads never
  count; independence by `source`.
- Park and continue: a parked task counts as done for the run only with a
  complete record; BLOCKED.md only for problems that stop all work.
- The safety defaults: the run's own branch (never main or master), permission
  mode `auto` (never `bypassPermissions` by default), the readiness gate
  before launch, settings changes opt-in with `--uninstall`, instruction edits
  only through `audit_rules.py --propose` and `--apply --approved-by`.
- uv only; stdlib-only hooks.

If MARPA needs one of these to behave differently, put the reason to the owner
first.

## 7. Suggested first steps on this branch

1. `git switch marpa`, `uv run pytest` (expect 287 passing).
2. Add `assets/presets/marpa/` with the eleven functions, the ladder,
   tolerances, units and question system, and `init_handoff.py --preset`.
   Add tests in the style of `test_the_registry_must_be_the_projects_own`.
3. Extend `UNITS` for MARPA's budget units, with tests.
4. Add MARPA owner rules to `audit_rules.py` with tests that a blocking one
   fails readiness.
5. Prove the BCF output in MARPA's BCF tool; adjust `BcfSystem` if needed.
6. Build the decided set and run `detective_backtest.py` on it; record the
   per-function scores and the calibrated threshold in this file.
7. Only then wire case storage to MARPA's pipe, if the owner wants it.

## 8. Known limits

- The BCF adapter round-trips with files this code writes; it has not been
  opened in a real BCF tool. The GitHub adapter was tested against a stand-in
  `gh`.
- Preflight's question triage is a first sort by wording; the preparing
  agent confirms each.
- The skill was never run on a Mac in this work; the macOS failures from
  1.0 were reproduced and fixed on Linux by simulating macOS's `python3`.
- Adjudication confidence is not a probability until the back-test calibrates
  it.

## 9. Done on this branch (2026-11-16)

- `init_handoff.py --preset marpa` and `assets/presets/marpa/` hold every row
  of the table in section 5 except case storage in MARPA's pipe and gap
  analysis corpus changes. The preset's README lists each setting and its
  MARPA source.
- The Jev decision framework (disler/ten-levels-of-jev) is applied to
  adjudication in the engine, generically: a written schema, the answer among
  the options offered, the abstain exit never applied, companions, post-checks,
  a receipt and confidence bands. The preset's README maps each place.
- `detective_backtest.py` gained `--min-accepted`, a cutoff table, and blind
  adjudications in the verdicts.
- Tests: `tests/test_marpa_preset.py`; `uv run pytest` passes 314.

### Back-test scores (37 ruled classes, run blind)

| Function | Evidence | Right | Accuracy |
| --- | --- | --- | --- |
| name match | 114 | 102 | 0.895 |
| drawing content | 3 | 2 | 0.667 |
| budget match | 28 | 5 | 0.179 |
| rules and precedent, own ruling hidden | 20 | 2 | 0.100 |

Calibrated adjudication threshold: **0.88** (lowest confidence with at least
10 answers at least 90% right; MARPA's own test in tenths gives 0.90).
Verdicts: 29 right, all settled by adjudication; 1 wrong (a class the name and
its project document place under groundcovers, ruled flatwork); 7 open.

The decided set names client projects, so it is rebuilt locally by
`export_decided_cases.py` and kept out of git.


### 2026-11-17 steps

- Allowance method (4574f64): mission rebuilt on the allocation engine; definition of done as stop condition; no model calls in calculations (readiness and stop gate).
- Desk map: `assets/presets/marpa/desk_map.py` on a clean clone of the desk at e50a89362. dependency-cruiser 18.8.0 refuses TypeScript 7.0.2, so it parses with @swc/core 1.16.22. 661 source modules: 334 needed by the kept features, 136 shared, 105 safe to remove, 222 reached by neither (mostly tests). knip 6.45.1: 15 unused files, no kept file flagged unused, route `src/routes/assistant.tsx` not flagged. Tauri: 47 commands called, 88 in Rust, 41 never called, 10 only for cut features. cargo-modules: 63 modules. vulture 2.16: 65 findings in 3,389 Python files. graphify 0.9.111 code-only: 28,610 nodes, 1,020 communities; import counts match dependency-cruiser on 6 of 8 files checked. Outputs: the desk's ignored `var/reference/desk-map/2026-11-16_e50a89362/`. Readiness refuses a desk without a map for its commit. Understand Anything moved to the final phase.
- Allocation engine, read-only: in its configured environment (`UV_PROJECT_ENVIRONMENT=~/worktrees/_env/marpa-allocation`, Python 3.14.10) `allocation check` passes and `verify-inputs` checks 352 inputs with no failure. Its tests were not run (they write QA evidence into its outputs). Portability: plain `uv run` makes a stray empty `.venv` there (one was made by this session's first call; git ignores it; removing it was refused, so it is left for the owner); machine paths in allocation.yaml; unpinned dependencies; 29 uncommitted files the run would rely on. Recorded in the preset's `related_locations`.
