"""Runtime event and verification boundary for the Coding SOP workflow."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, Optional, Sequence
import uuid

from .cli import MAX_ERROR_MESSAGE, MAX_REQUEST_BYTES, _preflight
from .collector_cli import trace_root
from .collector import CollectorService, validate_trace_root
from .contracts import RequirementDocRef, SCHEMA_VERSION
from .docs_hook import DocsImpactHook
from .docs_sync_observer import DocsSyncObserver
from .errors import (
    AiNativeDevError,
    ContractError,
    RequirementApprovalError,
    RequirementDocumentError,
)
from .execution_trace import ExecutionTraceStore, repository_digest
from .requirement_approval import RequirementApprovalGate
from .requirement_document import RequirementDocumentLoader
from .user_decisions import GATES, UserDecisions


OPERATIONS = {
    "workflow.route",
    "workflow.finish",
    "workflow.user_decision",
    "stage.start",
    "stage.complete",
    "stage.fail",
    "approval.request",
    "approval.resolve",
    "verification.complete",
    "docs.classify",
    "trace.load",
}
INTENTS = frozenset({"development", "debug"})
TIERS = frozenset({"fast", "standard", "strict"})
ROUTES = frozenset({"lightweight", "development", "debug"})
CHANGE_KINDS = frozenset({"feature", "bug", "test", "refactor", "temporary", "contract"})
STAGES = frozenset(
    {"init", "clarify", "design", "plan", "execute", "debug", "verify", "sync-docs"}
)
RUNTIME_STARTABLE_STAGES = frozenset(
    {"clarify", "design", "plan", "execute", "debug", "verify", "sync-docs"}
)
RUNTIME_TERMINAL_STAGES = frozenset(
    {"clarify", "design", "plan", "execute", "debug", "sync-docs"}
)
APPROVAL_KIND_BY_STAGE = {
    "clarify": "clarify.requirements",
    "design": "design.solution",
    "plan": "plan.implementation",
}
APPROVAL_KINDS_BY_STAGE = {
    "clarify": frozenset({"clarify.requirements"}),
    "design": frozenset({"design.solution"}),
    "plan": frozenset({"plan.implementation"}),
    "sync-docs": frozenset({"docs.semantic_write"}),
}
APPROVAL_DECISIONS = frozenset({"approved", "rejected", "changes_requested"})
DOCUMENT_SUBJECT_KIND_BY_STAGE = {
    "design": "design_document",
    "plan": "plan_document",
}
SOURCE_SUBJECT_BY_STAGE = {
    "plan": ("design", "design_document"),
    "execute": ("plan", "plan_document"),
}
SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
TERMINAL_STAGE_EVENTS = frozenset(
    {"workflow.stage.completed", "workflow.stage.failed", "workflow.stage.skipped"}
)
ROUTE_SKIPS = {
    "lightweight": ("clarify", "design", "plan", "debug"),
    "development": ("debug",),
    "debug": ("clarify", "design", "plan", "execute"),
}
REQUIRED_STAGE_ORDER_BY_ROUTE = {
    "lightweight": ("init", "execute", "verify", "sync-docs"),
    "development": (
        "init",
        "clarify",
        "design",
        "plan",
        "execute",
        "verify",
        "sync-docs",
    ),
    "debug": ("init", "debug", "verify", "sync-docs"),
}


def _runtime_error(code: str, message: str, retryable: bool) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "runtime_error",
        "code": code,
        "message": " ".join(message.split())[:MAX_ERROR_MESSAGE],
        "retryable": retryable,
    }


def _read_request() -> Dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ContractError("Runtime request exceeds the maximum size.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError("Runtime request is not valid UTF-8 JSON.") from error
    if not isinstance(value, dict):
        raise ContractError("Runtime request must be an object.")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("Runtime request schema version is incompatible.")
    operation = value.get("operation")
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ContractError("Runtime operation is invalid.")
    return value


def _session_id(request: Dict[str, Any]) -> str:
    host = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_TASK_ID")
    supplied = request.get("session_id")
    if host and supplied is not None and supplied != host:
        raise ContractError("Session identity does not match the active Codex task.")
    value = host or supplied
    if not isinstance(value, str) or not value.strip():
        raise ContractError("Runtime operation requires a Codex session identity.")
    return value


def _validate_route(request: Dict[str, Any]) -> None:
    intent = request.get("intent")
    tier = request.get("workflow_tier")
    route = request.get("route")
    change_kind = request.get("change_kind")
    if (
        intent not in INTENTS
        or tier not in TIERS
        or route not in ROUTES
        or change_kind not in CHANGE_KINDS
    ):
        raise ContractError("Workflow route fields are invalid.")
    if intent == "debug" and route != "debug":
        raise ContractError("Debug intent must use the debug route.")
    if intent == "debug" and change_kind != "bug":
        raise ContractError("Debug intent must classify the change as bug.")
    if intent == "development" and change_kind == "bug":
        raise ContractError("Bug work must use the debug intent.")
    if intent == "development" and (
        (tier == "fast" and route != "lightweight")
        or (tier != "fast" and route != "development")
    ):
        raise ContractError("Development intent, tier, and route are inconsistent.")


def _verification_payload(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or value.get("result") not in {"pass", "fail"}:
        raise ContractError("Verification completion requires pass or fail result.")
    payload = {"passed": value["result"] == "pass"}
    for field in ("criteria_total", "criteria_passed", "remaining_risks_count"):
        item = value.get(field)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise ContractError(f"Verification {field} must be a non-negative integer.")
        payload[field] = item
    if payload["criteria_passed"] > payload["criteria_total"]:
        raise ContractError("Verification passed criteria exceed the total.")
    if payload["passed"] and payload["criteria_passed"] != payload["criteria_total"]:
        raise ContractError("Passing verification requires every criterion to pass.")
    candidate = value.get("candidate_revision")
    if not isinstance(candidate, str) or not candidate.strip():
        raise ContractError("Verification requires candidate_revision.")
    payload["candidate_revision"] = candidate
    return payload


def _workflow_context(store: ExecutionTraceStore, session_id: str) -> Dict[str, Any]:
    loaded = store.load_session(session_id)
    if loaded is None:
        return {}
    for event in reversed(loaded["events"]):
        if event["event_type"] == "workflow.route.selected":
            return event.get("payload", {})
    return {}


def _has_workflow_start(store: ExecutionTraceStore, session_id: str) -> bool:
    loaded = store.load_session(session_id)
    return bool(
        loaded
        and any(
            event["event_type"] == "workflow.started" for event in loaded["events"]
        )
    )


def _events(store: ExecutionTraceStore, session_id: str) -> list[Dict[str, Any]]:
    loaded = store.load_session(session_id)
    return loaded["events"] if loaded else []


def _stage_run_event(
    store: ExecutionTraceStore,
    session_id: str,
    stage_run_id: str,
    event_types: frozenset[str],
) -> Optional[Dict[str, Any]]:
    return next(
        (
            event
            for event in reversed(_events(store, session_id))
            if event["event_type"] in event_types
            and event.get("correlation", {}).get("stage_run_id") == stage_run_id
        ),
        None,
    )


def _active_stage_run(
    store: ExecutionTraceStore,
    session_id: str,
    stage: str,
    cwd: Optional[str] = None,
) -> Optional[str]:
    closed = set()
    repository = repository_digest(cwd)
    for event in reversed(_events(store, session_id)):
        if event.get("stage") != stage:
            continue
        run_id = event.get("correlation", {}).get("stage_run_id")
        if not run_id:
            continue
        if event["event_type"] in TERMINAL_STAGE_EVENTS:
            closed.add(run_id)
        elif (
            event["event_type"] == "workflow.stage.started"
            and run_id not in closed
            and (
                repository is None
                or event.get("payload", {}).get("repository") == repository
            )
        ):
            return run_id
    return None


def _ensure_workflow_start(
    collector: CollectorService,
    store: ExecutionTraceStore,
    session_id: str,
    cwd: Optional[str],
) -> None:
    if not _has_workflow_start(store, session_id):
        collector.emit_runtime(
            {
                "session_id": session_id,
                "event_type": "workflow.started",
                "cwd": cwd,
                "payload": {"workflow_name": "coding-sop"},
            }
        )


def _start_stage(
    collector: CollectorService,
    store: ExecutionTraceStore,
    session_id: str,
    stage: str,
    cwd: Optional[str],
    *,
    stage_run_id: Optional[str] = None,
    source_subject_digest: Optional[str] = None,
) -> Dict[str, Any]:
    if stage not in STAGES:
        raise ContractError("Workflow stage is invalid.")
    active = _active_stage_run(store, session_id, stage, cwd)
    if active is not None:
        if stage == "sync-docs" and cwd:
            DocsSyncObserver(
                trace_root().parent,
                session_id,
                Path(cwd),
                active,
            ).prepare()
        event = _stage_run_event(
            store, session_id, active, frozenset({"workflow.stage.started"})
        )
        existing_source = event.get("payload", {}).get("source_subject_digest")
        if existing_source != source_subject_digest and (
            existing_source is not None or source_subject_digest is not None
        ):
            raise ContractError(
                "Active workflow stage has a different source document subject."
            )
        return {"stage_run_id": active, "event": event}
    selected = stage_run_id or str(uuid.uuid4())
    if stage == "sync-docs":
        if not cwd:
            raise ContractError("Docs Sync stage requires a repository path.")
        DocsSyncObserver(
            trace_root().parent,
            session_id,
            Path(cwd),
            selected,
        ).prepare()
    _ensure_workflow_start(collector, store, session_id, cwd)
    payload = {"stage": stage, "repository": repository_digest(cwd)}
    if source_subject_digest is not None:
        payload["source_subject_digest"] = source_subject_digest
    result = collector.emit_runtime(
        {
            "session_id": session_id,
            "event_type": "workflow.stage.started",
            "stage": stage,
            "correlation": {"stage_run_id": selected},
            "cwd": cwd,
            "payload": payload,
        }
    )
    if stage == "verify":
        collector.emit_runtime(
            {
                "session_id": session_id,
                "event_type": "verification.started",
                "stage": stage,
                "correlation": {"stage_run_id": selected},
                "cwd": cwd,
                "payload": {},
            }
        )
    return {"stage_run_id": selected, "event": result["event"]}


def _require_active_stage(
    store: ExecutionTraceStore,
    session_id: str,
    stage: str,
    stage_run_id: Any,
    cwd: Optional[str],
) -> str:
    if not isinstance(stage_run_id, str) or not stage_run_id.strip():
        raise ContractError("Workflow stage transition requires stage_run_id.")
    start = _require_stage_repository(
        store, session_id, stage, stage_run_id, cwd
    )
    terminal = _stage_run_event(
        store, session_id, stage_run_id, TERMINAL_STAGE_EVENTS
    )
    if terminal is not None:
        raise ContractError("Workflow stage run is already terminal.")
    return stage_run_id


def _require_stage_repository(
    store: ExecutionTraceStore,
    session_id: str,
    stage: str,
    stage_run_id: str,
    cwd: Optional[str],
) -> Dict[str, Any]:
    start = _stage_run_event(
        store,
        session_id,
        stage_run_id,
        frozenset({"workflow.stage.started"}),
    )
    if start is None or start.get("stage") != stage:
        raise ContractError("Workflow stage_run_id does not identify this stage.")
    if start.get("payload", {}).get("repository") != repository_digest(cwd):
        raise ContractError(
            "Workflow stage_run_id belongs to a different repository."
        )
    return start


def _approval_event(
    store: ExecutionTraceStore,
    session_id: str,
    approval_id: str,
    event_type: str,
) -> Optional[Dict[str, Any]]:
    return next(
        (
            event
            for event in reversed(_events(store, session_id))
            if event["event_type"] == event_type
            and event.get("payload", {}).get("approval_id") == approval_id
        ),
        None,
    )


def _require_current_requirement_subject(
    request: Dict[str, Any], cwd: Optional[str]
) -> tuple[RequirementDocRef, str]:
    if not isinstance(cwd, str) or not cwd:
        raise ContractError("Requirement approval requires a repository path.")
    try:
        reference = RequirementDocRef.from_dict(request.get("subject"))
        RequirementDocumentLoader().verify_current(
            repository_root=Path(cwd), reference=reference
        )
    except (ContractError, RequirementDocumentError) as error:
        raise ContractError("Requirement approval subject is not current.") from error
    return reference, reference.subject_digest()


def _document_subject(
    request: Dict[str, Any], stage: str
) -> Optional[Dict[str, str]]:
    value = request.get("subject")
    if value is None:
        return None
    expected_kind = DOCUMENT_SUBJECT_KIND_BY_STAGE.get(stage)
    if (
        expected_kind is None
        or not isinstance(value, dict)
        or value.get("kind") != expected_kind
        or not isinstance(value.get("digest"), str)
        or SHA256_DIGEST.fullmatch(value["digest"]) is None
    ):
        raise ContractError("Workflow document approval subject is invalid.")
    return {
        "subject_kind": expected_kind,
        "subject_digest": value["digest"],
    }


def _source_subject_digest(
    request: Dict[str, Any], stage: str
) -> Optional[str]:
    value = request.get("source_subject_digest")
    if value is None:
        return None
    if stage not in SOURCE_SUBJECT_BY_STAGE or (
        not isinstance(value, str) or SHA256_DIGEST.fullmatch(value) is None
    ):
        raise ContractError("Workflow stage source document subject is invalid.")
    return value


def _require_completed_source_subject(
    store: ExecutionTraceStore,
    session_id: str,
    stage: str,
    cwd: Optional[str],
    source_subject_digest: str,
    *,
    before_seq: Optional[int] = None,
    require_latest: bool = True,
) -> Dict[str, Any]:
    source_stage, source_kind = SOURCE_SUBJECT_BY_STAGE[stage]
    completed = _latest_completed_source_stage(
        store, session_id, stage, cwd, before_seq=before_seq
    )
    if not require_latest:
        repository = repository_digest(cwd)
        completed = next(
            (
                event
                for event in reversed(_events(store, session_id))
                if event.get("event_type") == "workflow.stage.completed"
                and event.get("stage") == source_stage
                and event.get("payload", {}).get("repository") == repository
                and event.get("payload", {}).get("subject_kind") == source_kind
                and event.get("payload", {}).get("subject_digest")
                == source_subject_digest
                and (
                    before_seq is None
                    or event.get("seq", 0) < before_seq
                )
            ),
            None,
        )
    if completed is None or (
        completed.get("payload", {}).get("subject_kind") != source_kind
        or completed.get("payload", {}).get("subject_digest")
        != source_subject_digest
    ):
        raise ContractError(
            "Workflow stage source must match the completed upstream document subject."
        )
    stage_run_id = completed.get("correlation", {}).get("stage_run_id")
    if not isinstance(stage_run_id, str):
        raise ContractError("Completed upstream document subject is malformed.")
    if UserDecisions(_events(store, session_id), repository_digest(cwd)).waived(
        source_stage, stage_run_id, "approval"
    ):
        if before_seq is not None and completed["seq"] >= before_seq:
            raise ContractError("Upstream document must precede its downstream stage.")
        return completed
    approved = _require_exact_document_approval(
        store,
        session_id,
        stage_run_id,
        APPROVAL_KIND_BY_STAGE[source_stage],
        {
            "subject_kind": source_kind,
            "subject_digest": source_subject_digest,
        },
    )
    if completed.get("payload", {}).get("approval_id") != approved.get(
        "payload", {}
    ).get("approval_id"):
        raise ContractError(
            "Completed upstream document subject has different approval evidence."
        )
    completed_seq = completed.get("seq")
    approved_seq = approved.get("seq")
    if (
        not isinstance(completed_seq, int)
        or not isinstance(approved_seq, int)
        or approved_seq >= completed_seq
        or (before_seq is not None and completed_seq >= before_seq)
    ):
        raise ContractError(
            "Completed upstream document approval must precede its downstream stage."
        )
    return completed


def _latest_completed_source_stage(
    store: ExecutionTraceStore,
    session_id: str,
    stage: str,
    cwd: Optional[str],
    *,
    before_seq: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    source_stage, _ = SOURCE_SUBJECT_BY_STAGE[stage]
    repository = repository_digest(cwd)
    return next(
        (
            event
            for event in reversed(_events(store, session_id))
            if event.get("event_type") == "workflow.stage.completed"
            and event.get("stage") == source_stage
            and event.get("payload", {}).get("repository") == repository
            and (before_seq is None or event.get("seq", 0) < before_seq)
        ),
        None,
    )


def _require_stage_source_chain(
    store: ExecutionTraceStore,
    session_id: str,
    stage: str,
    stage_run_id: str,
    cwd: Optional[str],
    *,
    exact_output: bool = False,
    terminal_seq: Optional[int] = None,
) -> None:
    start = _require_stage_repository(
        store, session_id, stage, stage_run_id, cwd
    )
    start_seq = start.get("seq")
    if not isinstance(start_seq, int):
        raise ContractError("Workflow stage source start evidence is malformed.")
    source_subject_digest = start.get("payload", {}).get(
        "source_subject_digest"
    )
    decisions = UserDecisions(_events(store, session_id), repository_digest(cwd))
    if decisions.waived(stage, stage_run_id, "input") or (
        source_subject_digest is None
        and decisions.input_optional(stage, stage_run_id, before_seq=start_seq)
    ):
        return
    if source_subject_digest is None:
        latest_source = _latest_completed_source_stage(
            store,
            session_id,
            stage,
            cwd,
            before_seq=terminal_seq,
        )
        if exact_output or (
            latest_source is not None
            and isinstance(
                latest_source.get("payload", {}).get("subject_digest"), str
            )
        ):
            raise ContractError(
                "Exact document chain requires the downstream stage start to bind its source subject."
            )
        return
    if (
        not isinstance(source_subject_digest, str)
        or SHA256_DIGEST.fullmatch(source_subject_digest) is None
    ):
        raise ContractError("Workflow stage source document subject is invalid.")
    if stage == "plan" and not exact_output:
        raise ContractError(
            "Exact design source requires an exact plan document completion."
        )
    completed_source = _require_completed_source_subject(
        store,
        session_id,
        stage,
        cwd,
        source_subject_digest,
        before_seq=start_seq,
        require_latest=False,
    )
    if stage == "execute":
        plan_run_id = completed_source.get("correlation", {}).get("stage_run_id")
        plan_terminal_seq = completed_source.get("seq")
        if not isinstance(plan_run_id, str) or not isinstance(plan_terminal_seq, int):
            raise ContractError("Completed plan source evidence is malformed.")
        _require_stage_source_chain(
            store,
            session_id,
            "plan",
            plan_run_id,
            cwd,
            exact_output=True,
            terminal_seq=plan_terminal_seq,
        )


def _pending_generic_approval(
    events: Sequence[Dict[str, Any]], stage_run_id: str, approval_kind: str
) -> Optional[Dict[str, Any]]:
    for event in reversed(events):
        if (
            event.get("event_type") == "approval.requested"
            and event.get("correlation", {}).get("stage_run_id") == stage_run_id
            and event.get("payload", {}).get("approval_kind") == approval_kind
        ):
            approval_id = event.get("payload", {}).get("approval_id")
            if not isinstance(approval_id, str):
                raise ContractError("Pending approval request is malformed.")
            if not any(
                candidate.get("event_type") == "approval.resolved"
                and candidate.get("payload", {}).get("approval_id") == approval_id
                for candidate in events
            ):
                return event
    return None


def _require_document_request_turn(
    events: Sequence[Dict[str, Any]],
    stage: str,
    stage_run_id: str,
    approval_kind: str,
    subject: Dict[str, str],
    *,
    request_event: Optional[Dict[str, Any]] = None,
) -> str:
    cutoff = request_event.get("seq") if request_event is not None else None
    if request_event is not None and not isinstance(cutoff, int):
        raise ContractError("Workflow document approval request is malformed.")

    starts = [
        event
        for event in events
        if (cutoff is None or event.get("seq", 0) < cutoff)
        and event.get("event_type") == "workflow.stage.started"
        and event.get("stage") == stage
        and event.get("correlation", {}).get("stage_run_id") == stage_run_id
        and event.get("actor") == "runtime"
        and event.get("source") == "devkit_runtime"
    ]
    if len(starts) != 1:
        raise ContractError(
            "Workflow document approval requires its exact stage start."
        )
    start_seq = starts[0].get("seq")
    signals = [
        event
        for event in events
        if isinstance(start_seq, int)
        and event.get("seq", 0) > start_seq
        and (cutoff is None or event.get("seq", 0) < cutoff)
        and event.get("event_type") in {"turn.prompt_submitted", "turn.stopped"}
    ]
    if not signals:
        raise ContractError(
            "Workflow document approval requires active user-turn evidence."
        )
    prompt = max(signals, key=lambda event: event.get("seq", 0))
    turn_id = prompt.get("correlation", {}).get("turn_id")
    trusted = (
        prompt.get("event_type") == "turn.prompt_submitted"
        and prompt.get("actor") == "user"
        and prompt.get("source") == "codex_hook"
        and prompt.get("stage") == stage
        and isinstance(turn_id, str)
        and sum(
            1
            for event in signals
            if event.get("event_type") == "turn.prompt_submitted"
            and event.get("correlation", {}).get("turn_id") == turn_id
        )
        == 1
    )
    if not trusted:
        raise ContractError(
            "Workflow document approval requires an active user turn."
        )
    if request_event is not None:
        payload = request_event.get("payload", {})
        if not (
            request_event.get("event_type") == "approval.requested"
            and request_event.get("stage") == stage
            and request_event.get("actor") == "runtime"
            and request_event.get("source") == "devkit_runtime"
            and request_event.get("correlation", {}).get("stage_run_id")
            == stage_run_id
            and request_event.get("correlation", {}).get("turn_id") == turn_id
            and payload.get("approval_kind") == approval_kind
            and payload.get("subject_kind") == subject["subject_kind"]
            and payload.get("subject_digest") == subject["subject_digest"]
            and isinstance(payload.get("approval_id"), str)
        ):
            raise ContractError("Workflow document approval request is malformed.")
    return turn_id


def _require_document_later_turn(
    events: Sequence[Dict[str, Any]], request_event: Dict[str, Any]
) -> str:
    request_turn = request_event.get("correlation", {}).get("turn_id")
    request_seq = request_event.get("seq")
    stage = request_event.get("stage")
    if not isinstance(request_turn, str) or not isinstance(request_seq, int):
        raise ContractError(
            "Workflow document approval request lacks user-turn evidence."
        )
    later_signals = [
        event
        for event in events
        if event.get("seq", 0) > request_seq
        and event.get("event_type") in {"turn.prompt_submitted", "turn.stopped"}
    ]
    if not later_signals:
        raise ContractError(
            "Workflow document approval requires a later user-authored turn."
        )
    latest = max(later_signals, key=lambda event: event.get("seq", 0))
    turn_id = latest.get("correlation", {}).get("turn_id")
    trusted = (
        latest.get("event_type") == "turn.prompt_submitted"
        and latest.get("actor") == "user"
        and latest.get("source") == "codex_hook"
        and latest.get("stage") == stage
        and isinstance(turn_id, str)
        and turn_id != request_turn
    )
    if not trusted:
        raise ContractError(
            "Workflow document approval requires a later user-authored turn."
        )
    return turn_id


def _require_exact_document_approval(
    store: ExecutionTraceStore,
    session_id: str,
    stage_run_id: str,
    approval_kind: str,
    subject: Dict[str, str],
) -> Dict[str, Any]:
    events = _events(store, session_id)
    for resolved in reversed(events):
        payload = resolved.get("payload", {})
        if not (
            resolved.get("event_type") == "approval.resolved"
            and resolved.get("correlation", {}).get("stage_run_id") == stage_run_id
            and payload.get("approval_kind") == approval_kind
            and payload.get("decision") == "approved"
            and payload.get("subject_kind") == subject["subject_kind"]
            and payload.get("subject_digest") == subject["subject_digest"]
        ):
            continue
        requested = next(
            (
                event
                for event in events
                if event.get("event_type") == "approval.requested"
                and event.get("payload", {}).get("approval_id")
                == payload.get("approval_id")
            ),
            None,
        )
        if requested is None or not all(
            requested.get("payload", {}).get(field) == payload.get(field)
            for field in ("approval_kind", "subject_kind", "subject_digest")
        ):
            continue
        try:
            request_turn = _require_document_request_turn(
                events,
                resolved["stage"],
                stage_run_id,
                approval_kind,
                subject,
                request_event=requested,
            )
        except ContractError:
            continue
        resolution_turn = resolved.get("correlation", {}).get("turn_id")
        request_seq = requested.get("seq")
        resolution_seq = resolved.get("seq")
        prompts = [
            event
            for event in events
            if isinstance(request_seq, int)
            and isinstance(resolution_seq, int)
            and request_seq < event.get("seq", 0) < resolution_seq
            and event.get("event_type") == "turn.prompt_submitted"
            and event.get("correlation", {}).get("turn_id") == resolution_turn
        ]
        trusted_resolution = (
            resolved.get("actor") == "runtime"
            and resolved.get("source") == "devkit_runtime"
            and isinstance(resolution_turn, str)
            and resolution_turn != request_turn
            and len(prompts) == 1
            and prompts[0].get("actor") == "user"
            and prompts[0].get("source") == "codex_hook"
            and prompts[0].get("stage") == resolved.get("stage")
            and not any(
                event.get("event_type") == "turn.stopped"
                and prompts[0].get("seq", 0) < event.get("seq", 0) < resolution_seq
                and event.get("correlation", {}).get("turn_id") == resolution_turn
                for event in events
            )
        )
        if trusted_resolution:
            return resolved
    raise ContractError(
        "Workflow stage completion requires the exact approved document subject."
    )


def _require_runtime_approved_subject(
    *,
    store: ExecutionTraceStore,
    cwd: Optional[str],
    subject_digest: str,
    approval_id: Optional[str] = None,
):
    if not isinstance(cwd, str) or not cwd:
        raise ContractError("Clarify requires a repository path.")
    try:
        return RequirementApprovalGate().require_subject_approved(
            trace_store=store,
            repository_digest_value=repository_digest(cwd),
            subject_digest=subject_digest,
            approval_id=approval_id,
        )
    except (RequirementApprovalError, RequirementDocumentError) as error:
        raise ContractError("Clarify requires exact approved requirements.") from error


def _pending_approval_for_run(
    events: Sequence[Dict[str, Any]], stage_run_id: str, approval_kind: str
) -> Optional[Dict[str, Any]]:
    requests = [
        event
        for event in events
        if event.get("event_type") == "approval.requested"
        and event.get("correlation", {}).get("stage_run_id") == stage_run_id
        and event.get("payload", {}).get("approval_kind") == approval_kind
    ]
    unresolved = []
    for requested in requests:
        approval_id = requested.get("payload", {}).get("approval_id")
        if not isinstance(approval_id, str):
            raise ContractError("Pending approval request is malformed.")
        resolutions = [
            event
            for event in events
            if event.get("event_type") == "approval.resolved"
            and event.get("payload", {}).get("approval_id") == approval_id
        ]
        if len(resolutions) > 1:
            raise ContractError("Approval request has duplicate resolutions.")
        if not resolutions:
            try:
                _require_clarify_request_turn(
                    events, stage_run_id, request_event=requested
                )
            except ContractError:
                continue
            unresolved.append(requested)
    if len(unresolved) > 1:
        raise ContractError("Workflow stage has duplicate pending approvals.")
    return unresolved[0] if unresolved else None


def _approval_response(event: Dict[str, Any]) -> Dict[str, Any]:
    payload = event["payload"]
    correlation = event["correlation"]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "approval_request",
        "trace_id": event["trace_id"],
        "stage": event["stage"],
        "stage_run_id": correlation["stage_run_id"],
        "approval_id": payload["approval_id"],
    }


def _require_clarify_request_turn(
    events: Sequence[Dict[str, Any]],
    stage_run_id: str,
    *,
    request_event: Optional[Dict[str, Any]] = None,
) -> str:
    cutoff = request_event.get("seq") if request_event is not None else None
    if request_event is not None and not isinstance(cutoff, int):
        raise ContractError("Requirement approval request evidence is malformed.")

    def before_cutoff(event: Dict[str, Any]) -> bool:
        return cutoff is None or event.get("seq", 0) < cutoff

    starts = [
        event
        for event in events
        if before_cutoff(event)
        and event.get("event_type") == "workflow.stage.started"
        and event.get("stage") == "clarify"
        and event.get("actor") == "runtime"
        and event.get("source") == "devkit_runtime"
        and event.get("correlation", {}).get("stage_run_id") == stage_run_id
        and event.get("payload", {}).get("stage") == "clarify"
    ]
    if len(starts) != 1:
        raise ContractError(
            "Requirement approval requires its exact Clarify stage start."
        )
    start_seq = starts[0].get("seq")
    if not isinstance(start_seq, int):
        raise ContractError("Clarify stage start evidence is malformed.")
    if any(
        before_cutoff(event)
        and event.get("seq", 0) > start_seq
        and event.get("event_type") in TERMINAL_STAGE_EVENTS
        and event.get("correlation", {}).get("stage_run_id") == stage_run_id
        for event in events
    ):
        raise ContractError("Requirement approval requires an active Clarify run.")
    turn_signals = [
        event
        for event in events
        if before_cutoff(event)
        and event.get("seq", 0) > start_seq
        and event.get("event_type")
        in {"turn.prompt_submitted", "turn.stopped"}
    ]
    if not turn_signals:
        raise ContractError(
            "Requirement approval requires active user-turn evidence."
        )
    prompt = max(turn_signals, key=lambda event: event.get("seq", 0))
    turn_id = prompt.get("correlation", {}).get("turn_id")
    matching_prompts = [
        event
        for event in events
        if before_cutoff(event)
        and event.get("event_type") == "turn.prompt_submitted"
        and event.get("correlation", {}).get("turn_id") == turn_id
    ]
    trusted = (
        prompt.get("event_type") == "turn.prompt_submitted"
        and prompt.get("actor") == "user"
        and prompt.get("source") == "codex_hook"
        and prompt.get("stage") == "clarify"
        and isinstance(turn_id, str)
        and len(matching_prompts) == 1
    )
    if not trusted:
        raise ContractError(
            "Requirement approval requires an active Clarify user turn."
        )
    if request_event is not None:
        payload = request_event.get("payload", {})
        request_valid = (
            request_event.get("event_type") == "approval.requested"
            and request_event.get("stage") == "clarify"
            and request_event.get("actor") == "runtime"
            and request_event.get("source") == "devkit_runtime"
            and request_event.get("correlation", {}).get("stage_run_id")
            == stage_run_id
            and request_event.get("correlation", {}).get("turn_id") == turn_id
            and payload.get("approval_kind") == "clarify.requirements"
            and payload.get("subject_kind") == "requirement_document"
            and isinstance(payload.get("approval_id"), str)
            and isinstance(payload.get("subject_digest"), str)
        )
        if not request_valid:
            raise ContractError("Requirement approval request evidence is malformed.")
    return turn_id


def _current_turn_id(store: ExecutionTraceStore, session_id: str) -> Optional[str]:
    for event in reversed(_events(store, session_id)):
        if event["event_type"] == "turn.stopped":
            return None
        if event["event_type"] == "turn.prompt_submitted":
            turn_id = event.get("correlation", {}).get("turn_id")
            if turn_id:
                return turn_id
    return None


def _require_stage_approval(
    store: ExecutionTraceStore,
    session_id: str,
    stage_run_id: str,
    approval_kind: str,
) -> None:
    for event in reversed(_events(store, session_id)):
        if (
            event["event_type"] == "approval.resolved"
            and event.get("correlation", {}).get("stage_run_id") == stage_run_id
            and event.get("payload", {}).get("decision") == "approved"
            and event.get("payload", {}).get("approval_kind") == approval_kind
        ):
            return
    raise ContractError("Workflow stage completion requires approved user confirmation.")


def _docs_classification_for_run(
    store: ExecutionTraceStore, session_id: str, stage_run_id: str
) -> Optional[Dict[str, Any]]:
    for event in reversed(_events(store, session_id)):
        if (
            event["event_type"] == "docs.impact.classified"
            and event.get("correlation", {}).get("stage_run_id") == stage_run_id
        ):
            return event.get("payload", {})
    return None


def _skip_stage(
    collector: CollectorService,
    store: ExecutionTraceStore,
    session_id: str,
    stage: str,
    cwd: Optional[str],
    reason: str,
    *,
    stage_run_id: Optional[str] = None,
    decision_id: Optional[str] = None,
) -> Dict[str, Any]:
    if stage_run_id is not None:
        terminal = _stage_run_event(
            store, session_id, stage_run_id, TERMINAL_STAGE_EVENTS
        )
        if terminal is not None:
            if (
                terminal["event_type"] == "workflow.stage.skipped"
                and terminal.get("stage") == stage
            ):
                return terminal
            raise ContractError("Workflow stage run already has a different terminal result.")
    for event in _events(store, session_id):
        if (
            event["event_type"] == "workflow.stage.skipped"
            and event.get("stage") == stage
            and event.get("payload", {}).get("reason") == reason
            and event.get("payload", {}).get("repository")
            == repository_digest(cwd)
            and event.get("payload", {}).get("decision_id") == decision_id
            and (stage_run_id is None or event.get("correlation", {}).get("stage_run_id") == stage_run_id)
        ):
            return event
    stage_run_id = (
        stage_run_id
        or _active_stage_run(store, session_id, stage, cwd)
        or str(uuid.uuid4())
    )
    result = collector.emit_runtime(
        {
            "session_id": session_id,
            "event_type": "workflow.stage.skipped",
            "stage": stage,
            "correlation": {"stage_run_id": stage_run_id},
            "cwd": cwd,
            "payload": {
                "stage": stage,
                "reason": reason,
                "repository": repository_digest(cwd),
                **({"decision_id": decision_id} if decision_id else {}),
            },
        }
    )
    if stage == "sync-docs":
        collector.emit_runtime(
            {
                "session_id": session_id,
                "event_type": "docs.sync.skipped",
                "stage": stage,
                "correlation": {"stage_run_id": stage_run_id},
                "cwd": cwd,
                "payload": {"reason": reason},
            }
        )
    return result["event"]



def _apply_docs_hook(
    collector: CollectorService, store: ExecutionTraceStore, session_id: str,
    cwd: Optional[str], docs_hook: Dict[str, Any],
) -> None:
    if UserDecisions(_events(store, session_id), repository_digest(cwd)).skipped("sync-docs"):
        return
    if docs_hook["triggered"]:
        report = docs_hook["report"]
        docs_impact = report["docsImpact"]
        docs_stage_run_id = str(uuid.uuid4())
        if docs_impact != "NO_CHANGE":
            docs_stage_run_id = _start_stage(
                collector,
                store,
                session_id,
                "sync-docs",
                cwd,
            )["stage_run_id"]
        collector.emit_runtime(
            {
                "session_id": session_id,
                "event_type": "docs.impact.classified",
                "stage": "sync-docs",
                "correlation": (
                    {"stage_run_id": docs_stage_run_id}
                ),
                "cwd": cwd,
                "payload": {
                    "docsImpact": docs_impact,
                    "changedPaths": report.get("changedPaths", []),
                    "requiresUserConfirmation": report[
                        "requiresUserConfirmation"
                    ],
                },
            }
        )
        if docs_impact == "NO_CHANGE":
            _skip_stage(
                collector,
                store,
                session_id,
                "sync-docs",
                cwd,
                "no_change",
                stage_run_id=docs_stage_run_id,
            )
    else:
        _skip_stage(
            collector,
            store,
            session_id,
            "sync-docs",
            cwd,
            docs_hook["reason"],
        )

def _record_user_decision(
    collector: CollectorService, store: ExecutionTraceStore, session_id: str,
    cwd: Optional[str], request: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(cwd, str) or not cwd:
        raise ContractError("User direction requires a repository path.")
    events = _events(store, session_id)
    policy = UserDecisions(events, repository_digest(cwd))
    policy.require_open_route(allow_failed=True)
    stage, action = request.get("stage"), request.get("action")
    decision_id, directive = request.get("decision_id"), request.get("user_directive")
    if (not isinstance(stage, str) or stage not in STAGES
            or not isinstance(action, str) or action not in {"skip_stage", "waive_blocker"}):
        raise ContractError("User direction requires a valid stage and action.")
    if not isinstance(decision_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", decision_id) is None:
        raise ContractError("User direction requires a stable decision_id for retries.")
    if not isinstance(directive, dict) or directive.get("source") != "user" or any(
        not isinstance(directive.get(field), str) or not directive[field].strip()
        or len(directive[field]) > 500 for field in ("reference", "summary")
    ):
        raise ContractError("User direction requires the explicit user's message reference and bounded summary.")
    public = {"stage": stage, "action": action, "decision_id": decision_id,
              "user_directive": {key: directive[key] for key in ("source", "reference", "summary")}}
    gate = request.get("gate")
    if action == "waive_blocker":
        if not isinstance(gate, str) or gate not in GATES[stage] or not isinstance(request.get("blocker_code"), str) or re.fullmatch(
            r"[a-zA-Z0-9_.-]{1,128}", request["blocker_code"]
        ) is None:
            raise ContractError("Blocker waiver requires a supported gate and precise blocker_code.")
        public.update(gate=gate, blocker_code=request["blocker_code"])
    elif gate is not None or request.get("blocker_code") is not None:
        raise ContractError("Stage skip does not waive individual gates.")
    requested_run = request.get("stage_run_id")
    if requested_run is not None:
        if not isinstance(requested_run, str) or not requested_run:
            raise ContractError("User direction stage_run_id is invalid.")
        public["stage_run_id"] = requested_run
    existing = next((event for event in events if event["event_type"] == "workflow.user_decision"
                     and event["payload"].get("decision_id") == decision_id), None)
    if existing:
        if (existing["payload"].get("request_digest") != hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()
                or existing["payload"].get("route_event_id") != policy.route_id
                or existing["payload"].get("repository") != policy.repository):
            raise ContractError("User direction retry has different scope or content.")
        run_id = existing["correlation"]["stage_run_id"]
        event = existing
    else:
        active = _active_stage_run(store, session_id, stage, cwd)
        run_id = requested_run or active
        if run_id:
            start = _require_stage_repository(store, session_id, stage, run_id, cwd)
            if start["seq"] < policy.route["seq"] and stage != "init":
                raise ContractError("User direction cannot target a run from an earlier route.")
            terminal = _stage_run_event(store, session_id, run_id, TERMINAL_STAGE_EVENTS)
            if terminal:
                allowed = (action == "waive_blocker" and (
                    gate == "stage_result" and terminal["event_type"] == "workflow.stage.failed"
                    or gate == "verification" and stage == "verify"
                    and terminal.get("payload", {}).get("outcome") == "fail"))
                if action == "skip_stage" and requested_run is None:
                    run_id = None
                elif not allowed:
                    raise ContractError("User direction cannot rewrite a terminal stage run.")
            latest_stage = policy.latest_stage(stage)
            if requested_run and latest_stage and latest_stage.get("correlation", {}).get("stage_run_id") != requested_run:
                raise ContractError("User direction must target the current stage attempt.")
        if action == "waive_blocker" and run_id is None and gate != "input":
            raise ContractError("Blocker waiver requires the current stage_run_id.")
        if action == "waive_blocker" and stage == "init" and run_id is None:
            raise ContractError("Init input waiver requires its observed run; use skip_stage to omit Init.")
        run_id = run_id or str(uuid.uuid4())
        event = collector.emit_runtime({
            "session_id": session_id, "event_type": "workflow.user_decision", "stage": stage,
            "correlation": {"stage_run_id": run_id}, "cwd": cwd,
            "payload": {**public, "request_digest": hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest(), "repository": policy.repository,
                        "route_event_id": policy.route_id},
        })["event"]
    if action == "skip_stage":
        _skip_stage(collector, store, session_id, stage, cwd, "user_requested",
                    stage_run_id=run_id, decision_id=decision_id)
    elif _stage_run_event(store, session_id, run_id, frozenset({"workflow.stage.started"})) is None:
        _start_stage(collector, store, session_id, stage, cwd, stage_run_id=run_id)
    return {"schema_version": SCHEMA_VERSION, "kind": "user_decision", "trace_id": event["trace_id"],
            "decision": public, "stage_run_id": run_id,
            "status": "skipped" if action == "skip_stage" else "waived"}


def _validate_completed_workflow(
    store: ExecutionTraceStore, session_id: str, cwd: Optional[str]
) -> None:
    loaded = store.load_session(session_id)
    if loaded is None:
        raise ContractError("Workflow completion requires an execution trace.")
    repository = repository_digest(cwd)
    route_event = next(
        (
            event
            for event in reversed(loaded["events"])
            if event["event_type"] == "workflow.route.selected"
            and event.get("payload", {}).get("repository") == repository
        ),
        None,
    )
    if route_event is None:
        raise ContractError(
            "Workflow completion requires a route for this repository."
        )
    route = route_event.get("payload", {}).get("route")
    required_stage_order = REQUIRED_STAGE_ORDER_BY_ROUTE.get(route)
    if required_stage_order is None:
        raise ContractError("Workflow completion route is invalid.")
    required_stages = frozenset(required_stage_order)
    decisions = UserDecisions(loaded["events"], repository)

    starts: Dict[str, Dict[str, Any]] = {}
    terminals: Dict[str, Dict[str, Any]] = {}
    for event in loaded["events"]:
        if not event["event_type"].startswith("workflow.stage."):
            continue
        run_id = event.get("correlation", {}).get("stage_run_id")
        if not run_id:
            continue
        if event["event_type"] == "workflow.stage.started":
            if event.get("payload", {}).get("repository") == repository:
                starts[run_id] = event
        elif run_id in starts or (
            event["event_type"] == "workflow.stage.skipped"
            and event.get("payload", {}).get("repository") == repository
        ):
            terminals[run_id] = event

    completed_runs: Dict[str, list[str]] = {}
    skipped_runs: Dict[str, list[str]] = {}
    latest_runs = {}
    for event in loaded["events"]:
        if event["event_type"].startswith("workflow.stage.") and event.get("payload", {}).get("repository") == repository:
            latest_runs[event.get("stage")] = event.get("correlation", {}).get("stage_run_id")
    terminals = {run_id: terminal for run_id, terminal in terminals.items()
                 if latest_runs.get(terminal.get("stage")) == run_id}
    for run_id, terminal in terminals.items():
        stage = terminal.get("stage")
        if terminal["event_type"] == "workflow.stage.completed" or decisions.accepted_failure(terminal):
            completed_runs.setdefault(stage, []).append(run_id)
        elif terminal["event_type"] == "workflow.stage.skipped" and (
            "decision_id" not in terminal.get("payload", {}) or decisions.is_user_skip(terminal)
        ):
            skipped_runs.setdefault(stage, []).append(run_id)

    exempt = {
        stage: event for event in terminals.values()
        for stage in [event.get("stage")]
        if decisions.is_user_skip(event) and decisions.skipped(stage)
    }

    missing = []
    for stage in sorted(required_stages):
        if stage in exempt:
            satisfied = True
        elif stage == "sync-docs":
            satisfied = bool(completed_runs.get(stage) or skipped_runs.get(stage))
        else:
            satisfied = bool(completed_runs.get(stage))
        if not satisfied:
            missing.append(stage)
    if missing:
        raise ContractError(
            "Workflow completion requires terminal stages: " + ", ".join(missing)
        )

    previous_index = -1
    selected_terminals: Dict[str, Dict[str, Any]] = {}
    for stage in required_stage_order:
        if stage in exempt:
            selected_terminals[stage] = exempt[stage]
            continue
        candidates = []
        for index, event in enumerate(loaded["events"]):
            if index <= previous_index or event.get("stage") != stage:
                continue
            run_id = event.get("correlation", {}).get("stage_run_id")
            if run_id not in terminals or terminals[run_id] is not event:
                continue
            if event["event_type"] == "workflow.stage.completed" or decisions.accepted_failure(event) or (
                stage == "sync-docs"
                and event["event_type"] == "workflow.stage.skipped"
                and run_id in skipped_runs.get(stage, [])
            ):
                candidates.append(index)
        if not candidates:
            raise ContractError(
                "Workflow completion requires ordered stage transitions."
            )
        previous_index = min(candidates)
        selected_terminals[stage] = loaded["events"][previous_index]

    def waived(stage, gate):
        return decisions.waived(stage, selected_terminals[stage]["correlation"]["stage_run_id"], gate)

    bypassed = set(exempt) | {stage for stage, terminal in selected_terminals.items()
                              if decisions.accepted_failure(terminal)}

    if "clarify" in required_stages and "clarify" not in bypassed and not waived("clarify", "input"):
        clarify_terminals = [
            terminals[run_id]
            for run_id in completed_runs.get("clarify", [])
            if run_id in terminals
        ]
        clarify_terminal = clarify_terminals[-1] if clarify_terminals else None
        clarify_payload = (clarify_terminal or {}).get("payload", {})
        subject_digest = clarify_payload.get("subject_digest")
        approval_id = clarify_payload.get("approval_id")
        if not isinstance(subject_digest, str) or (not isinstance(approval_id, str) and not waived("clarify", "approval")):
            raise ContractError(
                "Workflow completion requires exact approved clarify requirements."
            )
        if not waived("clarify", "approval"):
            _require_runtime_approved_subject(
                store=store, cwd=cwd, subject_digest=subject_digest, approval_id=approval_id,
            )

    for stage, approval_kind in (
        ("design", "design.solution"),
        ("plan", "plan.implementation"),
    ):
        if stage not in required_stages or stage in bypassed or waived(stage, "approval"):
            continue
        if not any(
            event["event_type"] == "approval.resolved"
            and event.get("payload", {}).get("approval_kind") == approval_kind
            and event.get("payload", {}).get("decision") == "approved"
            and event.get("correlation", {}).get("stage_run_id")
            in completed_runs.get(stage, [])
            for event in loaded["events"]
        ):
            raise ContractError(
                f"Workflow completion requires approved {stage} confirmation."
            )
    for stage in ("plan", "execute"):
        if stage not in required_stages or stage in bypassed:
            continue
        terminal = selected_terminals[stage]
        stage_run_id = terminal.get("correlation", {}).get("stage_run_id")
        terminal_seq = terminal.get("seq")
        if not isinstance(stage_run_id, str) or not isinstance(terminal_seq, int):
            raise ContractError("Workflow document chain evidence is malformed.")
        payload = terminal.get("payload", {})
        exact_output = False
        if stage == "plan":
            subject_kind = payload.get("subject_kind")
            subject_digest = payload.get("subject_digest")
            if subject_kind is not None or subject_digest is not None:
                if (
                    subject_kind != DOCUMENT_SUBJECT_KIND_BY_STAGE[stage]
                    or not isinstance(subject_digest, str)
                    or SHA256_DIGEST.fullmatch(subject_digest) is None
                ):
                    raise ContractError(
                        "Workflow plan document completion subject is malformed."
                    )
                exact_output = True
        _require_stage_source_chain(
            store,
            session_id,
            stage,
            stage_run_id,
            cwd,
            exact_output=exact_output,
            terminal_seq=terminal_seq,
        )
    verification = next(
        (
            event
            for event in reversed(loaded["events"])
            if event["event_type"] == "verification.completed"
            and event.get("correlation", {}).get("stage_run_id")
            in completed_runs.get("verify", [])
        ),
        None,
    )
    if "verify" not in bypassed and not waived("verify", "verification") and (
        verification is None or verification.get("payload", {}).get("passed") is not True
    ):
        raise ContractError("Workflow completion requires passing verification.")
    if "sync-docs" in bypassed:
        return
    classified_index = None
    classification = None
    resolved_index = None
    docs_run_ids = set(completed_runs.get("sync-docs", [])) | set(
        skipped_runs.get("sync-docs", [])
    )
    for index, event in enumerate(loaded["events"]):
        run_id = event.get("correlation", {}).get("stage_run_id")
        if run_id not in docs_run_ids:
            continue
        if event["event_type"] == "docs.impact.classified":
            classified_index = index
            classification = event.get("payload", {})
            resolved_index = None
        elif event["event_type"] in {"docs.sync.completed", "docs.sync.skipped"}:
            resolved_index = index
    if (classified_index is None or not isinstance(classification, dict)) and not waived("sync-docs", "docs_classification"):
        raise ContractError("Workflow completion requires a Docs Hook result.")
    classification = classification or {}
    if classification.get("docsImpact") == "CONFLICT" and not waived("sync-docs", "docs_classification"):
        raise ContractError("Workflow completion is blocked by a Docs Hook conflict.")
    if classification.get("docsImpact") != "NO_CHANGE" and (
        resolved_index is None or (classified_index is not None and resolved_index < classified_index)
    ):
        raise ContractError(
            "Workflow completion requires the Docs action to be resolved."
        )


def run() -> Dict[str, Any]:
    _preflight()
    request = _read_request()
    session_id = _session_id(request)
    root = trace_root()
    candidate_cwd = request.get("cwd")
    if request["operation"] == "verification.complete" and isinstance(
        request.get("repository"), dict
    ):
        candidate_cwd = request["repository"].get("path")
    validate_trace_root(root, candidate_cwd)
    store = ExecutionTraceStore(root)
    collector = CollectorService(store)
    operation = request["operation"]
    cwd = request.get("cwd")

    if operation == "workflow.user_decision":
        return _record_user_decision(collector, store, session_id, cwd, request)

    if operation == "docs.classify":
        decisions = UserDecisions(_events(store, session_id), repository_digest(cwd))
        decisions.require_open_route()
        latest_verify = decisions.latest_stage("verify") or {}
        if not decisions.skipped("verify") and not decisions.waived(
            "verify", latest_verify.get("correlation", {}).get("stage_run_id"), "verification"
        ):
            raise ContractError("Independent Docs classification requires user-directed verification continuation.")
        baseline = request.get("baseline_revision")
        if not isinstance(cwd, str) or not cwd or not isinstance(baseline, str) or not baseline:
            raise ContractError("Docs classification requires cwd and baseline_revision.")
        if decisions.skipped("sync-docs"):
            return {"schema_version": SCHEMA_VERSION, "kind": "docs_classification",
                    "docs_hook": {"triggered": False, "reason": "user_requested_skip", "report": None}}
        workflow = decisions.route["payload"]
        docs_hook = DocsImpactHook().classify(repository=Path(cwd), baseline_revision=baseline,
                                            intent=workflow.get("intent"), change_kind=workflow.get("change_kind"))
        docs_hook["reason"] = "user_directed_continuation"
        _apply_docs_hook(collector, store, session_id, cwd, docs_hook)
        return {"schema_version": SCHEMA_VERSION, "kind": "docs_classification", "docs_hook": docs_hook}

    if operation == "workflow.route":
        _validate_route(request)
        _ensure_workflow_start(collector, store, session_id, cwd)
        result = collector.emit_runtime(
            {
                "session_id": session_id,
                "event_type": "workflow.route.selected",
                "cwd": cwd,
                "payload": {
                    "intent": request["intent"],
                    "workflow_tier": request["workflow_tier"],
                    "route": request["route"],
                    "change_kind": request["change_kind"],
                    "repository": repository_digest(cwd),
                },
            }
        )
        for skipped_stage in ROUTE_SKIPS[request["route"]]:
            _skip_stage(
                collector,
                store,
                session_id,
                skipped_stage,
                cwd,
                "route_not_required",
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "workflow_route",
            "trace_id": result["event"]["trace_id"],
            "route": result["event"]["payload"],
        }

    if operation == "stage.start":
        stage = request.get("stage")
        if stage not in RUNTIME_STARTABLE_STAGES:
            raise ContractError("Workflow stage is invalid.")
        source_subject_digest = _source_subject_digest(request, stage)
        active = _active_stage_run(store, session_id, stage, cwd)
        decisions = UserDecisions(_events(store, session_id), repository_digest(cwd))
        if active is None:
            if stage in SOURCE_SUBJECT_BY_STAGE and source_subject_digest is None and not decisions.input_optional(stage, ""):
                completed_source = _latest_completed_source_stage(
                    store, session_id, stage, cwd
                )
                if completed_source is not None and isinstance(
                    completed_source.get("payload", {}).get("subject_digest"), str
                ):
                    raise ContractError(
                        "Exact upstream document completion requires source_subject_digest."
                    )
            if source_subject_digest is not None:
                _require_completed_source_subject(
                    store,
                    session_id,
                    stage,
                    cwd,
                    source_subject_digest,
                )
        result = _start_stage(
            collector,
            store,
            session_id,
            stage,
            cwd,
            source_subject_digest=source_subject_digest,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "stage_transition",
            "trace_id": result["event"]["trace_id"],
            "stage": stage,
            "status": "started",
            "stage_run_id": result["stage_run_id"],
        }

    if operation in {"stage.complete", "stage.fail"}:
        stage = request.get("stage")
        if stage not in RUNTIME_TERMINAL_STAGES:
            raise ContractError("Workflow stage is invalid.")
        if (
            operation == "stage.complete"
            and stage == "clarify"
            and (not isinstance(cwd, str) or not cwd)
        ):
            raise ContractError("Requirement approval requires a repository path.")
        document_subject = (
            _document_subject(request, stage)
            if operation == "stage.complete"
            and stage in DOCUMENT_SUBJECT_KIND_BY_STAGE
            else None
        )
        stage_run_id = request.get("stage_run_id")
        decisions = UserDecisions(_events(store, session_id), repository_digest(cwd))
        approval_waived = decisions.waived(stage, stage_run_id, "approval")
        input_waived = decisions.waived(stage, stage_run_id, "input")
        if operation == "stage.complete" and stage == "clarify" and input_waived and request.get("subject") is not None:
            raise ContractError("User-directed Clarify input must not be labeled as an exact requirement subject.")
        terminal = _stage_run_event(
            store,
            session_id,
            stage_run_id,
            TERMINAL_STAGE_EVENTS,
        ) if isinstance(stage_run_id, str) else None
        if terminal is not None:
            _require_stage_repository(
                store, session_id, stage, stage_run_id, cwd
            )
            expected_type = (
                "workflow.stage.completed"
                if operation == "stage.complete"
                else "workflow.stage.failed"
            )
            if terminal["event_type"] != expected_type or terminal.get("stage") != stage:
                raise ContractError("Workflow stage run has a different terminal result.")
            if operation == "stage.complete" and stage == "clarify" and not input_waived:
                _, subject_digest = _require_current_requirement_subject(request, cwd)
                if terminal.get("payload", {}).get("subject_digest") != subject_digest:
                    raise ContractError(
                        "Clarify completion retry requires the original requirements."
                    )
            if operation == "stage.complete" and stage in DOCUMENT_SUBJECT_KIND_BY_STAGE:
                terminal_subject = {
                    "subject_kind": terminal.get("payload", {}).get("subject_kind"),
                    "subject_digest": terminal.get("payload", {}).get("subject_digest"),
                }
                terminal_is_exact = all(
                    isinstance(terminal_subject[field], str)
                    for field in ("subject_kind", "subject_digest")
                )
                if terminal_is_exact and document_subject != terminal_subject:
                    raise ContractError(
                        "Workflow stage completion retry requires the original document subject."
                    )
                if not terminal_is_exact and document_subject is not None:
                    raise ContractError(
                        "Legacy workflow stage completion cannot acquire a document subject."
                    )
            if operation == "stage.complete" and stage in SOURCE_SUBJECT_BY_STAGE:
                _require_stage_source_chain(
                    store,
                    session_id,
                    stage,
                    stage_run_id,
                    cwd,
                    exact_output=(
                        stage == "plan"
                        and isinstance(
                            terminal.get("payload", {}).get("subject_digest"), str
                        )
                    ),
                    terminal_seq=terminal.get("seq"),
                )
            event = terminal
        else:
            stage_run_id = _require_active_stage(
                store, session_id, stage, stage_run_id, cwd
            )
            document_approval = None
            if operation == "stage.complete" and stage in APPROVAL_KIND_BY_STAGE and not approval_waived:
                if stage in DOCUMENT_SUBJECT_KIND_BY_STAGE:
                    if document_subject is not None:
                        document_approval = _require_exact_document_approval(
                            store,
                            session_id,
                            stage_run_id,
                            APPROVAL_KIND_BY_STAGE[stage],
                            document_subject,
                        )
                    else:
                        if any(
                            event.get("event_type") == "approval.requested"
                            and event.get("correlation", {}).get("stage_run_id")
                            == stage_run_id
                            and isinstance(
                                event.get("payload", {}).get("subject_digest"), str
                            )
                            for event in _events(store, session_id)
                        ):
                            raise ContractError(
                                "Exact document approval completion requires its subject."
                            )
                        _require_stage_approval(
                            store,
                            session_id,
                            stage_run_id,
                            APPROVAL_KIND_BY_STAGE[stage],
                        )
                elif stage != "clarify":
                    _require_stage_approval(
                        store,
                        session_id,
                        stage_run_id,
                        APPROVAL_KIND_BY_STAGE[stage],
                    )
            if operation == "stage.complete" and stage in SOURCE_SUBJECT_BY_STAGE:
                _require_stage_source_chain(
                    store,
                    session_id,
                    stage,
                    stage_run_id,
                    cwd,
                    exact_output=(stage == "plan" and document_subject is not None),
                )
            docs_result = None
            if operation == "stage.complete" and stage == "sync-docs":
                classification = _docs_classification_for_run(
                    store, session_id, stage_run_id
                )
                if classification is None and not decisions.waived(stage, stage_run_id, "docs_classification"):
                    raise ContractError(
                        "Docs Sync completion requires its Docs Hook classification."
                    )
                if (classification or {}).get("docsImpact") == "SEMANTIC_REVIEW" and not approval_waived:
                    _require_stage_approval(
                        store,
                        session_id,
                        stage_run_id,
                        "docs.semantic_write",
                    )
                if not cwd:
                    raise ContractError(
                        "Docs Sync completion requires a repository path."
                    )
                try:
                    docs_result = DocsSyncObserver(
                        trace_root().parent, session_id, Path(cwd), stage_run_id,
                    ).complete()
                except ContractError as error:
                    if not decisions.waived(stage, stage_run_id, "docs_capture"):
                        raise
                    docs_result = {"fullCapture": False, "error_code": error.code}
                if docs_result.get("fullCapture") is not True and not decisions.waived(stage, stage_run_id, "docs_capture"):
                    raise ContractError(
                        "Docs Sync completion requires a complete document observation."
                    )
            event_type = (
                "workflow.stage.completed"
                if operation == "stage.complete"
                else "workflow.stage.failed"
            )
            payload = {
                "stage": stage,
                "repository": repository_digest(cwd),
            }
            if operation == "stage.complete" and stage == "clarify" and not input_waived:
                _, subject_digest = _require_current_requirement_subject(request, cwd)
                record = store.load_session(session_id)
                local_requests = [
                    event
                    for event in (record or {}).get("events", [])
                    if event.get("event_type") == "approval.requested"
                    and event.get("correlation", {}).get("stage_run_id")
                    == stage_run_id
                    and event.get("payload", {}).get("approval_kind")
                    == "clarify.requirements"
                ]
                run_attempts = [
                    attempt
                    for attempt in RequirementApprovalGate.project([record])
                    if attempt.stage_run_id == stage_run_id
                ] if record is not None else []
                if len(local_requests) != len(run_attempts):
                    raise ContractError(
                        "Clarify completion has malformed local approval evidence."
                    )
                attempt = max(
                    run_attempts, key=lambda item: item.request_seq, default=None
                )
                if approval_waived:
                    attempt = None
                elif attempt is not None:
                    if (
                        attempt.subject_digest != subject_digest
                        or attempt.decision != "approved"
                        or not attempt.later_user_turn
                    ):
                        raise ContractError(
                            "Clarify completion requires exact approved requirements."
                        )
                else:
                    attempt = _require_runtime_approved_subject(
                        store=store, cwd=cwd, subject_digest=subject_digest
                    )
                payload.update({
                    **({"approval_id": attempt.approval_id} if attempt else {}),
                    "subject_kind": "requirement_document",
                    "subject_digest": subject_digest,
                })
            if (
                operation == "stage.complete"
                and stage in DOCUMENT_SUBJECT_KIND_BY_STAGE
                and document_subject is not None
            ):
                payload.update(
                    {
                        **({"approval_id": document_approval["payload"]["approval_id"]} if document_approval else {}),
                        **document_subject,
                    }
                )
            if operation == "stage.complete":
                applied = [event["payload"]["decision_id"] for event in decisions.decisions
                           if event["correlation"].get("stage_run_id") == stage_run_id]
                if applied:
                    payload.update(outcome="completed_with_exceptions", user_decision_ids=applied)
            if operation == "stage.fail":
                error_code = request.get("error_code")
                if not isinstance(error_code, str) or not error_code.strip():
                    raise ContractError("Failed workflow stage requires error_code.")
                payload["error_code"] = error_code
            if operation == "stage.complete" and stage == "sync-docs":
                collector.emit_runtime(
                    {
                        "session_id": session_id,
                        "event_type": "docs.sync.completed",
                        "stage": stage,
                        "correlation": {"stage_run_id": stage_run_id},
                        "cwd": cwd,
                        "payload": {
                            "result": "completed",
                            **(docs_result or {}),
                        },
                    }
                )
            event = collector.emit_runtime(
                {
                    "session_id": session_id,
                    "event_type": event_type,
                    "stage": stage,
                    "correlation": {"stage_run_id": stage_run_id},
                    "cwd": cwd,
                    "payload": payload,
                }
            )["event"]
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "stage_transition",
            "trace_id": event["trace_id"],
            "stage": stage,
            "status": "completed" if operation == "stage.complete" else "failed",
            "stage_run_id": stage_run_id,
        }

    if operation == "approval.request":
        stage = request.get("stage")
        approval_kind = request.get("approval_kind")
        if stage not in STAGES or not isinstance(approval_kind, str) or not approval_kind.strip():
            raise ContractError("Approval request requires stage and approval_kind.")
        if approval_kind not in APPROVAL_KINDS_BY_STAGE.get(stage, frozenset()):
            raise ContractError("Approval kind is not valid for this workflow stage.")
        if approval_kind == "clarify.requirements" and (
            not isinstance(cwd, str) or not cwd
        ):
            raise ContractError("Requirement approval requires a repository path.")
        stage_run_id = _require_active_stage(
            store, session_id, stage, request.get("stage_run_id"), cwd
        )
        if approval_kind == "clarify.requirements":
            reference, subject_digest = _require_current_requirement_subject(
                request, cwd
            )
            pending = _pending_approval_for_run(
                _events(store, session_id), stage_run_id, approval_kind
            )
            if pending is not None:
                if pending["payload"].get("subject_digest") != subject_digest:
                    raise ContractError(
                        "Resolve the pending requirement approval before replacing it."
                    )
                return _approval_response(pending)
            turn_id = _require_clarify_request_turn(
                _events(store, session_id), stage_run_id
            )
            requested = collector.emit_runtime({
                "session_id": session_id,
                "event_type": "approval.requested",
                "stage": "clarify",
                "correlation": {"stage_run_id": stage_run_id, "turn_id": turn_id},
                "cwd": cwd,
                "payload": {
                    "approval_id": str(uuid.uuid4()),
                    "approval_kind": "clarify.requirements",
                    "subject_kind": "requirement_document",
                    "subject_digest": reference.subject_digest(),
                },
            })["event"]
            _require_clarify_request_turn(
                _events(store, session_id),
                stage_run_id,
                request_event=requested,
            )
            return _approval_response(requested)
        document_subject = (
            _document_subject(request, stage)
            if stage in DOCUMENT_SUBJECT_KIND_BY_STAGE
            else None
        )
        if document_subject is not None:
            events = _events(store, session_id)
            pending = _pending_generic_approval(
                events, stage_run_id, approval_kind
            )
            if pending is not None:
                pending_payload = pending.get("payload", {})
                if any(
                    pending_payload.get(field) != document_subject[field]
                    for field in ("subject_kind", "subject_digest")
                ):
                    raise ContractError(
                        "Resolve the pending document approval before replacing it."
                    )
                return _approval_response(pending)
            turn_id = _require_document_request_turn(
                events,
                stage,
                stage_run_id,
                approval_kind,
                document_subject,
            )
            requested = collector.emit_runtime(
                {
                    "session_id": session_id,
                    "event_type": "approval.requested",
                    "stage": stage,
                    "correlation": {
                        "stage_run_id": stage_run_id,
                        "turn_id": turn_id,
                    },
                    "cwd": cwd,
                    "payload": {
                        "approval_id": str(uuid.uuid4()),
                        "approval_kind": approval_kind,
                        **document_subject,
                    },
                }
            )["event"]
            _require_document_request_turn(
                _events(store, session_id),
                stage,
                stage_run_id,
                approval_kind,
                document_subject,
                request_event=requested,
            )
            return _approval_response(requested)
        pending = None
        for event in reversed(_events(store, session_id)):
            if (
                event["event_type"] == "approval.requested"
                and event.get("stage") == stage
                and event.get("correlation", {}).get("stage_run_id") == stage_run_id
                and event.get("payload", {}).get("approval_kind") == approval_kind
                and _approval_event(
                    store,
                    session_id,
                    event.get("payload", {}).get("approval_id", ""),
                    "approval.resolved",
                )
                is None
            ):
                pending = event
                break
        if pending is None:
            approval_id = str(uuid.uuid4())
            pending = collector.emit_runtime(
                {
                    "session_id": session_id,
                    "event_type": "approval.requested",
                    "stage": stage,
                    "correlation": {"stage_run_id": stage_run_id},
                    "cwd": cwd,
                    "payload": {
                        "approval_id": approval_id,
                        "approval_kind": approval_kind,
                    },
                }
            )["event"]
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "approval_request",
            "trace_id": pending["trace_id"],
            "stage": stage,
            "stage_run_id": stage_run_id,
            "approval_id": pending["payload"]["approval_id"],
        }

    if operation == "approval.resolve":
        approval_id = request.get("approval_id")
        decision = request.get("decision")
        if not isinstance(approval_id, str) or decision not in APPROVAL_DECISIONS:
            raise ContractError("Approval resolution requires approval_id and decision.")
        requested = _approval_event(
            store, session_id, approval_id, "approval.requested"
        )
        if requested is None:
            raise ContractError("Approval resolution has no matching request.")
        if requested.get("payload", {}).get("approval_kind") not in APPROVAL_KINDS_BY_STAGE.get(
            requested.get("stage"), frozenset()
        ):
            raise ContractError("Approval belongs to an unsupported workflow stage or kind.")
        resolved = _approval_event(
            store, session_id, approval_id, "approval.resolved"
        )
        stage_run_id = requested["correlation"]["stage_run_id"]
        _require_stage_repository(
            store, session_id, requested["stage"], stage_run_id, cwd
        )
        if resolved is not None and resolved.get("payload", {}).get("decision") != decision:
            raise ContractError("Approval already has a different resolution.")
        if resolved is None:
            _require_active_stage(
                store, session_id, requested["stage"], stage_run_id, cwd
            )
            approval_kind = requested.get("payload", {}).get("approval_kind")
            if approval_kind == "clarify.requirements":
                later_turn = RequirementApprovalGate.require_later_user_turn(
                    events=_events(store, session_id), request_event=requested
                )
                if _current_turn_id(store, session_id) != later_turn:
                    raise ContractError(
                        "Approval resolution requires an active later user turn."
                    )
                correlation = {
                    "stage_run_id": stage_run_id, "turn_id": later_turn
                }
            elif (
                requested.get("payload", {}).get("subject_kind")
                in DOCUMENT_SUBJECT_KIND_BY_STAGE.values()
                and isinstance(
                    requested.get("payload", {}).get("subject_digest"), str
                )
            ):
                later_turn = _require_document_later_turn(
                    _events(store, session_id), requested
                )
                if _current_turn_id(store, session_id) != later_turn:
                    raise ContractError(
                        "Approval resolution requires an active later user turn."
                    )
                correlation = {
                    "stage_run_id": stage_run_id,
                    "turn_id": later_turn,
                }
            else:
                requested_turn = requested.get("correlation", {}).get("turn_id")
                current_turn = _current_turn_id(store, session_id)
                if requested_turn is not None and current_turn in {None, requested_turn}:
                    raise ContractError(
                        "Approval resolution requires a later user-authored turn."
                    )
                correlation = {"stage_run_id": stage_run_id}
            resolution_payload = {
                "approval_id": approval_id,
                "approval_kind": requested["payload"]["approval_kind"],
                "decision": decision,
            }
            if approval_kind == "clarify.requirements" or (
                requested.get("payload", {}).get("subject_kind")
                in DOCUMENT_SUBJECT_KIND_BY_STAGE.values()
            ):
                resolution_payload.update({
                    "subject_kind": requested["payload"].get("subject_kind"),
                    "subject_digest": requested["payload"].get("subject_digest"),
                })
            resolved = collector.emit_runtime(
                {
                    "session_id": session_id,
                    "event_type": "approval.resolved",
                    "stage": requested["stage"],
                    "correlation": correlation,
                    "cwd": cwd,
                    "payload": resolution_payload,
                }
            )["event"]
        if requested.get("payload", {}).get("approval_kind") == "clarify.requirements":
            record = store.load_session(session_id)
            attempts = [
                attempt
                for attempt in RequirementApprovalGate.project([record])
                if attempt.approval_id == approval_id
            ] if record is not None else []
            if (
                len(attempts) != 1
                or attempts[0].decision != decision
                or not attempts[0].later_user_turn
            ):
                raise ContractError(
                    "Approval resolution did not occur in an active later user turn."
                )
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "approval_resolution",
            "trace_id": resolved["trace_id"],
            "stage": resolved["stage"],
            "stage_run_id": resolved["correlation"]["stage_run_id"],
            "approval_id": approval_id,
            "decision": decision,
        }

    if operation == "verification.complete":
        verification = _verification_payload(request.get("verification"))
        repository = request.get("repository")
        baseline = request.get("baseline_revision")
        if (
            not isinstance(repository, dict)
            or not isinstance(repository.get("path"), str)
            or not repository["path"]
            or not isinstance(baseline, str)
            or not baseline
        ):
            raise ContractError(
                "Verification completion requires repository.path and baseline_revision."
            )
        requested_stage_run_id = request.get("stage_run_id")
        if requested_stage_run_id is None:
            stage_result = _start_stage(
                collector,
                store,
                session_id,
                "verify",
                repository["path"],
            )
            stage_run_id = stage_result["stage_run_id"]
        else:
            stage_run_id = _require_active_stage(
                store,
                session_id,
                "verify",
                requested_stage_run_id,
                repository["path"],
            )
        result = collector.emit_runtime(
            {
                "session_id": session_id,
                "event_type": "verification.completed",
                "stage": "verify",
                "correlation": {"stage_run_id": stage_run_id},
                "cwd": repository["path"],
                "payload": verification,
            }
        )
        collector.emit_runtime(
            {
                "session_id": session_id,
                "event_type": "workflow.stage.completed",
                "stage": "verify",
                "correlation": {"stage_run_id": stage_run_id},
                "cwd": repository["path"],
                "payload": {
                    "stage": "verify",
                    "outcome": "pass" if verification["passed"] else "fail",
                    "repository": repository_digest(repository["path"]),
                },
            }
        )
        workflow = _workflow_context(store, session_id)
        docs_hook = DocsImpactHook().after_verification(
            repository=Path(repository["path"]),
            baseline_revision=baseline,
            verification_passed=verification["passed"],
            intent=workflow.get("intent"),
            change_kind=workflow.get("change_kind"),
        )
        if UserDecisions(_events(store, session_id), repository_digest(repository["path"])).skipped("sync-docs"):
            docs_hook = {"triggered": False, "reason": "user_requested_skip", "report": None}
        _apply_docs_hook(collector, store, session_id, repository["path"], docs_hook)
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "verification_completion",
            "trace_id": result["event"]["trace_id"],
            "stage_run_id": stage_run_id,
            "verification": verification,
            "docs_hook": docs_hook,
        }

    if operation == "workflow.finish":
        status = request.get("status")
        if status not in {"completed", "failed"}:
            raise ContractError("Workflow finish status is invalid.")
        if status == "completed":
            _validate_completed_workflow(store, session_id, cwd)
        decisions = UserDecisions(_events(store, session_id), repository_digest(cwd))
        payload: Dict[str, Any] = {"status": status, "repository": repository_digest(cwd)}
        if status == "completed" and decisions.decisions:
            payload.update(outcome="completed_with_exceptions",
                           user_decision_ids=[event["payload"]["decision_id"] for event in decisions.decisions])
        failure = request.get("failure")
        if status == "failed":
            if not isinstance(failure, dict):
                raise ContractError("Failed workflow requires structured failure.")
            payload["failure_type"] = failure.get("failure_type")
            payload["failure_stage"] = failure.get("failure_stage")
            payload["error_code"] = failure.get("error_code")
        result = collector.emit_runtime(
            {
                "session_id": session_id,
                "event_type": (
                    "workflow.completed" if status == "completed" else "workflow.failed"
                ),
                "cwd": cwd,
                "payload": payload,
            }
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "workflow_completion",
            "trace_id": result["event"]["trace_id"],
            "status": status,
        }

    loaded = store.load_session(session_id)
    if loaded is None:
        raise ContractError("Execution trace does not exist for this session.")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "execution_trace",
        "trace": loaded,
    }


def main() -> int:
    try:
        response = run()
        exit_status = 0
    except AiNativeDevError as error:
        response = _runtime_error(error.code, error.message, error.retryable)
        exit_status = 1
    except Exception:
        response = _runtime_error(
            "runtime.internal_error",
            "AI Native DevKit runtime event failed without changing workflow behavior.",
            retryable=False,
        )
        exit_status = 1
    json.dump(
        response,
        sys.stdout,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return exit_status
