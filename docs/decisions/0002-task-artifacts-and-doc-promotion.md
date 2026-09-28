# ADR 0002: Separate task artifacts from canonical docs

Status: Accepted
Date: 2026-08-23

## Context

Clarification and design produce valuable decisions early, but those decisions describe requested or proposed future state. Writing them directly into canonical project docs can make unimplemented behavior look current and leaves half-confirmed terminology after users revise a decision.

## Decision

Authoritative task artifacts are captured immediately in TaskStateStore. Current
prompt Skills may keep uncommitted drafts under
`.scratch/ai-native-devkit/tasks/<task_id>/`. Canonical docs are updated through
the docs-sync gate after the appropriate approval and verification. CurrentState,
RequestedState and ProposedState remain explicit.

Exact upstream mirrors may enter `references/` before implementation if their source metadata is preserved. Semantic current-state docs are promoted conservatively.

ADR 0005 further specifies cross-session identity and the approval/status rules
for promoting a clarification decision for reuse by another task.

## Alternatives

1. Update domain and ADR docs after every user answer. Rejected because intermediate decisions can change and pollute long-lived context.
2. Write no artifacts until implementation is complete. Rejected because decisions, source conflicts and resume state would be lost.
3. Store full chat transcripts as memory. Rejected because they are noisy, sensitive and structurally unstable.

## Consequences

- A task-state schema and promotion engine are required.
- Resume becomes reliable without making task logs authoritative project knowledge.
- Documentation updates may occur later, but their evidence and status are clearer.
- Contract-first projects need an explicit Proposed status and target version.

## Revisit when

The repository adopts another formally governed specification system that already separates draft, accepted target and implemented state.

## Clarification supersession (2026-08-27)

ADR 0006 supersedes this decision only for Clarify: incomplete interviews are
not persisted, and completed requirements use the Git document plus exact Trace
approval boundary. The remaining TaskStateStore and canonical-doc promotion
rules stay accepted.

## Plan/Execute qualification (2026-08-28)

ADR 0007 qualifies the immediate TaskStateStore rule for the Current prompt
PlanDoc. Its content remains in the response or an already-ignored task-local
draft; Runtime may record only a caller-supplied digest identity. It is not a
durable task artifact or resume cursor. The separation from canonical docs and
the verified docs-promotion gate remain accepted.
