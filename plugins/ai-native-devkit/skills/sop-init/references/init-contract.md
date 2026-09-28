# SOP Init Contract

`$sop-init` first establishes resumable, read-only repository context, then initializes
Agent-facing project documentation without discarding useful project knowledge.

The plugin-owned `scripts/init_cli.py` is the authority for the first phase. It persists an
immutable `InitReport` in TaskStateStore. A `report` response carries the Workflow Task ID
at `report.task_id` and the exact artifact identity in the top-level `report_ref`, including
its digest. It never writes the target repository. The docs phase runs only after the report
is ready and remains a planning-and-application workflow: inspect, preview, obtain approval
for potentially destructive or semantic changes, apply, and validate.

Never infer a prior workflow task from repository path. A resumed task uses an explicit
`task_id`; downstream stages use exact ArtifactRefs. Task-local drafts and evidence remain
outside canonical docs. `user_request` carries the original engineering request or a stable
reference to it; use the literal `$sop-init` only when that is the user's complete request.

For an initial request only, the CLI may use `CODEX_THREAD_ID`, then `CODEX_TASK_ID`, as an
implicit candidate identity. If it is already bound to a different repository target, the
CLI creates a fresh Workflow Task and returns its new ID without rebinding or mutating the
existing task. Repository target identity covers requested path, observed root, and requested
scope. Any supplied `task_id`, `choice`, `authority_grant`, or `instruction_selection` is a strict continuation, so a
target mismatch remains `init.task_target_mismatch` and never falls back to another ID.

When the CLI returns `choice_required`, present exactly the returned
`reuse | new | cancel` choice and stop the current assistant turn. Call the CLI
again only after a later user message makes that explicit choice. The original
development request, general autonomy, and silence are not a choice and do not
authorize a retry in the same turn.

## Repository instruction differences

Init compares the rule bodies of same-directory `AGENTS.md` and `CLAUDE.md`.
Document titles, whitespace, list markers, emphasis, and corresponding
`.Codex/start-rule.md` / `.claude/start-rule.md` startup links do not by themselves
establish a rule conflict. Startup references remain host-specific reading routes;
follow the applicable file's startup instructions through the normal safe read path.
Section scopes, code blocks and other link destinations remain meaningful.

For `blocked.repository.source_conflict`, use
`report.payload.blocker.details.instruction_differences`. Each group names the
two files, hashes, and paired original line ranges with bounded, redacted excerpts.
Explain the actual disagreement in plain language: which rules contradict each
other and what following each would change. A textual difference may be
complementary or uncertain; do not claim the comparator proved a contradiction.
When an excerpt is truncated, inspect only the already-approved safe source ranges
needed to understand it. Show the relevant rules, not an undifferentiated file diff.

Offer the reported files as the task-local authority choices, or let the user
resolve the rules in their repository. A choice does not edit, merge, or synchronize
the files. It applies only within the corresponding directory scope and current
Workflow Task; it does not override higher-priority host instructions.

After a later user message chooses a file, reuse the exact task, repository and
user_request. Pass the exact blocked report_ref and only the selected source paths:

```json
"instruction_selection": {
  "report_ref": {"artifact_id":"returned-id","artifact_type":"init_report","digest":"sha256:<returned-digest>"},
  "preferred_sources": ["AGENTS.md"],
  "confirmed_at": "UTC timestamp of the user confirmation",
  "provenance": "stable reference to that user confirmation"
}
```

Copy the full returned report_ref; do not reconstruct it from this abbreviated
example. Select at most one file per reported directory. For multiple directories,
choices can be supplied together or one group at a time. Do not invent a source
preference from general permission to proceed. The CLI records the decision in
private task state and rechecks both files' hashes before applying it.

`blocked.repository.instruction_selection_stale` means the source versions changed.
Show the current differences and obtain a fresh choice bound to the new report.
If no rule differences remain, retry without a selection to obtain a ready report.
Never replay a stale selection or remove the competing file to force readiness.

## Repository read authority

Before invoking `init_cli.py` or opening project `AGENTS.md`, `CLAUDE.md`, or `docs/`, run
the Skill-owned symlink-safe `scripts/preflight_docs_scan.py` against the absolute project
root. Retain its result for the docs phase. Only returned `safePaths` may be inspected;
`unsafeAliases` and `blockedPaths` are conflicts, not permission to follow or read them.

For a latest `blocked.repository.read_authority` report only, retry the same task with the
same repository path and user request plus:

Present the exact capability and scope from the latest blocker, then stop the
current assistant turn. Only a later user message that explicitly grants that
exact authority permits the retry. The original development request is not
approval; neither are general autonomy, silence, nor an unrelated follow-up.
Do not submit the authority grant in the same turn.

```json
"authority_grant": {
  "capabilities": ["repository.read"],
  "scopes": ["repository:v1:<canonical-encoded-scope-or-.>"],
  "confirmed_at": "RFC-3339 timestamp",
  "provenance": "stable user-confirmation reference"
}
```

The exact scope comes from `report.payload.repository.requested_scope`; encode null as `.`.
Otherwise RFC 3986 percent-encode the UTF-8 repository-relative path with uppercase hex,
preserving `/` and unreserved characters (`A-Z`, `a-z`, `0-9`, `-`, `.`, `_`, `~`), and
prefix it with `repository:v1:`. All four grant fields are required, and no grant may
bypass another blocker.

## Modes

- **Bootstrap**: No usable indexed project documentation exists. Create the standard
  Chinese `docs/` structure from the bundled template and index only evidence found in
  the repository. Populate the five fixed Overview documents instead of inventing an
  alternative aggregate document. Bootstrap does not create `docs/README.md`; the
  project entry routes directly to child directory indexes.
