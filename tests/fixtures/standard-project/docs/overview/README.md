# 项目总览

本目录用于回答：项目做什么、业务如何运转、系统如何组织、采用什么技术以及当前做到什么程度。


## 文件索引

| 文件 | 内容 | 什么时候读取 |
|---|---|---|
| [`product.md`](./product.md) | 项目目标、用户、核心能力和范围 | 理解项目背景时 |
| [`domain-model.md`](./domain-model.md) | 业务实体、关系、状态和核心规则 | 修改业务逻辑时 |
| [`architecture.md`](./architecture.md) | 系统模块、依赖、边界和核心链路 | 修改系统结构时 |
| [`technical-stack.md`](./technical-stack.md) | 技术栈、测试、构建和部署方式 | 开发或排障环境问题时 |
| [`implementation-status.md`](./implementation-status.md) | 已实现、未实现、风险和下一步 | 继续已有任务时 |

## 维护规则

### 命名规则

以上五个文件名称和数量固定，不为单个模块新增 overview 文档。

### 更新规则

项目目标变化时更新 `product.md`；业务模型变化时更新 `domain-model.md`；系统边界变化时更新 `architecture.md`；技术选型变化时更新 `technical-stack.md`；功能进度变化时更新 `implementation-status.md`。

## 文档结构

`product.md` 包含项目目标、目标用户、核心能力和非目标。

`domain-model.md` 包含业务实体、实体关系、状态流转和关键规则。

`architecture.md` 包含系统边界、模块职责、外部依赖和核心链路。

`technical-stack.md` 包含语言、框架、存储、测试、构建和部署方式。

`implementation-status.md` 包含已完成、部分完成、待完成、风险和最后更新时间。
