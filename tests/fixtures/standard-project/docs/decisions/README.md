# 决策记录

本目录记录已经确定的重要技术或业务决策，用于说明为什么选择当前方案。

决策记录只说明已经批准的选择及其理由，不替代需求、API 契约或实现计划。被批准或提出的
决策不等于代码已经实现对应行为。

## 决策索引

| ADR | 状态 | 决策摘要 |
|---|---|---|
| `0001-<short-title>.md` | Accepted | 一句话说明最终决策 |

## 维护规则

### 命名规则

ADR 使用 `NNNN-short-title.md`，编号递增且不重复。

### 新增和更新规则

只有方案难以回退、存在明显取舍或会长期影响项目时才新增 ADR。决策被替代时保留原文件，将状态改为 `Superseded` 并链接新 ADR。

### 从任务产物晋升决策

当 `$sop-sync-docs` 把已批准的需求工作记录晋升为 canonical 决策时使用以下模板。不是从需求
工作记录晋升的架构 ADR 可以沿用项目既有格式；不得为了满足模板而伪造来源信息。

```markdown
---
status: accepted
state_class: RequestedState
implementation_status: not_implemented
source_requirement_path: docs/superpowers/requirements/2026-08-27-login-requirements.md
source_requirement_commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
source_requirement_blob_digest: git-sha1:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
---

# NNNN. Decision Title

## Status

Accepted | Superseded | Deprecated

## Context

Background, constraints, and trigger.

## Decision

Chosen approach.

## Consequences

Benefits, costs, and follow-up ownership.

## Alternatives Considered

Options not selected and why.
```

批准的需求或设计尚未通过代码证据验证时，必须使用 `RequestedState` 和 `not_implemented`。
只有仓库证据证明行为已经实现时，才能使用 `CurrentState` 和 `implemented`。保留精确的需求
文档 Git 路径、commit 和 blob identity，后续任务即可审计来源。

## ADR 模板

未从任务产物晋升的 ADR 至少包含 `Status`、`Context`、`Decision`、`Consequences`、
`Alternatives Considered` 和 `Related Docs`。
