from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts" / "runtime_cli.py"
SCRIPTS_ROOT = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit.collector import CollectorService
from ai_native_devkit.execution_trace import ExecutionTraceStore, repository_digest
from ai_native_devkit.requirement_document import RequirementDocumentWriter
import ai_native_devkit.runtime_cli as runtime_cli


SCHEMA_VERSION = "ai-native-devkit/v1alpha1"


def git(repository, *args):
    result = subprocess.run(
        ["git", *args], cwd=repository, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def run_cli(state_root, request, session_id="session-runtime-01"):
    environment = os.environ.copy()
    environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
    environment["CODEX_THREAD_ID"] = session_id
    return subprocess.run(
        [sys.executable, str(CLI)],
        input=json.dumps({"schema_version": SCHEMA_VERSION, **request}),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


class RuntimeTraceAndDocsHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.repository = self.root / "repository"
        self.repository.mkdir()
        git(self.repository, "init", "-b", "main")
        git(self.repository, "config", "user.name", "Test User")
        git(self.repository, "config", "user.email", "test@example.com")
        (self.repository / "README.md").write_text("# Project\n", encoding="utf-8")
        git(self.repository, "add", "README.md")
        git(self.repository, "commit", "-m", "initial")
        self.baseline = git(self.repository, "rev-parse", "HEAD")

    def tearDown(self):
        self.temporary.cleanup()

    def route(self, intent="debug", tier="fast", route="debug", change_kind=None):
        change_kind = change_kind or ("bug" if intent == "debug" else "feature")
        return run_cli(
            self.state,
            {
                "operation": "workflow.route",
                "cwd": str(self.repository),
                "intent": intent,
                "workflow_tier": tier,
                "route": route,
                "change_kind": change_kind,
            },
        )

    def write_requirement(self, title="Login Policy", requirements="Administrators revoke sessions."):
        return RequirementDocumentWriter(today=lambda: date(2026, 8, 27)).write_and_commit(
            repository_root=self.repository,
            title=title,
            clarified_requirements=requirements,
        )

    def record_prompt(self, turn_id, session_id="session-runtime-01"):
        return ExecutionTraceStore(self.state / "execution-traces").append(
            session_id=session_id,
            event_type="turn.prompt_submitted",
            actor="user",
            source="codex_hook",
            stage="clarify",
            correlation={"turn_id": turn_id},
            payload={"prompt_chars": 7},
            context={"cwd": str(self.repository)},
        )

    def record_stage_prompt(self, turn_id, stage, session_id="session-runtime-01"):
        return ExecutionTraceStore(self.state / "execution-traces").append(
            session_id=session_id,
            event_type="turn.prompt_submitted",
            actor="user",
            source="codex_hook",
            stage=stage,
            correlation={"turn_id": turn_id},
            payload={"prompt_chars": 7},
            context={"cwd": str(self.repository)},
        )

    def document_subject(self, kind, markdown):
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        return {"kind": kind, "digest": f"sha256:{digest}"}

    def complete_exact_document_stage(self, stage, subject, source_digest=None):
        start_request = {
            "operation": "stage.start", "stage": stage,
            "cwd": str(self.repository),
        }
        if source_digest is not None:
            start_request["source_subject_digest"] = source_digest
        started_result = run_cli(self.state, start_request)
        self.assertEqual(started_result.returncode, 0, started_result.stdout)
        started = json.loads(started_result.stdout)
        self.record_stage_prompt(f"{stage}-request", stage)
        requested_result = run_cli(self.state, {
            "operation": "approval.request", "stage": stage,
            "stage_run_id": started["stage_run_id"],
            "approval_kind": (
                "design.solution" if stage == "design" else "plan.implementation"
            ),
            "subject": subject, "cwd": str(self.repository),
        })
        self.assertEqual(requested_result.returncode, 0, requested_result.stdout)
        requested = json.loads(requested_result.stdout)
        self.record_stage_prompt(f"{stage}-approval", stage)
        resolved = run_cli(self.state, {
            "operation": "approval.resolve", "approval_id": requested["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        })
        self.assertEqual(resolved.returncode, 0, resolved.stdout)
        completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": stage,
            "stage_run_id": started["stage_run_id"], "subject": subject,
            "cwd": str(self.repository),
        })
        self.assertEqual(completed.returncode, 0, completed.stdout)
        return started

    def start_clarify(self, session_id="session-runtime-01"):
        routed = run_cli(self.state, {
            "operation": "workflow.route", "cwd": str(self.repository),
            "intent": "development", "workflow_tier": "strict",
            "route": "development", "change_kind": "feature",
        }, session_id=session_id)
        self.assertEqual(routed.returncode, 0, routed.stdout)
        started = run_cli(self.state, {
            "operation": "stage.start", "stage": "clarify",
            "cwd": str(self.repository),
        }, session_id=session_id)
        self.assertEqual(started.returncode, 0, started.stdout)
        return json.loads(started.stdout)

    def request_requirement_approval(self, started, reference, session_id="session-runtime-01"):
        return run_cli(self.state, {
            "operation": "approval.request", "stage": "clarify",
            "stage_run_id": started["stage_run_id"],
            "approval_kind": "clarify.requirements",
            "subject": reference.to_dict(), "cwd": str(self.repository),
        }, session_id=session_id)

    def approve_and_complete_requirement(self, started, reference, session_id):
        self.record_prompt("turn-request", session_id)
        requested = json.loads(
            self.request_requirement_approval(started, reference, session_id).stdout
        )
        self.record_prompt("turn-approval", session_id)
        resolved = run_cli(self.state, {
            "operation": "approval.resolve", "approval_id": requested["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        }, session_id=session_id)
        self.assertEqual(resolved.returncode, 0, resolved.stdout)
        completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": "clarify",
            "stage_run_id": started["stage_run_id"],
            "subject": reference.to_dict(), "cwd": str(self.repository),
        }, session_id=session_id)
        self.assertEqual(completed.returncode, 0, completed.stdout)
        return requested

    def test_clarify_completion_requires_exact_subject_and_later_turn(self):
        started = self.start_clarify()
        self.record_prompt("turn-request")
        reference = self.write_requirement()
        requested = json.loads(
            self.request_requirement_approval(started, reference).stdout
        )
        same_turn = run_cli(self.state, {
            "operation": "approval.resolve", "approval_id": requested["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        })
        self.assertNotEqual(same_turn.returncode, 0)
        self.assertEqual(json.loads(same_turn.stdout)["code"], "rejected.contract")
        self.record_prompt("turn-approval")
        resolved = run_cli(self.state, {
            "operation": "approval.resolve", "approval_id": requested["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        })
        completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": "clarify",
            "stage_run_id": started["stage_run_id"],
            "subject": reference.to_dict(), "cwd": str(self.repository),
        })
        self.assertEqual(resolved.returncode, 0, resolved.stdout)
        self.assertEqual(completed.returncode, 0, completed.stdout)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        terminal = next(event for event in trace["events"] if
            event["event_type"] == "workflow.stage.completed" and event["stage"] == "clarify")
        self.assertEqual(terminal["payload"]["approval_id"], requested["approval_id"])
        self.assertEqual(terminal["payload"]["subject_kind"], "requirement_document")
        self.assertEqual(terminal["payload"]["subject_digest"], reference.subject_digest())
        approval_events = [
            event for event in trace["events"]
            if event["event_type"] in {"approval.requested", "approval.resolved"}
        ]
        self.assertEqual(len(approval_events), 2)
        for event in approval_events:
            self.assertEqual(event["payload"]["approval_id"], requested["approval_id"])
            self.assertEqual(event["payload"]["subject_kind"], "requirement_document")
            self.assertEqual(event["payload"]["subject_digest"], reference.subject_digest())
        serialized = json.dumps(trace)
        for private_token in ("markdown", "clarified_requirements", "sources", "Administrators revoke sessions."):
            self.assertNotIn(private_token, serialized)

    def test_runtime_rejects_non_string_operation_before_dispatch(self):
        trace_root_path = self.state / "execution-traces"
        for operation in (None, [], {}):
            with self.subTest(operation=operation):
                result = run_cli(self.state, {"operation": operation, "cwd": str(self.repository)})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
        self.assertFalse(trace_root_path.exists())

    def test_clarify_rejects_malformed_or_no_longer_current_reference(self):
        started = self.start_clarify()
        self.record_prompt("turn-request")
        first = self.write_requirement()
        variants = (
            {"path": first.path},
            {**first.to_dict(), "commit": "a" * len(first.commit)},
            {**first.to_dict(), "blob_digest": "git-sha1:" + "b" * 40},
        )
        for subject in variants:
            with self.subTest(subject=subject):
                result = run_cli(self.state, {
                    "operation": "approval.request", "stage": "clarify",
                    "stage_run_id": started["stage_run_id"],
                    "approval_kind": "clarify.requirements", "subject": subject,
                    "cwd": str(self.repository),
                })
                self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
        RequirementDocumentWriter(today=lambda: date(2026, 8, 27)).write_and_commit(
            repository_root=self.repository, title="Login Policy",
            clarified_requirements="Administrators must record a reason.", supersedes=first,
        )
        stale = self.request_requirement_approval(started, first)
        self.assertEqual(json.loads(stale.stdout)["code"], "rejected.contract")

    def test_host_session_spoof_is_rejected_before_append(self):
        self.start_clarify()
        store = ExecutionTraceStore(self.state / "execution-traces")
        before = store.load_session("session-runtime-01")["events"]
        result = run_cli(self.state, {
            "operation": "stage.start", "stage": "clarify", "cwd": str(self.repository),
            "session_id": "session-foreign",
        }, session_id="session-runtime-01")
        self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
        self.assertEqual(store.load_session("session-runtime-01")["events"], before)

    def test_later_session_imports_only_the_exact_completed_approval(self):
        session_a = "session-runtime-01"
        started_a = self.start_clarify(session_a)
        reference = self.write_requirement()
        requested = self.approve_and_complete_requirement(started_a, reference, session_a)
        session_b = "session-runtime-02"
        started_b = self.start_clarify(session_b)
        imported = run_cli(self.state, {
            "operation": "stage.complete", "stage": "clarify",
            "stage_run_id": started_b["stage_run_id"], "subject": reference.to_dict(),
            "cwd": str(self.repository),
        }, session_id=session_b)
        self.assertEqual(imported.returncode, 0, imported.stdout)
        terminal = ExecutionTraceStore(self.state / "execution-traces").load_session(session_b)["events"][-1]
        self.assertEqual(terminal["payload"]["approval_id"], requested["approval_id"])
        self.assertEqual(terminal["payload"]["subject_digest"], reference.subject_digest())
        self.assertNotIn("markdown", json.dumps(terminal))

    def test_completed_clarify_retry_rejects_a_different_subject(self):
        started = self.start_clarify()
        approved = self.write_requirement(title="Login Policy")
        self.approve_and_complete_requirement(started, approved, "session-runtime-01")
        different = self.write_requirement(title="Audit Policy")
        retry = run_cli(self.state, {
            "operation": "stage.complete", "stage": "clarify",
            "stage_run_id": started["stage_run_id"], "subject": different.to_dict(),
            "cwd": str(self.repository),
        })
        self.assertEqual(json.loads(retry.stdout)["code"], "rejected.contract")

    def test_local_pending_subject_blocks_cross_session_approval_fallback(self):
        started_a = self.start_clarify("session-runtime-01")
        approved = self.write_requirement(title="Login Policy")
        self.approve_and_complete_requirement(started_a, approved, "session-runtime-01")
        started_b = self.start_clarify("session-runtime-02")
        self.record_prompt("turn-request-b", "session-runtime-02")
        pending = self.write_requirement(title="Audit Policy")
        requested_b = self.request_requirement_approval(started_b, pending, "session-runtime-02")
        self.assertEqual(requested_b.returncode, 0, requested_b.stdout)
        fallback = run_cli(self.state, {
            "operation": "stage.complete", "stage": "clarify",
            "stage_run_id": started_b["stage_run_id"], "subject": approved.to_dict(),
            "cwd": str(self.repository),
        }, session_id="session-runtime-02")
        self.assertEqual(json.loads(fallback.stdout)["code"], "rejected.contract")

    def test_pending_request_is_idempotent_only_for_the_same_subject(self):
        started = self.start_clarify()
        self.record_prompt("turn-request")
        reference_a = self.write_requirement(title="Login Policy")
        reference_b = self.write_requirement(title="Audit Policy")
        request_a = json.loads(self.request_requirement_approval(started, reference_a).stdout)
        request_a_retry = json.loads(self.request_requirement_approval(started, reference_a).stdout)
        request_b = self.request_requirement_approval(started, reference_b)
        self.assertEqual(request_a_retry["approval_id"], request_a["approval_id"])
        self.assertEqual(json.loads(request_b.stdout)["code"], "rejected.contract")

    def test_requirement_approval_request_requires_active_user_turn_evidence(self):
        started = self.start_clarify()
        reference = self.write_requirement()
        result = self.request_requirement_approval(started, reference)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
        events = ExecutionTraceStore(
            self.state / "execution-traces"
        ).load_session("session-runtime-01")["events"]
        self.assertFalse(any(event["event_type"] == "approval.requested" for event in events))

    def test_requirement_approval_rejects_prompt_that_predates_exact_stage_start(self):
        routed = self.route("development", "strict", "development", "feature")
        self.assertEqual(routed.returncode, 0, routed.stdout)
        self.record_prompt("turn-before-clarify")
        started = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "clarify",
            "cwd": str(self.repository),
        }).stdout)
        reference = self.write_requirement()
        result = self.request_requirement_approval(started, reference)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
        events = ExecutionTraceStore(
            self.state / "execution-traces"
        ).load_session("session-runtime-01")["events"]
        self.assertFalse(any(event["event_type"] == "approval.requested" for event in events))

    def test_stop_before_requirement_request_append_is_quarantined_and_retryable(self):
        started = self.start_clarify()
        self.record_prompt("turn-request")
        reference = self.write_requirement()
        original_emit = CollectorService.emit_runtime

        def stop_then_emit(service, value):
            if value.get("event_type") == "approval.requested":
                service.store.append(
                    session_id="session-runtime-01", event_type="turn.stopped",
                    actor="agent", source="codex_hook", stage="clarify",
                    correlation={"turn_id": "turn-request"}, payload={},
                    context={"cwd": str(self.repository)},
                )
            return original_emit(service, value)

        request = {
            "schema_version": SCHEMA_VERSION, "operation": "approval.request",
            "stage": "clarify", "stage_run_id": started["stage_run_id"],
            "approval_kind": "clarify.requirements",
            "subject": reference.to_dict(), "cwd": str(self.repository),
        }
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(request).encode("utf-8")))
        stdout = io.StringIO()
        with mock.patch.object(CollectorService, "emit_runtime", new=stop_then_emit), \
             mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout), \
             mock.patch.dict(os.environ, {"AI_NATIVE_DEVKIT_STATE_ROOT": str(self.state),
                                          "CODEX_THREAD_ID": "session-runtime-01"}, clear=False):
            self.assertEqual(runtime_cli.main(), 1)
        self.assertEqual(json.loads(stdout.getvalue())["code"], "rejected.contract")
        store = ExecutionTraceStore(self.state / "execution-traces")
        requests = [
            event for event in store.load_session("session-runtime-01")["events"]
            if event["event_type"] == "approval.requested"
        ]
        self.assertEqual(len(requests), 1)

        stopped_retry = self.request_requirement_approval(started, reference)
        self.assertNotEqual(stopped_retry.returncode, 0)
        self.record_prompt("turn-request-retry")
        recovered = self.request_requirement_approval(started, reference)
        self.assertEqual(recovered.returncode, 0, recovered.stdout)
        recovered_id = json.loads(recovered.stdout)["approval_id"]
        self.assertNotEqual(recovered_id, requests[0]["payload"]["approval_id"])
        self.record_prompt("turn-approval")
        resolved = run_cli(self.state, {
            "operation": "approval.resolve", "approval_id": recovered_id,
            "decision": "approved", "cwd": str(self.repository),
        })
        self.assertEqual(resolved.returncode, 0, resolved.stdout)
        completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": "clarify",
            "stage_run_id": started["stage_run_id"],
            "subject": reference.to_dict(), "cwd": str(self.repository),
        })
        self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_stop_sequenced_before_resolution_is_rejected_by_post_append_projection(self):
        started = self.start_clarify()
        self.record_prompt("turn-request")
        reference = self.write_requirement()
        requested = json.loads(self.request_requirement_approval(started, reference).stdout)
        self.record_prompt("turn-approval")
        original_emit = CollectorService.emit_runtime

        def stop_then_emit(service, value):
            if value.get("event_type") == "approval.resolved":
                service.store.append(
                    session_id="session-runtime-01", event_type="turn.stopped",
                    actor="agent", source="codex_hook", stage="clarify",
                    correlation={"turn_id": "turn-approval"}, payload={},
                    context={"cwd": str(self.repository)},
                )
            return original_emit(service, value)

        request = {"schema_version": SCHEMA_VERSION, "operation": "approval.resolve",
                   "approval_id": requested["approval_id"], "decision": "approved",
                   "cwd": str(self.repository)}
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(request).encode("utf-8")))
        stdout = io.StringIO()
        with mock.patch.object(CollectorService, "emit_runtime", new=stop_then_emit), \
             mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout), \
             mock.patch.dict(os.environ, {"AI_NATIVE_DEVKIT_STATE_ROOT": str(self.state),
                                          "CODEX_THREAD_ID": "session-runtime-01"}, clear=False):
            self.assertEqual(runtime_cli.main(), 1)
        self.assertEqual(json.loads(stdout.getvalue())["code"], "rejected.contract")
        completion = run_cli(self.state, {
            "operation": "stage.complete", "stage": "clarify",
            "stage_run_id": started["stage_run_id"], "subject": reference.to_dict(),
            "cwd": str(self.repository),
        })
        self.assertEqual(json.loads(completion.stdout)["code"], "rejected.contract")

    def test_imported_approval_satisfies_full_workflow_finish(self):
        session_a = "session-runtime-01"
        started_a = self.start_clarify(session_a)
        reference = self.write_requirement()
        self.approve_and_complete_requirement(started_a, reference, session_a)

        session_b = "session-runtime-02"
        routed = run_cli(self.state, {
            "operation": "workflow.route", "cwd": str(self.repository),
            "intent": "development", "workflow_tier": "strict",
            "route": "development", "change_kind": "feature",
        }, session_id=session_b)
        self.assertEqual(routed.returncode, 0, routed.stdout)
        store = ExecutionTraceStore(self.state / "execution-traces")

        def append(event_type, stage, run_id, payload):
            store.append(
                session_id=session_b, event_type=event_type, actor="runtime",
                source="devkit_runtime", stage=stage,
                correlation={"stage_run_id": run_id}, payload=payload,
                context={"cwd": str(self.repository)},
            )

        def complete(stage, approval_kind=None):
            run_id = stage + "-run"
            append("workflow.stage.started", stage, run_id, {
                "stage": stage, "repository": repository_digest(str(self.repository)),
            })
            if approval_kind is not None:
                approval_id = stage + "-approval"
                append("approval.requested", stage, run_id, {
                    "approval_id": approval_id, "approval_kind": approval_kind,
                })
                append("approval.resolved", stage, run_id, {
                    "approval_id": approval_id, "approval_kind": approval_kind,
                    "decision": "approved",
                })
            if stage == "verify":
                append("verification.completed", stage, run_id, {"passed": True})
            if stage == "sync-docs":
                append("docs.impact.classified", stage, run_id, {
                    "docsImpact": "NO_CHANGE",
                })
            append("workflow.stage.completed", stage, run_id, {"stage": stage})

        complete("init")
        started_b = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "clarify",
            "cwd": str(self.repository),
        }, session_id=session_b).stdout)
        imported = run_cli(self.state, {
            "operation": "stage.complete", "stage": "clarify",
            "stage_run_id": started_b["stage_run_id"], "subject": reference.to_dict(),
            "cwd": str(self.repository),
        }, session_id=session_b)
        self.assertEqual(imported.returncode, 0, imported.stdout)
        complete("design", "design.solution")
        complete("plan", "plan.implementation")
        complete("execute")
        complete("verify")
        complete("sync-docs")
        finished = run_cli(self.state, {
            "operation": "workflow.finish", "status": "completed",
            "cwd": str(self.repository),
        }, session_id=session_b)
        self.assertEqual(finished.returncode, 0, finished.stdout)

    def verify(self, passed=True):
        return run_cli(
            self.state,
            {
                "operation": "verification.complete",
                "repository": {"path": str(self.repository)},
                "baseline_revision": self.baseline,
                "verification": {
                    "result": "pass" if passed else "fail",
                    "criteria_total": 2,
                    "criteria_passed": 2 if passed else 1,
                    "remaining_risks_count": 0,
                    "candidate_revision": git(self.repository, "rev-parse", "HEAD"),
                },
            },
        )

    def complete_stage(self, stage):
        if stage == "init":
            collector = CollectorService(
                ExecutionTraceStore(self.state / "execution-traces")
            )
            stage_run_id = "managed-init-run"
            correlation = {"stage_run_id": stage_run_id}
            collector.emit_runtime(
                {
                    "session_id": "session-runtime-01",
                    "event_type": "workflow.stage.started",
                    "stage": "init",
                    "correlation": correlation,
                    "cwd": str(self.repository),
                    "payload": {
                        "stage": "init",
                        "repository": repository_digest(str(self.repository)),
                    },
                }
            )
            collector.emit_runtime(
                {
                    "session_id": "session-runtime-01",
                    "event_type": "init.completed",
                    "stage": "init",
                    "correlation": correlation,
                    "cwd": str(self.repository),
                    "payload": {"outcome": "ready"},
                }
            )
            collector.emit_runtime(
                {
                    "session_id": "session-runtime-01",
                    "event_type": "workflow.stage.completed",
                    "stage": "init",
                    "correlation": correlation,
                    "cwd": str(self.repository),
                    "payload": {"stage": "init", "outcome": "ready"},
                }
            )

            class Result:
                returncode = 0

            return Result()
        started = json.loads(
            run_cli(
                self.state,
                {
                    "operation": "stage.start",
                    "stage": stage,
                    "cwd": str(self.repository),
                },
            ).stdout
        )
        return run_cli(
            self.state,
            {
                "operation": "stage.complete",
                "stage": stage,
                "stage_run_id": started["stage_run_id"],
                "cwd": str(self.repository),
            },
        )

    def test_verification_completion_automatically_runs_docs_hook_and_records_events(self):
        routed = self.route()
        self.assertEqual(routed.returncode, 0, routed.stdout)
        (self.repository / "tests").mkdir()
        (self.repository / "tests/test_bug.py").write_text("assert True\n", encoding="utf-8")

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stderr or verified.stdout)
        response = json.loads(verified.stdout)
        self.assertEqual(response["kind"], "verification_completion")
        self.assertTrue(response["docs_hook"]["triggered"])
        self.assertEqual(response["docs_hook"]["report"]["docsImpact"], "NO_CHANGE")
        self.assertNotIn("handoffSignal", response["docs_hook"]["report"])
        self.assertNotIn("askHandoff", response["docs_hook"]["report"])

        loaded = run_cli(self.state, {"operation": "trace.load"})
        trace = json.loads(loaded.stdout)["trace"]
        event_types = [event["event_type"] for event in trace["events"]]
        self.assertEqual(
            event_types,
            [
                "workflow.started",
                "workflow.route.selected",
                "workflow.stage.skipped",
                "workflow.stage.skipped",
                "workflow.stage.skipped",
                "workflow.stage.skipped",
                "workflow.stage.started",
                "verification.started",
                "verification.completed",
                "workflow.stage.completed",
                "docs.impact.classified",
                "workflow.stage.skipped",
                "docs.sync.skipped",
            ],
        )
        self.assertTrue(all(event["source"] == "devkit_runtime" for event in trace["events"]))
        self.assertEqual(trace["summary"]["actual_route"], "debug")
        self.assertEqual(
            trace["summary"]["hook_actual_result"]["docsImpact"], "NO_CHANGE"
        )

    def test_failed_verification_records_fact_without_triggering_docs_hook(self):
        self.assertEqual(self.route().returncode, 0)
        verified = self.verify(passed=False)

        self.assertEqual(verified.returncode, 0, verified.stdout)
        response = json.loads(verified.stdout)
        self.assertFalse(response["docs_hook"]["triggered"])
        trace = json.loads(
            run_cli(self.state, {"operation": "trace.load"}).stdout
        )["trace"]
        self.assertEqual(
            [event["event_type"] for event in trace["events"]],
            [
                "workflow.started",
                "workflow.route.selected",
                "workflow.stage.skipped",
                "workflow.stage.skipped",
                "workflow.stage.skipped",
                "workflow.stage.skipped",
                "workflow.stage.started",
                "verification.started",
                "verification.completed",
                "workflow.stage.completed",
                "workflow.stage.skipped",
                "docs.sync.skipped",
            ],
        )

    def test_route_runtime_rejects_inconsistent_route_projection(self):
        result = self.route(intent="development", tier="strict", route="lightweight")

        self.assertNotEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertEqual(response["kind"], "runtime_error")
        self.assertEqual(response["code"], "rejected.contract")

    def test_managed_init_stage_cannot_be_fabricated_by_runtime_cli(self):
        result = run_cli(
            self.state,
            {"operation": "stage.start", "stage": "init", "cwd": str(self.repository)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")

    def test_design_stage_requires_exact_approval_before_completion(self):
        self.assertEqual(
            self.route(
                intent="development",
                tier="strict",
                route="development",
                change_kind="feature",
            ).returncode,
            0,
        )
        started = json.loads(
            run_cli(
                self.state,
                {
                    "operation": "stage.start",
                    "stage": "design",
                    "cwd": str(self.repository),
                },
            ).stdout
        )
        requested = json.loads(
            run_cli(
                self.state,
                {
                    "operation": "approval.request",
                    "stage": "design",
                    "stage_run_id": started["stage_run_id"],
                    "approval_kind": "design.solution",
                    "cwd": str(self.repository),
                },
            ).stdout
        )
        premature = run_cli(
            self.state,
            {
                "operation": "stage.complete",
                "stage": "design",
                "stage_run_id": started["stage_run_id"],
                "cwd": str(self.repository),
            },
        )
        self.assertNotEqual(premature.returncode, 0)
        self.assertIn("approved user confirmation", json.loads(premature.stdout)["message"])

        resolved = run_cli(
            self.state,
            {
                "operation": "approval.resolve",
                "approval_id": requested["approval_id"],
                "decision": "approved",
                "cwd": str(self.repository),
            },
        )
        completed = run_cli(
            self.state,
            {
                "operation": "stage.complete",
                "stage": "design",
                "stage_run_id": started["stage_run_id"],
                "cwd": str(self.repository),
            },
        )

        self.assertEqual(resolved.returncode, 0, resolved.stdout)
        self.assertEqual(completed.returncode, 0, completed.stdout)
        trace = json.loads(
            run_cli(self.state, {"operation": "trace.load"}).stdout
        )["trace"]
        approvals = trace["summary"]["approval_results"]
        self.assertEqual(
            [item["event_type"] for item in approvals],
            ["approval.requested", "approval.resolved"],
        )
        self.assertEqual(approvals[0]["approval_id"], approvals[1]["approval_id"])
        design = next(
            item
            for item in trace["summary"]["actual_stages"]
            if item["stage"] == "design"
        )
        self.assertEqual(design["status"], "completed")
        self.assertIsNotNone(design["started_at"])
        self.assertIsNotNone(design["ended_at"])

    def test_design_document_approval_binds_digest_and_requires_a_later_turn(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        started = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "design",
            "cwd": str(self.repository),
        }).stdout)
        subject = self.document_subject(
            "design_document", "# Design\n\nApproved interface.\n"
        )
        self.record_stage_prompt("design-request", "design")
        requested = json.loads(run_cli(self.state, {
            "operation": "approval.request", "stage": "design",
            "stage_run_id": started["stage_run_id"],
            "approval_kind": "design.solution", "subject": subject,
            "cwd": str(self.repository),
        }).stdout)

        same_turn = run_cli(self.state, {
            "operation": "approval.resolve", "approval_id": requested["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        })
        self.assertNotEqual(same_turn.returncode, 0)

        self.record_stage_prompt("design-approval", "design")
        resolved = run_cli(self.state, {
            "operation": "approval.resolve", "approval_id": requested["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        })
        completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": "design",
            "stage_run_id": started["stage_run_id"], "subject": subject,
            "cwd": str(self.repository),
        })
        self.assertEqual(resolved.returncode, 0, resolved.stdout)
        self.assertEqual(completed.returncode, 0, completed.stdout)

        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        relevant = [
            event for event in trace["events"]
            if event.get("stage") == "design"
            and event["event_type"] in {
                "approval.requested", "approval.resolved", "workflow.stage.completed"
            }
        ]
        self.assertEqual(len(relevant), 3)
        for event in relevant:
            self.assertEqual(event["payload"]["subject_kind"], "design_document")
            self.assertEqual(event["payload"]["subject_digest"], subject["digest"])
        self.assertNotIn("Approved interface", json.dumps(trace))

    def test_exact_document_completion_retry_requires_the_original_subject(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        subject = self.document_subject("design_document", "# Stable design\n")
        started = self.complete_exact_document_stage("design", subject)
        changed = self.document_subject("design_document", "# Changed design\n")

        missing_retry = run_cli(self.state, {
            "operation": "stage.complete", "stage": "design",
            "stage_run_id": started["stage_run_id"],
            "cwd": str(self.repository),
        })
        changed_retry = run_cli(self.state, {
            "operation": "stage.complete", "stage": "design",
            "stage_run_id": started["stage_run_id"], "subject": changed,
            "cwd": str(self.repository),
        })
        exact_retry = run_cli(self.state, {
            "operation": "stage.complete", "stage": "design",
            "stage_run_id": started["stage_run_id"], "subject": subject,
            "cwd": str(self.repository),
        })
        self.assertNotEqual(missing_retry.returncode, 0)
        self.assertNotEqual(changed_retry.returncode, 0)
        self.assertEqual(exact_retry.returncode, 0, exact_retry.stdout)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        terminals = [
            event for event in trace["events"]
            if event["event_type"] == "workflow.stage.completed"
            and event.get("stage") == "design"
        ]
        self.assertEqual(len(terminals), 1)
        self.assertEqual(terminals[0]["payload"]["subject_digest"], subject["digest"])

    def test_document_subject_rejects_malformed_kind_and_sha256_digest(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        started = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "design",
            "cwd": str(self.repository),
        }).stdout)
        self.record_stage_prompt("design-request", "design")
        variants = (
            {"kind": "plan_document", "digest": "sha256:" + "a" * 64},
            {"kind": "design_document", "digest": "sha1:" + "a" * 40},
            {"kind": "design_document", "digest": "sha256:" + "A" * 64},
            {"kind": "design_document", "digest": "sha256:" + "a" * 63},
            {"kind": "design_document"},
        )
        for subject in variants:
            with self.subTest(subject=subject):
                result = run_cli(self.state, {
                    "operation": "approval.request", "stage": "design",
                    "stage_run_id": started["stage_run_id"],
                    "approval_kind": "design.solution", "subject": subject,
                    "cwd": str(self.repository),
                })
                self.assertNotEqual(result.returncode, 0)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        self.assertFalse(any(
            event["event_type"] == "approval.requested"
            and event.get("stage") == "design"
            for event in trace["events"]
        ))

    def test_plan_and_execute_start_only_from_the_digest_completed_upstream(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )

        def complete_approved(stage, subject):
            started = json.loads(run_cli(self.state, {
                "operation": "stage.start", "stage": stage,
                "source_subject_digest": (
                    design_subject["digest"] if stage == "plan" else None
                ),
                "cwd": str(self.repository),
            }).stdout)
            self.record_stage_prompt(f"{stage}-request", stage)
            requested = json.loads(run_cli(self.state, {
                "operation": "approval.request", "stage": stage,
                "stage_run_id": started["stage_run_id"],
                "approval_kind": (
                    "design.solution" if stage == "design" else "plan.implementation"
                ),
                "subject": subject, "cwd": str(self.repository),
            }).stdout)
            self.record_stage_prompt(f"{stage}-approval", stage)
            self.assertEqual(run_cli(self.state, {
                "operation": "approval.resolve", "approval_id": requested["approval_id"],
                "decision": "approved", "cwd": str(self.repository),
            }).returncode, 0)
            completed = run_cli(self.state, {
                "operation": "stage.complete", "stage": stage,
                "stage_run_id": started["stage_run_id"], "subject": subject,
                "cwd": str(self.repository),
            })
            self.assertEqual(completed.returncode, 0, completed.stdout)

        design_subject = self.document_subject("design_document", "# Design\n")
        plan_subject = self.document_subject("plan_document", "# Plan\n")
        complete_approved("design", design_subject)
        complete_approved("plan", plan_subject)

        wrong = run_cli(self.state, {
            "operation": "stage.start", "stage": "execute",
            "source_subject_digest": "sha256:" + "0" * 64,
            "cwd": str(self.repository),
        })
        self.assertNotEqual(wrong.returncode, 0)

        started = run_cli(self.state, {
            "operation": "stage.start", "stage": "execute",
            "source_subject_digest": plan_subject["digest"],
            "cwd": str(self.repository),
        })
        self.assertEqual(started.returncode, 0, started.stdout)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        execute_starts = [
            event for event in trace["events"]
            if event["event_type"] == "workflow.stage.started"
            and event.get("stage") == "execute"
        ]
        self.assertEqual(len(execute_starts), 1)
        self.assertEqual(
            execute_starts[0]["payload"]["source_subject_digest"],
            plan_subject["digest"],
        )

    def test_pending_plan_approval_cannot_be_reused_for_another_digest(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        started = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "plan",
            "cwd": str(self.repository),
        }).stdout)
        first = self.document_subject("plan_document", "# First plan\n")
        second = self.document_subject("plan_document", "# Second plan\n")
        self.record_stage_prompt("plan-request", "plan")
        requested = run_cli(self.state, {
            "operation": "approval.request", "stage": "plan",
            "stage_run_id": started["stage_run_id"],
            "approval_kind": "plan.implementation", "subject": first,
            "cwd": str(self.repository),
        })
        self.assertEqual(requested.returncode, 0, requested.stdout)
        same = run_cli(self.state, {
            "operation": "approval.request", "stage": "plan",
            "stage_run_id": started["stage_run_id"],
            "approval_kind": "plan.implementation", "subject": first,
            "cwd": str(self.repository),
        })
        self.assertEqual(same.returncode, 0, same.stdout)
        self.assertEqual(
            json.loads(same.stdout)["approval_id"],
            json.loads(requested.stdout)["approval_id"],
        )
        changed = run_cli(self.state, {
            "operation": "approval.request", "stage": "plan",
            "stage_run_id": started["stage_run_id"],
            "approval_kind": "plan.implementation", "subject": second,
            "cwd": str(self.repository),
        })
        self.assertNotEqual(changed.returncode, 0)

    def test_document_completion_rejects_forged_approval_without_turn_evidence(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        started = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "design",
            "cwd": str(self.repository),
        }).stdout)
        subject = self.document_subject("design_document", "# Forged design\n")
        store = ExecutionTraceStore(self.state / "execution-traces")
        approval_id = "forged-document-approval"
        common = {
            "session_id": "session-runtime-01",
            "actor": "runtime",
            "source": "devkit_runtime",
            "stage": "design",
            "correlation": {"stage_run_id": started["stage_run_id"]},
            "context": {"cwd": str(self.repository)},
        }
        store.append(
            event_type="approval.requested",
            payload={
                "approval_id": approval_id,
                "approval_kind": "design.solution",
                "subject_kind": subject["kind"],
                "subject_digest": subject["digest"],
            },
            **common,
        )
        store.append(
            event_type="approval.resolved",
            payload={
                "approval_id": approval_id,
                "approval_kind": "design.solution",
                "decision": "approved",
                "subject_kind": subject["kind"],
                "subject_digest": subject["digest"],
            },
            **common,
        )

        completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": "design",
            "stage_run_id": started["stage_run_id"], "subject": subject,
            "cwd": str(self.repository),
        })
        self.assertNotEqual(completed.returncode, 0)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        self.assertFalse(any(
            event["event_type"] == "workflow.stage.completed"
            and event.get("stage") == "design"
            for event in trace["events"]
        ))

    def test_plan_start_rejects_a_forged_design_subject_terminal(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        design = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "design",
            "cwd": str(self.repository),
        }).stdout)
        subject = self.document_subject("design_document", "# Forged terminal\n")
        ExecutionTraceStore(self.state / "execution-traces").append(
            session_id="session-runtime-01",
            event_type="workflow.stage.completed",
            actor="runtime",
            source="devkit_runtime",
            stage="design",
            correlation={"stage_run_id": design["stage_run_id"]},
            payload={
                "stage": "design",
                "repository": repository_digest(str(self.repository)),
                "approval_id": "missing-approval",
                "subject_kind": subject["kind"],
                "subject_digest": subject["digest"],
            },
            context={"cwd": str(self.repository)},
        )

        plan = run_cli(self.state, {
            "operation": "stage.start", "stage": "plan",
            "source_subject_digest": subject["digest"],
            "cwd": str(self.repository),
        })
        self.assertNotEqual(plan.returncode, 0)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        self.assertFalse(any(
            event["event_type"] == "workflow.stage.started"
            and event.get("stage") == "plan"
            for event in trace["events"]
        ))

    def test_exact_upstream_requires_source_digest_but_legacy_upstream_does_not(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        design_subject = self.document_subject("design_document", "# Exact design\n")
        self.complete_exact_document_stage("design", design_subject)

        missing_source = run_cli(self.state, {
            "operation": "stage.start", "stage": "plan",
            "cwd": str(self.repository),
        })
        self.assertNotEqual(missing_source.returncode, 0)

        legacy_design = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "design",
            "cwd": str(self.repository),
        }).stdout)
        legacy_request = json.loads(run_cli(self.state, {
            "operation": "approval.request", "stage": "design",
            "stage_run_id": legacy_design["stage_run_id"],
            "approval_kind": "design.solution", "cwd": str(self.repository),
        }).stdout)
        self.record_stage_prompt("legacy-design-approval", "design")
        legacy_resolved = run_cli(self.state, {
            "operation": "approval.resolve",
            "approval_id": legacy_request["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        })
        self.assertEqual(legacy_resolved.returncode, 0, legacy_resolved.stdout)
        legacy_completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": "design",
            "stage_run_id": legacy_design["stage_run_id"],
            "cwd": str(self.repository),
        })
        self.assertEqual(legacy_completed.returncode, 0, legacy_completed.stdout)

        legacy_plan = run_cli(self.state, {
            "operation": "stage.start", "stage": "plan",
            "cwd": str(self.repository),
        })
        self.assertEqual(legacy_plan.returncode, 0, legacy_plan.stdout)

    def test_active_exact_source_run_rejects_missing_or_different_retry(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        design_subject = self.document_subject("design_document", "# Design A\n")
        self.complete_exact_document_stage("design", design_subject)
        first_plan = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "plan",
            "source_subject_digest": design_subject["digest"],
            "cwd": str(self.repository),
        }).stdout)

        legacy_design = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "design",
            "cwd": str(self.repository),
        }).stdout)
        legacy_request = json.loads(run_cli(self.state, {
            "operation": "approval.request", "stage": "design",
            "stage_run_id": legacy_design["stage_run_id"],
            "approval_kind": "design.solution", "cwd": str(self.repository),
        }).stdout)
        self.record_stage_prompt("new-legacy-design-approval", "design")
        self.assertEqual(run_cli(self.state, {
            "operation": "approval.resolve",
            "approval_id": legacy_request["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        }).returncode, 0)
        self.assertEqual(run_cli(self.state, {
            "operation": "stage.complete", "stage": "design",
            "stage_run_id": legacy_design["stage_run_id"],
            "cwd": str(self.repository),
        }).returncode, 0)

        missing_source_retry = run_cli(self.state, {
            "operation": "stage.start", "stage": "plan",
            "cwd": str(self.repository),
        })
        self.assertNotEqual(missing_source_retry.returncode, 0)

        newer_design = self.document_subject("design_document", "# Design B\n")
        self.complete_exact_document_stage("design", newer_design)
        same_source_retry = run_cli(self.state, {
            "operation": "stage.start", "stage": "plan",
            "source_subject_digest": design_subject["digest"],
            "cwd": str(self.repository),
        })
        self.assertEqual(same_source_retry.returncode, 0, same_source_retry.stdout)
        self.assertEqual(
            json.loads(same_source_retry.stdout)["stage_run_id"],
            first_plan["stage_run_id"],
        )
        different_source_retry = run_cli(self.state, {
            "operation": "stage.start", "stage": "plan",
            "source_subject_digest": newer_design["digest"],
            "cwd": str(self.repository),
        })
        self.assertNotEqual(different_source_retry.returncode, 0)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        plan_starts = [
            event for event in trace["events"]
            if event["event_type"] == "workflow.stage.started"
            and event.get("stage") == "plan"
        ]
        self.assertEqual(len(plan_starts), 1)
        self.assertEqual(
            plan_starts[0]["correlation"]["stage_run_id"],
            first_plan["stage_run_id"],
        )

    def test_exact_plan_completion_rejects_a_run_started_before_exact_design(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        early_plan = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "plan",
            "cwd": str(self.repository),
        }).stdout)
        design_subject = self.document_subject("design_document", "# Design\n")
        self.complete_exact_document_stage("design", design_subject)

        plan_subject = self.document_subject("plan_document", "# Plan\n")
        self.record_stage_prompt("plan-request", "plan")
        requested = json.loads(run_cli(self.state, {
            "operation": "approval.request", "stage": "plan",
            "stage_run_id": early_plan["stage_run_id"],
            "approval_kind": "plan.implementation", "subject": plan_subject,
            "cwd": str(self.repository),
        }).stdout)
        self.record_stage_prompt("plan-approval", "plan")
        self.assertEqual(run_cli(self.state, {
            "operation": "approval.resolve", "approval_id": requested["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        }).returncode, 0)

        completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": "plan",
            "stage_run_id": early_plan["stage_run_id"], "subject": plan_subject,
            "cwd": str(self.repository),
        })
        self.assertNotEqual(completed.returncode, 0)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        self.assertFalse(any(
            event["event_type"] == "workflow.stage.completed"
            and event.get("stage") == "plan"
            for event in trace["events"]
        ))

    def test_execute_completion_rejects_a_run_started_before_exact_plan(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        early_execute = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "execute",
            "cwd": str(self.repository),
        }).stdout)
        design_subject = self.document_subject("design_document", "# Design\n")
        self.complete_exact_document_stage("design", design_subject)
        plan_subject = self.document_subject("plan_document", "# Plan\n")
        self.complete_exact_document_stage(
            "plan", plan_subject, source_digest=design_subject["digest"]
        )

        completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": "execute",
            "stage_run_id": early_execute["stage_run_id"],
            "cwd": str(self.repository),
        })
        self.assertNotEqual(completed.returncode, 0)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        self.assertFalse(any(
            event["event_type"] == "workflow.stage.completed"
            and event.get("stage") == "execute"
            for event in trace["events"]
        ))

    def test_exact_development_workflow_finishes_with_digest_bound_chain(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        self.assertEqual(self.complete_stage("init").returncode, 0)
        clarify = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "clarify",
            "cwd": str(self.repository),
        }).stdout)
        requirement = self.write_requirement()
        self.approve_and_complete_requirement(
            clarify, requirement, "session-runtime-01"
        )

        design_subject = self.document_subject("design_document", "# Design\n")
        self.complete_exact_document_stage("design", design_subject)
        plan_subject = self.document_subject("plan_document", "# Plan\n")
        self.complete_exact_document_stage(
            "plan", plan_subject, source_digest=design_subject["digest"]
        )
        execute = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "execute",
            "source_subject_digest": plan_subject["digest"],
            "cwd": str(self.repository),
        }).stdout)
        execute_completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": "execute",
            "stage_run_id": execute["stage_run_id"],
            "cwd": str(self.repository),
        })
        self.assertEqual(execute_completed.returncode, 0, execute_completed.stdout)

        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stdout)
        verification = json.loads(verified.stdout)
        if verification["docs_hook"]["report"]["docsImpact"] != "NO_CHANGE":
            trace = json.loads(
                run_cli(self.state, {"operation": "trace.load"}).stdout
            )["trace"]
            docs_start = next(
                event for event in reversed(trace["events"])
                if event["event_type"] == "workflow.stage.started"
                and event.get("stage") == "sync-docs"
            )
            docs_completed = run_cli(self.state, {
                "operation": "stage.complete", "stage": "sync-docs",
                "stage_run_id": docs_start["correlation"]["stage_run_id"],
                "cwd": str(self.repository),
            })
            self.assertEqual(docs_completed.returncode, 0, docs_completed.stdout)

        finished = run_cli(self.state, {
            "operation": "workflow.finish", "status": "completed",
            "cwd": str(self.repository),
        })
        self.assertEqual(finished.returncode, 0, finished.stdout)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        self.assertTrue(any(
            event["event_type"] == "workflow.completed"
            for event in trace["events"]
        ))

    def test_execute_and_finish_reject_an_exact_plan_with_no_design_source_chain(self):
        self.assertEqual(
            self.route("development", "strict", "development", "contract").returncode,
            0,
        )
        self.assertEqual(self.complete_stage("init").returncode, 0)
        clarify = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "clarify",
            "cwd": str(self.repository),
        }).stdout)
        requirement = self.write_requirement()
        self.approve_and_complete_requirement(
            clarify, requirement, "session-runtime-01"
        )

        early_plan = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "plan",
            "cwd": str(self.repository),
        }).stdout)
        design_subject = self.document_subject("design_document", "# Design\n")
        self.complete_exact_document_stage("design", design_subject)
        plan_subject = self.document_subject("plan_document", "# Plan\n")
        self.record_stage_prompt("plan-request", "plan")
        requested = json.loads(run_cli(self.state, {
            "operation": "approval.request", "stage": "plan",
            "stage_run_id": early_plan["stage_run_id"],
            "approval_kind": "plan.implementation", "subject": plan_subject,
            "cwd": str(self.repository),
        }).stdout)
        self.record_stage_prompt("plan-approval", "plan")
        self.assertEqual(run_cli(self.state, {
            "operation": "approval.resolve", "approval_id": requested["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        }).returncode, 0)
        store = ExecutionTraceStore(self.state / "execution-traces")
        store.append(
            session_id="session-runtime-01",
            event_type="workflow.stage.completed",
            actor="runtime",
            source="devkit_runtime",
            stage="plan",
            correlation={"stage_run_id": early_plan["stage_run_id"]},
            payload={
                "stage": "plan",
                "repository": repository_digest(str(self.repository)),
                "approval_id": requested["approval_id"],
                "subject_kind": plan_subject["kind"],
                "subject_digest": plan_subject["digest"],
            },
            context={"cwd": str(self.repository)},
        )

        execute = json.loads(run_cli(self.state, {
            "operation": "stage.start", "stage": "execute",
            "source_subject_digest": plan_subject["digest"],
            "cwd": str(self.repository),
        }).stdout)
        execute_completed = run_cli(self.state, {
            "operation": "stage.complete", "stage": "execute",
            "stage_run_id": execute["stage_run_id"],
            "cwd": str(self.repository),
        })
        self.assertNotEqual(execute_completed.returncode, 0)
        store.append(
            session_id="session-runtime-01",
            event_type="workflow.stage.completed",
            actor="runtime",
            source="devkit_runtime",
            stage="execute",
            correlation={"stage_run_id": execute["stage_run_id"]},
            payload={
                "stage": "execute",
                "repository": repository_digest(str(self.repository)),
            },
            context={"cwd": str(self.repository)},
        )

        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stdout)
        verification = json.loads(verified.stdout)
        if verification["docs_hook"]["report"]["docsImpact"] != "NO_CHANGE":
            trace = json.loads(
                run_cli(self.state, {"operation": "trace.load"}).stdout
            )["trace"]
            docs_start = next(
                event for event in reversed(trace["events"])
                if event["event_type"] == "workflow.stage.started"
                and event.get("stage") == "sync-docs"
            )
            self.assertEqual(run_cli(self.state, {
                "operation": "stage.complete", "stage": "sync-docs",
                "stage_run_id": docs_start["correlation"]["stage_run_id"],
                "cwd": str(self.repository),
            }).returncode, 0)

        finished = run_cli(self.state, {
            "operation": "workflow.finish", "status": "completed",
            "cwd": str(self.repository),
        })
        self.assertNotEqual(finished.returncode, 0)
        trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
        self.assertFalse(any(
            event["event_type"] == "workflow.completed"
            for event in trace["events"]
        ))

    def test_active_stage_runs_are_scoped_by_repository_digest(self):
        other = self.root / "other-repository"
        other.mkdir()
        git(other, "init", "-b", "main")
        git(other, "config", "user.name", "Test User")
        git(other, "config", "user.email", "test@example.com")
        (other / "README.md").write_text("# Other\n", encoding="utf-8")
        git(other, "add", "README.md")
        git(other, "commit", "-m", "initial")

        first = json.loads(
            run_cli(
                self.state,
                {
                    "operation": "stage.start",
                    "stage": "design",
                    "cwd": str(self.repository),
                },
            ).stdout
        )
        second = json.loads(
            run_cli(
                self.state,
                {
                    "operation": "stage.start",
                    "stage": "design",
                    "cwd": str(other),
                },
            ).stdout
        )

        self.assertNotEqual(first["stage_run_id"], second["stage_run_id"])
        trace = json.loads(
            run_cli(self.state, {"operation": "trace.load"}).stdout
        )["trace"]
        design_runs = [
            item
            for item in trace["summary"]["actual_stages"]
            if item["stage"] == "design"
        ]
        self.assertEqual(len(design_runs), 2)
        self.assertNotEqual(
            design_runs[0]["repository"], design_runs[1]["repository"]
        )

    def test_terminal_stage_does_not_reopen_and_cannot_cross_repositories(self):
        other = self.root / "other-repository"
        other.mkdir()
        git(other, "init", "-b", "main")
        git(other, "config", "user.name", "Test User")
        git(other, "config", "user.email", "test@example.com")
        (other / "README.md").write_text("# Other\n", encoding="utf-8")
        git(other, "add", "README.md")
        git(other, "commit", "-m", "initial")

        first = json.loads(
            run_cli(
                self.state,
                {
                    "operation": "stage.start",
                    "stage": "debug",
                    "cwd": str(self.repository),
                },
            ).stdout
        )
        other_run = json.loads(
            run_cli(
                self.state,
                {
                    "operation": "stage.start",
                    "stage": "debug",
                    "cwd": str(other),
                },
            ).stdout
        )
        wrong_repository = run_cli(
            self.state,
            {
                "operation": "stage.complete",
                "stage": "debug",
                "stage_run_id": first["stage_run_id"],
                "cwd": str(other),
            },
        )
        self.assertNotEqual(wrong_repository.returncode, 0)
        self.assertIn("different repository", wrong_repository.stdout)

        completed = run_cli(
            self.state,
            {
                "operation": "stage.complete",
                "stage": "debug",
                "stage_run_id": first["stage_run_id"],
                "cwd": str(self.repository),
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        restarted = json.loads(
            run_cli(
                self.state,
                {
                    "operation": "stage.start",
                    "stage": "debug",
                    "cwd": str(self.repository),
                },
            ).stdout
        )
        other_reused = json.loads(
            run_cli(
                self.state,
                {
                    "operation": "stage.start",
                    "stage": "debug",
                    "cwd": str(other),
                },
            ).stdout
        )
        self.assertNotEqual(restarted["stage_run_id"], first["stage_run_id"])
        self.assertEqual(other_reused["stage_run_id"], other_run["stage_run_id"])

    def test_completed_workflow_is_code_gated_by_verification_and_docs_hook(self):
        self.assertEqual(self.route().returncode, 0)
        premature = run_cli(
            self.state,
            {
                "operation": "workflow.finish",
                "cwd": str(self.repository),
                "status": "completed",
            },
        )
        self.assertNotEqual(premature.returncode, 0)
        self.assertIn("terminal stages", json.loads(premature.stdout)["message"])

        self.assertEqual(self.complete_stage("init").returncode, 0)
        self.assertEqual(self.complete_stage("debug").returncode, 0)
        (self.repository / "tests").mkdir()
        (self.repository / "tests/test_bug.py").write_text("assert True\n", encoding="utf-8")
        self.assertEqual(self.verify().returncode, 0)
        completed = run_cli(
            self.state,
            {
                "operation": "workflow.finish",
                "cwd": str(self.repository),
                "status": "completed",
            },
        )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        trace = json.loads(
            run_cli(self.state, {"operation": "trace.load"}).stdout
        )["trace"]
        self.assertEqual(trace["summary"]["task_result"], "passed")

    def test_completed_workflow_stops_after_docs_without_handoff_decision(self):
        self.assertEqual(self.route().returncode, 0)
        self.assertEqual(self.complete_stage("init").returncode, 0)
        self.assertEqual(self.complete_stage("debug").returncode, 0)
        (self.repository / "docs/overview").mkdir(parents=True)
        (self.repository / "docs/overview/product.md").write_text(
            "# Product\n", encoding="utf-8"
        )

        verified = self.verify()

        self.assertEqual(verified.returncode, 0, verified.stdout)
        report = json.loads(verified.stdout)["docs_hook"]["report"]
        self.assertEqual(report["docsImpact"], "DETERMINISTIC")
        self.assertNotIn("handoffSignal", report)
        self.assertNotIn("askHandoff", report)
        trace = json.loads(
            run_cli(self.state, {"operation": "trace.load"}).stdout
        )["trace"]
        docs_start = next(
            event for event in reversed(trace["events"])
            if event["event_type"] == "workflow.stage.started"
            and event.get("stage") == "sync-docs"
        )
        docs_completed = run_cli(
            self.state,
            {
                "operation": "stage.complete",
                "stage": "sync-docs",
                "stage_run_id": docs_start["correlation"]["stage_run_id"],
                "cwd": str(self.repository),
            },
        )
        self.assertEqual(docs_completed.returncode, 0, docs_completed.stdout)

        completed = run_cli(
            self.state,
            {
                "operation": "workflow.finish",
                "cwd": str(self.repository),
                "status": "completed",
            },
        )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        final_trace = json.loads(
            run_cli(self.state, {"operation": "trace.load"}).stdout
        )["trace"]
        self.assertFalse(
            any(
                event.get("stage") == "handoff"
                or event["event_type"].startswith("handoff.")
                for event in final_trace["events"]
            )
        )

    def test_completed_workflow_rejects_required_stages_recorded_out_of_order(self):
        self.assertEqual(self.route().returncode, 0)
        (self.repository / "tests").mkdir()
        (self.repository / "tests/test_bug.py").write_text(
            "assert True\n", encoding="utf-8"
        )
        self.assertEqual(self.verify().returncode, 0)
        self.assertEqual(self.complete_stage("init").returncode, 0)
        self.assertEqual(self.complete_stage("debug").returncode, 0)

        completed = run_cli(
            self.state,
            {
                "operation": "workflow.finish",
                "cwd": str(self.repository),
                "status": "completed",
            },
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "ordered stage transitions", json.loads(completed.stdout)["message"]
        )

    def test_docs_sync_records_exact_paths_from_automatic_before_after_inventory(self):
        (self.repository / "docs/overview").mkdir(parents=True)
        product = self.repository / "docs/overview/product.md"
        product.write_text("# Product\n", encoding="utf-8")
        requirement = (
            self.repository
            / "docs/superpowers/requirements/2026-08-27-login-requirements.md"
        )
        requirement.parent.mkdir(parents=True)
        requirement.write_text("# Login requirements\n", encoding="utf-8")
        git(
            self.repository,
            "add",
            "docs/overview/product.md",
            "docs/superpowers/requirements/2026-08-27-login-requirements.md",
        )
        git(self.repository, "commit", "-m", "add docs")
        self.baseline = git(self.repository, "rev-parse", "HEAD")
        self.assertEqual(
            self.route(
                intent="development",
                tier="strict",
                route="development",
                change_kind="feature",
            ).returncode,
            0,
        )
        (self.repository / "src").mkdir()
        (self.repository / "src/feature.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.assertEqual(self.verify().returncode, 0)
        trace = json.loads(
            run_cli(self.state, {"operation": "trace.load"}).stdout
        )["trace"]
        sync_run = next(
            event["correlation"]["stage_run_id"]
            for event in trace["events"]
            if event["event_type"] == "workflow.stage.started"
            and event["stage"] == "sync-docs"
        )
        requested = json.loads(
            run_cli(
                self.state,
                {
                    "operation": "approval.request",
                    "stage": "sync-docs",
                    "stage_run_id": sync_run,
                    "approval_kind": "docs.semantic_write",
                    "cwd": str(self.repository),
                },
            ).stdout
        )
        self.assertEqual(
            run_cli(
                self.state,
                {
                    "operation": "approval.resolve",
                    "approval_id": requested["approval_id"],
                    "decision": "approved",
                    "cwd": str(self.repository),
                },
            ).returncode,
            0,
        )
        product.write_text("# Product\n\nImplemented behavior.\n", encoding="utf-8")
        requirement.write_text(
            "# Login requirements\n\nApproved revision.\n", encoding="utf-8"
        )

        completed = run_cli(
            self.state,
            {
                "operation": "stage.complete",
                "stage": "sync-docs",
                "stage_run_id": sync_run,
                "cwd": str(self.repository),
            },
        )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        summary = json.loads(
            run_cli(self.state, {"operation": "trace.load"}).stdout
        )["trace"]["summary"]
        self.assertEqual(
            summary["hook_actual_result"]["appliedChanges"],
            [
                "docs/overview/product.md",
                "docs/superpowers/requirements/2026-08-27-login-requirements.md",
            ],
        )
        self.assertEqual(
            summary["hook_actual_result"]["appliedChangesCount"], 2
        )


if __name__ == "__main__":
    unittest.main()
