# Roadmap and validation

## Delivery strategy

Build one executable vertical slice at a time. Do not begin by copying all upstream Skill text. Start with versioned contracts and a frozen end-to-end fixture so each stage can be implemented behind a stable interface.

## Status snapshot

| Slice | Status |
|---|---|
| v0.1 plugin, Skills, templates, validators, handoff isolation | **Current** |
| S0 Init/runtime contract kernel | **0.2 implemented** with contract, module and integration coverage |
| Historical S2 checkpoint/result persistence kernel | **Superseded in 0.4.0**; external state remains untouched and unsupported |
| Init identity isolation and confirmation gates | **0.2.3 implemented** for Init choices, authority, and docs writes |
| Execution Trace Collector and Docs Hook | **0.3 implemented** with runtime-gated lifecycle collection, append-only events, typed stage/approval transitions, route completion checks, deterministic Init/Docs path details and post-verify Docs classification; non-plugin Sessions create no Trace |
| Git requirements Clarify/Design handoff | **0.4.0 implemented** with Superpowers-aligned dialogue, minimal one-file Git commits, exact Trace approval, and exact approved loading |
| PlanDoc and serial Execute prompt contracts | **Current** Skills: approved DesignDoc-derived Markdown PlanDoc, ordered vertical slices, serial behavior-first execution, candidate review, and `ExecutionResult`; no durable slice cursor |
| S1, complete S2/S3/S6–S9 runtimes, and PlanDoc/cursor recovery | **Planned V1**; no ExecutionEngine interface selected |

An installed-plugin smoke test and publication remain release actions; their
absence must not be reported as completion of the full V1 runtime.

## P0: runnable engineering loop

### S0 — runnable `$sop-init` thin slice and contract kernel

The kernel in this section is 0.2 implemented. The acceptance list remains the
regression contract; installed-host smoke and publication are separate release
gates requiring the appropriate authority.

**Implemented kernel outcome:** the packaged `$sop-init` Phase 1 adapter can call the
versioned runtime, persist resumable state outside the Target Repository, and
return a sourced structured InitReport. **Remaining release-gate outcome:** prove
discovery and execution from a clean supported local Codex task after explicit
installation authority.

Implemented in 0.2:

- ship a plugin-owned Python standard-library execution module as source, with no
  third-party runtime dependency, execution-module install or build step, or
  unverified runtime fallback;
- expose that module through one versioned JSON CLI whose responses are exactly
  `report`, `choice_required` or `runtime_error`, reserving stdout for the
  response and stderr for bounded non-authoritative diagnostics;
- integrate Phase 1 of `sop-init/SKILL.md` as a narrow runtime adapter with
  required user choices and concise Markdown rendering from the structured
  response; its Current prompt-driven Phase 2 docs workflow is not part of S0;
- implement a read-only InitEngine that normalizes an eligible non-bare Git
  worktree while retaining an optional descendant `requested_scope`, computes
  deterministic source and worktree digests, records bounded findings and
  produces `ready` or `blocked` InitReports;
- encode TaskRequest, Transition, EvidenceRecord and InitReport as typed Python
  value structures with explicit validation, a common ArtifactEnvelope and
  algorithm-qualified ArtifactRef values;
- implement the TaskStateStore `load(task_id)` and atomic `commit(TaskCommit)`
  interface, including transition/reference validation, optimistic concurrency,
  idempotent operations, immutable `supersedes` chains, redaction, compatible
  unknown-field preservation and corruption detection;
- implement filesystem production and in-memory test adapters only for atomic
  compare-and-commit persistence, with authoritative state outside both the
  Target Repository and plugin installation;
- create frozen repository-context fixtures and run identical module behavior and
  adapter contract tests against both persistence adapters;
- validate CLI request envelopes, response invariants, bounded diagnostics and
  safe optional runtime-error evidence.

Remaining release action: after explicit installation authority, run a
supported-interpreter preflight and clean-task `$sop-init` smoke test, then record
the test commands.

Acceptance/regression gates:

- the S0 Phase 1 runtime never modifies the Target Repository, silently initializes Git, clones or
  creates a temporary worktree;
- non-Git and bare targets return typed `blocked` reports, while unborn, dirty and
  detached-HEAD worktrees can reach `ContextReady`; selecting a submodule records
  optional superproject metadata, while selecting its parent never
  auto-initializes it;
- invalid transitions, invalid references and incompatible schema versions are
  rejected, while compatible unknown fields survive round trips;
