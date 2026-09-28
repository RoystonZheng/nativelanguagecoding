---
name: sop-init
description: Establish resumable repository context, then initialize, adapt, or refresh Agent-facing project documentation. Use when starting a workflow task, retrying blocked context inspection, or normalizing project docs.
---

# SOP Init

Read [user-direction.md](../coding-sop/references/user-direction.md) before applying this Skill.
Explicit user skips and blocker waivers take precedence over this Skill's
normal stop/approval rules; record them once and continue the adjusted work.

Read [output-language.md](../coding-sop/references/output-language.md) before generating user-facing text or documents.

Read `references/init-contract.md`. Run the safety preflight and then the two
phases in order. The first phase is always read-only; the second may write
project docs only after its preview is approved.

## Phase 0: docs safety preflight

Resolve `SKILL_DIR` to this loaded Skill directory, `PLUGIN_ROOT` to
`SKILL_DIR/../..`, and select an explicit absolute target path, otherwise the
current working directory. Before invoking the init CLI or reading project
`AGENTS.md`, `CLAUDE.md`, or `docs/`, run:

```bash
python3 "$SKILL_DIR/scripts/preflight_docs_scan.py" "$PROJECT_ROOT"
```

Retain this result for Phase 2. Only inspect returned `safePaths`;
never inspect `unsafeAliases` or `blockedPaths`, and add them to
`conflicts`. The preflight is metadata-only.

## Phase 1: persisted context inspection

Resolve the CLI to the absolute path
`PLUGIN_ROOT/scripts/init_cli.py`. Never use a development checkout path,
current working directory, or fixed plugin-cache version to locate it.
Run it as `python3 "$CLI"`; do not rely on the entry file's executable bit.

1. Use the explicit target selected in Phase 0.
2. Encode one UTF-8 JSON request with a JSON encoder and pipe it to the CLI on
   standard input:

   ```json
   {
     "schema_version": "ai-native-devkit/v1alpha1",
     "operation": "init",
     "repository": {"path": "/absolute/target/path"},
     "user_request": "original user request or stable reference"
   }
   ```

3. For an initial request only, omit `task_id`. The CLI may use
   `CODEX_THREAD_ID`, then `CODEX_TASK_ID`, as an implicit candidate identity.
   If that candidate is already bound to a different explicitly selected
   repository target, the CLI creates a fresh Workflow Task and returns its new
   `report.task_id` without rebinding or mutating the existing task. Retain the
   returned `report.task_id` and exact top-level `report_ref`. Any supplied
   `task_id`, `choice`, `authority_grant`, or `instruction_selection` is a strict continuation: a target
   mismatch is `init.task_target_mismatch` and must not be retried under a new
   ID. Repository path never selects an existing task.
4. Treat response `kind` as exhaustive:
   - `report`: retain the persisted `InitReport`. Continue only when its outcome
     is `ready`; for instruction differences follow the selection flow in
     `references/init-contract.md`. For other `blocked` results, report the
     typed recovery condition and stop.
   - `choice_required`: ask only the returned `reuse | new | cancel` choice and
     stop the current assistant turn. Call the CLI again only after a later user
     message makes that explicit choice; the original development request,
     general autonomy, or silence is not a choice. Do not call the CLI again in
     the same turn.
   - `runtime_error`: report its stable code and bounded message; do not
     fabricate state or blindly retry an invariant failure.
5. A later authority grant is permitted only after the user grants the exact
   `repository.read` capability and canonical `repository:v1:<encoded-scope>`
   requested by the latest blocker.

   Present the exact capability and scope, then stop the current assistant
   turn. Only a later user message that explicitly grants that exact authority
   permits the retry. The original development request is not approval; neither
   are general autonomy or silence. Do not retry in the same turn.

   Reuse the original `task_id`, `repository`, and `user_request`; derive the
   scope from `report.payload.repository.requested_scope`. Encode null as `.`.
   Otherwise RFC 3986 percent-encode the UTF-8 repository-relative path with
   uppercase hex, preserving `/` and unreserved characters (`A-Z`, `a-z`,
   `0-9`, `-`, `.`, `_`, `~`), then prefix it with `repository:v1:`. Encode the
   retry with a JSON encoder in this complete shape:

   ```json
   {
     "schema_version": "ai-native-devkit/v1alpha1",
     "operation": "init",
     "task_id": "exact-blocked-task-id",
     "repository": {"path": "/same/absolute/target/path"},
     "user_request": "same original user request or stable reference",
     "authority_grant": {
       "capabilities": ["repository.read"],
       "scopes": ["repository:v1:."],
       "confirmed_at": "RFC-3339 timestamp",
       "provenance": "stable user-confirmation reference"
     }
   }
   ```

   Do not send an authority grant for any other blocker.

