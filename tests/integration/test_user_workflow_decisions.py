"""User directions change workflow gates without manufacturing success."""

import json
import unittest
from unittest import mock

from tests.integration import test_runtime_trace_and_docs_hook as fixtures

run_cli = fixtures.run_cli


class UserWorkflowDecisionTests(unittest.TestCase):
    setUp = fixtures.RuntimeTraceAndDocsHookTests.setUp
    tearDown = fixtures.RuntimeTraceAndDocsHookTests.tearDown
    route = fixtures.RuntimeTraceAndDocsHookTests.route
    record_stage_prompt = fixtures.RuntimeTraceAndDocsHookTests.record_stage_prompt
    complete_exact_document_stage = fixtures.RuntimeTraceAndDocsHookTests.complete_exact_document_stage
    document_subject = fixtures.RuntimeTraceAndDocsHookTests.document_subject

    def call(self, operation, **fields):
        result = run_cli(self.state, {"operation": operation, "cwd": str(self.repository), **fields})
        self.assertEqual(0, result.returncode, result.stdout)
        return json.loads(result.stdout)

    def decide(self, stage, action="skip_stage", **fields):
        self.counter = getattr(self, "counter", 0) + 1
        return self.call("workflow.user_decision", stage=stage, action=action,
                         decision_id=f"user-direction-{self.counter}",
                         user_directive={"source": "user", "reference": "current user message",
                                         "summary": "User explicitly chose this exception."}, **fields)

    def test_every_required_stage_can_be_skipped_and_finish_is_truthful(self):
        self.route("development", "standard", "development")
        for stage in ("init", "clarify", "design", "plan", "execute", "verify", "sync-docs"):
            self.decide(stage)
        self.call("workflow.finish", status="completed")
        trace = self.call("trace.load")["trace"]
        self.assertEqual("completed_with_exceptions", trace["summary"]["task_result"])
        self.assertIsNone(trace["summary"]["verification_result"])
        self.assertEqual(7, len(trace["summary"]["user_decisions"]))
        self.assertFalse(any(e["event_type"] == "approval.resolved" for e in trace["events"]))

    def test_waiver_only_removes_its_gate_and_keeps_stage_running(self):
        self.route("development", "standard", "development")
        start = self.call("stage.start", stage="plan")
        run_id = start["stage_run_id"]
        self.decide("plan", "waive_blocker", stage_run_id=run_id, gate="approval",
                    blocker_code="approval.plan.pending")
        subject = self.document_subject("plan_document", "Implement the requested change")
        result = run_cli(self.state, {"operation": "stage.complete", "cwd": str(self.repository),
                                     "stage": "plan", "stage_run_id": run_id, "subject": subject})
        self.assertNotEqual(0, result.returncode)  # Missing source remains a separate gate.
        self.assertIn("source", result.stdout)
        self.decide("plan", "waive_blocker", stage_run_id=run_id, gate="input",
                    blocker_code="input.design.missing")
        self.call("stage.complete", stage="plan", stage_run_id=run_id, subject=subject)
        summary = self.call("trace.load")["trace"]["summary"]
        plan = next(run for run in summary["actual_stages"] if run["stage_run_id"] == run_id)
        self.assertEqual("completed", plan["status"])
        self.assertNotIn("approval_id", plan)
        self.assertEqual(subject["digest"], plan["subject_digest"])

    def test_skipped_design_allows_plan_without_fabricated_design_ref(self):
        self.route("development", "standard", "development")
        self.decide("init")
        self.decide("clarify")
        self.decide("design")
        plan = self.document_subject("plan_document", "A real plan")
        plan_run = self.complete_exact_document_stage("plan", plan)
        execute = self.call("stage.start", stage="execute", source_subject_digest=plan["digest"])
        self.call("stage.complete", stage="execute", stage_run_id=execute["stage_run_id"])
        self.decide("verify")
        self.decide("sync-docs")
        self.call("workflow.finish", status="completed")

    def test_ignoring_failed_verification_keeps_failure_and_counts(self):
        self.route()
        self.decide("init")
        self.decide("debug")
        result = self.call("verification.complete", repository={"path": str(self.repository)},
                           baseline_revision=self.baseline,
                           verification={"result": "fail", "criteria_total": 3, "criteria_passed": 2, "remaining_risks_count": 1,
                                         "candidate_revision": self.baseline})
        self.decide("verify", "waive_blocker", stage_run_id=result["stage_run_id"],
                    gate="verification", blocker_code="verification.failed")
        self.decide("sync-docs")
        self.call("workflow.finish", status="completed")
        summary = self.call("trace.load")["trace"]["summary"]
        self.assertFalse(summary["verification_result"]["passed"])
        self.assertEqual(2, summary["verification_result"]["criteria_passed"])
        self.assertEqual("completed_with_exceptions", summary["task_result"])

    def test_failed_attempt_is_preserved_when_user_continues(self):
        self.route()
        self.decide("init")
        run = self.call("stage.start", stage="debug")["stage_run_id"]
        self.call("stage.fail", stage="debug", stage_run_id=run, error_code="debug.environment")
        self.decide("debug", "waive_blocker", stage_run_id=run, gate="stage_result",
                    blocker_code="debug.environment")
        self.decide("verify")
        self.decide("sync-docs")
        self.call("workflow.finish", status="completed")
        summary = self.call("trace.load")["trace"]["summary"]
        self.assertEqual("failed", next(s for s in summary["actual_stages"] if s["stage_run_id"] == run)["status"])

    def test_skip_retry_is_idempotent_and_new_route_does_not_inherit(self):
        self.route()
        decision = self.decide("debug")
        request = decision["decision"]
        # Response carries only the public, reusable request fields.
        self.call("workflow.user_decision", **request)
        self.assertEqual(1, len(self.call("trace.load")["trace"]["summary"]["user_decisions"]))
        self.route()
        result = run_cli(self.state, {"operation": "workflow.user_decision", "cwd": str(self.repository), **request})
        self.assertNotEqual(0, result.returncode)

    def test_absent_user_evidence_and_cross_repository_run_are_rejected(self):
        self.route()
        run = self.call("stage.start", stage="debug")["stage_run_id"]
        for extra in ({}, {"user_directive": {"source": "assistant", "reference": "plan", "summary": "skip"}}):
            result = run_cli(self.state, {"operation": "workflow.user_decision", "cwd": str(self.repository),
                                         "stage": "debug", "action": "skip_stage", "decision_id": "bad", **extra})
            self.assertNotEqual(0, result.returncode)
        result = run_cli(self.state, {"operation": "workflow.user_decision", "cwd": str(self.repository.parent),
                                     "stage": "debug", "action": "waive_blocker", "stage_run_id": run,
                                     "gate": "method", "blocker_code": "debug.step", "decision_id": "bad-cross-repo",
                                     "user_directive": {"source": "user", "reference": "message", "summary": "continue"}})
        self.assertNotEqual(0, result.returncode)

    def test_skipped_verification_still_allows_real_docs_classification(self):
        self.route()
        for stage in ("init", "debug", "verify"):
            self.decide(stage)
        result = self.call("docs.classify", baseline_revision=self.baseline)
        self.assertEqual("NO_CHANGE", result["docs_hook"]["report"]["docsImpact"])
        self.call("workflow.finish", status="completed")
        self.assertIsNone(self.call("trace.load")["trace"]["summary"]["verification_result"])

    def test_repeated_independent_docs_classification_has_matching_terminals(self):
        self.route()
        for stage in ("init", "debug", "verify"):
            self.decide(stage)
        self.call("docs.classify", baseline_revision=self.baseline)
        self.call("docs.classify", baseline_revision=self.baseline)
        self.call("workflow.finish", status="completed")
        events = self.call("trace.load")["trace"]["events"]
        classified = {e["correlation"]["stage_run_id"] for e in events if e["event_type"] == "docs.impact.classified"}
        skipped = {e["correlation"]["stage_run_id"] for e in events if e["event_type"] == "workflow.stage.skipped"}
        self.assertTrue(classified.issubset(skipped))

    def test_skipped_docs_are_not_restarted_by_verification(self):
        self.route()
        self.decide("init")
        self.decide("debug")
        self.decide("sync-docs")
        result = self.call("verification.complete", repository={"path": str(self.repository)},
                           baseline_revision=self.baseline,
                           verification={"result": "pass", "criteria_total": 1, "criteria_passed": 1,
                                         "remaining_risks_count": 0, "candidate_revision": self.baseline})
        self.assertEqual("user_requested_skip", result["docs_hook"]["reason"])
        self.call("workflow.finish", status="completed")
        docs_runs = [s for s in self.call("trace.load")["trace"]["summary"]["actual_stages"] if s["stage"] == "sync-docs"]
        self.assertEqual(["skipped"], [s["status"] for s in docs_runs])

    def test_input_waiver_before_start_and_new_attempt_does_not_inherit(self):
        self.route("development", "standard", "development")
        first = self.decide("plan", "waive_blocker", gate="input", blocker_code="input.design.missing")
        run = first["stage_run_id"]
        self.assertEqual(run, self.call("stage.start", stage="plan")["stage_run_id"])
        self.decide("plan", "waive_blocker", stage_run_id=run, gate="approval", blocker_code="approval.pending")
        subject = self.document_subject("plan_document", "A new plan")
        self.call("stage.complete", stage="plan", stage_run_id=run, subject=subject)
        second = self.call("stage.start", stage="plan")["stage_run_id"]
        result = run_cli(self.state, {"operation": "stage.complete", "cwd": str(self.repository),
                                     "stage": "plan", "stage_run_id": second, "subject": subject})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("approved", result.stdout.lower())

    def test_active_new_attempt_prevents_finish_using_older_skips(self):
        self.route()
        for stage in ("init", "debug", "verify", "sync-docs"):
            self.decide(stage)
        self.call("stage.start", stage="debug")
        result = run_cli(self.state, {"operation": "workflow.finish", "cwd": str(self.repository), "status": "completed"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("debug", result.stdout)

    def test_method_waiver_does_not_waive_approval(self):
        self.route("development", "standard", "development")
        run = self.call("stage.start", stage="design")["stage_run_id"]
        self.decide("design", "waive_blocker", stage_run_id=run, gate="method", blocker_code="review.unavailable")
        result = run_cli(self.state, {"operation": "stage.complete", "cwd": str(self.repository),
                                     "stage": "design", "stage_run_id": run})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("confirmation", result.stdout)

    def test_missing_docs_classification_can_be_waived_without_losing_observation(self):
        self.route()
        for stage in ("init", "debug", "verify"):
            self.decide(stage)
        run = self.call("stage.start", stage="sync-docs")["stage_run_id"]
        self.decide("sync-docs", "waive_blocker", stage_run_id=run,
                    gate="docs_classification", blocker_code="docs.classification.unavailable")
        self.call("stage.complete", stage="sync-docs", stage_run_id=run)
        self.call("workflow.finish", status="completed")
        self.assertTrue(self.call("trace.load")["trace"]["summary"]["hook_actual_result"]["fullCapture"])

    def test_skipping_upstream_after_downstream_started_unblocks_its_input(self):
        self.route("development", "standard", "development")
        run = self.call("stage.start", stage="plan")["stage_run_id"]
        self.decide("design")
        self.decide("plan", "waive_blocker", stage_run_id=run, gate="approval", blocker_code="approval.pending")
        self.call("stage.complete", stage="plan", stage_run_id=run,
                  subject=self.document_subject("plan_document", "Plan using the user's request"))

    def test_skipped_upstream_does_not_require_an_older_exact_document(self):
        self.route("development", "standard", "development")
        self.complete_exact_document_stage("design", self.document_subject("design_document", "An older design"))
        self.decide("design")
        self.complete_exact_document_stage("plan", self.document_subject("plan_document", "Replacement plan"))

    def test_failed_skip_write_can_be_retried_without_duplicate_decision(self):
        self.route()
        request = {"schema_version": fixtures.SCHEMA_VERSION, "operation": "workflow.user_decision",
                   "cwd": str(self.repository), "decision_id": "retry-partial", "stage": "debug",
                   "action": "skip_stage", "user_directive": {"source": "user", "reference": "message", "summary": "Skip debug."}}
        with mock.patch.dict(fixtures.os.environ, {"AI_NATIVE_DEVKIT_STATE_ROOT": str(self.state), "CODEX_THREAD_ID": "session-runtime-01"}), \
                mock.patch.object(fixtures.runtime_cli, "_read_request", return_value=request), \
                mock.patch.object(fixtures.runtime_cli, "_skip_stage", side_effect=OSError("interrupted write")):
            with self.assertRaises(OSError):
                fixtures.runtime_cli.run()
        self.call("workflow.user_decision", **{k: v for k, v in request.items() if k not in {"operation", "schema_version", "cwd"}})
        summary = self.call("trace.load")["trace"]["summary"]
        self.assertEqual(1, len(summary["user_decisions"]))
        self.assertEqual(["skipped"], [s["status"] for s in summary["actual_stages"] if s["stage"] == "debug"])

    def test_user_can_continue_a_workflow_previously_marked_failed(self):
        self.route()
        self.decide("init")
        run = self.call("stage.start", stage="debug")["stage_run_id"]
        self.call("stage.fail", stage="debug", stage_run_id=run, error_code="debug.environment")
        self.call("workflow.finish", status="failed", failure={"failure_type": "environment", "failure_stage": "debug", "error_code": "debug.environment"})
        self.decide("debug", "waive_blocker", stage_run_id=run, gate="stage_result", blocker_code="debug.environment")
        trace = self.call("trace.load")["trace"]
        self.assertEqual("active", trace["metadata"]["capture_status"])
        self.assertEqual("incomplete", trace["summary"]["task_result"])
        self.decide("verify")
        self.call("docs.classify", baseline_revision=self.baseline)
        self.call("workflow.finish", status="completed")
        trace = self.call("trace.load")["trace"]
        self.assertEqual("completed_with_exceptions", trace["summary"]["task_result"])
        self.assertTrue(any(e["event_type"] == "workflow.failed" for e in trace["events"]))


if __name__ == "__main__":
    unittest.main()
