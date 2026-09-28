---
name: sop-verify
description: Verify a candidate software change against acceptance criteria with fresh, revision-bound evidence. Use before claiming a task complete, after implementation or debugging, and whenever prior test evidence may be stale.
---

# SOP Verify

Read [user-direction.md](../coding-sop/references/user-direction.md) before applying this Skill.
Explicit user skips and blocker waivers take precedence over this Skill's
normal stop/approval rules; record them once and continue the adjusted work.

Read [output-language.md](../coding-sop/references/output-language.md) before generating user-facing text or documents.

Input: acceptance criteria, candidate revision or worktree digest, changed
paths, and any prior evidence.

1. Resolve `PLUGIN_ROOT` from this Skill and call
   `python3 "$PLUGIN_ROOT/scripts/runtime_cli.py"` operation `stage.start` with
   `stage: verify` and the repository root before running verification. Retain
   its `stage_run_id`; do not narrate this internal transition.
2. Enumerate every applicable acceptance criterion; keep conditional or
   not-applicable criteria visible with a reason. The denominator must not
   silently shrink.
3. Select the smallest sufficient mix of focused tests, broader regression
   tests, build/lint/type checks, and direct scenario checks.
4. Run commands freshly against the candidate state. Record invocation,
   observed revision/digest, exit status, and concise result; do not reuse stale
   evidence as proof.
5. Keep unavailable checks distinct from passing checks. A skipped or missing
   tool is not a pass.
6. Verify reviewer findings are resolved and public/data-contract or migration
   changes include the required compatibility evidence.
7. Return `pass` only when every applicable criterion has current evidence and
   no blocking review finding remains.
8. Submit the finished result to
   `python3 "$PLUGIN_ROOT/scripts/runtime_cli.py"` operation
   `verification.complete`, including the exact Git worktree root, baseline
   revision, candidate revision, criterion totals, remaining-risk count, and
   the retained `stage_run_id`.
   Do not provide changed paths; the runtime computes them from Git evidence.
9. A passing `verification.completed` event automatically triggers the Docs Hook in the same
   runtime call. Consume its `docs_hook.report` as follows:
   - `NO_CHANGE`: do not write docs.
   - `DETERMINISTIC`: apply only the deterministic synchronization identified by
     `$sop-sync-docs` and verify it without a semantic approval prompt.
   - `SEMANTIC_REVIEW`: invoke `$sop-sync-docs` to build a complete preview, then
     require user confirmation before any write.
   - `CONFLICT`: write nothing and report the conflict.
   Continue to workflow completion after the selected Docs action reaches its
   terminal state. Human-facing Handoff documents are outside plugin scope;
   do not inspect, manage, or ask about them.

Return a `VerificationReport` with `baselineRefs`, `candidateRevision`,
`criteria`, `evidence`, `coverage`, `result`, and `remainingRisks`. This release
uses an Agent-produced report plus a code-owned completion and Docs Hook boundary;
durable full VerificationReport artifacts remain a later runtime slice.
