# Test strategy

Tests are organized around public module interfaces and frozen workflow
fixtures:

- `contract/`: envelopes, transitions, persistence and compatibility;
- `modules/`: behavior through deep-module interfaces;
- `integration/`: CLI, resume, rejection and cross-process workflows;
- root `test_*.py`: packaged plugin, Skills, docs and promotion gates.

Prefer observable contract behavior over private helper or prompt wording. A
static Skill assertion is appropriate only when installation-relative lookup,
an approval boundary or another caller-visible instruction is itself the
contract. Production and in-memory persistence adapters should share the same
behavioral test cases.
