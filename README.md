# fable-handoff

A Claude Code skill that prepares a project for a long, unattended run by Claude Fable 5.2, then launches, watches and reviews that run.

## What it does

1. **Preflight** maps the specs, standards, current state, past errors and successes, evals, the goal and earlier conversation logs.
2. **Package**: `init_handoff.py` writes `fable/` (mission, state ledger, decisions, `handoff.json`), hooks, deny rules and four model-pinned subagents (Haiku scout, Sonnet worker, Opus builder, Fable specialist).
3. **Readiness check** gives a READY or NOT READY verdict, covering the CLI flags, MCP config, model pin and owner sign-off.
4. **Launch**: `fable/launch.py` runs `claude -p` with a budget cap and restarts. It starts fresh when context files change.
5. **Review**: `post_run_report.py` and `system_review.py` turn the run's transcripts into evidence, lessons and improvements for the next run.

During the run Fable acts as team lead. It keeps dependent work itself, delegates independent work by complexity, verifies every result, and runs an InfraNodus gap check before it writes its report when InfraNodus is connected.

## Install

```bash
# One line, into ~/.claude/skills/fable-handoff
curl -fsSL https://raw.githubusercontent.com/JeromyJSmith/fable-handoff/main/install.sh | bash

# Into the current repo's .claude/skills instead
curl -fsSL https://raw.githubusercontent.com/JeromyJSmith/fable-handoff/main/install.sh | bash -s -- --project

# As a Claude Code plugin (2.1.275 or later)
/plugin install fable-handoff --marketplace JeromyJSmith/fable-handoff

# By hand
git clone https://github.com/JeromyJSmith/fable-handoff && cp -R fable-handoff/fable-handoff ~/.claude/skills/
```

Then ask Claude in any session to hand a project to Fable.

## Quick start

```bash
S=~/.claude/skills/fable-handoff/scripts
python3 $S/preflight.py --project . --run-tests --project-logs
python3 $S/init_handoff.py --project . --from-preflight --verify-command "pytest -q" --branch fable/run-1 --max-budget-usd 40
# fill fable/MISSION.md, then:
python3 $S/readiness_check.py --project .
python3 fable/launch.py --dry-run
```

The full procedure is in `fable-handoff/SKILL.md`.

## Requirements

Claude Code, python3 3.9 or later (stdlib only), git, and jq 1.7 for the conversation and spec queries.

## Layout

| Path | Contents |
| --- | --- |
| `fable-handoff/SKILL.md` | The procedure |
| `fable-handoff/references/` | Deeper guides; `sources.md` lists the Anthropic docs each rule depends on |
| `fable-handoff/scripts/` | Preflight, init, readiness, spec, context, report and audit tools |
| `fable-handoff/assets/` | Hooks, agents, templates, jq modules, JSON Schema |
| `fable-handoff/evals/` | Behavior cases for `claude plugin eval` |
| `tests/` | Acceptance suite (253 tests) |
| `docs/USER_GUIDE.md` | Step-by-step guide ([live version](https://claude.ai/artifact/SuJs4jg2YGcp7kqd1qGbQU)) |
| `docs/SPEC.md` | Build specification the tests check |
| `install.sh`, `.claude-plugin/` | Installers |

## Testing

```bash
FABLE_HANDOFF_SKILL_DIR=$PWD/fable-handoff python3 -m pytest -q tests
```

## Keeping it correct

When Claude Code or the model changes, follow `fable-handoff/references/sources.md` section 4 to re-verify against the official docs.

## License

MIT. See `LICENSE` and `CHANGELOG.md`.
