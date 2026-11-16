# Claude Code setup for an unattended run

## Contents

1. How to use this file
2. Permission modes
3. The three hooks
4. What init changes in the project
5. The launcher
6. handoff.json reference
7. Tuning protected paths and blocked commands
8. Files in fable/.run/
9. Troubleshooting

## 1. How to use this file

Read sections 2, 6 and 7 when you tune `fable/handoff.json` in phase 4. Read
section 5 before you launch. Come back to section 9 when a run ends in a way
you did not expect.

The facts about Claude Code here were checked against its documentation
(code.claude.com/docs: hooks, cli-reference, permission-modes) and against
Claude Code 2.1.325. Interfaces change. If the CLI rejects a flag, run
`claude --help` and read the current documentation before you work around it.

## 2. Permission modes

The launcher runs the CLI in print mode (`claude -p`). In print mode nobody
can answer a permission prompt, so any tool call that would prompt is denied.
The permission mode decides how much runs without a prompt.

| Mode | What runs | Use it when |
| --- | --- | --- |
| `auto` | Everything, after a classifier has reviewed each action. A blocked action does not run, and the session continues. | The default for a handoff on the owner's own machine |
| `acceptEdits` | Reads, file edits and common file commands inside the project. Other shell commands are denied unless an allow rule matches. | The job needs few shell commands, and you can list them as narrow allow rules |
| `dontAsk` | Only reads, read-only shell commands and pre-approved tools. Everything else is denied at once. | Locked-down CI with an exact allowlist |
| `bypassPermissions` | Everything. Deny rules still apply. It refuses to start as root outside a recognized sandbox. | Only inside a container or VM that holds nothing you cannot lose |

What matters for a handoff:

- `auto` needs a supported model. Fable qualifies. An organization can disable
  the mode.
- By default the `auto` classifier blocks things like piping a download into a
  shell, force pushes, `git reset --hard`, production deploys and sending
  sensitive data out. It also treats boundaries stated in the conversation as
  blocks, so the Forbidden list in the mission reinforces it.
- On entering `auto`, broad allow rules such as `Bash(*)` or `Bash(python*)`
  are dropped. Narrow rules such as `Bash(uv run pytest *)` stay.
- Setting `auto` or `bypassPermissions` as `defaultMode` in the project's
  `.claude/settings.json` has no effect. The mode has to be passed on the
  command line, which `fable/launch.py` does from `permission_mode`.
- `acceptEdits` treats `.git`, `.claude` and similar paths as protected. The
  package keeps the ledger and the report in `fable/` for this reason.
- Deny rules apply in every mode. Init adds `Read(./.env)` and
  `Read(./.env.*)`.
- Under `acceptEdits` or `dontAsk`, a job that needs shell commands needs
  allow rules. Add narrow ones to `.claude/settings.json` for the verify
  command, the package manager and `git commit`, for example
  `"Bash(uv run pytest *)"`. The readiness check warns about these two modes
  to remind you.

## 3. The three hooks

The hooks are plain Python files with no dependencies, copied into
`.claude/hooks/`. Claude Code runs each one at a fixed moment and passes it a
JSON payload on stdin. A hook answers with its exit code: 0 lets the action
proceed, 2 blocks it and sends the hook's stderr text to the model. Any other
exit code counts as an error that does not block.

Each hook finds the project from `CLAUDE_PROJECT_DIR`, then from the `cwd` in
the payload, then from the working directory. Each does nothing in a project
without `fable/handoff.json`, so the files are harmless if copied elsewhere.

### fable_guard.py (PreToolUse)

Runs before every `Bash`, `PowerShell`, `Write`, `Edit` and `NotebookEdit`
call. PowerShell is how Claude Code runs commands on Windows without Git Bash,
and the guard checks it like Bash. `MultiEdit` stays in the matcher for older
Claude Code versions; the tools reference no longer lists it. For notebooks
the guard reads `notebook_path` and falls back to `file_path`, since the
field name is not documented.

