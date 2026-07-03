<!-- rdl:managed policy=managed_prefix -->
# Round {{ROUND}} Prompt

Mode: {{MODE}}
Profile: {{PROFILE}}
Objective: {{OBJECTIVE}}
Claim or Capability Under Review:
{{CLAIM_OR_CAPABILITY_UNDER_REVIEW}}
Previous Decision: {{PREVIOUS_DECISION}}
Required Files: {{REQUIRED_FILES}}
Open Questions:
{{OPEN_QUESTIONS}}
Known Evidence Gaps:
{{KNOWN_EVIDENCE_GAPS}}
Directions Tried:
{{DIRECTIONS_TRIED}}
Staleness Watch:
{{STALENESS_WATCH}}
Next Smallest Step: {{NEXT_SMALLEST_STEP}}
Expected Exit Decision: {{EXPECTED_EXIT_DECISION}}

Start-of-round check: read rdl handoff, mission.md, progress.md, factors.md,
decision-ledger.md, and previous round records when present.
During-round check: use optional events.md for operational events such as
timeouts, partial transfers, retries, cache notes, and environment details that
matter for recovery but are not decision-grade evidence.
Before rdl next: update session memory with rdl progress and rdl factors when
state, blockers, factors, assumptions, open questions, or next steps changed.
<!-- /rdl:managed -->

## Notes
