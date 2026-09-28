# ADR 0006: Hand Clarify to Design through a Git requirement document

Status: Accepted
Date: 2026-08-27

## Context

Clarify should reuse the requirement-understanding behavior of Superpowers
`brainstorming` without requiring that plugin at runtime. The former DevKit
flow persisted every clarification checkpoint and an approved structured
`ClarificationResult` in TaskStateStore. That made the clarification stage a
second persistence workflow and mixed requirement understanding with a schema
that later design work no longer needs.

The replacement still needs an auditable cross-turn approval, exact later-task
input, optional human-readable sources, and safe behavior in repositories with
unrelated staged, unstaged, or untracked work.

## Decision

After the interview is complete, `RequirementDocumentWriter` creates and
commits one minimal Markdown file below `docs/superpowers/requirements/`. Its
public identity is `RequirementDocRef(path, commit, blob_digest)`. The file
contains confirmed natural-language requirements and optional source lines; it
contains no transcript, design, plan, or approval claim.

The runtime records `clarify.requirements` approval against the canonical
SHA-256 digest of the complete reference. A request can resolve only in a later
trusted user turn. Design receives only an explicitly supplied exact reference,
then `RequirementDocumentLoader` verifies repository, path, commit, blob,
worktree/index freshness, source freshness, and a completed approval before
returning Markdown. A later Codex task may reuse a completed approval only for
the same repository and exact current subject. This is a narrow handoff rule,
not a global revocation or latest-approval service.

Repository sources record a relative path and commit. External sources retain
a stable HTTPS URL, resource URI, or opaque resource ID plus version or sync
time. Repository drift is verified by the Loader; Design re-reads external
sources. If either comparison detects drift, Design returns a bounded read-only
drift report with recommended next steps and waits for explicit user direction;
it does not start Clarify automatically. The existing source and document
revision entry modes remain available only after the user chooses revision.

The Writer delegates commit policy, signing, native temporary-index behavior,
and ref locking to `git commit --only`; a new file is exposed to Git with
`git add -N` first. See [`git commit`](https://git-scm.com/docs/git-commit) and
[`git add`](https://git-scm.com/docs/git-add). It snapshots unrelated
Git-visible state before and after the commit. Detected hook or repository drift
makes the outcome indeterminate and returns no reference; DevKit never uses
stash, reset, checkout, amend, or destructive rollback of hook side effects.

Git clean/EOL normalization can treat different raw bytes as equivalent. Such
repository-policy hook side effects are outside the Writer's Git-semantic
preservation claim and are not rolled back. Repositories with pre-existing
`skip-worktree` or `assume-unchanged` entries are rejected before a write
because Git intentionally hides those worktree changes from normal projections.

`ClarificationCheckpoint`, `ClarificationResult`, their CLI operations, and
their clarification-only TaskStateStore rules are removed without migration.
Existing external state files are left untouched but unsupported.

## Consequences

- Clarification writes no requirement document, checkpoint, transcript, or
  TaskStateStore artifact before the interview is complete; automatic
  Execution Trace remains active.
- Requirements history is human-readable and reviewable in Git.
- Every semantic change produces a new commit and approval subject.
- Design and Docs Sync must carry the exact reference explicitly.
- Historical requirement files are workflow records, not CurrentState docs.
- Interrupted pre-document interviews can continue only in the original Codex
  conversation.
- Writer failure can leave visible diagnostic state when safe cleanup cannot be
  proven; no reference or approval is emitted in that case.

## Alternatives considered

1. Keep TaskStateStore checkpoints and only change Skill wording. Rejected
   because it preserves the structured baseline and resume model being removed.
2. Store requirements only in chat. Rejected because Design would lack an exact,
   reviewable handoff.
3. Approve a path without commit/blob identity. Rejected because content could
   change after review.
4. Copy Superpowers as a runtime dependency. Rejected because packaged DevKit
   must remain independently installable.
5. Implement commits with `commit-tree` and manual hook emulation. Rejected
   because it bypasses or incompletely reproduces repository commit policy.

## Related docs

- `docs/superpowers/specs/2026-08-27-superpowers-aligned-requirement-clarification-design.md`
- `docs/contracts.md`
- `docs/workflow.md`
- `docs/context-and-docs.md`
