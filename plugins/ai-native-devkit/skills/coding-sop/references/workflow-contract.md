# Workflow Contract

[Explicit user direction](user-direction.md) governs scoped exceptions to the
normal stage, input, approval, verification, and completion rules below.

Routing has two independent dimensions:

- `intent`: `development` for changes or `debug` for failures;
- `workflowTier`: `fast`, `standard`, or `strict` for increasing risk and
  evidence requirements.

Keep the compatible `route` projection used by existing consumers:

| Route | Projection | Stages |
|---|---|---|
| `lightweight` | development intent + fast tier, local low-risk behavior already specified | Select context, implement, verify, conclude docs impact. |
| `development` | development intent + standard/strict tier, ambiguity, new behavior, cross-module or architectural work | Clarify, design, plan, execute, verify, sync docs. |
| `debug` | debug intent at any tier | Reproduce, prove root cause, add regression coverage, fix, verify, conclude docs impact. |

Select `strict` when authority, destructive action, public/data contract,
migration, security, compliance, production, or hard-to-reverse impact requires
stronger approval and evidence. A lower tier may be upgraded as evidence
emerges; record the reason. Do not weaken a mandatory gate merely to retain a
fast route.

## Exact Clarify handoff

- normal: `stage.start(clarify) -> interview -> requirements.write -> approval.request/resolve -> stage.complete(clarify, exact subject) -> requirements.load(purpose: design) -> stage.start(design)`
- later task with explicit approved ref: `stage.start(clarify) -> stage.complete(clarify, exact subject) -> requirements.load(purpose: design) -> stage.start(design)`; import the exact completed approval, do not replay the interview or request approval again
- input drift before Design: return bounded drift details and recommendations,
  do not start Design or Clarify automatically, and wait for explicit user
  direction; invoke `$sop-clarify` only when the user chooses requirement revision

A local request, resolution, and Clarify terminal share one `stage_run_id`. An
imported terminal uses the current Clarify run ID and cites the exact
`approval_id + subject_digest` of an original completed attempt whose run ID may
differ. `$coding-sop` remains the only top-level orchestrator.

## Exact DesignDoc and PlanDoc identity chain

Current Design and Plan are complete Markdown response artifacts. The producing
Skill computes `sha256` over the exact UTF-8 bytes shown for approval. Runtime
stores only `subject_kind` and the algorithm-qualified digest:

```text
approved RequirementDocRef
  -> approved DesignDoc (`design_document` digest)
  -> approved PlanDoc (`plan_document` digest)
  -> serial Execute -> ExecutionResult
  -> Verify -> Sync Docs -> TaskOutcome
```

Plan `stage.start` supplies the completed DesignDoc digest; Execute `stage.start`
supplies the completed PlanDoc digest. Approval request, resolution, and stage
completion use the same document identity. Any changed Markdown requires a new
digest and approval. Runtime does not store or load either document and the
digest is not a durable per-slice cursor.

Only `ExecutionResult.status: completed` continues to Verify and Docs Sync.
Plan gaps and every non-completed Execute result close their started run with
`stage.fail`; the router stops before `workflow.finish`. A new approved input
starts a new stage run rather than mutating or resuming the failed run.

Skill dispatch is exact:

- establish a ready context first through `$sop-init`, unless the caller already
  supplies an explicit ready `task_id` and exact context ArtifactRef;

- `lightweight`: handle the bounded task, invoke `$sop-verify`, then
  `$sop-sync-docs` only when durable knowledge may have changed.
- `development`: invoke `$sop-clarify`, `$sop-design`, `$sop-plan`,
  `$sop-execute`, receive its `ExecutionResult`, invoke `$sop-verify`, then docs
  sync. Plan is one detailed design-derived Markdown document whose ordered
  vertical slices are executed serially; it is not a task graph.
- `debug`: invoke `$sop-debug`; it uses `$sop-verify` and syncs docs when
  required.

Every terminal `TaskOutcome` preserves these fields and may add provenance refs:

```json
{
  "intent": "development | debug",
  "workflowTier": "fast | standard | strict",
  "route": "lightweight | development | debug",
  "verification": ["fresh command and result"],
  "review": [],
  "docsImpact": "NO_CHANGE | DETERMINISTIC | SEMANTIC_REVIEW | CONFLICT",
  "remainingRisks": []
}
```

The normal workflow ends after the Docs action is terminal. Human-facing
Handoff documents are outside plugin scope; do not inspect, manage, or ask
about them.
