# AI Native DevKit Plugin v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and locally install version `0.1.0` of the `ai-native-devkit` Codex plugin from a team marketplace repository.

**Architecture:** Package nine focused Skills under one plugin manifest. Keep reasoning and orchestration in `SKILL.md` files, place reusable project artifacts beside the Skill that owns them, and use read-only Python standard-library validators for deterministic checks. Distribute the plugin through a repo marketplace named `ai-native-devkit`.

**Tech Stack:** Codex plugin manifest JSON, Agent Skills Markdown, Python 3.10+ standard library, `unittest`, Git, Codex plugin CLI.

**Spec:** `docs/superpowers/specs/2026-08-24-coding-sop-plugin-design.md`

## Global Constraints

- Plugin and marketplace names are exactly `ai-native-devkit`; initial version is exactly `0.1.0`.
- Public Skill names are exactly `coding-sop`, `sop-init`, `sop-clarify`, `sop-design`, `sop-plan`, `sop-execute`, `sop-debug`, `sop-sync-docs`, and `sop-handoff`.
- Public documentation uses `$skill-name`; `/init`, `/execute`, `/debug`, `/sync-docs`, and `/handoff` may appear only in migration notes.
- Runtime scripts use Python 3.10+ and the standard library only; they are read-only and emit machine-readable JSON on success.
- `docs/` is Agent-facing current knowledge; root `handoff/` is a human-facing derived map and never a `docs/` child.
- Version `0.1.0` has no lifecycle hooks, MCP server, app connector, public-directory publication, or non-Codex adapter.
- Every implementation task follows red-green-refactor and ends with an independently reviewable commit.

## File Map

- `.agents/plugins/marketplace.json`: team marketplace catalog and install policy.
- `plugins/ai-native-devkit/.codex-plugin/plugin.json`: plugin identity and bundled Skills entry point.
- `plugins/ai-native-devkit/skills/coding-sop/`: task router and shared workflow contract.
- `plugins/ai-native-devkit/skills/sop-init/`: project context initialization, templates, and docs validator.
- `plugins/ai-native-devkit/skills/sop-{clarify,design,plan,execute,debug}/`: development workflow stages.
- `plugins/ai-native-devkit/skills/sop-sync-docs/`: docs impact rules and change classifier.
- `plugins/ai-native-devkit/skills/sop-handoff/`: handoff workflow, static site template, and validator.
- `tests/`: manifest, Skill contract, template, classifier, validator, and fixture tests.
- `scripts/validate_all.py`: one-command local verification entry point.

---

## Execution Bootstrap

The marketplace directory is not yet a Git repository, so perform this one-time bootstrap before
starting `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

Create `.gitignore` with:

```gitignore
.DS_Store
.superpowers/
.worktrees/
__pycache__/
*.pyc
```

Then run from the `ai-native-devkit` root:

```bash
git init -b main
git add .gitignore docs/superpowers/specs docs/superpowers/plans
git commit -m "docs: add coding sop plugin design and plan"
```

Invoke `superpowers:using-git-worktrees`, create branch `feature/plugin-v0.1`, enter that isolated
workspace, and then start Task 1. The clean bootstrap commit is the review baseline.

---

### Task 1: Bootstrap the marketplace repository and plugin package

**Files:**
- Create: `.agents/plugins/marketplace.json`
- Create: `plugins/ai-native-devkit/.codex-plugin/plugin.json`
- Create: `plugins/ai-native-devkit/README.md`
- Create: `tests/__init__.py`
- Create: `tests/test_plugin_contract.py`

**Interfaces:**
- Produces: marketplace `ai-native-devkit` exposing plugin `ai-native-devkit` at `./plugins/ai-native-devkit`.
- Produces: manifest version `0.1.0` with `skills: "./skills/"`.

- [x] **Step 1: Verify the isolated workspace**

Run:

```bash
git branch --show-current
git status --short
```

Expected: the active branch is `feature/plugin-v0.1` and the worktree is clean.

- [x] **Step 2: Write the failing manifest and marketplace contract test**

```python
# tests/test_plugin_contract.py
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PluginContractTest(unittest.TestCase):
    def test_marketplace_exposes_coding_sop(self):
        data = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(data["name"], "ai-native-devkit")
        entry = data["plugins"][0]
        self.assertEqual(entry["name"], "ai-native-devkit")
        self.assertEqual(entry["source"]["path"], "./plugins/ai-native-devkit")
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
        self.assertEqual(entry["category"], "Developer Tools")

    def test_manifest_has_stable_identity(self):
        path = ROOT / "plugins/ai-native-devkit/.codex-plugin/plugin.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["name"], "ai-native-devkit")
        self.assertEqual(data["version"], "0.1.0")
        self.assertEqual(data["skills"], "./skills/")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 3: Run the test and verify the missing files fail**

Run: `python3 -m unittest tests.test_plugin_contract -v`

Expected: ERROR with `FileNotFoundError` for `.agents/plugins/marketplace.json`.

- [x] **Step 4: Scaffold the plugin and create the exact marketplace metadata**

Create `.agents/plugins/marketplace.json` with:

```json
{
  "name": "ai-native-devkit",
  "interface": { "displayName": "AI Native DevKit" },
  "plugins": []
}
```

Then run:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/create_basic_plugin.py" ai-native-devkit \
  --path ./plugins \
  --marketplace-path ./.agents/plugins/marketplace.json \
  --with-skills --with-marketplace \
  --category "Developer Tools"
```

Set the generated manifest identity to:

```json
{
  "name": "ai-native-devkit",
  "version": "0.1.0",
  "description": "Route, execute, verify, and document software delivery work with the team Coding SOP.",
  "author": { "name": "AI Native DevKit Maintainers" },
  "skills": "./skills/",
  "interface": {
    "displayName": "AI Native DevKit",
    "shortDescription": "Plan, build, debug, and document code",
    "longDescription": "A structured software delivery workflow covering task routing, context initialization, clarification, design, planning, execution, debugging, documentation synchronization, and human handoff maps.",
    "developerName": "AI Native DevKit Maintainers",
    "category": "Developer Tools",
    "capabilities": ["Interactive", "Read", "Write"],
    "defaultPrompt": [
      "Use the Coding SOP to handle this engineering task.",
      "Initialize this project's development context.",
      "Generate or refresh the project's handoff map."
    ],
    "brandColor": "#2563EB"
  }
}
```

Create `plugins/ai-native-devkit/README.md` with:

```markdown
# AI Native DevKit

