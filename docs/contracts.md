# Stage contracts

> Status: S0 envelopes, TaskStateStore, and InitReport are **0.2 implemented**.
> Execution Trace and the automatic Docs Hook boundary are **0.3 implemented**.
> Init identity isolation and confirmation gates are **0.2.3 implemented**. The
> exact Git requirement handoff is **Current 0.4.0**. The former clarification
> checkpoint/result contracts are Historical. Contracts from
> TaskSignals onward are **Planned V1** unless a section says otherwise.

## Contract goals

## Current 0.4.0 requirement handoff

The implemented boundary replaces the clarification checkpoint/result flow.

`RequirementDocRef` has required `path`, `commit`, and algorithm-qualified
`blob_digest` fields and preserves compatible extension identity. The artifact
CLI accepts only `requirements.write` and `requirements.load`. Write returns one
exact reference; load requires that full reference and returns exact approved
Markdown. `clarify.requirements` approval stores only `subject_kind:
requirement_document` and the canonical subject digest. Raw requirement prose,
source contents, and chat text never enter Execution Trace.

`requirements.write` 新增可选 `document_language: zh-CN | en`，默认 `zh-CN`。
Writer 使用中文固定标题与来源标签；Agent 按语言要求生成 `title`、
`clarified_requirements` 和来源 `supports`，Writer 不对传入正文做自动翻译。
Loader 同时接受中文格式和既有英文格式，已有精确引用和审批不会因默认语言改变而重写。
写入保护快照继续校验 HEAD、索引及无关已跟踪文件的暂存/工作区差异，
不再枚举、读取或比较无关未跟踪文件。目标需求文档仍接受独立的占用、内容和 Git identity 校验。

The sequence is `stage.start(clarify) -> requirements.write ->
approval.request -> later user-authored approval.resolve ->
stage.complete(clarify, exact subject) -> requirements.load(purpose: design) ->
stage.start(design)`. A later session may materialize Clarify completion only
when its caller explicitly supplies a reference whose exact completed approval
exists in a validated Trace for the same repository.

`ClarificationCheckpoint`, `ClarificationResult`, and the old
checkpoint/load/finalize operations are absent from the Current contract.
Existing external state is not migrated or deleted.

Stage contracts make the workflow resumable, testable and replaceable. They are
logical schemas. Unless stated otherwise, examples below show the payload inside
a persisted artifact.

0.2 represents contracts as typed Python values with centralized JSON
encoding, decoding and explicit validation. It does not require a JSON Schema
runtime or a second `.schema.json` authority.

### 0.2 ArtifactEnvelope and ArtifactRef

Every persisted S0 contract uses one common envelope:

```yaml
schema_version: ai-native-devkit/v1alpha1
artifact_type: stable type identifier
artifact_id: opaque UUID
task_id: stable Workflow Task identifier
created_at: timestamp
producer: module and version
repo_revision: RepositoryRevision | null when this producer did not observe one
input_refs: [ArtifactRef]
payload: type-specific object
```

Current TaskStateStore artifact type identifiers are `task_request`,
`transition`, `evidence_record`, and `init_report`. Historical 0.2 clarification
state additionally used `clarification_checkpoint` and `clarification_result`;
those identifiers are no longer registered or accepted. Future stages may add
types without adding stage-specific store methods. Compatible unknown fields are preserved
independently in the envelope and payload; a newer incompatible major version
is rejected rather than guessed or truncated.

`repo_revision` records the repository observation used by that artifact's
producer. It is null when that producer did not observe a revision, including a
pre-inspection TaskRequest or an artifact created before a repository was
established; a caller's `expected_revision` is not an observation.

An `ArtifactRef` is:

```yaml
artifact_id: opaque UUID
artifact_type: expected stable type identifier
digest: algorithm-qualified digest, for example sha256:<hex>
```

The digest covers a deterministic UTF-8 JSON encoding of the complete envelope,
including compatible unknown fields. The envelope does not contain its own
digest. Exact canonical encoding rules are frozen in contract fixtures before
S0 acceptance. References resolve only within their envelope's `task_id`;
loading verifies task ownership, expected type and digest and never exposes an
adapter path.

## TaskRequest

```yaml
intent: init | clarify | design | plan | execute | debug | verify | sync-docs | workflow
user_request: original request text or stable reference
repository:
  requested_path: absolute local path
  observed_root: absolute Git worktree top-level | null when request was created
  requested_scope: optional descendant path
  expected_revision: optional RepositoryRevision supplied by the caller
constraints:
  scope: optional paths/modules
  permissions: granted authority
  destructive_actions: allowed or denied
attachments: source references and hashes
```

Invariant: original user text is preserved separately from agent interpretation.

Invariant: `review` is an internal gate, not a top-level TaskRequest intent.

A `TaskRequest` is immutable after creation. `repository.requested_scope`
preserves the descendant path from which `$sop-init` was invoked; it is descriptive
request context. `constraints.scope` is an independent caller restriction on
which paths or modules later work may touch. `constraints.permissions` records
authority granted at creation time. A later authority grant is an append-only,
bounded `EvidenceRecord` with `kind: authority`, referenced by the resume
transition and resulting report; it never mutates TaskRequest.

