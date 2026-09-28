# Pitfalls

当前关键禁区：

- 不按仓库路径猜测最近 Workflow Task；
- 不把 task-local RequestedState 写成 CurrentState；
- 不把 prompt-driven Skill 描述成已完成的持久化 runtime；
- 普通任务不读取或扫描根 `handoff/`。

新增可复现陷阱时应记录症状、根因、正确做法和验证证据。