Codex plugin source for the team software-delivery SOP. The complete installation,
invocation, development, and removal guide is added after the workflow contracts and
validation entry point are implemented.
```

Create `tests/__init__.py` with the single line `"""Coding SOP plugin tests."""` so focused
`python3 -m unittest tests.test_module` commands cannot resolve an unrelated installed package.

- [x] **Step 5: Run the contract test and official plugin validator**

Run:

```bash
python3 -m unittest tests.test_plugin_contract -v
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/validate_plugin.py" plugins/ai-native-devkit
```

Expected: both commands exit 0.

- [x] **Step 6: Commit the package foundation**

```bash
git add .agents plugins/ai-native-devkit tests
git commit -m "feat: scaffold coding sop plugin"
```

### Task 2: Define the shared Skill contract and task router

**Files:**
- Create: `plugins/ai-native-devkit/skills/coding-sop/SKILL.md`
- Create: `plugins/ai-native-devkit/skills/coding-sop/references/workflow-contract.md`
- Create: `tests/test_skill_contract.py`

**Interfaces:**
- Produces: route names `lightweight`, `development`, and `debug`.
- Produces: terminal result fields `route`, `verification`, `docsImpact`, `handoffSignal`, and `remainingRisks`.

- [x] **Step 1: Write the failing Skill discovery test**

```python
# tests/test_skill_contract.py
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/ai-native-devkit/skills"
EXPECTED = {
    "coding-sop", "sop-init", "sop-clarify", "sop-design", "sop-plan",
    "sop-execute", "sop-debug", "sop-sync-docs", "sop-handoff",
}


class SkillContractTest(unittest.TestCase):
    def test_existing_skills_have_matching_frontmatter_names(self):
        for path in SKILLS.glob("*/SKILL.md"):
            text = path.read_text()
            match = re.search(r"^name:\s*([^\n]+)$", text, re.MULTILINE)
            self.assertIsNotNone(match, path)
            name = match.group(1).strip()
            self.assertEqual(name, path.parent.name)

    def test_router_skill_exists(self):
        self.assertTrue((SKILLS / "coding-sop/SKILL.md").is_file())

    def test_public_docs_do_not_advertise_legacy_slash_commands(self):
        legacy = re.compile(r"(?<!migration: )/(init|execute|debug|sync-docs|handoff)\b")
        for path in SKILLS.glob("**/*.md"):
            self.assertIsNone(legacy.search(path.read_text()), path)
```

- [x] **Step 2: Run the test and verify it fails on the missing router**

Run: `python3 -m unittest tests.test_skill_contract -v`

Expected: FAIL because `coding-sop/SKILL.md` does not exist after scaffolding.

- [x] **Step 3: Write the router Skill and workflow contract**

The router `SKILL.md` must contain this frontmatter and routing contract:

```markdown
---
name: coding-sop
description: Route and manage software delivery work using the team Coding SOP. Use when a user asks to apply the SOP, handle an engineering task end to end, or choose the appropriate development workflow.
---

# Coding SOP Router

1. Read `references/workflow-contract.md`.
2. Inspect the task and minimum relevant project context.
3. Select exactly one initial route: lightweight, development, or debug.
4. State the route and one-sentence reason.
5. Invoke only the Skills required by that route.
6. Do not claim completion without fresh verification and a docs-impact conclusion.
```

Create `references/workflow-contract.md` with:

````markdown
# Workflow Contract

| Route | Select when | Stages |
|---|---|---|
| `lightweight` | The change is local, low risk, and behavior is already specified. | Select context, implement, verify, conclude docs impact. |
| `development` | The task adds behavior, crosses modules, is ambiguous, or changes architecture. | Clarify, design, plan, execute, verify, sync docs. |
| `debug` | The user reports a bug, failure, regression, or performance symptom. | Reproduce, isolate root cause, add a regression test, fix, verify, conclude docs impact. |

Skill dispatch is exact:

- `lightweight`: the router handles the bounded task directly, then invokes `$sop-sync-docs`
  only when durable knowledge may have changed.
- `development`: invoke `$sop-clarify`, `$sop-design`, `$sop-plan`, then `$sop-execute`.
- `debug`: invoke `$sop-debug`; it invokes `$sop-sync-docs` only when required.

Every terminal result contains:

```json
{
  "route": "lightweight | development | debug",
  "verification": ["fresh command and result"],
  "docsImpact": "NO_CHANGE | DETERMINISTIC | SEMANTIC_REVIEW | CONFLICT",
  "handoffSignal": "NO_IMPACT | POSSIBLE_IMPACT | UPDATE_RECOMMENDED",
  "remainingRisks": []
}
```

`handoffSignal` reuses the final diff and docs-impact evidence. It is only a lightweight
classification. Do not read or write `handoff/` unless the user explicitly invokes
`$sop-handoff` or approves the proposed check.
````

- [x] **Step 4: Run the Skill contract tests**

Run: `python3 -m unittest tests.test_skill_contract -v`

Expected: PASS.

- [x] **Step 5: Commit the router contract**

```bash
git add plugins/ai-native-devkit/skills tests/test_skill_contract.py
git commit -m "feat: add coding sop router contract"
```

### Task 3: Build the docs template and read-only validator

**Files:**
- Create: `plugins/ai-native-devkit/skills/sop-init/assets/AGENTS.md`
- Create: `plugins/ai-native-devkit/skills/sop-init/assets/docs-template/**/README.md`
- Create: `plugins/ai-native-devkit/skills/sop-init/scripts/validate_project_docs.py`
- Create: `tests/test_docs_template.py`

**Interfaces:**
- Produces CLI: `validate_project_docs.py PROJECT_ROOT`.
- Emits JSON: `{"valid": bool, "missing": list[str], "brokenLinks": list[str]}`.

- [x] **Step 1: Write failing template and validator tests**

```python
# tests/test_docs_template.py
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/ai-native-devkit/skills/sop-init"
REQUIRED = {"overview", "references", "decisions", "design", "api", "runbooks", "pitfalls", "superpowers"}


