# The detective standard

Read this before the run settles any question from evidence, and when you set
up `detective_functions` for a project. "Do detective work" is a slogan until
it is defined; this file defines it: named functions, each with a described
input and output, a strength of evidence, rules that combine evidence into a
verdict, and a written case file. The code is `fable/detective.py`.

## Contents

1. The case
2. The detective functions
3. Strength of evidence
4. The verdict rules
5. The case file and routing
6. Proving it works: the back-test
7. Setting it up for a project

## 1. The case

Every investigation is a case in `fable/cases.json`:

| Field | Meaning |
| --- | --- |
| `id`, `subject` | What is investigated: a class, layer, budget line, term, fee, setting, file or function, in one project |
| `question` | Where does it go, what is it, what is its value |
| `candidates` | The candidate answers |
| `evidence` | One item per finding: `function`, `source` (the underlying thing it read), `found`, `supports` (a candidate), optional `strength`, `link`, `rung`, `quantity` |
| `nature` | `policy` or `preference` when the question is the owner's choice |
| `adjudication` | Optional: `by`, `answer`, `confidence`, `reasoning` |
| `owner_question` | For a policy case: the full question record (judgment test) |
| `result` | The verdict, computed, never written by hand |

## 2. The detective functions

Each function is described before it is used, in `detective_functions` in
`fable/handoff.json`: `name`, `looks_at`, `returns`, `strength`, `status`
(`built` or `planned`) and `test`, optionally `strong_when` and `weak_when`.
Evidence from an unregistered or planned function makes the case invalid.

The default registry is generic: name match, content, text in documents,
relationships, quantity match, rules and precedent, the owner's own words,
outside standards, back-test, and gap analysis. A project replaces it with its
own. A landscape design-build firm, for example, registers: name match against
its class vocabulary; drawing content; text on the drawing; spatial
relationships; budget match; rules and precedent; the firm's own words through
the connectors; outside standards such as IFC or MasterFormat; back-tests on
past projects; gap analysis; and an adjudicator.

## 3. Strength of evidence

From weakest: **lead** (gap analysis: where to look, never a verdict),
**supporting**, **strong**, **decisive** (a rule or ruling that answers it).
An item's strength is the function's, unless the item says otherwise.

- **Independence.** Two items count as two sources only when their `source`
  differs. Name match and text in documents reading the same label are one
  source.
- **Quantities.** An item with `quantity` (`measured`, `measured_unit`,
  `stated`, `stated_unit`) counts as strong only when the two agree within
  `quantity_tolerance` after unit conversion (sf, m2, lf, m, cy, m3, each and
  others). Outside the tolerance it only supports.

## 4. The verdict rules

| Verdict | When |
| --- | --- |
| settled | A decisive source with no decisive source against it; or two independent strong sources that agree, with no strong source against them |
| open, policy (conflict) | Decisive sources disagree: the rules conflict, so the owner decides which applies |
| likely | One strong source, or strong contradicted only by supporting evidence |
| settled by adjudication | A likely case whose adjudicator answers the same candidate with written reasoning and a confidence at or above the threshold. Kept apart from settled by evidence |
| open, fact | Strong sources disagree, or the evidence is missing; the case names what would settle it and returns to the queue |
| open, policy | Nothing settles it and it is a matter of policy or preference |

No verdict rests on leads alone or on one weak source. The adjudication
threshold is `adjudication_threshold` (0.70) until the back-test calibrates
it; a model's stated confidence is not a probability until it has been
checked against decided cases.

## 5. The case file and routing

`uv run --script fable/detective.py verdicts` recomputes every verdict and
writes `fable/CASES.md`, each case in plain words.
`uv run --script fable/questions.py route` acts on them:

- settled, or settled by adjudication: a decision in the decisions log,
  marked "by evidence" or "by adjudication", and an entry in
  `fable/evidence_decisions.json`;
- open, policy: the case's `owner_question` goes to the question system with
  the case attached, after the judgment test, and its task is parked;
- open, fact: stays in the queue with what would settle it.

Owner-facing text is written in words. A question that leans on bare codes
("D121", "rule 12") is refused.

## 6. Proving it works: the back-test

Build a set of cases the owner already decided, each with `owner_answer` and
`ruling_sources` (where that ruling is written). Then:

```bash
uv run --script scripts/detective_backtest.py --project . --cases decided.json --write-calibration
```

The run is blind: evidence drawn from a case's own ruling is removed first, so
no function "finds" the answer it is tested on. It reports, per function and
overall, how often the detective reaches the owner's answer and where it went
wrong, and calibrates the adjudication threshold to the lowest confidence that
was right at least `--target` of the time. A function that is often wrong is
weakened in the registry or fixed, never trusted.

## 7. Setting it up for a project

1. Replace `detective_functions` with the project's real functions; mark the
   ones not built yet as `planned`.
2. Set `quantity_tolerance` per dimension (`area`, `length`, `volume`,
   `count`) or `default_pct`.
3. Build the decided set and run the back-test before the run relies on
   adjudication.
4. Then run the open questions as cases.
