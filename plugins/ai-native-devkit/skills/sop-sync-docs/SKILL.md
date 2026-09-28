---
name: sop-sync-docs
description: Classify documentation impact and synchronize Agent-facing project docs after verified code changes. Use when a task may have changed durable project knowledge.
---

# SOP Sync Docs

Read [user-direction.md](../coding-sop/references/user-direction.md) before applying this Skill.
Explicit user skips and blocker waivers take precedence over this Skill's
normal stop/approval rules; record them once and continue the adjusted work.

Read [output-language.md](../coding-sop/references/output-language.md) before generating user-facing text or documents.

Resolve `SKILL_DIR` to this loaded Skill directory, `PLUGIN_ROOT` to
`SKILL_DIR/../..`, and the workflow CLI to the absolute path
`PLUGIN_ROOT/scripts/workflow_cli.py`. Run it as `python3 "$CLI"`; never resolve
it relative to the repository or a development checkout.

The normal entry is `docs_hook.report` returned automatically by
`verification.complete`. Do not ask whether to run the cheap impact check; it already
ran in code after passing verification. This Skill owns the requested deterministic
sync or semantic preview/write that follows classification.

At entry call `python3 "$PLUGIN_ROOT/scripts/runtime_cli.py"` operation
`stage.start` with `stage: sync-docs` and the repository root. It returns the
already active run created by `verification.complete`, or starts one when this
is a recovered workflow. Retain `stage_run_id` and do not narrate the transition.

1. Read the project entry, final diff, verification evidence, and the relevant child
   directory `README.md` indexes. When `docs/README.md` exists as a safe regular
   in-repository file, read it as optional legacy or project-specific governance until
   an approved migration removes it; it is not a required default.
   Read requirement decisions only through an exact approved RequirementDocRef;
   read other task decisions only through an explicit `task_id` plus exact
   ArtifactRef. Never select task state by repository path.
2. Use the runtime report and its Git-derived changed paths. Run
   `python3 scripts/classify_changes.py CHANGED_FILES_PATH` only as a manual fallback
   when no runtime report can be recovered; record that fallback as a remaining risk.
3. Complete the runtime `DocImpactReport` with repository evidence and an exact preview.
4. For `NO_CHANGE`, write nothing. For `DETERMINISTIC`, update only paths, indexes, commands,
   or verified implementation status. For `SEMANTIC_REVIEW`, show a preview and require user
   confirmation. Before showing a semantic preview call `approval.request` with
   the retained run and `approval_kind: docs.semantic_write`; on the later user
   response call `approval.resolve` with the exact returned `approval_id` before
   writing. For `CONFLICT`, write nothing and report the conflicting evidence.
5. Never write guessed content and never create, read, move, or update root `handoff/`.
6. After the selected docs action is verified, call `stage.complete` with the
   retained run; the runtime emits `docs.sync.completed` with the same
   correlation and automatically derives the exact changed documentation paths
   from its private before/after inventory. On an unrecoverable conflict or
   partial write, call `stage.fail` with a stable `error_code` instead.
7. Continue to workflow completion after the Docs action reaches its terminal
   state. Human-facing Handoff documents are outside plugin scope; do not
   inspect, manage, or ask about them.

## Promote approved clarification decisions

An approved requirements document is a versioned workflow artifact, not
automatically canonical project knowledge. Promote only a decision that is
stable across tasks and whose user approval provenance is present.

When promotion uses a requirements workflow record, first call `stage.start`
with `stage: sync-docs`. Then call `requirements.load` with
`purpose: docs_promotion` and the exact approved RequirementDocRef. Record
its Git path, commit, and blob identity in decision provenance. Do not use
`purpose: design`, `purpose: clarify_revision`, a TaskStateStore artifact, a
path alone, or chat prose as promotion authority.

1. Use only the exact Markdown returned by that approved load.
2. Build an ADR candidate under `docs/decisions/`; do not copy the full baseline
   or chat transcript. Mark a not-yet-implemented decision as
   `state_class: RequestedState` and `implementation_status: not_implemented`.
3. Preview every target path (the ADR and its index), complete content, source
   task/ref type/digest, and SHA-256 of each current target file (or `absent`).
   Require explicit approval for this semantic write.
4. Write the proposed ADR to a temporary candidate outside the repository and
   run `python3 scripts/validate_promoted_decision.py CANDIDATE_PATH` from this
   Skill directory before any canonical write.
5. Recompute the ADR and index base hashes. On drift, invalid candidate, or
   conflicting evidence, write nothing and return `CONFLICT`. Apply the approved
   ADR and its `docs/decisions/README.md` index entry as one multi-file patch;
   verify both targets afterwards. If the edit mechanism partially fails,
   restore the captured preimages (or remove a newly created ADR) and report the
   failure rather than leaving an unindexed record. This is a guarded Current
   Skill workflow, not the Planned V1 transactional `DocsSyncEngine`.
6. Run the same validator once more against the applied ADR. Only verified
   implementation evidence may later change
   `implementation_status` to `implemented` and its statements to CurrentState.

`DocImpactReport` contains `docsImpact`, `reasons`, `proposedChanges`,
`appliedChanges`, `conflicts`, `verification`, and any `sourceArtifactRefs`.
It contains no Handoff recommendation or workflow follow-up.
