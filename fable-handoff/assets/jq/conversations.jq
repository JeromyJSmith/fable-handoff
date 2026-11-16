# conversations.jq: rebuild a concise context document from Claude Code
# conversation logs (JSONL), including subagents, forks and resumed sessions.
#
#   jq -n -r -L SKILL/assets/jq 'include "conversations"; load | context_md' FILES...
#   jq -n    -L SKILL/assets/jq 'include "conversations"; load | context'    FILES...
#
# Always run with -n and pass every file at once: `load` reads all inputs and
# remembers which file each line came from, so parent and child conversations
# in different files can be linked.
#
# Accepted inputs, in any mix:
#   - session logs:   ~/.claude/projects/<project>/<session>.jsonl
#   - subagent logs:  <session>/subagents/agent-<id>.jsonl, and the matching
#                     agent-<id>.meta.json (gives the agent type and the tool
#                     call that started it)
#   - print-mode output from `claude -p --output-format stream-json`, such as
#     fable/.run/transcript-<n>.jsonl from the launcher
#
# The signals (intent, issues, successes, achievements, progress) come from
# patterns, not understanding. They point a reader at the right lines; they do
# not replace reading them. Secrets that look like API keys are redacted.
# Tested with jq 1.7; written to avoid builtins added after 1.6.

# ------------------------------------------------------------------ helpers