- For the file tools it blocks a write whose path matches `protected_paths`,
  and a write outside the project unless `allow_writes_outside_project` is
  true.
- For `Bash` it blocks a command that matches one of `blocked_bash_patterns`.
  It also blocks a command that would write to, move or delete a protected
  path: the target of a redirect or of `tee`, an argument of `rm`, `mv`,
  `chmod`, `truncate`, `touch` and similar commands, the destination of `cp`,
  the file of `sed -i`, and the paths of `git checkout`, `restore`, `rm` and
  `mv`. Deleting or moving a directory that holds a protected path is blocked
  too, and so is a wildcard that can reach one.
- Reading a protected file, copying it elsewhere or mentioning its name is
  allowed.
- If `fable/handoff.json` cannot be parsed, the guard blocks every write and
  shell command. It fails closed, because it can no longer tell what is
  protected.

The block message tells the model that this is a deliberate limit, not to
work around it, to note it in `fable/DECISIONS.md` and to continue with other
work.

Every false block sends an unattended run on a detour, so the guard makes two
allowances for harmless commands.

**It follows `cd`.** A relative path is checked against the directory the
command is in at that point. After `cd /tmp/other && ...`, the commands
joined by `&&` are checked against `/tmp/other` only. So
`cd /tmp/other && echo x > fable/MISSION.md` passes, and
`cd fable && rm MISSION.md` is blocked. Only `&&` has this effect, because it
is the only separator that stops the command line when the `cd` fails. In
these cases the guard checks the path against the earlier directories as
well:

- after `;`, a newline, a pipe, `||` or `&`;
- after a `( ... )` group, because a `cd` inside the group ends with it;
- when it cannot tell where the `cd` goes: `cd -`, `popd`, or a variable or
  wildcard in the path.

**It reads quoted text and heredoc bodies as mentions.** A blocked pattern is
not matched inside a quoted string that contains whitespace, such as a commit
message or an `echo` or `grep` argument, and not inside a heredoc body. So
`git commit -m "explain why sudo is blocked"` passes, and so does a heredoc
that writes notes about `git push --force` into a file. Text is still checked
as a command where something may run it:

- **The command line hands text to a program that runs it.** When the line
  uses a shell (`bash`, `sh`, `zsh`, `dash`, `ksh`), `eval`, `trap`, `watch`,
  `ssh`, `su` or a database client (`psql`, `mysql`, `mariadb`, `sqlite3`,
  `sqlcmd`, `duckdb`), the whole line is checked, quoted text and heredoc
  bodies included. This keeps `bash -c "git push --force"`, a heredoc fed to
  `sh`, `echo "sudo make install" | bash` and `psql -c "DROP TABLE users"`
  blocked. A heredoc fed to a shell is also checked for writes to protected
  paths.
- **A quoted single word**, such as `"$HOME"` or `"main"`. It is an argument,
  not a message.
- **The value of a variable**, as in `CMD="git push --force"`, because `$CMD`
  may run it later.
- **A double-quoted string that holds `$(...)` or backticks**, and everything
  after it on the command line, because the shell runs the substitution.

One consequence: a mention still blocks when the same command line also runs
a shell, for example `bash build.sh && git commit -m "why sudo is blocked"`.
The block message tells the model so. The same two commands pass when they
are sent separately.

The shell check reads the command as text. It cannot see what a script or an
interpreter does once it runs. That includes code handed to an interpreter
other than a shell, such as `uv run python -c "..."` or a heredoc fed to an interpreter:
the guard reads it as data. It is a second layer behind the permission mode,
not a sandbox. For real isolation, run in a container.

### fable_stop_gate.py (Stop)

Claude Code has a cap of its own: after 8 consecutive Stop continuations it
lets the turn end. That count resets whenever the model calls a tool, so it
does not stop a loop in which the model keeps working without progressing.
The gate therefore keeps its own counter in `fable/.run/stop_gate.json` and
gives up after `max_stop_blocks` blocks without progress. A Stop hook whose
script is missing is treated as non-blocking, which is why the launcher
refuses to start without all three hook files.

