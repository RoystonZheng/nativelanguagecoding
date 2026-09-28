# ADR 0003: Reimplement a hybrid set of Skill mechanisms

Status: Accepted
Date: 2026-08-23

## Context

Function-level evaluations did not identify a universal winning upstream plugin. Matt-style workflows were stronger or more efficient in clarification and Ticket planning. Superpowers contributed clearer alternative comparison, centralized execution tracking and strict completion evidence. Design, execution and debugging evidence remains mixed.

## Decision

Implement a plugin-owned hybrid:

- Matt-style decision/domain coverage for clarification;
- Matt coverage plus Superpowers alternative comparison for design;
- Matt-style vertical Tickets with optional detailed drill-down;
- centralized execution ledger plus Ticket-level TDD and dual-axis review;
- vendor-neutral diagnosis protocol pending stronger evidence;
- Superpowers-style fresh evidence discipline for verification;
- custom context and documentation lifecycle.

Record upstream repository/version/license before directly deriving content. Prefer implementing the behavior through AI Native DevKit contracts rather than copying complete Skill files.

## Alternatives

1. Fork Matt-Skills as the base. Rejected because execution, verification and docs integration need different behavior.
2. Fork Superpowers as the base. Rejected because default flow weight and planning cost conflict with the product goal.
3. Compose both complete plugins. Rejected by ADR 0001.

## Consequences

- Feature behavior is evaluated independently instead of inheriting upstream branding.
- Future upstream updates require deliberate comparison, not automatic merge.
- Hybrid stages must be evaluated; combining strengths on paper does not prove a better workflow.
- Provenance and licensing become explicit project responsibilities.

## Revisit when

New controlled evaluations establish a consistent winner for a stage or the upstream interfaces become directly composable under WorkflowRuntime.

## Plan/Execute supersession (2026-08-28)

ADR 0007 supersedes only the vertical Ticket/public execution-ledger bullets.
The Current adaptation uses one detailed DesignDoc-derived Markdown PlanDoc,
serial behavior-first Execute, and one fixed-candidate Spec/Standards review.
The provenance, reimplementation, vendor-neutral diagnosis, fresh verification,
and custom documentation-lifecycle decisions remain accepted.