def _str: if type == "string" then . elif . == null then "" else tostring end;
def _redact: gsub("(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,})"; "[REDACTED]");
def _clip($n): _str | _redact | gsub("\\s+"; " ") | ltrimstr(" ") | if length > $n then .[0:$n] + "..." else . end;
def _first_line: _str | split("\n") | map(select(test("\\S"))) | (.[0] // "");
def _block_text: if type == "string" then . elif type == "array" then map(select(.type == "text") | .text) | join("\n") else "" end;
def _ts_min: if . == null or . == "" then "" else .[0:16] | sub("T"; " ") end;

# Text a person typed, as opposed to reminders, hook output, slash-command
# wrappers and skill bodies that also arrive as user messages.
def _is_human_text: test("\\S") and (test("^\\s*<") | not) and (test("^Base directory for this skill") | not)
  and (test("^Caveat: ") | not) and (test("^This session is being continued from a previous conversation") | not);

# Regular expressions for the signals, case-insensitive.
def _goal_rx: "\\b(i want|i'd like|i would like|we want|we need|i need|let'?s|can we|could we|should we|the goal|goal is|make (it|this|a)|build|create|add|implement|write|fix|get this|improve)\\b";
def _negative_rx: "(^\\s*no\\b|\\bnot what\\b|\\bwrong\\b|doesn'?t work|does not work|didn'?t work|\\bbroken\\b|\\bstill (fails|failing|broken|not)\\b|\\bstop\\b|\\bundo\\b|\\brevert\\b|\\bthat'?s not\\b|\\bwhy did you\\b|frustrat)";
def _approval_rx: "\\b(perfect|great|good enough|looks good|works( now| great)?|nice|thanks|thank you|exactly|awesome|ship it|approved?)\\b";
# Output lines that summarize a run. Anchored to the start of a line, so that
# code or prose that merely contains a word like "Error" does not count.
def _success_rx: "^\\s*(=+ )?([0-9]+ passed\\b(?!.*\\b[0-9]+ (failed|error))|ok\\b.*\\btests?\\b|Tests:.*\\bpassed\\b(?!.*failed)|READY\\b|BUILD SUCCESS|Build succeeded|All tests passed|✅)";
def _failure_rx: "^\\s*(=+ )?([0-9]+ failed\\b|.*\\b[0-9]+ failed,|FAILED\\b|FAIL\\s|Traceback \\(most recent call last\\)|E\\s+[A-Za-z]*(Error|Exception)\\b|[A-Za-z.]*(Error|Exception): |NOT READY\\b|fatal: |error(\\[[A-Z0-9]+\\])?: |npm ERR!|BUILD FAILURE)";
# Tools whose output is the result of running something.
def _runs_things: . == "Bash" or . == "PowerShell" or . == "mcp__remote-devices__device_bash";

# ------------------------------------------------------------------ loading

# Every input line, tagged with its file. Lines that are not objects are dropped.
def load: [inputs | select(type == "object") | {_file: input_filename} + .];

def _agent_id_from_file: (._file // "") | capture("agent-(?<id>[A-Za-z0-9]+)(\\.meta)?\\.json") .id // null;

# One event per meaningful content block.
#   kind: human | interrupt | assistant_text | tool_use | tool_result | compact | agent_meta
def events:
  .[] as $r
  | ($r.sessionId // $r.session_id) as $session
  | {file: $r._file, session: $session, uuid: $r.uuid, parent: $r.parentUuid,
     side: (($r.isSidechain // false) or ($r.parent_tool_use_id != null)),
     agent: ($r.agentId // (if $r.isSidechain then ($r | _agent_id_from_file) else null end)),
     parent_tool: $r.parent_tool_use_id, ts: ($r.timestamp // null)} as $base
  | if ($r | has("agentType")) then
      $base + {kind: "agent_meta", agent: ($r | _agent_id_from_file), agent_type: $r.agentType,
               description: ($r.description // ""), spawned_by: ($r.toolUseId // null)}
    elif ($r.isCompactSummary == true) or ($r.subtype == "compact_boundary") then
      $base + {kind: "compact", text: ($r.message.content | _block_text)}
    elif $r.type == "user" and ($r.isMeta | not) then
      ($r.message.content) as $c
      | if ($c | type) == "string" then
          if ($c | test("^\\[Request interrupted")) then $base + {kind: "interrupt", text: $c}
          elif ($c | _is_human_text) then $base + {kind: "human", text: $c}
          else empty end
        elif ($c | type) == "array" then
          $c[]
          | if .type == "text" then
              (.text // "") as $t
              | if ($t | test("^\\[Request interrupted")) then $base + {kind: "interrupt", text: $t}
                elif ($t | _is_human_text) then $base + {kind: "human", text: $t}
                else empty end
            elif .type == "tool_result" then
              $base + {kind: "tool_result", tool_id: .tool_use_id, is_error: (.is_error == true),
                       text: (.content | _block_text)}
            else empty end
        else empty end
    elif $r.type == "assistant" then
      ($r.message.content // [])[]
      | if .type == "text" and (.text | test("\\S")) then $base + {kind: "assistant_text", text: .text}
        elif .type == "tool_use" then $base + {kind: "tool_use", tool: .name, tool_id: .id, input: (.input // {})}
        else empty end
    else empty end;

# ------------------------------------------------------------------ structure

def _records: map(select(.uuid != null and (.type == "user" or .type == "assistant" or .type == "system" or .type == "attachment")));

# Sessions: one row per session id, main conversation only.
def sessions($ev):
  $ev | map(select(.side | not) | select(.session != null)) | group_by(.session)
  | map({session: .[0].session,
         files: (map(.file) | unique),
         start: (map(.ts // empty) | min // null),
         end: (map(.ts // empty) | max // null),
         human_turns: (map(select(.kind == "human")) | length),
         tool_calls: (map(select(.kind == "tool_use")) | length),
         errors: (map(select(.kind == "tool_result" and .is_error)) | length),
         interrupts: (map(select(.kind == "interrupt")) | length)})
  | sort_by(.start);

# Subagents: child conversations, linked to the tool call that started them.
def subagents($ev):
  ($ev | map(select(.kind == "agent_meta")) | INDEX(.agent)) as $meta
  | ($ev | map(select(.kind == "tool_use" and (.tool == "Agent" or .tool == "Task"))) | INDEX(.tool_id)) as $spawns
  | $ev | map(select(.side and .agent != null)) | group_by(.agent)
  | map(.[0].agent as $id
        | ($meta[$id] // {}) as $m
        | ($spawns[$m.spawned_by // ""] // null) as $s
        | {agent: $id,
           type: ($m.agent_type // ($s.input.subagent_type // null)),
           description: ($m.description // ($s.input.description // "")),
           parent_session: (.[0].session),
           started: (map(.ts // empty) | min // null),
           tool_calls: (map(select(.kind == "tool_use")) | length),
           errors: (map(select(.kind == "tool_result" and .is_error)) | length),
           result: (((map(select(.kind == "tool_use" and .tool == "SubagentHandback")) | last | .input.message)
                     // (map(select(.kind == "assistant_text")) | last | .text) // "") | _clip(300))})
  # Subagents seen only through print-mode output have no agent id; group by the spawning call.
  + ($ev | map(select(.side and .agent == null and .parent_tool != null)) | group_by(.parent_tool)
     | map(.[0].parent_tool as $pt | ($spawns[$pt] // null) as $s
           | {agent: $pt, type: ($s.input.subagent_type // null), description: ($s.input.description // ""),
              parent_session: .[0].session, started: (map(.ts // empty) | min // null),
              tool_calls: (map(select(.kind == "tool_use")) | length),
              errors: (map(select(.kind == "tool_result" and .is_error)) | length),
              result: ((map(select(.kind == "assistant_text")) | last | .text) // "" | _clip(300))}));

# Forks: a message with two or more different human replies under it. This is
# what an edited prompt, a rewind or a retry looks like in the log. Parallel
# tool calls also give a message several children, but those are not forks.
def forks($ev):
  $ev | map(select(.kind == "human" and .parent != null)) | group_by(.parent)
  | map(select(length > 1))
  | map({at: .[0].parent, session: .[0].session, when: (map(.ts // empty) | min // null),
         branches: (sort_by(.ts) | map({ts, uuid, text: (.text | _clip(120))}))});

# The active branch: from the newest message of each main session back to its root.
def active_path($records):
  ($records | INDEX(.uuid)) as $idx
  | $records | map(select((.isSidechain // false) | not)) | group_by(.sessionId)
  | map(max_by(.timestamp // "") | [recurse(($idx[.parentUuid // ""]) // empty) | .uuid])
  | add // [];

# ------------------------------------------------------------------ signals

def _tool_names($ev): $ev | map(select(.kind == "tool_use")) | INDEX(.tool_id) | map_values(.tool);
# The command line behind each tool call, so a signal can be reproduced.
def _tool_commands($ev): $ev | map(select(.kind == "tool_use")) | INDEX(.tool_id) | map_values(.input.command // null);

def intent($ev):
  $ev | map(select(.kind == "human" and (.side | not))) | group_by(.session)
  | map(sort_by(.ts) | {session: .[0].session, opening: (.[0].text | _clip(400)), ts: .[0].ts,
         later_goals: (.[1:] | map(select(.text | test(_goal_rx; "i"))) | map({ts, text: (.text | _clip(240))}))});

def issues($ev):
  _tool_names($ev) as $names | _tool_commands($ev) as $cmds
  | [ ($ev[] | select(.kind == "tool_result" and .is_error)
        | {ts, session, source: "tool error", tool: ($names[.tool_id] // "tool"), text: (.text | _first_line | _clip(200))}),
      ($ev[] | select(.kind == "tool_result" and (.is_error | not) and (($names[.tool_id] // "") | _runs_things))
        | . as $e | [.text | split("\n")[] | select(test(_failure_rx))] | select(length > 0)
        | {ts: $e.ts, session: $e.session, source: "failing output", tool: $names[$e.tool_id], command: ($cmds[$e.tool_id] // null | if . then _clip(160) else . end), text: (.[0] | _clip(200))}),
      ($ev[] | select(.kind == "interrupt") | {ts, session, source: "interrupted by the user", tool: null, text: (.text | _clip(120))}),
      ($ev[] | select(.kind == "human" and (.side | not) and (.text | length) < 600 and (.text | test(_negative_rx; "i")))
        | {ts, session, source: "user correction", tool: null, text: (.text | _clip(240))}) ]
  | sort_by(.ts);

def successes($ev):
  _tool_names($ev) as $names | _tool_commands($ev) as $cmds
  | [ ($ev[] | select(.kind == "tool_result" and (.is_error | not) and (($names[.tool_id] // "") | _runs_things))
        | . as $e | [.text | split("\n")[]] as $lines
        | select(($lines | map(select(test(_failure_rx))) | length) == 0)
        | [$lines[] | select(test(_success_rx))] | select(length > 0)
        | {ts: $e.ts, session: $e.session, source: "passing output", tool: $names[$e.tool_id], command: ($cmds[$e.tool_id] // null | if . then _clip(160) else . end), text: (last | _clip(200))}),
      ($ev[] | select(.kind == "human" and (.side | not) and (.text | length) < 600
                      and (.text | test(_approval_rx; "i")) and (.text | test(_negative_rx; "i") | not))
        | {ts, session, source: "user approval", tool: null, text: (.text | _clip(200))}) ]
  | sort_by(.ts);

# The first line of a commit message, from -m "..." or a heredoc.
def _commit_subject:
  # Only the text after the last `git commit`, so an earlier script in the same command is ignored.
  ([splits("git\\s+commit\\b")] | last) as $rest
  | ($rest | capture("^[^\\n]*?(^|\\s)-[a-zA-Z]*m\\s*(\"(?<a>[^\"]+)\"|'(?<b>[^']+)')") // null) as $m
  | ($rest | capture("^[^\\n]*?(\\$\\(cat|-F\\s*-)\\s*<<-?\\s*'?[A-Za-z_]+'?\\s*\\n(?<body>[\\s\\S]*)") // null) as $h
  | if $m and (($m.a // $m.b) | test("^\\$\\(cat") | not) then (($m.a // $m.b) | split("\n") | .[0])
    elif $h then ($h.body | split("\n") | map(select(test("\\S"))) | .[0] // "")
    else "(message not on the command line)" end;

def achievements($ev):
  ($ev | map(select(.kind == "tool_use"))) as $uses
  | {commits: [$uses[] | select(.tool == "Bash" and ((.input.command // "") | test("\\bgit\\s+commit\\b")))
                | {ts, session, message: (.input.command | _commit_subject | _clip(160))}],
     files_written: ([$uses[] | select(.tool == "Write" or .tool == "Edit" or .tool == "MultiEdit" or .tool == "NotebookEdit")
                      | (.input.file_path // .input.notebook_path // empty)] | group_by(.) | map({path: .[0], edits: length})
                      | sort_by(-.edits))};

def progress($ev):
  ($ev | map(select(.kind == "tool_use"))) as $uses
  | {tasks_created: [$uses[] | select(.tool == "TaskCreate") | .input.subject // empty | _clip(120)],
     tasks_completed: ([$uses[] | select(.tool == "TaskUpdate" and .input.status == "completed")] | length),
     todos_done: ([$uses[] | select(.tool == "TodoWrite") | .input.todos // [] | map(select(.status == "completed") | .content)]
                  | last // [] | map(_clip(120)))};

# Research: web searches and fetches, research tools from MCP servers and
# research subagents, each with what it asked, what came back and what the
# conversation concluded right after it.
def _is_research_tool: test("^(WebSearch|WebFetch)$") or test("^mcp__.*(search|fetch|extract|crawl|research|scrape|browse|exa|tavily|firecrawl|perplexity)"; "i");
def _research_query: .input.query // .input.url // .input.urls // .input.q // .input.search_query // .input.prompt // .input.description // .input.objective
  # Batched browser or fetch tools nest their URLs and queries one level down.
  // ([.input | .. | objects | (.url? // .query? // empty) | strings] | unique | if length > 0 then join(", ") else null end)
  | if type == "array" then map(tostring) | join(", ") else . end;
# The first line of a result that says something: at least six words, not a marker or a heading.
def _meaningful_line: _str | split("\n") | map(gsub("^[#*>\\s-]+"; "") | select(test("^(<|\\[|---|```)") | not) | select(([splits("\\s+")] | length) >= 6)) | (.[0] // "");
def _topic: _str | ascii_downcase | sub("^https?://(www\\.)?"; "") | (split("?")[0] // "")
  | [splits("[^a-z0-9.]+") | select(length > 2 and (. as $w | ["the", "and", "for", "with", "how", "what", "does", "from", "this", "that", "into", "about", "com", "org", "www", "https", "http"] | index([$w]) | not))]
  | .[0:4] | join(" ");
def research($ev):
  ($ev | map(select(.kind == "tool_result")) | INDEX(.tool_id)) as $results
  | ($ev | map(select(.kind == "assistant_text" and (.side | not)))) as $replies
  | [ $ev[] | select(.kind == "tool_use" and (
        ((.tool // "") | _is_research_tool)
        or ((.tool == "Agent" or .tool == "Task") and ((.input.description // "") + " " + (.input.prompt // "") | test("research|investigat|look up|find out|compare|survey|docs|documentation"; "i")))))
      | . as $u
      | ($results[$u.tool_id] // null) as $r
      | {ts, session, tool,
         query: ($u | _research_query | _clip(200)),
         topic: ($u | _research_query | _topic | if . == "" then "(no query: \($u.tool | sub("^mcp__"; "")))" else . end),
         ok: (if $r == null then null else ($r.is_error | not) end),
         result: (if $r == null then "" else ($r.text | _meaningful_line | _clip(200)) end),
         concluded: ([$replies[] | select(.session == $u.session and (.ts // "") > ($u.ts // ""))] | sort_by(.ts) | (.[0].text // "") | _clip(240))} ]
  | sort_by(.ts);

# Research grouped by topic, newest last.
def research_topics($ev):
  research($ev) | group_by(.topic) | map({topic: .[0].topic, lookups: length, tools: (map(.tool) | unique),
                                         failed: (map(select(.ok == false)) | length), last: (sort_by(.ts) | last)})
  | sort_by(.last.ts);

def latest($records; $ev):
  active_path($records) as $path
  | ($path | map({key: ., value: true}) | from_entries) as $on
  | $ev | map(select(.kind == "assistant_text" and (.side | not) and $on[.uuid // ""])) | sort_by(.ts) | last
  | if . == null then null else {ts, session, text: (.text | _clip(700))} end;

# ------------------------------------------------------------------ outputs

def _dedupe_text: group_by(.text) | map(.[0] + {count: length}) | sort_by(.ts);

# Everything, as one JSON object.
def context:
  . as $raw | ($raw | _records) as $records | ($raw | [events]) as $ev
  | {files: ($raw | map(._file) | unique),
     sessions: sessions($ev),
     subagents: subagents($ev),
     forks: forks($ev),
     compactions: ($ev | map(select(.kind == "compact")) | length),
     intent: intent($ev),
     issues: (issues($ev) | _dedupe_text),
     successes: (successes($ev) | _dedupe_text),
     achievements: achievements($ev),
     progress: progress($ev),
     research: research($ev),
     research_topics: research_topics($ev),
     latest: latest($records; $ev)};

def _md_list($items; $n; f): ($items | length) as $len
  | if $len == 0 then ["None found."] else ($items[0:$n] | map("- " + f)) + (if $len > $n then ["- ... and \($len - $n) more"] else [] end) end;

# A concise Markdown context document.
def context_md:
  context as $c
  | [ "# Conversation context", "",
      "Rebuilt from \($c.files | length) log file(s): \($c.sessions | length) session(s), \($c.subagents | length) subagent conversation(s), \($c.forks | length) fork(s), \($c.compactions) compaction(s). Signals come from patterns: read the cited lines before relying on one.", "",
      "## Intent", "" ]
    + ($c.intent | map("- \(.ts | _ts_min) session \(.session[0:8]): \(.opening)" , (.later_goals[0:6][] | "  - later, \(.ts | _ts_min): \(.text)")) )
    + (if ($c.intent | length) == 0 then ["None found."] else [] end)
    + ["", "## Where it stands", ""]
    + (if $c.latest then ["Last reply on the active branch (\($c.latest.ts | _ts_min)):", "", "> \($c.latest.text)"] else ["No assistant reply found."] end)
    + ["", "## Achievements", ""]
    + _md_list($c.achievements.commits; 15; "\(.ts | _ts_min) commit: \(.message)")
    + ["", "Files changed most:", ""]
    + _md_list($c.achievements.files_written; 12; "`\(.path)` (\(.edits) write(s))")
    + ["", "## Progress", ""]
    + ["- Tasks created: \($c.progress.tasks_created | length). Tasks marked completed: \($c.progress.tasks_completed)."]
    + ($c.progress.tasks_created[0:12] | map("  - \(.)"))
    + ($c.progress.todos_done[0:12] | map("  - done: \(.)"))
    + ["", "## Successes", ""]
    + _md_list($c.successes; 12; "\(.ts | _ts_min) \(.source)\(if .tool then " (\(.tool))" else "" end): \(.text)\(if .count > 1 then " (x\(.count))" else "" end)\(if .command then "\n  - rerun: `\(.command)`" else "" end)")
    + ["", "## Issues", ""]
    + _md_list($c.issues; 20; "\(.ts | _ts_min) \(.source)\(if .tool then " (\(.tool))" else "" end): \(.text)\(if .count > 1 then " (x\(.count))" else "" end)\(if .command then "\n  - rerun: `\(.command)`" else "" end)")
    + ["", "## Research", ""]
    + _md_list($c.research_topics; 12; "\(.last.ts | _ts_min) \(.topic): \(.lookups) lookup(s) with \(.tools | join(", "))\(if .failed > 0 then ", \(.failed) failed" else "" end). Last: \(.last.query)\(if .last.result != "" then "\n  - found: \(.last.result)" else "" end)\(if .last.concluded != "" then "\n  - concluded: \(.last.concluded)" else "" end)")
    + ["", "## Forks", ""]
    + _md_list($c.forks; 10; "\(.when | _ts_min) the conversation branched:\n" + (.branches | map("  - \(.ts | _ts_min): \(.text)") | join("\n")))
    + ["", "## Subagents", ""]
    + _md_list($c.subagents; 12; "\(.started | _ts_min) \(.type // "agent")\(if .description != "" then ", \(.description)" else "" end): \(.tool_calls) tool call(s), \(.errors) error(s). Result: \(.result)")
    + ["", "## Sessions", "", "| Session | Start | End | Human turns | Tool calls | Errors | Interrupts |", "| --- | --- | --- | --- | --- | --- | --- |"]
    + ($c.sessions | map("| \(.session[0:8]) | \(.start | _ts_min) | \(.end | _ts_min) | \(.human_turns) | \(.tool_calls) | \(.errors) | \(.interrupts) |"))
    + ["", "Files: " + ($c.files | map("`\(.)`") | join(", "))]
  | join("\n");
