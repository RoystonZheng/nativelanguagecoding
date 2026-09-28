# Superpowers-Aligned Requirement Clarification Design

## Status

Implemented in 0.4.0 after the design discussion completed on 2026-08-27 and
repository-wide verification on 2026-08-28. This document is an implemented
workflow record; canonical CurrentState remains in the repository's main docs.

## Goal

Make `$sop-clarify` behave as closely as practical to the requirement-understanding
part of Superpowers `brainstorming`, while keeping AI Native DevKit independent
of the Superpowers plugin at runtime.

The new clarification stage produces a small, human-readable, Git-versioned
requirements document. It does not persist the interview, create structured
requirement state, or enter solution design.

## Upstream provenance

The clarification dialogue rules are directly derived from:

- repository: `https://github.com/obra/superpowers`;
- packaged version: `superpowers@6.3.0`;
- source: `skills/brainstorming/SKILL.md`, especially `Understanding the idea`;
- license: MIT, Copyright (c) 2025 Jesse Vincent.

The deployed `$sop-clarify` Skill should reuse the agreed upstream wording
verbatim wherever DevKit semantics do not require an adaptation. The Skill must
route readers to
`skills/sop-clarify/references/upstream-superpowers-brainstorming.md`, which,
together with packaged `THIRD_PARTY_NOTICES.md`, identifies this source. DevKit
must not depend on the Superpowers plugin being installed.

## Scope

This design changes only the clarification slice and its handoff to design:

- adopt the Superpowers requirement-understanding dialogue behavior;
- replace clarification checkpoints and `ClarificationResult` with a committed
  Markdown requirements document;
- retain human-readable source references as a DevKit enhancement;
- retain a runtime-recorded approval operation bound to the exact Git artifact;
- make the approved document the only clarification input to `$sop-design`;
- remove the former clarification persistence contracts without compatibility.

## Non-goals

- Do not copy Superpowers `Three Paths`, approach exploration, design
  presentation, spec authoring, or planning into `$sop-clarify`.
- Do not persist incomplete clarification or support repository-level resume of
  an interrupted interview.
- Do not reconstruct a structured requirement baseline inside Markdown or the
  runtime.
- Do not make workflow requirements documents canonical CurrentState project
  documentation.
- Do not migrate, delete, or rewrite old user state stored outside the repository.
- Do not add a runtime dependency on the Superpowers plugin.

## Architecture

`$coding-sop` remains the only top-level workflow owner. The clarification stage
uses four modules at explicit seams.

### Clarification dialogue

`$sop-clarify` owns the conversational interview. Its interface is the current
task request and the minimum project context selected by the workflow. Its
output is confirmed requirement prose plus the sources actually used.

The Skill must use the upstream `Understanding the idea` wording for these
behaviors:

- inspect current project state before detailed questions;
- assess whether the request needs decomposition;
- decompose oversized requests and continue with only the first sub-project;
- ask one question per message;
- prefer multiple-choice questions when useful while permitting open questions;
- focus on purpose, constraints, and success criteria.

The interview must not discuss approaches, architecture, interfaces,
implementation steps, test design, or planning. No file or task-state artifact
is written until the requirements are fully clarified.

### RequirementDocumentWriter

`RequirementDocumentWriter` is a deep module that hides path generation, safe
file creation, Git staging, commit creation, and artifact identity. Its small
interface returns:

```yaml
path: docs/superpowers/requirements/YYYY-MM-DD-<topic>-requirements.md
commit: exact Git commit object ID
blob_digest: algorithm-qualified Git blob identity for the file content
```

The module writes and commits the document before approval. It commits only the
requirements file and preserves unrelated staged, unstaged, and untracked user
changes. If the target name already exists, it selects a non-overwriting,
deterministic numeric suffix.

### Approval gate

The existing runtime approval mechanism is extended to accept the exact
requirement document reference as its subject. Approval state remains outside
the Markdown file. The document never edits itself to claim approval.

An approval request is valid only for the exact path, commit, and blob identity.
Any content change creates a new commit and reference, invalidates the prior
request, and requires a new approval. A later user-authored response resolves
the request as approved, rejected, or changes requested.

### RequirementDocumentLoader

`$sop-design` receives only an approved requirement document reference.
`RequirementDocumentLoader` verifies repository identity, approval, path,
commit, blob identity, and content before returning the exact committed Markdown
to the design stage. It never accepts chat prose, a path without Git identity,
or an unapproved document.

If the requirements file or a cited source has materially changed, design stops
and returns to clarification rather than choosing an interpretation.

## Workflow

```text
inspect project state
-> assess scope and decompose if necessary
-> ask one focused question per user turn
-> complete clarification with no blocking ambiguity
-> write and commit the requirements document
-> request approval for the exact RequirementDocRef
-> user reviews the committed file
-> resolve approval
-> load the exact approved file in $sop-design
```

If the user requests changes, Clarify updates the requirements document in a new
commit and creates a new approval request. Git history is not amended to hide an
earlier reviewed version.

An interrupted interview has no repository-level recovery. Continuation before
document creation depends on the original Codex task conversation.

