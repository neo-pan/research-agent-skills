# RDL Operations

## Executable next actions

Before `next`, make `decision.next_step` state the smallest evidence action, its task-specific completion condition, the expected later transition when known, and remaining phases. Multi-round requirements belong in mission, unfinished progress, or that instruction.

## Receipt-first apply

Freeze the command, exit, decisive output, environment boundary, and stable project-relative snapshot before composing apply JSON. Typical patterns are:

```text
research: artifact receipt + evidence + uncertainty -> apply
build: failing receipt -> apply -> implement/verify -> passing receipt + decision -> apply
review: exact action/digest/adapter + adjudicated findings -> apply review_result
```

Use current versions and real references; do not copy placeholder payloads into a session.

## Terminal audit

After close, retain one compact audit covering final handoff and doctor, exact close replay, current-version terminal mutation rejection, stale-request rejection, and unchanged pointer, generation set, state version, and recursive store digest.
