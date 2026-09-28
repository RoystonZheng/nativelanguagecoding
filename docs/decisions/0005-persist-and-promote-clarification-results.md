# ADR 0005: Persist clarification per task and promote reusable decisions explicitly

Status: Superseded by ADR 0006
Date: 2026-08-24

## Context

Clarification answers are both a resumable requirement baseline and a source of
potentially reusable decisions. Chat history is not a stable cross-session
contract, while writing every answer directly into an ADR or domain document
would mix task-local RequestedState with CurrentState and publish decisions that
may still change.

A repository may also have several active tasks. Choosing the “latest” state by
repository path is ambiguous and can silently feed one task's requirements into
another.

## Decision

During clarification, persist immutable `ClarificationCheckpoint` artifacts in
TaskStateStore. Before requesting approval, persist an immutable
`approval_requested` checkpoint containing the exact draft baseline without a
lifecycle transition. The Skill presents that complete baseline and ends the
assistant turn. After a later user-authored message approves the exact
reference, atomically persist caller-asserted approval evidence, the approved
`ClarificationResult`, and the `ContextReady -> Clarified` lifecycle transition.
The current host supplies no host-attested user-turn proof, so the runtime
guarantees ordering, exact references, and freshness rather than message
authorship.

The same Workflow Task can continue in another session only when the caller
supplies the explicit `task_id`. A downstream stage such as `$sop-design` must
also supply the exact ClarificationResult `ArtifactRef`, including its digest.
Repository path is never a task-state selector, and adapters must not auto-select
the most recent task for a repository.

TaskStateStore artifacts remain private to their Workflow Task. A decision may be
shared with a different task only after an explicit semantic-doc promotion:

1. propose a canonical decision patch with source/result references;
2. label it `RequestedState` and `implementation_status: not_implemented`;
3. preview the semantic diff and obtain approval;
4. publish it in the repository's canonical decision structure;
5. promote it to CurrentState only after implementation and verification.

Finalizing ClarificationResult alone never writes canonical docs.

## Alternatives

1. Keep clarification only in chat history. Rejected because a later session
   cannot load or validate a stable requirement baseline.
2. Select the newest task by repository path. Rejected because multiple tasks can
   be valid simultaneously and “newest” does not prove user intent.
3. Let tasks read one another's TaskStateStore artifacts. Rejected because it
   creates hidden coupling and bypasses approval, status, and source metadata.
4. Write an ADR or domain update after each answer. Rejected because intermediate
   answers can be revised and do not establish implemented behavior.

## Consequences

- Cross-session continuation is deterministic and does not require replaying the
  interview.
- Callers must preserve task and artifact identity when handing work to another
  session.
- Cross-task reuse is more deliberate, but canonical knowledge remains visible,
  reviewable, and correctly labeled.
- The clarification runtime must validate task ownership, digest, latest-result
  projection, exact draft-to-approval-request content, approval evidence, and
  atomic finalization.
- Current approval evidence is explicitly `caller_asserted`; `host_attested`
  remains unavailable until a trusted host verifier exists.

## Revisit when

A governed repository-native requirements system provides equivalent immutable
identity, approval, RequestedState labeling, and cross-task discovery without
implicit repository-based task selection.
