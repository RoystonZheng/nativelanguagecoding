"""Fail-open runtime event recording for plugin-owned decision points."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Dict, List, Optional
import uuid

from .collector import CollectorService, error_fingerprint, validate_trace_root
from .contracts import utc_now
from .execution_trace import ExecutionTraceStore, repository_digest


TRACE_DIRECTORY = "execution-traces"


def append_health_error(
    root: Path, error: BaseException, event_type: Optional[str]
) -> None:
    try:
        if root.is_symlink():
            return
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        path = root / "collector-errors.jsonl"
        record = {
            "timestamp": utc_now(),
            "event_name": event_type,
            "error_fingerprint": error_fingerprint(error),
        }
        encoded = (
            json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")
            + b"\n"
        )
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_APPEND
            | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            if stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.fchmod(descriptor, 0o600)
                os.write(descriptor, encoded)
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        return


class RuntimeTrace:
    """Append validated runtime facts without changing the owning operation result."""

    def __init__(self, state_root: Path, session_id: str, cwd: str):
        self.state_root = state_root
        self.root = state_root / TRACE_DIRECTORY
        self.session_id = session_id
        self.cwd = cwd

    @classmethod
    def for_current_session(
        cls, state_root: Path, cwd: str
    ) -> Optional["RuntimeTrace"]:
        session_id = os.environ.get("CODEX_THREAD_ID") or os.environ.get(
            "CODEX_TASK_ID"
        )
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        return cls(state_root, session_id, cwd)

    def ensure_workflow_started(self, *, timestamp: Optional[str] = None) -> None:
        if self._has_event("workflow.started"):
            return
        self.emit(
            "workflow.started",
            payload={"workflow_name": "coding-sop"},
            timestamp=timestamp,
        )

    def ensure_stage_started(
        self,
        stage: str,
        *,
        stage_run_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> Optional[str]:
        """Return the active run for a stage, creating one when necessary."""
        active = self.active_stage_run_id(stage)
        if active is not None and (stage_run_id is None or stage_run_id == active):
            return active
        selected = stage_run_id or str(uuid.uuid4())
        self.emit(
            "workflow.stage.started",
            stage=stage,
            correlation={"stage_run_id": selected},
            payload={
                "stage": stage,
                "repository": repository_digest(self.cwd),
                **(payload or {}),
            },
            timestamp=timestamp,
        )
        return (
            selected
            if self._has_stage_event(stage, selected, "workflow.stage.started")
            else None
        )

    def active_stage_run_id(self, stage: str) -> Optional[str]:
        terminal = {
            "workflow.stage.completed",
            "workflow.stage.failed",
            "workflow.stage.skipped",
        }
        closed = set()
        repository = repository_digest(self.cwd)
        for event in reversed(self.events()):
            if event.get("stage") != stage:
                continue
            run_id = event.get("correlation", {}).get("stage_run_id")
            if not run_id:
                continue
            if event["event_type"] in terminal:
                closed.add(run_id)
            elif (
                event["event_type"] == "workflow.stage.started"
                and run_id not in closed
                and event.get("payload", {}).get("repository") == repository
            ):
                return run_id
        return None

    def emit_once(
        self,
        event_type: str,
        *,
        stage: Optional[str] = None,
        correlation: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
        match_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        expected_correlation = correlation or {}
        expected_payload = match_payload or {}
        for event in self.events():
            if event["event_type"] != event_type or event.get("stage") != stage:
                continue
            if any(
                event.get("correlation", {}).get(key) != value
                for key, value in expected_correlation.items()
            ):
                continue
            if any(
                event.get("payload", {}).get(key) != value
                for key, value in expected_payload.items()
            ):
                continue
            return
        self.emit(
            event_type,
            stage=stage,
            correlation=correlation,
            payload=payload,
            timestamp=timestamp,
        )

    def emit(
        self,
        event_type: str,
        *,
        stage: Optional[str] = None,
        correlation: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        try:
            if not self.state_root.is_dir():
                return
            validate_trace_root(self.root, self.cwd)
            CollectorService(ExecutionTraceStore(self.root)).emit_runtime(
                {
                    "session_id": self.session_id,
                    "event_type": event_type,
                    "stage": stage,
                    "correlation": correlation or {},
                    "payload": payload or {},
                    "cwd": self.cwd,
                    "timestamp": timestamp,
                }
            )
        except Exception as error:
            self.record_error(error, event_type)

    def record_error(self, error: BaseException, event_type: str) -> None:
        try:
            ExecutionTraceStore(self.root).mark_capture_status(
                self.session_id, "partial"
            )
        except Exception:
            pass
        append_health_error(self.root, error, event_type)

    def events(self) -> List[Dict[str, Any]]:
        try:
            if not self.state_root.is_dir():
                return []
            validate_trace_root(self.root, self.cwd)
            loaded = ExecutionTraceStore(self.root).load_session(self.session_id)
            return loaded["events"] if loaded else []
        except Exception as error:
            append_health_error(self.root, error, "trace.load")
            return []

    def _has_stage_event(self, stage: str, run_id: str, event_type: str) -> bool:
        return any(
            event["event_type"] == event_type
            and event.get("stage") == stage
            and event.get("correlation", {}).get("stage_run_id") == run_id
            for event in self.events()
        )

    def _has_event(self, event_type: str) -> bool:
        return any(event["event_type"] == event_type for event in self.events())
