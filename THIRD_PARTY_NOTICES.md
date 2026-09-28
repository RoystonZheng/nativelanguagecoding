# 第三方声明

AI Native DevKit 的研发流程设计借鉴或参考以下开源项目。相关项目不对本插件提供背书。

## Superpowers

- 项目：https://github.com/obra/superpowers
- 作者：Jesse Vincent 与 Prime Radiant
- 许可证：MIT License
- 打包来源版本：`superpowers@6.3.0`
- 复用文件：`skills/brainstorming/SKILL.md`
- 复用章节：`Understanding the idea`、`Exploring approaches`、`Presenting the design`、`Design for isolation and clarity`、`Working in existing codebases`

```text
MIT License

Copyright (c) 2025 Jesse Vincent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Matt Pocock Skills

- 项目：https://github.com/mattpocock/skills
- 作者：Matt Pocock
- 许可证：MIT License
- 打包来源提交：`6654f6b60cd9d5be8b54c6fafe44346dabeb3b76`
- 参考或复用文件：`skills/engineering/to-tickets/SKILL.md`、`skills/engineering/implement/SKILL.md`、`skills/engineering/tdd/SKILL.md`、`skills/engineering/tdd/tests.md`、`skills/engineering/tdd/mocking.md`、`skills/engineering/code-review/SKILL.md`、`skills/engineering/diagnosing-bugs/SKILL.md`、`skills/engineering/diagnosing-bugs/scripts/hitl-loop.template.sh`
- 采用机制：tracer-bullet 纵向切片、公共 seam 行为测试、focused checks、Spec/Standards 双轴评审；Debug 直接打包反馈回路、复现/最小化、假设/探针、回归修复和清理方法

```text
MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
