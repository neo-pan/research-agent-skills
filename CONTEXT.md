# Research Agent Skills

This context defines the language used by the local research engineering
skills in this repository.

## Language

**Deterministic readiness**:
Protocol, schema, managed-summary, state, and local artifact checks that can be
verified without judging research meaning.
_Avoid_: semantic readiness, review quality checks

**Semantic review output**:
Reviewer-produced judgment about evidence quality, claim scope, staleness,
memory fidelity, or next-action suitability.
_Avoid_: deterministic finding, parser rule

**Semantic gate finding**:
A gate finding produced by consuming semantic review output through an explicit
review adapter.
_Avoid_: readiness rule, parser warning

**Inconclusive close**:
A session close outcome that records why the current evidence cannot support a
positive or negative conclusion and why the missing evidence will remain open.
_Avoid_: evidence bypass, partial pass

**Review adapter**:
The boundary that turns reviewer judgment into RDL semantic review output.
RDL protocol may record multiple adapter labels, while orchestrated review uses
an independent subagent by default.
_Avoid_: deterministic checker, main-agent self-review