### RepositoryRevision

```yaml
head_state: attached | detached | unborn
head: commit hash | null; null when head_state is unborn
branch: branch name | null; null for detached or unborn HEAD
dirty: boolean
worktree_digest: algorithm-qualified digest | null
```

The Target Repository is a non-bare Git worktree. InitReport `repository.root`
is normalized to `git rev-parse --show-toplevel`; a descendant invocation is
retained only as `requested_scope`. A selected submodule is its own Target
Repository; optional superproject path and revision are observation metadata,
and invoking `$sop-init` on the parent never initializes the submodule automatically.
Unborn, detached and dirty worktrees are eligible. A non-Git path or bare
repository yields a blocked `InitReport`; `$sop-init` does not initialize, clone,
create a checkout, stash, clean, reset or commit.

`worktree_digest` 在 unborn 或 dirty 工作区中必填。`dirty` 与摘要只覆盖 Git
已跟踪文件的暂存变更、工作区修改和删除，包括已加入索引的新文件。所有未跟踪文件
及子模块中的未跟踪变化均不参与，是否被 Git 忽略不影响这一规则。无关未跟踪文件
不再进入内容哈希预算；已跟踪内容和明确选择的上下文来源仍受原有读取限制。

## 0.2 TaskCommit

`TaskStateStore` has only `load(task_id)` and `commit(TaskCommit)` operations.
A commit contains:

```yaml
task_id: explicit Workflow Task identifier
expected_store_version: opaque version returned by load, or absent for creation
operation_id: idempotent operation identifier
artifact_drafts:
  - local_ref: commit-local symbolic reference
    artifact_type: registered type
    payload: type-specific draft whose ArtifactRef slots accept ArtifactRef | local_ref
transition_intent:
  local_ref: commit-local symbolic reference
  to: lifecycle state
  reason: gate/user/system reason
  input_refs: [ArtifactRef | local_ref]
  output_ref: ArtifactRef | local_ref | null
  actor: runtime | user | stage module
  # optional; TaskStateStore derives `from` and the envelope `created_at`
```

`load` returns `missing` or this minimum snapshot:

```yaml
task_id: explicit Workflow Task identifier
store_version: opaque compare-and-commit version
lifecycle_state: lifecycle state
resume_state: lifecycle state | null
artifacts: [trusted ArtifactEnvelope]
latest_report_ref: ArtifactRef | null
```

`CommitReceipt` returns:

```yaml
task_id: explicit Workflow Task identifier
store_version: new opaque version
materialized_refs: {local_ref: ArtifactRef}
transition_ref: ArtifactRef | null
```

Creation is a store invariant rather than a fabricated lifecycle transition. A
commit against `missing` has no expected version, must contain the task's sole
`task_request`, creates the authoritative `Intake` checkpoint, and emits no
`missing -> Intake` Transition. Later commits cannot add or replace TaskRequest.
When a task enters `Blocked`, the store retains its derived prior state as
`resume_state`; a valid resume transition returns there.

The store applies redaction, checks the expected version, validates registered
draft structure, resolves commit-local symbols, validates the materialized
contracts and acyclic reference graph, derives and validates the transition,
then constructs envelopes and commits the complete batch atomically. Repeating
the same `operation_id` with the same content returns the original result;
reusing it with different content is rejected. A concurrent version mismatch,
invalid graph or transition, incompatible schema, unsafe content or persistence
failure commits nothing. `$sop-init` policy and report construction remain in
`InitEngine`. The atomic commit manifest carries the materialized artifact
references and digests; envelopes never self-hash.

The init slice avoids a report/transition digest cycle by leaving a Transition's
`output_ref` null and having the InitReport reference the materialized Transition.
The store hashes the acyclic batch in dependency order.

## InitReport

`InitReport` is an authoritative structured projection for one S0 Workflow Task
and remains the Init readiness/freshness anchor. Current 0.4.0 Clarify does not
consume `InitReport` or `context_ref`; it uses an exact approved
`RequirementDocRef`. In the Historical pre-0.4 clarification flow, the same
task's report was referenced exactly by `context_ref`. It is not a reusable
cross-task `ContextBundle` or an ambient repository baseline. Its payload is:

```yaml
repository:
  requested_path: absolute local path
  root: Git worktree top-level | null when not established
  requested_scope: optional descendant path
  revision: RepositoryRevision | null when not established
  superproject: null | {root: absolute Git worktree top-level, revision: RepositoryRevision}
sources:
  - id: stable source identifier
    path: repository-relative path
    kind: entry_doc | repository_instruction | verification_source | repository
    hash: algorithm-qualified content digest
findings:
  entry_docs: []
  repository_instructions: []
  verification_commands: []
gaps: []
outcome: ready | blocked
blocker:
  code: stable typed reason
  message: bounded safe message
  resume_when: explicit recovery condition
  details: optional bounded instruction_differences and omitted_groups
  # null when outcome is ready
artifact_refs:
  task_request: ArtifactRef
  transition: ArtifactRef
  evidence: [ArtifactRef]
supersedes: ArtifactRef | null
instruction_selection:  # optional; absent in existing reports
  report_ref: exact reviewed blocked InitReport ArtifactRef
  preferred_sources: [repository-relative AGENTS.md or CLAUDE.md paths]
  confirmed_at: UTC timestamp of the later user confirmation
  provenance: bounded reference to that user confirmation
  source_hashes: {repository-relative instruction path: sha256 digest}
```

