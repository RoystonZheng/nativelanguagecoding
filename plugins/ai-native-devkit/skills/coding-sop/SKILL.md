---
name: coding-sop
description: Route and manage software delivery work using the team Coding SOP. Use when a user asks to apply the SOP, handle an engineering task end to end, or choose the appropriate development workflow.
---

# Coding SOP Router

Read [user-direction.md](references/user-direction.md) before applying this Skill.
Explicit user skips and blocker waivers take precedence over this Skill's
normal stop/approval rules; record them once and continue the adjusted work.

Read [output-language.md](references/output-language.md) before generating user-facing text or documents.

1. Read `references/workflow-contract.md` and `references/execution-trace.md`.
2. Do not ask the user or invoke a logging command to start Trace. The first
   validated DevKit Runtime operation activates the current plugin Trace; the
   packaged Collector Hook is a no-op before that activation and then records
   Codex lifecycle events automatically.
3. Inspect the task and minimum relevant project context.
4. Classify task `intent` (`development` or `debug`), then select workflow
   `tier` (`fast`, `standard`, or `strict`). Preserve the compatible public
   `route` field (`lightweight`, `development`, or `debug`). Also classify
   `change_kind` as `feature`, `bug`, `test`, `refactor`, `temporary`, or
   `contract`; debug intent always uses `bug`.
5. Resolve `PLUGIN_ROOT` from this Skill and submit intent, tier, route,
   `change_kind`, and the
   repository root to `python3 "$PLUGIN_ROOT/scripts/runtime_cli.py"` operation
   `workflow.route`. Continue only with the validated route projection. Runtime
   event persistence is automatic and must not add a user prompt or SOP stage.
   Treat intent, tier, route, and routing evidence as internal control data. Do
   not add a route-status preamble or expose these fields unless the user asks.
6. Record any already explicit Init skip/failure exception before invoking Init.
   If the request is not already bound to a ready context by an explicit
   `task_id` and exact context ArtifactRef, invoke `$sop-init`. Never select the
   newest task by repository path; hand downstream stages only the ready context
   returned by init. If the user skipped Init or accepted its current failure,
   continue with available inspected facts without inventing ready context.
7. Apply already explicit user directions through `workflow.user_decision`,
   then invoke the remaining ordered stages required by the validated route:
   - `lightweight`: Init -> Execute -> Verify -> Sync Docs;
   - `development`: Init -> Clarify -> Design -> Plan -> Execute -> Verify -> Sync Docs;
   - `debug`: Init -> Debug -> Verify -> Sync Docs.
   Route-owned non-applicable stages are already recorded as skipped. Do not
   replace a required stage with an untyped narrative shortcut.
8. Use `$sop-verify` before claiming completion. Its runtime completion event
   automatically triggers the Docs Hook after passing verification.
9. Submit `workflow.finish` to the same runtime CLI before returning the terminal
   `TaskOutcome`. The runtime rejects completion when a required stage is absent,
   out of order, missing its approval, or has an unresolved Docs action.
   Collector failure belongs in `remainingRisks` but does not replace the
   engineering result.

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

## Exact Design and Plan handoff

`$sop-design` and `$sop-plan` present complete Markdown documents but send only
their caller-computed `sha256` identity to Runtime. Their approval requests and
terminal events bind the same digest. Plan starts from the completed DesignDoc
digest; Execute starts from the completed PlanDoc digest. The digest is an
observable handoff fact, not document storage or a resume cursor.

`$sop-execute` consumes the approved PlanDoc serially and returns an
`ExecutionResult`. It does not own Verify, Sync Docs, or terminal completion;
the router continues with `Execute -> Verify -> Sync Docs` and alone returns the
terminal `TaskOutcome`.

Continue that chain only when `ExecutionResult.status` is `completed`, unless
the user explicitly accepted the failed attempt or skipped the stage. Without
a scoped user exception, if Plan fails or `ExecutionResult.status` is not `completed`, stop the route. Do not
continue to Verify, Sync Docs, or workflow.finish. Surface the bounded blocker
and retained work. For `replan_required`, wait for a new approved
DesignDoc/PlanDoc and start new Plan/Execute runs; never revise the design inside
Execute or reuse the failed run.

## Trace boundary

Trace records observable facts only. Do not provide `task_id`, artificial test
case IDs, expected routes, expected documents, Hook expectations, hidden reasoning,
raw prompts, source contents, or tool output to the collector. Do not call the
removed `evaluation_cli.py` or reconstruct its former one-record trace.
