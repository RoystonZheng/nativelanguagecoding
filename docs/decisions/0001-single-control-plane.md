# ADR 0001: Single plugin-owned control plane

Status: Accepted
Date: 2026-08-23

## Context

Matt-Skills and Superpowers both contain workflow-oriented Skills. Installing both and relying on automatic triggers can cause duplicate clarification, repeated planning, conflicting state ownership and unclear completion semantics. Staged-execution evaluations also showed that centralized progress tracking and Ticket-level quality gates each provide value.

## Decision

AI Native DevKit will have one plugin-owned WorkflowRuntime, lifecycle state and
ExecutionLedger. User-facing stage Skills are adapters into this control plane,
not independent orchestration systems. Upstream workflows are sources of
evaluated mechanisms, not nested runtime dependencies.

Implementation note: 0.2 implements bounded Init and clarification runtimes over
one TaskStateStore; the complete WorkflowRuntime and ExecutionLedger remain
Planned V1.

## Alternatives

1. Install both upstream plugins and constrain them with prompts. Rejected because trigger visibility and control remain implicit and fragile.
2. Pick one upstream workflow unchanged. Rejected because no candidate wins every evaluated function and neither matches the team's docs lifecycle.
3. Let every stage own its own state. Rejected because resume, invalidation, evidence and docs sync would fragment.

## Consequences

- More initial implementation work is required.
- Routing, errors, approvals and evidence become consistent.
- Stage mechanisms can be replaced without changing the external workflow.
- The plugin must prevent hidden recursive orchestration by a stage Skill.

## Revisit when

A stable platform-native orchestration interface provides equivalent lifecycle, approval, persistence and evidence guarantees with less custom implementation.

## Plan/Execute supersession (2026-08-28)

ADR 0007 supersedes this decision only where it selects an ExecutionLedger as a
public Planned target. The one plugin-owned control plane, shared lifecycle and
evidence semantics, and prohibition on nested stage orchestrators remain
accepted. Current Execute returns `ExecutionResult`; `$coding-sop` owns Verify,
Docs Sync, and terminal `TaskOutcome`.