class DocsTemplateTest(unittest.TestCase):
    def test_template_has_required_entries_and_no_handoff_child(self):
        template = SKILL / "assets/docs-template"
        actual = {p.name for p in template.iterdir() if p.is_dir()}
        self.assertEqual(actual, REQUIRED)
        self.assertFalse((template / "handoff").exists())
        for name in REQUIRED:
            self.assertTrue((template / name / "README.md").is_file())

    def test_validator_rejects_blank_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), tmp],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(payload["valid"])
            self.assertIn("docs/README.md", payload["missing"])
```

- [x] **Step 2: Run the tests and verify missing assets fail**

Run: `python3 -m unittest tests.test_docs_template -v`

Expected: ERROR or FAIL because `assets/docs-template` and the validator do not exist.

- [x] **Step 3: Create the canonical templates**

Resolve the source checkout root first:

```bash
SOURCE_ROOT="$(cd "$(git rev-parse --git-common-dir)/../.." && pwd -P)"
```

Use `$SOURCE_ROOT/docs-template` as the content source. Copy only `README.md`,
`overview`, `references`, `decisions`, `design`, `api`, `runbooks`, `pitfalls`, and
`superpowers`; do not copy `.DS_Store` or `handoff`. Replace the root template index with
exactly those eight child links. Each child `README.md` must start with its title (`# Overview`,
`# References`, `# Decisions`, `# Design`, `# API`, `# Runbooks`, `# Pitfalls`, or `# Superpowers`),
`## Purpose`, and `## Files`; `## Files` is a Markdown table with `File`, `Summary`, and
`Updated` columns and may initially have no data rows.

Create `assets/AGENTS.md` with:

````markdown
# Project Knowledge

`docs/` is the Agent-facing source of current project knowledge.

1. Open `docs/README.md` and select only sections relevant to the task.
2. Read a child `README.md` before reading documents indexed by that child.
3. Treat code, configuration, tests, and verified runtime behavior as stronger evidence than prose.
4. Invoke `$sop-sync-docs` when a completed task changes durable project knowledge.
5. `$sop-sync-docs` never creates, moves, reads, or updates root `handoff/`.

Root `handoff/` is a human-facing derived map. Use `$sop-handoff` only after explicit
invocation or user approval.
````

- [x] **Step 4: Implement the read-only validator**

Create `validate_project_docs.py` with this public interface and implementation:

```python
#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

REQUIRED = (
    "overview", "references", "decisions", "design",
    "api", "runbooks", "pitfalls", "superpowers",
)
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def validate(project_root: Path) -> dict:
    project_root = project_root.resolve()
    docs = project_root / "docs"
    required_files = [docs / "README.md", *[docs / name / "README.md" for name in REQUIRED]]
    missing = [str(path.relative_to(project_root)) for path in required_files if not path.is_file()]
    broken_links = []
    if docs.is_dir():
        for source in docs.rglob("*.md"):
            for raw_target in LINK.findall(source.read_text(encoding="utf-8")):
                target = unquote(raw_target.split("#", 1)[0].strip())
                if not target or target.startswith(("http://", "https://", "mailto:")):
                    continue
                resolved = (source.parent / target).resolve()
                if not resolved.is_relative_to(project_root) or not resolved.exists():
                    broken_links.append(f"{source.relative_to(project_root)} -> {raw_target}")
    return {
        "valid": not missing and not broken_links,
        "missing": sorted(missing),
        "brokenLinks": sorted(broken_links),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"valid": False, "missing": [], "brokenLinks": [],
                          "error": "usage: validate_project_docs.py PROJECT_ROOT"}))
        return 2
    result = validate(Path(sys.argv[1]))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

The script imports only standard-library modules and performs no write operation.

- [x] **Step 5: Run the docs tests**

Run: `python3 -m unittest tests.test_docs_template -v`

Expected: PASS.

- [x] **Step 6: Commit the templates and validator**

```bash
git add plugins/ai-native-devkit/skills/sop-init tests/test_docs_template.py
git commit -m "feat: add project docs templates and validator"
```

### Task 4: Implement `$sop-init`

**Files:**
- Create: `plugins/ai-native-devkit/skills/sop-init/SKILL.md`
- Create: `plugins/ai-native-devkit/skills/sop-init/references/init-contract.md`
- Modify: `tests/test_skill_contract.py`

**Interfaces:**
- Produces modes `Bootstrap`, `Adapt`, and `Refresh`.
- Produces `InitReport` fields `mode`, `scanned`, `created`, `modified`, `preserved`, `conflicts`, `validation`, and `handoffMigrationSuggested`.

- [x] **Step 1: Add a failing assertion for the init contract**

Add this method to `SkillContractTest`:

```python
    def test_init_contract(self):
        text = (SKILLS / "sop-init/SKILL.md").read_text()
        required = {
            "Bootstrap", "Adapt", "Refresh", "InitReport",
            "validate_project_docs.py",
            "Do not create, move, or update handoff/",
        }
        for token in required:
            self.assertIn(token, text)