- new-task creation records one immutable TaskRequest and the initial `Intake`
  checkpoint without fabricating a `missing -> Intake` transition; later
  authority grants append bounded typed authority evidence rather than mutating
  the request;
- an initial implicit caller identity already bound to another repository target
  creates a separate task without modifying the first, including when concurrent
  initial calls race;
- explicit task IDs and `choice` or `authority_grant` follow-ups remain
  repository-target strict and never fall back to a new identity;
- each `ready` or `blocked` InitReport, its evidence and any newly created
  transition become visible atomically, and an interrupted task reloads the last
  committed state; repeated Blocked reports create no self-transition;
- corrupt state produces a typed runtime error rather than a partial task or
  failed-report outcome;
- raw secrets and forbidden fields are absent from every persisted byte and
  bounded diagnostic;
- the same fixtures produce equivalent results through filesystem and in-memory
  adapters;
- `ready` reuse is offered only for a matching repository revision, while retrying
  a Blocked task preserves immutable report history through `supersedes`;
- unresolved authoritative-source conflicts that can change safe behavior return
  a typed `blocked` report rather than a guessed `ready` result;
- the CLI emits one valid response envelope: `ready` and `blocked` reports plus
  expected choices exit zero, while structured runtime errors exit nonzero;
- the minimum Python version is derived from used syntax/APIs and enforced by
  preflight; tests exercise the active development interpreter, and an unsupported
  host does not install or select a fallback runtime;
- after explicit installation authority, a newly created supported local task
  discovers `$sop-init`, demonstrates that its Codex task identifier can bind the
  Workflow Task ID, produces the expected InitReport, and passes plugin
  validation.

S0 non-goal: no RouteDecision, ContextBundle, deterministic
Bootstrap/Adapt/Refresh runtime integration, Target Repository writes, external
Cooper adapter or general workflow orchestrator. The Current `$sop-init` Phase 2
prompt workflow can preview and apply approved docs changes, then creates a fresh
read-only post-write task/report; that does not turn it into the planned S1
`ContextCatalog`. The Historical 0.2/0.2.3 clarification persistence flow does
not change these S0 boundaries. S0 also has no automatic task-state
expiry/deletion; retention and cleanup UX are deferred.
RouteDecision is introduced with integrated routing in S9. ChatGPT Web, Codex
Cloud, Windows and self-contained binary distribution are also outside S0 until
their own smoke and adapter tests exist.

### S1 — ContextCatalog and `$sop-init`

**Outcome:** a new or mature repository receives a sourced ContextBundle without destructive document rewriting.

Build:

- project inventory;
- Bootstrap, Adapt and Refresh mode selection;
- repository docs routing and content hashes;
- source conflict/drift reporting;
- safe plan/preview for structural changes;
- fixture repository adapter.

Acceptance:

- empty project receives the minimum structure and entry rules;
- mature project keeps all valid existing files;
- Adapt produces a preview before semantic moves/splits;
- stale index and broken-link fixtures are detected;
- repeated Refresh is idempotent.

### S2 — `$sop-clarify`

**Current 0.4.0 outcome:** an appropriately scoped request becomes one minimal,
human-readable Git requirements workflow record. Approval is bound to its exact
`RequirementDocRef`, and Design loads only that explicit approved reference.
The boundary is defined by ADR 0006.

**Historical 0.2/0.2.3:** immutable ClarificationCheckpoint persistence,
ClarificationResult, baseline approval, and `task_id`/ArtifactRef clarification
resume are superseded and unsupported. Existing external state is not migrated
or deleted.

Still to build for the complete stage:

- stronger question prioritization and blocking-conflict detection without a
  structured clarification baseline;
- broader behavior evaluation across independent repositories and task classes;
- an external-source adapter if automatic revalidation becomes necessary.

Acceptance:

- the Skill uses the pinned Superpowers 6.3.0 requirement-understanding wording
  without a runtime dependency;
- no clarification artifact is written before the interview completes;
- Writer commits exactly one minimal requirements path while preserving unrelated
  staged, unstaged, and untracked work;
- approval binds exact path, commit, blob identity, repository, and later user turn;
- changed documents cannot reuse earlier approval;
- Design receives only an exact approved `RequirementDocRef`;
- requirements prose excludes solution design and execution planning;
- optional source references remain human-readable and verifiable;
- historical requirements remain workflow records rather than CurrentState;
- old clarification operations are unsupported without deleting external state;
- all focused tests, Skill validators, plugin validation, and the repository
  suite pass with fresh evidence.

