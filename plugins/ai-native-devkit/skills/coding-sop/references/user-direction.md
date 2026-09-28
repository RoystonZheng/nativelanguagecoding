# Explicit user direction

The user's current direction controls the plugin's process. This reference
takes precedence over stop, wait, approval, required-stage, and retry rules in
the Skills and their method references. Apply an already explicit direction
immediately; do not ask the user to repeat it in another turn. Ask only when
the scope is ambiguous, and continue independent work while clarifying.

This changes plugin workflow requirements. It does not create unavailable tool
permissions or authorize unrelated actions. Keep actual failures, unrun checks,
and missing inputs visible; never manufacture approval, readiness, or a pass.

## Record the decision once

Resolve `PLUGIN_ROOT` from the Skill, and use the packaged
`scripts/runtime_cli.py` with ordinary versioned JSON. Select `workflow.route`
once before Init or the first stage, reusing the current route from `trace.load`
on continuation. Do not re-select the route on every user reply: a new selection
starts a new decision scope. The Runtime associates decisions with the current
session, repository, route event, and stage attempt.

For a whole stage (including Init, Clarify, Design, Plan, Execute, Debug, Verify,
or Sync Docs), submit:

```json
{
  "schema_version": "ai-native-devkit/v1alpha1",
  "operation": "workflow.user_decision",
  "cwd": "/absolute/repository",
  "decision_id": "unique-id-reused-on-retry",
  "action": "skip_stage",
  "stage": "verify",
  "user_directive": {
    "source": "user",
    "reference": "current user message or actual host message ID",
    "summary": "User asked to omit verification for this task."
  }
}
```

Use a short paraphrase of the actual instruction, never a raw prompt, document,
secret, or invented host event. Record multiple explicitly skipped stages with
separate IDs. Reuse the exact request and ID after an uncertain tool response.

For only the current blocker, use `action: waive_blocker`, the same provenance,
the exact `stage_run_id`, a `gate` below, and a precise `blocker_code` such as
`requirements.source_drift`, `approval.plan.pending`, or `verification.failed`.
The run remains active and its remaining work continues. An input blocker
before Design/Plan/Execute/Clarify starts may omit `stage_run_id`; Runtime
returns the new run ID. Other blockers require the existing run ID.

| Gate | Scope and continuation |
|---|---|
| `input` | Ignore the named input problem for this run. Use the input explicitly selected by the user, or their current request plus inspected repository facts; describe the replacement basis in the decision summary. Do not load a changed file as an old approved reference. |
| `approval` | User waived this run's procedural document approval (Clarify, Design, Plan, Sync Docs). Complete real work without fabricating `approval.resolve`. It does not approve unrelated writes. |
| `method` | Omit only the named method step, e.g. a particular test, review, interview question, or isolation step. Perform the other work; it does not waive runtime input, approval, or verification gates. |
| `verification` | Accept continuation despite this Verify run's actual failed result. Record `verification.complete` with the actual counts first; never change failure into pass. |
| `stage_result` | Continue past this already failed stage attempt. Preserve its failed terminal and retained work; this does not claim the failed stage finished its work. |
| `docs_classification` | Ignore this Sync Docs run's missing/conflicting classification. Preserve the conflict; still observe actual docs changes and honor any remaining approval requirement. |
| `docs_capture` | Accept incomplete observation for this Sync Docs run. Preserve `fullCapture: false`; never invent a diff. |

Runtime validates which gates apply to each stage. If a stage has already
failed, use `stage_result` to continue past that attempt or skip the stage; do
not overwrite its terminal event. If resuming the actual work, start a new run
and bind any still-needed input/method exception to that new run explicitly.
A workflow already reported as failed may continue through the same explicit
decision; Runtime reactivates collection and preserves the earlier failure.
An Init exception never changes its private TaskStateStore or InitReport to
ready. Continue with the available inspected facts and the stated limitation.

## Continue the adjusted workflow

The router remains the sole owner of the remaining route. After a recorded
skip, do not invoke that Skill, request its approval, require its missing
artifact, or return to it automatically. Stage Skills return control to the
router when their stage is skipped. A blocker waiver keeps the stage's other
work and checks in place; do not expand one waiver into a whole-stage skip.

When the upstream stage was skipped or its failed result was explicitly
accepted, consume the user's stated task and
observed repository facts as the replacement input. Design omits the strict
`requirements.load` handoff in that case; Plan/Execute omit the absent
`source_subject_digest`. Do not invent a RequirementDocRef, DesignDoc, or
PlanDoc, or reuse an older digest as though the skipped stage produced it.
When the upstream document exists but its approval was explicitly waived,
use that actual document with the recorded exception as the input; do not
re-request the waived approval. For Design this also means omitting the strict
approved-reference loader, while checking the available source facts directly.
For a specifically waived source-input blocker, retain its returned run ID;
the strict RequirementDocumentLoader itself remains unchanged.

If the user skipped Verify, do not run tests or emit `verification.complete`.
If the user only skipped some checks, keep the denominator and missing checks
visible. Submit the actual non-passing result, and record `verification` only
when the same explicit instruction authorizes proceeding without those checks.
No second confirmation is needed for “skip tests and continue/commit.”

Unless Sync Docs was also skipped, after skipped Verify or accepted failed
Verify call `docs.classify` with `cwd` and the actual `baseline_revision`.
It inspects the real Git diff independently of tests and returns `docs_hook`.
Continue the appropriate Docs action. If Docs was explicitly skipped, neither
the router nor the automatic Hook may restart it.

Finally call `workflow.finish` normally. It accepts scoped user exceptions and
records `completed_with_exceptions`, while keeping failed verification,
failed attempts, and skipped stages intact. State the useful delivered result
and the omitted/failed work briefly to the user. Never call an unverified task
“all checks passed.”
