---
name: phase-review
description: Manual independent review gate for research engineering plans, implementation phases, evidence, and final readiness.
---

# Phase Review

Review the smallest boundary that satisfies the user's request, using an
independent review-only subagent. The reviewer returns findings and does not
edit files, implement fixes, broaden scope, or introduce requirements.

After reporting findings, the main agent continues any implementation already
authorized by the user as a separate step. A review-only request ends with the
report; authorization for review alone does not authorize fixes.

## Workflow

1. **Pin the target.** Infer the target from the active request and retained
   scope, incorporating user corrections. State the phase goal and decision
   gated. Ask only if ambiguity could cause review of the wrong artifact.
   For implementation or final-gate reviews, use the supplied fixed point or
   relevant merge base; include staged, unstaged, and relevant untracked changes
   in working-tree reviews. Record the comparison command and commit list when
   applicable. Complete when the target, boundary, and comparison are explicit.

2. **Gather bounded context.** Supply the artifacts for the selected target:
   - Implementation: original request/spec, pinned diff, repository standards,
     verification receipts, and completion claims.
   - Plan or context proposal: proposal, goals, constraints, acceptance criteria,
     dependencies, assumptions, excluded work, and any cited evidence.
   - Evidence: claim, raw results, setup/commands, expected and observed behavior,
     controls, uncertainty, and decision supported.
   - Final gate: original scope, final diff, standards, verification, deferrals,
     generated or local-only files, and merge/release constraints.
   Complete when required artifacts are supplied or identified as unreviewed.

3. **Delegate independently.** Spawn one review-only Codex subagent with
   `fork_turns="none"`, or an equivalent clean-spawn option. Give it the target,
   boundary, relevant artifacts, and applicable criteria below. Exclude the
   parent transcript, search logs, and other agents' working output. Require
   evidence-located findings classified as blocking, non-blocking, or out of
   scope; the reviewer must not edit, run destructive commands, or broaden work.
   If independent review is unavailable under the runtime or tool policy, return
   `BLOCKED` with the tooling reason; do not substitute a main-agent review.
   Complete when findings arrive or the tooling blocker is established.

4. **Adjudicate and report.** Check enough source context to resolve suspected
   false positives. Keep spec alignment separate from repository standards.
   Use existing verification receipts where they cover the reviewed state;
   run proportionate checks only for missing evidence, changed artifacts, or an
   unresolved concern. Complete when each finding has a supported disposition
   and the report states coverage and remaining gaps.

## Review criteria

Apply only criteria relevant to the target; skip rules already enforced by
verified tooling.

- **Alignment:** required behavior and acceptance items are complete. Distinguish
  missing or incorrect behavior from unrequested scope. For code, assess the
  documented repository standards separately.
- **Correctness and feasibility:** behavior, edge cases, and integration respect
  the contract. Plans have workable sequencing, dependencies, resources, and
  testable acceptance criteria.
- **Evidence:** claims have sufficient, reproducible support with controls,
  provenance, uncertainty, and untested boundaries. Check staleness, baseline
  fairness, cherry-picking, and overclaiming where relevant.
- **Minimality:** changes serve the requested scope. Flag speculative
  abstractions, generalized machinery, compatibility shims, defensive branches,
  or fallback paths only when unsupported by a real contract or observed need.
- **Final readiness:** required work and proportionate verification are complete;
  deferrals and merge/release constraints are explicit. Identify unrelated
  changes, generated churn, local-only files, or exposed credentials.

Blocking findings prevent the bounded decision: violated requirements,
incorrect behavior, decisive evidence gaps, infeasibility, or harmful
complexity. Non-blocking findings improve the result without preventing it.
Out-of-scope observations do not become new acceptance requirements.

## Report

Start with `PASS`, `PASS_WITH_NOTES`, or `BLOCKED`, followed by the principal
finding. Include:

- Scope: target, comparison, decision gated, reviewed and unreviewed artifacts.
- Findings: severity, precise locator, evidence, impact, and required resolution.
  Distinguish spec findings from standards findings when both apply.
- Verification: evidence used, unresolved checks, and independent-review status.

Use concise prose or bullets for small reviews. Expand into separate alignment,
minimality, evidence, and readiness sections only when the review warrants it;
omit empty sections. Use file/line, proposal section, or evidence IDs as locators.

`PASS` means the boundary is satisfied with no unresolved findings;
`PASS_WITH_NOTES` permits only non-blocking findings. Use `BLOCKED` when required
work, evidence, correctness, feasibility, or independent tooling is missing.
Report the blocker without treating it as authorization to fix or bypass it.
