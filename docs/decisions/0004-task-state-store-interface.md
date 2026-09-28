# ADR 0004: Keep stage policy out of TaskStateStore

Status: Accepted
Date: 2026-08-24

## Context

S0 needs resumable state, immutable artifact history, transition validation,
optimistic concurrency, idempotency, redaction and interruption recovery. A
generic event platform would exceed the first vertical slice, while stage-specific
persistence methods would turn the store into a second workflow controller.

## Decision

`TaskStateStore` exposes only `load(task_id)` and `commit(TaskCommit)`. Stage
modules such as `InitEngine` decide user-facing flow and propose transition
intents. The store derives current state, validates shared invariants, and
atomically persists immutable artifacts plus any requested transition.

Filesystem and in-memory adapters implement only atomic compare-and-commit
persistence. Contract decoding, reference validation, transition rules, hashing,
redaction, idempotency, recovery and corruption detection remain shared inside
the TaskStateStore implementation.

Implementation note: 0.2 applies the same interface to both the Init and
clarification persistence slices; no clarification-specific store method was
added.

## Alternatives

1. A queryable artifact/event journal as the public S0 interface. Rejected
   because its query and projection surface is not needed by the first vertical
   slice; internal persistence may still evolve without widening the interface.
2. An `$sop-init`-specific interface such as `prepareInit` and `commitInit`. Rejected
   because future stages would either bypass it or expand the store into a shallow
   collection of stage methods.
3. Separate `save` and `transition` operations. Rejected because callers could
   expose an artifact without its lifecycle change or advance state without the
   corresponding immutable output.

## Consequences

- The store interface remains small as future artifact types are added.
- Atomicity, concurrency, compatibility and safety rules have one implementation.
- `InitEngine` needs typed commit construction but remains the only owner of
  `$sop-init` policy.
- Persistence layout can change without changing stage contracts.

## Revisit when

Measured future-stage requirements need queryable history or independent writers
that cannot be served behind the same `load` / `commit` contract.

## Clarification supersession (2026-08-27)

ADR 0006 supersedes the clarification-specific ownership note above. Clarify no
longer writes TaskStateStore artifacts; the small `load` / `commit` interface
continues to govern the remaining persisted task contracts.