```

- [x] **Step 2: Run the focused test and verify it fails on the missing Skill**

Run: `python3 -m unittest tests.test_skill_contract.SkillContractTest -v`

Expected: FAIL because `sop-init/SKILL.md` does not exist.

- [x] **Step 3: Write the complete initialization workflow**

Create `sop-init/SKILL.md` with:

````markdown
---
name: sop-init
description: Initialize, adapt, or refresh Agent-facing project documentation. Use when a project lacks indexed development context or its docs structure needs normalization.
---

# SOP Init

Read `references/init-contract.md`, then:

1. Inventory the repository, `AGENTS.md`, `docs/`, and any legacy `docs/handoff/` before writes.
2. Select `Bootstrap` when no usable docs exist, `Adapt` when useful non-standard docs exist,
   or `Refresh` when the standard structure exists.
3. Build a preview listing creates, moves, merges, splits, semantic additions, preserved files,
   and conflicts. Ask for confirmation before moves, merges, splits, or semantic additions.
4. Preserve existing valid content. Never replace a fact without stronger repository evidence.
5. Apply the approved changes using `assets/AGENTS.md` and `assets/docs-template/`.
6. Run `python3 scripts/validate_project_docs.py PROJECT_ROOT` from this Skill directory.
7. Return an `InitReport`.

Do not create, move, or update handoff/. If `docs/handoff/` exists, set
`handoffMigrationSuggested` to `true` and ask whether to invoke `$sop-handoff`.

`InitReport` has these fields:

```json
{
  "mode": "Bootstrap | Adapt | Refresh",
  "scanned": [],
  "created": [],
  "modified": [],
  "preserved": [],
  "conflicts": [],
  "validation": {"valid": true, "missing": [], "brokenLinks": []},
  "handoffMigrationSuggested": false
}
```
````

Create `references/init-contract.md` with the mode definitions above, the evidence precedence
`runtime/code/config/tests > current indexed docs > unindexed prose`, and the same preview and
report fields. `PROJECT_ROOT` in the command is replaced at runtime with the absolute target path.

- [x] **Step 4: Run the Skill and docs tests**

Run:

```bash
python3 -m unittest tests.test_skill_contract tests.test_docs_template -v
```

Expected: PASS.

- [x] **Step 5: Commit `$sop-init`**

```bash
git add plugins/ai-native-devkit/skills/sop-init tests/test_skill_contract.py
git commit -m "feat: implement sop init workflow"
```

### Task 5: Implement clarification, design, and planning Skills

**Files:**
- Create: `plugins/ai-native-devkit/skills/sop-clarify/SKILL.md`
- Create: `plugins/ai-native-devkit/skills/sop-design/SKILL.md`
- Create: `plugins/ai-native-devkit/skills/sop-plan/SKILL.md`
- Create: `tests/test_development_skills.py`

**Interfaces:**
- `sop-clarify` produces a requirement baseline with goals, non-goals, constraints, acceptance criteria, and unresolved questions.
- `sop-design` consumes an approved baseline and produces an approved design spec.
- `sop-plan` consumes an approved spec and produces a task-by-task implementation plan.

- [x] **Step 1: Write failing contract tests for the three Skills**

Create `tests/test_development_skills.py` with:

```python
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "plugins/ai-native-devkit/skills"


class DevelopmentSkillTest(unittest.TestCase):
    def test_contract_tokens(self):
        cases = {
            "sop-clarify": ["requirement baseline", "one question at a time", "explicit approval", "Do not implement"],
            "sop-design": ["approved requirement baseline", "two or three approaches", "trade-offs", "explicit approval"],
            "sop-plan": ["approved design spec", "- [ ]", "exact file paths", "Expected:", "git commit"],
        }
        for name, tokens in cases.items():
            text = (ROOT / name / "SKILL.md").read_text()
            for token in tokens:
                self.assertIn(token, text, f"{name}: {token}")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run the tests and verify the Skills are missing**

Run: `python3 -m unittest tests.test_development_skills -v`

Expected: FAIL because all three Skill files are absent.

- [x] **Step 3: Implement `$sop-clarify`**

Create its `SKILL.md` with:

```markdown
---
name: sop-clarify
description: Clarify requirements and produce an approved baseline. Use when goals, constraints, acceptance criteria, or scope are ambiguous.
---

# SOP Clarify

1. Read only the minimum relevant project context.
2. Identify missing goals, non-goals, constraints, acceptance criteria, and risk decisions.
3. Ask one question at a time. Prefer bounded choices when the trade-off is known.
4. Maintain a requirement baseline with `Goals`, `Non-goals`, `Constraints`,
   `Acceptance criteria`, and `Unresolved questions`.
5. Do not implement or design while clarifying.
6. Present the requirement baseline and require explicit approval.
7. Stop with unresolved questions if approval cannot be obtained.

Output: an approved requirement baseline or a concise blocked result.
```

- [x] **Step 4: Implement `$sop-design`**

Create its `SKILL.md` with:

```markdown
---
name: sop-design
description: Design an approved technical solution from a requirement baseline. Use when a change adds behavior, crosses modules, or affects architecture or public contracts.
---

# SOP Design

Input: an approved requirement baseline.

1. Verify the baseline is approved; otherwise invoke `$sop-clarify` and stop.
2. For architectural work, present two or three approaches with trade-offs and a recommendation.
3. Write a design covering architecture, component responsibilities, interfaces, data flow,
   failure handling, testing, migration, and documentation impact.
4. Keep `docs/` Agent-facing and root `handoff/` human-facing.
5. Present the design for explicit approval. Do not start planning before approval.
6. Save the approved design under `docs/superpowers/specs/`.

Output: the approved design spec path or a concise blocked result.
```

- [x] **Step 5: Implement `$sop-plan`**

Create its `SKILL.md` with:

```markdown
---
name: sop-plan
description: Turn an approved design into a test-driven implementation plan. Use when the design is approved and execution needs exact tasks, commands, and checkpoints.
---

# SOP Plan

Input: an approved design spec path.

1. Read the approved design spec and verify that it has no unresolved scope decision.
2. Write a file responsibility map before task decomposition.
3. Split work into independently reviewable tasks. Every task uses `- [ ]` checkbox steps.
4. For behavior changes, order steps as failing test, observed failure, minimal implementation,
   passing test, refactor, verification, and commit.
5. Include exact file paths, exact commands, `Expected:` results, interfaces, and frequent
   `git commit` checkpoints.
6. Save the plan under `docs/superpowers/plans/`.
7. Offer `superpowers:subagent-driven-development` as the preferred executor and
   `superpowers:executing-plans` as the inline alternative.

Output: the implementation plan path and the selected execution method.
```