The store derives an envelope's `input_refs` from every named payload reference
and validates that derivation while decoding, so duplicate reference lists
cannot drift. The envelope's `artifact_id` is the report identity; the payload
does not repeat it as `report_id`. Supporting blocker evidence is named once by
`artifact_refs.evidence`. `artifact_refs.transition` points to the transition
that established the report's lifecycle state; a repeated blocked report may
reuse the existing `Intake -> Blocked` transition and add no self-transition.
The report contains no full raw source contents, unbounded command output,
`RouteDecision`, `ContextBundle`, documentation patch plan or rendered Markdown.
Its repository revision is derived from and must equal the envelope's
`repo_revision`.

`ready` means inspection produced a trustworthy result, not that every desirable
source exists. Confirmed absence is a gap. Inability to establish a
safety-relevant fact, an unresolved authoritative-source conflict that can
change safe behavior, or required new read authority is a typed blocker. An
initial ready report and `Intake -> ContextReady` transition commit atomically.
An initial blocked report commits `Intake -> Blocked`; a repeated blocked report
preserves trustworthy findings and a recovery condition without adding a
`Blocked -> Blocked` transition. Schema rejection, corrupt state and persistence
failure are runtime errors, not a third report outcome.

Same-directory `AGENTS.md` / `CLAUDE.md` comparison ignores a non-directive
opening H1 title, prose whitespace and soft wrapping, equivalent list markers and
emphasis, and corresponding `.Codex/start-rule.md` / `.claude/start-rule.md` links
on startup-rule lines. Section scopes, list nesting, code, and other link targets
remain significant. Startup references remain host-specific reading routes; their
normalization does not certify that the linked files have identical rules.

Residual differences retain `blocked.repository.source_conflict` for compatibility;
they require review and are not proof of semantic contradiction. Optional
`blocker.details.instruction_differences` contains at most 32 directory groups,
with `directory`, `left` / `right` source paths and exact hashes, and up to eight
paired `changes`. Each side is null for an insertion/deletion, or an original
`line_start`, `line_end`, redacted `excerpt` of at most 300 characters, and
`truncated` flag. `comparison_limited`, `more_differences`, and `omitted_groups`
make incomplete comparisons explicit. Full source files are never persisted.

A later user choice sends `instruction_selection` with the explicit `task_id`,
exact latest blocked `report_ref`, one `preferred_sources` path per selected
directory, `confirmed_at`, and `provenance`. The CLI derives `source_hashes` from
that report; callers cannot supply them. The selection and manual evidence are
persisted before reinspection, allowing recovery after interruption. Choices
may resolve directory groups incrementally and apply only within this task and
scope; they never edit either file or override higher-priority host instructions.
The report's findings select the authoritative file while sources retain both
files for freshness. Its selection reference participates in derived `input_refs`.
Both file versions must still match before a choice applies; drift returns
`blocked.repository.instruction_selection_stale` with current differences and
clears the choice. A stale report identity or unrelated source cannot authorize
continuation. Existing reports without these optional fields remain valid.

Reports are immutable. A blocked retry produces fresh evidence and a new report
whose `supersedes` references the prior report. Stale is a runtime freshness
projection over an unchanged ready report: the report remains inspectable but
cannot establish readiness for a changed repository.

## S0 CLI response envelope

The `$sop-init` Skill receives exactly one versioned JSON response:

```yaml
schema_version: ai-native-devkit/v1alpha1
kind: report
report: persisted InitReport ArtifactEnvelope
report_ref: ArtifactRef
```

`report_ref` must identify and hash the exact embedded `report` envelope.

```yaml
schema_version: ai-native-devkit/v1alpha1
kind: choice_required
reason: stable typed reason
choices: bounded allowed choice identifiers
```

```yaml
schema_version: ai-native-devkit/v1alpha1
kind: runtime_error
code: stable error code
message: bounded safe message
retryable: boolean
```

A `report` covers both `ready` and `blocked`; report and `choice_required` use
process exit status zero. An encodable `runtime_error` uses a nonzero status.
The CLI accepts only its versioned request envelope. Malformed input,
incompatible request schema and invalid follow-up choices become `runtime_error`
when Python can still encode safely. Standard output is reserved for the
response. Standard error may contain only bounded, safe, non-authoritative
diagnostics and is never parsed as a contract. Runtime-error evidence is
persisted only when doing so is safe and cannot misrepresent a failed commit.

