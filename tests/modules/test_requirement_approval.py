import sys
from pathlib import Path
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit.contracts import RequirementDocRef
from ai_native_devkit.errors import RequirementApprovalError
from ai_native_devkit.execution_trace import ExecutionTraceStore, repository_digest
from ai_native_devkit.requirement_approval import RequirementApprovalGate


def emit_attempt(
    store, *, session_id, repository_root, reference, decision="approved",
    terminal=True, request_turn="turn-1", resolution_turn="turn-2",
    include_later_prompt=True, stop_later_turn=False, hour=1,
    repository_override=None, request_prompt_source="codex_hook",
    duplicate_request_prompt=False, later_prompt_source="codex_hook",
    duplicate_later_prompt=False, newer_later_turn=None,
    stop_newer_later_turn=False, duplicate_resolution=False,
    include_start_repository=True, include_terminal_repository=False,
):
    run_id = "clarify-run-" + session_id
    approval_id = "approval-" + session_id
    subject = reference.subject_digest()
    repository = repository_override or repository_digest(str(repository_root))
    append = store.append
    start_payload = {"stage": "clarify"}
    if include_start_repository:
        start_payload["repository"] = repository
    append(
        session_id=session_id, event_type="workflow.stage.started",
        actor="runtime", source="devkit_runtime", stage="clarify",
        correlation={"stage_run_id": run_id},
        payload=start_payload,
        context={"cwd": str(repository_root)},
        timestamp=f"2026-08-27T{hour:02d}:00:00.000Z",
    )
    if request_turn is not None:
        append(
            session_id=session_id, event_type="turn.prompt_submitted",
            actor="user", source=request_prompt_source, stage="clarify",
            correlation={"turn_id": request_turn}, payload={},
            timestamp=f"2026-08-27T{hour:02d}:01:00.000Z",
        )
        if duplicate_request_prompt:
            append(
                session_id=session_id, event_type="turn.prompt_submitted",
                actor="user", source=request_prompt_source, stage="clarify",
                correlation={"turn_id": request_turn}, payload={},
                timestamp=f"2026-08-27T{hour:02d}:01:30.000Z",
            )
    append(
        session_id=session_id, event_type="approval.requested",
        actor="runtime", source="devkit_runtime", stage="clarify",
        correlation={
            "stage_run_id": run_id,
            **({"turn_id": request_turn} if request_turn is not None else {}),
        },
        payload={
            "approval_id": approval_id,
            "approval_kind": "clarify.requirements",
            "subject_kind": "requirement_document",
            "subject_digest": subject,
        },
        timestamp=f"2026-08-27T{hour:02d}:02:00.000Z",
    )
    if decision is None:
        return
    if include_later_prompt and resolution_turn is not None:
        append(
            session_id=session_id, event_type="turn.prompt_submitted",
            actor="user", source=later_prompt_source, stage="clarify",
            correlation={"turn_id": resolution_turn}, payload={},
            timestamp=f"2026-08-27T{hour:02d}:03:00.000Z",
        )
        if duplicate_later_prompt:
            append(
                session_id=session_id, event_type="turn.prompt_submitted",
                actor="user", source=later_prompt_source, stage="clarify",
                correlation={"turn_id": resolution_turn}, payload={},
                timestamp=f"2026-08-27T{hour:02d}:03:10.000Z",
            )
        if stop_later_turn:
            append(
                session_id=session_id, event_type="turn.stopped",
                actor="agent", source="codex_hook", stage="clarify",
                correlation={"turn_id": resolution_turn}, payload={},
                timestamp=f"2026-08-27T{hour:02d}:03:30.000Z",
            )
    if newer_later_turn is not None:
        append(
            session_id=session_id, event_type="turn.prompt_submitted",
            actor="user", source="codex_hook", stage="clarify",
            correlation={"turn_id": newer_later_turn}, payload={},
            timestamp=f"2026-08-27T{hour:02d}:03:20.000Z",
        )
        if stop_newer_later_turn:
            append(
                session_id=session_id, event_type="turn.stopped",
                actor="agent", source="codex_hook", stage="clarify",
                correlation={"turn_id": newer_later_turn}, payload={},
                timestamp=f"2026-08-27T{hour:02d}:03:30.000Z",
            )
    append(
        session_id=session_id, event_type="approval.resolved",
        actor="runtime", source="devkit_runtime", stage="clarify",
        correlation={
            "stage_run_id": run_id,
            **({"turn_id": resolution_turn} if resolution_turn is not None else {}),
        },
        payload={
            "approval_id": approval_id,
            "approval_kind": "clarify.requirements",
            "subject_kind": "requirement_document",
            "subject_digest": subject,
            "decision": decision,
        },
        timestamp=f"2026-08-27T{hour:02d}:04:00.000Z",
    )
    if duplicate_resolution:
        append(
            session_id=session_id, event_type="approval.resolved",
            actor="runtime", source="devkit_runtime", stage="clarify",
            correlation={"stage_run_id": run_id, "turn_id": resolution_turn},
            payload={
                "approval_id": approval_id,
                "approval_kind": "clarify.requirements",
                "subject_kind": "requirement_document",
                "subject_digest": subject,
                "decision": decision,
            },
            timestamp=f"2026-08-27T{hour:02d}:04:30.000Z",
        )
    if terminal:
        terminal_payload = {
            "stage": "clarify", "approval_id": approval_id,
            "subject_kind": "requirement_document",
            "subject_digest": subject,
        }
        if include_terminal_repository:
            terminal_payload["repository"] = repository
        append(
            session_id=session_id, event_type="workflow.stage.completed",
            actor="runtime", source="devkit_runtime", stage="clarify",
            correlation={
                "stage_run_id": run_id,
                **({"turn_id": resolution_turn} if resolution_turn is not None else {}),
            },
            payload=terminal_payload,
            timestamp=f"2026-08-27T{hour:02d}:05:00.000Z",
        )


class RequirementApprovalGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()
        self.store = ExecutionTraceStore(Path(self.temporary.name) / "traces")
        self.reference = RequirementDocRef.from_dict({
            "path": "docs/superpowers/requirements/2026-08-27-login-requirements.md",
            "commit": "a" * 40,
            "blob_digest": "git-sha1:" + "b" * 40,
        })

    def tearDown(self):
        self.temporary.cleanup()

    def assert_not_approved(self):
        with self.assertRaises(RequirementApprovalError):
            RequirementApprovalGate().require_approved(
                trace_store=self.store,
                repository_root=self.repository,
                reference=self.reference,
            )

    def test_exact_approval_is_reusable_from_another_session(self):
        emit_attempt(
            self.store, session_id="original-session",
            repository_root=self.repository, reference=self.reference,
        )
        evidence = RequirementApprovalGate().require_approved(
            trace_store=self.store, repository_root=self.repository,
            reference=self.reference,
        )
        self.assertEqual(evidence.approval_id, "approval-original-session")

    def test_attempt_repository_comes_from_exact_stage_start_not_trace_metadata(self):
        original_repository = Path(self.temporary.name) / "original-repository"
        original_repository.mkdir()
        session_id = "cross-repository-session"
        self.store.append(
            session_id=session_id, event_type="session.started",
            actor="system", source="codex_hook", payload={},
            context={"cwd": str(original_repository)},
            timestamp="2026-08-27T00:00:00.000Z",
        )
        emit_attempt(
            self.store, session_id=session_id,
            repository_root=self.repository, reference=self.reference,
            include_terminal_repository=True,
        )

        record = self.store.load_session(session_id)
        self.assertEqual(
            record["metadata"]["repository"],
            repository_digest(str(original_repository)),
        )
        stage_events = [
            event for event in record["events"]
            if event["event_type"] in {
                "workflow.stage.started", "workflow.stage.completed"
            }
        ]
        self.assertEqual(
            {
                event["payload"].get("repository")
                for event in stage_events
            },
            {repository_digest(str(self.repository))},
        )
        attempt = RequirementApprovalGate.project([record])[0]
        self.assertEqual(
            attempt.repository_digest, repository_digest(str(self.repository))
        )
        self.assertTrue(attempt.later_user_turn)
        self.assertTrue(attempt.terminal)
        approved = RequirementApprovalGate().require_approved(
            trace_store=self.store,
            repository_root=self.repository,
            reference=self.reference,
        )
        self.assertEqual(approved.approval_id, "approval-cross-repository-session")

    def test_stage_start_repository_must_match_lookup_and_be_present(self):
        other_repository = Path(self.temporary.name) / "other-repository"
        other_repository.mkdir()
        cases = (
            {
                "session_id": "mismatched-start-repository",
                "repository_override": repository_digest(str(other_repository)),
            },
            {
                "session_id": "missing-start-repository",
                "include_start_repository": False,
            },
        )
        for case in cases:
            with self.subTest(case=case["session_id"]):
                emit_attempt(
                    self.store, repository_root=self.repository,
                    reference=self.reference, **case,
                )
                self.assert_not_approved()

    def test_missing_request_turn_is_not_approval(self):
        emit_attempt(
            self.store, session_id="missing-turn",
            repository_root=self.repository, reference=self.reference,
            request_turn=None,
        )
        self.assert_not_approved()

    def test_same_turn_or_missing_later_prompt_is_not_approval(self):
        for session_id, resolution_turn, include_prompt in (
            ("same-turn", "turn-1", False),
            ("missing-prompt", "turn-2", False),
        ):
            with self.subTest(session_id=session_id):
                emit_attempt(
                    self.store, session_id=session_id,
                    repository_root=self.repository,
                    reference=self.reference, resolution_turn=resolution_turn,
                    include_later_prompt=include_prompt,
                )
                self.assert_not_approved()

    def test_stopped_later_turn_is_not_persisted_approval_evidence(self):
        emit_attempt(
            self.store, session_id="stopped-turn",
            repository_root=self.repository, reference=self.reference,
            stop_later_turn=True,
        )
        attempts = RequirementApprovalGate.project(
            list(self.store.iter_records())
        )
        stopped = next(
            attempt for attempt in attempts
            if attempt.approval_id == "approval-stopped-turn"
        )
        self.assertFalse(stopped.later_user_turn)
        self.assertFalse(stopped.terminal)
        self.assert_not_approved()

    def test_latest_stopped_turn_does_not_fall_back_to_earlier_prompt(self):
        emit_attempt(
            self.store, session_id="latest-stopped",
            repository_root=self.repository, reference=self.reference,
            newer_later_turn="turn-3", stop_newer_later_turn=True,
        )
        self.assert_not_approved()

    def test_duplicate_selected_later_prompt_is_not_approval(self):
        emit_attempt(
            self.store, session_id="duplicate-later-prompt",
            repository_root=self.repository, reference=self.reference,
            duplicate_later_prompt=True,
        )
        self.assert_not_approved()

    def test_rejected_changed_or_incomplete_attempt_is_not_approval(self):
        for hour, decision, terminal in (
            (1, "rejected", True), (2, "changes_requested", True),
            (3, "approved", False),
        ):
            emit_attempt(
                self.store, session_id=f"attempt-{hour}", hour=hour,
                repository_root=self.repository, reference=self.reference,
                decision=decision, terminal=terminal,
            )
            self.assert_not_approved()

    def test_pending_attempt_alone_is_not_approval(self):
        emit_attempt(
            self.store, session_id="pending",
            repository_root=self.repository, reference=self.reference,
            decision=None,
        )
        self.assert_not_approved()

    def test_approval_from_another_repository_is_not_reused(self):
        foreign = Path(self.temporary.name) / "foreign-repository"
        foreign.mkdir()
        emit_attempt(
            self.store, session_id="foreign", repository_root=foreign,
            reference=self.reference,
        )
        self.assert_not_approved()

    def test_terminal_must_match_the_exact_approval_tuple(self):
        emit_attempt(
            self.store, session_id="mismatched-terminal",
            repository_root=self.repository, reference=self.reference,
            terminal=False,
        )
        self.store.append(
            session_id="mismatched-terminal",
            event_type="workflow.stage.completed", actor="runtime",
            source="devkit_runtime", stage="clarify",
            correlation={"stage_run_id": "clarify-run-mismatched-terminal"},
            payload={
                "stage": "clarify", "approval_id": "approval-other",
                "subject_kind": "requirement_document",
                "subject_digest": self.reference.subject_digest(),
            },
            timestamp="2026-08-27T01:05:00.000Z",
        )
        self.assert_not_approved()

    def test_preterminal_resolution_is_valid_for_stage_completion_only(self):
        emit_attempt(
            self.store, session_id="preterminal",
            repository_root=self.repository, reference=self.reference,
            terminal=False,
        )
        attempt = RequirementApprovalGate.project(
            list(self.store.iter_records())
        )[-1]
        self.assertEqual(attempt.decision, "approved")
        self.assertTrue(attempt.later_user_turn)
        self.assertFalse(attempt.terminal)
        self.assert_not_approved()

    def test_untrusted_or_ambiguous_turn_evidence_is_not_approval(self):
        cases = (
            {
                "session_id": "wrong-request-source",
                "request_prompt_source": "codex_transcript_fallback",
            },
            {
                "session_id": "duplicate-request-prompt",
                "duplicate_request_prompt": True,
            },
            {
                "session_id": "wrong-later-source",
                "later_prompt_source": "codex_transcript_fallback",
            },
            {"session_id": "duplicate-resolution", "duplicate_resolution": True},
        )
        for case in cases:
            with self.subTest(case=case["session_id"]):
                emit_attempt(
                    self.store, repository_root=self.repository,
                    reference=self.reference, **case,
                )
                self.assert_not_approved()
