# Changelog

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