The Skill renders concise Markdown from the JSON; tests treat the structured
report as authoritative and assert only essential visible information rather
than incidental wording. Re-invoking a task whose latest report is `ready` first
checks freshness. A matching revision requires a choice between reuse and a new
task; a stale revision permits only a new task or cancellation. An explicitly
identified Blocked task rechecks its blocker, resumes through its prior `Intake`
state when satisfied, and produces a new report attempt. Every follow-up
revalidates state and repository revision before applying a choice. If no task
identity is retained or explicitly supplied, `$sop-init` creates a distinct Workflow
Task.

For an initial request with no `task_id`, `choice`, `authority_grant`, or
`instruction_selection`, the CLI may use `CODEX_THREAD_ID`, then `CODEX_TASK_ID`, as a candidate task identity. If
that implicit identity is already bound to a different repository target, the
adapter creates a fresh Workflow Task and leaves the existing task unchanged.
Repository target identity includes requested path, observed root, and requested
scope. Explicit IDs and all follow-ups remain strict: a target mismatch is
`init.task_target_mismatch` and never falls back to another ID.

## Historical clarification CLI boundary (0.2 core; 0.2.3 approval gate)

The following boundary documents the superseded implementation. It is not a
Current interface; `workflow_cli.py` now accepts only `requirements.write` and
`requirements.load`.

The stage CLI accepted only the operations below under the same schema version:

```yaml
operation: clarification.checkpoint | clarification.checkpoint.load | clarification.approval.request | clarification.finalize | clarification.load
task_id: required explicit Workflow Task identifier
operation_id: required for checkpoint, approval-request, and finalize mutations
expected_store_version: optional optimistic-concurrency token
content: required for clarification.checkpoint
checkpoint_ref: required for clarification.approval.request and clarification.finalize
approval: required for clarification.finalize
clarification_ref: required for clarification.load
```

Requests containing `repository` or `path` were rejected because a filesystem
location could not identify workflow state. Checkpoint, approval-request, and result
responses included the explicit `task_id`, store version, exact reference, and the
referenced bounded ready InitReport envelope as `context`, so a new session
could select and freshness-check sources without opening persistence internals. An
approval-request response also carried `kind: clarification_approval_required`,
the complete canonical `baseline`, and an `approval_request_ref` equal to its
`checkpoint_ref`. Contract, state, ownership, digest, approval, or freshness
failures were bounded `runtime_error` responses and never exposed a partial commit.

## Execution Trace (0.3 implemented)

Execution Trace is an append-only local fact stream, not a Workflow Task artifact,
an artificial evaluation case, or production telemetry. The Collector Hook receives
Codex lifecycle input automatically but persists nothing until a DevKit program
emits a validated `workflow.started` event for the Session. Sessions that never
use the plugin therefore have no Trace. DevKit programs emit their own runtime
facts at validated decision points. The Agent never creates or edits a Trace record.

The identity model is fixed:

```text
session_id 1 : 1 trace_id
trace_id   1 : N turn_id
turn_id    1 : N event_id
```

Each `events.jsonl` line is one complete event:

```yaml
schema_version: ai-native-devkit/execution-event/v1
trace_id: UUID
seq: trace-local monotonically increasing integer
event_id: collector-generated identifier
timestamp: canonical UTC timestamp
event_type: registered Host or DevKit Runtime event type
stage: SOP stage or null when unavailable
actor: user | agent | runtime | system
source: codex_hook | devkit_runtime | codex_transcript_fallback
correlation:
  turn_id: string | null
  tool_call_id: string | null
  stage_run_id: string | null
  subagent_id: string | null
  parent_event_id: string | null
payload: event-specific bounded and redacted facts
```

`metadata.json` stores Trace/Session identity, plugin/collector/host versions,
repository digest, start/end time and `active | complete | partial | failed`
capture status. `summary.json` is a deterministic projection of the immutable
event stream. It is not Agent-authored and may be rebuilt.

Every required SOP stage run is correlated by a code-generated `stage_run_id` and has a
`workflow.stage.started` event followed by one terminal
`completed | skipped | failed` event. `summary.json.actual_stages` keeps one
entry per run with `stage`, `stage_run_id`, `status`, `started_at`, `ended_at`,
and `duration_ms`; retries do not overwrite earlier runs. Clarify, Design, and
Plan confirmations are paired `approval.requested` / `approval.resolved` events
with an exact `approval_id`, approval kind, decision, timestamp, and the same
stage correlation. Clarify binds the exact Git `RequirementDocRef`. Design and
Plan may additionally bind an algorithm-qualified, caller-supplied document
digest. The runtime validates that the same digest identity flows through
approval and the next stage, but it does not write, load, or independently hash
the DesignDoc or PlanDoc content. Approval content and raw user messages are not
persisted.
Route-owned non-applicable stages may be recorded directly as skipped and do
not satisfy a required stage.

`workflow.finish(status=completed)` is a code-owned completion gate. It checks
the selected route's required stages in order, stage-bound Clarify/Design/Plan
approvals, a passing Verify run, and the matching Docs classification/action.
Missing or cross-repository facts are rejected and no `workflow.completed`
event is written.

