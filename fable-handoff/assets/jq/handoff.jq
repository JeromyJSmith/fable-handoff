# handoff.jq: queries over fable/handoff_spec.json.
#
# Load it with -L pointing at this directory, then include it:
#
#   jq -L SKILL/assets/jq 'include "handoff"; summary' fable/handoff_spec.json
#   jq -L SKILL/assets/jq -r 'include "handoff"; problems_text' fable/handoff_spec.json
#   jq -L SKILL/assets/jq -e 'include "handoff"; ready' fable/handoff_spec.json   # exit 1 when not ready
#
# Tested with jq 1.7. Written to avoid builtins added after 1.6. The rules in `problems` are the same as in
# scripts/spec_tool.py, which is the authority; a test keeps the two equal.
# The input is assumed to be schema-valid. Run spec_tool.py check for the schema.

def _words: [splits("\\s+") | select(length > 0)] | length;
def _human: "ask me|wait for (my|the owner'?s?|the user'?s?) (approval|answer|reply|confirmation)|check with me|let me know|i will review|i'll review";
def _protected_branches: ["main", "master", "production", "prod", "release"];
def _p($severity; $path; $message): {severity: $severity, path: $path, message: $message};

# Every readiness problem, sorted by path then message.
# Each rule is wrapped in parentheses: `|` binds more loosely than `,`, so an
# unwrapped `select` would also drop every rule after it.
def problems:
  . as $s
  | [
      ((($s.goal.job // "") | _words) as $n | select($n < 40)
        | _p("FAIL"; "goal.job"; "is \($n) words; state the whole outcome in at least 40"))
    , ((($s.goal.why // "") | _words) as $n | select($n < 20)
        | _p("FAIL"; "goal.why"; "is \($n) words; say who it is for and what wins in a tradeoff, in at least 20"))
    , (("job", "why") as $k | select(($s.goal[$k] // "") | test(_human; "i"))
        | _p("FAIL"; "goal.\($k)"; "assumes a person will answer during the run"))
    , (select(($s.commands.verify // "") | test("\\S") | not)
        | _p("FAIL"; "commands.verify"; "is empty; the run needs one command that passes only when the job is done"))
    , (($s.open_questions // [] | to_entries[])
        | _p("FAIL"; "open_questions[\(.key)]"; "is still open: \(.value.question)"))
    , (($s.acceptance_criteria // [] | to_entries[])
        | select(.value.status == "open" and ((.value.verified_by // "") | test("\\S") | not))
        | _p("FAIL"; "acceptance_criteria[\(.key)]"; "'\(.value.id)' is open but no test or eval checks it"))
    , (select(($s.tasks // []) | length == 0)
        | _p("FAIL"; "tasks"; "is empty; seed the ledger with the first checkable results"))
    , (([$s.acceptance_criteria // [] | .[].id]) as $ids
        | ($s.tasks // [] | to_entries[]) as $t
        | ($t.value.criteria // [])[] as $cid
        | select($ids | index([$cid]) | not)
        | _p("FAIL"; "tasks[\($t.key)]"; "refers to unknown criterion '\($cid)'"))
    , ([$s.acceptance_criteria // [] | .[] | select((.verified_by // "") | test("\\S")) | .id] as $verified
        | ($s.tasks // [] | to_entries[])
        | select(((.value.check // "") | test("\\S") | not) and ([(.value.criteria // [])[] | select(. as $c | $verified | index([$c]))] | length == 0))
        | _p("WARN"; "tasks[\(.key)]"; "names no check and no verified criterion, so only the checkbox says it is done"))
    , (select(($s.guardrails.pre_approved // []) | length == 0)
        | _p("FAIL"; "guardrails.pre_approved"; "is empty; name the routine actions the run may take without asking"))
    , (($s.guardrails.forbidden // [] | to_entries[])
        | select(((.value.enforced_by.protected_paths // []) | length) + ((.value.enforced_by.blocked_bash_patterns // []) | length) == 0)
        | _p("FAIL"; "guardrails.forbidden[\(.key)]"; "no protected path or blocked command enforces it"))
    , (select(($s.guardrails.out_of_scope // []) | length == 0)
        | _p("WARN"; "guardrails.out_of_scope"; "is empty; name adjacent work to leave alone"))
    , (($s.run.branch // "") as $b | select(_protected_branches | index([$b]))
        | _p("FAIL"; "run.branch"; "'\($b)' is a protected branch; use a run branch such as fable/my-job"))
    , (select($s.run.max_budget_usd == null)
        | _p("WARN"; "run.max_budget_usd"; "is not set, so nothing caps the spend"))
    , (($s.traps // [] | to_entries[])
        | select((.value.instead // "") | test("\\S") | not)
        | _p("WARN"; "traps[\(.key)]"; "says what went wrong but not what to do instead"))
    , (select((($s.traps // []) | length) == 0 and (($s.practices_to_keep // []) | length) == 0)
        | _p("WARN"; "traps"; "no history recorded; ask the owner what failed and what worked"))
    , (select(($s.decisions // []) | length == 0)
        | _p("WARN"; "decisions"; "none recorded; every question the run might ask should be answered here"))
    ]
  | sort_by(.path, .message);

def fails: [problems[] | select(.severity == "FAIL")];

# true when nothing FAILs. Use with jq -e in scripts and CI.
def ready: fails | length == 0;

# One line per problem, for people.
def problems_text: problems[] | "\(.severity)\t\(.path)\t\(.message)";

# Counts at a glance.
def summary: {
  project: .project.name,
  ready: ready,
  fails: (fails | length),
  warns: ([problems[] | select(.severity == "WARN")] | length),
  criteria: {open: ([.acceptance_criteria[]? | select(.status == "open")] | length),
             done: ([.acceptance_criteria[]? | select(.status == "done")] | length)},
  tasks: (.tasks | length),
  open_questions: (.open_questions | length),
  decisions: (.decisions | length),
  traps: (.traps | length),
  forbidden: (.guardrails.forbidden | length),
  verify: .commands.verify
};

# Focused lists for the interview and the review.
def open_questions: .open_questions[]? | "\(.question)\(if .source then "  (\(.source))" else "" end)";
def unverified: .acceptance_criteria[]? | select(.status == "open" and ((.verified_by // "") == "")) | "\(.id)\t\(.text)";
def unenforced: .guardrails.forbidden[]? | select(((.enforced_by.protected_paths // []) + (.enforced_by.blocked_bash_patterns // [])) | length == 0) | .action;
def criteria_without_task:
  ([.tasks[]?.criteria[]?] | unique) as $covered
  | .acceptance_criteria[]? | .id as $id | select(.status == "open" and ($covered | index([$id]) | not)) | "\(.id)\t\(.text)";

# What the hooks will enforce, merged from every forbidden entry.
def enforcement: {
  protected_paths: ([.guardrails.forbidden[]?.enforced_by.protected_paths[]?] | unique),
  blocked_bash_patterns: ([.guardrails.forbidden[]?.enforced_by.blocked_bash_patterns[]?] | unique)
};

# Where each piece came from.
def sources_by_role: (.sources // []) | group_by(.role) | map({key: .[0].role, value: map(.path)}) | from_entries;
def provenance:
  [ (.acceptance_criteria[]? | {item: "criterion \(.id)", source}),
    (.decisions[]? | {item: "decision: \(.decision)", source}),
    (.traps[]? | {item: "trap: \(.text)", source}),
    (.open_questions[]? | {item: "question: \(.question)", source}) ]
  | map(select(.source != null));

# Markdown fragments, for pasting or review.
def tasks_md: .tasks[]? | "- [ ] \(.text)\(if .check then " (check: `\(.check)`)" else "" end)\(if .route then " [route: \(.route)]" else "" end)";
# Tasks grouped by who should do them.
def routing: [.tasks[]? | {route: (.route // "unrouted"), text}] | group_by(.route) | map({key: .[0].route, value: map(.text)}) | from_entries;
def traps_md: .traps[]? | "- \(.text)\(if .instead then " Instead: \(.instead)" else "" end)";
def criteria_tsv: .acceptance_criteria[]? | [.id, .status, (.verified_by // ""), .text] | @tsv;