This phase must not initialize Git, mutate the repository, inspect persistence
files directly, dump raw source content, or create docs or scratch files.

## Phase 2: project docs preparation

After a ready context report:

**Boundary: exclude from semantic inventory; deterministic index/link
preservation only.**

Exclude every descendant of `docs/superpowers/requirements/`,
`docs/superpowers/specs/`, and `docs/superpowers/plans/` from semantic
inventory even when Phase 0 reports it in `safePaths`. Preserve those files
byte-for-byte; do not open, summarize, migrate, promote, or use them to infer
the current task. Deterministic index/link preservation is allowed. A routed
stage may consume an explicitly supplied approved reference later.

1. Inventory the repository and only the safe project-entry/docs paths returned
   by Phase 0. Do not follow symlinks and always exclude `docs/handoff/`.
2. Select `Bootstrap` when no usable docs exist, `Adapt` when useful
   non-standard docs exist, or `Refresh` when the standard structure exists.
   Bootstrap does not create `docs/README.md`; `AGENTS.md` or `CLAUDE.md` routes
   directly to each relevant child directory `README.md`.
3. Run `python3 scripts/check_managed_docs.py PROJECT_ROOT` from this Skill directory.
   Add missing managed runbook creation and `OUTDATED_UNMODIFIED` upgrades to the proposed
   changes. Preserve `LOCAL_MODIFIED` copies. Show a diff only when `localHash` is non-null;
   a null hash marks an unsafe alias that must not be inspected or replaced.
   Do not write managed docs before the preview.
4. Preview creates, moves, merges, splits, semantic additions, preserved files,
   and conflicts. Ask for confirmation before moves, merges, splits, or
   semantic additions. When the preview contains repository writes, state that
   approval also authorizes creation of a fresh post-write Workflow Task so the
   next stage does not inherit a stale pre-write revision.
   If the preview contains any repository write, persist or otherwise retain
   the complete preview, present the exact preview, and stop the current
   assistant turn. Do not apply the preview, run post-write init, or enter
   Clarify in the same turn. Only a later user message that explicitly approves
   the exact preview authorizes those writes. The original development request
   is not approval; neither are general autonomy, silence, or an unrelated
   follow-up. If the preview contains no repository write, this pause is not
   required.
5. Preserve valid content and prefer repository evidence over weaker prose.
   Preserve an existing `docs/README.md`. If it contains unique durable facts,
   include their destination and complete content in a migration preview. Only
   propose deleting the old file after all unique content has an approved home;
   never delete or rewrite it silently.
6. Apply approved changes and the Chinese project entry/docs structure from
   `assets/AGENTS.md` and `assets/docs-template/`. The template contains child
   indexes but no root docs README. Create and populate the five fixed
   `docs/overview/` documents; do not replace them with an aggregate file such as
   `project-overview.md`. Copy the four managed platform runbooks without adding
   project-specific resource identifiers or secrets.
7. From this Skill directory run
   `python3 scripts/validate_project_docs.py PROJECT_ROOT`.
   The validator automatically compares the code-owned pre-Init docs inventory
   with the validated result and records recognized, generated, overwritten,
   preserved, removed, and conflicting paths in Trace. Do not rescan, summarize,
   or ask the user for any Trace-only data.
8. If this phase changed `AGENTS.md` or `docs/`, do not hand the original
   pre-write report to clarification. After successful docs validation, call
   `init_cli.py` again with the original `task_id` and explicit `choice: new`;
   retain the new ready task ID and report reference. If the post-write
   inspection blocks or errors, stop before downstream work. If no repository
   file changed, retain the original ready report.
9. Return a `DocsInitReport`, then combine both phases as `InitOutcome` with
   `task_id`, `context_ref`, `context_outcome`, and `docs`.

Human-facing Handoff documents are outside plugin scope. Do not inspect,
create, migrate, update, or ask about them. Init silently excludes them
from project context and leaves existing content untouched.

`DocsInitReport` keeps the existing docs contract:

```json
{
  "mode": "Bootstrap | Adapt | Refresh",
  "scanned": [],
  "created": [],
  "modified": [],
  "preserved": [],
  "conflicts": [],
  "validation": {"valid": true, "missing": [], "brokenLinks": []}
}
```
