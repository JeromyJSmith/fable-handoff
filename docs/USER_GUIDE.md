# Fable Handoff user guide

The full step-by-step guide is kept live at https://claude.ai/artifact/SuJs4jg2YGcp7kqd1qGbQU and downloads as Word, PDF or Markdown from there.

The steps in short:

| Step | What | Command |
| --- | --- | --- |
| 1 | Decide it is a Fable job (long, open-ended, too big for Opus) | |
| 1b | Preflight; sorts open questions into evidence and judgment | `preflight.py --project . --run-tests` |
| 1d | Detective work: settle evidence questions; find gaps | `decision_interview.py --project . --settle`, `gap_analysis.py --project .` |
| 1c | Rebuild context from past sessions | `conversation_context.py --project . --project-logs` |
| 2 | Discover the project and every instructions file | |
| 3 | Interview the owner on judgment calls only, one at a time | `decision_interview.py --project .` |
| 4 | Make done checkable with one failing verify command | |
| 5 | Scaffold; the settings diff is shown and written only on your yes | `init_handoff.py --project . --from-preflight --verify-command "..." --branch fable/job --max-budget-usd 40` |
| 6 | Propose instruction edits; apply only after the owner's yes | `audit_rules.py --project . --propose`, then `--apply --approved-by "Name"` |
| 7 / 7b | Write the mission, or render it from the spec | `spec_tool.py check`, `render_handoff.py` |
| 8 | Prove readiness | `readiness_check.py --project .` |
| 8b | Owner sign-off and look-back | `spec_tool.py brief`, `spec_tool.py signoff --by "Name"`, `system_review.py` |
| 9 | Launch and walk away | `uv run --script fable/launch.py --dry-run`, then `nohup uv run --script fable/launch.py &` |
| 9b | Answer parked questions in the question system, then import | `uv run --script fable/questions.py import` |
| 10 | Review | `post_run_report.py --project . --out fable/REVIEW.md` |

Run every script with `uv run --script`. To remove the hooks again: `init_handoff.py --project . --uninstall`. Scripts live in `fable-handoff/scripts/` (or `~/.claude/skills/fable-handoff/scripts/` after install).