- [x] **Step 6: Run the development Skill tests**

Run: `python3 -m unittest tests.test_development_skills tests.test_skill_contract -v`

Expected: PASS.

- [x] **Step 7: Commit the pre-implementation workflow**

```bash
git add plugins/ai-native-devkit/skills/sop-clarify plugins/ai-native-devkit/skills/sop-design plugins/ai-native-devkit/skills/sop-plan tests
git commit -m "feat: add clarification design and planning skills"
```

### Task 6: Implement execution and debugging Skills

**Files:**
- Create: `plugins/ai-native-devkit/skills/sop-execute/SKILL.md`
- Create: `plugins/ai-native-devkit/skills/sop-debug/SKILL.md`
- Create: `tests/test_delivery_skills.py`

**Interfaces:**
- `sop-execute` consumes an approved plan and produces code, tests, verification evidence, review evidence, and `TaskOutcome`.
- `sop-debug` consumes a reproducible symptom and produces root-cause evidence, a failing regression test, a focused fix, verification evidence, and `TaskOutcome`.

- [x] **Step 1: Write failing execution and debug contract tests**

Create `tests/test_delivery_skills.py` with:

```python
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "plugins/ai-native-devkit/skills"


class DeliverySkillTest(unittest.TestCase):
    def test_execute_gates(self):
        text = (SKILLS / "sop-execute/SKILL.md").read_text()
        for token in ("approved plan", "isolated Git workspace", "red-green-refactor",
                      "review after each task", "fresh final verification", "TaskOutcome"):
            self.assertIn(token, text)

    def test_debug_gates(self):
        text = (SKILLS / "sop-debug/SKILL.md").read_text()
        for token in ("reproduce before fixing", "hypothesis", "root-cause evidence",
                      "failing regression test", "one focused fix", "TaskOutcome"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run the tests and verify the Skills are missing**

Run: `python3 -m unittest tests.test_delivery_skills -v`

Expected: FAIL for missing execution and debugging gates.

- [x] **Step 3: Implement `$sop-execute` and `$sop-debug`**

Create `sop-execute/SKILL.md` with:

````markdown
---
name: sop-execute
description: Execute an approved Coding SOP implementation plan. Use when design and planning are complete and code changes should begin.
---

# SOP Execute

Input: an approved plan with unchecked tasks.

1. Work in an isolated Git workspace and confirm the baseline tests.
2. Execute one plan task at a time. Use red-green-refactor for every behavior change.
3. Run the task's exact verification and request review after each task.
4. Resolve review findings before checking the task complete and committing it.
5. Run fresh final verification after all tasks.
6. Invoke `$sop-sync-docs`, or record `docsImpact: NO_CHANGE` with evidence.
7. Derive only a lightweight `handoffSignal` from the final diff and docs result.
8. Do not read or write `handoff/` unless the user approves `$sop-handoff`.

Return `TaskOutcome`:

```json
{
  "route": "development | lightweight",
  "verification": [],
  "review": [],
  "docsImpact": "NO_CHANGE | DETERMINISTIC | SEMANTIC_REVIEW | CONFLICT",
  "handoffSignal": "NO_IMPACT | POSSIBLE_IMPACT | UPDATE_RECOMMENDED",
  "remainingRisks": []
}
```
````

Create `sop-debug/SKILL.md` with:

````markdown
---
name: sop-debug
description: Diagnose and fix software failures with reproduce-first evidence. Use when a bug, regression, crash, incorrect result, or performance symptom is reported.
---

# SOP Debug

1. Reproduce before fixing and record the exact command, input, actual result, and expected result.
2. Inspect boundaries and recent changes, then state one falsifiable hypothesis at a time.
3. Gather root-cause evidence; do not patch a correlated symptom.
4. Add a failing regression test that demonstrates the root cause.
5. Apply one focused fix and make the regression test pass.
6. If the fix changes architecture or public contracts, stop and invoke `$sop-design`.
7. Run focused and fresh final verification.
8. Invoke `$sop-sync-docs`, or record `docsImpact: NO_CHANGE` with evidence.
9. Derive only a lightweight `handoffSignal`. Do not read or write `handoff/` without user
   approval for `$sop-handoff`.

Return the same `TaskOutcome` fields defined by `$sop-execute`, with `route: debug`.
````

- [x] **Step 4: Run delivery Skill tests**

Run: `python3 -m unittest tests.test_delivery_skills tests.test_skill_contract -v`

Expected: PASS.

- [x] **Step 5: Commit execution and debugging**

```bash
git add plugins/ai-native-devkit/skills/sop-execute plugins/ai-native-devkit/skills/sop-debug tests/test_delivery_skills.py
git commit -m "feat: add execution and debugging skills"
```

### Task 7: Implement docs impact classification and `$sop-sync-docs`

**Files:**
- Create: `plugins/ai-native-devkit/skills/sop-sync-docs/SKILL.md`
- Create: `plugins/ai-native-devkit/skills/sop-sync-docs/references/doc-impact-rules.md`
- Create: `plugins/ai-native-devkit/skills/sop-sync-docs/scripts/classify_changes.py`
- Create: `tests/test_classify_changes.py`

**Interfaces:**
- CLI: `classify_changes.py CHANGED_FILES_PATH`.
- Output: `{"docsImpact": str, "handoffSignal": str, "reasons": list[str]}`.
- Allowed `docsImpact`: `NO_CHANGE`, `DETERMINISTIC`, `SEMANTIC_REVIEW`, `CONFLICT`.
- Allowed `handoffSignal`: `NO_IMPACT`, `POSSIBLE_IMPACT`, `UPDATE_RECOMMENDED`.

- [x] **Step 1: Write failing classifier tests**

Create `tests/test_classify_changes.py` with a temporary newline-delimited input file and run
the classifier as a subprocess. Use this case table:

```python
CASES = {
    "tests/foo_test.py": ("NO_CHANGE", "NO_IMPACT"),
    "src/internal/cache.py": ("NO_CHANGE", "NO_IMPACT"),
    "api/order.proto": ("SEMANTIC_REVIEW", "UPDATE_RECOMMENDED"),
    "migrations/002_move_owner.sql": ("SEMANTIC_REVIEW", "UPDATE_RECOMMENDED"),
    "docs/design/order.md": ("DETERMINISTIC", "POSSIBLE_IMPACT"),
}
```

For each row assert exit code 0, parse stdout with `json.loads`, and compare
`docsImpact` and `handoffSignal` to the tuple.

- [x] **Step 2: Run tests and verify the classifier is missing**

Run: `python3 -m unittest tests.test_classify_changes -v`

Expected: ERROR because `classify_changes.py` does not exist.

- [x] **Step 3: Implement the minimal deterministic classifier**

Create `classify_changes.py` with:

```python
#!/usr/bin/env python3
import json
import sys
from pathlib import Path, PurePosixPath