Runs each time the model tries to end its turn, and checks in this order:

1. `fable/BLOCKED.md` has content: the stop is allowed. This is how the model
   reports that nothing can move without the owner.
2. `fable/STATE.md` has unchecked tasks: the stop is blocked, and the tasks
   are listed.
3. No task is open: each checked task that names its check, written as
   ``(check: `command`)``, has that command run. If any fails, the stop is
   blocked and the tasks are listed, so a checkbox alone cannot end the run.
   A check written without backticks is prose and is not run.
4. Then the verify command runs. If it fails or times out, the stop is
   blocked, and the command and the end of its output are shown.
5. `fable/REPORT.md` is missing or empty: the stop is blocked.
6. Otherwise the stop is allowed.

So that a run cannot loop forever, each block is counted in
`fable/.run/stop_gate.json`. Once the gate has blocked `max_stop_blocks` times
in a row without progress, or `max_total_stop_blocks` times in total, it gives
up at the next attempt. It allows that stop and writes the reasons to
`fable/.run/stop_gate_exhausted.txt`. Progress means that the number of open
tasks or the verify result changed since the last block.

With `FABLE_GATE_DRY_RUN=1` in the environment the gate only answers and
writes nothing. The launcher and the readiness check use this to ask whether
the mission is finished. The gate removes the variable from the environment of
the verify command, so that a test suite which itself runs a stop gate is not
switched into dry-run mode by accident.

### fable_session_context.py (SessionStart)

Prints a short note that is added to the model's context on startup, on
resume and after compaction. The note names the mission, the ledger and the
decisions file, and gives the current task count. After compaction this is
what sends the model back to the files instead of to its memory.

### Changing what the hooks do

Change `fable/handoff.json`, not the hook files.

A project that was prepared with an older copy of the skill keeps the hooks
and the launcher of that copy. To bring them up to date, run:

```bash
uv run --script scripts/init_handoff.py --project /path/to/project --refresh-hooks
```

This overwrites the three hook files and `fable/launch.py` with the skill's
current copies and lists them under `created` in the JSON summary it prints.
It touches nothing else: the
mission, the operating rules, the ledger, the decisions, `fable/handoff.json`,
the subagents and `.claude/settings.json` stay as they are. In a project
without `fable/handoff.json` it stops with an error and creates nothing.
Afterwards, commit the four files and run the readiness check, whose
self-tests exercise the new hooks.

Do not use `init_handoff.py --force` for this. It resets all eleven package
files, including a mission and ledger you have filled in.

## 4. What init changes in the project

`init_handoff.py` creates eleven files:

| Path | What it is |
| --- | --- |
| `fable/handoff.json` | The config. Section 6 |
| `fable/MISSION.md` | Template for the prompt of the run. You fill it in |
| `fable/STATE.md` | Template for the task ledger. You seed it |
| `fable/DECISIONS.md` | Template for decisions. You fill it from the interview |
| `fable/OPERATING_RULES.md` | Appended to the system prompt. Ready to use |
| `fable/launch.py` | The launcher. Section 5 |
| `.claude/hooks/fable_guard.py`, `fable_stop_gate.py`, `fable_session_context.py` | Section 3 |
| `.claude/agents/fable-scout.md`, `fable-worker.md`, `fable-builder.md`, `fable-specialist.md` | The team Fable leads: Haiku for search and reading, Sonnet for small exact changes, Opus for specified larger pieces, Fable for hard isolated problems. Each pins its model, so delegated work never silently runs at the lead's price |

Files that already exist are left alone and listed under `skipped_existing`
in the JSON summary it prints. To update only the hooks and the launcher of
an existing package, use `--refresh-hooks`, described at the end of section 3.

