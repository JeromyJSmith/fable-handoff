## MARPA

Building the product:

- Quantities come from the drawing's geometry, never typed in. Each budget line records the class, the geometry it was measured from, the unit, the rate and where the rate came from.
- A gap between a generated budget and the firm's real one is explained in plain words or parked as a question. Never close a gap by changing the real budget or the tolerance.
- The desk app is not part of stages 1 to 3; leave it untouched until the owner decides about it after stage 1.
- Run output goes to the git-ignored runs/ folder and is never committed.
- Agents never mine old runs for information or use them as a source. This run does not read runs/ at all; the guard blocks it. Findings from runs live in the troubleshooting document, which people write when they troubleshoot.
- The allocation engine in /Volumes/MARPA/method/allocation is read and run through its own commands only; never edit its code, guide or adjustments.
- No language model call in any calculation. Jev only for bounded decisions under a written schema, in the files deterministic_code allows.

Keeping the standard (the owner's rules in CLAUDE.md):

- Take the writer lock before any write to the working database: set MARPA_AGENT to this run's branch name and run writer_lock.py take. If another agent holds it, park the task and continue with work that does not write the database. Release it when you stop writing.
- Write the database only through run_pipeline.sh or rebuild.sh, which archive it first. Loads go source, NDJSON, jq, transform.jq, DuckDB.
- A fix goes everywhere it belongs in one task: the rule or word list, the data, the budget categories, MARPA_STANDARD.md, SPEC.md, DECISIONS.md and HARDENING.md.
- Class-word grammar: a class name is family, head word and modifiers ("L-Detail Material-Aggregate": family L, head word Aggregate, modifier Detail Material). A modifier changes how the class is read, never what the head word names. One class word is weak evidence; an exact standard term or alias is strong.
- Adjudication is Jev under a written schema from jev_schemas.yaml: the case records the schema, the options offered, the answer, the confidence, the companions' answers, each post-check and the receipt. An answer below the threshold is kept as the suggestion. The OTHER answer is never applied. The threshold is the measured one in fable/calibration.json.
- Record each finished task in /Volumes/MARPA/apps/marpa-desk/TASKS.md with the commit, the test result and the state.
- Never send mail to a client, never touch the desk app's Pixeltable home, and never write MARPA's own BCF file.
- Questions for the firm are written in plain words: what the thing is (project, sheet, class or line, what it draws or costs), what is in conflict, each option and what it does, and your recommendation. Never a bare decision number.
