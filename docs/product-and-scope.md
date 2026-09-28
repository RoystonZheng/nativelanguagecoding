# Product and scope

## Product thesis

Teams already know that good context, explicit decisions, tests and documentation improve AI-assisted development. The failure is operational: the workflow is too easy to skip on risky work and too expensive to run on simple work.

AI Native DevKit turns that discipline into a portable Codex plugin: it selects
the smallest safe workflow, preserves decisions needed by later stages, requires
evidence before completion, and promotes only durable knowledge into project
documentation.

## Delivery status

### Current 0.4.0

Clarify reuses the Superpowers requirement-understanding behavior without a
runtime dependency, then writes one minimal Git requirements workflow record.
Approval binds its exact path, commit, and blob; Design accepts only that
explicit approved reference. The old checkpoint/result contract is removed
without migrating or deleting external state. The runtime and Skill contract are
0.4.0 implemented; workflow records remain separate from canonical CurrentState.

| Status | Scope |
|---|---|
| **Current** | Installable plugin, explicit `$coding-sop` routing, stage Skills, and project-doc tooling |
| **0.2 implemented** | Read-only initialization runtime, versioned JSON contracts, and TaskStateStore |
| **0.2.3 implemented** | Cross-target isolation for implicit Init caller identity plus mandatory later-user-message gates for Init choices, authority, and docs writes |
| **0.3 implemented** | Automatic plugin-bundled Execution Trace with typed stage/approval events, route completion gate, deterministic Init/Docs path details, plus the post-verification Docs Hook; no evaluation oracle or production telemetry |
| **0.4.0 implemented** | Superpowers-aligned requirement discovery, one minimal Git workflow record, exact Trace approval, and exact approved `RequirementDocRef` loading by Design |
| **Historical clarification** | The removed 0.2/0.2.3 checkpoint/result and baseline-approval flow; existing external state remains untouched and unsupported |
| **Planned V1** | Integrated WorkflowRuntime, ContextCatalog, automatic risk tiers, structured Design/Verify/Docs contracts, and future PlanDoc/cursor recovery without a preselected ExecutionEngine |

The existence of a stage Skill is not evidence that the corresponding Planned V1
engine, lifecycle transition, or persisted output is already implemented.

The Current Plan/Execute prompt slice is deliberately smaller than such an
engine. Plan derives one detailed Markdown PlanDoc from the approved DesignDoc;
Execute follows its ordered vertical slices serially and returns
`ExecutionResult`. The router then owns Verify, Docs Sync, and terminal
`TaskOutcome`. PlanDoc content remains in the response or an already-ignored
draft. The runtime may correlate a caller-supplied digest identity, but it does
not write or load the document.

## Target users

- engineers using Codex for day-to-day repository work;
- product and engineering collaborators who need decisions to remain traceable;
- maintainers taking over a repository or a partially completed task;
- teams that want reusable platform knowledge without loading every guideline into every prompt.

## Core jobs

1. Understand a new or existing repository without blindly loading all documentation.
2. Turn an ambiguous request into a confirmed, reviewable Git requirements record.
3. Compare technical approaches without repeating the requirement interview.
4. Produce a detailed, design-derived PlanDoc of ordered vertical slices instead of a long implementation transcript or task graph.
5. Execute or debug with tests, stage reviews and fresh completion evidence.
6. Keep project documentation aligned without writing proposals as current facts.
7. Resume private workflow state by exact identity and hand requirements across sessions by an exact approved Git reference.

## Planned V1 scope: complete engineering loop

V1 includes:

- `$sop-init`: bootstrap, adapt or refresh project context;
- the Current router classifies `intent` as `development | debug`, selects Fast,
  Standard or Strict `workflowTier`, and projects the compatibility `route` as
  `lightweight | development | debug`; the integrated runtime persists and
  automatically risk-scores the same decision;
- `$sop-clarify`: facts, scope, acceptance criteria, domain terms and decisions;
- `$sop-design`: alternatives, trade-offs, selected solution, test and rollback design;
- `$sop-plan`: detailed DesignDoc-derived Markdown PlanDoc with ordered vertical
  slices and complete acceptance coverage;
- `$sop-execute`: serial PlanDoc implementation with behavior-first tests,
  focused checks, and one baseline-to-candidate two-axis review;
- `$sop-debug`: reproduction, hypotheses, probes, regression and original-symptom verification;
- `$sop-verify`: acceptance mapping based on fresh evidence;
- `$sop-sync-docs`: documentation impact planning, preview and controlled application;
- trace and resume: stage state, evidence and blocking reason without private
  reasoning logs; durable PlanDoc loading and per-slice cursor recovery remain
  future Planned work rather than a public execution ledger.

## Non-goals for V1

- replacing the repository's issue tracker or source-control platform;
- copying complete Matt-Skills or Superpowers workflows into the plugin;
- silently changing semantic project documentation;
- treating full chat transcripts as project memory;
- implementing a general agent framework or arbitrary DAG engine;
- full product-design and QA automation;
- publishing a marketplace release without runnable-slice validation.

## Product values

### Smallest safe process

Simple, reversible tasks should not pay for a full requirements and architecture process. Data migrations, authentication, cross-module contracts and destructive operations must be upgraded automatically.

### Evidence over confidence

The plugin reports what was executed, what passed, what remained unverified and why. It does not convert plausible reasoning into a completion claim.

### Durable context without pollution

The system captures decisions immediately in task state, but only promotes stable, sourced and approved facts into canonical docs.

### One workflow owner

The plugin owns routing and lifecycle state. Stage mechanisms can be replaced or improved without changing the caller's workflow.

### Human authority at meaningful boundaries

User confirmation is reserved for product meaning, semantic documentation, permission changes, destructive actions and material scope changes—not routine progress acknowledgements.

## Planned V1 definition of Accepted Done

A task is Accepted Done only when:

1. the applicable acceptance criteria are mapped to current evidence;
2. required tests and original scenarios have fresh results;
3. spec and repository-standards review have no unresolved blocking findings;
4. known limitations and environment gaps are explicit;
5. documentation impact is either applied, approved for later work, or explicitly judged unnecessary;
6. the final TaskOutcome and SyncReceipt are persisted.

The Current prompt workflow can complete only with fresh verification and an
explicit docs-impact conclusion. It returns the compatibility TaskOutcome
projection, but does not claim the not-yet-implemented persisted V1
TaskOutcome/SyncReceipt pair.

## Success measures

| Dimension | Initial V1 measure |
|---|---|
| Workflow fit | Correct route for simple, standard and strict fixtures |
| Requirement quality | Required decision/acceptance coverage with zero unsupported assumptions |
| Collaboration cost | User intervention count and repeated-question count |
| Delivery quality | Accepted Done rate and first-formal-fix success rate |
| Verification | Acceptance criteria with fresh evidence / applicable criteria |
| Documentation | Required-doc recall, incorrect-write rate and drift rate |
| Efficiency | Effective duration, conversation turns and tool/token cost by task class |
| Recoverability | Interrupted fixtures resumed without repeating completed decisions |

Aggregate averages must not hide a failure in one task class. Results are reported separately for Fast, Standard and Strict work.
