# Changelog

## Unreleased

- `init_handoff.py --preset NAME [--shape NAME]`: a firm's preset (assets/presets/NAME/) merges its settings into fable/handoff.json (paths and blocked commands are added to the defaults, never replace them), adds mission and rules sections, installs per-shape mission, ledger and decisions files, and the decisions the owner must answer before launch. `assets/presets/example/` shows the shape.
- Adjudication under a written schema (the Jev decision framework, disler/ten-levels-of-jev): a named schema, the answer among the options offered, an abstain exit never applied, companion questions, post-checks, a receipt, and confidence bands (auto, review, low).
- `detective_backtest.py`: `--min-accepted`, a cutoff table, blind adjudications in the verdicts under the threshold the run calibrates.
- Units for weight, flats, pallets and lump sums; a null tolerance means never compared. Registry sources may be absolute paths.
- Readiness checks: launch requirements (functions built or planned as first tasks, files), companion repositories (own branch, clean, a map for their commit), no model calls in calculation code, decisions the owner must answer (per shape). The stop gate also refuses model calls in calculation code.
- The guard: named writable files outside the project, companion repositories, and `unreadable_paths` (run output is never a source; Read, Grep, Glob and shell reads are blocked).
- Question triage words and owner rules from the project's configuration; `decision_interview.py --file`.
- `scripts/intent.py`: a condensed INTENT.md from the conversation logs, with a section for data lost or regressed and whether each was resolved.
- runs/ holds run output and is never committed. The test suite fails if it changes any path outside the repository and the temporary folders that a preset names.

## 1.3.1 (2026-11-16)

- The detective functions must be the project's own. Init writes the generic registry marked as examples; the preparing agent analyses the project and replaces it (`references/detective-standard.md`, section 7, and the new step in SKILL.md phase 4). Each function names its `project_sources`, and every path must match something in the project. `fable/detective.py functions` and the readiness check refuse generic examples, missing sources and sources that match nothing.

## 1.3.0 (2026-11-16)

The detective standard: detective work defined, not a slogan.

- `fable/detective.py`: every investigation is a case (subject, question, candidates, evidence, verdict, record) in `fable/cases.json` and `fable/CASES.md`.
- `detective_functions` in `fable/handoff.json`: each function described before use (what it looks at, what it returns, strength, built or planned, test). Evidence from an unregistered or planned function, or without an underlying source, is refused.
- Computed verdicts: settled (a decisive source, or two independent strong sources), likely, settled by adjudication (kept apart), open fact, open policy. Conflicting decisive sources go to the owner. Leads never count. Two functions reading the same source count once. Quantities count as strong only within `quantity_tolerance` after unit conversion.
- `questions.py route`: settled cases become decisions by evidence or by adjudication; policy cases go to the question system with the case attached; facts return to the queue.
- `detective_backtest.py`: run blind on cases the owner decided (each case's own ruling hidden), score each function and the verdicts, and calibrate the adjudication threshold into `fable/calibration.json`.
- Owner-facing questions that lean on bare codes are refused.
- Readiness checks the registry and the cases; the review reports cases, verdicts and the back-test.

## 1.2.0 (2026-11-16)

Detective work before judgment calls; park and continue.

- The judgment test, in the mission template, the run's operating rules and `fable-behaviors.md`: a question goes to the owner only when every rung of the evidence ladder (in `fable/handoff.json`) was searched and recorded, and it is a matter of policy or preference. `questions.py check`, `decision_interview.py --check`, the readiness check and the stop gate refuse a question without that record.
- Preflight sorts open questions into "evidence can settle" and "judgment" and reports the counts; the interview takes only judgment calls; `decision_interview.py --settle` records the rest as decisions by evidence.
- Gap analysis and bridging (`gap_analysis.py`, `references/gap-analysis.md`): InfraNodus when connected, else a built-in concept graph (networkx 3.7, pinned in the script's uv header). Gaps and how each closed are recorded.
- Park and continue: `fable/questions.py park` writes a true judgment call to the project's question system (BCF 3.0, a markdown decisions table, GitHub issues, or `fable/open_decisions.json`), marks the task "waiting on owner" and the run goes on. The stop gate counts a parked task as finished for this run only with a complete record. The launcher exits 4 when the rest waits on answers and refuses to start until answers are imported. BLOCKED.md is only for problems that stop all work.
- `--question-system` and `--decisions-log` point the interview and the run at the project's own systems instead of parallel copies.
- The post-run review shows questions settled by evidence (by kind, with the evidence), questions parked with their records, and gaps found and bridged.

## 1.1.0 (2026-11-16)

- uv is the only Python manager: every script and hook is a PEP 723 script run with `uv run --script`; hooks, launcher and installer use uv; tests run with `uv run pytest` from `pyproject.toml` and `uv.lock`.
- Fixed: a verify command that cannot run (for example `python3 -m pytest` where that interpreter has no pytest, common on macOS) used to pass readiness as "fails now, as it should" and then trap the stop gate. Readiness now fails it, and the stop gate names it as an environment problem.
- Owner rules: recognized, never rewritten, honored or reported as blocking; a blocking one stops the launch.
- `audit_rules.py --propose` / `--apply --approved-by`: instruction edits as a diff that waits for the owner's yes.
- New `decision_interview.py`: one decision at a time, in plain words, recorded to DECISIONS.md and the spec.
- `init_handoff.py` shows the settings diff and writes it only on opt-in; new `--uninstall`.
- `install.sh` checks for uv, prints the installed commit, and recommends `--ref <tag>`.

## 1.0.0 (2026-11-16)

First public release, ready for a first trial run.

- Preflight maps goal, spec, standards, state, history and evals, with READY, THIN or MISSING per input.
- Structured handoff spec (JSON Schema, jq queries), owner sign-off tied to a spec hash, and rendering of the mission files.
- Conversation context from Claude Code JSONL logs: sessions, subagents, forks, intent, issues, successes, achievements, progress and research topics.
- Fable as team lead with four model-pinned subagents, routed by Anthropic's published cost data; every result verified by the lead.
- Hooks: PreToolUse guard (Bash and PowerShell, write tools, notebooks), Stop gate that runs each task's own check, SessionStart note.
- Launcher: pinned `claude-fable-5-2`, budget split across restarts, refuses missing hooks, passes and checks `mcp_config`, starts fresh when context files change.
- InfraNodus gap check before the final report when connected.
- Post-run review, lessons carried to the next preflight, and a look-back system review.
- Cross-checked against Anthropic's docs; sources in `fable-handoff/references/sources.md`.
- 253 acceptance tests and three `claude plugin eval` cases.
