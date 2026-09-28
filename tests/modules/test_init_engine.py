import sys
from pathlib import Path
import tempfile
import threading
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit.errors import RepositoryError, StoreError
from ai_native_devkit.init_engine import InitEngine
from ai_native_devkit.persistence import FilesystemAtomicPersistence, InMemoryAtomicPersistence
from ai_native_devkit.repository import RepositoryClassification, RepositoryInspection
from ai_native_devkit.contracts import (
    ArtifactDraft,
    EvidenceRecord,
    LocalRef,
    RepositoryRevision,
    TaskCommit,
    TaskRequest,
    TransitionIntent,
)
from ai_native_devkit.state_store import MISSING, TaskStateStore


class _DelayedSecondCreateStore:
    """Force both callers to observe MISSING before one create is delayed."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._missing_loads = threading.Barrier(2)
        self._commit_lock = threading.Lock()
        self._create_commits = 0
        self._winner_finished = threading.Event()

    def load(self, task_id):
        snapshot = self._delegate.load(task_id)
        if snapshot is MISSING:
            self._missing_loads.wait(timeout=5)
        return snapshot

    def commit(self, commit):
        is_create = commit.operation_id.startswith("init:create:")
        if is_create:
            with self._commit_lock:
                self._create_commits += 1
                create_number = self._create_commits
            if create_number == 2:
                if not self._winner_finished.wait(timeout=5):
                    raise AssertionError("The winning init did not finish in time.")
        receipt = self._delegate.commit(commit)
        if not is_create:
            self._winner_finished.set()
        return receipt


class InitEngineTests(unittest.TestCase):
    def test_delayed_equivalent_create_reuses_concurrent_ready_winner(self):
        class ReadyInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/delayed-ready-repository",
                    root="/tmp/delayed-ready-repository",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                revision = RepositoryRevision(
                    head_state="attached",
                    head="d" * 40,
                    branch="main",
                    dirty=False,
                    worktree_digest=None,
                )
                return RepositoryInspection(
                    repository={
                        "requested_path": classification.requested_path,
                        "root": classification.root,
                        "requested_scope": None,
                        "revision": revision.to_dict(),
                        "superproject": None,
                    },
                    revision=revision,
                    sources=[
                        {
                            "id": "repository:.",
                            "path": ".",
                            "kind": "repository",
                            "hash": "sha256:" + "3" * 64,
                        }
                    ],
                    findings={
                        "entry_docs": [],
                        "repository_instructions": [],
                        "verification_commands": [],
                    },
                    gaps=[
                        "entry_docs",
                        "repository_instructions",
                        "verification_commands",
                    ],
                    started_at="2026-08-24T01:00:00.000Z",
                    duration_ms=1,
                )

        durable_store = TaskStateStore(InMemoryAtomicPersistence())
        delayed_store = _DelayedSecondCreateStore(durable_store)
        responses = []
        errors = []

        def initialize():
            try:
                responses.append(
                    InitEngine(delayed_store, ReadyInspector()).run(
                        "delayed-ready-task",
                        "/tmp/delayed-ready-repository",
                        "/init",
                    )
                )
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=initialize) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["report_ref"], responses[1]["report_ref"])
        snapshot = durable_store.load("delayed-ready-task")
        self.assertEqual(snapshot.lifecycle_state, "ContextReady")
        self.assertEqual(len(snapshot.artifacts), 4)

    def test_delayed_equivalent_create_reuses_concurrent_blocked_winner(self):
        class BlockedInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/delayed-blocked-repository",
                    root="/tmp/delayed-blocked-repository",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                raise RepositoryError(
                    "blocked.repository.read_failed",
                    "A selected repository source could not be read safely.",
                    retryable=True,
                )

        durable_store = TaskStateStore(InMemoryAtomicPersistence())
        delayed_store = _DelayedSecondCreateStore(durable_store)
        responses = []
        errors = []

        def initialize():
            try:
                responses.append(
                    InitEngine(delayed_store, BlockedInspector()).run(
                        "delayed-blocked-task",
                        "/tmp/delayed-blocked-repository",
                        "/init",
                    )
                )
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=initialize) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["report_ref"], responses[1]["report_ref"])
        snapshot = durable_store.load("delayed-blocked-task")
        self.assertEqual(snapshot.lifecycle_state, "Blocked")
        self.assertEqual(len(snapshot.artifacts), 4)

    def test_delayed_non_equivalent_create_reenters_existing_ready_route(self):
        class ChangingInspector:
            def __init__(self):
                self._lock = threading.Lock()
                self._calls = 0

            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/delayed-changing-repository",
                    root="/tmp/delayed-changing-repository",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                with self._lock:
                    self._calls += 1
                    call = self._calls
                revision = RepositoryRevision(
                    head_state="attached",
                    head="c" * 40,
                    branch="main",
                    dirty=call > 1,
                    worktree_digest=(
                        None if call == 1 else "sha256:" + "4" * 64
                    ),
                )
                return RepositoryInspection(
                    repository={
                        "requested_path": classification.requested_path,
                        "root": classification.root,
                        "requested_scope": None,
                        "revision": revision.to_dict(),
                        "superproject": None,
                    },
                    revision=revision,
                    sources=[
                        {
                            "id": "repository:.",
                            "path": ".",
                            "kind": "repository",
                            "hash": "sha256:" + str(call) * 64,
                        }
                    ],
                    findings={
                        "entry_docs": [],
                        "repository_instructions": [],
                        "verification_commands": [],
                    },
                    gaps=[
                        "entry_docs",
                        "repository_instructions",
                        "verification_commands",
                    ],
                    started_at="2026-08-24T01:00:00.000Z",
                    duration_ms=1,
                )

        durable_store = TaskStateStore(InMemoryAtomicPersistence())
        delayed_store = _DelayedSecondCreateStore(durable_store)
        inspector = ChangingInspector()
        responses = []
        errors = []

        def initialize():
            try:
                responses.append(
                    InitEngine(delayed_store, inspector).run(
                        "delayed-changing-task",
                        "/tmp/delayed-changing-repository",
                        "/init",
                    )
                )
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=initialize) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(
            sorted(response["kind"] for response in responses),
            ["choice_required", "report"],
        )
        choice_response = next(
            response for response in responses if response["kind"] == "choice_required"
        )
        self.assertEqual(choice_response["reason"], "init.ready_stale")
        snapshot = durable_store.load("delayed-changing-task")
        self.assertEqual(snapshot.lifecycle_state, "ContextReady")
        self.assertEqual(len(snapshot.artifacts), 4)

    def test_concurrent_equivalent_initialization_returns_one_shared_ready_report(self):
        class ConcurrentInspector:
            def __init__(self):
                self.barrier = threading.Barrier(2)
                self.lock = threading.Lock()
                self.calls = 0

            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/concurrent-repository",
                    root="/tmp/concurrent-repository",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                with self.lock:
                    self.calls += 1
                    call = self.calls
                self.barrier.wait(timeout=5)
                revision = RepositoryRevision(
                    head_state="attached",
                    head="e" * 40,
                    branch="main",
                    dirty=False,
                    worktree_digest=None,
                )
                return RepositoryInspection(
                    repository={
                        "requested_path": classification.requested_path,
                        "root": classification.root,
                        "requested_scope": None,
                        "revision": revision.to_dict(),
                        "superproject": None,
                    },
                    revision=revision,
                    sources=[
                        {
                            "id": "repository:.",
                            "path": ".",
                            "kind": "repository",
                            "hash": "sha256:" + "2" * 64,
                        }
                    ],
                    findings={
                        "entry_docs": [],
                        "repository_instructions": [],
                        "verification_commands": [],
                    },
                    gaps=[
                        "entry_docs",
                        "repository_instructions",
                        "verification_commands",
                    ],
                    started_at=f"2026-08-24T00:00:0{call}.000Z",
                    duration_ms=call,
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        inspector = ConcurrentInspector()
        responses = []
        errors = []

        def initialize():
            try:
                responses.append(
                    InitEngine(store, inspector).run(
                        "concurrent-ready-task",
                        "/tmp/concurrent-repository",
                        "/init",
                    )
                )
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=initialize) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["report_ref"], responses[1]["report_ref"])
        snapshot = store.load("concurrent-ready-task")
        self.assertEqual(snapshot.lifecycle_state, "ContextReady")
        self.assertEqual(
            [artifact["artifact_type"] for artifact in snapshot.artifacts],
            ["task_request", "evidence_record", "transition", "init_report"],
        )

    def test_concurrent_equivalent_initial_blocker_returns_one_shared_report(self):
        class ConcurrentBlockedInspector:
            def __init__(self):
                self.barrier = threading.Barrier(2)

            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/concurrent-blocked-repository",
                    root="/tmp/concurrent-blocked-repository",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                self.barrier.wait(timeout=5)
                raise RepositoryError(
                    "blocked.repository.read_failed",
                    "A selected repository source could not be read safely.",
                    retryable=True,
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        inspector = ConcurrentBlockedInspector()
        responses = []
        errors = []

        def initialize():
            try:
                responses.append(
                    InitEngine(store, inspector).run(
                        "concurrent-blocked-task",
                        "/tmp/concurrent-blocked-repository",
                        "/init",
                    )
                )
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=initialize) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["report_ref"], responses[1]["report_ref"])
        self.assertEqual(responses[0]["report"]["payload"]["outcome"], "blocked")
        snapshot = store.load("concurrent-blocked-task")
        self.assertEqual(snapshot.lifecycle_state, "Blocked")
        self.assertEqual(
            [artifact["artifact_type"] for artifact in snapshot.artifacts],
            ["task_request", "evidence_record", "transition", "init_report"],
        )

    def test_ready_task_with_new_inspection_uncertainty_is_stale_not_runtime_failure(self):
        class BecomesUncertainInspector:
            calls = 0

            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/uncertain-after-ready",
                    root="/tmp/uncertain-after-ready",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                self.calls += 1
                if self.calls > 1:
                    raise RepositoryError(
                        "blocked.repository.source_conflict",
                        "Repository instruction sources now conflict.",
                        retryable=True,
                    )
                revision = RepositoryRevision(
                    head_state="attached",
                    head="f" * 40,
                    branch="main",
                    dirty=False,
                    worktree_digest=None,
                )
                return RepositoryInspection(
                    repository={
                        "requested_path": classification.requested_path,
                        "root": classification.root,
                        "requested_scope": None,
                        "revision": revision.to_dict(),
                        "superproject": None,
                    },
                    revision=revision,
                    sources=[
                        {
                            "id": "repository:.",
                            "path": ".",
                            "kind": "repository",
                            "hash": "sha256:" + "1" * 64,
                        }
                    ],
                    findings={
                        "entry_docs": [],
                        "repository_instructions": [],
                        "verification_commands": [],
                    },
                    gaps=[
                        "entry_docs",
                        "repository_instructions",
                        "verification_commands",
                    ],
                    started_at="2026-08-24T00:00:00.000Z",
                    duration_ms=1,
                )

        inspector = BecomesUncertainInspector()
        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, inspector)
        engine.run(
            "ready-becomes-uncertain",
            "/tmp/uncertain-after-ready",
            "/init",
        )
        before = store.load("ready-becomes-uncertain")

        response = engine.run(
            "ready-becomes-uncertain",
            "/tmp/uncertain-after-ready",
            "/init",
        )

        self.assertEqual(
            response,
            {
                "schema_version": "ai-native-devkit/v1alpha1",
                "kind": "choice_required",
                "reason": "init.ready_stale",
                "choices": ["new", "cancel"],
            },
        )
        self.assertEqual(store.load("ready-becomes-uncertain"), before)

    def test_same_frozen_inspection_projection_across_persistence_adapters(self):
        class FrozenInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/frozen-repository",
                    root="/tmp/frozen-repository",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                revision = RepositoryRevision(
                    head_state="attached",
                    head="a" * 40,
                    branch="main",
                    dirty=False,
                    worktree_digest=None,
                )
                return RepositoryInspection(
                    repository={
                        "requested_path": classification.requested_path,
                        "root": classification.root,
                        "requested_scope": classification.requested_scope,
                        "revision": revision.to_dict(),
                        "superproject": None,
                    },
                    revision=revision,
                    sources=[
                        {
                            "id": "repository:.",
                            "path": ".",
                            "kind": "repository",
                            "hash": "sha256:" + "b" * 64,
                        },
                        {
                            "id": "entry_doc:README.md",
                            "path": "README.md",
                            "kind": "entry_doc",
                            "hash": "sha256:cee5438c38e54a2d71f6b4c7c61d6796711f8f3e5cd5c6b718648503bf6f69fe",
                        },
                    ],
                    findings={
                        "entry_docs": ["README.md"],
                        "repository_instructions": [],
                        "verification_commands": [],
                    },
                    gaps=["repository_instructions", "verification_commands"],
                    started_at="2026-08-24T00:00:00.000Z",
                    duration_ms=1,
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            stores = [
                TaskStateStore(InMemoryAtomicPersistence()),
                TaskStateStore(
                    FilesystemAtomicPersistence(
                        Path(temporary_directory) / "filesystem-state"
                    )
                ),
            ]
            projections = []
            artifact_types = []
            for index, store in enumerate(stores):
                response = InitEngine(store, FrozenInspector()).run(
                    task_id="adapter-parity-" + str(index),
                    requested_path="/tmp/frozen-repository",
                    user_request="/init",
                )
                payload = response["report"]["payload"]
                projections.append(
                    {
                        key: payload[key]
                        for key in (
                            "repository",
                            "sources",
                            "findings",
                            "gaps",
                            "outcome",
                            "blocker",
                        )
                    }
                )
                snapshot = store.load("adapter-parity-" + str(index))
                self.assertEqual(snapshot.lifecycle_state, "ContextReady")
                artifact_types.append(
                    [artifact["artifact_type"] for artifact in snapshot.artifacts]
                )

        self.assertEqual(projections[0], projections[1])
        self.assertEqual(artifact_types[0], artifact_types[1])

    def test_existing_task_rejects_a_different_resolved_repository_target(self):
        class MutableClassificationInspector:
            def __init__(self, first, second):
                self.classification = first
                self.second = second

            def classify(self, requested_path):
                return self.classification

            def inspect(self, classification):
                revision = RepositoryRevision(
                    head_state="attached",
                    head="a" * 40,
                    branch="main",
                    dirty=False,
                    worktree_digest=None,
                )
                return RepositoryInspection(
                    repository={
                        "requested_path": classification.requested_path,
                        "root": classification.root,
                        "requested_scope": classification.requested_scope,
                        "revision": revision.to_dict(),
                        "superproject": None,
                    },
                    revision=revision,
                    sources=[],
                    findings={
                        "entry_docs": [],
                        "repository_instructions": [],
                        "verification_commands": [],
                    },
                    gaps=[
                        "entry_docs",
                        "repository_instructions",
                        "verification_commands",
                    ],
                    started_at="2026-08-24T00:00:00.000Z",
                    duration_ms=1,
                )

        cases = [
            (
                "requested_path",
                RepositoryClassification("/tmp/repository", "/tmp/repository", None, "worktree"),
                RepositoryClassification("/tmp/other", "/tmp/other", None, "worktree"),
            ),
            (
                "root",
                RepositoryClassification("/tmp/repository", "/tmp/repository", None, "worktree"),
                RepositoryClassification("/tmp/repository", "/tmp/other", None, "worktree"),
            ),
            (
                "requested_scope",
                RepositoryClassification(
                    "/tmp/repository/sub", "/tmp/repository", "sub", "worktree"
                ),
                RepositoryClassification(
                    "/tmp/repository/sub", "/tmp/repository", "other", "worktree"
                ),
            ),
        ]
        for label, first, second in cases:
            with self.subTest(field=label):
                inspector = MutableClassificationInspector(first, second)
                store = TaskStateStore(InMemoryAtomicPersistence())
                engine = InitEngine(store, inspector)
                engine.run(
                    task_id="task-target-" + label,
                    requested_path=first.requested_path,
                    user_request="/init",
                )
                before = store.load("task-target-" + label)
                inspector.classification = second

                with self.assertRaises(StoreError) as raised:
                    engine.run(
                        task_id="task-target-" + label,
                        requested_path=second.requested_path,
                        user_request="/init",
                    )

                self.assertEqual(raised.exception.code, "init.task_target_mismatch")
                self.assertEqual(store.load("task-target-" + label), before)

    def test_followup_choices_are_rejected_unless_task_is_context_ready(self):
        class NonGitInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/choice-invalid",
                    root=None,
                    requested_scope=None,
                    kind="non_git",
                )

        def scenario(lifecycle_state):
            store = TaskStateStore(InMemoryAtomicPersistence())
            engine = InitEngine(store, NonGitInspector())
            task_id = "task-choice-" + lifecycle_state.lower()
            if lifecycle_state == "Intake":
                store.commit(
                    TaskCommit(
                        task_id=task_id,
                        expected_store_version=None,
                        operation_id="create-intake-fixture",
                        artifact_drafts=[
                            ArtifactDraft(
                                local_ref="request",
                                artifact_type="task_request",
                                payload=TaskRequest(
                                    user_request="/init",
                                    requested_path="/tmp/choice-invalid",
                                    observed_root=None,
                                    requested_scope=None,
                                ).to_payload(),
                            )
                        ],
                        transition_intent=None,
                    )
                )
            elif lifecycle_state == "Blocked":
                engine.run(task_id, "/tmp/choice-invalid", "/init")
            return store, engine, task_id

        for lifecycle_state in ("missing", "Intake", "Blocked"):
            for choice in ("reuse", "new", "cancel"):
                with self.subTest(state=lifecycle_state, choice=choice):
                    store, engine, task_id = scenario(lifecycle_state)
                    before = store.load(task_id)

                    with self.assertRaises(StoreError) as raised:
                        engine.run(
                            task_id,
                            "/tmp/choice-invalid",
                            "/init",
                            choice=choice,
                        )

                    self.assertEqual(raised.exception.code, "init.invalid_choice")
                    self.assertEqual(store.load(task_id), before)

    def test_safety_relevant_inspection_uncertainty_returns_blocked_report(self):
        class UncertainInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/uncertain-repository",
                    root="/tmp/uncertain-repository",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                raise RepositoryError(
                    "blocked.repository.read_authority",
                    "Repository inspection requires additional read authority.",
                    retryable=False,
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, UncertainInspector())

        response = engine.run(
            task_id="task-read-authority",
            requested_path="/tmp/uncertain-repository",
            user_request="/init",
        )

        payload = response["report"]["payload"]
        self.assertEqual(response["kind"], "report")
        self.assertEqual(payload["outcome"], "blocked")
        self.assertEqual(
            payload["blocker"],
            {
                "code": "blocked.repository.read_authority",
                "message": "Repository inspection requires additional read authority.",
                "resume_when": "Grant the required bounded repository read authority, then retry this task.",
            },
        )
        self.assertEqual(payload["repository"]["root"], "/tmp/uncertain-repository")
        self.assertIsNone(payload["repository"]["revision"])
        snapshot = store.load("task-read-authority")
        self.assertEqual(snapshot.lifecycle_state, "Blocked")
        self.assertEqual(snapshot.resume_state, "Intake")

    def test_persisting_inspection_blocker_retries_without_lifecycle_self_transition(self):
        class UncertainInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/uncertain-repository",
                    root="/tmp/uncertain-repository",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                raise RepositoryError(
                    "blocked.repository.read_authority",
                    "Repository inspection requires additional read authority.",
                    retryable=False,
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, UncertainInspector())
        first = engine.run(
            task_id="task-persisting-authority",
            requested_path="/tmp/uncertain-repository",
            user_request="/init",
        )

        retried = engine.run(
            task_id="task-persisting-authority",
            requested_path="/tmp/uncertain-repository",
            user_request="/init",
        )

        self.assertEqual(retried["report"]["payload"]["outcome"], "blocked")
        self.assertEqual(
            retried["report"]["payload"]["supersedes"], first["report_ref"]
        )
        snapshot = store.load("task-persisting-authority")
        transitions = [
            artifact
            for artifact in snapshot.artifacts
            if artifact["artifact_type"] == "transition"
        ]
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["payload"]["from"], "Intake")
        self.assertEqual(transitions[0]["payload"]["to"], "Blocked")

    def test_later_authority_grant_is_append_only_and_referenced_on_resume(self):
        class AuthorityInspector:
            allowed = False

            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/authority-repository",
                    root="/tmp/authority-repository",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                if not self.allowed:
                    raise RepositoryError(
                        "blocked.repository.read_authority",
                        "Repository inspection requires additional read authority.",
                        retryable=False,
                    )
                revision = RepositoryRevision(
                    head_state="attached",
                    head="b" * 40,
                    branch="main",
                    dirty=False,
                    worktree_digest=None,
                )
                return RepositoryInspection(
                    repository={
                        "requested_path": classification.requested_path,
                        "root": classification.root,
                        "requested_scope": None,
                        "revision": revision.to_dict(),
                        "superproject": None,
                    },
                    revision=revision,
                    sources=[
                        {
                            "id": "repository:.",
                            "path": ".",
                            "kind": "repository",
                            "hash": "sha256:" + "c" * 64,
                        }
                    ],
                    findings={
                        "entry_docs": [],
                        "repository_instructions": [],
                        "verification_commands": [],
                    },
                    gaps=[
                        "entry_docs",
                        "repository_instructions",
                        "verification_commands",
                    ],
                    started_at="2026-08-24T00:00:00.000Z",
                    duration_ms=1,
                )

        inspector = AuthorityInspector()
        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, inspector)
        engine.run(
            task_id="task-authority-resume",
            requested_path="/tmp/authority-repository",
            user_request="/init",
        )
        before = store.load("task-authority-resume")
        original_request = next(
            artifact
            for artifact in before.artifacts
            if artifact["artifact_type"] == "task_request"
        )
        inspector.allowed = True
        grant = {
            "capabilities": ["repository.read"],
            "scopes": ["repository:v1:."],
            "confirmed_at": "2026-08-24T00:01:00.000Z",
            "provenance": "codex:user-confirmation",
        }

        response = engine.run(
            task_id="task-authority-resume",
            requested_path="/tmp/authority-repository",
            user_request="/init",
            authority_grant=grant,
        )

        self.assertEqual(response["report"]["payload"]["outcome"], "ready")
        snapshot = store.load("task-authority-resume")
        persisted_request = next(
            artifact
            for artifact in snapshot.artifacts
            if artifact["artifact_type"] == "task_request"
        )
        self.assertEqual(persisted_request, original_request)
        authority = next(
            artifact
            for artifact in snapshot.artifacts
            if artifact["artifact_type"] == "evidence_record"
            and artifact["payload"]["kind"] == "authority"
        )
        self.assertEqual(
            authority["payload"]["authority_grant"],
            {"granted_by": "user", **grant},
        )
        authority_ref = next(
            reference
            for reference in response["report"]["payload"]["artifact_refs"]["evidence"]
            if reference["artifact_id"] == authority["artifact_id"]
        )
        resume_transition = next(
            artifact
            for artifact in snapshot.artifacts
            if artifact["artifact_type"] == "transition"
            and artifact["payload"]["from"] == "Blocked"
        )
        self.assertIn(authority_ref, resume_transition["payload"]["input_refs"])

    def test_authority_grant_cannot_bypass_a_non_authority_blocker(self):
        class NonGitInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/not-a-repository",
                    root=None,
                    requested_scope=None,
                    kind="non_git",
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, NonGitInspector())
        engine.run(
            task_id="task-non-authority-blocker",
            requested_path="/tmp/not-a-repository",
            user_request="/init",
        )
        before = store.load("task-non-authority-blocker")

        with self.assertRaises(StoreError) as raised:
            engine.run(
                task_id="task-non-authority-blocker",
                requested_path="/tmp/not-a-repository",
                user_request="/init",
                authority_grant={
                    "capabilities": ["repository.read"],
                    "scopes": ["repository:v1:."],
                    "confirmed_at": "2026-08-24T00:01:00.000Z",
                    "provenance": "codex:user-confirmation",
                },
            )

        self.assertEqual(raised.exception.code, "init.authority_not_applicable")
        self.assertEqual(store.load("task-non-authority-blocker"), before)

    def test_authority_grant_requires_read_capability_and_exact_repository_scope(self):
        class ScopedAuthorityInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/scoped-repository/subdirectory",
                    root="/tmp/scoped-repository",
                    requested_scope="subdirectory",
                    kind="worktree",
                )

            def inspect(self, classification):
                raise RepositoryError(
                    "blocked.repository.read_authority",
                    "Repository inspection requires additional read authority.",
                    retryable=False,
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, ScopedAuthorityInspector())
        engine.run(
            task_id="task-scoped-authority",
            requested_path="/tmp/scoped-repository/subdirectory",
            user_request="/init",
        )
        before = store.load("task-scoped-authority")
        invalid_bounds = [
            {
                "capabilities": ["repository.metadata"],
                "scopes": ["repository:v1:subdirectory"],
            },
            {
                "capabilities": ["repository.read"],
                "scopes": ["repository:v1:."],
            },
            {
                "capabilities": ["repository.read", "production.write"],
                "scopes": ["repository:v1:subdirectory"],
            },
            {
                "capabilities": ["repository.read"],
                "scopes": ["repository:v1:subdirectory", "repository:v1:."],
            },
        ]

        for bounds in invalid_bounds:
            with self.subTest(bounds=bounds):
                with self.assertRaises(StoreError) as raised:
                    engine.run(
                        task_id="task-scoped-authority",
                        requested_path="/tmp/scoped-repository/subdirectory",
                        user_request="/init",
                        authority_grant={
                            **bounds,
                            "confirmed_at": "2026-08-24T00:01:00.000Z",
                            "provenance": "codex:user-confirmation",
                        },
                    )

                self.assertEqual(
                    raised.exception.code, "init.authority_bounds_mismatch"
                )
                self.assertEqual(store.load("task-scoped-authority"), before)

    def test_authority_scope_round_trips_case_spaces_and_unicode(self):
        class ScopedAuthorityInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/scoped-repository/Sub Directory/中文%:A",
                    root="/tmp/scoped-repository",
                    requested_scope="Sub Directory/中文%:A",
                    kind="worktree",
                )

            def inspect(self, classification):
                raise RepositoryError(
                    "blocked.repository.read_authority",
                    "Repository inspection requires additional read authority.",
                    retryable=False,
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, ScopedAuthorityInspector())
        task_id = "task-canonical-authority-scope"
        requested_path = "/tmp/scoped-repository/Sub Directory/中文%:A"
        engine.run(task_id, requested_path, "/init")
        expected_scope = (
            "repository:v1:Sub%20Directory/"
            "%E4%B8%AD%E6%96%87%25%3AA"
        )

        response = engine.run(
            task_id=task_id,
            requested_path=requested_path,
            user_request="/init",
            authority_grant={
                "capabilities": ["repository.read"],
                "scopes": [expected_scope],
                "confirmed_at": "2026-08-24T00:01:00.000Z",
                "provenance": "codex:user-confirmation",
            },
        )

        self.assertEqual(response["report"]["payload"]["outcome"], "blocked")
        snapshot = store.load(task_id)
        authority = next(
            artifact
            for artifact in snapshot.artifacts
            if artifact["artifact_type"] == "evidence_record"
            and artifact["payload"]["kind"] == "authority"
        )
        self.assertEqual(
            authority["payload"]["authority_grant"]["scopes"],
            [expected_scope],
        )

    def test_retry_continues_from_committed_resume_checkpoint_after_interruption(self):
        class RecoveringInspector:
            ready = False

            def classify(self, requested_path):
                if not self.ready:
                    return RepositoryClassification(
                        requested_path="/tmp/recovery-repository",
                        root=None,
                        requested_scope=None,
                        kind="non_git",
                    )
                return RepositoryClassification(
                    requested_path="/tmp/recovery-repository",
                    root="/tmp/recovery-repository",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                revision = RepositoryRevision(
                    head_state="attached",
                    head="d" * 40,
                    branch="main",
                    dirty=False,
                    worktree_digest=None,
                )
                return RepositoryInspection(
                    repository={
                        "requested_path": classification.requested_path,
                        "root": classification.root,
                        "requested_scope": None,
                        "revision": revision.to_dict(),
                        "superproject": None,
                    },
                    revision=revision,
                    sources=[
                        {
                            "id": "repository:.",
                            "path": ".",
                            "kind": "repository",
                            "hash": "sha256:" + "e" * 64,
                        }
                    ],
                    findings={
                        "entry_docs": [],
                        "repository_instructions": [],
                        "verification_commands": [],
                    },
                    gaps=[
                        "entry_docs",
                        "repository_instructions",
                        "verification_commands",
                    ],
                    started_at="2026-08-24T00:00:00.000Z",
                    duration_ms=1,
                )

        inspector = RecoveringInspector()
        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, inspector)
        first = engine.run(
            "task-resume-checkpoint", "/tmp/recovery-repository", "/init"
        )
        blocked = store.load("task-resume-checkpoint")
        resume_receipt = store.commit(
            TaskCommit(
                task_id="task-resume-checkpoint",
                expected_store_version=blocked.store_version,
                operation_id="simulated-resume-before-crash",
                artifact_drafts=[],
                transition_intent=TransitionIntent(
                    local_ref="resume",
                    to_state="Intake",
                    reason="simulated resolved blocker",
                    input_refs=[blocked.latest_report_ref],
                    output_ref=None,
                    actor="stage module",
                ),
            )
        )
        inspector.ready = True

        recovered = engine.run(
            "task-resume-checkpoint", "/tmp/recovery-repository", "/init"
        )

        self.assertEqual(recovered["report"]["payload"]["outcome"], "ready")
        self.assertEqual(
            recovered["report"]["payload"]["supersedes"], first["report_ref"]
        )
        snapshot = store.load("task-resume-checkpoint")
        final_transition = [
            artifact
            for artifact in snapshot.artifacts
            if artifact["artifact_type"] == "transition"
        ][-1]
        self.assertIn(
            resume_receipt.transition_ref.to_dict(),
            final_transition["payload"]["input_refs"],
        )

    def test_interrupted_resume_that_is_blocked_again_creates_a_new_attempt_report(self):
        class StillNonGitInspector:
            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/reblocked-repository",
                    root=None,
                    requested_scope=None,
                    kind="non_git",
                )

        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, StillNonGitInspector())
        first = engine.run(
            "task-reblocked-checkpoint", "/tmp/reblocked-repository", "/init"
        )
        blocked = store.load("task-reblocked-checkpoint")
        resume_receipt = store.commit(
            TaskCommit(
                task_id="task-reblocked-checkpoint",
                expected_store_version=blocked.store_version,
                operation_id="simulated-reblocked-resume-before-crash",
                artifact_drafts=[],
                transition_intent=TransitionIntent(
                    local_ref="resume",
                    to_state="Intake",
                    reason="simulated blocker resolution",
                    input_refs=[blocked.latest_report_ref],
                    output_ref=None,
                    actor="stage module",
                ),
            )
        )

        retried = engine.run(
            "task-reblocked-checkpoint", "/tmp/reblocked-repository", "/init"
        )

        self.assertEqual(retried["report"]["payload"]["outcome"], "blocked")
        self.assertEqual(
            retried["report"]["payload"]["supersedes"], first["report_ref"]
        )
        snapshot = store.load("task-reblocked-checkpoint")
        self.assertEqual(snapshot.lifecycle_state, "Blocked")
        transitions = [
            artifact
            for artifact in snapshot.artifacts
            if artifact["artifact_type"] == "transition"
        ]
        self.assertEqual(len(transitions), 3)
        self.assertEqual(transitions[-1]["payload"]["from"], "Intake")
        self.assertEqual(transitions[-1]["payload"]["to"], "Blocked")
        self.assertIn(
            resume_receipt.transition_ref.to_dict(),
            transitions[-1]["payload"]["input_refs"],
        )

    def test_interrupted_authority_resume_keeps_authority_on_recovered_ready_report(self):
        class AuthorityInspector:
            allowed = False

            def classify(self, requested_path):
                return RepositoryClassification(
                    requested_path="/tmp/interrupted-authority",
                    root="/tmp/interrupted-authority",
                    requested_scope=None,
                    kind="worktree",
                )

            def inspect(self, classification):
                if not self.allowed:
                    raise RepositoryError(
                        "blocked.repository.read_authority",
                        "Repository inspection requires additional read authority.",
                        retryable=False,
                    )
                revision = RepositoryRevision(
                    head_state="attached",
                    head="f" * 40,
                    branch="main",
                    dirty=False,
                    worktree_digest=None,
                )
                return RepositoryInspection(
                    repository={
                        "requested_path": classification.requested_path,
                        "root": classification.root,
                        "requested_scope": None,
                        "revision": revision.to_dict(),
                        "superproject": None,
                    },
                    revision=revision,
                    sources=[],
                    findings={
                        "entry_docs": [],
                        "repository_instructions": [],
                        "verification_commands": [],
                    },
                    gaps=[
                        "entry_docs",
                        "repository_instructions",
                        "verification_commands",
                    ],
                    started_at="2026-08-24T00:02:00.000Z",
                    duration_ms=1,
                )

        inspector = AuthorityInspector()
        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, inspector)
        engine.run(
            "task-interrupted-authority", "/tmp/interrupted-authority", "/init"
        )
        blocked = store.load("task-interrupted-authority")
        grant = {
            "granted_by": "user",
            "capabilities": ["repository.read"],
            "scopes": ["repository:v1:."],
            "confirmed_at": "2026-08-24T00:01:00.000Z",
            "provenance": "codex:user-confirmation",
        }
        resume_receipt = store.commit(
            TaskCommit(
                task_id="task-interrupted-authority",
                expected_store_version=blocked.store_version,
                operation_id="simulated-authority-resume-before-crash",
                artifact_drafts=[
                    ArtifactDraft(
                        local_ref="authority",
                        artifact_type="evidence_record",
                        payload=EvidenceRecord(
                            observed_revision=None,
                            started_at=grant["confirmed_at"],
                            duration_ms=0,
                            summary="User granted bounded repository read authority.",
                            kind="authority",
                            invocation="user-confirmed authority grant",
                            authority_grant=grant,
                        ).to_payload(),
                    )
                ],
                transition_intent=TransitionIntent(
                    local_ref="resume",
                    to_state="Intake",
                    reason="init.blocker_resolved",
                    input_refs=[blocked.latest_report_ref, LocalRef("authority")],
                    output_ref=None,
                    actor="stage module",
                ),
            )
        )
        inspector.allowed = True

        recovered = engine.run(
            "task-interrupted-authority", "/tmp/interrupted-authority", "/init"
        )

        self.assertEqual(recovered["report"]["payload"]["outcome"], "ready")
        self.assertIn(
            resume_receipt.materialized_refs["authority"].to_dict(),
            recovered["report"]["payload"]["artifact_refs"]["evidence"],
        )


if __name__ == "__main__":
    unittest.main()
