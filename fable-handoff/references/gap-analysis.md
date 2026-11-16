# Gap analysis and bridging

Read this when evidence that should connect does not: a label in the drawings
with no line in the budget, a rule in the spec with no column in the data, a
question nobody can place. Run it in phase 1, again before the owner
interview, and during the run whenever the evidence ladder comes up empty.

## Contents

1. What it is for
2. With the InfraNodus connector
3. Without it: the built-in check
4. Turning a gap into evidence
5. Recording gaps and how they closed

## 1. What it is for

Detective work fails most often because two things that belong together are
never read side by side. Gap analysis maps the concepts in the project's text
and shows the clusters that nothing links. Each gap suggests a bridge: a place
to look for the evidence that ties the clusters together. A bridge is a lead
to verify, never a decision.

The texts analysed: the project's specs and documents, the open questions,
code comments, and data descriptions (column headers, schema descriptions).

## 2. With the InfraNodus connector

When the InfraNodus tools are available (`generate_content_gaps`,
`develop_conceptual_bridges`, `analyze_text`), use them:

1. Write the corpus: `uv run --script scripts/gap_analysis.py --project .
   --corpus-out fable/.run/gap_corpus.txt`.
2. Run `generate_content_gaps` on that text, then
   `develop_conceptual_bridges` for each gap worth following. Use
   `analyze_text` for the cluster overview.
3. Record each gap it reports: `gap_analysis.py --project . --add "<cluster A>
   | <cluster B>" --lead "<the bridge to check>" --source infranodus`.

## 3. Without it: the built-in check

`uv run --script scripts/gap_analysis.py --project .` builds a concept
co-occurrence graph with networkx, pinned in the script's uv header. Terms are
nodes; two terms are linked when they appear in the same sentence. It reports:

- **disconnected** components: term groups that share no sentence with the
  main body of the text;
- **weak links between clusters**: communities in the main graph
  (greedy modularity) with almost no links between them;
- **weakly linked terms**: frequent terms with at most one neighbour.

It writes `fable/gaps.json` and `fable/GAPS.md`. It uses wording only, so a
gap can be an artefact of how documents are written. Check before acting.

## 4. Turning a gap into evidence

For each gap, look for the document, label, drawing note, data field or past
decision that ties the two sides together, on the evidence ladder in
`fable/handoff.json`. Three outcomes:

- the evidence connects them: record the link, and settle any question it
  answers as a decision by evidence;
- the evidence shows they are separate: record that, and the gap is closed;
- the evidence cannot decide it and it is policy or preference: it becomes a
  judgment call with a full question record (see `fable-behaviors.md`,
  section 14).

## 5. Recording gaps and how they closed

`gap_analysis.py --project . --close gap-3 --how "<the evidence>"` closes a
gap with the evidence that settled it. The post-run review lists every gap
found, how each was closed, and the ones still open.
