"""Append-only execution traces for observable Codex and DevKit events."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional
import uuid

try:
    import fcntl
except ImportError:  # pragma: no cover - guarded by the CLI host preflight.
    fcntl = None

from . import __version__
from .contracts import utc_now
from .errors import ContractError, StoreError
from .state_store import sanitize_persisted_value


EVENT_SCHEMA_VERSION = "ai-native-devkit/execution-event/v1"
METADATA_SCHEMA_VERSION = "ai-native-devkit/execution-trace-metadata/v1"
SUMMARY_SCHEMA_VERSION = "ai-native-devkit/execution-trace-summary/v1"
COLLECTOR_VERSION = "1"
CAPTURE_STATUSES = frozenset({"active", "complete", "partial", "failed"})
EVENT_SOURCES = frozenset(
    {"codex_hook", "devkit_runtime", "codex_transcript_fallback"}
)
EVENT_ACTORS = frozenset({"user", "agent", "runtime", "system"})
EVENT_TYPES = frozenset(
    {
        "session.started",
        "session.ended",
        "turn.prompt_submitted",
        "turn.stopped",
        "tool.requested",
        "tool.completed",
        "tool.blocked",
        "tool.abandoned",
        "permission.requested",
        "subagent.started",
        "subagent.stopped",
        "context.compaction.started",
        "context.compaction.completed",
        "workflow.started",
        "workflow.completed",
        "workflow.failed",
        "workflow.route.selected",
        "workflow.user_decision",
        "workflow.stage.started",
        "workflow.stage.completed",
        "workflow.stage.failed",
        "workflow.stage.skipped",
        "approval.requested",
        "approval.resolved",
        "init.mode.selected",
        "init.context.inspected",
        "init.completed",
        "docs.read",
        "docs.impact.classified",
        "docs.sync.completed",
        "docs.sync.skipped",
        # Read compatibility for historical traces; no active Handoff producer.
        "handoff.check.requested",
        "handoff.check.resolved",
        "handoff.access.blocked",
        "handoff.completed",
        "handoff.updated",
        "verification.started",
        "verification.completed",
    }
)
CORRELATION_FIELDS = frozenset(
    {"turn_id", "tool_call_id", "stage_run_id", "subagent_id", "parent_event_id"}
)
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
MAX_EVENT_BYTES = 128 * 1024
MAX_EVENTS_BYTES = 64 * 1024 * 1024
MAX_TEXT = 1024


def _bounded_text(value: Any, field: str, *, nullable: bool = False) -> Optional[str]:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"Execution trace {field} must be non-empty text.")
    return " ".join(value.split())[:MAX_TEXT]


def _validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise ContractError("Execution trace timestamp is not canonical UTC.")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ContractError("Execution trace timestamp is invalid.") from error
    return value


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError("Execution trace numeric payload must be finite.")
        return value
    if isinstance(value, str):
        return " ".join(value.split())[:MAX_TEXT]
    raise ContractError("Execution trace payload values must be bounded scalars.")


def _safe_payload(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        raise ContractError("Execution trace payload is too deeply nested.")
    if isinstance(value, dict):
        if len(value) > 64 or any(not isinstance(key, str) for key in value):
            raise ContractError("Execution trace payload object is invalid.")
        return {
            _bounded_text(key, "payload key"): _safe_payload(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        if len(value) > 256:
            raise ContractError("Execution trace payload list is too large.")
        return [_safe_payload(item, depth=depth + 1) for item in value]
    return _safe_scalar(value)


def _validate_correlation(value: Any) -> Dict[str, Optional[str]]:
    if value is None:
        value = {}
    if not isinstance(value, dict) or not set(value).issubset(CORRELATION_FIELDS):
        raise ContractError("Execution trace correlation is invalid.")
    result: Dict[str, Optional[str]] = {}
    for key in sorted(CORRELATION_FIELDS):
        item = value.get(key)
        result[key] = _bounded_text(item, key, nullable=True)
    return result


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("Execution trace write made no progress.")
        remaining = remaining[written:]


def repository_digest(cwd: Optional[str]) -> Optional[str]:
    if not cwd:
        return None
    normalized = str(Path(cwd).expanduser().resolve(strict=False))
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _duration_ms(start: Optional[str], end: Optional[str]) -> Optional[int]:
    if not start or not end:
        return None
    left = datetime.fromisoformat(start[:-1] + "+00:00")
    right = datetime.fromisoformat(end[:-1] + "+00:00")
    return max(0, int((right - left).total_seconds() * 1000))


class ExecutionTraceStore:
    """Owns session mapping, append-only events, metadata, and projections."""

    def __init__(
        self,
        root: Path,
        *,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        event_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        clock: Callable[[], str] = utc_now,
    ):
        self.root = root.expanduser().absolute()
        self._id_factory = id_factory
        self._event_id_factory = event_id_factory
        self._clock = clock

    def append(
        self,
        *,
        session_id: str,
        event_type: str,
        actor: str,
        source: str,
        stage: Optional[str] = None,
        correlation: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session_id = _bounded_text(session_id, "session_id")
        if len(session_id) > 512:
            raise ContractError("Execution trace session_id is too long.")
        if event_type not in EVENT_TYPES:
            raise ContractError("Execution trace event_type is not registered.")
        if actor not in EVENT_ACTORS:
            raise ContractError("Execution trace actor is invalid.")
        if source not in EVENT_SOURCES:
            raise ContractError("Execution trace source is invalid.")
        if stage is not None:
            stage = _bounded_text(stage, "stage")
        normalized_correlation = _validate_correlation(correlation)
        normalized_payload = _safe_payload(sanitize_persisted_value(payload or {}))
        if not isinstance(normalized_payload, dict):  # pragma: no cover - caller type.
            raise ContractError("Execution trace payload must be an object.")
        observed_at = _validate_timestamp(timestamp or self._clock())
        normalized_context = _safe_payload(context or {})
        if not isinstance(normalized_context, dict):  # pragma: no cover - caller type.
            raise ContractError("Execution trace context must be an object.")

        self._ensure_layout()
        with self._session_lock(session_id):
            trace_id = self._ensure_trace(session_id, observed_at, normalized_context)
            events = self._read_events(trace_id)
            if stage is None:
                stage = self._active_stage(events)
            event = {
                "schema_version": EVENT_SCHEMA_VERSION,
                "trace_id": trace_id,
                "seq": len(events) + 1,
                "event_id": _bounded_text(self._event_id_factory(), "event_id"),
                "timestamp": observed_at,
                "event_type": event_type,
                "stage": stage,
                "actor": actor,
                "source": source,
                "correlation": normalized_correlation,
                "payload": normalized_payload,
            }
            encoded = _canonical_bytes(event)
            if len(encoded) > MAX_EVENT_BYTES:
                raise ContractError("Execution trace event exceeds the size limit.")
            self._append_event(trace_id, encoded)
            events.append(event)
            metadata = self._update_metadata(
                trace_id, events, event, normalized_context
            )
            summary = project_summary(metadata, events)
            self._atomic_write(self._summary_path(trace_id), _canonical_bytes(summary))
            return {"metadata": metadata, "event": event, "summary": summary}

    def trace_id_for_session(self, session_id: str) -> Optional[str]:
        session_id = _bounded_text(session_id, "session_id")
        path = self._session_path(session_id)
        if not path.exists():
            return None
        record = self._read_json(path)
        if record.get("session_id") != session_id:
            raise StoreError(
                "trace.session_index_invalid",
                "Execution trace session index is invalid.",
                retryable=False,
            )
        return _bounded_text(record.get("trace_id"), "trace_id")

    def load_metadata(self, trace_id: str) -> Dict[str, Any]:
        return self._read_json(self._metadata_path(self._validate_trace_id(trace_id)))

    def load_events(self, trace_id: str) -> List[Dict[str, Any]]:
        return self._read_events(self._validate_trace_id(trace_id))

    def load_summary(self, trace_id: str) -> Dict[str, Any]:
        return self._read_json(self._summary_path(self._validate_trace_id(trace_id)))

    def _load_session_unlocked(self, session_id: str) -> Optional[Dict[str, Any]]:
        trace_id = self.trace_id_for_session(session_id)
        if trace_id is None:
            return None
        return {
            "metadata": self.load_metadata(trace_id),
            "events": self.load_events(trace_id),
            "summary": self.load_summary(trace_id),
        }

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        session_id = _bounded_text(session_id, "session_id")
        if not self.root.exists():
            return None
        self._ensure_layout()
        with self._session_lock(session_id):
            return self._load_session_unlocked(session_id)

    def iter_records(self) -> Iterator[Dict[str, Any]]:
        self._ensure_layout()
        session_root = self.root / ".sessions"
        for path in sorted(session_root.iterdir(), key=lambda item: item.name):
            if path.name.startswith("."):
                try:
                    temporary_metadata = path.lstat()
                except OSError as error:
                    raise StoreError(
                        "trace.session_index_invalid",
                        "Execution trace session index is invalid.",
                        retryable=False,
                    ) from error
                if (
                    re.fullmatch(r"\.[0-9a-f]{64}\.json-[0-9a-f]{16}", path.name)
                    and stat.S_ISREG(temporary_metadata.st_mode)
                    and not stat.S_ISLNK(temporary_metadata.st_mode)
                ):
                    continue
                raise StoreError(
                    "trace.session_index_invalid",
                    "Execution trace session index is invalid.",
                    retryable=False,
                )
            try:
                metadata = path.lstat()
            except OSError as error:
                raise StoreError(
                    "trace.session_index_invalid",
                    "Execution trace session index is invalid.",
                    retryable=False,
                ) from error
            if (
                not path.name.endswith(".json")
                or stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
            ):
                raise StoreError(
                    "trace.session_index_invalid",
                    "Execution trace session index is invalid.",
                    retryable=False,
                )
            try:
                mapping = self._read_json(path)
            except StoreError as error:
                raise StoreError(
                    "trace.session_index_invalid",
                    "Execution trace session index is invalid.",
                    retryable=False,
                ) from error
            session_id = _bounded_text(mapping.get("session_id"), "session_id")
            trace_id = self._validate_trace_id(mapping.get("trace_id"))
            if path.name != self._session_key(session_id) + ".json":
                raise StoreError(
                    "trace.session_index_invalid",
                    "Execution trace session index is invalid.",
                    retryable=False,
                )
            with self._session_lock(session_id):
                try:
                    current = self._read_json(path)
                except StoreError as error:
                    raise StoreError(
                        "trace.session_index_invalid",
                        "Execution trace session index is invalid.",
                        retryable=False,
                    ) from error
                if current != {"session_id": session_id, "trace_id": trace_id}:
                    raise StoreError(
                        "trace.session_index_invalid",
                        "Execution trace session index changed during lookup.",
                        retryable=False,
                    )
                record = self._load_session_unlocked(session_id)
                if (
                    record is None
                    or record["metadata"].get("trace_id") != trace_id
                    or record["metadata"].get("session_id") != session_id
                    or record["summary"]
                    != project_summary(record["metadata"], record["events"])
                ):
                    raise StoreError(
                        "trace.session_index_invalid",
                        "Execution trace session index is invalid.",
                        retryable=False,
                    )
                detached = json.loads(json.dumps(record))
            yield detached

    def mark_capture_status(self, session_id: str, status: str) -> None:
        if status not in CAPTURE_STATUSES:
            raise ContractError("Execution trace capture status is invalid.")
        self._ensure_layout()
        with self._session_lock(session_id):
            trace_id = self.trace_id_for_session(session_id)
            if trace_id is None:
                return
            metadata = self.load_metadata(trace_id)
            metadata["capture_status"] = status
            self._atomic_write(self._metadata_path(trace_id), _canonical_bytes(metadata))
            events = self.load_events(trace_id)
            self._atomic_write(
                self._summary_path(trace_id),
                _canonical_bytes(project_summary(metadata, events)),
            )

    def _ensure_layout(self) -> None:
        self._reject_symlink_components(self.root)
        self._ensure_private_dir(self.root)
        self._ensure_private_dir(self.root / ".sessions")
        self._ensure_private_dir(self.root / ".locks")

    def _ensure_trace(
        self, session_id: str, timestamp: str, context: Dict[str, Any]
    ) -> str:
        existing = self.trace_id_for_session(session_id)
        if existing is not None:
            return existing
        trace_id = self._validate_trace_id(self._id_factory())
        trace_dir = self.root / trace_id
        self._ensure_private_dir(trace_dir)
        metadata = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "trace_id": trace_id,
            "session_id": session_id,
            "workflow_name": None,
            "workflow_version": "coding-sop/v1",
            "plugin_version": __version__,
            "agent_host": "codex",
            "agent_version": context.get("agent_version"),
            "model": context.get("model"),
            "repository": repository_digest(context.get("cwd")),
            "revision_start": context.get("revision_start"),
            "start_time": timestamp,
            "end_time": None,
            "collector_version": COLLECTOR_VERSION,
            "capture_status": "active",
        }
        self._atomic_write(self._metadata_path(trace_id), _canonical_bytes(metadata))
        self._atomic_write(
            self._summary_path(trace_id),
            _canonical_bytes(project_summary(metadata, [])),
        )
        self._atomic_write(
            self._session_path(session_id),
            _canonical_bytes({"session_id": session_id, "trace_id": trace_id}),
        )
        return trace_id

    def _update_metadata(
        self,
        trace_id: str,
        events: List[Dict[str, Any]],
        event: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        metadata = self.load_metadata(trace_id)
        if metadata.get("model") is None and context.get("model"):
            metadata["model"] = context["model"]
        if metadata.get("agent_version") is None and context.get("agent_version"):
            metadata["agent_version"] = context["agent_version"]
        if metadata.get("revision_start") is None and context.get("revision_start"):
            metadata["revision_start"] = context["revision_start"]
        if len(events) == 1 and event["event_type"] not in {
            "session.started",
            "workflow.started",
        }:
            metadata["capture_status"] = "partial"
        if event["event_type"] == "workflow.started":
            metadata["workflow_name"] = event["payload"].get(
                "workflow_name", "coding-sop"
            )
        if event["source"] == "codex_transcript_fallback":
            metadata["capture_status"] = "partial"
        if event["event_type"] in {"workflow.completed", "workflow.failed"}:
            metadata["end_time"] = event["timestamp"]
            metadata["capture_status"] = (
                "complete"
                if event["event_type"] == "workflow.completed"
                else "failed"
            )
        if event["event_type"] == "session.ended":
            if metadata["capture_status"] in {"active", "partial"}:
                metadata["end_time"] = event["timestamp"]
            if metadata["capture_status"] == "active":
                metadata["capture_status"] = "complete"
        if event["event_type"] == "workflow.user_decision" and metadata["capture_status"] == "failed":
            metadata["capture_status"] = "active"
            metadata["end_time"] = None
        self._atomic_write(self._metadata_path(trace_id), _canonical_bytes(metadata))
        return metadata

    def _active_stage(self, events: Iterable[Dict[str, Any]]) -> Optional[str]:
        active: List[str] = []
        for event in events:
            name = event.get("stage") or event.get("payload", {}).get("stage")
            if not name:
                continue
            if event["event_type"] == "workflow.stage.started":
                active.append(name)
            elif event["event_type"] in {
                "workflow.stage.completed",
                "workflow.stage.failed",
                "workflow.stage.skipped",
            }:
                active = [item for item in active if item != name]
        return active[-1] if active else None

    def _read_events(self, trace_id: str) -> List[Dict[str, Any]]:
        path = self._events_path(trace_id)
        if not path.exists():
            return []
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > MAX_EVENTS_BYTES
        ):
            raise StoreError(
                "trace.events_invalid",
                "Execution trace events file is invalid.",
                retryable=False,
            )
        events = []
        try:
            with path.open("r", encoding="utf-8") as stream:
                for expected_seq, line in enumerate(stream, 1):
                    event = json.loads(line)
                    if (
                        not isinstance(event, dict)
                        or event.get("schema_version") != EVENT_SCHEMA_VERSION
                        or event.get("trace_id") != trace_id
                        or event.get("seq") != expected_seq
                        or event.get("event_type") not in EVENT_TYPES
                        or event.get("source") not in EVENT_SOURCES
                    ):
                        raise ValueError("invalid event")
                    events.append(event)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise StoreError(
                "trace.events_invalid",
                "Execution trace events could not be decoded.",
                retryable=False,
            ) from error
        return events

    def _append_event(self, trace_id: str, encoded: bytes) -> None:
        path = self._events_path(trace_id)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("Execution trace events must be a regular file.")
            os.fchmod(descriptor, 0o600)
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _atomic_write(self, path: Path, content: bytes) -> None:
        temporary = path.parent / ("." + path.name + "-" + secrets.token_hex(8))
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            _write_all(descriptor, content)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _read_json(self, path: Path) -> Dict[str, Any]:
        try:
            metadata = path.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > MAX_EVENT_BYTES
            ):
                raise OSError("Execution trace JSON file is invalid.")
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StoreError(
                "trace.record_invalid",
                "Execution trace record could not be decoded.",
                retryable=False,
            ) from error
        if not isinstance(value, dict):
            raise StoreError(
                "trace.record_invalid",
                "Execution trace record is invalid.",
                retryable=False,
            )
        return value

    def _session_lock(self, session_id: str):
        if fcntl is None:
            raise OSError("Execution trace locking is unavailable.")
        path = self.root / ".locks" / (self._session_key(session_id) + ".lock")
        descriptor = os.open(
            path,
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)

        class _Lock:
            def __enter__(self_nonlocal):
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                return self_nonlocal

            def __exit__(self_nonlocal, exc_type, exc, traceback):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

        return _Lock()

    def _ensure_private_dir(self, path: Path) -> None:
        if path.is_symlink():
            raise OSError("Execution trace directories cannot be symlinks.")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.stat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("Execution trace path is not a directory.")
        path.chmod(0o700)

    def _reject_symlink_components(self, path: Path) -> None:
        cursor = path
        while not cursor.exists() and cursor != cursor.parent:
            cursor = cursor.parent
        if cursor.is_symlink():
            raise OSError("Execution trace path contains a symlink.")

    def _validate_trace_id(self, trace_id: Any) -> str:
        if not isinstance(trace_id, str):
            raise ContractError("Execution trace identifier must be a UUID.")
        try:
            parsed = uuid.UUID(trace_id)
        except (ValueError, AttributeError) as error:
            raise ContractError("Execution trace identifier is invalid.") from error
        if str(parsed) != trace_id:
            raise ContractError("Execution trace identifier is not canonical.")
        return trace_id

    def _session_key(self, session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    def _session_path(self, session_id: str) -> Path:
        return self.root / ".sessions" / (self._session_key(session_id) + ".json")

    def _metadata_path(self, trace_id: str) -> Path:
        return self.root / trace_id / "metadata.json"

    def _events_path(self, trace_id: str) -> Path:
        return self.root / trace_id / "events.jsonl"

    def _summary_path(self, trace_id: str) -> Path:
        return self.root / trace_id / "summary.json"


def project_summary(
    metadata: Dict[str, Any], events: List[Dict[str, Any]]
) -> Dict[str, Any]:
    route = None
    stage_runs: Dict[str, Dict[str, Any]] = {}
    docs_read: List[str] = []
    init_result = None
    approvals = []
    user_decisions = []
    docs_result = None
    handoff_result = None
    verification_result = None
    task_result = "incomplete"
    failure = None
    dialogue_count = 0
    tool_counts = {
        "requested": 0,
        "completed": 0,
        "error": 0,
        "blocked": 0,
        "abandoned": 0,
    }

    for event in events:
        event_type = event["event_type"]
        payload = event.get("payload", {})
        stage = event.get("stage") or payload.get("stage")
        if event_type == "turn.prompt_submitted":
            dialogue_count += 1
        elif event_type == "tool.requested":
            tool_counts["requested"] += 1
        elif event_type == "tool.completed":
            tool_counts["completed"] += 1
            if payload.get("status") == "error":
                tool_counts["error"] += 1
        elif event_type == "tool.blocked":
            tool_counts["blocked"] += 1
        elif event_type == "tool.abandoned":
            tool_counts["abandoned"] += 1
        elif event_type == "workflow.route.selected":
            route = payload.get("route")
        elif event_type == "workflow.user_decision":
            if task_result == "failed":
                task_result = "incomplete"
                failure = None
            user_decisions.append({"timestamp": event["timestamp"], "stage": stage,
                                   "stage_run_id": event.get("correlation", {}).get("stage_run_id"),
                                   **{key: value for key, value in payload.items() if key != "request_digest"}})
        elif event_type.startswith("workflow.stage.") and stage:
            run_id = event.get("correlation", {}).get("stage_run_id")
            if run_id is None and event_type != "workflow.stage.started":
                run_id = next(
                    (
                        candidate_id
                        for candidate_id, candidate in reversed(
                            list(stage_runs.items())
                        )
                        if candidate["stage"] == stage
                        and candidate["status"] == "started"
                    ),
                    None,
                )
            key = run_id or f"{stage}:{event['event_id']}"
            run = stage_runs.setdefault(
                key,
                {
                    "stage": stage,
                    "stage_run_id": run_id,
                    "status": "started",
                    "started_at": None,
                    "ended_at": None,
                    "duration_ms": None,
                },
            )
            repository = payload.get("repository")
            if isinstance(repository, str):
                run["repository"] = repository
            for field in (
                "approval_id",
                "subject_kind",
                "subject_digest",
                "source_subject_digest",
                "decision_id",
                "outcome",
                "reason",
                "error_code",
            ):
                value = payload.get(field)
                if isinstance(value, str):
                    run[field] = value
            if event_type == "workflow.stage.started":
                run["status"] = "started"
                run["started_at"] = event["timestamp"]
            else:
                run["status"] = event_type.rsplit(".", 1)[-1]
                run["ended_at"] = event["timestamp"]
                if run["started_at"] is None and run["status"] == "skipped":
                    run["started_at"] = event["timestamp"]
                run["duration_ms"] = _duration_ms(
                    run["started_at"], run["ended_at"]
                )
        elif event_type == "docs.read":
            path = payload.get("path")
            if isinstance(path, str) and path not in docs_read:
                docs_read.append(path)
        elif event_type in {
            "init.mode.selected",
            "init.context.inspected",
            "init.completed",
        }:
            init_result = payload
        elif event_type in {"approval.requested", "approval.resolved"}:
            approvals.append(
                {
                    "event_type": event_type,
                    "timestamp": event["timestamp"],
                    "stage": stage,
                    "stage_run_id": event.get("correlation", {}).get(
                        "stage_run_id"
                    ),
                    **payload,
                }
            )
        elif event_type in {
            "docs.impact.classified",
            "docs.sync.completed",
            "docs.sync.skipped",
        }:
            docs_result = {
                **(docs_result or {}),
                "event_type": event_type,
                **payload,
            }
        elif event_type in {
            "handoff.check.requested",
            "handoff.check.resolved",
            "handoff.completed",
            "handoff.updated",
        }:
            handoff_result = {
                **(handoff_result or {}),
                "event_type": event_type,
                "timestamp": event["timestamp"],
                "stage_run_id": event.get("correlation", {}).get(
                    "stage_run_id"
                ),
                **payload,
            }
        elif event_type == "verification.completed":
            verification_result = payload
        elif event_type == "workflow.completed":
            task_result = ("completed_with_exceptions" if payload.get("outcome") == "completed_with_exceptions" else "passed")
        elif event_type == "workflow.failed":
            task_result = "failed"
            failure = payload

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "trace_id": metadata["trace_id"],
        "session_id": metadata["session_id"],
        "workflow_name": metadata.get("workflow_name"),
        "actual_route": route,
        "actual_stages": list(stage_runs.values()),
        "docs_actual_read": docs_read,
        "init_result": init_result,
        "approval_results": approvals,
        "user_decisions": user_decisions,
        "hook_actual_result": docs_result,
        "handoff_actual_result": handoff_result,
        "verification_result": verification_result,
        "dialogue_count": dialogue_count,
        "tool_counts": tool_counts,
        "duration_ms": _duration_ms(
            metadata.get("start_time"), metadata.get("end_time")
        ),
        "task_result": task_result,
        "failure": failure,
        "capture_status": metadata.get("capture_status"),
        "last_seq": len(events),
    }
