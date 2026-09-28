import hashlib
import json
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit.collector import CollectorService
from ai_native_devkit.errors import ContractError, StoreError
from ai_native_devkit.execution_trace import (
    EVENT_SCHEMA_VERSION,
    ExecutionTraceStore,
    project_summary,
)


class ExecutionTraceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "execution-traces"
        self.store = ExecutionTraceStore(
            self.root,
            id_factory=lambda: "00000000-0000-4000-8000-000000000001",
            event_id_factory=self._event_id,
            clock=lambda: "2026-08-25T03:00:00.000Z",
        )
        self.event_number = 0

    def tearDown(self):
        self.temporary.cleanup()

    def _event_id(self):
        self.event_number += 1
        return f"event-{self.event_number}"

    def append(self, event_type, **overrides):
        fields = {
            "session_id": "session-01",
            "event_type": event_type,
            "actor": "system",
            "source": "codex_hook",
            "payload": {},
        }
        fields.update(overrides)
        return self.store.append(**fields)

    def _two_session_store(self):
        trace_ids = iter(
            (
                "00000000-0000-4000-8000-000000000011",
                "00000000-0000-4000-8000-000000000012",
            )
        )
        event_ids = iter(("event-a", "event-b", "event-c", "event-d"))
        return ExecutionTraceStore(
            self.root,
            id_factory=lambda: next(trace_ids),
            event_id_factory=lambda: next(event_ids),
            clock=lambda: "2026-08-27T01:00:00.000Z",
        )

    def _append_session_event(self, store, session_id, event_type="session.started"):
        return store.append(
            session_id=session_id,
            event_type=event_type,
            actor="system",
            source="devkit_runtime",
            payload={},
            context={"cwd": "/private/project"},
        )

    def test_iter_records_returns_each_mapped_trace_as_a_detached_record(self):
        store = self._two_session_store()
        self._append_session_event(store, "session-a")
        self._append_session_event(store, "session-b")
        records = list(store.iter_records())
        self.assertEqual(len(records), 2)
        self.assertTrue(
            all(
                set(record) == {"metadata", "events", "summary"}
                for record in records
            )
        )
        records[0]["metadata"]["capture_status"] = "mutated"
        records[0]["events"].clear()
        persisted = store.load_session(records[0]["metadata"]["session_id"])
        self.assertNotEqual(persisted["metadata"]["capture_status"], "mutated")
        self.assertTrue(persisted["events"])

    def test_iter_records_ignores_only_strict_atomic_session_temp_files(self):
        store = self._two_session_store()
        self._append_session_event(store, "session-a")
        key = hashlib.sha256(b"crashed-session").hexdigest()
        temporary = self.root / ".sessions" / f".{key}.json-{'a' * 16}"
        temporary.write_text("{}", encoding="utf-8")
        self.assertEqual(len(list(store.iter_records())), 1)
        (self.root / ".sessions" / ".unknown").write_text("{}", encoding="utf-8")
        with self.assertRaises(StoreError) as caught:
            list(store.iter_records())
        self.assertEqual(caught.exception.code, "trace.session_index_invalid")

    def test_iter_records_rejects_invalid_published_session_mapping(self):
        cases = ("unexpected", "wrong_hash", "mismatched_session", "malformed")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "traces"
                store = ExecutionTraceStore(
                    root,
                    id_factory=lambda: "00000000-0000-4000-8000-000000000021",
                    event_id_factory=lambda: "event-1",
                    clock=lambda: "2026-08-27T01:00:00.000Z",
                )
                self._append_session_event(store, "session-a")
                session_root = root / ".sessions"
                published = next(session_root.glob("*.json"))
                if case == "unexpected":
                    (session_root / "unexpected.txt").write_text(
                        "{}", encoding="utf-8"
                    )
                elif case == "wrong_hash":
                    published.rename(session_root / ("f" * 64 + ".json"))
                elif case == "mismatched_session":
                    value = json.loads(published.read_text(encoding="utf-8"))
                    value["session_id"] = "session-other"
                    published.write_text(json.dumps(value), encoding="utf-8")
                else:
                    published.write_text("not-json", encoding="utf-8")
                with self.assertRaises(StoreError) as caught:
                    list(store.iter_records())
                self.assertEqual(caught.exception.code, "trace.session_index_invalid")

    def test_iter_records_rejects_symlinked_session_mapping(self):
        store = self._two_session_store()
        self._append_session_event(store, "session-a")
        session_root = self.root / ".sessions"
        outside = Path(self.temporary.name) / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        (session_root / ("f" * 64 + ".json")).symlink_to(outside)
        with self.assertRaises(StoreError) as caught:
            list(store.iter_records())
        self.assertEqual(caught.exception.code, "trace.session_index_invalid")

    def test_iter_records_rejects_summary_that_does_not_match_events(self):
        store = self._two_session_store()
        appended = self._append_session_event(store, "session-a")
        summary_path = self.root / appended["metadata"]["trace_id"] / "summary.json"
        forged = json.loads(summary_path.read_text(encoding="utf-8"))
        forged["task_result"] = "passed"
        summary_path.write_text(json.dumps(forged), encoding="utf-8")

        with self.assertRaises(StoreError) as caught:
            list(store.iter_records())

        self.assertEqual(caught.exception.code, "trace.session_index_invalid")

    def test_iter_records_rejects_mapping_session_that_conflicts_with_metadata(self):
        store = self._two_session_store()
        self._append_session_event(store, "session-a")
        session_root = self.root / ".sessions"
        published = next(session_root.glob("*.json"))
        mapping = json.loads(published.read_text(encoding="utf-8"))
        mapping["session_id"] = "session-other"
        remapped = session_root / (hashlib.sha256(b"session-other").hexdigest() + ".json")
        published.rename(remapped)
        remapped.write_text(json.dumps(mapping), encoding="utf-8")

        with self.assertRaises(StoreError) as caught:
            list(store.iter_records())

        self.assertEqual(caught.exception.code, "trace.session_index_invalid")

    def test_iter_records_waits_for_inflight_append_and_returns_coherent_record(self):
        writer = self._two_session_store()
        reader = ExecutionTraceStore(self.root)
        self._append_session_event(writer, "session-a")
        paused = threading.Event()
        release = threading.Event()
        original_append_event = writer._append_event

        def append_then_pause(trace_id, encoded):
            original_append_event(trace_id, encoded)
            if trace_id == "00000000-0000-4000-8000-000000000012":
                paused.set()
                self.assertTrue(release.wait(2))

        writer._append_event = append_then_pause
        append_error = []
        scan_error = []
        scanned = []
        append_thread = threading.Thread(
            target=lambda: self._capture_thread_error(
                append_error,
                lambda: self._append_session_event(writer, "session-b"),
            )
        )
        scan_thread = threading.Thread(
            target=lambda: self._capture_thread_error(
                scan_error, lambda: scanned.extend(reader.iter_records())
            )
        )
        append_thread.start()
        self.assertTrue(paused.wait(2))
        scan_thread.start()
        time.sleep(0.05)
        self.assertTrue(scan_thread.is_alive())
        release.set()
        append_thread.join(2)
        scan_thread.join(2)
        self.assertFalse(append_thread.is_alive())
        self.assertFalse(scan_thread.is_alive())
        self.assertEqual(append_error + scan_error, [])
        self.assertEqual(len(scanned), 2)
        for record in scanned:
            self.assertEqual(
                record["summary"],
                project_summary(record["metadata"], record["events"]),
            )

    def _capture_thread_error(self, errors, operation):
        try:
            operation()
        except Exception as error:  # assertions below re-raise with context
            errors.append(error)

    def test_session_maps_one_to_one_to_append_only_full_events(self):
        self.append(
            "session.started",
            context={"cwd": "/private/project", "model": "gpt-test"},
            payload={"start_source": "startup"},
        )
        self.append(
            "turn.prompt_submitted",
            actor="user",
            correlation={"turn_id": "turn-01"},
            payload={"prompt_chars": 32},
        )
        completed = self.append(
            "session.ended",
            payload={"reason": "other"},
            timestamp="2026-08-25T03:00:01.000Z",
        )

        trace_id = self.store.trace_id_for_session("session-01")
        self.assertEqual(trace_id, "00000000-0000-4000-8000-000000000001")
        loaded = self.store.load_session("session-01")
        self.assertEqual(loaded["metadata"]["session_id"], "session-01")
        self.assertEqual(loaded["metadata"]["capture_status"], "complete")
        self.assertRegex(loaded["metadata"]["repository"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("/private/project", json.dumps(loaded))
        self.assertEqual([event["seq"] for event in loaded["events"]], [1, 2, 3])
        self.assertEqual(loaded["summary"]["dialogue_count"], 1)
        self.assertEqual(loaded["summary"]["duration_ms"], 1000)
        self.assertEqual(completed["event"]["schema_version"], EVENT_SCHEMA_VERSION)
        self.assertEqual(
            set(completed["event"]),
            {
                "schema_version",
                "trace_id",
                "seq",
                "event_id",
                "timestamp",
                "event_type",
                "stage",
                "actor",
                "source",
                "correlation",
                "payload",
            },
        )
        for forbidden in (
            "task_id",
            "case_id",
            "expected_route",
            "docs_should_read",
            "observation_mode",
        ):
            self.assertNotIn(forbidden, json.dumps(loaded))

    def test_runtime_events_project_route_stages_docs_and_verification(self):
        service = CollectorService(self.store)
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.started",
                "payload": {"workflow_name": "coding-sop"},
            }
        )
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.route.selected",
                "payload": {
                    "intent": "development",
                    "workflow_tier": "standard",
                    "route": "development",
                    "change_kind": "feature",
                },
            }
        )
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.stage.started",
                "stage": "verify",
                "correlation": {"stage_run_id": "verify-01"},
                "payload": {"stage": "verify"},
            }
        )
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "docs.read",
                "payload": {"path": "docs/contracts.md"},
            }
        )
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "verification.completed",
                "stage": "verify",
                "payload": {"passed": True},
            }
        )
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.stage.completed",
                "stage": "verify",
                "payload": {"stage": "verify"},
            }
        )
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.completed",
                "payload": {"status": "completed"},
            }
        )

        loaded = self.store.load_session("session-01")
        self.assertEqual(loaded["metadata"]["workflow_name"], "coding-sop")
        self.assertEqual(loaded["metadata"]["capture_status"], "complete")
        summary = loaded["summary"]
        self.assertEqual(summary["actual_route"], "development")
        self.assertEqual(
            summary["actual_stages"],
            [
                {
                    "stage": "verify",
                    "stage_run_id": "verify-01",
                    "status": "completed",
                    "started_at": "2026-08-25T03:00:00.000Z",
                    "ended_at": "2026-08-25T03:00:00.000Z",
                    "duration_ms": 0,
                }
            ],
        )
        self.assertEqual(summary["docs_actual_read"], ["docs/contracts.md"])
        self.assertTrue(summary["verification_result"]["passed"])
        self.assertEqual(summary["task_result"], "passed")

    def test_clarify_summary_projects_only_subject_identity(self):
        service = CollectorService(self.store)
        subject_digest = "sha256:" + "a" * 64
        service.emit_runtime({
            "session_id": "session-01", "event_type": "workflow.stage.started",
            "stage": "clarify", "correlation": {"stage_run_id": "clarify-01"},
            "payload": {"stage": "clarify"},
        })
        service.emit_runtime({
            "session_id": "session-01", "event_type": "approval.requested",
            "stage": "clarify", "correlation": {"stage_run_id": "clarify-01"},
            "payload": {"approval_id": "approval-01",
                        "approval_kind": "clarify.requirements",
                        "subject_kind": "requirement_document",
                        "subject_digest": subject_digest},
        })
        service.emit_runtime({
            "session_id": "session-01", "event_type": "workflow.stage.completed",
            "stage": "clarify", "correlation": {"stage_run_id": "clarify-01"},
            "payload": {"stage": "clarify", "approval_id": "approval-01",
                        "subject_kind": "requirement_document",
                        "subject_digest": subject_digest},
        })
        summary = self.store.load_session("session-01")["summary"]
        run = summary["actual_stages"][0]
        self.assertEqual(run["approval_id"], "approval-01")
        self.assertEqual(run["subject_kind"], "requirement_document")
        self.assertEqual(run["subject_digest"], subject_digest)
        self.assertNotIn('"subject":', json.dumps(summary))

    def test_stage_summary_projects_only_the_source_subject_digest(self):
        service = CollectorService(self.store)
        source_digest = "sha256:" + "b" * 64
        service.emit_runtime({
            "session_id": "session-01", "event_type": "workflow.stage.started",
            "stage": "execute", "correlation": {"stage_run_id": "execute-01"},
            "payload": {"stage": "execute",
                        "source_subject_digest": source_digest},
        })
        service.emit_runtime({
            "session_id": "session-01", "event_type": "workflow.stage.completed",
            "stage": "execute", "correlation": {"stage_run_id": "execute-01"},
            "payload": {"stage": "execute"},
        })

        summary = self.store.load_session("session-01")["summary"]
        self.assertEqual(
            summary["actual_stages"][0]["source_subject_digest"], source_digest
        )
        self.assertNotIn("source_document", json.dumps(summary))

    def test_runtime_event_inherits_the_active_host_turn_and_unambiguous_tool(self):
        self.append("session.started", context={"cwd": "/private/project"})
        self.append(
            "turn.prompt_submitted",
            actor="user",
            correlation={"turn_id": "turn-active"},
        )
        self.append(
            "tool.requested",
            actor="agent",
            correlation={"turn_id": "turn-active", "tool_call_id": "tool-active"},
        )

        result = CollectorService(self.store).emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "init.completed",
                "stage": "init",
                "correlation": {"stage_run_id": "init-run"},
                "payload": {"outcome": "ready"},
            }
        )

        self.assertEqual(result["event"]["correlation"]["turn_id"], "turn-active")
        self.assertEqual(result["event"]["correlation"]["tool_call_id"], "tool-active")
        self.assertEqual(result["event"]["correlation"]["stage_run_id"], "init-run")

    def test_host_events_are_scoped_to_an_active_plugin_workflow(self):
        service = CollectorService(self.store)
        hook = {
            "session_id": "session-01",
            "hook_event_name": "UserPromptSubmit",
            "turn_id": "turn-01",
            "prompt": "not persisted",
        }

        ignored = service.collect_codex(hook)
        self.assertEqual(ignored["reason"], "plugin_workflow_inactive")
        self.assertIsNone(self.store.load_session("session-01"))

        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.started",
                "payload": {"workflow_name": "coding-sop"},
            }
        )
        collected = service.collect_codex(hook)
        self.assertEqual(collected["event"]["event_type"], "turn.prompt_submitted")

        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.failed",
                "payload": {"status": "failed"},
            }
        )
        ignored_after_finish = service.collect_codex(
            {
                "session_id": "session-01",
                "hook_event_name": "Stop",
                "turn_id": "turn-02",
            }
        )
        self.assertEqual(
            ignored_after_finish["reason"], "plugin_workflow_inactive"
        )
        loaded = self.store.load_session("session-01")
        self.assertEqual(loaded["metadata"]["capture_status"], "failed")
        self.assertEqual(
            [event["event_type"] for event in loaded["events"]],
            [
                "workflow.started",
                "turn.prompt_submitted",
                "workflow.failed",
            ],
        )

    def test_session_end_closes_unmatched_tools_after_workflow_completion(self):
        service = CollectorService(self.store)
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.started",
                "payload": {"workflow_name": "coding-sop"},
            }
        )
        self.append(
            "turn.prompt_submitted",
            actor="user",
            correlation={"turn_id": "turn-final"},
        )
        self.append(
            "tool.requested",
            actor="agent",
            correlation={"turn_id": "turn-final", "tool_call_id": "tool-final"},
        )
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.completed",
                "payload": {"status": "completed"},
            }
        )
        transcript = Path(self.temporary.name) / "rollout.jsonl"
        transcript.write_text(
            "\n".join(
                json.dumps(item)
                for item in (
                    {
                        "timestamp": "2026-08-25T03:00:01.000Z",
                        "type": "turn_context",
                        "payload": {"turn_id": "turn-non-plugin"},
                    },
                    {
                        "timestamp": "2026-08-25T03:00:01.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "ordinary follow-up",
                        },
                    },
                    {
                        "timestamp": "2026-08-25T03:00:01.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "call_id": "tool-non-plugin",
                            "name": "Bash",
                        },
                    },
                )
            )
            + "\n",
            encoding="utf-8",
        )

        ended = service.collect_codex(
            {
                "session_id": "session-01",
                "hook_event_name": "SessionEnd",
                "cwd": "/private/project",
                "reason": "other",
                "transcript_path": str(transcript),
            }
        )

        self.assertEqual(ended["event"]["event_type"], "session.ended")
        loaded = self.store.load_session("session-01")
        self.assertEqual(
            [event["event_type"] for event in loaded["events"][-2:]],
            ["tool.abandoned", "session.ended"],
        )
        self.assertEqual(loaded["summary"]["tool_counts"]["abandoned"], 1)
        self.assertEqual(loaded["summary"]["dialogue_count"], 1)
        self.assertEqual(loaded["metadata"]["capture_status"], "partial")

    def test_completed_workflow_does_not_collect_later_non_plugin_turns(self):
        service = CollectorService(self.store)
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.started",
                "payload": {"workflow_name": "coding-sop"},
            }
        )
        self.append(
            "turn.prompt_submitted",
            actor="user",
            correlation={"turn_id": "turn-plugin"},
        )
        service.emit_runtime(
            {
                "session_id": "session-01",
                "event_type": "workflow.completed",
                "payload": {"status": "completed"},
            }
        )

        ignored_prompt = service.collect_codex(
            {
                "session_id": "session-01",
                "hook_event_name": "UserPromptSubmit",
                "turn_id": "turn-later",
                "prompt": "ordinary follow-up",
            }
        )
        ignored_stop = service.collect_codex(
            {
                "session_id": "session-01",
                "hook_event_name": "Stop",
                "turn_id": "turn-later",
            }
        )

        self.assertEqual(ignored_prompt["reason"], "plugin_workflow_inactive")
        self.assertEqual(ignored_stop["reason"], "plugin_workflow_inactive")
        self.assertEqual(
            [event["event_type"] for event in self.store.load_session("session-01")["events"]],
            ["workflow.started", "turn.prompt_submitted", "workflow.completed"],
        )

    def test_unknown_event_type_and_unregistered_source_are_rejected(self):
        with self.assertRaises(ContractError):
            self.append("model.hidden_reasoning")
        with self.assertRaises(ContractError):
            self.append("session.started", source="session_log")

    def test_transcript_fallback_marks_capture_partial(self):
        self.append(
            "turn.stopped",
            actor="agent",
            source="codex_transcript_fallback",
            correlation={"turn_id": "turn-01"},
        )
        self.assertEqual(
            self.store.load_session("session-01")["metadata"]["capture_status"],
            "partial",
        )

    def test_runtime_payload_secrets_are_redacted_before_append(self):
        result = self.append(
            "workflow.started",
            actor="runtime",
            source="devkit_runtime",
            payload={"workflow_name": "coding-sop", "token": "secret-value"},
        )

        serialized = json.dumps(result["event"])
        self.assertNotIn("secret-value", serialized)
        self.assertEqual(result["event"]["payload"]["token"], "[REDACTED]")

    def test_concurrent_appends_keep_one_trace_and_monotonic_sequence(self):
        store = ExecutionTraceStore(self.root)
        failures = []

        def append(index):
            try:
                store.append(
                    session_id="concurrent-session",
                    event_type="tool.requested",
                    actor="agent",
                    source="codex_hook",
                    correlation={"turn_id": "turn-01", "tool_call_id": f"call-{index}"},
                    payload={"tool": "Bash"},
                )
            except Exception as error:  # pragma: no cover - failure assertion below.
                failures.append(error)

        threads = [threading.Thread(target=append, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        loaded = store.load_session("concurrent-session")
        self.assertEqual(len(loaded["events"]), 12)
        self.assertEqual([event["seq"] for event in loaded["events"]], list(range(1, 13)))


if __name__ == "__main__":
    unittest.main()