`workflow.user_decision` is the explicit exception boundary for these normal
completion requirements. Its request contains `decision_id`, `stage`, `action`
(`skip_stage | waive_blocker`), and `user_directive` with `source: user`, an
actual message reference, and a bounded paraphrase. A blocker waiver adds a
stage-valid `gate`, precise `blocker_code`, and exact `stage_run_id`; an input
waiver before a stage starts may allocate its run. A skip may close an active
run or create a skipped run without changing an earlier failed terminal.

The Runtime emits an immutable `workflow.user_decision` event, binding the
repository digest, current `route_event_id`, and stage correlation. Exact
request retries reuse `decision_id`; different content or scope is rejected.
Skip terminals carry `decision_id`. Summary `user_decisions` exposes bounded,
redacted facts, never raw user prompts. This agent-supplied provenance records
an explicit instruction; it is not host-authenticated document approval.

Valid waiver gates are `input`, `approval`, `method`, `verification`,
`stage_result`, `docs_classification`, and `docs_capture`, restricted by stage.
They do not relax core JSON validation, cross-repository isolation, or external
tool permissions. Approval waivers do not emit `approval.resolved`. Source
exceptions do not forge a `RequirementDocRef`, document digest, or ready Init
state. Actual failed terminals and verification counts remain unchanged.

A completed workflow with scoped exceptions projects
`summary.task_result: completed_with_exceptions`. Ordinary fully verified
completion keeps `passed`. Only current stage attempts satisfy completion;
older completions or waivers cannot hide an unfinished new attempt.
`docs.classify(cwd, baseline_revision)` inspects Git evidence independently
when Verify was explicitly skipped or its failure accepted; it never creates
`verification.completed` or changes a failed result to pass.

The three sources are explicit. `codex_hook` is the normal Host lifecycle path.
`devkit_runtime` records validated route, stage, Init, approval, Docs and
Verify state changes. The Init CLI starts one Init run, records Phase 1 context
inspection and captures a private docs baseline. The existing docs validator
finishes the same run by deterministically recording recognized, generated,
overwritten, preserved, removed, and conflicting paths. Neither boundary
requires an Agent-authored logging call or exposes the internal Workflow Task ID
in Trace payloads. When available,
runtime facts inherit the active Host `turn_id` and an unambiguous enclosing
`tool_call_id`. `codex_transcript_fallback` is allowed only for deterministic
recovery of a missing structured event and marks capture partial. There is no
`observation_mode`, `task_id`, `case_id`, expected route, expected docs, expected
Hook result, hidden reasoning, prompt body, command input, raw output or source
content in this contract.

`PostToolUse` is the normal terminal tool event for both zero and non-zero
results. At SessionEnd, a requested call with no observable terminal callback is
closed as `tool.abandoned`; the summary therefore separates completed, errored,
blocked and abandoned calls instead of silently leaving them unmatched.
Transcript recovery is bounded to the plugin workflow's start/end timestamps;
after completion, only the matching final turn/tool terminal and SessionEnd are
accepted, so later ordinary turns in the same Session are not added to Trace.

## Automatic Docs Hook result (0.3 implemented boundary)

`verification.complete` emits the observed verification result. A pass invokes
the Docs Hook immediately; a failure records verification only. The Hook derives
changed paths from the exact Git baseline and current worktree, then returns:

```yaml
triggered: boolean
reason: verification_completed | verification_not_passed | evidence_conflict
report:
  docsImpact: NO_CHANGE | DETERMINISTIC | SEMANTIC_REVIEW | CONFLICT
  reasons: [bounded fact]
  changedPaths: [repository-relative path]
  proposedChanges: [preview descriptor]
  appliedChanges: [path]
  conflicts: [code]
  verification: {status, baselineRevision, candidateRevision}
  sourceArtifactRefs: []
  requiresUserConfirmation: boolean
```

The Hook always performs the cheap classification after passing `/execute` or
`/debug` verification. `NO_CHANGE` produces no write and no question. Semantic
docs require a complete preview and user approval. The Hook never derives a
Handoff recommendation and never scans or modifies `handoff/` itself. The
validated route event carries `change_kind: feature | bug | test | refactor |
temporary | contract`, so internal refactors and tests remain silent even when
their paths overlap normal source directories.

Docs Sync completion compares a private before/after hash inventory and emits
only exact bounded created, modified and removed Agent-doc paths and counts.

Human-facing Handoff is outside current plugin scope. Its Skill, stage,
`stage.skip` operation, content observer, approvals, and path-based Hook gate
are retired. Init does not report detection or suggest migration. Historical
`handoff.*` events and `summary.handoff_actual_result` remain readable;
new runtime calls cannot produce those events or resolve retired approvals.
Existing user documents and private trace files are not migrated or deleted.

## TaskSignals and RouteDecision

Persisted `RouteDecision` remains a Planned V1 logical contract. 0.2 does not
encode, produce, persist or reference it. The Current prompt router already
uses the same two dimensions and emits a compatibility route projection; V1
adds automatic risk scoring and persistence rather than a second vocabulary.