The change to `.claude/settings.json` is opt-in. Init prints the exact diff:
three hook registrations, each `uv run --quiet --script
"${CLAUDE_PROJECT_DIR}/.claude/hooks/<name>"`, and two deny rules, with every
existing key kept. It writes the change only after a yes at the terminal
prompt or with `--apply-settings`; otherwise the proposed file is saved as
`fable/settings.proposed.json`, settings stay untouched, and readiness fails
on "hooks registered". When it writes and the file existed, the old version
is saved as `settings.json.bak-<timestamp>`, and `fable/settings_install.json`
records what was added. Commit or delete the backup, because the readiness
check fails on uncommitted files. If the existing file is not valid JSON,
init stops and changes nothing.

To undo, run `init_handoff.py --project . --uninstall`. If settings were not
edited since, the backup is restored exactly (or the file removed, when there
was none). Otherwise only this skill's hooks and deny rules are taken out and
everything else is kept. The hook scripts and unmodified agent files are
removed; `fable/` stays.

The Stop hook's timeout in the settings is the verify timeout plus two
minutes, because the gate runs the verify command. If you raise
`verify_timeout_seconds` later, raise that timeout in
`.claude/settings.json` too.

Finally it adds `fable/.run/` to `.gitignore`. Commit everything else, so
that the run branch carries the package.

## 5. The launcher

`uv run --script fable/launch.py --dry-run` prints the command without starting
anything. Its shape is:

```bash
claude -p "<contents of fable/MISSION.md>" \
  --model fable --effort high --permission-mode auto \
  --append-system-prompt-file fable/OPERATING_RULES.md \
  --output-format stream-json --verbose \
  --max-budget-usd 40.00
```

`--max-turns` is added when `max_turns` is set, and `extra_cli_args` are
appended at the end.

What the launcher does:

- **It refuses to start** (exit 2) when `fable/.run/readiness.json` is
  missing, records a failed check, or was produced for different contents of
  the mission, the operating rules or the config. This applies to `--dry-run`
  as well. It also refuses when the CLI cannot be found, or when
  `fable/BLOCKED.md` already has content.
- **It moves a stale report out of the way.** Just before the first launch,
  a `fable/REPORT.md` that already exists is moved to
  `fable/.run/REPORT-previous-<timestamp>.md`. The stop gate accepts any
  non-empty report, so one left from an earlier run would let the new run stop
  before it has done any work. A report written during the run stays where it
  is, also across relaunches. A dry run and a refused start move nothing.
- **It records each launch.** Output goes to
  `fable/.run/transcript-<n>.jsonl`, errors to `stderr-<n>.log`, and one
  entry per launch to `launch_log.json`.
- **It checks whether the mission is finished** after the CLI exits, by
  asking the stop gate in dry-run mode.
- **It relaunches an unfinished run**, up to `max_relaunches` extra times.
  After a clean exit it adds `--continue` and sends a short prompt that points
  at `fable/STATE.md`. After a crash it starts a fresh session with that
  prompt followed by the mission, and the new session resumes from the ledger.
  Either way the prompt says where the previous session stopped: its last
  message, the last failing output it saw and, after a crash, the end of its
  error log, all read from that attempt's transcript.
- **It does not relaunch into a blocker.** When `fable/BLOCKED.md` has
  content it stops with exit 3.
- **It keeps to the budget.** Each launch gets `max_budget_usd` minus what
  the earlier transcripts report as spent, and no launch starts when nothing
  is left. The CLI compares spending against its own estimate, which can
  differ from the bill.

Exit codes: 0 finished, 1 unfinished, 2 refused to start, 3 stopped on a
recorded blocker.

Start it so that it outlives the terminal, for example under `nohup` or
`tmux`, or from a job runner. On a laptop, prevent sleep for the length of
the run.

```bash
nohup uv run --script fable/launch.py > fable/.run/launch.out 2>&1 &
```

## 6. handoff.json reference

