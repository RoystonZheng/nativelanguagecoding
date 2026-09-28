# Skill selection

## Decision rule

Each feature is labeled by evidence type:

- **Direct A/B**: a comparable experiment supports the selection.
- **Hybrid**: experiments or qualitative strengths conflict; the plugin combines mechanisms.
- **Adopted mechanism**: useful design, not independently evaluated.
- **Custom**: required by the product/docs architecture rather than chosen from the two projects.
- **Unresolved**: evidence is insufficient for a final selection.

The plugin implements these mechanisms under its own namespace and contracts. It does not require both upstream plugins at runtime.

This document records mechanism choices and their delivery status. The 0.2
runtime implements the Init kernel; Current 0.4.0 implements the Git requirement
handoff. Current Plan and Execute are prompt-Skill contracts; complete downstream
Design/Verify/Docs contracts and durable PlanDoc/cursor recovery remain Planned
V1 unless stated otherwise. No ExecutionEngine interface has been selected.

## Selection matrix

| Feature | Plugin decision | Source mechanisms | Evidence type | Confidence |
|---|---|---|---|---|
| `$sop-init` and context | `ContextCatalog + InitEngine` with Bootstrap/Adapt/Refresh | Internal docs design | Custom | Init kernel implemented; ContextCatalog runtime unverified |
| `$sop-clarify` | Reuse Superpowers 6.3.0 requirement-understanding behavior; retain DevKit source references and exact approval | Superpowers `brainstorming` / `Understanding the idea` | Later product decision informed by historical A/B | Current 0.4.0; upstream version pinned |
| `$sop-design` | Reuse Superpowers 6.3.0 solution-design wording; retain DevKit exact input and one final approval | Superpowers `brainstorming`; DevKit handoff and approval contracts | Adopted mechanism with DevKit adaptation | Current prompt Skill; persisted `DesignEngine` remains Planned V1 |
| `$sop-plan` | One approved DesignDoc becomes a detailed Markdown PlanDoc of ordered vertical slices with complete acceptance coverage | Matt `/to-tickets`, adapted to a self-contained PlanDoc | Historical A/B direction plus adopted contract | Current prompt Skill; no tracker or dependency graph |
| `$sop-execute` | Serial PlanDoc execution with public-seam TDD, focused/final checks, one candidate commit and independent Spec/Standards review | Matt `implement`, `tdd`, and `code-review`; DevKit top-level routing | Hybrid adopted mechanism | Current prompt Skill; no execution ledger or durable cursor |
| `$sop-debug` | Thin DevKit lifecycle adapter that automatically invokes a packaged copy of Matt `diagnosing-bugs`, then preserves DevKit Verify/Docs boundaries | Matt `diagnosing-bugs`; DevKit Runtime, Verify and Docs lifecycle | Later product decision despite unresolved A/B | Current prompt Skills; upstream commit pinned; comparative confidence remains low to medium |
| Test gate | Public-seam, observable-behavior vertical Red→Green | Matt `tdd` | Adopted mechanism | Needs isolated evaluation |
| Review gate | Independent Spec and Standards axes | Matt `code-review` | Adopted mechanism | Needs isolated evaluation |
| Verify gate | Fresh-command evidence before completion | Superpowers `verification-before-completion` | Adopted mechanism | Needs isolated evaluation |
| `$sop-sync-docs` | `DocsSyncEngine.plan/apply` with preview and conflict handling | Internal docs design | Custom | 0.3 automatic Git classifier + Current preview/Skill; transactional engine unverified |
| Product and real QA | No selection yet | To be researched | Unresolved | None |

## `$sop-clarify`

Current 0.4.0. Inspect project state, assess scope,
decompose oversized requests, and ask one purpose/constraint/success question
per message. Do not design or persist partial answers. After clarification,
write one minimal requirements record, request later-turn approval for its
exact `RequirementDocRef`, and complete Clarify only for that subject.

## `$sop-design`

**Current 0.4.0 input rule.**

Load only an explicitly supplied approved `RequirementDocRef`; never infer it
from Init, chat, repository recency, or historical workflow records. If source
or document drift is detected, return a bounded read-only comparison and
recommended next steps, then wait for explicit user direction; do not start
Design or Clarify automatically. `$sop-sync-docs` promotes durable decisions
with exact Git provenance and the existing semantic preview/approval gate. Old
external clarification state remains untouched and unsupported.

