# Artifacts And Events

Index artifacts in `artifact-manifest.json`; do not copy project artifacts into
RDL. Cite artifacts explicitly as `[artifact:ID]` in evidence and decisions.
Use `rdl record artifact` for existing local files or `http(s)` URLs; local
file entries record size and sha256. Local artifacts default to
`stability: snapshot`, where size or sha256 mismatch blocks the gate. Use
`live-path` only for intentionally mutable project files; drift is reported as
a warning instead of a blocker.

Use optional round-local `events.md` for operational events that matter for
recovery but are not decision-grade evidence: command timeouts, partial
transfers, retries, cache or working-directory requirements, and environment
notes.

Keep `evidence.md` focused on evidence that changes a claim or capability
decision.

Keep markdown templates as the protocol surface.