| Key | Default | Meaning |
| --- | --- | --- |
| `version` | 1 | Format version of this file |
| `model` | `claude-fable-5-2` | Full model ID. The alias `fable` can resolve to an older version on the API, and the readiness check warns about it |
| `effort` | `high` | `low`, `medium`, `high`, `xhigh` or `max` |
| `permission_mode` | `auto` | See section 2 |
| `branch` | `fable/run-1` | Branch the run works on. Readiness fails on main, master, production, prod and release, and warns when the current branch differs |
| `verify_command` | empty | One shell command that exits 0 only when the job is done. Run from the project root |
| `verify_timeout_seconds` | 1800 | Time limit for the verify command |
| `ownership` | false | Whether init added the ownership paragraph to the operating rules. Changing it here does not change the rules |
| `protected_paths` | see section 7 | Gitignore-style globs that the guard refuses to write |
| `blocked_bash_patterns` | see section 7 | Regular expressions, matched without regard to case, for forbidden shell commands |
| `allow_writes_outside_project` | false | Whether the file tools may write outside the project |
| `max_stop_blocks` | 8 | Blocks in a row without progress before the stop gate gives up |
| `max_total_stop_blocks` | 60 | Blocks in total before the stop gate gives up |
| `max_relaunches` | 3 | Extra launches after the first |
| `max_budget_usd` | null | Spend cap across all launches. Null means no cap, and readiness warns |
| `max_turns` | null | Optional cap on turns per launch |
| `audit_accept` | [] | `"<file>:<rule id>"` entries that the rules audit treats as accepted |
| `extra_cli_args` | [] | Extra flags appended to the CLI command. Never `--bare`, which skips the hooks |
| `mcp_config` | none | Path, inside the project, to an MCP config JSON passed as `--mcp-config`, for example one that adds InfraNodus. The readiness check validates it, and the launcher logs any server that does not connect |
| `claude_binary` | not set | Optional path to the CLI when it is not on the PATH as `claude` |

The mission, the operating rules and this file are covered by a hash in the
readiness record. Change any of them and you have to run the readiness check
again before the launcher will start.

## 7. Tuning protected paths and blocked commands

### Protected paths

The defaults protect secrets (`.env`, `.env.*`, `*.pem`, `*.key`), git
internals (`.git/**`), and the files that define the run, so that the run
cannot loosen its own limits: `.claude/settings.json`,
`.claude/settings.local.json`, `.claude/hooks/**`, `fable/handoff.json`,
`fable/MISSION.md`, `fable/OPERATING_RULES.md`, `fable/launch.py` and
`fable/.run/**`.

Add a glob for every path on the mission's Forbidden list. The rules are
those of `.gitignore`:

| Pattern | Protects |
| --- | --- |
| `.env` | a file or directory named `.env` at any depth, because the pattern has no slash |
| `*.pem` | any `.pem` file at any depth |
| `migrations/` | a directory named `migrations` at any depth, and everything in it |
| `db/migrations/**` | everything under `db/migrations` at the project root, because a slash in the pattern anchors it |
| `config/prod.yaml` | that one file at the project root |
| `docs/**/api.md` | `api.md` at any depth under `docs` |

`*` stays inside one path segment and `**` crosses directories. Matching
ignores case.

Do not protect `fable/STATE.md`, `fable/DECISIONS.md`, `fable/REPORT.md` or
`fable/BLOCKED.md`. The model has to write them. The readiness check tests
that it can.

### Blocked commands

The defaults cover: force pushes, pushes to main, master or production,
`git reset --hard`, `git clean -f`, `rm` aimed at `/`, `~` or `$HOME`, a
download piped into a shell, `sudo`, apply and destroy with terraform or
tofu, up and destroy with pulumi, kubectl apply or delete, package publishing
(npm, pnpm, yarn, bun, cargo, uv, poetry, flit, hatch, twine, gem), and SQL
`DROP TABLE`, `DROP DATABASE` and `DROP SCHEMA`.

Add a pattern for each command that the mission forbids and the defaults do
not cover, such as the project's own deploy script:

