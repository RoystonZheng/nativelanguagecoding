# Context and documentation lifecycle

## Purpose

Project documentation is a durable context system. It helps an agent understand the repository, but it must not become a mixture of upstream requirements, speculative designs, implementation facts and execution notes.

AI Native DevKit preserves source type and lifecycle state from intake through
documentation sync. 0.2 persists only the remaining Init and generic task-state
contracts. Current 0.4.0 hands Clarify to Design through a committed Git
requirements document and exact Execution Trace approval instead of
TaskStateStore clarification artifacts. The 0.3 runtime automatically classifies
Docs impact from verified Git evidence; the complete ContextCatalog and
transactional DocsSyncEngine remain Planned V1.

## Three-state model

```text
CurrentState
  What the code, migrations, configuration and canonical project docs currently do.

RequestedState
  What Cooper/PRD and explicitly confirmed user decisions ask the system to become.

ProposedState
  Candidate technical designs produced by the design stage.
```

Rules:

- RequestedState differing from CurrentState is normally a requirement gap, not automatically a stale PRD.
- ProposedState is never presented as implemented behavior.
- A source conflict is recorded, not resolved by silently choosing the newest or most convenient text.
- Only implementation plus verification can promote a selected proposal into CurrentState.

## Recommended project-doc structure

The `$sop-init` module adapts to repository conventions, but the default structure is:

```text
AGENTS.md / CLAUDE.md       # project entry and routing rules
docs/
  overview/                 # product, domain, architecture, stack, status
  references/               # mirrored upstream requirements and external facts
  decisions/                # accepted durable decisions
  design/                   # long-lived module and target design
  api/                      # implemented interface contracts
  runbooks/                 # verified operational procedures
  pitfalls/                 # confirmed reusable failure knowledge
  superpowers/              # Current noncanonical requirement/spec/plan workflow records
.scratch/ai-native-devkit/tasks/<task>/ # prompt-Skill drafts and evidence
handoff/                    # root human-facing derived map; isolated by default
```

The project entry routes directly to the relevant child directory indexes. The plugin does
not generate `docs/README.md` for a new repository. In a mature repository, an existing
`docs/README.md` is valid optional project-specific governance: Adapt and Refresh preserve it
until any unique durable content is migrated through preview and explicit approval.

The plugin does not force this exact taxonomy onto a mature repository. Adapt mode maps existing responsibilities, preserves valid material and proposes migrations before moving semantic content. Root `handoff/` is not part of the Agent-facing docs taxonomy and never becomes a fact source.

## Source roles

| Source | What it proves | What it does not prove |
|---|---|---|
| Code/migrations/config | Current executable or deployed intent | Product correctness or desired future behavior |
| Canonical docs | Team-maintained current/long-lived understanding | That every sentence matches the latest code without verification |
| Cooper/PRD mirror | What upstream requested at a recorded version | That the requirement is implemented |
| Accepted ADR | Why a durable choice was made | That the implementation still conforms |
| Historical spec/plan | How a past task was reasoned/planned | Current truth |
| User confirmation | Authorized decision in this task | Current implemented behavior |
| Managed knowledge pack | Versioned platform guidance | Applicability without matching task and version |

## ContextCatalog (Planned V1)

ContextCatalog is a derived index, not a second hand-maintained knowledge base.

It records:

- source URI/path/resource ID;
- source class and responsibility;
- version, revision, timestamp and content hash;
- why the source was selected for this task;
- freshness and conflict status;
- token/size estimate and selected excerpts;
- sensitivity flags.

Its `resolve` implementation starts from repository entry files and directory indexes, then loads only task-relevant material. It does not scan and inject all docs by default.

## Reading routes

### New feature

```text
project entry
→ relevant child directory index
→ relevant upstream reference
→ implementation status and domain model
→ related accepted decisions
→ related design/API
→ relevant code and migrations
→ operational docs only when rollout/integration requires them
```

### Existing behavior change

```text
project entry
→ relevant child directory index and implementation status
→ related design/API/decisions
→ code, tests and migrations
→ upstream reference describing the change
```

### Bug diagnosis

```text
project entry
→ relevant child directory index and current design/runbook/pitfall
→ failing path, tests and observability
→ requirement only when expected behavior is ambiguous
```