The design stage loads the exact approved requirements Markdown before it starts;
it does not repeat the requirement interview. Its solution-design behavior
reuses the Superpowers 6.3.0 `Exploring approaches`, `Presenting the design`,
`Design for isolation and clarity`, and `Working in existing codebases`
sections. It proposes 2–3 approaches with trade-offs, leads with a recommendation,
removes unnecessary features, scales each design section to its complexity, and
stays focused on changes that serve the current goal. Apply the same relevant
comparison dimensions to every option; include migration, rollout, rollback,
and documentation impact only when they apply.

Section check-ins are conversational feedback. After the complete design is
stable, the existing Runtime flow requests one final `design.solution`
approval. If a business ambiguity is discovered, explain it and wait for user
direction; do not automatically start Clarify or pick an interpretation merely
to make the design internally consistent.

## `$sop-plan`

The Current input is one complete approved DesignDoc. Plan translates it into a
detailed Markdown PlanDoc with source-design provenance, inherited constraints,
an acceptance-coverage table, ordered vertical slices, and Final integration.
Each behavior slice contains an observable outcome, Design basis, Touchpoints,
public seam, scenario, relevant Red, implementation actions, focused check,
expected result, and `Done when` condition.

Additional detail is included only when the approved DesignDoc makes it
applicable, for example:

- schema migration or backfill;
- authentication, authorization or secrets;
- cross-service ordering;
- irreversible or destructive operations;
- unfamiliar build/deploy tooling;
- transaction correctness or required operational ordering.

The slice order is the serial execution order. Plan does not publish tracker
tickets or expose a dependency graph, frontier, write-scope scheduler, or risk
score. The PlanDoc remains in the response or an already-ignored draft; a
caller-supplied approval digest records identity, not document storage.

## `$sop-execute`

Current `$sop-execute` consumes the complete approved PlanDoc and cited
DesignDoc, pins one Git baseline, preserves existing work, and executes slices
one at a time. Each behavior slice proves a relevant Red through the approved
public seam, reaches minimal Green, and runs focused checks.

After all slices, Execute runs Final integration, creates one local candidate
commit, and reviews the exact baseline-to-candidate diff on independent Spec and
Standards axes. Candidate changes invalidate affected checks and review. Execute
returns `ExecutionResult`; `$coding-sop` remains the only top-level workflow and
owns Verify, Docs Sync, and terminal `TaskOutcome`.

Durable per-slice cursor/recovery and cross-session PlanDoc selection remain
Planned V1. No public ExecutionEngine, centralized ledger, tracker frontier, or
concurrent work scheduler is selected.

## `$sop-debug`

E7/E8 do not establish a brand-level winner. Their comparative conclusion
remains unresolved and low to medium confidence.

A later product decision on 2026-08-28 selected a simpler Current composition:
the plugin packages Matt `diagnosing-bugs` as a self-contained, model-invoked
Skill, while `$sop-debug` remains a thin lifecycle adapter. The adapter owns the
typed Debug run, architecture/public-contract stop, downstream Verify, and the
automatic Docs Hook. The packaged method owns the
feedback loop, reproduction/minimization, ranked hypotheses, targeted probes,
correct-seam regression, focused fix, and cleanup.

This product choice does not upgrade the historical A/B evidence or select a
persisted DiagnosisEngine. Planned V1 can replace the internal method behind
the same `$sop-debug` lifecycle seam.

## Cross-cutting gates

TDD and review are used inside the applicable Execute or Debug work. Completion
verification is a downstream stage owned by `$coding-sop`; these mechanisms are
not competing top-level workflows.

- TestGate rejects a non-behavioral Red as proof of the bug.
- ReviewGate reports Spec and Standards independently.
- VerifyGate rejects stale results, inferred success and environment failures presented as passes.

## Licensing and provenance requirement

Before copying upstream text or code, record the exact repository, commit/version and license. Prefer reimplementation of workflow primitives and contracts over copying entire Skill files. Maintain a provenance note beside any directly derived asset.