DOCS_PREFIX = "docs/"
SEMANTIC_PREFIXES = ("api/", "migrations/", "schema/", "proto/")
NO_IMPACT_PREFIXES = ("tests/", "test/", "src/internal/", "internal/")
HANDOFF_DOCS = ("docs/overview/", "docs/design/", "docs/api/", "docs/runbooks/")


def classify(paths: list[str]) -> dict:
    normalized = [str(PurePosixPath(path.strip())) for path in paths if path.strip()]
    reasons = []
    docs_impact = "NO_CHANGE"
    handoff_signal = "NO_IMPACT"

    for path in normalized:
        if path.startswith(SEMANTIC_PREFIXES):
            docs_impact = "SEMANTIC_REVIEW"
            handoff_signal = "UPDATE_RECOMMENDED"
            reasons.append(f"public contract or data model changed: {path}")
            continue
        if path.startswith(DOCS_PREFIX):
            if docs_impact == "NO_CHANGE":
                docs_impact = "DETERMINISTIC"
            if path.startswith(HANDOFF_DOCS) and handoff_signal == "NO_IMPACT":
                handoff_signal = "POSSIBLE_IMPACT"
            reasons.append(f"Agent-facing docs changed: {path}")
            continue
        if path.startswith(NO_IMPACT_PREFIXES):
            reasons.append(f"routine internal or test-only change: {path}")

    return {"docsImpact": docs_impact, "handoffSignal": handoff_signal, "reasons": reasons}


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: classify_changes.py CHANGED_FILES_PATH"}))
        return 2
    paths = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    print(json.dumps(classify(paths), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `doc-impact-rules.md` containing the four ordered rules encoded above and state that
the classifier supplies candidate evidence only. `SEMANTIC_REVIEW` and `CONFLICT` require
Agent reasoning and user review before writes.

- [x] **Step 4: Write the sync-docs Skill**

Create `sop-sync-docs/SKILL.md` with:

````markdown
---
name: sop-sync-docs
description: Classify documentation impact and synchronize Agent-facing project docs after verified code changes. Use when a task may have changed durable project knowledge.
---

# SOP Sync Docs

1. Read the final diff, task decisions, verification evidence, and `docs/README.md`.
2. Write changed paths to a temporary newline-delimited file and run
   `python3 scripts/classify_changes.py CHANGED_FILES_PATH` from this Skill directory.
3. Combine classifier output with repository evidence and produce a `DocImpactReport`.
4. For `NO_CHANGE`, write nothing. For `DETERMINISTIC`, update only paths, indexes, commands,
   or verified implementation status. For `SEMANTIC_REVIEW`, show a preview and require user
   confirmation. For `CONFLICT`, write nothing and report the conflicting evidence.
5. Never write guessed content and never create, read, move, or update root `handoff/`.

`DocImpactReport` contains `docsImpact`, `handoffSignal`, `reasons`, `proposedChanges`,
`appliedChanges`, `conflicts`, and `verification`.

`handoffSignal` is only a cheap classification. Ordinary Bug fixes, test additions, internal
refactors, and temporary state changes remain `NO_IMPACT`; do not ask the user about handoff.
For `POSSIBLE_IMPACT` or `UPDATE_RECOMMENDED`, ask whether to invoke `$sop-handoff`; only approval
starts a full handoff scan.
````

- [x] **Step 5: Run classifier and Skill tests**

Run:

```bash
python3 -m unittest tests.test_classify_changes tests.test_skill_contract -v
```

Expected: PASS.

- [x] **Step 6: Commit docs synchronization**

```bash
git add plugins/ai-native-devkit/skills/sop-sync-docs tests
git commit -m "feat: add docs impact classification and sync skill"
```

### Task 8: Build the handoff template, validator, and `$sop-handoff`

**Files:**
- Create: `plugins/ai-native-devkit/skills/sop-handoff/SKILL.md`
- Create: `plugins/ai-native-devkit/skills/sop-handoff/assets/handoff-template/README.md`
- Create: `plugins/ai-native-devkit/skills/sop-handoff/assets/handoff-template/index.html`
- Create: `plugins/ai-native-devkit/skills/sop-handoff/assets/handoff-template/system-overview.html`
- Create: `plugins/ai-native-devkit/skills/sop-handoff/assets/handoff-template/business-flows.html`
- Create: `plugins/ai-native-devkit/skills/sop-handoff/assets/handoff-template/assets/style.css`
- Create: `plugins/ai-native-devkit/skills/sop-handoff/assets/handoff-template/assets/app.js`
- Create: `plugins/ai-native-devkit/skills/sop-handoff/assets/handoff-template/assets/map-data.js`
- Create: `plugins/ai-native-devkit/skills/sop-handoff/scripts/validate_handoff.py`
- Create: `tests/test_handoff.py`

**Interfaces:**
- CLI: `validate_handoff.py PROJECT_ROOT`.
- Output: `{"valid": bool, "missing": list[str], "brokenLinks": list[str], "unreachablePages": list[str]}`.
- Skill modes: `Bootstrap`, `Adapt`, `Refresh`.

- [x] **Step 1: Write failing template and validator tests**

In `tests/test_handoff.py`, define:

```python
REQUIRED = {
    "README.md", "index.html", "system-overview.html", "business-flows.html",
    "assets/style.css", "assets/app.js", "assets/map-data.js",
}
```

Add one test comparing these paths to files under `assets/handoff-template` and rejecting any HTML
filename that matches `r"\d{4}[-_]\d{2}[-_]\d{2}"`. Reject `docs/handoff` in HTML, CSS, and
JavaScript; in `README.md`, allow it only in the `Adapt` migration rule. Add a subprocess test
against a temporary blank project that asserts exit code 1, `valid is False`, and
`"handoff/index.html" in missing`. Add a valid-template test that copies
`assets/handoff-template` to `TEMP_PROJECT/handoff`, runs the validator, and asserts exit code 0
with `valid is True`, empty `brokenLinks`, and empty `unreachablePages`. Add a mutation test that
removes the `system-overview.html` entry from copied `map-data.js` and asserts that page appears in
`unreachablePages`.

- [x] **Step 2: Run tests and verify missing files fail**

Run: `python3 -m unittest tests.test_handoff -v`

Expected: FAIL because the template and validator are absent.

- [x] **Step 3: Create the human-facing static template**

Extract the finalized `handoff/README.md` block from
`$SOURCE_ROOT/plugin-plan-section-5-latest.md` without changing its ownership,
source-of-truth, update-trigger, or preview rules. Create `map-data.js` with:

```javascript
window.HANDOFF_MAP = {
  "projectName": "Project Handoff",
  "pages": [
    {"path": "index.html", "label": "Home"},
    {"path": "system-overview.html", "label": "System Overview"},
    {"path": "business-flows.html", "label": "Business Flows"}
  ]
};
```

Create `app.js` with:

```javascript
(function () {
  "use strict";
  var map = window.HANDOFF_MAP;
  var nav = document.querySelector("[data-handoff-nav]");
  var title = document.querySelector("[data-project-name]");
  if (!map || !nav) return;
  if (title) title.textContent = map.projectName;
  map.pages.forEach(function (page) {
    var link = document.createElement("a");
    link.href = page.path;
    link.textContent = page.label;
    if (location.pathname.endsWith(page.path)) link.setAttribute("aria-current", "page");
    nav.appendChild(link);
  });
}());
```

Each HTML file must use semantic `header`, `nav`, `main`, and `footer` elements; load
`assets/style.css`, then `assets/map-data.js`, then `assets/app.js`; contain exactly one `h1`;
and use `data-project-name` and `data-handoff-nav`. The overview page contains `System Boundary`,
`Components`, and `Dependencies` sections. The flows page contains `Actors`, `Primary Flows`,
`Exceptions`, and `Operational Entry Points` sections. CSS uses a neutral white surface,
`#111827` text, `#2563eb` links, an 8 px maximum radius, a 72 rem content width, visible focus
styles, and a single-column layout below 720 px.

- [x] **Step 4: Implement the read-only handoff validator**

Create `validate_handoff.py` with functions `load_map(path: Path) -> dict` and
`validate(project_root: Path) -> dict`. `load_map` reads `window.HANDOFF_MAP = ...;` using
`re.fullmatch(r"\s*window\.HANDOFF_MAP\s*=\s*(\{.*\})\s*;\s*", text, re.DOTALL)` and parses
the captured object with `json.loads`. `validate` must:

```python
REQUIRED = (
    "README.md", "index.html", "system-overview.html", "business-flows.html",
    "assets/style.css", "assets/app.js", "assets/map-data.js",
)
LOCAL_REF = re.compile(r'(?:href|src)="([^"#]+)"')
```

1. Report absent required paths relative to the project root in `missing`.
2. For every HTML file, resolve non-HTTP `href` and `src` values inside `handoff/`; report
   missing or escaping targets in `brokenLinks`.
3. Parse `assets/map-data.js`; require page paths to be unique, to exist, and to include all
   top-level HTML files. Put absent or unlisted pages in `unreachablePages`.
4. Emit sorted JSON keys `valid`, `missing`, `brokenLinks`, and `unreachablePages`; exit 0 only
   when all three error lists are empty, 1 for an invalid map, and 2 for invalid CLI usage.

Do not require Mermaid in `0.1.0`; generated projects may add it later. The script must contain
no file-write API.

- [x] **Step 5: Write the handoff Skill**

Create `sop-handoff/SKILL.md` with:

````markdown
---
name: sop-handoff
description: Generate, adapt, or refresh a human-facing project handoff map. Use only when the user explicitly requests handoff work or approves a handoff-impact check.
---

# SOP Handoff

1. Confirm explicit invocation or prior user approval before scanning `handoff/`.
2. Select `Bootstrap` when root `handoff/` is absent, `Adapt` when legacy `docs/handoff/` or a
   non-standard map exists, or `Refresh` when the standard map exists.
3. Gather evidence from runtime behavior, code, configuration, tests, and indexed `docs/`.
   Treat `handoff/` only as a human-authored derived view, never as a project fact source.
4. Produce `HandoffImpactReport` with `mode`, `evidence`, `affectedPages`, `preservedContent`,
   `conflicts`, and `previewRequired`.
5. Preview and require confirmation before deleting pages, migrating legacy content, or
   overwriting human-authored content.
6. Update only affected pages and preserve unrelated content.
7. Run `python3 scripts/validate_handoff.py PROJECT_ROOT` from this Skill directory.
8. Return `HandoffReport` with `mode`, `created`, `modified`, `migrated`, `preserved`,
   `conflicts`, and `validation`.

Ordinary Bug fixes, test additions, internal refactors, and temporary state changes neither scan
handoff nor ask about it. A candidate signal from `$sop-sync-docs` may ask once whether the user
wants this Skill; declining performs no scan and no write.
````

- [x] **Step 6: Run handoff and Skill tests**

Run:

```bash
python3 -m unittest tests.test_handoff tests.test_skill_contract -v
```

Expected: PASS.

- [x] **Step 7: Commit the handoff capability**

```bash
git add plugins/ai-native-devkit/skills/sop-handoff tests/test_handoff.py
git commit -m "feat: add human handoff map skill"
```

### Task 9: Add the complete validation command and evaluation fixtures

**Files:**
- Create: `scripts/validate_all.py`
- Create: `tests/fixtures/blank-project/.gitkeep`
- Create: `tests/fixtures/legacy-docs-project/docs/handoff/README.md`
- Create: `tests/fixtures/standard-project/docs/**/README.md`
- Create: `tests/test_end_to_end_contract.py`
- Modify: `plugins/ai-native-devkit/README.md`

**Interfaces:**
- CLI: `python3 scripts/validate_all.py`.
- Exit 0 only when unit tests and the official plugin validator both pass.

- [x] **Step 1: Write a failing end-to-end contract test**

Create `tests/test_end_to_end_contract.py`. Import validator modules with
`importlib.util.spec_from_file_location` so the scripts do not need package marker files. Add these
five assertions:

```python
EXPECTED_SKILLS = {
    "coding-sop", "sop-init", "sop-clarify", "sop-design", "sop-plan",
    "sop-execute", "sop-debug", "sop-sync-docs", "sop-handoff",
}

self.assertFalse(validate_docs(BLANK)["valid"])
self.assertTrue((LEGACY / "docs/handoff/README.md").is_file())
self.assertFalse((LEGACY / "handoff").exists())
self.assertTrue(validate_docs(STANDARD)["valid"])
self.assertEqual(discovered_skill_names(), EXPECTED_SKILLS)
```

Read `plugins/ai-native-devkit/README.md` and assert it contains `codex plugin marketplace add`,
`codex plugin add`, all nine `$...` invocation names, `python3 scripts/validate_all.py`, and
`codex plugin remove ai-native-devkit@ai-native-devkit`. Also assert the development-update section contains
`read_marketplace_name.py` and `update_plugin_cachebuster.py`.

- [x] **Step 2: Run the end-to-end test and verify missing fixtures fail**

Run: `python3 -m unittest tests.test_end_to_end_contract -v`

Expected: FAIL because fixtures and validation entry point are absent.

- [x] **Step 3: Add fixtures and the aggregate validator**

Create the blank fixture with only `.gitkeep`. Create the legacy fixture with only a
`docs/handoff/README.md` whose heading is `# Legacy Handoff`. Create the standard fixture by
copying the canonical docs template under `standard-project/docs/`.

Create `scripts/validate_all.py` with:

```python
#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
PLUGIN_VALIDATOR = CODEX_HOME / "skills/.system/plugin-creator/scripts/validate_plugin.py"
COMMANDS = (
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    [sys.executable, str(PLUGIN_VALIDATOR), "plugins/ai-native-devkit"],
)


def main() -> int:
    for command in COMMANDS:
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Document exact local development commands**

Document:

```bash
python3 scripts/validate_all.py
codex plugin marketplace add "$(pwd)"
codex plugin add ai-native-devkit@ai-native-devkit
codex plugin remove ai-native-devkit@ai-native-devkit
```

Document this local update loop separately:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/read_marketplace_name.py" \
  --marketplace-path .agents/plugins/marketplace.json
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py" \
  plugins/ai-native-devkit
codex plugin add ai-native-devkit@ai-native-devkit
```

State that the cachebuster is for local development only, release versions use clean SemVer, and
updated Skills are tested in a new Codex task after reinstall.
Document all nine public invocation names and explain the three routes, docs/handoff ownership
boundary, explicit handoff approval rule, Python 3.10 prerequisite, and `0.1.0` exclusions.

- [x] **Step 5: Run the complete validation**

Run: `python3 scripts/validate_all.py`

Expected: all unit tests pass and the official plugin validator exits 0.

- [x] **Step 6: Commit evaluation and documentation**

```bash
git add scripts tests plugins/ai-native-devkit/README.md
git commit -m "test: add plugin contract evaluation suite"
```

### Task 10: Install locally and run the integration acceptance gate

**Files:**
- Modify: `docs/superpowers/plans/2026-08-24-coding-sop-plugin-v0.1.md` only to check completed steps during execution.

**Interfaces:**
- Consumes: validated marketplace and plugin.
- Produces: installed plugin visible in `codex plugin list` and a recorded acceptance result.

- [x] **Step 1: Add the local marketplace**

Run:

```bash
codex plugin marketplace add "$(pwd)"
codex plugin marketplace list
```

Expected: output includes marketplace `ai-native-devkit` resolved from the local repository.

- [x] **Step 2: Install the plugin**

Run:

```bash
codex plugin add ai-native-devkit@ai-native-devkit
codex plugin list --json
```

Expected: JSON includes an installed and enabled `ai-native-devkit` entry at version `0.1.0`.

- [x] **Step 3: Start a new Codex task and run the smoke scenarios**

Run these prompts in a new task:

```text
$coding-sop classify this task: add a unit test for an existing pure function.
$sop-init inspect this blank fixture and show the initialization preview without writing.
$sop-handoff inspect this legacy fixture and show the Adapt preview without writing.
```

Expected: the first selects `lightweight`; the second selects `Bootstrap` and does not create `handoff/`; the third selects `Adapt`, preserves legacy content, and does not write before confirmation.

- [x] **Step 4: Run final verification from a clean working tree**

Run:

```bash
python3 scripts/validate_all.py
git status --short
```

Expected: validation exits 0 and `git status --short` is empty except for plan checkbox updates made during execution.

- [x] **Step 5: Commit the completed execution record**

```bash
git add docs/superpowers/plans/2026-08-24-coding-sop-plugin-v0.1.md
git commit -m "docs: record coding sop plugin acceptance"
```

## Follow-up Releases

- `0.2.0`: add an opt-in plugin-bundled `Stop` hook that exits immediately unless a Coding SOP task produced a `TaskOutcome`, then emits only a lightweight docs/handoff signal.
- `0.3.0`: add Cooper MCP integration and reference-document synchronization.
- `1.0.0`: add product and QA workflow Skills after separate designs and evaluations.
