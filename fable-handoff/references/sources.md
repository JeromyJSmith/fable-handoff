# Official sources this skill depends on

Read this when Claude Code or the model changes, when a run behaves in a way
the skill did not predict, or before you trust a number in another reference.
Each row names what the skill relies on and how the skill applies it. Last full
cross-check: 2026-11-16, against Claude Code 2.1.325.

## Contents

1. Claude Code
2. Fable 5.2 and model choice
3. Skills
4. How to re-verify

## 1. Claude Code

| Page | What the skill relies on | How the skill uses it |
| --- | --- | --- |
| https://code.claude.com/docs/en/hooks | PreToolUse, Stop and SessionStart events; exit 2 blocks and sends stderr to the model; other codes do not block; `timeout` in seconds; `CLAUDE_PROJECT_DIR`; Stop input has `stop_hook_active`; a built-in cap of 8 consecutive Stop continuations that resets whenever a tool runs; a hook whose script is missing is treated as non-blocking | The guard and stop gate exit 2. The stop gate keeps its own counter in `fable/.run/stop_gate.json`, because the built-in cap resets on every tool call. The launcher refuses to start when a hook script is missing |
| https://code.claude.com/docs/en/tools-reference | Tool names and input fields: Bash `command`, Write and Edit `file_path`; PowerShell replaces Bash on Windows without Git Bash; MultiEdit and NotebookEdit's field are not documented | The guard treats PowerShell like Bash and reads `notebook_path` or `file_path`. MultiEdit stays in the matcher for older versions; it does no harm |
| https://code.claude.com/docs/en/permission-modes | The six modes; `-p` runs start in Manual mode; auto mode needs a recent model and can be disabled by an admin; `auto` and `bypassPermissions` as `defaultMode` in project settings have no effect; deny rules apply in every mode | The launcher passes `--permission-mode` on the command line; init adds deny rules |
| https://code.claude.com/docs/en/cli-reference, https://code.claude.com/docs/en/headless | `-p`, `--model`, `--effort`, `--append-system-prompt-file`, `--output-format stream-json` with `--verbose`, `--max-budget-usd` (an estimate, includes subagents, can be exceeded), `--max-turns`, `claude -p --continue` resumes print-mode sessions, `--mcp-config`; `--bare` skips hooks and MCP servers; MCP servers in `.mcp.json` load in print mode; the `system/init` event lists server status | The launcher builds its command from these, passes `mcp_config`, logs servers that did not connect, never uses `--bare`, and leaves budget headroom. The readiness check confirms the flags against the installed CLI's `--help`. In 2.1.325, `--append-system-prompt-file` and `--max-turns` work and are documented but `--help` does not print them, so the check accepts them |
| https://code.claude.com/docs/en/model-config | The `fable` alias can resolve to Fable 5.1 on the API unless `ANTHROPIC_DEFAULT_FABLE_MODEL` is set | Init pins `claude-fable-5-2`; readiness warns on a bare alias |
| https://code.claude.com/docs/en/sub-agents | Frontmatter `name`, `description`, `tools`, `model` (`haiku`, `sonnet`, `opus`, `fable`, `inherit` or an ID); subagents nest up to 3 levels; the built-in Explore agent runs on Opus when the main model is Fable; subagent spend counts toward limits | The four project agents pin their models. Define a project agent named `Explore` if the owner wants exploration on another model |
| https://code.claude.com/docs/en/claude-directory | Transcripts at `~/.claude/projects/<path with non-alphanumerics as ->/<session>.jsonl`, subagents in `<session>/subagents/`; deleted after 30 days by default | `conversation_context.py --project-logs` finds them. Read old runs before they expire |

## 2. Fable 5.2 and model choice

| Page | What the skill relies on | How the skill uses it |
| --- | --- | --- |
| https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-2 | Effort levels and `high` for long unattended runs; the "Finishing work" block (measured at medium); exact approvals; the ownership sentence and its cost; progress updates; caution that piles up; stale rules; reasoning-extraction refusals; the "Communicating clearly" block; changing the system prompt or tools mid-conversation breaks preserved thinking | The operating rules, the audit rules, the ownership switch, and the launcher's rule to start fresh when the context changed. See `fable-behaviors.md` |
| https://platform.claude.com/docs/en/models/fable-5-2/whats-new-fable-5-2 | Adaptive thinking is always on; refusal categories | Background for `fable-behaviors.md` |
| https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence | Measured orchestration results: Fable 5.2 alone at high scored best; Fable leading Sonnet subagents cost far less and scored somewhat lower; Opus leading Haiku subagents was cheapest and weakest; for dependent chains of work the lead alone at lower effort did best; re-run failures at higher effort where results can be checked | The team-lead rules: the lead keeps connected work, Sonnet takes independent fan-out, Haiku only reads, and every result is verified |
| https://platform.claude.com/docs/en/about-claude/pricing | Fable 5.2 $8/$40 per million input/output tokens; Opus 5.5 $4/$20; Sonnet 5.5 $2/$10; Haiku 5.5 $0.10/$0.50 | Phase 0's cost argument and the budget guidance |
| https://www.anthropic.com/claude-fable-and-mythos-5-2 | Fable as planner or orchestrator; most work should start on Opus 5.5 | Phase 0 |

## 3. Skills

| Page | What the skill relies on | How the skill uses it |
| --- | --- | --- |
| https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices | Name and description rules; SKILL.md under 500 lines; references one level deep with a table of contents over 100 lines; scripts that handle errors; evaluations | SKILL.md stays short and points here; every reference has Contents; the acceptance suite is the evaluation |
| https://agentskills.io/specification | Optional `compatibility` field; folder layout | The `compatibility` line in SKILL.md |
| https://code.claude.com/docs/en/skills | `${CLAUDE_SKILL_DIR}`; only the first part of a skill survives compaction | Script commands use `${CLAUDE_SKILL_DIR}`; the important steps come first |

## 4. How to re-verify

1. Open each page above and check the "What the skill relies on" column.
   Note anything that moved.
2. Run `uv run --script scripts/readiness_check.py` on a prepared project. Its `cli
   flags` row compares the launcher's flags with the installed CLI.
3. Fix the scripts, the references or the templates, run the acceptance suite,
   and update the date at the top of this file.
4. If InfraNodus is connected, run a content-gap analysis on SKILL.md after
   any large change. A gap between clusters often marks a step that one part
   of the skill assumes and no part does.
