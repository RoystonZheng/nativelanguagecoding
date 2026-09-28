---
name: sop-debug
description: Run the plugin's Debug lifecycle around the packaged diagnosing-bugs method, then hand the verified result to the automatic Docs Hook.
---

# SOP Debug

Read [user-direction.md](../coding-sop/references/user-direction.md) before applying this Skill.
Explicit user skips and blocker waivers take precedence over this Skill's
normal stop/approval rules; record them once and continue the adjusted work.

Read [output-language.md](../coding-sop/references/output-language.md) before generating user-facing text or documents.

This Skill is a thin DevKit lifecycle adapter. The packaged `$diagnosing-bugs`
Skill owns the diagnosis and focused-fix method.

1. Resolve `PLUGIN_ROOT` from this Skill directory as `../..` and call
   `python3 "$PLUGIN_ROOT/scripts/runtime_cli.py"` operation `stage.start` with
   `stage: debug` and the repository root. Retain `stage_run_id`; do not narrate
   this internal transition.
2. Invoke `$diagnosing-bugs` and follow it completely. Give it the ready project
   context returned by `$sop-init`. Do not create a commit or pull request unless
   that action is already in scope; when neither is created, preserve the proven
   hypothesis in `TaskOutcome.remainingRisks` or the final diagnosis summary.
3. If no red-capable feedback loop can be established, the diagnosis remains
   unresolved, or the focused fix cannot be completed, call `stage.fail` for the
   retained run with a stable error code and return the exact blocker. Do not
   continue to Verify or Docs Sync.
4. If the proven fix requires an architecture or public-contract change, do not
   make that expanded change inside Debug. Call `stage.fail` with
   `error_code: debug.design_required` and report that an approved Design flow is
   required.
5. After `$diagnosing-bugs` completes its focused fix and cleanup, call
   `stage.complete` for the retained debug run.
6. Invoke `$sop-verify` for focused, fresh, acceptance-linked final verification.
7. Consume the automatic Docs Hook result returned by `$sop-verify`; do not run a
   second ad hoc classification. Invoke `$sop-sync-docs` only when that result
   requires it.
8. Human-facing Handoff documents are outside plugin scope; do not inspect,
   manage, or ask about them.

Return `TaskOutcome`:

```json
{
  "intent": "debug",
  "workflowTier": "fast | standard | strict",
  "route": "debug",
  "verification": [],
  "review": [],
  "docsImpact": "NO_CHANGE | DETERMINISTIC | SEMANTIC_REVIEW | CONFLICT",
  "remainingRisks": []
}
```