### Project takeover

```text
project entry
→ overview
→ implementation status
→ module docs selected by the task
```

Human-facing Handoff documents are outside plugin scope. Do not inspect,
manage, or ask about them; they are not evidence for canonical project facts.

## Task artifacts

During work, the plugin stores authoritative runtime artifacts separately.
Current design/plan prompt Skills may use the repository-local namespaced view
`.scratch/ai-native-devkit/tasks/<task_id>/` for uncommitted drafts only when
that path is already ignored by repository policy:

```text
.scratch/ai-native-devkit/tasks/<task_id>/
  design.md
  plan.md
```

The Current PlanDoc is the complete Markdown returned by `$sop-plan`, with an
optional view at the ignored `plan.md` path above. It is derived from one
approved DesignDoc and is not a Git workflow record, TaskStateStore artifact, or
canonical project document. A Plan approval may place a caller-supplied,
algorithm-qualified digest identity in Execution Trace. Trace does not store the
PlanDoc content, independently recompute it, or create a resume cursor.

### Current 0.4.0 requirement workflow records

`docs/superpowers/requirements/`, `specs/`, and `plans/` are versioned workflow records,
not canonical CurrentState. Init preserves and indexes them but does
not infer the current task or current requirements from their contents. Design
and Docs Sync read a requirement only through an explicitly supplied exact
approved `RequirementDocRef`. Durable implemented knowledge is promoted to the
normal overview, design, API, decision, runbook, and pitfall documents through
the existing semantic preview/approval boundary.

`docs/superpowers/` is the Current workflow-record location for this handoff.
It may contain Implemented, RequestedState, and Historical records, but directory
presence or recency never makes any record canonical CurrentState.

The 0.2 `$sop-init` Phase 1 runtime writes no task state, `.scratch` content,
documentation or other files into the Target Repository. Its Phase 2 Current
prompt workflow may apply approved docs changes, validates them, and then creates
a fresh read-only post-write Workflow Task before clarification. Persisted
runtime artifacts remain immutable; `contracts.md` and `workflow.md` define
retry and freshness behavior.

Do not persist:

- full hidden reasoning;
- access tokens, cookies or secrets;
- raw personal data not required by the task;
- raw repository source contents when source identifiers and hashes suffice;
- unbounded command output when a stable evidence reference and digest suffice.

## Promotion lifecycle

| Stage | Allowed durable write | Disallowed by default |
|---|---|---|
| Upstream sync | Exact/source-preserving mirror in `references/` with metadata | Design, API or implementation claims |
| Clarification | One minimal requirements workflow record after the interview is complete | Partial interview state, transcript, structured baseline, canonical overview/design/ADR/API writes |
| Design draft | Task-state alternatives, trade-offs and ADR candidates | Current-state documentation |
| Approved design (Current) | Ignored task-local `design.md`, or the task response when no ignored path exists | Historical/canonical writes or claiming implementation exists |
| Approved PlanDoc (Current) | Ignored task-local `plan.md`, or the complete task response when no ignored path exists | Tracker tickets, canonical writes, TaskStateStore persistence, or claiming cross-session recovery |
| Approved design (Planned V1) | Persisted DesignResult and approved canonical patch proposal; accepted ADR only with explicit approval | Claiming implementation exists |
| Implemented + verified | In-place updates to affected overview/design/API/runbooks/status | Dated duplicate topics or unrelated rewrites |
| Operationally verified | Deployment/runbook/status/pitfall updates supported by evidence | Guessing production behavior from tests alone |

Contract-first teams may update a target design earlier only when the document carries explicit `Proposed` status and target version. Implemented API and status remain gated by code and verification.

### Sharing across sessions and tasks

- Another session may resume private Workflow Task state only with its explicit
  `task_id`; consuming a requirement requires the exact approved
  `RequirementDocRef` with path, commit, and blob digest.
- Repository path, chat history, and file recency never select the latest or
  “most relevant” requirement.
- Current PlanDoc content has no corresponding loader or durable per-slice
  cursor. A later session cannot reconstruct or select it from repository path,
  chat recency, the optional scratch path, or its Trace digest. Cross-session
  PlanDoc loading and slice recovery remain Planned V1.
