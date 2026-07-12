# Issue tracker: Local Markdown

Issues and specs (also known as PRDs) for this repo live as markdown files in
`.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state is recorded as a `Status:` line near the top of each issue file; see `triage-labels.md`
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/`, creating the directory if needed.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or issue number directly.

## Wayfinding operations

The `wayfinder` skill uses a map file with one child file per investigation
ticket:

- Map: `.scratch/<effort>/map.md`, containing Destination, Notes,
  Decisions-so-far, Not-yet-specified, and Out-of-scope sections.
- Child ticket: `.scratch/<effort>/issues/<NN>-<slug>.md`, numbered from `01`.
  A `Type:` line records `research`, `prototype`, `grilling`, or `task`; a
  `Status:` line records `open`, `claimed`, or `resolved`.
- Blocking: a `Blocked by: NN, NN` line. A ticket is unblocked when every listed
  ticket is resolved.
- Frontier: the open, unblocked, unclaimed child tickets, ordered by number.
- Claim: set `Status: claimed` and save before beginning work.
- Resolve: append the answer under `## Answer`, set `Status: resolved`, then add
  a gist and link to the map's Decisions-so-far section.
