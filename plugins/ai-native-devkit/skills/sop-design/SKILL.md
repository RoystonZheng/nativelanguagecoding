---
name: sop-design
description: Design a technical solution from one exact approved RequirementDocRef. Use when a change adds behavior, crosses modules, affects architecture or public contracts, or continues approved clarification in a new session.
---

# SOP Design

Read [user-direction.md](../coding-sop/references/user-direction.md) before applying this Skill.
Explicit user skips and blocker waivers take precedence over this Skill's
normal stop/approval rules; record them once and continue the adjusted work.

Read [output-language.md](../coding-sop/references/output-language.md) before generating user-facing text or documents.

Resolve `PLUGIN_ROOT` from this Skill directory as `../..`, `WORKFLOW_CLI` as
`PLUGIN_ROOT/scripts/workflow_cli.py`, and `RUNTIME_CLI` as
`PLUGIN_ROOT/scripts/runtime_cli.py`. Invoke them with `python3`, encode bounded
JSON rather than interpolating paths or user text, and parse standard output as
one response object.

## Load the only design input

Require one complete `RequirementDocRef` containing `path`, `commit`, and
algorithm-qualified `blob_digest`. Reject a path alone, chat prose, a task ID,
a legacy task-state artifact, or any attempt to reconstruct input from
conversation history.

Call `requirements.load` with `purpose: design` through the packaged workflow
CLI before `stage.start(design)`:

```json
{
  "schema_version": "ai-native-devkit/v1alpha1",
  "operation": "requirements.load",
  "cwd": "/absolute/repository",
  "purpose": "design",
  "reference": {"path": "...", "commit": "...", "blob_digest": "git-sha1:..."}
}
```

The exact reference may have completed approval in another validated Codex
Execution Trace for the same repository only because the caller explicitly
supplied it. Never select a recent path or approval.

Map Loader failures before Design starts:

| Loader code | Observed drift |
|---|---|
| `requirements.document_worktree_drift` | worktree content |
| `requirements.document_index_drift` | staged content |
| `requirements.document_committed_drift` | committed history |
| `requirements.document_missing` | missing document |
| `requirements.source_drift` | cited source |

For any drift, keep the exact input `reference` and use read-only evidence to
report the drifted path or source, Loader code and message, recorded state,
current state, and a bounded difference when it is safely available. Add concise
recommended next steps such as restoring the approved content, revising and
re-approving the requirement, or supplying another approved reference. Do not
automatically start or enter Clarify. Do not create a new runtime operation,
persisted drift artifact, or repository write. Stop and wait for explicit user
direction.

For each external source line, route its HTTPS URL, `resource://` URI, or
preserved opaque resource ID to the mechanism that supplied it. Re-read it and
compare the recorded version or sync time. Include `reason: changed` for a
different value, `reason: unavailable` for an inaccessible or unroutable
locator, or `reason: version_uncomparable` when no stable comparison exists in
the same bounded drift report. Do not call `stage.start(design)` for any drift.

Only after the exact approved Markdown and every source are current, call
`stage.start` with `stage: design`, then perform the solution-design and
`design.solution` approval flow.

## Design and approve the solution

This behavior adapts Superpowers 6.3.0. See
[upstream-superpowers-brainstorming.md](references/upstream-superpowers-brainstorming.md)
for source and license provenance. It does not invoke or require the Superpowers
plugin at runtime.

Apply the same relevant comparison dimensions to every option. Include
migration, rollout/rollback, and documentation impact only when they apply.

### Exploring approaches

- Propose 2-3 different approaches with trade-offs
- Present options conversationally with your recommendation and reasoning
- Lead with your recommended option and explain why
- YAGNI ruthlessly - remove unnecessary features from every approach and design

### Presenting the design

- Once you believe you understand what you're building, present the design
- Scale each section to its complexity: a few sentences if straightforward, up to 200-300 words if nuanced
- Ask after each section whether it looks right so far
- Cover: architecture, components, data flow, error handling, testing
- Be ready to go back and clarify if something doesn't make sense

### Design for isolation and clarity

- Break the system into smaller units that each have one clear purpose, communicate through well-defined interfaces, and can be understood and tested independently
- For each unit, you should be able to answer: what does it do, how do you use it, and what does it depend on?
- Can someone understand what a unit does without reading its internals? Can you change the internals without breaking consumers? If not, the boundaries need work.
- Smaller, well-bounded units are also easier for you to work with - you reason better about code you can hold in context at once, and your edits are more reliable when files are focused. When a file grows large, that's often a signal that it's doing too much.

### Working in existing codebases

- Explore the current structure before proposing changes. Follow existing patterns.
- Where existing code has problems that affect the work (e.g., a file that's grown too large, unclear boundaries, tangled responsibilities), include targeted improvements as part of the design - the way a good developer improves code they're working in.
- Don't propose unrelated refactoring. Stay focused on what serves the current goal.

Section check-ins are conversational feedback, not Runtime approvals. Going
back to clarify means explain what does not make sense and wait for user
direction; do not automatically start `$sop-clarify` or choose a business
interpretation.

Keep `docs/` Agent-facing and root `handoff/` human-facing. After the complete
design is stable, encode the exact complete Markdown as UTF-8 and compute
`sha256:<64 lowercase hex>`. This is the `design_document` identity; do not send
the Markdown, path, prompt, or source contents to Runtime.

Call `approval.request` with the retained `stage_run_id`, `stage: design`,
`approval_kind: design.solution`, and:

```json
{"subject":{"kind":"design_document","digest":"sha256:<64 lowercase hex>"}}
```

Present the exact bytes identified by that digest for explicit approval and stop
the current assistant turn. On the later user response, call `approval.resolve`
with the exact returned `approval_id` and
`decision: approved | rejected | changes_requested`. Only `approved` permits
`stage.complete` for the same run; pass the same `subject` again. Any edit,
including formatting, creates a new digest and requires a new approval request.
Hand planning the complete approved Markdown plus its digest and requirement
provenance.

## Optional ignored design view

Compute `RequirementDocRef.subject_digest()` and use all 64 hex characters in
`.scratch/ai-native-devkit/tasks/requirement-<64-hex>/design.md`. Write only
when that exact path is already ignored. Put the full RequirementDocRef in the
header and refuse to overwrite a file whose header names a different reference.
This view is never authority, never reconstructs resume state, is never
committed, and never changes `.gitignore`. Otherwise return the design only in
Codex.

Output: approved design, its `design_document` digest, its exact requirement
provenance, optional ignored view path, or a bounded drift report with
recommended next steps.
