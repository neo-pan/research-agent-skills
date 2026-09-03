# Story and evidence matrix

Use the smallest matrix that exposes a missing link.

| Central claim | Challenge/gap | Method or resource | Metric/experiment | Analysis/case | Scope/uncertainty |
| --- | --- | --- | --- | --- | --- |
| [claim] | [why existing work is insufficient] | [design] | [measurement] | [failure/insight] | [boundary] |

## Paper-type prompts

- **Benchmark/data:** What capability gap does the resource measure, how is
  quality controlled, and which comparisons demonstrate coverage and difficulty?
- **Method:** Which assumption or mechanism addresses each challenge, and which
  ablation or robustness check isolates its contribution?
- **System/agent:** Which closed-loop capability is evaluated, where can the
  workflow fail, and which cases make those failures inspectable?
- **Training/data loop:** How are supervision or feedback produced, what is the
  optimization target, and what checks distinguish learning from leakage or
  formatting effects?

Delete a row that has no evidence, or record the missing experiment as an
explicit open question instead of filling it with a speculative claim.