- **Adapt**: Useful project documentation exists, but its organization is non-standard.
  Map and normalize it to the standard structure while preserving valid content and
  identifying ambiguous moves, merges, splits, or semantic additions for approval.
  Preserve an existing `docs/README.md`; move unique durable content only through a
  complete migration preview and explicit approval.
- **Refresh**: The standard documentation structure exists. Re-scan repository evidence,
  repair missing or broken indexes, and propose narrowly scoped updates without replacing
  stronger existing facts. Preserve an existing `docs/README.md` under the same migration
  preview rule; it is optional and is not required by validation.

## Evidence precedence

Use evidence in this order when facts conflict:

`runtime/code/config/tests > current indexed docs > unindexed prose`

Record unresolved disagreements in `conflicts`; do not silently choose between equally
supported claims.

## Workflow contract

**Boundary: exclude from semantic inventory; deterministic index/link
preservation only.**

Exclude every descendant of `docs/superpowers/requirements/`,
`docs/superpowers/specs/`, and `docs/superpowers/plans/` from semantic
inventory even when Phase 0 reports it in `safePaths`. Preserve those files
byte-for-byte; do not open, summarize, migrate, promote, or use them to infer
the current task. Deterministic index/link preservation is allowed. A routed
stage may consume an explicitly supplied approved reference later.

1. Before opening any project `AGENTS.md`, `CLAUDE.md`, or `docs/` content, run the
   symlink-safe preflight from this Skill directory:

   `python3 scripts/preflight_docs_scan.py PROJECT_ROOT`

   Inspect project-entry/docs content only when its path appears in `safePaths`. Never open,
   list, parse, or scan anything in `unsafeAliases` or `blockedPaths`; report those paths in
   `conflicts`. When scanning other repository paths, do not follow symlinks and always
   exclude `docs/handoff/`.
2. Inventory the repository and the preflight-approved project-entry/docs paths without
   changing anything.
3. Choose exactly one mode using the definitions above.
4. Run the managed-doc classifier from this Skill directory:

   `python3 scripts/check_managed_docs.py PROJECT_ROOT`

   Add `MISSING` copies and `OUTDATED_UNMODIFIED` upgrades to the preview; do not write
   either before step 7. `OUTDATED_UNMODIFIED` means the local hash matches a prior version
   retained in `assets/managed-docs.json`. `LOCAL_MODIFIED` means the local copy is unknown
   or aliased; preserve it. Show a diff only when `localHash` is non-null. A null hash marks
   an unsafe alias: do not inspect it, do not replace it, and report it as a conflict.
5. Produce a preview of `creates`, `moves`, `merges`, `splits`, `semantic additions`,
   `preserved` files, managed-document actions, and `conflicts`. A write preview must
   disclose that approval also authorizes a fresh post-write Workflow Task.
6. Ask for confirmation before applying the preview. If it contains any repository write,
   retain the complete preview, present the exact preview, then stop the current assistant turn.
   Do not apply it, run post-write init, or enter Clarify in the same turn. Only a later
   user message that explicitly approves the exact preview authorizes those writes. The
   original development request is not approval; neither are general autonomy, silence,
   or an unrelated follow-up. Explicitly call out every move, merge, split, semantic
   addition, or replacement of a locally modified managed document. Existing valid
   content must remain intact unless an approved change and stronger evidence justify
   modification. If the preview contains no repository write, this pause is not required.
7. Apply approved changes from `assets/AGENTS.md` and `assets/docs-template/`.
   The default structure contains the child directory indexes and does not contain
   `docs/README.md`.
   The standard result includes exactly these fixed Overview documents:

   - `docs/overview/product.md`
   - `docs/overview/domain-model.md`
   - `docs/overview/architecture.md`
   - `docs/overview/technical-stack.md`
   - `docs/overview/implementation-status.md`

   It also includes managed copies of:

   - `docs/runbooks/rds-schema-change.md`
   - `docs/runbooks/rds-data-query.md`
   - `docs/runbooks/apollo-config.md`
   - `docs/runbooks/kms-secret.md`

   Fill project-specific documents only from repository evidence. Use an explicit
   `待确认` item when evidence is insufficient; never guess. Managed platform runbooks
   contain only cross-project rules. Never add service names, namespaces, keys, database
   coordinates, credentials, owners, or other project-specific values to those copies.
   If an existing managed copy has local changes, preserve it and require confirmation
   before replacement.
8. Validate from this Skill directory with:

   `python3 scripts/validate_project_docs.py PROJECT_ROOT`

   Replace `PROJECT_ROOT` with the absolute target project path at runtime.
   The validator also completes the active Init stage by comparing the private,
   code-owned baseline captured by `init_cli.py` with the validated filesystem.
   This deterministic projection records recognized, generated, overwritten,
   preserved, removed, and conflicting paths without an Agent-authored log or a
   second docs inspection.
9. When approved docs changes were applied and validation passes, invoke the
   read-only init CLI again with the original task ID and explicit `choice: new`.
   The resulting new `task_id` and ready `report_ref` are the only context handed
   to clarification. This prevents the docs phase from making its own pre-write
   InitReport stale. If the docs phase made no repository change, keep the
   original ready context.

## DocsInitReport

Return an object with exactly these fields. Paths and descriptions in the lists should
make the result auditable.

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

The combined `InitOutcome` also returns the persisted context `task_id`, `context_ref`, and
`context_outcome`. Do not merge the docs report and runtime artifact into an ambiguous
single schema.

Human-facing Handoff documents are outside plugin scope. Do not inspect,
create, migrate, update, or ask about them. Init silently excludes them
from project context and leaves existing content untouched.
