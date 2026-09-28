# AI Native DevKit Plugin Design

## Status

Approved for implementation based on the SOP and handoff design discussion completed on 2026-08-24.

## Goal

Build an installable Codex plugin named `ai-native-devkit` that packages the team's development SOP as reusable Skills, project-document templates, deterministic validators, and a team marketplace entry.

## Release Scope

Version `0.1.0` delivers the complete explicit workflow without lifecycle hooks or external MCP dependencies:

- Route work into lightweight, development, or debug flows.
- Initialize or adapt project `docs/` and `AGENTS.md` through `$sop-init`.
- Clarify requirements through `$sop-clarify`.
- Produce approved designs through `$sop-design`.
- Produce executable plans through `$sop-plan`.
- Execute approved work with verification through `$sop-execute`.
- Diagnose bugs with a reproduce-first loop through `$sop-debug`.
- Analyze and update Agent-facing project documentation through `$sop-sync-docs`.
- Generate, migrate, or refresh the human-facing root `handoff/` map through `$sop-handoff`.

Lifecycle hooks, Cooper MCP integration, product workflows, QA browser automation, public directory publication, and non-Codex host adapters are later releases.

## Distribution Model

The source repository is a team marketplace:

```text
ai-native-devkit/
├── .agents/plugins/marketplace.json
├── plugins/ai-native-devkit/
│   ├── .codex-plugin/plugin.json
│   ├── skills/
│   ├── assets/
│   └── README.md
├── scripts/
├── tests/
└── docs/superpowers/
```

Until the team Git URL is assigned, local installation uses:

```bash
codex plugin marketplace add "$(pwd)"
codex plugin add ai-native-devkit@ai-native-devkit
```

For team distribution, publish the same repository and replace the local path with its Git URL in the release README. The marketplace and plugin names remain `ai-native-devkit`.

## Plugin Structure

```text
plugins/ai-native-devkit/
├── .codex-plugin/
│   └── plugin.json
├── skills/
│   ├── coding-sop/
│   │   ├── SKILL.md
│   │   └── references/workflow-contract.md
│   ├── sop-init/
│   │   ├── SKILL.md
│   │   ├── assets/AGENTS.md
│   │   ├── assets/docs-template/
│   │   └── scripts/validate_project_docs.py
│   ├── sop-clarify/SKILL.md
│   ├── sop-design/SKILL.md
│   ├── sop-plan/SKILL.md
│   ├── sop-execute/SKILL.md
│   ├── sop-debug/SKILL.md
│   ├── sop-sync-docs/
│   │   ├── SKILL.md
│   │   ├── references/doc-impact-rules.md
│   │   └── scripts/classify_changes.py
│   └── sop-handoff/
│       ├── SKILL.md
│       ├── assets/handoff-template/
│       └── scripts/validate_handoff.py
└── README.md
```

## Invocation Contract

Codex Skills use `$skill-name` for explicit invocation. The public names are:

| Capability | Invocation |
|---|---|
| Main router | `$coding-sop` |
| Project context initialization | `$sop-init` |
| Requirements clarification | `$sop-clarify` |
| Design | `$sop-design` |
| Implementation planning | `$sop-plan` |
| Plan execution | `$sop-execute` |
| Debugging | `$sop-debug` |
| Project docs synchronization | `$sop-sync-docs` |
| Human handoff map | `$sop-handoff` |

The documentation may mention legacy `/init` or `/handoff` names only in migration notes. The plugin itself must use the `$...` names above.

## Workflow Contract

The router classifies tasks into three routes:

| Route | Criteria | Required stages |
|---|---|---|
| Lightweight | Local, low-risk, behavior already specified | Context selection, implementation, verification, docs-impact conclusion |
| Development | New behavior, multiple modules, ambiguous requirements, or architectural impact | Clarify, design, plan, execute, verify, docs sync |
| Debug | Bug, failure, regression, or performance symptom | Reproduce, isolate root cause, regression test, fix, verify, docs-impact conclusion |

Every route ends with an explicit docs-impact conclusion. No route may claim completion without fresh verification evidence.

## Project Documentation Boundary

`docs/` is the Agent-facing current project knowledge layer. `$sop-init` supports:

- Bootstrap: no usable `docs/` exists.
- Adapt: existing project documents need migration or re-indexing.
- Refresh: the standard structure exists and needs consistency checks.

The standard directories are `overview`, `references`, `decisions`, `design`, `api`, `runbooks`, `pitfalls`, and `superpowers`. Every directory has a `README.md` entry point and file index.

`$sop-sync-docs` classifies changes as:

- `NO_CHANGE`: no long-term project knowledge changed.
- `DETERMINISTIC`: paths, indexes, commands, or implementation status can be updated directly.
- `SEMANTIC_REVIEW`: business, architecture, contract, or decision text requires a preview and user confirmation.
- `CONFLICT`: evidence is insufficient or sources disagree; do not write guessed content.

## Handoff Boundary

`handoff/` is a human-facing derived project map at the project root, never a `docs/` child and never a project fact source. `$sop-handoff` supports:

- Bootstrap: generate a new map.
- Adapt: migrate legacy `docs/handoff/` or a non-standard map while preserving valid human content.
- Refresh: update only affected pages.

Ordinary tasks do not scan `handoff/`. Task completion may reuse the final diff and docs-impact result to identify a candidate handoff impact. Only an explicit `$sop-handoff` invocation or user approval starts a full handoff scan. File updates require a preview when pages are deleted, legacy content is migrated, or human-authored content would be overwritten.

## Deterministic Tooling

All runtime validators use Python 3.10 or newer and the standard library only.

- `validate_project_docs.py` validates required directories, README entry points, and relative links.
- `classify_changes.py` accepts a newline-delimited changed-file list and emits JSON containing `docsImpact`, `handoffSignal`, and `reasons`.
- `validate_handoff.py` validates required pages, navigation membership, relative assets, and local link reachability.

The scripts must never modify project files. Skills remain responsible for proposing or applying changes.

## Testing Strategy

Automated tests use Python `unittest` and temporary fixture directories. Tests cover:

- Plugin manifest and marketplace schema invariants.
- Skill frontmatter, public invocation names, and internal cross-links.
- Docs template structure and validator failure modes.
- Change classification for no-impact, docs-only, and handoff-candidate cases.
- Handoff template structure, navigation consistency, and validator failure modes.
- Absence of legacy `docs/handoff/` and public `/command` invocations.

The official plugin validator is the final packaging gate. A local marketplace install and a new Codex task are the final integration gate.

## Security and Safety

- No credentials, cookies, tokens, internal absolute paths, or signed temporary URLs are bundled.
- Validators are read-only.
- Project writes require the normal Codex approval and review behavior.
- Handoff updates preserve unrelated human content.
- No external network dependency is required for version `0.1.0`.

## Acceptance Criteria

1. `python3 -m unittest discover -s tests -v` passes.
2. The official plugin validator accepts `plugins/ai-native-devkit`.
3. The marketplace lists `ai-native-devkit` with installation policy `AVAILABLE`.
4. A local install succeeds with `codex plugin add ai-native-devkit@ai-native-devkit`.
5. A new Codex task discovers all nine Skills.
6. `$sop-init` creates a valid docs structure in a blank fixture without creating `handoff/`.
7. `$sop-sync-docs` distinguishes deterministic, semantic-review, conflict, and no-change outcomes.
8. `$sop-handoff` creates or refreshes a valid root `handoff/` without treating it as a fact source.
9. No ordinary Bug, test-only change, or internal refactor triggers a full handoff scan.
