from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = PROJECT_ROOT / "plugins" / "ai-native-devkit"
sys.path.insert(0, str(PLUGIN / "scripts"))
CLI = PLUGIN / "scripts" / "trace_collector.py"
RUNTIME_CLI = PLUGIN / "scripts" / "runtime_cli.py"
HOOKS = PLUGIN / "hooks" / "hooks.json"
SCHEMA_VERSION = "ai-native-devkit/v1alpha1"

from ai_native_devkit.requirement_document import RequirementDocumentWriter


def run_hook(state_root, payload):
    environment = os.environ.copy()
    environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
    return subprocess.run(
        [sys.executable, str(CLI)],
        input=json.dumps(payload) if not isinstance(payload, str) else payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


def activate_plugin_trace(state_root, workspace, session_id):
    environment = os.environ.copy()
    environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
    environment["CODEX_THREAD_ID"] = session_id
    return subprocess.run(
        [sys.executable, str(RUNTIME_CLI)],
        input=json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "operation": "workflow.route",
                "cwd": str(workspace),
                "intent": "development",
                "workflow_tier": "fast",
                "route": "lightweight",
                "change_kind": "feature",
            }
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


def run_runtime(state_root, session_id, payload):
    environment = os.environ.copy()
    environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
    environment["CODEX_THREAD_ID"] = session_id
    return subprocess.run(
        [sys.executable, str(RUNTIME_CLI)],
        input=json.dumps({"schema_version": SCHEMA_VERSION, **payload}),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


class TraceCollectorCliTests(unittest.TestCase):
    def test_stopped_hook_turn_cannot_resolve_requirement_approval(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            workspace = root / "workspace"
            workspace.mkdir()
            for arguments in (
                ("init", "-b", "main"),
                ("config", "user.name", "Test User"),
                ("config", "user.email", "test@example.com"),
            ):
                subprocess.run(["git", *arguments], cwd=workspace, check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (workspace / "README.md").write_text("# Project\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=workspace,
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            session_id = "session-requirement-stop"
            routed = run_runtime(state_root, session_id, {
                "operation": "workflow.route", "cwd": str(workspace),
                "intent": "development", "workflow_tier": "strict",
                "route": "development", "change_kind": "feature",
            })
            self.assertEqual(routed.returncode, 0, routed.stdout)
            started = json.loads(run_runtime(state_root, session_id, {
                "operation": "stage.start", "stage": "clarify", "cwd": str(workspace),
            }).stdout)
            reference = RequirementDocumentWriter(
                today=lambda: date(2026, 8, 27)
            ).write_and_commit(
                repository_root=workspace, title="Login Policy",
                clarified_requirements="Administrators revoke sessions.",
            )

            def hook(name, turn_id, **extra):
                return run_hook(state_root, {
                    "session_id": session_id, "cwd": str(workspace),
                    "hook_event_name": name, "turn_id": turn_id,
                    "permission_mode": "default", "model": "gpt-test", **extra,
                })

            self.assertEqual(hook("UserPromptSubmit", "turn-request",
                                  prompt="review requirements").returncode, 0)
            requested = json.loads(run_runtime(state_root, session_id, {
                "operation": "approval.request", "stage": "clarify",
                "stage_run_id": started["stage_run_id"],
                "approval_kind": "clarify.requirements",
                "subject": reference.to_dict(), "cwd": str(workspace),
            }).stdout)
            self.assertEqual(hook("UserPromptSubmit", "turn-approval",
                                  prompt="approved").returncode, 0)
            self.assertEqual(hook("Stop", "turn-approval", stop_hook_active=False,
                                  last_assistant_message="done").returncode, 0)
            resolved = run_runtime(state_root, session_id, {
                "operation": "approval.resolve", "approval_id": requested["approval_id"],
                "decision": "approved", "cwd": str(workspace),
            })
            self.assertNotEqual(resolved.returncode, 0)
            self.assertEqual(json.loads(resolved.stdout)["code"], "rejected.contract")

    def test_plugin_bundles_complete_collector_hook_lifecycle(self):
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]
        expected = {
            "SessionStart",
            "SessionEnd",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "PermissionRequest",
            "PreCompact",
            "PostCompact",
            "SubagentStart",
            "SubagentStop",
            "Stop",
        }
        self.assertEqual(set(hooks), expected)
        for event_name, groups in hooks.items():
            handler = groups[0]["hooks"][0]
            self.assertEqual(handler["type"], "command")
            self.assertIn("$PLUGIN_ROOT/scripts/trace_collector.py", handler["command"])
            self.assertLessEqual(handler["timeout"], 3, event_name)
            self.assertNotIn("async", handler)

    def test_hook_cli_ignores_sessions_without_plugin_activation(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            workspace = Path(temporary_directory) / "workspace"
            workspace.mkdir()
            common = {
                "session_id": "session-hook-01",
                "transcript_path": None,
                "cwd": str(workspace),
                "model": "gpt-test",
                "permission_mode": "default",
            }
            started = run_hook(
                state_root,
                {**common, "hook_event_name": "SessionStart", "source": "startup"},
            )
            stopped = run_hook(
                state_root,
                {
                    **common,
                    "hook_event_name": "Stop",
                    "turn_id": "turn-01",
                    "stop_hook_active": False,
                    "last_assistant_message": "secret response not persisted",
                },
            )

            self.assertEqual(started.returncode, 0, started.stderr)
            self.assertEqual(started.stdout, "")
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertEqual(json.loads(stopped.stdout), {})
            self.assertFalse((state_root / "execution-traces").exists())

    def test_user_prompt_records_length_without_prompt_content(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            workspace = Path(temporary_directory) / "workspace"
            workspace.mkdir()
            activated = activate_plugin_trace(
                state_root, workspace, "session-hook-02"
            )
            self.assertEqual(activated.returncode, 0, activated.stderr)
            result = run_hook(
                state_root,
                {
                    "session_id": "session-hook-02",
                    "cwd": str(workspace),
                    "hook_event_name": "UserPromptSubmit",
                    "turn_id": "turn-01",
                    "prompt": "token=do-not-store-this",
                    "permission_mode": "default",
                    "model": "gpt-test",
                },
            )

            self.assertEqual(result.returncode, 0)
            trace_dir = next(
                path
                for path in (state_root / "execution-traces").iterdir()
                if not path.name.startswith(".")
            )
            event = json.loads(
                (trace_dir / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[-1]
            )
            self.assertEqual(event["payload"]["prompt_chars"], 23)
            self.assertNotIn("do-not-store", json.dumps(event))

    def test_malformed_hook_input_is_fail_open_and_records_health_only(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            result = run_hook(state_root, "not-json")

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")
            health = state_root / "execution-traces" / "collector-errors.jsonl"
            record = json.loads(health.read_text(encoding="utf-8").strip())
            self.assertEqual(
                set(record), {"timestamp", "event_name", "error_fingerprint"}
            )
            self.assertIsNone(record["event_name"])

    def test_session_end_recovers_only_missing_transcript_facts_and_marks_partial(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            workspace = root / "workspace"
            workspace.mkdir()
            transcript = root / "rollout.jsonl"
            activated = activate_plugin_trace(
                state_root, workspace, "session-fallback"
            )
            self.assertEqual(activated.returncode, 0, activated.stderr)
            trace_dir = next(
                path
                for path in (state_root / "execution-traces").iterdir()
                if not path.name.startswith(".")
            )
            observed_at = json.loads(
                (trace_dir / "metadata.json").read_text(encoding="utf-8")
            )["start_time"]
            transcript.write_text(
                "\n".join(
                    json.dumps(item)
                    for item in (
                        {
                            "timestamp": observed_at,
                            "type": "turn_context",
                            "payload": {"turn_id": "turn-fallback"},
                        },
                        {
                            "timestamp": observed_at,
                            "type": "event_msg",
                            "payload": {
                                "type": "user_message",
                                "message": "must not persist",
                            },
                        },
                        {
                            "timestamp": observed_at,
                            "type": "response_item",
                            "payload": {
                                "type": "function_call",
                                "call_id": "call-fallback",
                                "name": "Bash",
                                "arguments": "secret command",
                            },
                        },
                        {
                            "timestamp": observed_at,
                            "type": "response_item",
                            "payload": {
                                "type": "function_call_output",
                                "call_id": "call-fallback",
                                "output": "secret output",
                            },
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            ended = run_hook(
                state_root,
                {
                    "session_id": "session-fallback",
                    "transcript_path": str(transcript),
                    "cwd": str(workspace),
                    "hook_event_name": "SessionEnd",
                    "reason": "other",
                    "model": "gpt-test",
                },
            )

            self.assertEqual(ended.returncode, 0, ended.stderr)
            events = [
                json.loads(line)
                for line in (trace_dir / "events.jsonl").read_text().splitlines()
            ]
            self.assertEqual(
                [event["event_type"] for event in events],
                [
                    "workflow.started",
                    "workflow.route.selected",
                    "workflow.stage.skipped",
                    "workflow.stage.skipped",
                    "workflow.stage.skipped",
                    "workflow.stage.skipped",
                    "turn.prompt_submitted",
                    "tool.requested",
                    "tool.completed",
                    "session.ended",
                ],
            )
            self.assertEqual(
                [
                    event["source"]
                    for event in events
                    if event["event_type"]
                    in {"turn.prompt_submitted", "tool.requested", "tool.completed"}
                ],
                ["codex_transcript_fallback"] * 3,
            )
            self.assertNotIn("secret", json.dumps(events))
            metadata = json.loads((trace_dir / "metadata.json").read_text())
            self.assertEqual(metadata["capture_status"], "partial")

    def test_hook_fails_open_without_writing_trace_inside_target_repository(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "repository"
            repository.mkdir()
            unsafe_state = repository / ".trace-state"
            result = run_hook(
                unsafe_state,
                {
                    "session_id": "unsafe-session",
                    "cwd": str(repository),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                    "model": "gpt-test",
                },
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")
            self.assertFalse(unsafe_state.exists())

    def test_pre_tool_hook_observes_handoff_without_plugin_approval(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            workspace = root / "workspace"
            (workspace / "handoff").mkdir(parents=True)
            (workspace / "handoff/README.md").write_text(
                "# Handoff\n", encoding="utf-8"
            )
            session_id = "session-handoff-unmanaged"
            self.assertEqual(
                activate_plugin_trace(state_root, workspace, session_id).returncode,
                0,
            )
            common = {
                "session_id": session_id,
                "cwd": str(workspace),
                "hook_event_name": "PreToolUse",
                "turn_id": "turn-request",
                "tool_name": "Bash",
                "permission_mode": "default",
            }
            self.assertEqual(
                run_hook(
                    state_root,
                    {
                        "session_id": session_id,
                        "cwd": str(workspace),
                        "hook_event_name": "UserPromptSubmit",
                        "turn_id": "turn-request",
                        "prompt": "check whether handoff should be updated",
                        "permission_mode": "default",
                        "model": "gpt-test",
                    },
                ).returncode,
                0,
            )
            observed = run_hook(
                state_root,
                {
                    **common,
                    "tool_use_id": "tool-observed",
                    "tool_input": {"command": "cat handoff/README.md"},
                },
            )
            self.assertEqual(observed.returncode, 0, observed.stderr)
            self.assertEqual(observed.stdout, "")
            from ai_native_devkit.execution_trace import ExecutionTraceStore
            events = ExecutionTraceStore(state_root / "execution-traces").load_session(session_id)["events"]
            self.assertIn("tool.requested", [e["event_type"] for e in events])
            self.assertFalse(any(e["event_type"].startswith(("handoff.", "approval."))
                                 or e["event_type"] == "tool.blocked" for e in events))


if __name__ == "__main__":
    unittest.main()
