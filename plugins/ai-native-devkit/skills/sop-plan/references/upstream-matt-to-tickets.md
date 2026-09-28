# Matt Pocock planning provenance

This packaged planning behavior adapts ideas from
[`mattpocock/skills`](https://github.com/mattpocock/skills) at commit
`6654f6b60cd9d5be8b54c6fafe44346dabeb3b76`.

## Source

- `skills/engineering/to-tickets/SKILL.md`
- Repository license: MIT
- Copyright: Matt Pocock

## Adopted mechanism

- tracer-bullet vertical slices rather than horizontal layer work;
- every slice delivers a complete, independently verifiable result;
- slice size is bounded so one focused agent context can complete it;
- wide mechanical migrations may use an explicit expand-contract sequence.

## DevKit adaptations

- `$sop-plan` consumes one complete approved DesignDoc and records exact design
  provenance in the PlanDoc.
- The ordinary output is one ordered Markdown PlanDoc, not tracker tickets.
- Each slice adds Design basis, Touchpoints, a public test seam, a relevant Red,
  exact focused verification, and a completion condition because the PlanDoc is
  consumed directly by `$sop-execute`.
- Blocking edges, tracker publication, ready labels, task-graph scheduling, and
  parallel execution are intentionally not adopted for the default serial flow.

The packaged Skill does not invoke or require Matt Pocock's plugin, Skills,
tracker setup, or network access at runtime. Its instructions are maintained in
this repository under the MIT attribution recorded in `THIRD_PARTY_NOTICES.md`.