## Requirements document format

The document is intentionally not a machine-readable requirement contract:

```markdown
# <Topic>

## Clarified Requirements
<Confirmed requirements in natural language>

## Sources
<Only sources actually used; omit the section when there are none>
```

The requirements section records only confirmed user requirements. Scope or
constraints appear only when they are themselves part of the confirmed
requirement. The document excludes conversation transcripts, proposed solutions,
architecture, interfaces, acceptance-test design, implementation steps, risk
handling, and blocking open questions.

Semantic completeness remains a Skill and user-review responsibility. Automated
validation is deliberately limited to safe path placement, non-empty content,
Git identity, source-reference syntax, and approval identity.

## Source references

Sources are human-readable rather than TaskStateStore identifiers:

- repository sources use a repository-relative path and Git revision;
- external sources use a stable URL or resource ID and a version or sync time;
- each entry briefly states which requirement or fact it supports;
- source contents and chat transcripts are not copied into the document.

Source references are an optional DevKit enhancement. A `Sources` section is
omitted when clarification uses no source beyond the user's confirmed request.

## Documentation semantics

`docs/superpowers/requirements/` contains versioned workflow artifacts, alongside
Superpowers-style specs and plans. These records are not canonical CurrentState
project documentation.

- `$sop-design` reads a requirement document only through its approved exact
  reference.
- `$sop-init` does not automatically treat historical requirements as current
  requirements.
- A later task reads one only when the user or an upstream workflow stage
  explicitly references it.
- Completed requirement documents remain as history and are not rewritten to
  describe the implemented system.
- Durable current knowledge continues to live in the repository's canonical
  overview, design, API, decision, runbook, and pitfall documents.

## Failure handling

- A non-Git repository, unsafe target path, file-write failure, or commit failure
  produces no approval request and cannot enter design.
- Existing requirement files are never overwritten.
- A commit is verified to contain only the intended requirements file; unrelated
  worktree and index state is preserved.
- A missing path, wrong repository, commit mismatch, blob mismatch, or stale
  approval is rejected without guessing a replacement artifact.
- A changed requirement produces a new commit and approval request.
- A rejected or changes-requested approval keeps Clarify active.
- Cited-source drift blocks Design and returns control to Clarify.
- Failures never trigger destructive Git recovery or deletion of user state.

## Breaking migration

This is an intentional clean break:

- remove `ClarificationCheckpoint`, `ClarificationResult`, and their
  clarification-specific TaskStateStore validation;
- remove checkpoint, checkpoint-load, clarification approval-request,
  finalization, and result-load CLI operations;
- replace `$sop-design`'s `task_id + clarification_ref` input with an approved
  `RequirementDocRef`;
- remove old checkpoint/result fixtures and compatibility tests;
- leave existing external state files untouched but unsupported by the new
  clarification flow;
- supersede ADR 0005 with a new accepted decision while retaining the old ADR as
  historical evidence;
- update workflow, contract, architecture, roadmap, Skill-selection, plugin,
  template, and documentation-index descriptions without presenting the target
  behavior as implemented before verification.

## Verification strategy

### Skill behavior

- lock the agreed upstream wording and provenance in contract tests;
- require context inspection before questions;
- require scope assessment and decomposition before detailed questions;
- require one question per message and preference for bounded choices;
- reject design, specification, and planning behavior in `$sop-clarify`.

### Requirement document module

- write the minimal Markdown shape with optional sources;
- reject unsafe paths and preserve existing files;
- preserve unrelated dirty and staged worktree content;
- commit only the target requirements document;
- return path, commit, and blob identities that reproduce the exact content.

### Approval and design handoff

- bind approval to the exact requirement document reference;
- invalidate approval after any document change;
- distinguish approved, rejected, and changes-requested results;
- load the exact approved Git blob in `$sop-design`;
- reject path-only, wrong-repository, stale, missing, or unapproved inputs;
- return to Clarify when cited sources drift.

### Breaking contract and packaging

- assert that old clarification operations and public contracts are removed;
- keep Init, workflow routing, Trace, and unrelated TaskStateStore behavior green;
- run the Skill quick validator for every Skill;
- run the plugin creator validator;
- run the complete repository validation suite with fresh evidence.

## Acceptance criteria

1. `$sop-clarify` uses the agreed Superpowers 6.3.0 requirement-understanding
   wording while remaining independently installable.
2. No clarification artifact is persisted before the interview is complete.
3. An initially completed clarification creates a commit whose diff contains
   exactly one minimal requirements document path and no unrelated user changes.
4. The approval operation binds the exact path, commit, and blob identity.
5. Modified requirements cannot reuse an earlier approval.
6. `$sop-design` consumes only the exact approved requirement document.
7. The requirements document contains no solution design or execution plan.
8. Source references remain human-readable, optional, and verifiable.
9. Historical requirements remain workflow records rather than canonical
   CurrentState documentation.
10. Old clarification persistence operations are unsupported without deleting
    existing external user state.
11. Relevant tests and all required validators pass with fresh evidence.
