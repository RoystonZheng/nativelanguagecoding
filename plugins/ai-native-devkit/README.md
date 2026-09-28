# AI Native DevKit

AI Native DevKit 是一个面向 Codex 的结构化软件交付插件，适用于普通 Git
仓库和公开团队工作流。它不依赖私有代码托管、内部文档系统或专有发布平台。

Current 0.4.0 让 Clarify 复用 Superpowers 6.3.0 的需求理解行为，提交一份最小
Git requirements 记录，并通过 Execution Trace 将后续回合审批绑定到精确 Git
identity；Design 只读取显式提供的已批准 `RequirementDocRef`。`0.3.0` 新增的插件内置
Collector Hook、自动 Execution Trace 和验证后的 Docs Hook，以及 Init 的
`0.2.3` 跨仓隔离和跨回合确认门禁继续保留。旧 clarification checkpoint/result
流程已成为 Historical，外部历史状态保持原样但不再支持。

## 安装

在 Marketplace 仓库根目录执行校验、注册本地 Marketplace 并安装插件：

```bash
python3 scripts/validate_all.py
codex plugin marketplace add "$(pwd)"
codex plugin add ai-native-devkit@ai-native-devkit
```

首次启用后，在 Codex 中打开 `/hooks`，审核并信任来自 `ai-native-devkit` 的 Hook。
信任按 Hook 内容 hash 保存；插件升级导致 Hook 内容变化时需要重新审核。信任后无需启动
后台服务，也无需逐任务开启 Trace。Hook 会收到 Codex 生命周期回调，但只有 DevKit Runtime
发出 `workflow.started` 激活当前 Session 后才持久化事件；没有使用本插件的 Session 不创建
Execution Trace。

卸载插件：

```bash
codex plugin remove ai-native-devkit@ai-native-devkit
```

## 调用方式

使用 `$coding-sop` 处理完整研发任务，或者显式调用：

- `$sop-init`
- `$sop-clarify`
- `$sop-design`
- `$sop-plan`
- `$sop-execute`
- `$sop-debug`
- `$diagnosing-bugs`
- `$sop-verify`
- `$sop-sync-docs`

`$sop-debug` 是 DevKit 生命周期适配器，会调用内置 `$diagnosing-bugs` 完成反馈回路、
根因定位、回归测试和聚焦修复。直接调用 `$diagnosing-bugs` 只运行调试方法，不包含
DevKit Runtime、Verify 和 Docs Hook 链路。

## 用户决定优先

用户可以明确跳过整个阶段，也可以只忽略当前阻塞项。AI 会通过
`workflow.user_decision` 记录本次决定并继续，不要求重复确认。Trace 保留跳过、未执行和失败的实际结果，
不会伪造审批、Init 就绪状态或测试通过；最终可显示 `completed_with_exceptions`。

## 默认语言与快照范围

所有 Skill 默认使用简体中文交流并生成文档，包括标题、章节、正文、来源说明及实施计划。
用户明确指定语言时按其要求输出。代码标识符、命令、路径、JSON 字段和精确 Git 引用保持原样。

Init 的 `RepositoryRevision` 和需求写入的仓库保护快照只纳入 Git 已跟踪内容，排除所有未跟踪文件，
包括被忽略的依赖和构建产物。

## 开发流程与 Skill

`$coding-sop` 会先分类任务意图和流程强度：

| 意图 / 强度 | 兼容 route | 场景 |
|---|---|---|
| `development + fast` | `lightweight` | 行为明确、局部、低风险 |
| `development + standard/strict` | `development` | 新行为、歧义、跨模块、架构或高风险变更 |
| `debug + fast/standard/strict` | `debug` | Bug、失败、回归或性能异常 |

当前 development 流程为：

```text
$sop-init -> $sop-clarify -> $sop-design -> $sop-plan -> $sop-execute -> $sop-verify -> $sop-sync-docs
```

`$sop-clarify` 完成访谈后通过 `requirements.write` 提交最小 requirements 文档，并返回精确
`path`、`commit` 和 `blob_digest`。Runtime 请求该引用的审批；`$sop-design` 启动前只通过
`requirements.load` 加载同一已批准引用。内容或来源漂移会回到显式用户决策，不会猜测替代物。

`$sop-plan` 把完整批准的 DesignDoc 翻译成详细 Markdown PlanDoc。`$sop-execute`
按切片串行完成行为优先实现和 focused/final checks，创建一个 candidate commit，完成
Spec/Standards 双轴评审后返回 `ExecutionResult`。Verify、Docs Sync 和最终
`TaskOutcome` 仍由 `$coding-sop` 顶层流程负责。

