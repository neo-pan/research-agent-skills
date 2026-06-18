---
name: phase-review
description: Manual independent review gate for research engineering plans, implementation phases, evidence, and final readiness. Use only when explicitly invoked.
disable-model-invocation: true
---

# Phase Review

Run a skeptical, bounded review before proceeding. This is a review-only gate:
do not edit files, implement fixes, broaden scope, or introduce new
requirements.

Infer the smallest review target that satisfies the user's invocation, state the
boundary explicitly, then prefer an independent review-only Codex subagent when
available. If subagent tooling is unavailable or prohibited, perform the same
review locally and state the fallback reason.

## Review Targets

- **Implementation**: changed code, tests, benchmarks, and completion claims
  after a phase of work.
- **Plan**: implementation plan, draft, task breakdown, acceptance criteria, or
  milestone design before coding starts.
- **Context proposal**: proposed approach described in conversation, with no
  file or diff yet.
- **Evidence**: tests, benchmarks, profiling, root-cause analysis, ablations, or
  other evidence used to justify a decision.
- **Final gate**: pre-merge, pre-submit, or pre-finish check across the final
  relevant diff, verification, deferrals, and scope.

## Workflow

1. Determine the review target and boundary.
   - Use the latest explicit user request as the primary scope.
   - Choose the smallest target that satisfies the wording.
   - State reviewed artifacts, unreviewed artifacts, assumed phase goal, and the
     decision being gated.
   - Ask for clarification only when the target cannot be inferred without high
     risk of reviewing the wrong artifact.

2. Gather only target-relevant context.
   - Implementation: original request or plan, claimed completion summary,
     changed files or diff, and relevant verification.
   - Plan: original request, constraints, plan draft, acceptance criteria,
     sequencing, dependencies, and path boundaries.
   - Context proposal: proposal text, goals, assumptions, constraints, excluded
     work, and cited evidence.
   - Evidence: claim being evaluated, raw evidence, setup or commands, expected
     vs observed result, controls, and the decision it supports.
   - Final gate: final diff, original scope, verification summary, known
     deferrals, generated or local-only files, and merge or release constraints.

3. Delegate when available.
   - Spawn a review-only Codex subagent when subagent tooling is available.
   - Tell the subagent not to edit files, run destructive commands, broaden the
     task, or introduce new requirements.
   - Include the inferred target, explicit boundary, relevant artifacts, and the
     rubric below.
   - Treat subagent findings as review input, not automatic truth; verify enough
     context to avoid passing through false positives.

   Suggested subagent prompt:

   ```text
   You are an independent review-only Codex subagent. Review the provided target
   within the stated boundary. Do not edit files. Do not run destructive
   commands. Do not introduce new requirements. Do not broaden the task.

   If the target is code, review it against the plan, diff, tests, and stated
   verification. If the target is a plan or proposal, review feasibility,
   completeness, sequencing, acceptance criteria, assumptions, unnecessary
   complexity, compatibility or fallback work, and scope control. If the target
   is evidence, review whether the evidence supports the claim. If the target is
   a final gate, review final scope, verification, deferrals, and readiness.

   Classify findings as blocking, non-blocking, or out of scope.
   ```

4. Apply the gates.
   - **Plan alignment**: required acceptance items are complete or explicitly
     pending.
   - **Correctness**: behavior, edge cases, and integration points match the
     intended contract.
   - **Plan quality**: goals, acceptance criteria, dependencies, sequencing,
     validation, and path boundaries are clear enough to execute.
   - **Feasibility**: the proposal can plausibly be implemented with available
     repository patterns, tools, and constraints.
   - **Evidence quality**: measurements, diagnostics, or root-cause claims
     support the decision without cherry-picking, stale assumptions, missing
     controls, or overclaiming.
   - **Final readiness**: the final state matches the requested scope, has no
     unresolved blocking deferrals, and has proportionate verification.
   - **Minimality**: no speculative abstraction, broad framework, extra
     configuration, or generalized machinery unless required by the plan or
     existing architecture.
   - **Compatibility discipline**: no redundant legacy fallback, unused
     compatibility path, defensive branch, migration shim, or permissive parsing
     unless justified by a real supported input or existing contract.

5. Classify findings.
   - **Blocking**: violates the plan, breaks correctness, hides a material test
     or evidence gap, is infeasible, is too ambiguous to execute, or adds harmful
     complexity that should be removed before proceeding.
   - **Non-blocking**: useful cleanup, clarification, or future hardening that
     does not affect this phase's acceptance or decision.
   - **Out of scope**: unrelated improvements, style preferences, broad
     rewrites, or new requirements.

6. Return findings only.
   - Do not fix issues inside this review.
   - If blocking fixes are needed, return `BLOCKED` and the required changes.
   - If the user wants fixes, they should start a separate implementation step
     or explicitly ask to continue after the review.

## Rubric

For all targets:

- What exactly is being reviewed, and what is outside the boundary?
- Does the target satisfy the user's current request without silently deferring
  required work?
- Are assumptions, dependencies, and excluded work explicit enough?
- Is there speculative abstraction, generalized machinery, or broad
  compatibility work that is not justified?
- Are validation steps concrete and proportional to risk?

For implementation reviews:

- Are all changed files necessary for this phase?
- Is any new abstraction used by only one caller without a clear reason?
- Is any fallback or compatibility branch unreachable, untested, or unsupported?
- Did the code preserve existing repository patterns instead of introducing a
  parallel style?
- Are tests or benchmarks targeted to the behavior that changed?
- Did the implementation touch generated files, local-only files, credentials,
  or unrelated surfaces?

For plan or proposal reviews:

- Is the goal precise enough to drive implementation?
- Are acceptance criteria testable and complete?
- Are milestones ordered so risk is retired early?
- Are path boundaries clear: maximum scope, minimum viable scope, allowed
  choices, and rejected choices?
- Does the plan avoid prescribing unnecessary architecture before the codebase
  demands it?
- Does it avoid compatibility, migration, fallback, or configurability work that
  lacks a concrete supported scenario?

For evidence or final-gate reviews:

- Does the evidence support the stated conclusion without overclaiming?
- Are benchmark, profiling, test, or diagnostic results reproducible enough for
  the decision being made?
- Are controls, baselines, setup, and raw artifacts sufficient to trust the
  interpretation?
- Are unresolved deferrals explicit and genuinely non-blocking?
- Did the final state avoid unrelated changes, local-only files, generated
  churn, and unrequested cleanup?

## Output Format

Return findings first. Keep the response concise and actionable.

```markdown
Verdict: PASS | PASS_WITH_NOTES | BLOCKED

Review Target:
- Type: implementation | plan | context-proposal | evidence | final-gate
- Boundary:
- Reviewed artifacts:
- Not reviewed:
- Decision gated:

Blocking Findings:
- [severity] location - issue, why it matters, required fix

Non-Blocking Notes:
- location - note or follow-up

Alignment / Scope:
- Satisfied:
- Pending:
- Out of scope:

Minimality / Compatibility:
- Unnecessary complexity found: yes/no
- Redundant compatibility found: yes/no
- Required removals:

Verification / Evidence:
- Checks or evidence reviewed:
- Checks or evidence still needed:
- Fallback reason, if no subagent review:
```

Use `location` as `file:line` for code or file-backed plans, and as a plan
section, bullet name, evidence artifact, or conversation reference for
context-only reviews.

Use `PASS` only when the target satisfies the requested boundary and no blocking
findings remain. Use `PASS_WITH_NOTES` when only non-blocking notes remain. Use
`BLOCKED` when required work, correctness, verification, feasibility, evidence,
or complexity issues must be fixed before continuing.