```yaml
signals:
  write_scope: none | local | multi-module | cross-system
  reversibility: easy | costly | irreversible
  ambiguity: none | bounded | blocking
  contract_change: boolean
  data_migration: boolean
  auth_or_security: boolean
  production_or_external_side_effect: boolean
  known_verification_seam: boolean

intent: development | debug
workflow_tier: fast | standard | strict
route: lightweight | development | debug
required_stages: [context, clarify, design, plan, execute, verify, docs]
mandatory_upgrade_reasons: []
user_override: null | recorded override
```

Invariant: mandatory security, migration and destructive signals cannot be silently downgraded.

## ContextBundle

```yaml
request_id: context resolution ID
sources:
  - id: stable path or resource ID
    kind: code | migration | canonical_doc | upstream | adr | runbook | knowledge_pack
    version: revision, timestamp or external version
    hash: content digest
    purpose: why selected
    freshness: current | stale | unknown
current_state: sourced findings
requested_state: sourced requirements
conflicts: structured source conflicts
missing_context: items that could change the route or answer
```

Invariant: every nontrivial fact carries a source reference; ContextCatalog does not copy itself into the source list.

## Historical ClarificationCheckpoint and ClarificationResult (0.2/0.2.3)

This section preserves the former contract for provenance only. Current 0.4.0
does not register, load, migrate, or delete these artifact types.

`ClarificationCheckpoint` was an immutable task-local draft or approval request.
Its envelope carried the `task_id`; its payload was:

```yaml
status: draft | approval_requested
context_ref: ArtifactRef to the ready InitReport
operation_id: idempotent caller operation identifier
supersedes: ArtifactRef to the prior ClarificationCheckpoint | null
goal: concise outcome
in_scope: []
out_of_scope: []
acceptance_criteria: []
constraints: []
facts: []
decisions: []
domain_delta: {terms: [], entities: [], rules: []}
open_questions: []
expected_doc_impacts: []
```

Saving a newer checkpoint did not mutate or delete its predecessor and did not
advance lifecycle state. `supersedes` had to form the task's immutable
checkpoint chain.

`clarification.approval.request` accepted only the latest exact `draft` with no
blocking questions. It persisted a new `approval_requested` checkpoint whose
requirement content exactly matched, and whose `supersedes` referenced, that
draft. The commit advanced the store version but created no approval evidence,
result, or lifecycle transition; the task remained `ContextReady`.

Finalization copied the requirement content from the exact latest checkpoint and
added runtime-owned references. Compatible stage-owned extension fields were
copied unchanged; only `status`, context/checkpoint/approval/supersedes refs and
`operation_id` were runtime-owned:

```yaml
status: approved
context_ref: ArtifactRef to the ready InitReport
operation_id: idempotent caller operation identifier
checkpoint_ref: ArtifactRef to the exact approved checkpoint
approval_ref: ArtifactRef to the approval EvidenceRecord
goal: concise outcome
in_scope: []
out_of_scope: []
acceptance_criteria:
  - id: AC-1
    observable: behavior or evidence
    applicability: required | conditional
constraints: []
facts:
  - statement: sourced fact
    source_ref: exact source ID from the referenced ready InitReport
decisions:
  - id: D-1
    kind: product | technical | authority
    depends_on: []
    options: [option-a, option-b]
    selected: option-a
    rationale: explicit rationale
    confirmed_by: user/source
    status: confirmed | deferred | superseded
domain_delta:
  terms: []
  entities: []
  rules: []
open_questions: []
expected_doc_impacts: []
```

Finalization accepted only a `ContextReady` task, the latest exact
`approval_requested` checkpoint, no blocking open question, and an approval
object containing `confirmed_by`, `confirmed_at`, and stable `provenance`.
Direct finalization of a `draft` was rejected as
`clarification.approval_not_requested` and committed nothing. The approval
EvidenceRecord, ClarificationResult, and `ContextReady -> Clarified` Transition
were one atomic `TaskCommit`; its Transition `output_ref` identified the result.
Approval evidence had to pass, the Transition actor was `user`, its inputs were
exactly the approved checkpoint and approval evidence, and each clarification
payload operation ID equaled the owning commit operation ID. Retrying checkpoint,
approval request, or finalization with the same operation ID and identical
content returned the original artifact reference without another write; reusing
the ID with different content was rejected.

At the historical 0.2.3 commit boundary, every new `ClarificationResult` had to
reference an `approval_requested` checkpoint, including when a caller omitted
assurance metadata. For backward compatibility at that time, the 0.2.3 loader
accepted a legacy approval record with no `assurance` only when its producer was
the pre-0.2.3 workflow runtime. A 0.2.3-or-later record, or any record explicitly
marked `caller_asserted`, had to reference an `approval_requested` checkpoint or
the state was rejected as corrupt.

`load_result(task_id, ArtifactRef)` verified all reference fields including the
digest, task ownership, `approved` status, then-current lifecycle projection,
and whether the result was current for the task. No API accepted repository
path as a replacement for `task_id`, and no adapter could auto-select the most
recent task.

The 0.2 runtime exit invariant required no `open_questions` item with
`blocking: true`. Semantic coverage of acceptance criteria, decisions, and
source conflicts was the then-current Skill/user-approval responsibility.
Automatic decision-frontier and source-conflict completeness gates remained
Planned V1.

