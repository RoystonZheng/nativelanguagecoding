"""Versioned stdin/stdout JSON adapter for S0 `/init`."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import sys
from typing import Any, Dict, Optional
import uuid

from .contracts import SCHEMA_VERSION, utc_now
from .docs_init_observer import DocsInitObserver
from .errors import AiNativeDevError, ContractError, StoreError
from .init_engine import InitEngine
from .instruction_selection import validate_instruction_selection
from .persistence import FilesystemAtomicPersistence
from .repository import RepositoryInspector
from .runtime_trace import RuntimeTrace
from .state_store import TaskStateStore


MINIMUM_PYTHON = (3, 9)
MAX_REQUEST_BYTES = 1024 * 1024
MAX_ERROR_MESSAGE = 300


def _runtime_error(code: str, message: str, retryable: bool) -> Dict[str, Any]:
    bounded_message = " ".join(message.split())[:MAX_ERROR_MESSAGE]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "runtime_error",
        "code": code,
        "message": bounded_message,
        "retryable": retryable,
    }


def _preflight() -> None:
    if sys.version_info < MINIMUM_PYTHON:
        raise AiNativeDevError(
            "runtime.unsupported_python",
            "AI Native DevKit requires Python 3.9 or newer.",
            retryable=False,
        )
    if platform.system() not in {"Darwin", "Linux"}:
        raise AiNativeDevError(
            "runtime.unsupported_host",
            "AI Native DevKit init supports local macOS and Linux hosts in S0.",
            retryable=False,
        )


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
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("CLI request schema version is incompatible.")
    if value.get("operation") != "init":
        raise ContractError("CLI operation must be init.")
    repository = value.get("repository")
    if (
        not isinstance(repository, dict)
        or not isinstance(repository.get("path"), str)
        or not repository["path"]
    ):
        raise ContractError("CLI request repository.path must be a non-empty string.")
    if not isinstance(value.get("user_request"), str) or not value["user_request"]:
        raise ContractError("CLI request user_request must be a non-empty string.")
    if value.get("task_id") is not None and (
        not isinstance(value["task_id"], str) or not value["task_id"]
    ):
        raise ContractError(
            "CLI request task_id must be a non-empty string when provided."
        )
    if value.get("choice") is not None and value["choice"] not in {
        "reuse",
        "new",
        "cancel",
    }:
        raise ContractError("CLI request choice is invalid.")
    if value.get("authority_grant") is not None and not isinstance(
        value["authority_grant"], dict
    ):
        raise ContractError("CLI request authority_grant must be an object.")
    if value.get("authority_grant") is not None:
        authority = value["authority_grant"]
        if not {
            "capabilities",
            "scopes",
            "confirmed_at",
            "provenance",
        }.issubset(authority):
            raise ContractError("CLI authority_grant is missing a required field.")
        if "granted_by" in authority:
            raise ContractError("CLI authority_grant cannot set granted_by.")
        if not isinstance(authority["capabilities"], list) or not isinstance(
            authority["scopes"], list
        ):
            raise ContractError("CLI authority bounds must be lists.")
        if not isinstance(authority["confirmed_at"], str) or not isinstance(
            authority["provenance"], str
        ):
            raise ContractError("CLI authority metadata must be strings.")
    if value.get("instruction_selection") is not None:
        validate_instruction_selection(value["instruction_selection"])
        if not value.get("task_id"):
            raise ContractError("Instruction selection requires the exact blocked task_id.")
    return value


def _state_root() -> Path:
    configured = os.environ.get("AI_NATIVE_DEVKIT_STATE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return (
        Path.home() / ".codex" / "state" / "ai-native-devkit" / "v1"
    ).resolve(strict=False)


def _validate_state_root(
    state_root: Path, repository_path: str, inspector: RepositoryInspector
) -> None:
    state_root = state_root.expanduser().resolve(strict=False)
    classification = inspector.classify(repository_path)
    target = Path(classification.root or classification.requested_path).resolve()
    plugin_root = Path(__file__).resolve().parents[2]
    for protected_root in (target, plugin_root):
        if (
            state_root == protected_root
            or state_root.is_relative_to(protected_root)
            or protected_root.is_relative_to(state_root)
        ):
            raise AiNativeDevError(
                "persistence.unsafe_state_root",
                "Task state must remain outside the Target Repository and plugin installation.",
                retryable=False,
            )


def _task_id(request: Dict[str, Any]) -> str:
    explicit = request.get("task_id")
    if explicit:
        return explicit
    caller = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_TASK_ID")
    if caller:
        return caller
    return str(uuid.uuid4())


def _init_result_payload(
    response: Dict[str, Any], request: Dict[str, Any]
) -> Dict[str, Any]:
    report = response["report"]
    payload = report["payload"]
    findings = payload.get("findings") or {}
    blocker = payload.get("blocker") or {}
    return {
        "phase": "context_inspection",
        "outcome": payload.get("outcome"),
        "gaps": payload.get("gaps") or [],
        "blocker_code": blocker.get("code"),
        "entry_docs_count": len(findings.get("entry_docs") or []),
        "repository_instructions_count": len(
            findings.get("repository_instructions") or []
        ),
        "verification_commands_count": len(
            findings.get("verification_commands") or []
        ),
        "choice": request.get("choice"),
        "authority_grant_present": request.get("authority_grant") is not None,
    }


def _start_init_trace(
    state_root: Path,
    request: Dict[str, Any],
    stage_run_id: str,
    started_at: str,
) -> Optional[RuntimeTrace]:
    trace = RuntimeTrace.for_current_session(
        state_root, request["repository"]["path"]
    )
    if trace is None:
        return None
    trace.ensure_workflow_started(timestamp=started_at)
    trace.ensure_stage_started(
        "init",
        stage_run_id=stage_run_id,
        payload={"phase": "context_and_project_docs"},
        timestamp=started_at,
    )
    return trace


def _record_init_failure(
    state_root: Path,
    request: Dict[str, Any],
    stage_run_id: str,
    started_at: str,
    error_code: str,
) -> None:
    trace = _start_init_trace(state_root, request, stage_run_id, started_at)
    if trace is not None:
        trace.emit(
            "workflow.stage.failed",
            stage="init",
            correlation={"stage_run_id": stage_run_id},
            payload={
                "stage": "init",
                "phase": "context_inspection",
                "error_code": error_code,
            },
        )


def _record_init_result(
    trace: RuntimeTrace,
    stage_run_id: str,
    request: Dict[str, Any],
    response: Dict[str, Any],
) -> None:
    correlation = {"stage_run_id": stage_run_id}
    choice = request.get("choice")
    if choice is not None:
        trace.emit_once(
            "approval.resolved",
            stage="init",
            correlation=correlation,
            payload={
                "approval_id": f"{stage_run_id}:init.choice",
                "approval_kind": "init.choice",
                "decision": choice,
            },
            match_payload={"approval_id": f"{stage_run_id}:init.choice"},
        )
    if request.get("authority_grant") is not None:
        trace.emit_once(
            "approval.resolved",
            stage="init",
            correlation=correlation,
            payload={
                "approval_id": f"{stage_run_id}:repository.read",
                "approval_kind": "repository.read",
                "decision": "approved",
            },
            match_payload={
                "approval_id": f"{stage_run_id}:repository.read"
            },
        )
    if response["kind"] == "choice_required":
        choices = response.get("choices") or []
        if choices:
            trace.emit_once(
                "approval.requested",
                stage="init",
                correlation=correlation,
                payload={
                    "approval_id": f"{stage_run_id}:init.choice",
                    "approval_kind": "init.choice",
                    "reason": response.get("reason"),
                    "choices": choices,
                },
                match_payload={"approval_id": f"{stage_run_id}:init.choice"},
            )
        else:
            trace.emit(
                "workflow.stage.skipped",
                stage="init",
                correlation=correlation,
                payload={"stage": "init", "reason": response.get("reason")},
            )
        return
    report_payload = response["report"]["payload"]
    blocker = report_payload.get("blocker") or {}
    if blocker.get("code") == "blocked.repository.read_authority":
        trace.emit_once(
            "approval.requested",
            stage="init",
            correlation=correlation,
            payload={
                "approval_id": f"{stage_run_id}:repository.read",
                "approval_kind": "repository.read",
                "capability": "repository.read",
            },
        )
    trace.emit_once(
        "init.context.inspected",
        stage="init",
        correlation=correlation,
        payload=_init_result_payload(response, request),
    )


def run() -> Dict[str, Any]:
    _preflight()
    request = _read_request()
    inspector = RepositoryInspector()
    state_root = _state_root()
    _validate_state_root(state_root, request["repository"]["path"], inspector)
    store = TaskStateStore(FilesystemAtomicPersistence(state_root))
    engine = InitEngine(store, inspector)
    task_id = _task_id(request)
    started_at = utc_now()
    stage_run_id = str(uuid.uuid4())

    def invoke(selected_task_id: str) -> Dict[str, Any]:
        return engine.run(
            task_id=selected_task_id,
            requested_path=request["repository"]["path"],
            user_request=request["user_request"],
            choice=request.get("choice"),
            authority_grant=request.get("authority_grant"),
            instruction_selection=request.get("instruction_selection"),
        )

    caller_identity = os.environ.get("CODEX_THREAD_ID") or os.environ.get(
        "CODEX_TASK_ID"
    )
    implicit_initial_request = (
        request.get("task_id") is None
        and bool(caller_identity)
        and request.get("choice") is None
        and request.get("authority_grant") is None
        and request.get("instruction_selection") is None
    )

    def invoke_with_identity_policy() -> Dict[str, Any]:
        try:
            return invoke(task_id)
        except StoreError as error:
            if not implicit_initial_request:
                raise
            if error.code == "rejected.concurrent_update" and error.retryable:
                try:
                    return invoke(task_id)
                except StoreError as retry_error:
                    if retry_error.code != "init.task_target_mismatch":
                        raise
            elif error.code != "init.task_target_mismatch":
                raise
            return invoke(str(uuid.uuid4()))

    try:
        response = invoke_with_identity_policy()
    except AiNativeDevError as error:
        _record_init_failure(
            state_root, request, stage_run_id, started_at, error.code
        )
        raise
    except Exception:
        _record_init_failure(
            state_root,
            request,
            stage_run_id,
            started_at,
            "runtime.internal_error",
        )
        raise
    observer = DocsInitObserver.for_current_session(
        state_root, Path(request["repository"]["path"])
    )
    ready_for_docs = response["kind"] == "choice_required" or (
        response["kind"] == "report"
        and response["report"]["payload"]["outcome"] == "ready"
    )
    if observer is not None and ready_for_docs:
        try:
            stage_run_id = observer.prepare()["stage_run_id"]
        except Exception as error:
            trace = RuntimeTrace.for_current_session(
                state_root, request["repository"]["path"]
            )
            if trace is not None:
                trace.record_error(error, "init.docs.prepare")
    trace = _start_init_trace(state_root, request, stage_run_id, started_at)
    if trace is not None:
        try:
            _record_init_result(trace, stage_run_id, request, response)
        except Exception as error:
            trace.record_error(error, "init.runtime_projection")
    if (
        observer is not None
        and response["kind"] == "choice_required"
        and not (response.get("choices") or [])
    ):
        try:
            observer.abandon()
        except Exception as error:
            if trace is not None:
                trace.record_error(error, "init.docs.abandon")
    return response


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
            "AI Native DevKit init failed without committing a report.",
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
