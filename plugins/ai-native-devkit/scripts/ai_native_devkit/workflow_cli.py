"""Versioned JSON CLI for exact requirement-document artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Dict

from .cli import MAX_ERROR_MESSAGE, MAX_REQUEST_BYTES, _preflight
from .collector import validate_trace_root
from .collector_cli import trace_root
from .contracts import RequirementDocRef, SCHEMA_VERSION
from .errors import AiNativeDevError, ContractError, StoreError
from .execution_trace import ExecutionTraceStore, repository_digest
from .requirement_document import (
    DOCUMENT_LANGUAGES,
    RequirementDocumentLoader,
    RequirementDocumentWriter,
    RequirementSource,
)


OPERATIONS = {"requirements.write", "requirements.load"}
ALLOWED_FIELDS = {
    "requirements.write": {
        "schema_version",
        "operation",
        "session_id",
        "cwd",
        "title",
        "clarified_requirements",
        "sources",
        "supersedes",
        "document_language",
    },
    "requirements.load": {
        "schema_version",
        "operation",
        "session_id",
        "cwd",
        "reference",
        "purpose",
    },
}
REQUIRED_FIELDS = {
    "requirements.write": {
        "schema_version",
        "operation",
        "cwd",
        "title",
        "clarified_requirements",
    },
    "requirements.load": {
        "schema_version",
        "operation",
        "cwd",
        "reference",
        "purpose",
    },
}


def _runtime_error(code: str, message: str, retryable: bool) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "runtime_error",
        "code": code,
        "message": " ".join(message.split())[:MAX_ERROR_MESSAGE],
        "retryable": retryable,
    }


def _required_text(request: Dict[str, Any], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ContractError(f"Workflow operation requires a valid {field}.")
    return value


def _absolute_cwd(request: Dict[str, Any]) -> Path:
    value = _required_text(request, "cwd")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ContractError("Workflow operation cwd must be absolute.")
    return candidate


def _validate_request_fields(request: Dict[str, Any]) -> None:
    operation = request.get("operation")
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ContractError("CLI workflow operation is invalid.")
    if request.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("CLI request schema version is incompatible.")
    if set(request) - ALLOWED_FIELDS[operation]:
        raise ContractError("CLI workflow operation contains unknown fields.")
    if not REQUIRED_FIELDS[operation].issubset(request):
        raise ContractError("CLI workflow operation is missing required fields.")
    _absolute_cwd(request)
    supplied_session = request.get("session_id")
    if supplied_session is not None and (
        not isinstance(supplied_session, str) or not supplied_session.strip()
    ):
        raise ContractError("Workflow session_id must be a non-empty string.")
    if operation == "requirements.write":
        _required_text(request, "title")
        _required_text(request, "clarified_requirements")
        language = request.get("document_language", "zh-CN")
        if not isinstance(language, str) or language not in DOCUMENT_LANGUAGES:
            raise ContractError("Document language must be zh-CN or en.")
        sources = request.get("sources", [])
        if not isinstance(sources, list) or len(sources) > 64:
            raise ContractError(
                "Requirement sources must be a list of at most 64 items."
            )
        if request.get("supersedes") is not None and not isinstance(
            request["supersedes"], dict
        ):
            raise ContractError("supersedes must be an object when provided.")
    else:
        if not isinstance(request.get("reference"), dict):
            raise ContractError("Requirement reference must be an object.")
        purpose = _required_text(request, "purpose")
        if purpose not in {"design", "clarify_revision", "docs_promotion"}:
            raise ContractError("Requirement load purpose is invalid.")


def _read_request() -> Dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ContractError("CLI request exceeds the maximum supported size.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError("CLI request is not valid UTF-8 JSON.") from error
    if not isinstance(value, dict):
        raise ContractError("CLI request must be a JSON object.")
    _validate_request_fields(value)
    return value


def _session_id(request: Dict[str, Any]) -> str:
    host = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_TASK_ID")
    supplied = request.get("session_id")
    if host and supplied is not None and supplied != host:
        raise ContractError("Session identity does not match the active Codex task.")
    value = host or supplied
    if not isinstance(value, str) or not value.strip():
        raise ContractError("Workflow operation requires a Codex session identity.")
    return value


def _require_active_run(
    store: ExecutionTraceStore, session_id: str, stage: str, cwd: Path
) -> str:
    message = f"Workflow operation requires one active {stage} run for this repository."
    try:
        records = list(store.iter_records())
    except StoreError as error:
        raise ContractError(message) from error
    matching = [
        record
        for record in records
        if record.get("metadata", {}).get("session_id") == session_id
    ]
    if len(matching) != 1 or not isinstance(matching[0].get("events"), list):
        raise ContractError(message)
    events = matching[0]["events"]
    expected_repository = repository_digest(str(cwd))
    starts = [
        event
        for event in events
        if event.get("event_type") == "workflow.stage.started"
        and event.get("stage") == stage
        and event.get("actor") == "runtime"
        and event.get("source") == "devkit_runtime"
        and event.get("payload", {}).get("stage") == stage
        and event.get("payload", {}).get("repository") == expected_repository
        and isinstance(event.get("correlation", {}).get("stage_run_id"), str)
    ]
    active = []
    for start in starts:
        run_id = start["correlation"]["stage_run_id"]
        terminal = any(
            event.get("event_type")
            in {
                "workflow.stage.completed",
                "workflow.stage.failed",
                "workflow.stage.skipped",
            }
            and event.get("correlation", {}).get("stage_run_id") == run_id
            and event.get("seq", 0) > start.get("seq", 0)
            for event in events
        )
        if not terminal:
            active.append(run_id)
    if len(active) != 1:
        raise ContractError(message)
    return active[0]


def run() -> Dict[str, Any]:
    request = _read_request()
    cwd = _absolute_cwd(request)
    session_id = _session_id(request)
    _preflight()
    root = trace_root()
    validate_trace_root(root, str(cwd))
    trace_store = ExecutionTraceStore(root)
    operation = request["operation"]

    if operation == "requirements.write":
        _require_active_run(trace_store, session_id, "clarify", cwd)
        sources = tuple(
            RequirementSource.from_dict(value)
            for value in request.get("sources", [])
        )
        supersedes = (
            RequirementDocRef.from_dict(request["supersedes"])
            if request.get("supersedes") is not None
            else None
        )
        reference = RequirementDocumentWriter().write_and_commit(
            repository_root=cwd,
            title=request["title"],
            clarified_requirements=request["clarified_requirements"],
            sources=sources,
            supersedes=supersedes,
            document_language=request.get("document_language", "zh-CN"),
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "requirement_document",
            "reference": reference.to_dict(),
        }

    purpose = request["purpose"]
    if purpose == "clarify_revision":
        _require_active_run(trace_store, session_id, "clarify", cwd)
    elif purpose == "docs_promotion":
        _require_active_run(trace_store, session_id, "sync-docs", cwd)
    reference = RequirementDocRef.from_dict(request["reference"])
    markdown = RequirementDocumentLoader().load_approved(
        trace_store=trace_store,
        repository_root=cwd,
        reference=reference,
        enforce_repository_source_freshness=(purpose != "clarify_revision"),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "approved_requirement_document",
        "reference": reference.to_dict(),
        "markdown": markdown,
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
            "AI Native DevKit workflow operation failed without a partial commit.",
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
