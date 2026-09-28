---
name: sop-clarify
description: Clarify goals, scope, constraints, success criteria, and domain decisions into one minimal committed requirements document with exact later-turn approval.
---

# SOP Clarify

Read [user-direction.md](../coding-sop/references/user-direction.md) before applying this Skill.
Explicit user skips and blocker waivers take precedence over this Skill's
normal stop/approval rules; record them once and continue the adjusted work.

Read [output-language.md](../coding-sop/references/output-language.md) before generating user-facing text or documents.

Use this Skill only for requirement understanding. `$coding-sop` owns the
workflow. Resolve `PLUGIN_ROOT` from this Skill directory as `../..`,
`RUNTIME_CLI` as `PLUGIN_ROOT/scripts/runtime_cli.py`, and `WORKFLOW_CLI` as
`PLUGIN_ROOT/scripts/workflow_cli.py`; invoke both with `python3` and bounded
JSON on standard input. Never invoke `superpowers:brainstorming` at runtime.

This behavior adapts Superpowers 6.3.0. See
[upstream-superpowers-brainstorming.md](references/upstream-superpowers-brainstorming.md)
for source and license provenance.

## Understanding the idea

- Check out the current project state first (files, docs, recent commits)
- Before asking detailed questions, assess scope: if the request describes multiple independent subsystems (e.g., "build a platform with chat, file storage, billing, and analytics"), flag this immediately. Don't spend questions refining details of a project that needs to be decomposed first.
- If the project is too large for a single requirements document, help the user decompose into sub-projects: what are the independent pieces, how do they relate, what order should they be built? Then clarify the first sub-project through this requirement-understanding flow. Each sub-project gets its own requirements → design → plan → implementation cycle.
- For appropriately-scoped projects, ask questions one at a time to refine the idea
- Prefer multiple choice questions when possible, but open-ended is fine too
- Only one question per message - if a topic needs more exploration, break it into multiple questions
- Focus on understanding: purpose, constraints, success criteria

Do not explore approaches, design solutions, architecture, interfaces, specs,
tests, implementation steps, risks, or plans here. Do not create a checkpoint,
structured baseline, transcript, task artifact, or repository file while any
requirement question remains open. An interrupted pre-document interview can
continue only in this original Codex conversation.

## Start and interview

At entry, call `stage.start` with `stage: clarify`, the absolute repository
`cwd`, and no fabricated session ID if there is no active Clarify run. Inspect
only project context needed for the request. Record sources in working memory
only when they actually support a confirmed requirement:

- repository: repository-relative path, exact Git revision, and supported fact;
- external: stable HTTPS URL, resource URI, or opaque resource ID, recorded
  version or sync time, and supported fact.

Ask one question per assistant message. Continue until purpose, scope,
constraints, success criteria, and required domain decisions have no blocking
ambiguity. The confirmed prose is natural language, not a schema.

## Write the completed requirement

Only after the interview is complete, call `requirements.write`:

```json
{
  "schema_version": "ai-native-devkit/v1alpha1",
  "operation": "requirements.write",
  "cwd": "/absolute/repository",
  "title": "已确认的需求主题",
  "clarified_requirements": "已确认的需求正文",
  "sources": []
}
```

For an in-conversation revision, add `supersedes` with the exact previously
returned `RequirementDocRef`. Never pass a path alone. The response must be
`kind: requirement_document` with exact `path`, `commit`, and
algorithm-qualified `blob_digest`.

Present the committed file and exact reference. Do not add approval metadata
to the file or create another baseline.

## Request and resolve exact approval

Call `approval.request` with `stage: clarify`, the active `stage_run_id`,
`approval_kind: clarify.requirements`, and the exact reference as `subject`.
Present that approval ID and committed file, ask for approval, and stop the current assistant turn.

The original request, silence, broad autonomy, an Agent-authored confirmation,
or a response in the request turn is not approval. Only a later user-authored response may be passed to `approval.resolve` for that exact `approval_id`:

- `approved`: resolve, then call `stage.complete` with `stage: clarify`, the
  active run ID, and the same exact reference as `subject`;
- `changes_requested`: keep Clarify active, ask only affected questions, and
  call `requirements.write` with the already-held exact reference as
  `supersedes`; do not call the approved-only Loader for this decision;
- `rejected`: resolve, keep Clarify active, do not complete it, and wait for
  explicit user direction.

Every changed requirement creates a new commit and a new approval request.
Never amend or reuse the earlier approval.

## Explicit revision and drift entry modes

For an explicitly supplied approved reference whose cited source drifted, start
Clarify and call `requirements.load` with `purpose: clarify_revision`. Ask only
questions affected by the source change, then write with that exact reference
as `supersedes` and request a new approval. Never discover a reference by path
or recency.

For `requirements_document_drift`, the old reference is not current and cannot
be loaded or superseded. Start Clarify in `document_drift` mode, inspect the
changed or missing path only as repository state, re-confirm every affected
requirement, then call initial `requirements.write` without `supersedes`. The
Writer must choose a suffixed new path. Never restore, overwrite, or treat the
changed historical path as approved input.

Return the exact pending approval or completed `RequirementDocRef` to
`$coding-sop`. Do not enter Design, Plan, Execute, Docs Sync, or Handoff here.
