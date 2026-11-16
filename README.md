# fable-handoff

A Claude Code skill that prepares a project for a long, unattended run by Claude Fable 5.2, then launches, watches and reviews that run.

## What it does

1. **Preflight** maps the specs, standards, current state, past errors and successes, evals, the goal and earlier conversation logs.
2. **Package**: `init_handoff.py` writes `fable/` (mission, state ledger, decisions, `handoff.json`), hooks, deny rules and four model-pinned subagents (Haiku scout, Sonnet worker, Opus builder, Fable specialist).
3. **Readiness check** gives a READY or NOT READY verdict, covering the CLI flags, MCP config, model pin and owner sign-off.
4. **Launch**: `fable/launch.py` runs `claude -p` with a budget cap and restarts. It starts fresh when context files change.
5. **Review**: `post_run_report.py` and `system_review.py` turn the run's transcripts into evidence, lessons and improvements for the next run.

During the run Fable acts as team lead. It keeps dependent work itself, delegates independent work by complexity, verifies every result, and runs an InfraNodus gap check before it writes its report when InfraNodus is connected.

## Python is managed by uv, and only uv

Every script and hook is a [PEP 723](https://peps.python.org/pep-0723/) script
(`requires-python = ">=3.11"`, no third-party dependencies) and runs as
`uv run --script <file>`. The hooks registered in `.claude/settings.json`,
the launcher and the scripts calling each other all go through uv, and the
tests run with `uv run pytest` from `pyproject.toml` and `uv.lock`. Nothing
calls a bare `python3` or `pip`, so the interpreter on your PATH (on macOS
often a different one from your project's) never matters. Install uv first:
https://docs.astral.sh/uv/getting-started/installation/

## Requirements

Claude Code, uv, git, and jq 1.7 for the conversation and spec queries. uv
fetches Python 3.11 or later when none is installed.

## Install

Install a release tag. `main` can change at any time.

```bash
# Recommended: a tagged release, into ~/.claude/skills/fable-handoff
curl -fsSL https://raw.githubusercontent.com/JeromyJSmith/fable-handoff/v1.1.0/install.sh | bash -s -- --ref v1.1.0

# Into the current repo's .claude/skills instead
curl -fsSL https://raw.githubusercontent.com/JeromyJSmith/fable-handoff/v1.1.0/install.sh | bash -s -- --ref v1.1.0 --project

# As a Claude Code plugin (2.1.275 or later)
/plugin install fable-handoff --marketplace JeromyJSmith/fable-handoff

# By hand
git clone --branch v1.1.0 https://github.com/JeromyJSmith/fable-handoff && cp -R fable-handoff/fable-handoff ~/.claude/skills/
```

The installer checks for git and uv, prints the exact commit it installed,
and records the repo, ref and commit in `fable-handoff/.installed-from`. An
older copy is moved aside, not deleted. Then ask Claude in any session to
hand a project to Fable.

## Quick start

```bash
S=~/.claude/skills/fable-handoff/scripts
uv run --script $S/preflight.py --project . --run-tests --project-logs
uv run --script $S/decision_interview.py --project .        # settle open decisions, one at a time
uv run --script $S/init_handoff.py --project . --from-preflight --verify-command "uv run pytest -q" --branch fable/run-1 --max-budget-usd 40
uv run --script $S/audit_rules.py --project . --propose      # proposed instruction edits, as a diff
# fill fable/MISSION.md, then:
uv run --script $S/readiness_check.py --project .
uv run --script fable/launch.py --dry-run
```

The full procedure is in `fable-handoff/SKILL.md`.

## Your rules stay yours

- **Instruction edits wait for your yes.** `audit_rules.py --propose` writes
  the changes it suggests to CLAUDE.md, AGENTS.md and `.claude/` as a diff in
  `fable/RULES_PROPOSAL.md` and edits nothing. `--apply --approved-by "Name"`
  applies that exact diff, refuses if a file changed since, and records the
  approval in `fable/DECISIONS.md`.
- **Owner rules are never rewritten.** Mark a line "(owner rule)" or put it
  under an "Owner rules" heading. Rules like "commit only when I say", "never
  edit a test to make it pass", writer locks or "one writer at a time", and
  "record every decision" are recognized on their own. Each is either honored
  by the run or blocks it. A blocking rule makes the readiness check fail, so
  the run does not launch.
- **Settings changes are opt-in and reversible.** `init_handoff.py` prints the
  exact `.claude/settings.json` diff and writes it only after a yes at the
  prompt or with `--apply-settings`. `init_handoff.py --project . --uninstall`
  removes the hooks and restores the backup.
- **Safe defaults stay.** The run happens on its own branch, never main or
  master. The permission mode is `auto`, never `bypassPermissions`, unless you
  set it. The readiness gate always runs before launch.

## Decision interview

`decision_interview.py` walks you through open decisions one at a time,
without launching anything. Each is shown in plain words: what the thing is,
why it matters, each option and what happens if you choose it, and a
recommendation. Answers go to `fable/DECISIONS.md` and the handoff spec.
`--check` lists questions not yet written up well enough to ask, including
any that lean on bare numbers or IDs. `--answers file.json` answers without a
terminal.

## Layout

| Path | Contents |
| --- | --- |
| `fable-handoff/SKILL.md` | The procedure |
| `fable-handoff/references/` | Deeper guides; `sources.md` lists the Anthropic docs each rule depends on |
| `fable-handoff/scripts/` | Preflight, decision interview, init and uninstall, readiness, spec, context, report and audit tools |
| `fable-handoff/assets/` | Hooks, agents, templates, jq modules, JSON Schema |
| `fable-handoff/evals/` | Behavior cases for `claude plugin eval` |
| `tests/`, `pyproject.toml`, `uv.lock` | Acceptance suite (267 tests), run with `uv run pytest` |
| `docs/USER_GUIDE.md` | Step-by-step guide ([live version](https://claude.ai/artifact/SuJs4jg2YGcp7kqd1qGbQU)) |
| `docs/SPEC.md` | Build specification the tests check |
| `install.sh`, `.claude-plugin/` | Installers |

## Testing

```bash
uv run pytest
```

`uv.lock` pins pytest. To test an installed copy instead of this checkout,
set `FABLE_HANDOFF_SKILL_DIR=/path/to/fable-handoff`.

## Releasing

1. Update `CHANGELOG.md` and the version in `pyproject.toml` and `.claude-plugin/*.json`.
2. Run `uv run pytest`.
3. Tag and push: `git tag -a v1.1.0 -m "fable-handoff 1.1.0" && git push origin v1.1.0`.
4. Point the install commands in this README at the new tag.

## Keeping it correct

When Claude Code or the model changes, follow `fable-handoff/references/sources.md` section 4 to re-verify against the official docs.

## License

MIT. See `LICENSE` and `CHANGELOG.md`.
