"""Projection and authorization gate for exact requirement approvals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .contracts import RequirementDocRef
from .errors import ContractError, RequirementApprovalError
from .execution_trace import ExecutionTraceStore, repository_digest


REQUIREMENT_APPROVAL_DECISIONS = frozenset(
    {"approved", "rejected", "changes_requested"}
)
_SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class RequirementApprovalAttempt:
    trace_id: str
    repository_digest: str
    stage_run_id: str
    approval_id: str
    subject_digest: str
    requested_at: str
    request_seq: int
    request_turn_id: Optional[str]
    decision: Optional[str]
    resolved_at: Optional[str]
    resolution_turn_id: Optional[str]
    later_user_turn: bool
    terminal: bool


class RequirementApprovalGate:
    @staticmethod
    def _turn_was_stopped(
        *, events: Sequence[Dict[str, Any]], turn_id: str, after_seq: int
    ) -> bool:
        return any(
            event.get("seq", 0) > after_seq
            and event.get("event_type") == "turn.stopped"
            and event.get("actor") == "agent"
            and event.get("source") == "codex_hook"
            and event.get("stage") == "clarify"
            and event.get("correlation", {}).get("turn_id") == turn_id
            for event in events
        )

    @staticmethod
    def require_later_user_turn(
        *, events: Sequence[Dict[str, Any]], request_event: Dict[str, Any]
    ) -> str:
        request_turn = request_event.get("correlation", {}).get("turn_id")
        request_seq = request_event.get("seq")
        if not isinstance(request_turn, str) or not isinstance(request_seq, int):
            raise ContractError(
                "Requirement approval request lacks user-turn evidence."
            )
        later_prompts = [
            event
            for event in events
            if event.get("seq", 0) > request_seq
            and event.get("event_type") == "turn.prompt_submitted"
        ]
        if not later_prompts:
            raise ContractError(
                "Requirement approval requires a later user-authored turn."
            )
        latest = max(later_prompts, key=lambda event: event.get("seq", 0))
        latest_turn = latest.get("correlation", {}).get("turn_id")
        prompt_evidence = [
            event
            for event in later_prompts
            if event.get("correlation", {}).get("turn_id") == latest_turn
        ]
        trusted = (
            isinstance(latest_turn, str)
            and latest_turn != request_turn
            and len(prompt_evidence) == 1
            and latest.get("actor") == "user"
            and latest.get("source") == "codex_hook"
            and latest.get("stage") == "clarify"
            and not RequirementApprovalGate._turn_was_stopped(
                events=events,
                turn_id=latest_turn,
                after_seq=latest["seq"],
            )
        )
        if not trusted:
            raise ContractError(
                "Requirement approval requires a later user-authored turn."
            )
        return latest_turn

    @classmethod
    def project(
        cls, records: Iterable[Dict[str, Any]]
    ) -> List[RequirementApprovalAttempt]:
        attempts = []
        for record in records:
            metadata = record["metadata"]
            events = record["events"]
            trace_id = metadata["trace_id"]
            raw_requests = [
                event
                for event in events
                if event.get("event_type") == "approval.requested"
            ]
            requests = [
                event
                for event in raw_requests
                if event.get("stage") == "clarify"
                and event.get("payload", {}).get("approval_kind")
                == "clarify.requirements"
            ]
            for request in requests:
                payload = request.get("payload", {})
                correlation = request.get("correlation", {})
                approval_id = payload.get("approval_id")
                subject_digest = payload.get("subject_digest")
                stage_run_id = correlation.get("stage_run_id")
                if not all(
                    isinstance(item, str)
                    for item in (approval_id, subject_digest, stage_run_id)
                ):
                    continue
                same_requests = [
                    event
                    for event in raw_requests
                    if event.get("payload", {}).get("approval_id") == approval_id
                ]
                starts = [
                    event
                    for event in events
                    if event.get("event_type") == "workflow.stage.started"
                    and event.get("correlation", {}).get("stage_run_id")
                    == stage_run_id
                    and event.get("seq", 0) < request.get("seq", 0)
                ]
                resolutions = [
                    event
                    for event in events
                    if event.get("event_type") == "approval.resolved"
                    and event.get("payload", {}).get("approval_id") == approval_id
                ]
                terminals = [
                    event
                    for event in events
                    if event.get("event_type") == "workflow.stage.completed"
                    and event.get("payload", {}).get("approval_id") == approval_id
                ]
                start_repository = (
                    starts[0].get("payload", {}).get("repository")
                    if len(starts) == 1
                    else ""
                )
                request_turn_events = [
                    event
                    for event in events
                    if event.get("event_type") == "turn.prompt_submitted"
                    and event.get("correlation", {}).get("turn_id")
                    == correlation.get("turn_id")
                    and event.get("seq", 0) < request.get("seq", 0)
                ]
                request_prompts = [
                    event
                    for event in request_turn_events
                    if event.get("actor") == "user"
                    and event.get("source") == "codex_hook"
                    and event.get("stage") == "clarify"
                ]
                structural = (
                    len(same_requests) == len(starts) == 1
                    and len(request_turn_events) == len(request_prompts) == 1
                    and len(resolutions) <= 1
                    and len(terminals) <= 1
                    and starts[0].get("seq", 0)
                    < request_prompts[0].get("seq", 0)
                    < request.get("seq", 0)
                    and not cls._turn_was_stopped(
                        events=[
                            event
                            for event in events
                            if event.get("seq", 0) < request.get("seq", 0)
                        ],
                        turn_id=correlation.get("turn_id"),
                        after_seq=request_prompts[0].get("seq", 0),
                    )
                    and request.get("actor") == "runtime"
                    and request.get("source") == "devkit_runtime"
                    and starts[0].get("stage") == "clarify"
                    and starts[0].get("actor") == "runtime"
                    and starts[0].get("source") == "devkit_runtime"
                    and payload.get("subject_kind") == "requirement_document"
                    and _SHA256_DIGEST.fullmatch(subject_digest) is not None
                    and isinstance(start_repository, str)
                    and _SHA256_DIGEST.fullmatch(start_repository) is not None
                    and starts[0].get("payload", {}).get("stage") == "clarify"
                )
                resolution = resolutions[0] if len(resolutions) == 1 else None
                terminal = terminals[0] if len(terminals) == 1 else None
                valid = cls._valid_attempt(
                    events=events,
                    request=request,
                    resolution=resolution,
                    terminal=terminal,
                    structural=structural,
                )
                attempts.append(
                    RequirementApprovalAttempt(
                        trace_id=trace_id,
                        repository_digest=start_repository,
                        stage_run_id=stage_run_id,
                        approval_id=approval_id,
                        subject_digest=subject_digest,
                        requested_at=request.get("timestamp", ""),
                        request_seq=request.get("seq", 0),
                        request_turn_id=request.get("correlation", {}).get(
                            "turn_id"
                        ),
                        decision=(resolution or {}).get("payload", {}).get(
                            "decision"
                        ),
                        resolved_at=(resolution or {}).get("timestamp"),
                        resolution_turn_id=(resolution or {}).get(
                            "correlation", {}
                        ).get("turn_id"),
                        later_user_turn=valid["later_user_turn"],
                        terminal=valid["terminal"],
                    )
                )
        return sorted(
            attempts,
            key=lambda item: (item.requested_at, item.trace_id, item.request_seq),
        )

    @classmethod
    def _valid_attempt(
        cls, *, events, request, resolution, terminal, structural
    ):
        invalid = {"later_user_turn": False, "terminal": False}
        if not structural or resolution is None:
            return invalid
        requested = request["payload"]
        resolved = resolution.get("payload", {})
        run_id = request["correlation"]["stage_run_id"]
        resolution_matches = (
            resolution.get("stage") == "clarify"
            and resolution.get("actor") == "runtime"
            and resolution.get("source") == "devkit_runtime"
            and resolution.get("seq", 0) > request.get("seq", 0)
            and resolution.get("correlation", {}).get("stage_run_id") == run_id
            and resolved.get("approval_id") == requested["approval_id"]
            and resolved.get("approval_kind") == "clarify.requirements"
            and resolved.get("subject_kind") == "requirement_document"
            and resolved.get("subject_digest") == requested["subject_digest"]
            and resolved.get("decision") in REQUIREMENT_APPROVAL_DECISIONS
        )
        if not resolution_matches:
            return invalid
        try:
            later_turn = cls.require_later_user_turn(
                events=[
                    event
                    for event in events
                    if event.get("seq", 0) < resolution["seq"]
                ],
                request_event=request,
            )
        except ContractError:
            return invalid
        later_matches = (
            resolution.get("correlation", {}).get("turn_id") == later_turn
        )
        if terminal is None:
            return {"later_user_turn": later_matches, "terminal": False}
        completed = terminal.get("payload", {})
        terminal_matches = (
            later_matches
            and terminal.get("stage") == "clarify"
            and terminal.get("actor") == "runtime"
            and terminal.get("source") == "devkit_runtime"
            and terminal.get("seq", 0) > resolution["seq"]
            and terminal.get("correlation", {}).get("stage_run_id") == run_id
            and completed.get("stage") == "clarify"
            and completed.get("approval_id") == requested["approval_id"]
            and completed.get("subject_kind") == "requirement_document"
            and completed.get("subject_digest") == requested["subject_digest"]
        )
        return {"later_user_turn": later_matches, "terminal": terminal_matches}

    def require_approved(
        self,
        *,
        trace_store: ExecutionTraceStore,
        repository_root: Path,
        reference: RequirementDocRef,
    ) -> RequirementApprovalAttempt:
        repository = repository_digest(str(repository_root))
        if not isinstance(repository, str):
            raise RequirementApprovalError(
                "requirements.repository_invalid",
                "Repository identity is unavailable.",
            )
        return self.require_subject_approved(
            trace_store=trace_store,
            repository_digest_value=repository,
            subject_digest=reference.subject_digest(),
        )

    def require_subject_approved(
        self,
        *,
        trace_store: ExecutionTraceStore,
        repository_digest_value: str,
        subject_digest: str,
        approval_id: Optional[str] = None,
    ) -> RequirementApprovalAttempt:
        if (
            not isinstance(repository_digest_value, str)
            or _SHA256_DIGEST.fullmatch(repository_digest_value) is None
            or not isinstance(subject_digest, str)
            or _SHA256_DIGEST.fullmatch(subject_digest) is None
            or (approval_id is not None and not isinstance(approval_id, str))
        ):
            raise RequirementApprovalError(
                "requirements.approval_invalid", "Approval lookup is invalid."
            )
        candidates = [
            attempt
            for attempt in self.project(trace_store.iter_records())
            if attempt.repository_digest == repository_digest_value
            and attempt.subject_digest == subject_digest
            and (approval_id is None or attempt.approval_id == approval_id)
            and attempt.decision == "approved"
            and attempt.later_user_turn
            and attempt.terminal
        ]
        if not candidates:
            raise RequirementApprovalError(
                "requirements.approval_missing",
                "The exact requirement document has no completed approval.",
            )
        return candidates[-1]
