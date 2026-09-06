---
name: paper-story-design
description: Design an AI or research paper's central thesis, evidence alignment, and section plan without forcing a venue-specific template.
---

# Paper story design

Use this skill when turning research into a coherent paper argument, planning
a new paper, restructuring a draft, or diagnosing why claims and experiments do
not align. It supports benchmark/data, method, system/agent, and training/data
loop papers; it does not assume one paper type.

## Core workflow

1. Read the available draft and research evidence. Establish audience, stage,
   and scope, then state the central question in one sentence. Identify the
   capability or evidence gap and distinguish observed results from plans.
2. Choose the paper type and map each major challenge to a method choice,
   metric/experiment, and analysis or case. Remove challenges that have no
   downstream evidence or add a concrete missing check.
3. Plan the argument using sections that serve this paper: related-work
   distinction, method or task definition, evaluation, results, analysis, and
   conclusion. Include ablations or cases where they answer a research question.
4. Check every major claim for evidence, scope, reproducibility, baseline
   fairness, invalid handling, and terminology consistency. Mark unsupported
   claims as gaps; keep proposed experiments distinct from supporting evidence.
5. Produce the smallest useful outline or revision proposal. Separate semantic
   writing decisions from later LaTeX layout, asset, and submission-compliance
   work.

## Core principles

- Write a research argument, not a feature list or engineering diary.
- Prefer bounded claims such as what is shown under the evaluated setting;
  avoid claiming generality beyond the evidence.
- Experiments should explain phenomena and limitations, not only rank systems.
- Preserve distinctions between task definition, method mechanism, metric
  validity, and empirical result.
- Use real citations and verify them when the user requests citation work or
  current related work.
- Treat visual style, exact paragraph counts, reference counts, table macros,
  and template rules as optional project/venue decisions.

## Optional references

- Read [references/story-evidence-matrix.md](references/story-evidence-matrix.md)
  for a compact planning table and paper-type prompts.
- Read [references/drafting-templates.md](references/drafting-templates.md) when
  drafting a Markdown outline, figure/table plan, or section skeleton.
- Read [references/section-logic-checklist.md](references/section-logic-checklist.md)
  when restructuring particular sections or experiments.

Template migration and submission audit are separate tasks covered by
`latex-template-migration` and `paper-submission-audit`. If an authorized RDL
session governs this task, record material evidence and decisions there;
otherwise include them in the outline or revision proposal.
