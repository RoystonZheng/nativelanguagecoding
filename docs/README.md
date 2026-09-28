# 设计文档入口

本目录是 AI Native DevKit 的实现设计基线。中文读者先看 `方案总览.md`；编码和测试时再按下面的路由读取详细文档。

## 状态口径

Current 0.4.0 implements the exact approved Git requirements handoff.
The requirement/spec/plan files already under `docs/superpowers/` remain
versioned workflow records, not canonical CurrentState. The Current prompt
PlanDoc is different: it is returned in the task response or kept only as an
already-ignored draft, while the runtime may record only its caller-supplied
digest identity.

本文档集严格区分三种状态：

| 标记 | 含义 |
|---|---|
| **Current** | 已存在于当前插件中的显式 Skills，包括 DesignDoc 派生的 Markdown PlanDoc、串行 Execute/ExecutionResult、docs 工具、模板与只读校验器 |
| **0.2 implemented** | 已落入当前代码的版本化 JSON CLI、只读 InitEngine 和 TaskStateStore |
| **0.2.3 implemented** | Init 隐式 caller 跨仓隔离，以及 Init 选择、读权限和文档写入必须等待后续用户消息的确认门禁 |
| **0.3 implemented** | 插件内置 Collector Hook、自动 Execution Trace、Runtime 事件和验证后的 Docs Hook |
| **0.4.0 implemented** | Superpowers-aligned requirement interview、最小 Git requirements 记录、精确 Trace 审批与 Design 加载门禁 |
| **Historical clarification** | 0.2/0.2.3 的 ClarificationCheckpoint / ClarificationResult 和 baseline 审批契约；外部状态不迁移、不删除，但不再支持 |
| **Planned V1** | 尚未完整实现的 WorkflowRuntime、ContextCatalog、自动 Fast/Standard/Strict 路由、结构化 Design/Verify/Docs 契约，以及未预选 ExecutionEngine 的 PlanDoc 跨会话选择和 cursor/recovery |

`docs/superpowers/` 保存带显式状态的 workflow requirement/spec/plan 记录，包括历史、
RequestedState 和 Implemented 材料；它不是当前设计事实源。根目录
`handoff/` 是只有显式调用才能读取/更新的人类派生视图；普通任务和
docs 同步不得把它当作项目事实源。

## 阅读路由

| 任务 | 优先读取 |
|---|---|
| 快速了解整体方案 | `方案总览.md` |
| 理解产品范围 | `product-and-scope.md`、`skill-selection.md` |
| 实现内部模块 | `architecture.md`、`contracts.md`、相关 ADR |
| 实现命令或阶段门禁 | `workflow.md`、`contracts.md` |
| 实现当前 clarification/requirements handoff | `workflow.md`、`contracts.md`、ADR 0006 |
| 实现上下文或 docs 同步 | `context-and-docs.md`、ADR 0002、ADR 0006；ADR 0005（Historical）仅用于追溯已移除契约 |
| 追溯 Skill 选型原因 | `skill-selection.md`、`evaluation-evidence.md` |
| 选择下一项开发任务 | `roadmap-and-validation.md` |

## 文件索引

| 文件 | 内容 |
|---|---|
| [`方案总览.md`](方案总览.md) | 中文总体方案和开发入口 |
| [`product-and-scope.md`](product-and-scope.md) | 产品定位、用户、范围、非目标和价值 |
| [`skill-selection.md`](skill-selection.md) | 各功能采用的机制和置信度 |
| [`architecture.md`](architecture.md) | 模块、接口、seam、adapter 和控制流 |
| [`workflow.md`](workflow.md) | 当前任务意图路由、Planned V1 流程档位和生命周期门禁 |
| [`context-and-docs.md`](context-and-docs.md) | ContextCatalog、来源优先级和文档晋升 |
| [`contracts.md`](contracts.md) | 阶段间数据契约和不变量 |
| [`evaluation-evidence.md`](evaluation-evidence.md) | 量化评测证据和方法局限 |
| [`roadmap-and-validation.md`](roadmap-and-validation.md) | P0/P1/P2 实现顺序和验收测试 |
| [`decisions/`](decisions/README.md) | 已接受决策及其后果 |

兼容 `$sop-init` 的项目文档分类索引位于
[`overview/`](overview/README.md)、[`references/`](references/README.md)、
[`design/`](design/README.md)、[`api/`](api/README.md)、
[`runbooks/`](runbooks/README.md)、[`pitfalls/`](pitfalls/README.md) 和
[`superpowers/`](superpowers/README.md)。这些索引指向本项目的 canonical
设计基线或明确标注的历史材料。

## 维护规则

- 只有出现独立、长期稳定的职责时才新增文档。
- 文件新增、删除或改名时同步更新本索引。
- 执行过程、未完成任务状态和临时 TODO 不进入本目录。
- 外部来源尽量保留稳定 resourceId、URL、版本和同步时间。
- 新增能力必须标明属于 Current、已实现版本还是 Planned V1，不能把目标契约写成已经可运行的能力。
