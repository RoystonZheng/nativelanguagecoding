# Evaluation evidence

> Evidence snapshot: 2026-08-23. The original evaluation artifacts were produced
> before this public repository was prepared. Treat this file as a summarized
> historical decision record unless and until public, reproducible fixtures are
> added.

## Source index

| ID | Source | Used for |
|---|---|---|
| P0 | Original plugin proposal summary | Product scope, docs architecture, init and sync concepts |
| P1 | Skill selection and overall design summary | Consolidated feature decisions and architecture |
| E0 | Historical evaluation corpus summary | Evaluation corpus |
| E2 | Clarification and planning study summary | `$sop-clarify` and `$sop-plan` |
| E3 | Solution design study summary | `$sop-design` |
| E4 | Implementation planning study summary | Cross-project `$sop-plan` evidence |
| E5 | Staged execution study 1 summary | Centralized orchestration strengths |
| E6 | Staged execution study 2 summary | Ticket gates and early review strengths |
| E7 | Debug task/report 1 summary | Debug protocol; no reliable completed comparison |
| E8 | Debug task/report 2 summary | Directional debug evidence and limitations |
| C1 | Context input strategy summary | ContextCatalog and source routing |
| C2 | Standard development flow summary | Stage lifecycle and gates |

## Measured conclusions

### Requirement clarification

In the full-PRD E2 experiment both candidates covered 32/32 required items with zero incorrect assumptions and the same 4.3 subjective mean. Matt took 53 dialogue rounds versus Superpowers' 84, reducing interaction by 31 rounds, about 37%. A narrower historical E2 case also favored Matt on coverage, 87.5% versus 62.5%.

Historical evaluation-era decision: Matt-style clarification is the default,
confidence medium. It was superseded by the Current 0.4.0 product decision below.

Later product decision (2026-08-27; implemented and verified in 0.4.0 on
2026-08-28): despite the historical A/B measurement, the Current clarification
flow reuses Superpowers 6.3.0 requirement-understanding behavior and retains
DevKit source references plus exact approval. This does not alter the recorded
measurement.

### Solution design

E3 recorded Matt at 13/14 required design items with no blocking design issue, and Superpowers at 11/14 with a blocking lifecycle issue. Superpowers explained alternatives and trade-offs more clearly and received a higher subjective mean, 4.00 versus 3.67. Neither candidate passed strict acceptance.

Decision: hybrid design, confidence medium; the hybrid itself must be evaluated.

### Implementation planning

In full-PRD E2, Superpowers covered 32/32 and Matt 31/32, a 3.1 percentage-point gap below the experiment's materiality threshold. Matt produced 14 vertical tickets in 25m38s with no new unresolved design decisions; Superpowers ran 3h03m44s and produced a 1,998-line plan with seven new decision classes.

E4 provided cross-project support: both covered 17/17, Matt's 7/7 tickets were executable, while one of Superpowers' 14 tasks contained an invalid build path. Matt took 10m02s versus 48m31s.

Decision: `/to-tickets` style by default, with optional high-risk drill-down.

### Staged execution

E5 favored Superpowers: both passed the task, while its centralized process and evidence were easier to control. E6 favored the Matt-style process: both scored 18/20, but Matt found issues earlier and had slightly fewer rework rounds; it also required substantially more manual advancement.

Decision: no complete upstream workflow wins. Use a centralized plugin ledger plus Ticket-level test and review gates. Confidence medium-low to medium.

### 2026-08-28 design supersession

ADR 0007 supersedes the two design conclusions above without rewriting their
experimental observations. E2/E4 still support concise vertical slicing and
complete acceptance coverage; they do not establish that a public dependency
graph, tracker frontier, or write-scope scheduler is necessary. E5/E6 still
support explicit test/review stops and a single plugin-owned top-level workflow;
they do not establish a durable execution ledger or concurrent scheduler.

The Current adaptation is therefore one detailed DesignDoc-derived Markdown
PlanDoc with ordered vertical slices, followed by serial Execute and one
baseline-to-candidate Spec/Standards review. Durable cursor/recovery remains a
separate Planned hypothesis.

### Debugging

E7 did not provide a reliable completed selection. E8 directionally favored Superpowers on evidence quality and change scope, but the later inputs diverged, the total-time difference was small, final changes were cumulative rather than isolated, and there was only one usable sample. Separate clean debug work also demonstrated the risk of both candidates overfitting a single production fixture.

Decision: no final winner. Implement and evaluate the shared diagnosis protocol. Confidence low to medium.

Later product decision (2026-08-28): despite the unresolved comparison,
Current Debug packages Matt `diagnosing-bugs` and uses `$sop-debug` as a thin
DevKit lifecycle adapter. This is a simplicity and composition decision, not
new comparative evidence; confidence in the A/B selection remains low to
medium.

## Evidence classification

The following are not established A/B winners:

- TestGate based on Matt TDD;
- ReviewGate based on Matt dual-axis review;
- VerifyGate based on Superpowers completion verification;
- ContextCatalog, TaskStateStore and DocsSyncEngine;
- Fast/Standard/Strict automatic routing;
- the combined `$sop-design` and `$sop-execute` workflows.

They are engineering hypotheses that require implementation-level tests and, where material, controlled evaluation.

## Known methodological risks

- Most functions have only one or two project samples.
- Some studies were non-blind and used a fixed candidate order.
- Tooling, model effort and sub-agent usage were not always symmetric.
- A passing final state does not prove which cumulative change fixed a problem.
- Dialogue count can reward terse but incomplete behavior unless coverage remains a hard gate.
- Reading a Skill is not the same as executing its intended workflow.
- Future upstream Skill versions may differ from the evaluated snapshot.

## Release-evidence rule

No selection is upgraded in confidence without:

1. a frozen task and acceptance oracle;
2. isolated, equivalent repositories and inputs;
3. exact Skill version/commit recording;
4. equal tools, model and permission profile;
5. original-scenario feedback loops for both candidates;
6. blind or independent final review;
7. raw counts and denominators, not only summary scores;
8. attribution or ablation for the claimed key fix;
9. explicit accounting for human corrections and rework.