## 自动 Execution Trace

插件中的 `hooks/hooks.json` 监听 Session、Turn、Tool、Permission、Compact、Subagent 和
Stop 生命周期。`scripts/trace_collector.py` 自动把 Codex Hook 输入转换为完整、追加写入的事实事件，
但在插件工作流激活前保持无写入；普通 Codex 任务不会生成 Trace。

默认记录位于：

```text
~/.codex/state/ai-native-devkit/v1/execution-traces/<trace_id>/
├── metadata.json
├── events.jsonl
└── summary.json
```

`events.jsonl` 每行是完整事件；`summary.json` 是确定性投影。Trace 不保存完整提示词、
完整回复、原始命令/工具输出、源码、凭证、隐藏思考或人工评测真值。

## 自动 Docs Hook

`$sop-verify` 把新鲜验证结果提交到 `runtime_cli.py` 的 `verification.complete`。只有验证通过
才会在同一个程序调用中触发 Docs Hook。Hook 从 Git baseline、HEAD、工作区和未跟踪文件
自动得到 changed paths，然后输出 `NO_CHANGE`、`DETERMINISTIC`、`SEMANTIC_REVIEW` 或
`CONFLICT`。

普通 Bug、测试补充、内部重构和临时状态仍会经过后台的低成本分类，但结果为
`NO_CHANGE`，不写文档，也不询问用户。语义文档修改必须先给出完整预览并取得确认。

## 文档边界

`docs/` 是面向 Agent 的项目知识。Human-facing Handoff 文档由用户自行管理；插件不再提供
相关 Skill、模板、扫描、迁移提示、审批或路径拦截，也不询问是否更新。

受支持的任务请求、状态转换、Init 报告和证据写入仓库外 TaskStateStore，不直接污染 canonical docs。
完成的 clarification requirements 写入 `docs/superpowers/requirements/` 并保留精确 Git
identity；它们是 workflow records，不是 canonical CurrentState。适合跨任务复用的批准决策
可经完整语义预览晋升到 `docs/decisions/`，并保留精确 requirement Git provenance。

## 本地开发更新

修改本地插件源码后，更新缓存标识并重新安装：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/read_marketplace_name.py" \
  --marketplace-path .agents/plugins/marketplace.json
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py" \
  plugins/ai-native-devkit
codex plugin add ai-native-devkit@ai-native-devkit
```

Cachebuster 只用于本地开发；正式版本使用干净 SemVer。重新安装后应在新 Codex 任务验证更新。

## 当前验证范围

Current 0.4.0：Clarify 产出 Git requirements 记录，Design 只读取显式的已批准精确引用。

- `python3 scripts/validate_all.py` 运行单元、契约、集成和插件结构校验。
- Runtime 覆盖 Artifact contract、TaskStateStore 原子性/幂等/并发/损坏拒绝、持久化安全、
  Git repository inspection 与 init CLI。
- Requirement runtime 覆盖最小文档、单文件 Git commit、脏工作区保护、SHA-1/SHA-256、
  精确 approval subject、修改后失效、跨会话精确引用、来源漂移和 Design 加载门禁。
- Execution Trace 覆盖完整事件结构、1:1 Session 映射、并发追加、脱敏、Host/Runtime 来源、
  捕获状态、跨进程 Hook CLI 和确定性 summary。
- Docs Hook 覆盖 Git changed paths、验证后自动触发、普通变更静默、语义确认信号，以及不产生 Handoff 联动。

## 0.4.0 版本边界

0.4.0 implemented 的边界是：Superpowers-aligned requirement discovery、一个最小 Git
workflow record、精确 Trace approval，以及 Design 对显式批准 `RequirementDocRef` 的加载门禁。
它不表示完整 Planned V1 WorkflowRuntime、ContextCatalog、自动 risk-tier scoring、持久
PlanDoc cursor 或事务型 DocsSyncEngine 已经实现。

## Historical 0.3.0 版本边界

`0.3.0` 新增插件内置 Collector Hook、自动 Execution Trace、Runtime 事件和验证后的 Docs Hook。
它不再包含旧 evaluation oracle，也不恢复已移除的 Handoff 自动化能力。Historical
clarification checkpoint/result 状态可保留读取边界，但新流程不再支持或迁移该契约。
