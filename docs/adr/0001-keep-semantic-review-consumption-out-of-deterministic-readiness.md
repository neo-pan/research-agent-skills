# Keep Semantic Review Consumption Out Of Deterministic Readiness

RDL deterministic readiness will validate protocol, schema, managed-summary,
state, and local artifact facts, but it will not interpret semantic review
output such as blocked verdicts, evidence gaps, staleness risk, or recommended
decision mismatch. Those review results may still block or warn, but only after
being consumed through the semantic review adapter and surfaced as semantic gate
findings.

This keeps lightweight parser checks from growing into scattered research
judgment policy. It also preserves the normal `rdl doctor`, `rdl next`,
`rdl close`, and `rdl review --pack` flow: users still see blocking gate
results, while reviewers receive deterministic findings that are limited to
locally verifiable facts.