- A different task may reuse only an explicitly supplied exact reference whose
  completed approval belongs to the same repository and subject. It must not
  treat historical workflow records as ambient memory.
- A clarification decision promoted for reuse is recorded in `docs/decisions/`
  as `RequestedState` with implementation status `not_implemented` until code and
  verification justify CurrentState. Promotion requires semantic diff preview and
  explicit approval; it does not happen as a side effect of finalization.

The promoted decision carries machine-checkable frontmatter:

```yaml
status: accepted
state_class: RequestedState
implementation_status: not_implemented
source_requirement_path: docs/superpowers/requirements/YYYY-MM-DD-topic-requirements.md
source_requirement_commit: <exact full Git OID>
source_requirement_blob_digest: git-sha1:<40 hex> or git-sha256:<64 hex>
```

## Docs impact and DocsSyncEngine

The 0.3 `DocsImpactHook.after_verification` boundary is implemented. A passing
verification event triggers Git changed-path collection and produces the cheap
`docsImpact` classification. It writes nothing for `NO_CHANGE`, never proposes
Handoff work, and never opens root `handoff/`. Semantic preview/application and
a transactional `SyncReceipt` remain owned by the Current Skill and Planned V1
engine respectively.

### Planned V1 DocsSyncEngine

```text
plan(TaskOutcome) -> DocImpactReport
apply(ApprovedDocChanges) -> SyncReceipt
```

`plan` classifies changes:

- **none**: no durable knowledge changed;
- **deterministic**: indexes, links, resource IDs, generated schema references;
- **semantic**: business rules, architecture, domain, interface or operational meaning;
- **conflicted**: source disagreement, stale base or ambiguous destination.

Policy:

- deterministic changes may be auto-applied and shown in the final diff;
- semantic changes require preview and approval;
- conflicted changes are never applied automatically;
- every applied patch is based on the verified revision and current document hash;
- SyncReceipt records changed docs, evidence, approvals and remaining conflicts.

## Conflict handling

| Conflict | Required behavior |
|---|---|
| Code vs canonical docs | Code represents current executable behavior; record doc drift and verify intent before editing |
| New PRD vs code | Record requested delta; do not call either source wrong without context |
| New requirement vs accepted ADR | Pause design; retain or supersede explicitly and link decisions |
| Two upstream sources | Ask the responsible human; preserve both source versions |
| User override vs Cooper | Keep the mirror unchanged; record override, confirmer, time and rationale |
| Historical spec vs current docs | Current code/canonical docs win for current state; history remains explanatory |
| Repo/source drift after approval | Invalidate affected downstream artifacts and refresh context |
| Design or repository drift after Plan approval | Stop Execute with the affected PlanDoc section and observed mismatch; Current has no automatic suffix recovery or cursor |

## Managed knowledge packs

Reusable RDS, Apollo, KMS, MQ and framework guidance should be versioned plugin-managed packs selected by task relevance.

Requirements:

- stable pack ID, version, source and hash;
- compatibility/applicability metadata;
- local cached copy only when offline portability is needed;
- local modifications trigger a diff instead of silent overwrite;
- packs do not become project-specific truth until applied and documented in that repository.

## Handoff and historical artifacts

- Root `handoff/` is a human-facing derived map. Ordinary tasks, `$sop-init`, and
  `$sop-sync-docs` do not scan, create, move, or update it.
- The plugin has no Handoff Skill, scan, migration prompt, approval, or path
  gate. Existing documents are left untouched and managed by the user.
- Historical specs/plans remain historical. `docs/superpowers/` is the Current
  workflow-record location, but it is not canonical project truth and its
  contents are never selected by directory presence or recency.
- Temporary TODOs, progress logs and chat summaries remain task artifacts.

## Documentation quality gate

Before applying a canonical patch, check:

1. stability across future tasks;
2. traceable evidence and source type;
3. correct destination responsibility;
4. current/requested/proposed status clarity;
5. in-place update versus duplicate creation;
6. implementation and operational verification level;
7. secret, personal data and temporary-path safety;
8. index/link consistency;
9. user approval for semantic meaning;
10. diff review against the verified revision.
