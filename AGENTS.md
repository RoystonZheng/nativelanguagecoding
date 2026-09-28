# AI Native DevKit contributor instructions

## Start here

1. Read `README.md` and `docs/README.md`.
2. Read only the documents routed for the current task.
3. Treat `plugins/ai-native-devkit` as the deployable plugin root.
4. Preserve the distinction between Current prompt capabilities, the remaining
   0.2 Init/TaskStateStore behavior, the 0.3 automatic Execution Trace and Docs
   Hook boundary, the Current 0.4.0 Clarify/Design handoff, Historical
   clarification contracts, and Planned V1 contracts.

Current 0.4.0 implements the Superpowers-aligned Clarify/Design handoff through
an exact approved Git requirements document. The former 0.2/0.2.3
checkpoint/result clarification flow is Historical and unsupported.

## Design rules

- The plugin owns one top-level workflow; do not embed a second complete
  orchestrator inside a stage Skill.
- Keep deep-module interfaces small while hiding persistence, conflict handling,
  validation and evidence collection behind them.
- Add an adapter seam only when production and test implementations genuinely
  vary.
- Exchange the structured contracts in `docs/contracts.md`; never reconstruct a
  persisted task from unstructured chat history or repository path.
- Treat `intent` and `workflowTier` as independent dimensions and preserve the
  compatibility `route` projection.

## State and documentation rules

- Authoritative private task state belongs in TaskStateStore outside both the
  target repository and plugin installation. Resume that state only by explicit
  `task_id` and exact ArtifactRef. Clarification instead hands Design an
  explicitly supplied, exact approved `RequirementDocRef`.
- Optional `.scratch/ai-native-devkit/tasks/<task_id>/` drafts are allowed only
  when the target repository already ignores that path.
- Canonical project docs describe durable knowledge. Do not present requested or
  proposed behavior as implemented CurrentState.
- Semantic docs changes require a complete preview and approval; deterministic
  index/link repair may be automated.
- Human-facing Handoff documents are outside plugin scope. Do not inspect, manage, or ask about them.

## Plugin rules

- Keep the plugin and Marketplace identity `ai-native-devkit`.
- Do not add manifest capabilities without their packaged implementation.
- Do not install, reinstall or publish the plugin unless the user explicitly
  asks.
- Run every Skill through the Skill quick validator and run the plugin creator
  validator before handoff.

## Change discipline

- Implement one verified vertical slice at a time.
- Preserve compatible unknown contract fields while rejecting malformed core
  fields and invalid state transitions.
- Do not refactor unrelated files or overwrite pre-existing user changes.
- Completion requires fresh tests, relevant validators and a documentation
  impact conclusion.
