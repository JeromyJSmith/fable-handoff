## MARPA

- Take the writer lock before any write to the working database: set MARPA_AGENT to this run's branch name and run writer_lock.py take. If another agent holds the lock, park the task and continue with work that does not write the database. Release the lock when you stop writing.
- Write the database only through run_pipeline.sh or rebuild.sh, which archive it first.
- Adjudication is Jev under a written schema. An adjudication record in a case names its schema from jev_schemas.yaml, lists the options offered, gives the answer, the confidence, the companions' answers, the result of each post-check and the receipt path in jev-receipts/. An answer below the gate is kept as the suggestion and settles nothing. The OTHER answer is never applied.
- The adjudication threshold is the measured cutoff in fable/calibration.json (0.90 on the owner's ruled cases), not the 0.70 gate Jev uses for its own answers.
- A fix goes everywhere it belongs in one task: the rule or word list, the data, the budget categories, MARPA_STANDARD.md, SPEC.md, DECISIONS.md and HARDENING.md.
- Record each finished task in /Volumes/MARPA/apps/marpa-desk/TASKS.md with the commit, the test result and the state.
- Never send mail to a client, never touch the desk app's Pixeltable home, and never write MARPA's own BCF file.
- Questions for the firm are written in plain words: what the thing is (project, sheet, class or line, what it draws or costs), what is in conflict, each option and what it does, and your recommendation. Never a bare decision number.
