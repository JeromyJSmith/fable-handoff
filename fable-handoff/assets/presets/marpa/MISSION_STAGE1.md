### This run is stage 1 of 3: the data

Load every past project that has a budget, with its own budget as the truth, through JSON and jq, until everything needed to allocate and estimate is in. Do not estimate anything. The MARPA Standard session's stage 1 audit (tests/test_audit_stage1.py and its definition of done) is the measure:

- every budget file loaded, including inputs/owner-import-2026-11-16 and Mallett's drawing;
- the component digit kept in every code: a component is never an item of its own;
- the 153 uncoded lines worked out: each has a slot, item and component, or an open case with what would settle it;
- the line_measure and item_measure tables built;
- the finance formula check done;
- every budgeted project's .vwx decoded with the repository's own vwx/run_vwx.sh.

Done is `done_check.py --check --stage 1`; when it passes it writes fable/done/stage1.json with the commit, which stage 2 requires before it launches.