## DesignDoc (Current prompt contract)

`$sop-design` returns one complete approved Markdown DesignDoc derived from the
exact loaded `RequirementDocRef`. It contains the selected approach, interfaces,
invariants, relevant error/migration/test/rollback decisions, approval evidence,
and requirement provenance needed by Plan. Its content remains in the response
or an already-ignored `design.md` draft. When Runtime receives a caller-supplied
`subject_kind: design_document` and algorithm-qualified `subject_digest`, it
binds only that identity across Design approval and Plan start; it does not write
or load the document.

## DesignResult (Planned V1)

```yaml
requirement_ref: exact RequirementDocRef
alternatives:
  - id: A
    summary: approach
    invariants: []
    interfaces: []
    error_modes: []
    migration: []
    testing: []
    rollout_rollback: []
    operational_cost: []
selected_approach: alternative ID
selection_rationale: []
modules:
  - name: Module
    interface: caller-visible contract
    hidden_behavior: summary
    seams_and_adapters: []
approval_ledger: []
adr_candidates: []
doc_patch_plan: []
unresolved_risks: []
```

Invariant: alternatives use the same comparison dimensions; business ambiguity is not encoded as a technical default.

## PlanDoc (Current prompt contract)

`$sop-plan` produces one detailed Markdown PlanDoc from the complete approved
DesignDoc. The Current PlanDoc is returned in the task response or may have an
optional view at `.scratch/ai-native-devkit/tasks/<task_id>/plan.md` when that
exact path is already ignored. It is not a Git workflow record, a
TaskStateStore artifact, or an implicitly discoverable cross-session reference.

```markdown
# <Change> Implementation Plan

**Source design:** <exact approved design reference and approval>

## Goal
## Design constraints
## Acceptance coverage
## Slice 1: <independently observable result>
**Outcome:** ...
**Design basis:** ...
**Touchpoints:** ...
**Test first:** public seam, scenario, relevant Red
**Implementation:** design-derived actions
**Verify:** exact focused check and expected result
**Done when:** ...
## Final integration
```

Invariants:

- the PlanDoc translates one approved DesignDoc and does not choose a new
  solution;
- top-level slices are ordered and execute serially by default; there is no
  public dependency graph, tracker frontier, write-scope scheduler, or risk-score
  protocol;
- every material design requirement maps to a slice or Final integration, so
  the acceptance denominator cannot silently shrink;
- each behavior slice names its public seam, relevant Red, minimal Green,
  focused verification, and observable completion condition;
- migration, rollback, security, destructive-action, or manual checkpoints are
  added only when the approved design makes them applicable;
- a material design decision is never deferred into Execute.
- after a Plan run has started, a design or repository gap closes that run with
  `stage.fail(error_code: plan.design_gap)`; the router does not continue to
  Execute, and a revised approved DesignDoc starts a new Plan run.

When the Plan approval carries `subject_kind: plan_document` and an
algorithm-qualified `subject_digest`, that value is only a caller-supplied
identity. The runtime can require equality across Plan approval, Plan completion,
and Execute start without storing or reconstructing the Markdown.

## ExecutionResult and ChangeSet (Current prompt contracts)

`$sop-execute` consumes the complete approved PlanDoc and its cited DesignDoc,
executes the ordered slices serially, and returns this result to the calling
workflow:

```yaml
status: completed | blocked | failed | replan_required
baseline: Git commit
candidate: reviewed candidate commit or null
completed_slices: []
focused_checks: []
final_checks: []
review:
  spec: pass | blocked | not_run
  standards: pass | blocked | not_run
remaining_risks: []
```

The review input remains the smaller `ChangeSet` contract:

```yaml
base_revision: hash
candidate_revision: hash or working-tree digest
changed_paths: []
generated_artifacts: []
```

Invariants:

- Execute pins one baseline for the PlanDoc and preserves pre-existing work;
- any pre-existing staged, unstaged, or untracked change requires one clean
  isolated workspace at that baseline for the whole PlanDoc; inability to create
  it closes the run with `stage.fail` and a blocked `ExecutionResult`;
- slices run one at a time through the approved public seam and focused checks;
- every applicable Final integration check must pass or match its `Expected`
  result before Execute may create the candidate commit;
- Execute reviews the exact baseline-to-candidate diff on independent Spec and
  Standards axes;
- changing the candidate invalidates affected evidence and reapplies the same
  focused and Final integration gate before the affected review axis runs again;
- evidence is tied to the candidate revision;
- `completed` closes the Execute run with `stage.complete`; `blocked`, `failed`,
  and `replan_required` close the started run with exactly one `stage.fail`;
- only a completed `ExecutionResult` lets the router enter Verify, Docs Sync, and
  `workflow.finish`; Execute does not own those stages or terminal TaskOutcome.

Durable per-slice cursors, automatic recovery, and cross-session PlanDoc loading
remain Planned V1. They are not a centralized execution ledger or a second
orchestrator.

## DiagnosisResult

