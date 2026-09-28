"""Adapters and handler service for Codex Hook and DevKit runtime events."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
from typing import Any, Dict, List, Optional

from .errors import ContractError
from .execution_trace import EVENT_TYPES, ExecutionTraceStore


HOOK_EVENT_MAP = {
    "SessionStart": ("session.started", "system"),
    "SessionEnd": ("session.ended", "system"),
    "UserPromptSubmit": ("turn.prompt_submitted", "user"),
    "PreToolUse": ("tool.requested", "agent"),
    "PostToolUse": ("tool.completed", "agent"),
    "PermissionRequest": ("permission.requested", "system"),
    "PreCompact": ("context.compaction.started", "system"),
    "PostCompact": ("context.compaction.completed", "system"),
    "SubagentStart": ("subagent.started", "system"),
    "SubagentStop": ("subagent.stopped", "system"),
    "Stop": ("turn.stopped", "agent"),
}
LEGACY_HANDOFF_EVENT_TYPES = frozenset(
    event for event in EVENT_TYPES if event.startswith("handoff.")
)
RUNTIME_EVENT_TYPES = EVENT_TYPES - LEGACY_HANDOFF_EVENT_TYPES - frozenset(
    event for event, _ in HOOK_EVENT_MAP.values()
)
DOC_PATH = re.compile(r"(?<![A-Za-z0-9_.@/-])([A-Za-z0-9_.@/-]+\.md)(?![A-Za-z0-9_.@/-])")
READ_COMMAND = re.compile(r"(^|[;&|\n]\s*)(cat|sed|head|tail|less|more|rg|grep)\b")
MAX_TRANSCRIPT_BYTES = 64 * 1024 * 1024


def _text(value: Any, *, limit: int = 1024) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.split())[:limit]


def _keys(value: Any) -> List[str]:
    if not isinstance(value, dict):
        return []
    return sorted(str(key)[:128] for key in value)[:64]


def _response_facts(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "observed", "response_type": type(value).__name__}
    facts: Dict[str, Any] = {"status": "success"}
    if value.get("isError") is True or value.get("is_error") is True:
        facts["status"] = "error"
    for field in ("exit_code", "duration_ms", "wall_time_seconds"):
        item = value.get(field)
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            facts[field] = item
    structured = value.get("structuredContent")
    if isinstance(structured, dict):
        exit_code = structured.get("exit_code")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            facts["exit_code"] = exit_code
    if facts.get("exit_code") not in (None, 0):
        facts["status"] = "error"
    facts["response_keys"] = _keys(value)
    return facts


def _run_observation_git(cwd: str, *arguments: str):
    executable = shutil.which("git", path=os.defpath)
    if executable is None:
        return None
    try:
        executable = str(Path(executable).resolve(strict=True))
    except OSError:
        return None
    environment = os.environ.copy()
    environment["PATH"] = os.defpath
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    for name in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_EXEC_PATH",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_PREFIX",
        "GIT_SHALLOW_FILE",
        "GIT_WORK_TREE",
    ):
        environment.pop(name, None)
    try:
        return subprocess.run(
            [
                executable,
                "-c",
                "credential.helper=",
                "-c",
                "protocol.allow=never",
                "-C",
                cwd,
                *arguments,
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=1,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _git_revision(cwd: Optional[str]) -> Optional[str]:
    if not cwd:
        return None
    result = _run_observation_git(cwd, "rev-parse", "--verify", "HEAD")
    if result is None:
        return None
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", revision) else None


def _repository_root(cwd: str) -> Optional[Path]:
    result = _run_observation_git(cwd, "rev-parse", "--show-toplevel")
    if result is None:
        return None
    if result.returncode:
        return None
    return Path(result.stdout.strip()).resolve(strict=False)


def validate_trace_root(root: Path, cwd: Optional[str]) -> None:
    cursor = root.expanduser().absolute()
    while not cursor.exists() and cursor != cursor.parent:
        cursor = cursor.parent
    if cursor.is_symlink():
        raise ContractError("Execution Trace storage path cannot contain a symlink.")
    resolved = root.expanduser().resolve(strict=False)
    plugin_root = Path(__file__).resolve().parents[2]
    protected = [plugin_root]
    if isinstance(cwd, str) and cwd:
        repository = _repository_root(cwd)
        protected.append(repository or Path(cwd).expanduser().resolve(strict=False))
    for target in protected:
        if (
            resolved == target
            or resolved.is_relative_to(target)
            or target.is_relative_to(resolved)
        ):
            raise ContractError(
                "Execution Trace storage must remain outside the target repository and plugin installation."
            )


def _normalize_doc_path(path: str, cwd: str, root: Path) -> Optional[str]:
    cleaned = path.strip("'\"`:,()[]{}")
    candidate = Path(cleaned)
    if not candidate.is_absolute():
        candidate = Path(cwd) / candidate
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return None
    normalized = PurePosixPath(relative.as_posix())
    if ".." in normalized.parts or normalized.suffix.lower() != ".md":
        return None
    return normalized.as_posix()


def docs_read_from_hook(value: Dict[str, Any]) -> List[str]:
    """Extract only repository-relative Markdown paths from successful read tools."""

    if value.get("hook_event_name") != "PostToolUse":
        return []
    response = _response_facts(value.get("tool_response"))
    if response.get("status") == "error":
        return []
    cwd = value.get("cwd")
    if not isinstance(cwd, str):
        return []
    root = _repository_root(cwd)
    if root is None:
        return []
    tool_name = value.get("tool_name")
    tool_input = value.get("tool_input")
    candidates: List[str] = []
    if tool_name == "Bash" and isinstance(tool_input, dict):
        command = tool_input.get("command")
        if isinstance(command, str) and READ_COMMAND.search(command):
            candidates.extend(match.group(1) for match in DOC_PATH.finditer(command))
    elif isinstance(tool_input, dict) and any(
        token in str(tool_name).lower() for token in ("read", "open", "view")
    ):
        for field in ("path", "file_path", "ref_id"):
            item = tool_input.get(field)
            if isinstance(item, str) and item.endswith(".md"):
                candidates.append(item)
    normalized = {
        path
        for candidate in candidates
        if (path := _normalize_doc_path(candidate, cwd, root)) is not None
    }
    return sorted(normalized)


class CodexHookAdapter:
    def adapt(self, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ContractError("Codex Hook input must be an object.")
        event_name = value.get("hook_event_name")
        if event_name not in HOOK_EVENT_MAP:
            raise ContractError("Codex Hook event is not supported by the collector.")
        session_id = _text(value.get("session_id"))
        if session_id is None:
            raise ContractError("Codex Hook event requires session_id.")
        event_type, actor = HOOK_EVENT_MAP[event_name]
        correlation = {
            "turn_id": _text(value.get("turn_id")),
            "tool_call_id": _text(value.get("tool_use_id")),
            "subagent_id": _text(value.get("agent_id")),
        }
        payload = self._payload(event_name, value)
        context = {
            "cwd": _text(value.get("cwd"), limit=4096),
            "model": _text(value.get("model")),
            "agent_version": _text(os.environ.get("CODEX_VERSION")),
        }
        if event_name == "SessionStart":
            context["revision_start"] = _git_revision(context.get("cwd"))
        return {
            "session_id": session_id,
            "event_type": event_type,
            "actor": actor,
            "source": "codex_hook",
            "correlation": correlation,
            "payload": payload,
            "context": context,
        }

    def _payload(self, event_name: str, value: Dict[str, Any]) -> Dict[str, Any]:
        permission_mode = _text(value.get("permission_mode"))
        if event_name == "SessionStart":
            return {"start_source": _text(value.get("source")), "permission_mode": permission_mode}
        if event_name == "SessionEnd":
            return {"reason": _text(value.get("reason"))}
        if event_name == "UserPromptSubmit":
            prompt = value.get("prompt")
            return {
                "prompt_chars": len(prompt) if isinstance(prompt, str) else None,
                "permission_mode": permission_mode,
            }
        if event_name in {"PreToolUse", "PermissionRequest"}:
            return {
                "tool": _text(value.get("tool_name")),
                "input_keys": _keys(value.get("tool_input")),
                "permission_mode": permission_mode,
                "description_present": bool(
                    isinstance(value.get("tool_input"), dict)
                    and value["tool_input"].get("description")
                ),
            }
        if event_name == "PostToolUse":
            return {
                "tool": _text(value.get("tool_name")),
                **_response_facts(value.get("tool_response")),
            }
        if event_name in {"PreCompact", "PostCompact"}:
            return {"trigger": _text(value.get("trigger"))}
        if event_name in {"SubagentStart", "SubagentStop"}:
            return {
                "agent_type": _text(value.get("agent_type")),
                "permission_mode": permission_mode,
                "stop_hook_active": bool(value.get("stop_hook_active")),
            }
        if event_name == "Stop":
            message = value.get("last_assistant_message")
            return {
                "stop_hook_active": bool(value.get("stop_hook_active")),
                "assistant_message_chars": len(message) if isinstance(message, str) else None,
            }
        return {}  # pragma: no cover - exhaustive mapping above.


class RuntimeEventAdapter:
    def adapt(self, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ContractError("DevKit runtime event must be an object.")
        event_type = value.get("event_type")
        if event_type not in RUNTIME_EVENT_TYPES:
            raise ContractError("DevKit runtime event_type is not registered.")
        session_id = _text(value.get("session_id")) or _text(
            os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_TASK_ID")
        )
        if session_id is None:
            raise ContractError("DevKit runtime event requires session_id.")
        actor = value.get("actor", "runtime")
        if actor != "runtime":
            raise ContractError("DevKit runtime events must use the runtime actor.")
        correlation = value.get("correlation") or {}
        if not isinstance(correlation, dict):
            raise ContractError("DevKit runtime correlation must be an object.")
        return {
            "session_id": session_id,
            "event_type": event_type,
            "actor": actor,
            "source": "devkit_runtime",
            "stage": _text(value.get("stage")),
            "correlation": dict(correlation),
            "payload": value.get("payload") or {},
            "timestamp": _text(value.get("timestamp")),
            "context": {
                "cwd": _text(value.get("cwd"), limit=4096),
                "model": _text(value.get("model")),
                "agent_version": _text(os.environ.get("CODEX_VERSION")),
            },
        }


class CollectorService:
    def __init__(self, store: ExecutionTraceStore):
        self.store = store
        self.codex_adapter = CodexHookAdapter()
        self.runtime_adapter = RuntimeEventAdapter()

    def collect_codex(self, value: Dict[str, Any]) -> Dict[str, Any]:
        event = self.codex_adapter.adapt(value)
        loaded = self.store.load_session(event["session_id"])
        if not self._plugin_trace_accepts(value, loaded):
            return {"ignored": True, "reason": "plugin_workflow_inactive"}
        if value.get("hook_event_name") == "SessionEnd":
            fallback = TranscriptFallback(self.store)
            fallback.recover(value, event["session_id"])
            fallback.close_unmatched(value, event["session_id"])
        result = self.store.append(**event)
        docs_read = docs_read_from_hook(value)
        for path in docs_read:
            result = self.store.append(
                session_id=event["session_id"],
                event_type="docs.read",
                actor="agent",
                source="codex_hook",
                stage=result["event"].get("stage"),
                correlation=event["correlation"],
                payload={"path": path},
                context=event["context"],
            )
        return result

    def _plugin_trace_accepts(
        self, hook_input: Dict[str, Any], loaded: Optional[Dict[str, Any]]
    ) -> bool:
        if loaded is None:
            return False
        metadata = loaded["metadata"]
        if metadata.get("workflow_name") != "coding-sop":
            return False
        if metadata.get("capture_status") in {"active", "partial"}:
            return True
        if metadata.get("capture_status") != "complete":
            return False
        event_name = hook_input.get("hook_event_name")
        if event_name == "SessionEnd":
            return True
        if event_name == "Stop":
            turn_id = _text(hook_input.get("turn_id"))
            completion = next(
                (
                    event
                    for event in reversed(loaded["events"])
                    if event["event_type"] == "workflow.completed"
                ),
                None,
            )
            if completion is None or turn_id is None:
                return False
            if completion.get("correlation", {}).get("turn_id") != turn_id:
                return False
            return not any(
                event["event_type"] == "turn.stopped"
                and event.get("correlation", {}).get("turn_id") == turn_id
                for event in loaded["events"]
            )
        if event_name != "PostToolUse":
            return False
        tool_call_id = _text(hook_input.get("tool_use_id"))
        if tool_call_id is None:
            return False
        requested = any(
            event["event_type"] == "tool.requested"
            and event.get("correlation", {}).get("tool_call_id") == tool_call_id
            for event in loaded["events"]
        )
        terminal = any(
            event["event_type"] in {"tool.completed", "tool.blocked", "tool.abandoned"}
            and event.get("correlation", {}).get("tool_call_id") == tool_call_id
            for event in loaded["events"]
        )
        return requested and not terminal

    def emit_runtime(self, value: Dict[str, Any]) -> Dict[str, Any]:
        event = self.runtime_adapter.adapt(value)
        if not event["correlation"].get("turn_id"):
            event["correlation"].update(
                self._active_host_correlation(event["session_id"])
            )
        return self.store.append(**event)

    def _active_host_correlation(self, session_id: str) -> Dict[str, Optional[str]]:
        loaded = self.store.load_session(session_id)
        if not loaded:
            return {}
        turn_id = None
        for event in reversed(loaded["events"]):
            if event["event_type"] == "turn.stopped":
                break
            candidate = event.get("correlation", {}).get("turn_id")
            if candidate:
                turn_id = candidate
                break
        if turn_id is None:
            return {}
        requested = []
        completed = set()
        for event in loaded["events"]:
            correlation = event["correlation"]
            if correlation.get("turn_id") != turn_id:
                continue
            tool_call_id = correlation.get("tool_call_id")
            if event["event_type"] == "tool.requested" and tool_call_id:
                requested.append(tool_call_id)
            elif event["event_type"] in {
                "tool.completed",
                "tool.blocked",
                "tool.abandoned",
            } and tool_call_id:
                completed.add(tool_call_id)
        active_tools = [
            tool_call_id
            for tool_call_id in requested
            if tool_call_id not in completed
        ]
        result = {"turn_id": turn_id}
        if len(active_tools) == 1:
            result["tool_call_id"] = active_tools[0]
        return result


def error_fingerprint(error: BaseException) -> str:
    value = f"{type(error).__module__}.{type(error).__name__}"
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_timestamp(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class TranscriptFallback:
    """Conservatively restores missing structured facts from a local transcript."""

    def __init__(self, store: ExecutionTraceStore):
        self.store = store

    def recover(self, hook_input: Dict[str, Any], session_id: str) -> int:
        path_value = hook_input.get("transcript_path")
        if not isinstance(path_value, str) or not path_value:
            return 0
        path = Path(path_value)
        try:
            metadata = path.lstat()
        except OSError:
            return 0
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > MAX_TRANSCRIPT_BYTES
        ):
            return 0

        loaded = self.store.load_session(session_id)
        events = loaded["events"] if loaded else []
        workflow_start = next(
            (
                event["timestamp"]
                for event in events
                if event["event_type"] == "workflow.started"
            ),
            None,
        )
        workflow_end = next(
            (
                event["timestamp"]
                for event in reversed(events)
                if event["event_type"]
                in {"workflow.completed", "workflow.failed"}
            ),
            None,
        )
        prompt_turns = {
            event["correlation"].get("turn_id")
            for event in events
            if event["event_type"] == "turn.prompt_submitted"
        }
        stopped_turns = {
            event["correlation"].get("turn_id")
            for event in events
            if event["event_type"] == "turn.stopped"
        }
        requested_tools = {
            event["correlation"].get("tool_call_id")
            for event in events
            if event["event_type"] == "tool.requested"
        }
        completed_tools = {
            event["correlation"].get("tool_call_id")
            for event in events
            if event["event_type"]
            in {"tool.completed", "tool.blocked", "tool.abandoned"}
        }
        recovered = 0
        current_turn = None
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    record = json.loads(line)
                    if not isinstance(record, dict) or not isinstance(
                        record.get("payload"), dict
                    ):
                        continue
                    payload = record["payload"]
                    timestamp = _canonical_timestamp(record.get("timestamp"))
                    call_id = payload.get("call_id")
                    existing_tool_result = (
                        payload.get("type") == "function_call_output"
                        and isinstance(call_id, str)
                        and call_id in requested_tools
                    )
                    outside_window = timestamp is None or (
                        workflow_start is not None and timestamp < workflow_start
                    ) or (
                        workflow_end is not None and timestamp > workflow_end
                    )
                    if outside_window and not existing_tool_result:
                        continue
                    if record.get("type") == "turn_context" and isinstance(
                        payload.get("turn_id"), str
                    ):
                        current_turn = payload["turn_id"]
                        continue
                    if record.get("type") == "event_msg" and payload.get(
                        "type"
                    ) == "task_started":
                        current_turn = payload.get("turn_id") or current_turn
                        continue
                    if (
                        record.get("type") == "event_msg"
                        and payload.get("type") == "user_message"
                        and current_turn
                        and current_turn not in prompt_turns
                    ):
                        self._append(
                            session_id,
                            "turn.prompt_submitted",
                            "user",
                            current_turn,
                            None,
                            timestamp,
                            {"recovered_from": "user_message"},
                            hook_input,
                        )
                        prompt_turns.add(current_turn)
                        recovered += 1
                        continue
                    if record.get("type") != "response_item":
                        if (
                            record.get("type") == "event_msg"
                            and payload.get("type") == "task_complete"
                            and current_turn
                            and current_turn not in stopped_turns
                        ):
                            self._append(
                                session_id,
                                "turn.stopped",
                                "agent",
                                current_turn,
                                None,
                                timestamp,
                                {"recovered_from": "task_complete"},
                                hook_input,
                            )
                            stopped_turns.add(current_turn)
                            recovered += 1
                        continue
                    if not isinstance(call_id, str) or not call_id:
                        continue
                    if payload.get("type") == "function_call" and call_id not in requested_tools:
                        self._append(
                            session_id,
                            "tool.requested",
                            "agent",
                            current_turn,
                            call_id,
                            timestamp,
                            {
                                "tool": _text(payload.get("name")),
                                "recovered_from": "function_call",
                            },
                            hook_input,
                        )
                        requested_tools.add(call_id)
                        recovered += 1
                    elif (
                        payload.get("type") == "function_call_output"
                        and call_id not in completed_tools
                    ):
                        self._append(
                            session_id,
                            "tool.completed",
                            "agent",
                            current_turn,
                            call_id,
                            timestamp,
                            {
                                "status": "observed",
                                "recovered_from": "function_call_output",
                            },
                            hook_input,
                        )
                        completed_tools.add(call_id)
                        recovered += 1
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return recovered
        return recovered

    def close_unmatched(
        self, hook_input: Dict[str, Any], session_id: str
    ) -> int:
        refreshed = self.store.load_session(session_id)
        refreshed_events = refreshed["events"] if refreshed else []
        terminals = {
            event.get("correlation", {}).get("tool_call_id")
            for event in refreshed_events
            if event["event_type"]
            in {"tool.completed", "tool.blocked", "tool.abandoned"}
        }
        closed = 0
        for event in refreshed_events:
            tool_call_id = event.get("correlation", {}).get("tool_call_id")
            if (
                event["event_type"] != "tool.requested"
                or not tool_call_id
                or tool_call_id in terminals
            ):
                continue
            self._append(
                session_id,
                "tool.abandoned",
                "system",
                event.get("correlation", {}).get("turn_id"),
                tool_call_id,
                None,
                {
                    "status": "unknown",
                    "reason": "session_ended_without_tool_output",
                },
                hook_input,
            )
            terminals.add(tool_call_id)
            closed += 1
        return closed

    def _append(
        self,
        session_id: str,
        event_type: str,
        actor: str,
        turn_id: Optional[str],
        tool_call_id: Optional[str],
        timestamp: Optional[str],
        payload: Dict[str, Any],
        hook_input: Dict[str, Any],
    ) -> None:
        self.store.append(
            session_id=session_id,
            event_type=event_type,
            actor=actor,
            source="codex_transcript_fallback",
            correlation={"turn_id": turn_id, "tool_call_id": tool_call_id},
            payload=payload,
            timestamp=timestamp,
            context={
                "cwd": _text(hook_input.get("cwd"), limit=4096),
                "model": _text(hook_input.get("model")),
            },
        )