### S3 — `$sop-design`

**Outcome:** exact approved requirements Markdown becomes an approved DesignResult with traceable alternatives.

Build:

- two or more genuinely different approaches when appropriate;
- common comparison dimensions;
- deep-module interface and seam checks;
- migration/error/test/rollback sections;
- section approval ledger for high-risk design;
- Spec lint and invalidation on changed inputs.

Acceptance:

- known design fixture covers its oracle decisions;
- alternatives are rejected if they use incomparable criteria;
- unresolved product meaning returns to clarification;
- repo/upstream drift invalidates the affected DesignResult;
- no implementation action occurs before required approval.

### S4 — `$sop-plan`

**Current prompt outcome:** one complete approved DesignDoc becomes a detailed
Markdown PlanDoc that another execution context can follow without redesigning
the solution.

Build:

- source-design provenance and inherited constraints;
- ordered vertical slices with independently observable outcomes;
- complete acceptance coverage across slices and Final integration;
- per-slice Design basis, Touchpoints, public seam, relevant Red, focused check,
  expected result, and `Done when`;
- migration, rollback, security, destructive-action, and manual details only when
  required by the approved design;
- optional caller-supplied digest identity at the existing approval boundary.

Acceptance:

- every material DesignDoc requirement has an implementation and verification
  owner;
- slice order is sufficient for serial execution without a dependency graph,
  tracker frontier, or write-scope scheduler;
- routine fixture stays concise;
- migration fixture receives detailed verification and rollback steps;
- no new unapproved design decision appears in a slice;
- PlanDoc content stays in the response or an already-ignored draft; Trace stores
  only bounded digest identity when supplied;
- a design/repository gap after Plan starts emits `stage.fail(plan.design_gap)`
  and does not unlock Execute.

### S5 — `$sop-execute`, TestGate and ReviewGate

**Current prompt outcome:** one approved PlanDoc is executed serially through
behavior tests and one fixed-candidate two-axis review, producing
`ExecutionResult` for the calling workflow.

Build:

- one exact baseline and one safe workspace for the PlanDoc;
- mandatory whole-Plan isolation when the original worktree or index contains
  any staged, unstaged, or untracked user change;
- ordered one-at-a-time slice execution;
- public-seam Red→Green gate;
- focused checks plus final integration checks;
- one local candidate commit followed by Spec and Standards review of the same
  baseline-to-candidate diff;
- bounded retry/rework policy;
- explicit `execute.replan_required` when repository facts invalidate the design.

Acceptance:

- a fixture change cannot pass with compilation-only Red;
- a Spec failure is not hidden by clean code quality;
- a Standards failure is not hidden by requirement coverage;
- slices are attempted in PlanDoc order and a failed slice does not silently skip
  to later work;
- a changed candidate invalidates affected checks and review evidence;
- Execute returns `ExecutionResult` and does not invoke Verify, Docs Sync, or
  construct terminal `TaskOutcome`;
- every applicable Final integration `Expected` result is a hard pre-candidate
  gate and is reapplied after candidate changes;
- `blocked`, `failed`, and `replan_required` each produce one terminal
  `stage.fail`; only `completed` lets the router enter Verify, Docs Sync, and
  `workflow.finish`.

Durable per-slice cursor/recovery and cross-session PlanDoc selection remain
Planned V1. They are not represented by a public execution ledger, tracker
frontier, concurrency scheduler, or named ExecutionEngine.

### S6 — `$sop-verify`

**0.3 slice:** the Skill enforces fresh-evidence discipline and submits a
code-validated `verification.complete` event that automatically invokes the Docs
Hook after a pass. **Planned V1 outcome:** completion is represented by a persisted
full VerificationReport with current candidate evidence and acceptance denominators.

Build:

- EvidenceRecord ingestion;
- revision/freshness checks;
- acceptance mapping and denominators;
- environment-gap classification;
- manual/browser/API evidence adapters later behind the same interface.

Acceptance:

- stale passing output is rejected after a change;
- unavailable Docker/browser/production access yields unverified, not pass;
- applicable criteria report passed/total counts;
- original-scenario evidence is mandatory for bug fixes;
- final report distinguishes failures, gaps and non-applicable criteria.

### S7 — `$sop-debug`

