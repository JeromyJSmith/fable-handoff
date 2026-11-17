<!-- draft: prepare.py phase 6 completes this -->
# Decisions

## Made before the run

- Three data-first stages: the data, the weighted averages, the benchmark; each its own run. Reason: the owner's decision of 2026-11-16; nothing is estimated before the data is in.
- Allowances first: each category allowance from the project settings is spread top-down onto that category's drawn classes. Reason: this is how MARPA budgets (the allocation method).
- The allocation engine is read and run through its own commands; the run integrates with it and does not rebuild it. Reason: it already conserves every dollar on six projects.
- Every calculation is plain code with tests; Jev answers only bounded decisions under the written schemas. Reason: the owner's rule for deterministic calculations.
- A project's own budget is never used to estimate it. Reason: held-out validation.
- The desk app is left alone until stage 1 is through. Reason: the owner's decision of 2026-11-16.
- Quantity tolerances stay as they are: area and length 5 percent, counts exact, volume 10 percent, weight never compared. Reason: the owner's decision of 2026-11-16.
- The answers in fable/owner_decisions.json, once given, are the owner's decisions for this run.

## Defaults for anything not listed

- Prefer the option that is easiest to undo.
- Prefer the smallest change that satisfies the mission.
- Follow the conventions already in the codebase over personal preference.

## Open questions for the owner

None.

## Made during the run

## Left for the owner
