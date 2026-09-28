# ADR 0007: Use a design-derived PlanDoc and serial Execute

Status: Accepted
Date: 2026-08-28

## Context

ADR 0001 and ADR 0003 selected a future public TicketGraph plus centralized
ExecutionLedger after early planning and staged-execution evaluations. Those
evaluations support vertical slices, explicit test stops, one plugin-owned
workflow, and independent Spec/Standards review. They do not establish that a
dependency graph, tracker frontier, concurrent scheduler, or durable per-slice
ledger is required.

The shipped Plan and Execute stages are prompt Skills rather than structured
stage engines. Adding graph and ledger interfaces before persistence and
recovery exist would make callers and tests learn a large contract without
providing Current leverage. It would also invite a second orchestrator inside
Execute, competing with `$coding-sop` for Verify, Docs Sync, and completion.

## Decision

The Current Plan interface is one detailed Markdown PlanDoc derived from the
complete approved DesignDoc. It includes source-design provenance, inherited
constraints, acceptance coverage, ordered vertical slices, and Final
integration. Each behavior slice carries its observable outcome, Design basis,
Touchpoints, public seam, relevant Red, implementation actions, focused check,
expected result, and completion condition. Extra migration, rollback, security,
destructive-action, or manual detail appears only when the approved design makes
it applicable.

The PlanDoc remains in the task response or an optional
`.scratch/ai-native-devkit/tasks/<task_id>/plan.md` view when that exact path is
already ignored. The existing Runtime approval seam may bind an
algorithm-qualified digest supplied by the caller. Runtime verifies identity
equality across the relevant stage events; it does not write, load,
independently hash, or reconstruct PlanDoc content.

The Current Execute interface consumes the complete approved PlanDoc and its
cited DesignDoc and returns `ExecutionResult`. Execute pins one Git baseline,
preserves existing work, runs slices serially through behavior-first focused
checks, runs Final integration, creates one local candidate commit, and reviews
the fixed baseline-to-candidate diff on independent Spec and Standards axes.
Changing the candidate invalidates affected checks and review evidence.

Any pre-existing staged, unstaged, or untracked user change forces one clean
isolated workspace for the whole PlanDoc. Every applicable Final integration
check must pass or match its `Expected` result before candidate creation, and
the same gate is reapplied after candidate changes. Plan design gaps and every
non-completed Execute result close their started run with `stage.fail`. Only
`ExecutionResult.status: completed` advances the router to Verify, Docs Sync,
and `workflow.finish`.

`$coding-sop` remains the only top-level workflow. It owns downstream Verify,
Docs Sync, and terminal `TaskOutcome`. Execute does not call those stages or
maintain a second lifecycle. Handoff is a separate tool invoked only by an
explicit user request.

TicketGraph, ExecutionLedger, tracker frontier, write-scope scheduling, and
concurrent slice execution are removed from the public Current and Planned V1
design. Durable per-slice cursor/recovery and cross-session PlanDoc selection
remain Planned V1, without preselecting a writer, loader, or ExecutionEngine
interface.

This ADR supersedes only the ExecutionLedger clauses in ADR 0001, qualifies the
Current prompt-artifact rule in ADR 0002, and supersedes the Ticket/ledger
mechanism bullets in ADR 0003. Their single-control-plane, canonical-doc
promotion, provenance, TDD, review, and fresh-verification decisions remain
accepted.

## Alternatives

1. Keep TicketGraph and ExecutionLedger as the Planned target. Rejected because
   their public graph, state, retry, frontier, and concurrency surfaces add
   contracts that the Current prompt workflow cannot use or verify.
2. Return only a short checkbox list. Rejected because another execution context
   would need to reconstruct design constraints, test seams, acceptance coverage,
   and completion conditions.
3. Drive execution from an issue tracker or implement-spec frontier. Rejected
   because tracker availability and status are not authoritative workflow state,
   and the default serial PlanDoc needs no external scheduler.
4. Embed a complete execution orchestrator inside `$sop-execute`. Rejected
   because it would duplicate router-owned Verify, Docs Sync, lifecycle, and
   completion semantics.

## Consequences

- Plan and Execute expose smaller interfaces while retaining design traceability,
  behavior-first implementation, and exact candidate review.
- PlanDoc order is the default execution order; there is no graph validation or
  dependency-unlock policy to maintain.
- A digest proves only that Runtime events cite the same caller-supplied identity;
  it is not a content store or independently verified document reference.
- Current execution cannot resume automatically at a completed slice after the
  task context is lost. Any future cursor/recovery design must earn its own seam
  and preserve the one-control-plane rule.
- The calling router remains responsible for fresh final verification and docs
  impact after `ExecutionResult`.

## Revisit when

Measured cross-session recovery failures justify durable slice state, or a
second real execution adapter requires a shared interface that serial PlanDoc
execution cannot provide.