**Outcome:** a reported failure follows an evidence-driven diagnosis protocol and produces a behavior regression.

Build:

- feedback-loop selection and readiness gate;
- exact/minimal reproduction records;
- hypothesis/prediction/probe ledger;
- targeted observability helpers;
- root-cause evidence chain;
- regression and original-scenario rerun;
- cleanup verification.

Acceptance:

- no causal theory is accepted before the feedback loop runs;
- rejected hypotheses remain auditable without bloating canonical docs;
- two distinct messages/events are not merged by an invented heuristic in the yaw fixture;
- cumulative changes do not prove root cause without attribution;
- temporary debug logs/harnesses are removed or deliberately retained in a debug location.

### S8 — `$sop-sync-docs`

**0.3 slice:** the post-verification Docs Hook derives changed paths from Git and
automatically identifies docs impact without proposing Handoff work. The Skill completes deterministic
sync or a semantic preview; promoted RequestedState decisions retain exact
task/artifact provenance. Transactional publication remains planned.

**Planned V1 outcome:** a verified TaskOutcome produces safe documentation changes and a SyncReceipt.

Still to build:

- deterministic patch application;
- semantic diff preview and approval;
- stale-base/conflict handling;
- index/link validation;
- Cooper source metadata preservation;
- no-impact receipt.

Acceptance:

- pure internal refactor produces no semantic-doc churn;
- API/domain change proposes the correct documents;
- semantic change is not applied without approval;
- source conflict produces no write;
- applied docs reference the verified revision and pass link/index checks;
- repeated application is idempotent.

### S9 — integrated route and release-ready local install

**Outcome:** Fast, Standard and Strict fixtures run through the installed plugin.

Build:

- top-level WorkflowRuntime adapters;
- route decision UX and user override;
- plugin Skills with complete trigger boundaries;
- replace the 0.3 typed event-only boundaries with persisted Design, Plan,
  Execute, Debug, Verify and Docs Sync artifacts without scraping private host
  logs;
- production-ready local marketplace entry only when explicitly approved;
- installation/update runbook.

Acceptance:

- plugin and every Skill validator pass;
- Fast fixture skips unnecessary stages but still verifies and resolves docs impact;
- Strict signals cannot be silently downgraded;
- interruption/resume succeeds in each route;
- clean new tasks load every installed stage Skill, extending the S0 smoke test;
- no external upstream workflow is required at runtime.

## P1: reliability and team reuse

- production Cooper adapter with refresh/version metadata;
- managed RDS, Apollo, KMS, MQ and framework knowledge packs;
- task/source drift notifications;
- structured doc-diff UI and conflict resolution;
- richer evaluation runner and blinded report package;
- automatic route calibration with explicit safety floors;
- browser/API/manual verification adapters;
- state schema migration and recovery tooling.

## P2: product and QA loop

- product objective, prototype and metric artifacts;
- acceptance-case design shared by product, engineering and QA;
- real browser/UI and API test execution;
- release readiness and production verification;
- product/QA Skill selection based on dedicated experiments.

## Validation pyramid

| Layer | What it protects |
|---|---|
| Schema/contract tests | stable stage interfaces and compatible persistence |
| Module behavior tests | deep module behavior through its interface |
| Adapter contract tests | production and fake adapters obey the same seam |
| Route integration tests | stage selection, transitions, pause/resume and gates |
| Frozen evaluation fixtures | task quality, interaction cost and regression against known oracles |
| Installed-plugin smoke tests | discovery, manifest, Skill triggers and clean-thread behavior |

## Evaluation backlog

### Debug selection

Run multiple independent bug classes with:

- identical isolated repositories and artifacts;
- exact upstream Skill versions;
- equivalent original-symptom feedback loops;
- symmetric evidence responses;
- reversed execution order or separate operators;
- independent final reviewers;
- ablation of claimed key fixes.

Until then, keep DiagnosisEngine protocol-driven and replaceable.

### Execute composition

Re-test serial PlanDoc slices and one end-of-plan candidate review using the same
final-review and intervention rules. Measure accepted correctness first, then
manual advances, early issue detection, rework and elapsed time. Do not infer a
need for a tracker frontier, durable ledger, or concurrent scheduler from this
evaluation.

### Design hybrid

Compare the combined workflow against each source workflow. The hybrid must prove increased oracle coverage without simply adding both dialogue costs.

### Cross-cutting gates

