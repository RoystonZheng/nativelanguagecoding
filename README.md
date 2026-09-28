# AI Native DevKit

AI Native DevKit is a Codex plugin for structured AI-assisted software delivery.
It helps an agent choose an appropriate workflow, understand a repository,
clarify requirements, design a solution, plan implementation slices, execute or
debug changes, verify the result, and keep project documentation aligned.

The project is meant for general engineering teams and individual developers.
It is not tied to a private company workflow, issue tracker, or source-control
host. The packaged skills work with ordinary Git repositories and keep private
workflow state outside the target repository.

## What It Provides

- `$coding-sop`: top-level router for development and debugging work.
- `$sop-init`: repository context inspection and optional project-doc bootstrap.
- `$sop-clarify`: one-question-at-a-time requirement discovery that writes an
  exact Git requirements record.
- `$sop-design`: solution design from one approved requirement reference.
- `$sop-plan`: an ordered Markdown implementation plan derived from the design.
- `$sop-execute`: serial behavior-first implementation with focused checks and
  candidate review.
- `$sop-debug`: debug lifecycle wrapper around the packaged diagnosis method.
- `$diagnosing-bugs`: feedback-loop-first debugging discipline.
- `$sop-verify`: fresh, revision-bound completion evidence.
- `$sop-sync-docs`: documentation impact classification and controlled updates.

The plugin also bundles:

- Codex lifecycle hooks for automatic execution trace collection.
- Runtime CLIs for workflow routing, stage transitions, approvals, verification,
  docs impact classification, and trace loading.
- Project documentation templates and managed runbooks.
- Contract, integration, and plugin validation tests.

## Current Status

Current 0.4.0 implemented capabilities include the installable plugin, stage
skills, automatic execution trace collection, post-verification docs impact
classification, and the exact Clarify-to-Design handoff through an approved Git
requirements document. `0.3.0` 新增 the packaged Collector Hook, automatic
Execution Trace, runtime events, and the post-verification Docs Hook.

Some documents describe planned V1 runtime capabilities. Those sections are
explicitly marked as `Planned V1` and should not be read as already implemented
behavior.

## Repository Layout

```text
.
├── AGENTS.md                         # Contributor and project rules
├── .agents/plugins/marketplace.json  # Local Codex marketplace entry
├── plugins/ai-native-devkit/         # Plugin manifest, skills, hooks, scripts
├── docs/                             # Architecture, contracts, workflow, ADRs
├── scripts/validate_all.py           # Full validation entry point
└── tests/                            # Contract, integration, and regression tests
```

## Install For Local Use

```bash
git clone https://github.com/RoystonZheng/nativelanguagecoding.git
cd nativelanguagecoding
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate_all.py
codex plugin marketplace add "$(pwd)"
codex plugin add ai-native-devkit@ai-native-devkit
```

After installation, open `/hooks` in Codex and review the `ai-native-devkit`
hook definitions before trusting them. Hooks are inert for ordinary sessions and
start writing trace events only after a validated DevKit runtime operation
activates the current workflow.

## Development Validation

Python 3.9 or newer is required. Before submitting changes, run:

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate_all.py
```

The validation entry point runs unit tests, integration tests, contract tests,
and plugin/skill structure checks.

## Documentation

- [Plugin README](plugins/ai-native-devkit/README.md) explains installation,
  invocation, runtime behavior, and validation scope.
- [Docs index](docs/README.md) routes architecture, workflow, contract, and ADR
  reading.
- [Third-party notices](THIRD_PARTY_NOTICES.md) records upstream method
  provenance and licenses.

## Design Principles

- Use the smallest safe workflow for the task.
- Keep product meaning, implementation decisions, and verification evidence
  explicit.
- Preserve user authority at meaningful boundaries.
- Store private workflow state outside target repositories.
- Promote only durable, sourced, approved knowledge into project documentation.
