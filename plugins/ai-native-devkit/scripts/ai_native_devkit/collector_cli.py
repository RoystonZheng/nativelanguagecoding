"""Fail-open command-hook entry point for execution trace collection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional

from .cli import MAX_REQUEST_BYTES
from .collector import CollectorService, validate_trace_root
from .execution_trace import ExecutionTraceStore
from .runtime_trace import TRACE_DIRECTORY, append_health_error


def trace_root() -> Path:
    configured = os.environ.get("AI_NATIVE_DEVKIT_STATE_ROOT")
    state_root = (
        Path(configured).expanduser().absolute()
        if configured
        else (Path.home() / ".codex" / "state" / "ai-native-devkit" / "v1")
    )
    return state_root / TRACE_DIRECTORY


def _read_hook_input() -> Dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("hook input too large")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("hook input must be an object")
    return value


def run() -> int:
    value: Optional[Dict[str, Any]] = None
    wrote_output = False
    root = trace_root()
    root_is_safe = False
    try:
        validate_trace_root(root, None)
        root_is_safe = True
        value = _read_hook_input()
        try:
            validate_trace_root(root, value.get("cwd"))
        except Exception:
            root_is_safe = False
            raise
        store = ExecutionTraceStore(root)
        result = CollectorService(store).collect_codex(value)
        hook_output = result.get("hook_output")
        if isinstance(hook_output, dict):
            json.dump(
                hook_output,
                sys.stdout,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            sys.stdout.write("\n")
            wrote_output = True
    except Exception as error:
        if (
            root_is_safe
            and isinstance(value, dict)
            and isinstance(value.get("session_id"), str)
        ):
            try:
                ExecutionTraceStore(root).mark_capture_status(
                    value["session_id"], "partial"
                )
            except Exception:
                pass
        if root_is_safe:
            event_name = (
                value.get("hook_event_name") if isinstance(value, dict) else None
            )
            append_health_error(
                root,
                error,
                event_name if isinstance(event_name, str) else None,
            )

    if (
        isinstance(value, dict)
        and value.get("hook_event_name") in {
            "Stop",
            "SubagentStop",
        }
        and not wrote_output
    ):
        sys.stdout.write("{}\n")
    return 0


def main() -> int:
    return run()
