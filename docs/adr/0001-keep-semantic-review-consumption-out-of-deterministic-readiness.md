# Keep Semantic Review Consumption Out Of Deterministic Readiness

RDL deterministic readiness validates schema, normalized state, subject
bindings, typed blocking state, and local artifact facts. It does not infer
evidence quality, overclaim, or staleness from prose. Those judgments enter the
gate only as a typed `review_result` produced through an explicit semantic
review adapter.

This keeps lightweight parser checks from growing into scattered research
judgment policy. The normal `rdl review --for ...`, `rdl apply`, `rdl next`,
and `rdl close` flow can consume reviewer findings while keeping deterministic
findings limited to locally verifiable facts.