```json
"blocked_bash_patterns": ["...", "\\bmake\\s+deploy\\b", "\\bscripts/release\\.sh\\b"]
```

A pattern is searched for in the text of the command. Quoted text that
contains whitespace and heredoc bodies are left out, as section 3 describes,
so a commit message may name a forbidden command. Unquoted text and a quoted
single word are still searched, so keep patterns specific: `\bdeploy\b` would
also block `grep -rn deploy docs/`. In JSON, each backslash is written twice.

After any change to these lists, run the readiness check. Its guard self-test
feeds the guard a few made-up tool calls and fails if a pattern is broken or
if a path the run needs is protected.

## 8. Files in fable/.run/

The directory is git-ignored and protected from the model's tools.

| File | Written by | Holds |
| --- | --- | --- |
| `readiness.json` | readiness check | Result, package hash, base commit and the baseline verify result |
| `transcript-<n>.jsonl` | launcher | Everything the CLI printed during launch n |
| `stderr-<n>.log` | launcher | Errors from launch n |
| `launch_log.json` | launcher | One entry per launch: mode, exit code, seconds, budget, finished, blocked |
| `stop_gate.json` | stop gate | Block counters. Reset by the launcher at the start of each run |
| `stop_gate_exhausted.txt` | stop gate | Present only when the gate gave up, with the reasons |
| `REPORT-previous-<timestamp>.md` | launcher | The `fable/REPORT.md` of an earlier run, moved here before the first launch |

To watch a run from outside, look at `git log` on the run branch and at
`fable/STATE.md`. Both change as tasks complete.

## 9. Troubleshooting

**The launcher refuses to start.** Its message says which of the conditions
in section 5 failed. Most often the mission or the config changed after the
last readiness check. Run the check again.

**The run ended early and `stop_gate_exhausted.txt` exists.** The model tried
to stop again and again without progress. Read that file and the end of the
last transcript. The usual causes are a verify command that cannot pass in
this environment, a task that needs something forbidden, or a mission that is
unclear about what done means. Fix the cause and relaunch. Raising the caps
alone only buys more of the same.

**`fable/BLOCKED.md` exists.** The package worked as designed: the model
found that it could not continue without the owner and said so. Put the
owner's answer into `fable/DECISIONS.md`, delete `BLOCKED.md`, commit, run
the readiness check and launch again. Leave the old `fable/REPORT.md` alone:
the launcher moves it into `fable/.run/` before the first launch, so that the
stop gate asks the next run for a fresh one. The ledger carries the progress.

**Every shell command is denied.** The permission mode is `acceptEdits` or
`dontAsk` without allow rules, or `auto` is disabled for the account. See
section 2.

**The guard blocks something the job needs.** Narrow the pattern in
`fable/handoff.json`, run the readiness check, which tests the guard, and
launch again. Do not edit the hook file.

**The guard blocks a command that only mentions a forbidden command or a
protected path**, or one that works in another directory. The project
probably has the hooks of an older copy of the skill. Refresh them with
`init_handoff.py --refresh-hooks` (end of section 3). If the block remains,
section 3 lists the cases where quoted text is still checked.

**The model keeps asking questions that nobody reads.** An instructions file
that loads during the run still tells it to ask. Run `audit_rules.py` again
with `--extra` pointing at the instructions and memory files outside the
project that the owner's setup loads.

**The budget ran out.** Raise `max_budget_usd`, run the readiness check and
launch again. Earlier spending still counts against the new cap, and the
ledger carries the progress.

**A refusal on harmless work.** Look through the mission and the skills that
load for requests to write out reasoning, and reword security or biology
tasks around their defensive purpose. See section 11 of `fable-behaviors.md`.

**A flag is rejected by the CLI.** The CLI changed. Run `claude --help`,
correct `extra_cli_args` or the config, and check the current documentation
before you edit `fable/launch.py`. That file is protected from the model
during a run, but the owner may edit it between runs.
