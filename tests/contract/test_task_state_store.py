import sys
from pathlib import Path
import copy
import hashlib
import json
import tempfile
import threading
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = (
    PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
)
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit.contracts import (
    ArtifactDraft,
    ArtifactRef,
    LocalRef,
    TaskCommit,
    TransitionIntent,
    reference_for,
)
from ai_native_devkit.errors import ContractError, StoreError
from ai_native_devkit.persistence import (
    FilesystemAtomicPersistence,
    InMemoryAtomicPersistence,
)
from ai_native_devkit.init_engine import InitEngine
from ai_native_devkit.repository import RepositoryClassification
from ai_native_devkit.state_store import ALLOWED_TRANSITIONS, MISSING, TaskStateStore


def valid_task_request_payload():
    return {
        "intent": "init",
        "user_request": "/init",
        "repository": {
            "requested_path": "/tmp/example-repository",
            "observed_root": "/tmp/example-repository",
            "requested_scope": None,
            "expected_revision": None,
        },
        "constraints": {
            "scope": None,
            "permissions": [],
            "destructive_actions": "denied",
        },
        "attachments": [],
    }


def creation_commit(task_id, operation_id="create-task"):
    return TaskCommit(
        task_id=task_id,
        expected_store_version=None,
        operation_id=operation_id,
        artifact_drafts=[
            ArtifactDraft(
                local_ref="request",
                artifact_type="task_request",
                payload=valid_task_request_payload(),
            )
        ],
        transition_intent=None,
    )


def valid_evidence_payload(artifact_refs=None, summary="fixture"):
    return {
        "kind": "inspection",
        "invocation": "fixture inspection",
        "observed_revision": None,
        "started_at": "2026-08-24T00:00:00.000Z",
        "duration_ms": 1,
        "exit_status": "pass",
        "summary": summary,
        "artifact_refs": list(artifact_refs or []),
        "authority_grant": None,
    }


def valid_authority_payload(capabilities=None, scopes=None):
    return {
        "kind": "authority",
        "invocation": "fixture authority grant",
        "observed_revision": None,
        "started_at": "2026-08-24T00:00:00.000Z",
        "duration_ms": 0,
        "exit_status": "pass",
        "summary": "The user granted bounded authority.",
        "artifact_refs": [],
        "authority_grant": {
            "granted_by": "user",
            "capabilities": list(capabilities or ["production.write"]),
            "scopes": list(scopes or ["environment:production"]),
            "confirmed_at": "2026-08-24T00:00:00.000Z",
            "provenance": "fixture:user-turn-1",
        },
    }


