---
name: sop-execute
description: Execute one approved DesignDoc-derived PlanDoc serially through behavior-first implementation, focused checks, and an end-of-plan two-axis review.
---

# SOP Execute

Read [user-direction.md](../coding-sop/references/user-direction.md) before applying this Skill.
Explicit user skips and blocker waivers take precedence over this Skill's
normal stop/approval rules; record them once and continue the adjusted work.

Read [output-language.md](../coding-sop/references/output-language.md) before generating user-facing text or documents.

Input: the complete approved PlanDoc, its `plan_document` SHA-256 digest, and the
approved DesignDoc it cites. Do not execute a bare checklist, an unapproved
revision, or a plan reconstructed from chat history.

This workflow adapts Matt Pocock's stable implementation, TDD, and review
mechanisms. Read
[upstream-matt-stable-execution.md](references/upstream-matt-stable-execution.md)
for the pinned sources, deliberate adaptations, and license provenance. The
packaged Skill is self-contained.

## Preflight

1. Resolve `PLUGIN_ROOT` from this Skill directory as `../..` and call
   `python3 "$PLUGIN_ROOT/scripts/runtime_cli.py"` operation `stage.start` with
   `stage: execute`, the repository root, and `source_subject_digest` equal to
   the approved PlanDoc digest. Retain `stage_run_id`; do not narrate this
   internal transition. Runtime rejects a digest that is not the completed Plan
   output for this repository.
2. Read the complete PlanDoc and its cited DesignDoc. Confirm that the approval,
   Design basis, repository, and PlanDoc revision all describe the work being
   executed.
3. Pin the current Git commit as the execution baseline. Inspect existing
   worktree and index changes before editing. If there are any pre-existing
   staged, unstaged, or untracked changes, preserve them and create one clean
   isolated workspace at that baseline for the whole PlanDoc. Do not stash,
   reset, move, commit, or otherwise absorb the user's changes. If a clean
   isolated workspace cannot be created, call `stage.fail` with
   `execute.environment_blocked` and return a blocked `ExecutionResult`.
4. Run only the baseline checks needed to distinguish a pre-existing failure
   from a regression introduced by this execution. Record unavailable checks as
   unavailable, never as passing.

## Execute ordered slices

Execute one ordered vertical slice at a time. For each slice:

1. Read its Outcome, Design basis, Touchpoints, Test first, Verify, and Done when.
2. For behavior work, test through the approved public seam. Write one behavior
   test with an independently derived expectation, run it, and confirm a
   relevant Red caused by the missing target behavior rather than a typo,
   compilation accident, or neighboring failure.
3. Write only the minimal Green implementation required by that slice. Do not
   anticipate later slices, change an approved interface, or repair unrelated
   findings.
4. Mock only a true system boundary. Do not assert private implementation
   details or the behavior of a mock.
5. Run the slice's focused test and relevant typecheck, lint, or build command.
   Keep the result tied to the current working state.
6. Refactor only after Green and keep the focused checks passing. Continue when
   the slice's Done when condition is observable.

If repository facts invalidate the Design basis, the public seam is wrong, or
implementation requires a material scope or interface decision, stop with
`execute.replan_required`. Call `stage.fail` with that error code, return an
`ExecutionResult` whose status is `replan_required`, and include the affected
PlanDoc section, observed fact, and decision needed. The caller stops downstream
work; do not redesign inside Execute.

## Final candidate and review

1. After every slice is complete, run the PlanDoc's final checks against the
   integrated working state. Every applicable check must pass or match every
   applicable Expected result. Fix an implementation failure within the bounded
   loop. If the checks still fail, call `stage.fail` with
   `execute.final_checks_failed` and return a failed `ExecutionResult`; if the
   environment prevents a required check, use `execute.environment_blocked` and
   return blocked. Do not create the candidate commit until this gate passes.
2. Stage only the approved work and inspect the complete cached diff. Verify the
   staged diff contains only work authorized by the PlanDoc and no pre-existing
   user change. Then create one local candidate commit. Do not push, create a
   pull request, modify tracker state, or perform a deployment without separate
   authorization.
3. Review the complete baseline-to-candidate diff along two isolated axes, which
   may run in parallel:
   - **Spec:** compare behavior and scope with the exact approved DesignDoc and
     PlanDoc. Report missing requirements, incorrect behavior, and scope creep.
   - **Standards:** compare the same diff with repository instructions and
     documented coding standards. Report violations and maintainability risks.
4. Keep Spec and Standards findings separate; one axis cannot hide or rerank the
   other. Review inspects the change and does not substitute for tests.
5. Resolve every blocking finding. A changed candidate invalidates affected
   evidence: re-run the relevant focused test and apply the same passing final
   checks gate before amending the candidate commit and re-running the affected
   review axis. Use a bounded rework loop. If a blocking finding remains, call
   `stage.fail` with `execute.review_blocked` and return a blocked
   `ExecutionResult`; do not claim completion.

After the reviewed candidate and passing recorded checks agree, call
`stage.complete` for the retained run and return completed. On any other exit,
call `stage.fail` exactly once with the stable code defined above, or
`execute.implementation_failed` for another unrecoverable implementation
failure, and preserve the user's existing work. Every started Execute run has
exactly one terminal transition.

Return `ExecutionResult` to the calling workflow:

```yaml
status: completed | blocked | failed | replan_required
baseline: Git commit
candidate: reviewed candidate commit or null
completed_slices: []
focused_checks: []
final_checks: []
review:
  spec: pass | blocked | not_run
  standards: pass | blocked | not_run
remaining_risks: []
```

The calling workflow owns all downstream stages and the terminal task outcome.
