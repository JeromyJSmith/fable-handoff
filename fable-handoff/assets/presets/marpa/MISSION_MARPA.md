## MARPA

This run works in the MARPA budget standard repository for MARPA Design Studios, a landscape architecture and design-build construction firm in Boulder. Read CLAUDE.md, AGENTS.md, SPEC.md, MARPA_STANDARD.md and HANDOFF.md before the first task. The rules in CLAUDE.md are the owner's rules; they are kept exactly as written.

Where things are:

- The standard: MARPA_STANDARD.md, master_categories.yaml (the budget slots), budget_standard.yaml, standard_terms.yaml and class_vocabulary.yaml.
- The owner's rulings and decisions: class_rulings.yaml and DECISIONS.md. A ruling is decisive for its own project only. Another project's decision is never a vote.
- The detective standard: docs/standard/DETECTIVE_STANDARD.md and detective_functions.yaml. Every question of fact is a case with a subject (a class, layer, budget line, term, fee or setting, in one project), candidates, evidence, a verdict and a record.
- Jev decisions: jev_schemas.yaml and jev_schema.py. Jev is called only for a decision with a written schema there. No schema, no call.
- The drawings: Vectorworks exports listed in inventory/export_inventory.ndjson, read as NDJSON in ndjson/raw/ (drawn_class, drawn_object, drawn_label, dxf_class_evidence). Read docs/DRAWING_INPUT_METHOD.md before any VWX text export.
- The questions for the firm: a BCF 3.0 file, bcf/fable-questions.bcf, one topic per open policy case. MARPA's own question file, bcf/marpa-questions.bcf, is written only by bcf_questions.py.

The class-word grammar. A Vectorworks class name is read as family, head word and modifiers. For example "L-Detail Material-Aggregate" has the family L (landscape), the head word Aggregate and the modifier Detail Material. A modifier such as Existing, Proposed, Labels or Detail Material changes how the class is read, never what the head word names. A single class word is weak evidence; an exact standard term or alias in the name is strong.

The pipe. A source becomes NDJSON in ndjson/raw/, jq keeps only what the budget system reads, transform.jq shapes it, and it loads into DuckDB through the writer lock. The cases go to the detective_case and detective_evidence tables the same way. fable/cases.json and fable/CASES.md are the run's own record of them.
