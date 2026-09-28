"""Retired human-document workflow cannot create new runtime activity."""

from pathlib import Path
import json
import tempfile
import unittest

from tests.integration.test_trace_collector_cli import (
    activate_plugin_trace, run_runtime,
)
from ai_native_devkit.collector import CollectorService
from ai_native_devkit.errors import ContractError
from ai_native_devkit.execution_trace import ExecutionTraceStore, repository_digest


class HandoffRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.state_root = self.root / "state"
        self.session = "retired-handoff"
        result = activate_plugin_trace(self.state_root, self.workspace, self.session)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.store = ExecutionTraceStore(self.state_root / "execution-traces")

    def test_retired_runtime_operations_cannot_start_or_approve_handoff(self):
        before = self.store.load_session(self.session)["events"]
        for payload in (
            {"operation": "stage.start", "stage": "handoff"},
            {"operation": "stage.skip", "stage": "handoff", "reason": "skip"},
            {"operation": "approval.request", "stage": "handoff", "approval_kind": "handoff.full_scan"},
            {"operation": "approval.request", "stage": "handoff", "approval_kind": "handoff.destructive_write"},
            {"operation": "workflow.user_decision", "stage": "handoff", "action": "skip_stage",
             "decision_id": "skip-retired-stage", "user_directive": {
                 "source": "user", "reference": "user-message", "summary": "Skip Handoff.",
             }},
        ):
            with self.subTest(payload=payload):
                result = run_runtime(self.state_root, self.session, {
                    "cwd": str(self.workspace), **payload,
                })
                self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.store.load_session(self.session)["events"], before)

    def test_legacy_events_remain_readable_but_pending_approval_is_retired(self):
        for event_type, payload in (
            ("workflow.stage.started", {
                "stage": "handoff", "repository": repository_digest(str(self.workspace)),
            }),
            ("approval.requested", {"approval_id": "old-approval", "approval_kind": "handoff.full_scan"}),
            ("handoff.check.requested", {"approval_id": "old-approval"}),
            ("handoff.access.blocked", {"reason": "handoff.full_scan_approval_required"}),
            ("handoff.completed", {"result": "completed", "fullCapture": True, "appliedChanges": []}),
        ):
            self.store.append(
                session_id=self.session, event_type=event_type, actor="system",
                source="devkit_runtime", stage="handoff",
                correlation={"stage_run_id": "old-run"}, payload=payload,
            )
        before = self.store.load_session(self.session)
        self.assertEqual(before["summary"]["handoff_actual_result"]["result"], "completed")
        result = run_runtime(self.state_root, self.session, {
            "operation": "trace.load", "cwd": str(self.workspace),
        })
        self.assertEqual(result.returncode, 0, result.stdout)
        result = run_runtime(self.state_root, self.session, {
            "operation": "approval.resolve", "approval_id": "old-approval",
            "decision": "approved", "cwd": str(self.workspace),
        })
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("unsupported workflow stage or kind", json.loads(result.stdout)["message"])
        after = self.store.load_session(self.session)
        self.assertEqual(after["events"], before["events"])
        with self.assertRaises(ContractError):
            CollectorService(self.store).emit_runtime({
                "session_id": self.session, "event_type": "handoff.completed",
                "stage": "handoff", "payload": {"result": "completed"},
            })
        result = run_runtime(self.state_root, self.session, {
            "operation": "stage.start", "stage": "execute", "cwd": str(self.workspace),
        })
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["stage"], "execute")


if __name__ == "__main__":
    unittest.main()
