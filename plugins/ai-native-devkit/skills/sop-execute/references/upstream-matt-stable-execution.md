# Matt Pocock stable execution provenance

This packaged execution behavior adapts ideas from
[`mattpocock/skills`](https://github.com/mattpocock/skills) at commit
`6654f6b60cd9d5be8b54c6fafe44346dabeb3b76`.

## Sources

- `skills/engineering/implement/SKILL.md`
- `skills/engineering/tdd/SKILL.md`
- `skills/engineering/tdd/tests.md`
- `skills/engineering/tdd/mocking.md`
- `skills/engineering/code-review/SKILL.md`
- Repository license: MIT
- Copyright: Matt Pocock

## Adopted mechanisms

- implement the supplied spec or plan rather than rediscovering its intent;
- test behavior at a pre-agreed public seam;
- advance through one vertical Red-to-minimal-Green slice at a time;
- derive expectations independently and mock only true system boundaries;
- run focused tests and typechecks during implementation, then final checks once
  against the integrated candidate;
- review a fixed baseline-to-candidate diff along isolated Spec and Standards
  axes and report both without allowing one to mask the other.

## DevKit adaptations

- The exact approved DesignDoc and PlanDoc are supplied directly to Spec review;
  upstream heuristic discovery through commit messages or tracker setup is not
  used.
- One local candidate commit gives review a stable Git identity. Review fixes
  invalidate affected evidence and require focused checks, final checks, and the
  affected review axis to run again.
- The default flow is serial. Per-ticket worktrees, implementer and merger agents,
  ready-frontier scheduling, automatic pull-request state changes, and the Beta
  `in-progress/implement-spec` workflow are not adopted.
- Workflow verification, documentation synchronization, and the final
  task outcome remain owned by the plugin's single top-level workflow.

The packaged Skill does not invoke or require Matt Pocock's plugin, Skills,
tracker setup, or network access at runtime. Its instructions are maintained in
this repository under the MIT attribution recorded in `THIRD_PARTY_NOTICES.md`.
