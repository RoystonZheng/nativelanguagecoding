# Architecture decisions

| ADR | Status | Decision |
|---|---|---|
| [`0001-single-control-plane.md`](0001-single-control-plane.md) | Accepted | One plugin-owned workflow owns lifecycle and evidence semantics |
| [`0002-task-artifacts-and-doc-promotion.md`](0002-task-artifacts-and-doc-promotion.md) | Accepted | Task state stays separate from canonical docs and is promoted through gates |
| [`0003-hybrid-skill-mechanisms.md`](0003-hybrid-skill-mechanisms.md) | Accepted | Reimplement selected mechanisms rather than nesting upstream workflows |
| [`0004-task-state-store-interface.md`](0004-task-state-store-interface.md) | Accepted | Keep stage policy outside a generic atomic `load` / `commit` store |
| [`0005-persist-and-promote-clarification-results.md`](0005-persist-and-promote-clarification-results.md) | Superseded by ADR 0006 | Persist clarification by explicit task identity and promote reusable RequestedState decisions explicitly |

- [ADR 0006](0006-git-versioned-requirements-handoff.md) — Accepted; Implemented in 0.4.0
- [ADR 0007](0007-design-derived-plandoc-and-serial-execute.md) — Accepted; Current prompt PlanDoc and serial Execute contract

Add an ADR only for a durable choice with real alternatives and material
consequences. Supersede rather than rewriting history.
