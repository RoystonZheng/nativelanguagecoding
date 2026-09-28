# Documentation Impact Rules

The classifier supplies candidate evidence only. The Agent may override it after reasoning
from the final diff and repository evidence.

Apply these rules in order for every changed path:

1. Paths under `api/`, `migrations/`, `schema/`, or `proto/` are public-contract or data-model
   changes. They produce `SEMANTIC_REVIEW`.
2. Paths under `docs/` produce `DETERMINISTIC` unless a prior semantic rule already produced
   `SEMANTIC_REVIEW`.
3. Paths under `tests/`, `test/`, `src/internal/`, or `internal/` are routine internal or
   test-only changes and remain `NO_CHANGE`.
4. All other paths remain `NO_CHANGE` until repository evidence requires an
   Agent decision.

`SEMANTIC_REVIEW` and `CONFLICT` require Agent reasoning and user review before writes.
