---
name: sop-plan
description: Turn one approved technical DesignDoc into a detailed, ordered implementation PlanDoc that another agent can execute without redesigning the solution.
---

# SOP Plan

Read [user-direction.md](../coding-sop/references/user-direction.md) before applying this Skill.
Explicit user skips and blocker waivers take precedence over this Skill's
normal stop/approval rules; record them once and continue the adjusted work.

Read [output-language.md](../coding-sop/references/output-language.md) before generating user-facing text or documents.

Input: the complete approved DesignDoc from `$sop-design`, its
`design_document` SHA-256 digest, and its exact requirements provenance and
approval evidence. A bare path, a chat summary, or an unapproved draft is not
sufficient.

This workflow adapts Matt Pocock's vertical-slice planning guidance. Read
[upstream-matt-to-tickets.md](references/upstream-matt-to-tickets.md) for the
pinned source, deliberate adaptations, and license provenance. The packaged
Skill is self-contained.

## Start from the approved design

1. Resolve `PLUGIN_ROOT` from this Skill directory as `../..` and call
   `python3 "$PLUGIN_ROOT/scripts/runtime_cli.py"` operation `stage.start` with
   `stage: plan`, the repository root, and `source_subject_digest` equal to the
   approved DesignDoc digest. Retain `stage_run_id`; do not narrate this internal
   transition. Runtime rejects a digest that is not the completed Design output
   for this repository.
2. Read the complete approved DesignDoc and the minimum relevant repository
   context. Confirm that the design has no unresolved product, scope, interface,
   migration, or authority decision. Planning translates the design; it does
   not choose a new solution.
3. If the repository now contradicts a material design assumption, or an
   implementer would still need to make a material design decision, call
   `stage.fail` for the retained run with `error_code: plan.design_gap`, then
   report the exact gap. The calling workflow stops and does not continue to
   Execute. Do not hide the decision inside an implementation step. A revised,
   approved DesignDoc starts a new Plan run.

## Write the PlanDoc

Produce one Markdown PlanDoc with these sections. This is the default Simplified
Chinese template; when the user specifies another language, translate the prose
labels while preserving contract identifiers.

```markdown
# <变更主题>实施计划

**来源设计：** <design_document 的 SHA-256 摘要、审批 ID，以及精确的 RequirementDocRef 来源>

## 目标

<用户或系统可观察到的结果。>

## 设计约束

- <继承自 DesignDoc 的接口、不变量、兼容性要求和明确排除的范围。>

## 验收覆盖

| 设计要求 | 实现任务 | 验证方式 |
|---|---|---|
| <需求或设计章节> | 任务 1 | <聚焦验证或最终检查> |

## 任务 1：<可独立观察的结果>

**预期结果：** <完成后能够证实的行为>

**设计依据：** <本任务落实的 DesignDoc 章节、接口或决策>

**涉及位置：**
- 修改：`<已确认的模块或路径>` — <职责>
- 测试：`<已确认的测试路径或公共接口>` — <覆盖行为>

**先写测试：**
- 公共接口：<用于观察行为的接口>
- 场景：<一个具体行为>
- 预期失败：<缺失该行为时产生的相关失败>

**实现步骤：**
1. <具体实现动作，以及需要保持的设计约束>
2. <下一项必要动作；不加入推测性的能力>

**验证：**
- 执行：`<准确的聚焦验证命令或确定性场景>`
- 预期：<可观察的结果、退出状态或断言>

**完成条件：** <当前任务的完成标准>

## 最终集成验证

- 执行：`<相关完整测试集、类型检查、构建或静态检查命令>`
- 预期：<可观察的集成结果>
```

Plan rules:

- Use ordered vertical slices. Each slice delivers a complete observable result,
  contains its implementation and tests, and is small enough for one focused
  execution context.
- Map every material DesignDoc requirement to a slice or `最终集成验证`. The
  acceptance denominator must not silently shrink.
- For a behavior change, name the public seam, a concrete scenario, the relevant
  Red, and the focused verification. For a non-behavioral change, replace
  `先写测试` with a concise reason and a deterministic check.
- Include exact paths and symbols when repository inspection makes them reliable.
  Treat `涉及位置` as implementation guidance rather than permission to ignore
  adjacent changes required by the approved design.
- Keep implementation steps specific enough that `$sop-execute` does not need to
  redesign the solution. Do not expand every slice into repeated generic
  test-run-commit boilerplate.
- Add migration, rollback, destructive-action, security, or manual checkpoint
  details only when the approved DesignDoc makes them applicable.
- Do not publish tracker tickets, create branches, edit production code, or begin
  execution during Plan.

## Approve and hand off

Save an optional task-local view at
`.scratch/ai-native-devkit/tasks/<task_id>/plan.md` only when that exact path is
already ignored by repository policy; verify the exact path with
`git check-ignore`. Otherwise present the complete PlanDoc in the response
without changing the repository or its ignore rules, and do not promote the
PlanDoc to canonical project docs.

Encode the exact complete PlanDoc Markdown as UTF-8 and compute
`sha256:<64 lowercase hex>`. Call `approval.request` with the retained run,
`stage: plan`, `approval_kind: plan.implementation`, and:

```json
{"subject":{"kind":"plan_document","digest":"sha256:<64 lowercase hex>"}}
```

Present the exact bytes identified by that digest and stop the current assistant
turn. On a later user response, call `approval.resolve` with the exact returned
`approval_id`. For `changes_requested`, revise the complete PlanDoc in the same
active run, compute a new digest, and request approval again. For `rejected`,
call `stage.fail` with `plan.user_rejected` and stop. Only
`decision: approved` permits `stage.complete` for that run; pass the same
`subject` again. Any PlanDoc edit creates a new digest and approval request.
Then select bundled `$sop-execute` with the complete approved PlanDoc and its
digest.

If planning fails after the run starts for any other reason, call `stage.fail`
once with a stable `plan.environment_blocked` or `plan.generation_failed` code.
Never leave a started Plan run without one terminal transition.

Output: the approved PlanDoc, its `plan_document` digest, its source-design
provenance, optional ignored view path, and `$sop-execute` as the selected
execution method.
