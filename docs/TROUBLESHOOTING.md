# Troubleshooting

One document for every finding taken from run output (the owner's rule of 2026-11-16: runs are read only to find what went wrong; once a finding is solved, its run output is deleted). Each finding says what was seen, the evidence, the cause, the fix, and its state.

## The standard repository's tests rewrote tracked screenshots

- **Seen:** the readiness check failed "git clean": each verify run left `docs/standard/evidence/accessibility/lines-dark-375.png` and `lines-light-375.png` changed.
- **Cause:** `tests/test_accessibility.py` wrote its screenshots over the committed ones.
- **Fix:** the standard repository's commit 38af501. The test writes each run's screenshots to a new dated folder under this package's runs/ (FABLE_RUNS_DIR).
- **Evidence:** on fresh copies at commit ae13485, readiness passed with no failure.
- **State:** solved. The run output it left (runs/2026-11-16_*_accessibility/) may now be deleted.

## A test overwrote three allocation documents

- **Seen:** `/Volumes/MARPA/method/allocation/AEC-ALLOWANCE-METHOD.md`, `SPEC.md` and `DESIGN-TO-COST-SPEC.md` held "x" or "{}" between 17:54 and 18:18 on 2026-11-16.
- **Cause:** two preset tests wrote placeholder files at every path the preset names, including absolute paths outside the repository.
- **Fix:** the tests write only under their temporary folder, and conftest fingerprints every outside path and fails the run on any change (commits 823da3d and 1dbdef3). The documents are back to their committed text (105, 331 and 244 lines).
- **State:** solved.

## The Ulm slope setting and the sod-timing note were dropped by a pipeline run

- **Seen:** intent.py on the standard repository's conversation logs lists "10.7%, 2 WEEKS" as lost.
- **Cause, from the firm's task log:** a rewording inside text_functions.yaml changed the Jev schema's fingerprint, and the next pipeline run rebuilt `text_function` empty. The wording was restored and the table rebuilt (2,075 rows).
- **State:** open. The latest messages ask where the Ulm slope (10.7%) and the "2 WEEKS" note now sit in the working database; a plain-text search of `text_function` found neither. This belongs to the MARPA Standard session's stage 1 audit.