```yaml
symptom: exact user-observable failure
feedback_loop:
  command_or_harness: stable invocation
  baseline_results: []
minimal_reproduction: evidence ref
hypotheses:
  - claim: falsifiable cause
    prediction: expected probe result
    probe: one-variable test
    result: supported | rejected | inconclusive
root_cause:
  statement: proven causal chain
  evidence_refs: []
regression: behavior-level test ref
fix_change_set: ChangeSet ref
original_scenario_result: evidence ref
cleanup: removed probes/artifacts
remaining_uncertainty: []
```

Invariant: the root cause cannot be justified solely because the final cumulative state passed.

## ReviewReport

```yaml
baseline: requirement/design/plan refs or digests
change_set: ref
spec:
  findings: []
  result: pass | blocked
standards:
  findings: []
  result: pass | blocked
```

Invariant: Spec and Standards findings remain separate; one axis cannot suppress the other.

## EvidenceRecord and VerificationReport

An `EvidenceRecord` envelope contains this payload:

```yaml
kind: test | build | lint | manual | browser | api | inspection | authority | approval
assurance: caller_asserted | absent
# Historical 0.2/0.2.3 clarification state used caller_asserted approval evidence.
# host_attested is not implemented and is rejected.
invocation: command or stable scenario
observed_revision: RepositoryRevision | null
started_at: timestamp
duration_ms: number
exit_status: pass | fail | unavailable
summary: bounded output
artifact_refs: [ArtifactRef]
authority_grant:
  granted_by: user
  capabilities: [bounded stable capability identifier]
  scopes: [bounded stable scope identifier]
  confirmed_at: timestamp
  provenance: stable interaction reference
  # required only when kind is authority; otherwise null
approval:
  confirmed_by: user
  confirmed_at: timestamp
  provenance: stable interaction reference
  # required only when kind is approval; otherwise absent/null
```

The CLI and store validate ordering, exact references, freshness, and the shape
of caller-supplied approval fields. The current host supplies no host-attested
proof that a later user-authored turn provided those fields. Consequently,
`confirmed_by`, `confirmed_at`, `provenance`, Transition `actor: user`, and
`assurance: caller_asserted` record caller assertions rather than host
verification. Existing compatible evidence may omit `assurance`; evidence must
not claim `host_attested` until a verifier is implemented.

The store accepts generic authority bounds. The InitEngine narrows its own
grant to exactly `repository.read` and one canonical repository scope encoded
as `repository:v1:` plus RFC 3986 percent-encoded UTF-8 relative path (`.` for
the repository root); it rejects extra capabilities or scopes.

For S0 inspection evidence, `observed_revision` must equal the EvidenceRecord
envelope's `repo_revision`.

A `VerificationReport` payload is:

```yaml
acceptance:
  - criterion_ref: AC-1
    applicable: true
    evidence_refs: [ArtifactRef]
    result: pass | fail | unverified
overall: pass | fail | blocked
gaps: []
```

Invariant: unavailable environment is not pass; stale evidence does not satisfy a changed revision.

## TaskOutcome

The YAML below is the Planned V1 persisted artifact. The Current prompt Skills
emit a compatibility projection with camelCase fields
`workflowTier`, `docsImpact`, and `remainingRisks`; adapters
must map those names explicitly rather than treating the two wire shapes as one.

```yaml
intent: development | debug
workflow_tier: fast | standard | strict
route: lightweight | development | debug
final_revision: hash or working-tree digest
requirement_ref: optional exact RequirementDocRef
design_ref: optional
plan_digest: optional algorithm-qualified PlanDoc identity
execution_or_diagnosis_ref: required for change/debug
review_ref: required when configured
verification_ref: required
durable_changes:
  domain: []
  architecture: []
  interface: []
  operations: []
  pitfalls: []
documentation_candidates: []
remaining_risks: []
```

## DocImpactReport and SyncReceipt

```yaml
doc_impact:
  task_outcome_ref: ID and hash
  base_revision: verified revision
  changes:
    - destination: path
      class: none | deterministic | semantic | conflicted
      rationale: durable impact
      evidence_refs: []
      patch_preview: ref
      approval_required: boolean
  conflicts: []

sync_receipt:
  applied_revision: repository/doc revision
  applied_changes: []
  approvals: []
  validation_evidence: []
  unapplied_conflicts: []
```

Invariants:

- semantic patches require approval;
- apply checks the same base hashes used by plan;
- conflicts produce no silent write;
- the receipt records no-impact decisions as well as applied changes.

## Transition record

A persisted `Transition` envelope contains this payload:

```yaml
from: lifecycle state
to: lifecycle state
reason: route/gate/user/system reason
input_refs: [ArtifactRef]
output_ref: ArtifactRef | null
actor: runtime | user | stage module
```

`TaskStateStore` derives `from` from committed state and rejects an invalid
requested transition. The Transition envelope's `created_at` is the committed
occurrence time. It appends the transition and artifacts in one atomic
`TaskCommit`; failure cannot advance authoritative in-memory or durable state.
Interrupted filesystem persistence reloads the last complete commit, while
corrupt committed state produces a typed runtime error.
