# Automatic Execution Trace

[Explicit user direction](user-direction.md) governs scoped exceptions to the
normal stage, input, approval, verification, and completion rules below.

The plugin bundles `hooks/hooks.json` and `scripts/trace_collector.py`. After the
user reviews and trusts the Hook once with `/hooks`, the Hook receives Codex
lifecycle callbacks. It does not persist them until a validated DevKit Runtime
operation emits `workflow.started` for that Session. Sessions that never use the
plugin do not create a Trace. After activation, collection is automatic; the
Agent does not start, update, finish, or summarize Trace records.

Host lifecycle facts use `source: codex_hook`. Validated workflow state changes
use `source: devkit_runtime`. `codex_transcript_fallback` is reserved for a
deterministic recovery path when a structured event is missing; using it marks
the capture partial.

ID relationships are fixed:

```text
session_id 1 : 1 trace_id
trace_id   1 : N turn_id
turn_id    1 : N event_id
```

Each line of `events.jsonl` is a full event with `schema_version`, `trace_id`,
`seq`, `event_id`, `timestamp`, `event_type`, `stage`, `actor`, `source`,
`correlation`, and a bounded, redacted `payload`. `summary.json` is a deterministic
projection and can be rebuilt from events. Neither file contains evaluation
oracles or `observation_mode`.

Every required SOP stage run uses `workflow.stage.started` followed by exactly one of
`workflow.stage.completed | workflow.stage.skipped | workflow.stage.failed`.
All four event types carry a code-generated `stage_run_id` and their own timestamp.
The deterministic summary projects `started_at`, `ended_at`, `duration_ms`, and
terminal status for each run, including retries as separate runs.
Route-owned non-applicable stages may be recorded directly as skipped; they do
not satisfy a required stage.

Clarify, Design, and Plan confirmation use paired `approval.requested` and
`approval.resolved` events. A code-generated `approval_id` identifies the exact
request; `stage_run_id` binds it to the stage. The Trace records only approval
kind, decision, timestamp, and bounded artifact digest where one exists. It does
not store the presented baseline, design, plan, or user message.

For the Current Design/Plan identity chain, the producing Skill computes
`sha256` over the exact UTF-8 Markdown bytes. Design and Plan approval/terminal
events carry only `subject_kind` plus `subject_digest`; Plan and Execute start
events carry the upstream `source_subject_digest`. Runtime checks those values
against the completed upstream stage for the same repository. These facts do
not make Trace a DesignDoc/PlanDoc store or a durable execution cursor.

## Exact Clarify handoff

- normal: `stage.start(clarify) -> interview -> requirements.write -> approval.request/resolve -> stage.complete(clarify, exact subject) -> requirements.load(purpose: design) -> stage.start(design)`
- later task with explicit approved ref: `stage.start(clarify) -> stage.complete(clarify, exact subject) -> requirements.load(purpose: design) -> stage.start(design)`; import the exact completed approval, do not replay the interview or request approval again
- input drift before Design: return bounded drift details and recommendations,
  do not start Design or Clarify automatically, and wait for explicit user
  direction; invoke `$sop-clarify` only when the user chooses requirement revision

A local request, resolution, and Clarify terminal share one `stage_run_id`. An
imported terminal uses the current Clarify run ID and cites the exact
`approval_id + subject_digest` of an original completed attempt whose run ID may
differ. `$coding-sop` remains the only top-level orchestrator.

Default storage:

```text
~/.codex/state/ai-native-devkit/v1/execution-traces/<trace_id>/
├── metadata.json
├── events.jsonl
└── summary.json
```

Set `AI_NATIVE_DEVKIT_STATE_ROOT` only for isolated development or testing. Trace
must remain outside both the target repository and plugin installation.

The runtime CLI is not a logging API for the Agent to fill. It is the code boundary
that validates real workflow transitions and emits their facts. Use it only at the
decision point described by the owning Skill. Current operations are
`workflow.route`, `workflow.user_decision`, `docs.classify`, `stage.start`, `stage.complete`, `stage.fail`,
`approval.request`, `approval.resolve`, `verification.complete`,
`workflow.finish`, and `trace.load`. Skills invoke
these control transitions; they never compose event payloads, summarize a turn,
or display Trace-only status to the user.

All control requests use the standard schema and infer `session_id` from the
Host. The bounded shapes are:

```json
{"schema_version":"ai-native-devkit/v1alpha1","operation":"stage.start","stage":"design","cwd":"/absolute/repository"}
{"schema_version":"ai-native-devkit/v1alpha1","operation":"approval.request","stage":"design","stage_run_id":"runtime-returned-id","approval_kind":"design.solution","subject":{"kind":"design_document","digest":"sha256:<64 lowercase hex>"},"cwd":"/absolute/repository"}
{"schema_version":"ai-native-devkit/v1alpha1","operation":"approval.resolve","approval_id":"runtime-returned-id","decision":"approved","cwd":"/absolute/repository"}
{"schema_version":"ai-native-devkit/v1alpha1","operation":"stage.complete","stage":"design","stage_run_id":"runtime-returned-id","subject":{"kind":"design_document","digest":"sha256:<64 lowercase hex>"},"cwd":"/absolute/repository"}
{"schema_version":"ai-native-devkit/v1alpha1","operation":"stage.start","stage":"plan","source_subject_digest":"sha256:<approved DesignDoc digest>","cwd":"/absolute/repository"}
{"schema_version":"ai-native-devkit/v1alpha1","operation":"stage.start","stage":"execute","source_subject_digest":"sha256:<approved PlanDoc digest>","cwd":"/absolute/repository"}
```

`stage.fail` adds a stable `error_code`. User-directed skips use
`workflow.user_decision` as described in `user-direction.md`.
Encode requests as JSON and parse the one JSON response. Never interpolate user
text or send design/plan content to this control interface.

`workflow.finish` is a code-owned completion gate. It verifies the route's
required stages are terminal in order, Clarify/Design/Plan approvals belong to
their completed runs, verification passed, and Docs Sync resolved. Missing facts
leave the Trace incomplete instead of producing `workflow.completed`.

`init_cli.py` automatically captures the pre-write docs inventory and selects
Bootstrap, Adapt, or Refresh. The existing project-docs validator completes the
same Init run by comparing that private baseline with the validated filesystem.
The resulting `init.completed` event lists recognized, generated, overwritten,
preserved, removed, and conflicting paths. This reuses the normal Init scan and
validation; it adds no Agent-authored inspection or user question.

Docs Sync keeps a private content-hash inventory outside the target
repository. Its terminal runtime event exposes only bounded created,
modified, and removed paths plus counts; the Agent does not provide them.

Human-facing Handoff is no longer a plugin capability. There is no Handoff
stage, approval, content observer, or path-based Hook denial. Historical
`handoff.*` events and `summary.handoff_actual_result` remain readable, but
new runtime calls cannot emit those events or resolve retired approvals.
Existing trace and user document files are not migrated or deleted.

`PostToolUse` records both successful and non-zero tool results. If Codex ends a
session without a terminal callback for a requested tool, SessionEnd transcript
recovery closes it as `tool.abandoned` with an unknown result rather than leaving
an unmatched request. The summary reports requested, completed, errored, blocked,
and abandoned tool counts. Transcript fallback is bounded to the workflow time
window; ordinary turns after workflow completion are ignored even when the
Codex Session remains open.

The collector never stores full prompts, full assistant messages, raw commands,
raw tool output, credentials, cookies, personal data, or complete source files.
Collector errors are fail-open for the engineering task and are recorded as
fingerprinted health records under `execution-traces/collector-errors.jsonl`.
