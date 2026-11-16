# Rebuilding context from conversation logs

Read this in phase 1 when the work so far happened in Claude Code sessions,
and those sessions hold intent, decisions, failures and progress that no
document records.

## Contents

1. What it does
2. Running it
3. What it reads
4. How the structure is rebuilt
5. How the signals are found
6. The document
7. Querying the logs with jq
8. Limits and privacy

## 1. What it does

`scripts/conversation_context.py` reads one or more Claude Code conversation
logs, links them into one picture, and writes a short context document:

- `fable/CONTEXT.md`: intent, where things stand, achievements, progress,
  successes, issues, forks, subagents and a session table.
- `fable/context.json`: the same data, for scripts and jq.

The work is done by the jq module `assets/jq/conversations.jq`; the script
finds the files and runs jq once over all of them. jq must be installed.

## 2. Running it

```bash
# The logs Claude Code keeps for this project, subagents included
python3 scripts/conversation_context.py --project . --project-logs

# Specific files or directories, mixed freely
python3 scripts/conversation_context.py --project . \
  --logs ~/.claude/projects/-Users-me-app/ fable/.run/transcript-0.jsonl

# As part of preflight: CONTEXT.md becomes a history and state source
python3 scripts/preflight.py --project . --run-tests --project-logs
python3 scripts/preflight.py --project . --conversations path/to/logs/
```

`--project-logs` looks in `~/.claude/projects/<project path with every
character other than letters and digits replaced by "-">/`. Set
`CLAUDE_CONFIG_DIR` if your Claude configuration lives elsewhere. `--json`
prints the data, `--no-write` writes nothing.

## 3. What it reads

| Input | Where it comes from |
| --- | --- |
| Session logs | `~/.claude/projects/<project>/<session-id>.jsonl`. One JSON object per line, linked by `uuid` and `parentUuid` |
| Subagent logs | `<session-id>/subagents/agent-<id>.jsonl`, lines marked `isSidechain` with an `agentId` |
| Subagent metadata | `agent-<id>.meta.json`: the agent type, its description and the `toolUseId` of the call that started it |
| Print-mode output | `claude -p --output-format stream-json`, such as the launcher's `fable/.run/transcript-<n>.jsonl`. Subagent lines carry `parent_tool_use_id` |

Lines that are not objects, streaming deltas, hook events and other
bookkeeping are skipped. File names that start with `-` are handled.

## 4. How the structure is rebuilt

- **Sessions** are grouped by session id, across files, so a resumed session
  split over several files is one row.
- **Parent and child.** A subagent's conversation is tied to its parent
  session and to the tool call that started it, through the metadata file or
  through `parent_tool_use_id`. Its handback message is its result.
- **Forks.** A fork is a message with two or more different human replies
  under it: an edited prompt, a rewind or a retry. Several children from
  parallel tool calls are not counted as forks. Each fork lists its branches
  in time order, so you can see what the person changed their mind about.
- **The active branch** runs from the newest message of each session back to
  its root. "Where it stands" quotes the last reply on it, so a reply on an
  abandoned branch is never reported as the current state.
- **Compactions** are counted. A compaction means earlier detail was
  summarized, so the document is the better record of that stretch.

## 5. How the signals are found

All signals are patterns over the text. They show where to look.

| Signal | Comes from |
| --- | --- |
| Intent | The first message a person typed in each session, then later messages that state a goal ("I want", "we need", "let's", "can we", "build", "fix") |
| Issues | Tool calls that returned an error, failure lines in command output (a failing test count, `FAILED`, a traceback, `Error:` at the start of a line, `NOT READY`), interruptions, and short messages in which the person corrects course ("no", "that's wrong", "revert") |
| Successes | Command output whose summary line passes (`6 passed`, `All tests passed`, `READY`) with no failure line in the same output, and short approvals ("perfect", "good enough", "works") |
| Achievements | `git commit` subjects, taken from `-m` or a heredoc, and the files written or edited most |
| Progress | Tasks created and completed with the task tools, and completed to-do items |
| Research | Web searches and fetches, research and browsing tools from MCP servers, and subagents briefed to research, investigate or compare. Each lookup records its query, whether it worked, the first meaningful line of what came back, and what the conversation concluded right after. Lookups are grouped into topics by the main words of the query or URL, so the same question asked through two tools is one topic |

Only the output of tools that run things (Bash and similar) counts as passing
or failing; the contents of a file that was read do not. System reminders,
slash-command wrappers and skill bodies are not counted as human messages.

## 6. The document

`CONTEXT.md` is meant to fit in one read. Each list is capped and repeated
lines are merged with a count. Use it three ways:

- **In the interview.** Forks and corrections are where the owner changed
  their mind. Each one is usually a decision to write down.
- **In the mission.** Recurring issues become traps in "Where things are",
  with what to do instead. Achievements tell the run what not to redo.
- **In the spec.** With `--conversations` or `--project-logs`, preflight adds
  `fable/CONTEXT.md` to the spec's sources and drafts trap candidates from its
  issue lines. Review every one: a solved problem is not a trap.

Read the cited lines in the logs before you rely on a signal.

Each passing or failing output also carries the command that produced it, so
a claim can be checked by running it again. After a run, `post_run_report.py`
reads the run's own transcripts the same way: it summarizes their issues in
the review and turns a failure that recurred into a trap for the next run.

## 7. Querying the logs with jq

The module works without the script. Always use `-n` and pass all files at
once, so that `load` can link them:

```bash
J="jq -n -L SKILL/assets/jq"
$J -r 'include "conversations"; load | context_md' logs/*.jsonl logs/*/subagents/*
$J 'include "conversations"; load | context | .forks' logs/*.jsonl
$J -r 'include "conversations"; load | [events] | map(select(.kind == "human")) | .[] | "\(.ts) \(.text[0:100])"' logs/*.jsonl
$J 'include "conversations"; load | [events] | map(select(.kind == "tool_use")) | group_by(.tool) | map({tool: .[0].tool, n: length})' logs/*.jsonl
```

| Definition | Gives |
| --- | --- |
| `load` | Every line of every file, tagged with `_file` |
| `events` | One normalized event per content block: `kind` is human, interrupt, assistant_text, tool_use, tool_result, compact or agent_meta, with session, uuid, parent, side (subagent), agent, ts and text or tool fields |
| `context` | Everything below, as one object |
| `sessions($ev)`, `subagents($ev)`, `forks($ev)` | The structure |
| `intent($ev)`, `issues($ev)`, `successes($ev)`, `achievements($ev)`, `progress($ev)` | The signals |
| `context_md` | The Markdown document |

## 8. Limits and privacy

- Patterns miss things and mislabel things. A message that says "no" for
  another reason can appear as a correction.
- Logs can contain secrets and personal data. Strings that look like API keys
  and tokens are replaced with `[REDACTED]`, but nothing else is removed.
  Read `CONTEXT.md` before you commit it or share it. Add it to `.gitignore`
  if it should stay local.
- The log format belongs to Claude Code and can change. The module ignores
  fields it does not know, but a renamed field would silently drop a signal.
  Tested with Claude Code 2.1.325 and jq 1.7.
