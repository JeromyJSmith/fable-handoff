# Changelog

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
