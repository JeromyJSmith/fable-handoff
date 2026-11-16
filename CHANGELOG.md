# Changelog

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