class TaskStateStoreTests(unittest.TestCase):
    def test_removed_clarified_transition_is_not_allowed(self):
        self.assertNotIn(("ContextReady", "Clarified"), ALLOWED_TRANSITIONS)

    def test_clarification_approval_evidence_kind_is_no_longer_registered(self):
        store = TaskStateStore(InMemoryAtomicPersistence())
        task_id = "removed-approval-evidence"
        store.commit(creation_commit(task_id))
        before = store.load(task_id)
        payload = valid_evidence_payload()
        payload["kind"] = "approval"

        with self.assertRaises(ContractError):
            store.commit(
                TaskCommit(
                    task_id=task_id,
                    expected_store_version=before.store_version,
                    operation_id="removed-approval-evidence",
                    artifact_drafts=[ArtifactDraft("evidence", "evidence_record", payload)],
                    transition_intent=None,
                )
            )

        self.assertEqual(store.load(task_id), before)

    def test_authority_contract_is_generic_but_requires_stable_unique_bounds(self):
        store = TaskStateStore(InMemoryAtomicPersistence())
        task_id = "generic-authority-task"
        store.commit(creation_commit(task_id))
        before = store.load(task_id)
        receipt = store.commit(
            TaskCommit(
                task_id=task_id,
                expected_store_version=before.store_version,
                operation_id="record-production-authority",
                artifact_drafts=[
                    ArtifactDraft(
                        "authority",
                        "evidence_record",
                        valid_authority_payload(),
                    )
                ],
                transition_intent=None,
            )
        )
        authority_ref = receipt.materialized_refs["authority"]
        persisted = next(
            artifact
            for artifact in store.load(task_id).artifacts
            if artifact["artifact_id"] == authority_ref.artifact_id
        )
        self.assertEqual(
            persisted["payload"]["authority_grant"]["capabilities"],
            ["production.write"],
        )

        invalid_bounds = [
            ("duplicate-capability", ["production.write", "production.write"], ["environment:production"]),
            ("invalid-capability", ["Production Write"], ["environment:production"]),
            ("duplicate-scope", ["production.write"], ["environment:production", "environment:production"]),
            ("noncanonical-repository-scope", ["repository.read"], ["repository:v1:Sub%20Directory/%e4%b8%ad"]),
        ]
        for name, capabilities, scopes in invalid_bounds:
            with self.subTest(name=name):
                current = store.load(task_id)
                with self.assertRaises(ContractError):
                    store.commit(
                        TaskCommit(
                            task_id=task_id,
                            expected_store_version=current.store_version,
                            operation_id="reject-authority-" + name,
                            artifact_drafts=[
                                ArtifactDraft(
                                    "authority",
                                    "evidence_record",
                                    valid_authority_payload(capabilities, scopes),
                                )
                            ],
                            transition_intent=None,
                        )
                    )
                self.assertEqual(store.load(task_id), current)

    def test_creation_establishes_intake_without_fabricating_transition(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            stores = [
                TaskStateStore(InMemoryAtomicPersistence()),
                TaskStateStore(
                    FilesystemAtomicPersistence(Path(temporary_directory) / "state")
                ),
            ]
            for index, store in enumerate(stores):
                task_id = "creation-task-" + str(index)

                with self.subTest(adapter=index):
                    self.assertIs(store.load(task_id), MISSING)
                    receipt = store.commit(creation_commit(task_id))
                    snapshot = store.load(task_id)
                    self.assertEqual(snapshot.store_version, receipt.store_version)
                    self.assertEqual(snapshot.lifecycle_state, "Intake")
                    self.assertIsNone(snapshot.resume_state)
                    self.assertIsNone(snapshot.latest_report_ref)
                    self.assertEqual(len(snapshot.artifacts), 1)
                    self.assertEqual(
                        snapshot.artifacts[0]["artifact_type"], "task_request"
                    )
                    self.assertIsNone(snapshot.artifacts[0]["repo_revision"])

    def test_same_operation_is_idempotent_across_both_adapters(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            stores = [
                TaskStateStore(InMemoryAtomicPersistence()),
                TaskStateStore(
                    FilesystemAtomicPersistence(Path(temporary_directory) / "state")
                ),
            ]
            for index, store in enumerate(stores):
                task_id = "idempotent-task-" + str(index)
                commit = creation_commit(task_id)

                with self.subTest(adapter=index):
                    first_receipt = store.commit(commit)
                    first_snapshot = store.load(task_id)
                    second_receipt = store.commit(commit)
                    second_snapshot = store.load(task_id)
                    self.assertEqual(first_receipt, second_receipt)
                    self.assertEqual(first_snapshot, second_snapshot)

    def test_same_operation_with_different_content_is_rejected_atomically(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            stores = [
                TaskStateStore(InMemoryAtomicPersistence()),
                TaskStateStore(
                    FilesystemAtomicPersistence(Path(temporary_directory) / "state")
                ),
            ]
            for index, store in enumerate(stores):
                task_id = "idempotency-conflict-task-" + str(index)
                store.commit(creation_commit(task_id))
                before = store.load(task_id)
                changed_payload = valid_task_request_payload()
                changed_payload["user_request"] = "/init with different content"
                conflicting_commit = TaskCommit(
                    task_id=task_id,
                    expected_store_version=None,
                    operation_id="create-task",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="request",
                            artifact_type="task_request",
                            payload=changed_payload,
                        )
                    ],
                    transition_intent=None,
                )

                with self.subTest(adapter=index):
                    with self.assertRaises(StoreError) as raised:
                        store.commit(conflicting_commit)
                    self.assertEqual(
                        raised.exception.code, "rejected.idempotency_conflict"
                    )
                    self.assertEqual(store.load(task_id), before)

    def test_stale_expected_version_from_different_operation_is_rejected_atomically(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            stores = [
                TaskStateStore(InMemoryAtomicPersistence()),
                TaskStateStore(
                    FilesystemAtomicPersistence(Path(temporary_directory) / "state")
                ),
            ]
            for index, store in enumerate(stores):
                task_id = "stale-version-task-" + str(index)
                store.commit(creation_commit(task_id))
                stale = store.load(task_id)
                store.commit(
                    TaskCommit(
                        task_id=task_id,
                        expected_store_version=stale.store_version,
                        operation_id="winning-evidence",
                        artifact_drafts=[
                            ArtifactDraft(
                                local_ref="evidence",
                                artifact_type="evidence_record",
                                payload=valid_evidence_payload(summary="winner"),
                            )
                        ],
                        transition_intent=None,
                    )
                )
                before_rejected_commit = store.load(task_id)
                stale_commit = TaskCommit(
                    task_id=task_id,
                    expected_store_version=stale.store_version,
                    operation_id="stale-evidence",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="evidence",
                            artifact_type="evidence_record",
                            payload=valid_evidence_payload(summary="stale"),
                        )
                    ],
                    transition_intent=None,
                )

                with self.subTest(adapter=index):
                    with self.assertRaises(StoreError) as raised:
                        store.commit(stale_commit)
                    self.assertEqual(
                        raised.exception.code, "rejected.concurrent_update"
                    )
                    self.assertEqual(store.load(task_id), before_rejected_commit)

    def test_invalid_existing_artifact_references_are_rejected_atomically(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            stores = [
                TaskStateStore(InMemoryAtomicPersistence()),
                TaskStateStore(
                    FilesystemAtomicPersistence(Path(temporary_directory) / "state")
                ),
            ]
            for index, store in enumerate(stores):
                task_id = "invalid-reference-task-" + str(index)
                other_task_id = "reference-source-task-" + str(index)
                creation = store.commit(creation_commit(task_id))
                other_creation = store.commit(
                    creation_commit(other_task_id, operation_id="create-other-task")
                )
                before = store.load(task_id)
                request_ref = creation.materialized_refs["request"]
                wrong_digest = "sha256:" + (
                    "0" * 64
                    if request_ref.digest != "sha256:" + "0" * 64
                    else "1" * 64
                )
                invalid_references = {
                    "dangling": ArtifactRef(
                        "00000000-0000-4000-8000-000000000001",
                        "task_request",
                        "sha256:" + "2" * 64,
                    ),
                    "wrong-digest": ArtifactRef(
                        request_ref.artifact_id,
                        request_ref.artifact_type,
                        wrong_digest,
                    ),
                    "cross-task": other_creation.materialized_refs["request"],
                }

                for case, invalid_reference in invalid_references.items():
                    invalid_commit = TaskCommit(
                        task_id=task_id,
                        expected_store_version=before.store_version,
                        operation_id="invalid-reference-" + case,
                        artifact_drafts=[
                            ArtifactDraft(
                                local_ref="evidence",
                                artifact_type="evidence_record",
                                payload=valid_evidence_payload([invalid_reference]),
                            )
                        ],
                        transition_intent=None,
                    )

                    with self.subTest(adapter=index, case=case):
                        with self.assertRaises(ContractError):
                            store.commit(invalid_commit)
                        self.assertEqual(store.load(task_id), before)

    def test_invalid_report_rejects_entire_ready_batch(self):
        revision = {
            "head_state": "attached",
            "head": "a" * 40,
            "branch": "main",
            "dirty": False,
            "worktree_digest": None,
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            stores = [
                TaskStateStore(InMemoryAtomicPersistence()),
                TaskStateStore(
                    FilesystemAtomicPersistence(Path(temporary_directory) / "state")
                ),
            ]
            for index, store in enumerate(stores):
                task_id = "invalid-ready-batch-" + str(index)
                creation = store.commit(creation_commit(task_id))
                before = store.load(task_id)
                request_ref = creation.materialized_refs["request"]
                commit = TaskCommit(
                    task_id=task_id,
                    expected_store_version=before.store_version,
                    operation_id="invalid-ready",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="evidence",
                            artifact_type="evidence_record",
                            payload={
                                "kind": "inspection",
                                "invocation": "fixture inspection",
                                "observed_revision": revision,
                                "started_at": "2026-08-24T00:00:00.000Z",
                                "duration_ms": 1,
                                "exit_status": "pass",
                                "summary": "fixture",
                                "artifact_refs": [],
                                "authority_grant": None,
                            },
                        ),
                        ArtifactDraft(
                            local_ref="report",
                            artifact_type="init_report",
                            payload={
                                "repository": {
                                    "requested_path": "/tmp/example-repository",
                                    "root": "/tmp/example-repository",
                                    "requested_scope": None,
                                    "revision": revision,
                                    "superproject": None,
                                },
                                "sources": [],
                                "findings": {
                                    "entry_docs": [],
                                    "repository_instructions": [],
                                    "verification_commands": [],
                                },
                                "gaps": [],
                                "outcome": "ready",
                                "blocker": {
                                    "code": "blocked.should_not_exist",
                                    "message": "invalid",
                                    "resume_when": "invalid",
                                },
                                "artifact_refs": {
                                    "task_request": request_ref,
                                    "transition": LocalRef("transition"),
                                    "evidence": [LocalRef("evidence")],
                                },
                                "supersedes": None,
                            },
                        ),
                    ],
                    transition_intent=TransitionIntent(
                        local_ref="transition",
                        to_state="ContextReady",
                        reason="fixture-ready",
                        input_refs=[request_ref, LocalRef("evidence")],
                        output_ref=None,
                        actor="stage module",
                    ),
                )

                with self.subTest(adapter=index):
                    with self.assertRaises(ContractError):
                        store.commit(commit)
                    self.assertEqual(store.load(task_id), before)

    def test_invalid_evidence_rejects_commit_without_changing_task(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            stores = [
                TaskStateStore(InMemoryAtomicPersistence()),
                TaskStateStore(
                    FilesystemAtomicPersistence(Path(temporary_directory) / "state")
                ),
            ]
            for index, store in enumerate(stores):
                task_id = "invalid-evidence-" + str(index)
                store.commit(creation_commit(task_id))
                before = store.load(task_id)
                invalid_commit = TaskCommit(
                    task_id=task_id,
                    expected_store_version=before.store_version,
                    operation_id="invalid-evidence",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="evidence",
                            artifact_type="evidence_record",
                            payload={
                                "kind": "inspection",
                                "invocation": "fixture inspection",
                                "observed_revision": None,
                                "started_at": "2026-08-24T00:00:00.000Z",
                                "duration_ms": -1,
                                "exit_status": "pass",
                                "summary": "fixture",
                                "artifact_refs": [],
                                "authority_grant": None,
                            },
                        )
                    ],
                    transition_intent=None,
                )

                with self.subTest(adapter=index):
                    with self.assertRaises(ContractError):
                        store.commit(invalid_commit)
                    self.assertEqual(store.load(task_id), before)

    def test_context_ready_transition_requires_report_in_same_atomic_batch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            stores = [
                TaskStateStore(InMemoryAtomicPersistence()),
                TaskStateStore(
                    FilesystemAtomicPersistence(Path(temporary_directory) / "state")
                ),
            ]
            for index, store in enumerate(stores):
                task_id = "transition-without-report-" + str(index)
                creation = store.commit(creation_commit(task_id))
                before = store.load(task_id)
                invalid_commit = TaskCommit(
                    task_id=task_id,
                    expected_store_version=before.store_version,
                    operation_id="transition-without-report",
                    artifact_drafts=[],
                    transition_intent=TransitionIntent(
                        local_ref="transition",
                        to_state="ContextReady",
                        reason="invalid-ready",
                        input_refs=[creation.materialized_refs["request"]],
                        output_ref=None,
                        actor="stage module",
                    ),
                )

                with self.subTest(adapter=index):
                    with self.assertRaises(ContractError):
                        store.commit(invalid_commit)
                    self.assertEqual(store.load(task_id), before)

    def test_concurrent_same_operation_returns_one_shared_receipt(self):
        class CoordinatedPersistence:
            def __init__(self, delegate):
                self.delegate = delegate
                self.barrier = threading.Barrier(2)

            def load_bytes(self, task_id):
                return self.delegate.load_bytes(task_id)

            def compare_and_commit(self, task_id, expected, replacement):
                self.barrier.wait(timeout=5)
                return self.delegate.compare_and_commit(
                    task_id, expected, replacement
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            backends = [
                InMemoryAtomicPersistence(),
                FilesystemAtomicPersistence(Path(temporary_directory) / "state"),
            ]
            for index, backend in enumerate(backends):
                coordinated = CoordinatedPersistence(backend)
                stores = [TaskStateStore(coordinated), TaskStateStore(coordinated)]
                task_id = "concurrent-same-operation-" + str(index)
                commit = creation_commit(task_id)
                receipts = []
                errors = []

                def worker(store):
                    try:
                        receipts.append(store.commit(commit))
                    except Exception as error:
                        errors.append(error)

                threads = [
                    threading.Thread(target=worker, args=(store,)) for store in stores
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)

                with self.subTest(adapter=index):
                    self.assertEqual(errors, [])
                    self.assertEqual(len(receipts), 2)
                    self.assertEqual(receipts[0], receipts[1])
                    snapshot = stores[0].load(task_id)
                    self.assertEqual(len(snapshot.artifacts), 1)

    def test_ambiguous_persistence_result_recovers_committed_receipt(self):
        class CommitThenFailPersistence:
            def __init__(self):
                self.delegate = InMemoryAtomicPersistence()

            def load_bytes(self, task_id):
                return self.delegate.load_bytes(task_id)

            def compare_and_commit(self, task_id, expected, replacement):
                self.delegate.compare_and_commit(task_id, expected, replacement)
                raise OSError("simulated lost acknowledgement")

        store = TaskStateStore(CommitThenFailPersistence())
        task_id = "ambiguous-persistence"

        receipt = store.commit(creation_commit(task_id))

        snapshot = store.load(task_id)
        self.assertEqual(snapshot.store_version, receipt.store_version)
        self.assertEqual(snapshot.lifecycle_state, "Intake")
        self.assertEqual(len(snapshot.artifacts), 1)

    def test_secrets_are_redacted_before_reaching_filesystem_persistence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            store = TaskStateStore(FilesystemAtomicPersistence(state_root))
            task_id = "redacted-task"
            payload = valid_task_request_payload()
            payload["user_request"] = (
                "Use token=top-secret-123 and Bearer abcdefghijklmnop for this task"
            )
            commit = TaskCommit(
                task_id=task_id,
                expected_store_version=None,
                operation_id="create-redacted-task",
                artifact_drafts=[
                    ArtifactDraft(
                        local_ref="request",
                        artifact_type="task_request",
                        payload=payload,
                    )
                ],
                transition_intent=None,
            )

            store.commit(commit)

            snapshot = store.load(task_id)
            persisted_request = snapshot.artifacts[0]["payload"]["user_request"]
            self.assertEqual(
                persisted_request,
                "Use token=[REDACTED] and Bearer [REDACTED] for this task",
            )
            persisted_bytes = b"".join(
                path.read_bytes() for path in state_root.rglob("*") if path.is_file()
            )
            self.assertNotIn(b"top-secret-123", persisted_bytes)
            self.assertNotIn(b"abcdefghijklmnop", persisted_bytes)

    def test_values_under_explicit_secret_keys_are_redacted_before_persistence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            store = TaskStateStore(FilesystemAtomicPersistence(state_root))
            payload = valid_task_request_payload()
            payload["attachments"] = [
                {
                    "access_token": "plain-access-value",
                    "password": "plain-password-value",
                    "clientSecret": {"nested": "plain-client-value"},
                }
            ]

            store.commit(
                TaskCommit(
                    task_id="redacted-key-task",
                    expected_store_version=None,
                    operation_id="create-redacted-key-task",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="request",
                            artifact_type="task_request",
                            payload=payload,
                        )
                    ],
                    transition_intent=None,
                )
            )

            attachment = store.load("redacted-key-task").artifacts[0]["payload"][
                "attachments"
            ][0]
            self.assertEqual(attachment["access_token"], "[REDACTED]")
            self.assertEqual(attachment["password"], "[REDACTED]")
            self.assertEqual(attachment["clientSecret"], "[REDACTED]")
            persisted_bytes = b"".join(
                path.read_bytes() for path in state_root.rglob("*") if path.is_file()
            )
            for secret in (
                b"plain-access-value",
                b"plain-password-value",
                b"plain-client-value",
            ):
                self.assertNotIn(secret, persisted_bytes)

    def test_common_slack_and_jwt_credentials_are_redacted_from_plain_text_fields(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            store = TaskStateStore(FilesystemAtomicPersistence(state_root))
            payload = valid_task_request_payload()
            slack_token = "xox" + "b-" + "123456789012" + "-" + "abcdefghijklmnop"
            jwt_token = (
                "eyJhbGci" + "OiJIUzI1NiJ9."
                "eyJzdWIi" + "OiIxMjM0NTY3ODkwIn0."
                "abcdefghijklmnop"
            )
            payload["attachments"] = [
                {"note": "credentials " + slack_token + " and " + jwt_token}
            ]

            store.commit(
                TaskCommit(
                    task_id="common-credential-redaction",
                    expected_store_version=None,
                    operation_id="redact-common-values",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="request",
                            artifact_type="task_request",
                            payload=payload,
                        )
                    ],
                    transition_intent=None,
                )
            )

            persisted_bytes = b"".join(
                path.read_bytes() for path in state_root.rglob("*") if path.is_file()
            )
            self.assertNotIn(slack_token.encode("utf-8"), persisted_bytes)
            self.assertNotIn(jwt_token.encode("utf-8"), persisted_bytes)

    def test_cookie_headers_and_assignments_are_redacted_and_tampering_is_rejected(self):
        backend = InMemoryAtomicPersistence()
        store = TaskStateStore(backend)
        task_id = "cookie-redaction"
        payload = valid_task_request_payload()
        payload["attachments"] = [
            {
                "cookie_policy": "same-site-strict",
                "note": (
                    "Cookie: session=header-cookie-secret; theme=dark\n"
                    "Set-Cookie: auth=set-cookie-secret; Path=/; HttpOnly\n"
                    "cookie=assignment-cookie-secret"
                ),
            }
        ]

        store.commit(
            TaskCommit(
                task_id=task_id,
                expected_store_version=None,
                operation_id="redact-cookie-values",
                artifact_drafts=[
                    ArtifactDraft(
                        local_ref="request",
                        artifact_type="task_request",
                        payload=payload,
                    )
                ],
                transition_intent=None,
            )
        )

        raw = backend.load_bytes(task_id)
        for secret in (
            b"header-cookie-secret",
            b"set-cookie-secret",
            b"assignment-cookie-secret",
        ):
            self.assertNotIn(secret, raw)
        persisted_payload = store.load(task_id).artifacts[0]["payload"]
        self.assertEqual(
            persisted_payload["attachments"][0],
            {
                "cookie_policy": "same-site-strict",
                "note": (
                    "Cookie: [REDACTED]\n"
                    "Set-Cookie: [REDACTED]\n"
                    "cookie=[REDACTED]"
                ),
            },
        )
        self.assertEqual(persisted_payload["repository"], payload["repository"])

        manifest = json.loads(raw.decode("utf-8"))
        request = manifest["artifacts"][0]
        request["payload"]["attachments"][0]["note"] = (
            "Cookie: session=tampered-cookie-secret"
        )
        request_bytes = json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["operations"]["redact-cookie-values"]["receipt"][
            "materialized_refs"
        ]["request"]["digest"] = (
            "sha256:" + hashlib.sha256(request_bytes).hexdigest()
        )
        del manifest["integrity"]
        unsigned = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["integrity"] = {
            "digest": "sha256:" + hashlib.sha256(unsigned).hexdigest()
        }
        replacement = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        backend.compare_and_commit(task_id, raw, replacement)

        with self.assertRaises(StoreError) as raised:
            store.load(task_id)

        self.assertEqual(raised.exception.code, "state.corrupt")

    def test_credential_embedded_in_json_key_is_rejected_before_persistence(self):
        store = TaskStateStore(InMemoryAtomicPersistence())
        payload = valid_task_request_payload()
        payload["attachments"] = [{"note-" + "s" + "k-" + "abcdefghijk": "ordinary value"}]

        with self.assertRaises(ContractError):
            store.commit(
                TaskCommit(
                    task_id="credential-key",
                    expected_store_version=None,
                    operation_id="reject-unsafe-key",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="request",
                            artifact_type="task_request",
                            payload=payload,
                        )
                    ],
                    transition_intent=None,
                )
            )

        self.assertIs(store.load("credential-key"), MISSING)

    def test_credential_shaped_task_identifier_is_rejected(self):
        store = TaskStateStore(InMemoryAtomicPersistence())

        with self.assertRaises(ContractError):
            store.commit(creation_commit("s" + "k-" + "abcdefghijk"))

        self.assertIs(store.load("ordinary-task"), MISSING)

    def test_init_report_rejects_fields_forbidden_by_the_s0_contract(self):
        class NonGitInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/not-git",
                    root=None,
                    requested_scope=None,
                    kind="non_git",
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, NonGitInspector())
        engine.run("forbidden-report-fields", "/tmp/not-git", "/init")
        before = store.load("forbidden-report-fields")
        latest = next(
            artifact
            for artifact in before.artifacts
            if artifact["artifact_id"] == before.latest_report_ref.artifact_id
        )
        payload = copy.deepcopy(latest["payload"])
        payload["supersedes"] = before.latest_report_ref
        payload["artifact_refs"]["evidence"] = [LocalRef("fresh")]
        payload["rendered_markdown"] = "must not be persisted"

        with self.assertRaises(ContractError):
            store.commit(
                TaskCommit(
                    task_id="forbidden-report-fields",
                    expected_store_version=before.store_version,
                    operation_id="forbidden-report-fields",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="fresh",
                            artifact_type="evidence_record",
                            payload={
                                "kind": "inspection",
                                "invocation": "fixture",
                                "observed_revision": None,
                                "started_at": "2026-08-24T00:00:00.000Z",
                                "duration_ms": 0,
                                "exit_status": "fail",
                                "summary": "still blocked",
                                "artifact_refs": [],
                                "authority_grant": None,
                            },
                        ),
                        ArtifactDraft(
                            local_ref="report",
                            artifact_type="init_report",
                            payload=payload,
                        ),
                    ],
                    transition_intent=None,
                )
            )

        self.assertEqual(store.load("forbidden-report-fields"), before)

    def test_blocked_retry_requires_latest_supersedes_and_fresh_evidence(self):
        class NonGitInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/not-git",
                    root=None,
                    requested_scope=None,
                    kind="non_git",
                )

        def fresh_evidence():
            return {
                "kind": "inspection",
                "invocation": "fixture",
                "observed_revision": None,
                "started_at": "2026-08-24T00:00:00.000Z",
                "duration_ms": 0,
                "exit_status": "fail",
                "summary": "still blocked",
                "artifact_refs": [],
                "authority_grant": None,
            }

        for case in ("missing-supersedes", "missing-fresh-evidence"):
            with self.subTest(case=case):
                store = TaskStateStore(InMemoryAtomicPersistence())
                task_id = "blocked-chain-" + case
                engine = InitEngine(store, NonGitInspector())
                engine.run(task_id, "/tmp/not-git", "/init")
                before = store.load(task_id)
                latest = next(
                    artifact
                    for artifact in before.artifacts
                    if artifact["artifact_id"] == before.latest_report_ref.artifact_id
                )
                payload = copy.deepcopy(latest["payload"])
                payload["supersedes"] = (
                    None if case == "missing-supersedes" else before.latest_report_ref
                )
                drafts = []
                if case == "missing-supersedes":
                    drafts.append(
                        ArtifactDraft(
                            local_ref="fresh",
                            artifact_type="evidence_record",
                            payload=fresh_evidence(),
                        )
                    )
                    payload["artifact_refs"]["evidence"] = [LocalRef("fresh")]
                drafts.append(
                    ArtifactDraft(
                        local_ref="report",
                        artifact_type="init_report",
                        payload=payload,
                    )
                )

                with self.assertRaises(ContractError):
                    store.commit(
                        TaskCommit(
                            task_id=task_id,
                            expected_store_version=before.store_version,
                            operation_id="invalid-chain-" + case,
                            artifact_drafts=drafts,
                            transition_intent=None,
                        )
                    )

                self.assertEqual(store.load(task_id), before)

    def test_blocked_retry_must_reference_the_transition_that_established_current_block(self):
        class NonGitInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/not-git",
                    root=None,
                    requested_scope=None,
                    kind="non_git",
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, NonGitInspector())
        task_id = "blocked-transition-chain"
        engine.run(task_id, "/tmp/not-git", "/init")
        first_blocked = store.load(task_id)
        first_transition = next(
            reference_for(artifact)
            for artifact in first_blocked.artifacts
            if artifact["artifact_type"] == "transition"
        )
        store.commit(
            TaskCommit(
                task_id=task_id,
                expected_store_version=first_blocked.store_version,
                operation_id="resume-for-second-block",
                artifact_drafts=[],
                transition_intent=TransitionIntent(
                    local_ref="resume",
                    to_state="Intake",
                    reason="retry",
                    input_refs=[first_blocked.latest_report_ref],
                    output_ref=None,
                    actor="stage module",
                ),
            )
        )
        intake = store.load(task_id)
        latest_before_second_block = intake.latest_report_ref
        request_ref = reference_for(
            next(
                artifact
                for artifact in intake.artifacts
                if artifact["artifact_type"] == "task_request"
            )
        )
        second = store.commit(
            TaskCommit(
                task_id=task_id,
                expected_store_version=intake.store_version,
                operation_id="second-block",
                artifact_drafts=[
                    ArtifactDraft(
                        local_ref="evidence",
                        artifact_type="evidence_record",
                        payload={
                            "kind": "inspection",
                            "invocation": "fixture",
                            "observed_revision": None,
                            "started_at": "2026-08-24T00:00:00.000Z",
                            "duration_ms": 0,
                            "exit_status": "fail",
                            "summary": "blocked again",
                            "artifact_refs": [],
                            "authority_grant": None,
                        },
                    ),
                    ArtifactDraft(
                        local_ref="report",
                        artifact_type="init_report",
                        payload={
                            "repository": {
                                "requested_path": "/tmp/not-git",
                                "root": None,
                                "requested_scope": None,
                                "revision": None,
                                "superproject": None,
                            },
                            "sources": [],
                            "findings": {
                                "entry_docs": [],
                                "repository_instructions": [],
                                "verification_commands": [],
                            },
                            "gaps": ["eligible_repository"],
                            "outcome": "blocked",
                            "blocker": {
                                "code": "blocked.repository.not_git",
                                "message": "not git",
                                "resume_when": "select git",
                            },
                            "artifact_refs": {
                                "task_request": request_ref,
                                "transition": LocalRef("transition"),
                                "evidence": [LocalRef("evidence")],
                            },
                            "supersedes": latest_before_second_block,
                        },
                    ),
                ],
                transition_intent=TransitionIntent(
                    local_ref="transition",
                    to_state="Blocked",
                    reason="blocked.repository.not_git",
                    input_refs=[request_ref, LocalRef("evidence")],
                    output_ref=None,
                    actor="stage module",
                ),
            )
        )
        current = store.load(task_id)
        latest = next(
            artifact
            for artifact in current.artifacts
            if artifact["artifact_id"] == second.materialized_refs["report"].artifact_id
        )
        payload = copy.deepcopy(latest["payload"])
        payload["supersedes"] = current.latest_report_ref
        payload["artifact_refs"]["transition"] = first_transition
        payload["artifact_refs"]["evidence"] = [LocalRef("fresh")]

        with self.assertRaises(ContractError):
            store.commit(
                TaskCommit(
                    task_id=task_id,
                    expected_store_version=current.store_version,
                    operation_id="wrong-block-transition",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="fresh",
                            artifact_type="evidence_record",
                            payload={
                                "kind": "inspection",
                                "invocation": "fixture",
                                "observed_revision": None,
                                "started_at": "2026-08-24T00:00:00.000Z",
                                "duration_ms": 0,
                                "exit_status": "fail",
                                "summary": "still blocked",
                                "artifact_refs": [],
                                "authority_grant": None,
                            },
                        ),
                        ArtifactDraft(
                            local_ref="report",
                            artifact_type="init_report",
                            payload=payload,
                        ),
                    ],
                    transition_intent=None,
                )
            )

    def test_load_rejects_a_recomputed_but_disconnected_blocked_report_chain(self):
        class NonGitInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/not-git",
                    root=None,
                    requested_scope=None,
                    kind="non_git",
                )

        backend = InMemoryAtomicPersistence()
        store = TaskStateStore(backend)
        task_id = "corrupt-blocked-chain"
        engine = InitEngine(store, NonGitInspector())
        engine.run(task_id, "/tmp/not-git", "/init")
        engine.run(task_id, "/tmp/not-git", "/init")
        raw = backend.load_bytes(task_id)
        manifest = json.loads(raw.decode("utf-8"))
        report = manifest["artifacts"][-1]
        self.assertEqual(report["artifact_type"], "init_report")
        report["payload"]["supersedes"] = None
        named = report["payload"]["artifact_refs"]
        report["input_refs"] = [
            named["task_request"],
            named["transition"],
            *named["evidence"],
        ]
        report_bytes = json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        report_digest = "sha256:" + hashlib.sha256(report_bytes).hexdigest()
        manifest["latest_report_ref"]["digest"] = report_digest
        for operation in manifest["operations"].values():
            materialized = operation["receipt"]["materialized_refs"]
            for reference in materialized.values():
                if reference["artifact_id"] == report["artifact_id"]:
                    reference["digest"] = report_digest
        del manifest["integrity"]
        unsigned = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["integrity"] = {
            "digest": "sha256:" + hashlib.sha256(unsigned).hexdigest()
        }
        replacement = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        backend.compare_and_commit(task_id, raw, replacement)

        with self.assertRaises(StoreError) as raised:
            store.load(task_id)

        self.assertEqual(raised.exception.code, "state.corrupt")

    def test_task_request_cannot_be_added_or_replaced_after_creation(self):
        store = TaskStateStore(InMemoryAtomicPersistence())
        task_id = "immutable-request"
        store.commit(creation_commit(task_id))
        before = store.load(task_id)
        replacement = TaskCommit(
            task_id=task_id,
            expected_store_version=before.store_version,
            operation_id="replace-request",
            artifact_drafts=[
                ArtifactDraft(
                    local_ref="replacement",
                    artifact_type="task_request",
                    payload=valid_task_request_payload(),
                )
            ],
            transition_intent=None,
        )

        with self.assertRaises(ContractError):
            store.commit(replacement)

        self.assertEqual(store.load(task_id), before)

    def test_load_rejects_incompatible_artifact_schema_after_integrity_is_recomputed(self):
        backend = InMemoryAtomicPersistence()
        store = TaskStateStore(backend)
        task_id = "incompatible-artifact-schema"
        store.commit(creation_commit(task_id))
        raw = backend.load_bytes(task_id)
        manifest = json.loads(raw.decode("utf-8"))
        request_envelope = manifest["artifacts"][0]
        request_envelope["schema_version"] = "ai-native-devkit/v99"
        request_bytes = json.dumps(
            request_envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request_digest = "sha256:" + hashlib.sha256(request_bytes).hexdigest()
        manifest["operations"]["create-task"]["receipt"]["materialized_refs"][
            "request"
        ]["digest"] = request_digest
        del manifest["integrity"]
        unsigned = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["integrity"] = {
            "digest": "sha256:" + hashlib.sha256(unsigned).hexdigest()
        }
        replacement = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        backend.compare_and_commit(task_id, raw, replacement)

        with self.assertRaises(StoreError) as raised:
            store.load(task_id)

        self.assertEqual(raised.exception.code, "state.corrupt")

    def test_compatible_unknown_envelope_and_payload_fields_survive_round_trip(self):
        backend = InMemoryAtomicPersistence()
        store = TaskStateStore(backend)
        task_id = "compatible-unknown-fields"
        store.commit(creation_commit(task_id))
        raw = backend.load_bytes(task_id)
        manifest = json.loads(raw.decode("utf-8"))
        request_envelope = manifest["artifacts"][0]
        request_envelope["future_envelope"] = {"mode": "compatible"}
        request_envelope["payload"]["future_payload"] = {"value": 7}
        request_bytes = json.dumps(
            request_envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request_digest = "sha256:" + hashlib.sha256(request_bytes).hexdigest()
        operation = manifest["operations"]["create-task"]
        operation["receipt"]["materialized_refs"]["request"][
            "digest"
        ] = request_digest
        del manifest["integrity"]
        unsigned = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["integrity"] = {
            "digest": "sha256:" + hashlib.sha256(unsigned).hexdigest()
        }
        replacement = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        backend.compare_and_commit(task_id, raw, replacement)
        loaded = store.load(task_id)
        evidence_commit = TaskCommit(
            task_id=task_id,
            expected_store_version=loaded.store_version,
            operation_id="append-compatible-evidence",
            artifact_drafts=[
                ArtifactDraft(
                    local_ref="evidence",
                    artifact_type="evidence_record",
                    payload={
                        "kind": "inspection",
                        "invocation": "fixture",
                        "observed_revision": None,
                        "started_at": "2026-08-24T00:00:00.000Z",
                        "duration_ms": 0,
                        "exit_status": "pass",
                        "summary": "fixture",
                        "artifact_refs": [],
                        "authority_grant": None,
                        "future_payload": {"value": 8},
                    },
                )
            ],
            transition_intent=None,
        )

        store.commit(evidence_commit)

        snapshot = store.load(task_id)
        self.assertEqual(
            snapshot.artifacts[0]["future_envelope"], {"mode": "compatible"}
        )
        self.assertEqual(
            snapshot.artifacts[0]["payload"]["future_payload"], {"value": 7}
        )
        self.assertEqual(
            snapshot.artifacts[1]["payload"]["future_payload"], {"value": 8}
        )

    def test_historical_non_clarification_producer_remains_readable(self):
        backend = InMemoryAtomicPersistence()
        store = TaskStateStore(backend)
        task_id = "historical-init-producer"
        store.commit(creation_commit(task_id))
        raw = backend.load_bytes(task_id)
        manifest = json.loads(raw.decode("utf-8"))
        request = manifest["artifacts"][0]
        request["producer"] = "ai-native-devkit/workflow-runtime@0.3.0"
        request_bytes = json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request_digest = "sha256:" + hashlib.sha256(request_bytes).hexdigest()
        manifest["operations"]["create-task"]["receipt"]["materialized_refs"][
            "request"
        ]["digest"] = request_digest
        del manifest["integrity"]
        unsigned = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["integrity"] = {
            "digest": "sha256:" + hashlib.sha256(unsigned).hexdigest()
        }
        replacement = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        backend.compare_and_commit(task_id, raw, replacement)

        snapshot = store.load(task_id)

        self.assertEqual(
            snapshot.artifacts[0]["producer"],
            "ai-native-devkit/workflow-runtime@0.3.0",
        )

    def test_load_rejects_unredacted_secret_in_compatible_unknown_field(self):
        backend = InMemoryAtomicPersistence()
        store = TaskStateStore(backend)
        task_id = "unsafe-compatible-field"
        store.commit(creation_commit(task_id))
        raw = backend.load_bytes(task_id)
        manifest = json.loads(raw.decode("utf-8"))
        request = manifest["artifacts"][0]
        request["payload"]["future_access_token"] = "plain-secret-value"
        request_bytes = json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["operations"]["create-task"]["receipt"]["materialized_refs"][
            "request"
        ]["digest"] = "sha256:" + hashlib.sha256(request_bytes).hexdigest()
        del manifest["integrity"]
        unsigned = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["integrity"] = {
            "digest": "sha256:" + hashlib.sha256(unsigned).hexdigest()
        }
        replacement = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        backend.compare_and_commit(task_id, raw, replacement)

        with self.assertRaises(StoreError) as raised:
            store.load(task_id)

        self.assertEqual(raised.exception.code, "state.corrupt")

    def test_semantically_corrupt_operation_receipt_is_rejected_even_with_new_integrity(self):
        backend = InMemoryAtomicPersistence()
        store = TaskStateStore(backend)
        task_id = "semantic-corruption"
        store.commit(creation_commit(task_id))
        raw = backend.load_bytes(task_id)
        manifest = json.loads(raw.decode("utf-8"))
        manifest["operations"]["create-task"]["receipt"]["task_id"] = "other-task"
        del manifest["integrity"]
        unsigned = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["integrity"] = {
            "digest": "sha256:" + hashlib.sha256(unsigned).hexdigest()
        }
        replacement = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        backend.compare_and_commit(task_id, raw, replacement)

        with self.assertRaises(StoreError) as raised:
            store.load(task_id)

        self.assertEqual(raised.exception.code, "state.corrupt")

    def test_task_request_envelope_cannot_claim_repository_observation(self):
        backend = InMemoryAtomicPersistence()
        store = TaskStateStore(backend)
        task_id = "invalid-request-observation"
        store.commit(creation_commit(task_id))
        raw = backend.load_bytes(task_id)
        manifest = json.loads(raw.decode("utf-8"))
        request_envelope = manifest["artifacts"][0]
        request_envelope["repo_revision"] = {
            "head_state": "attached",
            "head": "a" * 40,
            "branch": "main",
            "dirty": False,
            "worktree_digest": None,
        }
        request_bytes = json.dumps(
            request_envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["operations"]["create-task"]["receipt"]["materialized_refs"][
            "request"
        ]["digest"] = "sha256:" + hashlib.sha256(request_bytes).hexdigest()
        del manifest["integrity"]
        unsigned = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["integrity"] = {
            "digest": "sha256:" + hashlib.sha256(unsigned).hexdigest()
        }
        replacement = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        backend.compare_and_commit(task_id, raw, replacement)

        with self.assertRaises(StoreError) as raised:
            store.load(task_id)

        self.assertEqual(raised.exception.code, "state.corrupt")

    def test_dirty_repository_revision_requires_worktree_digest(self):
        store = TaskStateStore(InMemoryAtomicPersistence())
        task_id = "dirty-without-digest"
        store.commit(creation_commit(task_id))
        before = store.load(task_id)
        commit = TaskCommit(
            task_id=task_id,
            expected_store_version=before.store_version,
            operation_id="dirty-without-digest",
            artifact_drafts=[
                ArtifactDraft(
                    local_ref="evidence",
                    artifact_type="evidence_record",
                    payload={
                        "kind": "inspection",
                        "invocation": "fixture",
                        "observed_revision": {
                            "head_state": "attached",
                            "head": "a" * 40,
                            "branch": "main",
                            "dirty": True,
                            "worktree_digest": None,
                        },
                        "started_at": "2026-08-24T00:00:00.000Z",
                        "duration_ms": 0,
                        "exit_status": "pass",
                        "summary": "fixture",
                        "artifact_refs": [],
                        "authority_grant": None,
                    },
                )
            ],
            transition_intent=None,
        )

        with self.assertRaises(ContractError):
            store.commit(commit)

        self.assertEqual(store.load(task_id), before)

    def test_transition_actor_must_be_a_registered_contract_value(self):
        class NonGitInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/not-git",
                    root=None,
                    requested_scope=None,
                    kind="non_git",
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, NonGitInspector())
        engine.run("invalid-transition-actor", "/tmp/not-git", "/init")
        before = store.load("invalid-transition-actor")
        commit = TaskCommit(
            task_id="invalid-transition-actor",
            expected_store_version=before.store_version,
            operation_id="invalid-transition-actor",
            artifact_drafts=[],
            transition_intent=TransitionIntent(
                local_ref="resume",
                to_state="Intake",
                reason="fixture",
                input_refs=[before.latest_report_ref],
                output_ref=None,
                actor="unregistered actor",
            ),
        )

        with self.assertRaises(ContractError):
            store.commit(commit)

        self.assertEqual(store.load("invalid-transition-actor"), before)

    def test_persistence_read_failure_is_a_typed_runtime_error(self):
        class ReadFailurePersistence:
            def load_bytes(self, task_id):
                raise OSError("simulated read failure")

            def compare_and_commit(self, task_id, expected, replacement):
                raise AssertionError("write must not be attempted")

        store = TaskStateStore(ReadFailurePersistence())

        with self.assertRaises(StoreError) as raised:
            store.load("read-failure")

        self.assertEqual(raised.exception.code, "persistence.read_failed")
        self.assertTrue(raised.exception.retryable)

    def test_oversized_artifact_payload_is_rejected_before_persistence(self):
        store = TaskStateStore(InMemoryAtomicPersistence())
        task_id = "oversized-payload"
        payload = valid_task_request_payload()
        payload["user_request"] = "x" * (300 * 1024)
        commit = TaskCommit(
            task_id=task_id,
            expected_store_version=None,
            operation_id="oversized-payload",
            artifact_drafts=[
                ArtifactDraft(
                    local_ref="request",
                    artifact_type="task_request",
                    payload=payload,
                )
            ],
            transition_intent=None,
        )

        with self.assertRaises(ContractError):
            store.commit(commit)

        self.assertIs(store.load(task_id), MISSING)

    def test_creation_rejects_malformed_task_request_without_committing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            stores = [
                TaskStateStore(InMemoryAtomicPersistence()),
                TaskStateStore(
                    FilesystemAtomicPersistence(Path(temporary_directory) / "state")
                ),
            ]
            for index, store in enumerate(stores):
                task_id = "malformed-task-" + str(index)
                commit = TaskCommit(
                    task_id=task_id,
                    expected_store_version=None,
                    operation_id="create-malformed",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="request",
                            artifact_type="task_request",
                            payload={"intent": "init"},
                        )
                    ],
                    transition_intent=None,
                )

                with self.subTest(adapter=index):
                    with self.assertRaises(ContractError):
                        store.commit(commit)
                    self.assertIs(store.load(task_id), MISSING)

    def test_task_request_rejects_scope_that_is_not_a_descendant_of_observed_root(self):
        store = TaskStateStore(InMemoryAtomicPersistence())
        payload = valid_task_request_payload()
        payload["repository"]["requested_scope"] = "../outside"

        with self.assertRaises(ContractError):
            store.commit(
                TaskCommit(
                    task_id="invalid-request-scope",
                    expected_store_version=None,
                    operation_id="invalid-request-scope",
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="request",
                            artifact_type="task_request",
                            payload=payload,
                        )
                    ],
                    transition_intent=None,
                )
            )

        self.assertIs(store.load("invalid-request-scope"), MISSING)


if __name__ == "__main__":
    unittest.main()