Test TDD, ReviewGate and VerifyGate independently so a useful mechanism is not credited merely because it was bundled with a stronger end-to-end workflow.

## Next implementation work

The S0 kernel and 0.4.0 Git requirements handoff now provide deterministic
seams. Continue vertically rather than declaring the entire prompt-driven workflow
to be a structured runtime:

1. keep all S0 and clarification contract/module/integration tests green and run
   the official plugin validator;
2. with explicit installation authority, complete clean-task `$sop-init` and
   cross-session exact `RequirementDocRef` host smoke tests;
3. implement S1 ContextCatalog behind its documented interface without widening
   TaskStateStore;
4. improve S2 question prioritization without recreating the removed structured
   baseline or a second orchestrator;
5. advance to S3 only after a frozen clarification fixture proves no repeated
   interview is needed in a new session.

## 0.4.0 verification evidence

Date: 2026-08-28.

Pre-promotion evidence on candidate revision `feb42db0ca39a55a2d2ef3adbed88fcb99580148`:

- `python3 -m unittest tests.contract.test_contracts tests.contract.test_task_state_store tests.modules.test_requirement_approval tests.modules.test_requirement_document tests.modules.test_execution_trace tests.integration.test_workflow_cli tests.integration.test_runtime_trace_and_docs_hook tests.integration.test_trace_collector_cli tests.test_plugin_contract tests.test_skill_contract tests.test_development_skills tests.test_decision_promotion tests.test_docs_template tests.test_end_to_end_contract -v` passed 235 tests;
- `for skill_dir in plugins/ai-native-devkit/skills/*; do python3 /Users/didi/.codex/skills/.system/skill-creator/scripts/quick_validate.py "$skill_dir"; done` passed all 10 packaged Skills;
- `python3 /Users/didi/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/ai-native-devkit` passed;
- `python3 scripts/validate_all.py` passed 356 tests and plugin validation;
- the Task 11 `rg` old-symbol command, `git diff --check`, and
  `git status --short` were clean.

Post-promotion evidence on the final pre-commit tree:

- `python3 -m unittest tests.test_skill_contract tests.test_end_to_end_contract tests.test_execution_trace_docs -v` passed 31 tests;
- the same Skill loop passed all 10 packaged Skills;
- the same plugin-validator command passed;
- `git diff --check` passed;
- `python3 scripts/validate_all.py` passed 356 tests and plugin validation.

After commit, Task 11 reruns `python3 scripts/validate_all.py`, the same 10-Skill
validator loop, an unchanged-HEAD assertion, and a clean-worktree assertion on
the captured committed revision.

Remaining risks and release boundaries:

- installed-plugin smoke and publication were not run because they are separate
  authority-gated release actions;
- interrupted interviews before document creation remain resumable only in the
  original Codex task conversation;
- external source freshness still requires Design to re-read the source because
  there is no runtime external-source adapter;
- repository commit hooks and unsupported Git capabilities can deliberately
  produce typed failure or an indeterminate no-reference result;
- the integrated WorkflowRuntime and downstream structured engines remain
  Planned V1.

### Post-review corrective evidence — 2026-08-28

The two-axis review found an approval repository-scoping gap, Init/Docs
observation of excluded workflow records (including resumed v1 observations),
and a stale Current clarification-persistence claim. The corrective commits were
`3fb8b9f` (`fix: scope requirement approvals to stage repository`), `a20f953`
(`fix: exclude workflow records from init observation`), and `480193b`
(`fix: sanitize resumed init observations`). On revision
`480193bafe4115c2d93c7947376f5b42554087a5`, the scoped re-review concluded
**Standards PASS / Spec PASS**, with zero open P0/P1 findings.

Fresh fix-report evidence recorded 55 focused approval tests and 359 full tests;
75 focused Init/Docs tests in the first round, then 7 Init tests plus 23 Docs
Sync/runtime tests and 362 full tests in the final round. All 10 packaged Skill
validators and the plugin validator passed.

Release boundaries are unchanged: no plugin install or publication was run;
pre-document interviews have no repository-level resume; external-source
freshness still lacks a runtime adapter; repository hooks and unsupported Git
capabilities may return typed failure or an indeterminate no-reference outcome;
and the integrated WorkflowRuntime and downstream structured engines remain
Planned V1.

This is post-review corrective evidence for revision `480193b`; the exact final
evidence commit is revalidated separately, and its OID is reported only in the
human handoff to avoid a self-referential evidence claim.
