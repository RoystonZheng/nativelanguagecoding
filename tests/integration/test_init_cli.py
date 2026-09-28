import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts" / "init_cli.py"
SCRIPTS_ROOT = CLI_PATH.parent
SCHEMA_VERSION = "ai-native-devkit/v1alpha1"
READY_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "repository-context" / "ready"
READY_FIXTURE_HEAD = "bf3886c2d60bb7752e67f430069dd3cce2120a72"

sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit.persistence import FilesystemAtomicPersistence
from ai_native_devkit.state_store import TaskStateStore


def run_git(repository, *arguments):
    environment = os.environ.copy()
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    ).stdout.strip()


def create_committed_repository(repository):
    repository.mkdir()
    run_git(repository, "init", "--object-format=sha1", "-b", "main")
    for source in READY_FIXTURE.iterdir():
        if source.is_file():
            (repository / source.name).write_bytes(source.read_bytes())
    run_git(repository, "add", "README.md", "AGENTS.md")
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "AI Native Dev Tests",
            "GIT_AUTHOR_EMAIL": "tests@example.invalid",
            "GIT_COMMITTER_NAME": "AI Native Dev Tests",
            "GIT_COMMITTER_EMAIL": "tests@example.invalid",
            "GIT_AUTHOR_DATE": "2026-08-24T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-08-24T00:00:00Z",
        }
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "fixture"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    if run_git(repository, "rev-parse", "HEAD") != READY_FIXTURE_HEAD:
        raise AssertionError("Frozen ready fixture produced an unexpected Git revision.")


class InitCliTests(unittest.TestCase):
    def test_new_task_returns_persisted_ready_report_without_modifying_repository(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository = temporary_root / "target"
            state_root = temporary_root / "state"
            create_committed_repository(repository)
            canonical_repository = repository.resolve()
            head = run_git(repository, "rev-parse", "HEAD")
            before_status = run_git(repository, "status", "--porcelain=v1", "--untracked-files=all")

            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-ready-fixture",
                "repository": {"path": str(repository)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout)
            report = response["report"]
            report_payload = report["payload"]
            canonical_report = json.dumps(
                report,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

            self.assertEqual(response["schema_version"], SCHEMA_VERSION)
            self.assertEqual(response["kind"], "report")
            self.assertEqual(report["artifact_type"], "init_report")
            self.assertEqual(report["task_id"], "task-ready-fixture")
            self.assertEqual(report_payload["outcome"], "ready")
            self.assertEqual(
                report_payload["repository"],
                {
                    "requested_path": str(canonical_repository),
                    "root": str(canonical_repository),
                    "requested_scope": None,
                    "revision": {
                        "head_state": "attached",
                        "head": head,
                        "branch": "main",
                        "dirty": False,
                        "worktree_digest": None,
                    },
                    "superproject": None,
                },
            )
            self.assertEqual(report_payload["findings"]["entry_docs"], ["README.md"])
            self.assertEqual(
                report_payload["findings"]["repository_instructions"],
                ["AGENTS.md"],
            )
            self.assertEqual(report_payload["findings"]["verification_commands"], [])
            self.assertEqual(report_payload["gaps"], ["verification_commands"])
            self.assertIsNone(report_payload["blocker"])
            self.assertEqual(
                report_payload["sources"],
                [
                    {
                        "id": "repository:.",
                        "path": ".",
                        "kind": "repository",
                        "hash": "sha256:"
                        + hashlib.sha256(
                            json.dumps(
                                {
                                    "head_state": "attached",
                                    "head": head,
                                    "branch": "main",
                                    "dirty": False,
                                    "worktree_digest": None,
                                },
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest(),
                    },
                    {
                        "id": "entry_doc:README.md",
                        "path": "README.md",
                        "kind": "entry_doc",
                        "hash": "sha256:cee5438c38e54a2d71f6b4c7c61d6796711f8f3e5cd5c6b718648503bf6f69fe",
                    },
                    {
                        "id": "repository_instruction:AGENTS.md",
                        "path": "AGENTS.md",
                        "kind": "repository_instruction",
                        "hash": "sha256:b14ecd6806dc4dcb7a79218bb9a3f6a61b0c6015bb9a68bee7a2420234f76c57",
                    },
                ],
            )
            self.assertEqual(
                response["report_ref"],
                {
                    "artifact_id": report["artifact_id"],
                    "artifact_type": "init_report",
                    "digest": "sha256:" + hashlib.sha256(canonical_report).hexdigest(),
                },
            )
            self.assertEqual(
                run_git(repository, "status", "--porcelain=v1", "--untracked-files=all"),
                before_status,
            )
            self.assertFalse((repository / ".scratch").exists())
            snapshot = TaskStateStore(
                FilesystemAtomicPersistence(state_root)
            ).load("task-ready-fixture")
            self.assertEqual(snapshot.lifecycle_state, "ContextReady")
            self.assertIsNone(snapshot.resume_state)
            self.assertEqual(snapshot.latest_report_ref.to_dict(), response["report_ref"])
            self.assertEqual(
                [artifact["artifact_type"] for artifact in snapshot.artifacts],
                ["task_request", "evidence_record", "transition", "init_report"],
            )
            persisted_bytes = b"".join(
                path.read_bytes() for path in state_root.rglob("*") if path.is_file()
            )
            self.assertNotIn(b"# Fixture project", persisted_bytes)
            self.assertNotIn(b"# Repository instructions", persisted_bytes)

    def test_non_git_directory_returns_blocked_report_without_initializing_git(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "plain-directory"
            state_root = temporary_root / "state"
            target.mkdir()
            sentinel = target / "keep.txt"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            before = {
                path.relative_to(target).as_posix(): path.read_bytes()
                for path in target.rglob("*")
                if path.is_file()
            }
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-non-git-fixture",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout)
            payload = response["report"]["payload"]
            self.assertEqual(response["kind"], "report")
            self.assertEqual(payload["outcome"], "blocked")
            self.assertEqual(
                payload["repository"],
                {
                    "requested_path": str(target.resolve()),
                    "root": None,
                    "requested_scope": None,
                    "revision": None,
                    "superproject": None,
                },
            )
            self.assertEqual(payload["sources"], [])
            self.assertEqual(
                payload["findings"],
                {
                    "entry_docs": [],
                    "repository_instructions": [],
                    "verification_commands": [],
                },
            )
            self.assertEqual(payload["gaps"], ["eligible_repository"])
            self.assertEqual(
                payload["blocker"],
                {
                    "code": "blocked.repository.not_git",
                    "message": "The requested path is not a Git worktree.",
                    "resume_when": "Select or initialize a non-bare Git worktree, then retry this task.",
                },
            )
            snapshot = TaskStateStore(
                FilesystemAtomicPersistence(state_root)
            ).load("task-non-git-fixture")
            self.assertEqual(snapshot.lifecycle_state, "Blocked")
            self.assertEqual(snapshot.resume_state, "Intake")
            self.assertEqual(
                [artifact["artifact_type"] for artifact in snapshot.artifacts],
                ["task_request", "evidence_record", "transition", "init_report"],
            )
            self.assertFalse((target / ".git").exists())
            self.assertEqual(
                {
                    path.relative_to(target).as_posix(): path.read_bytes()
                    for path in target.rglob("*")
                    if path.is_file()
                },
                before,
            )

    def test_bare_repository_returns_no_worktree_blocker_without_creating_checkout(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "bare.git"
            state_root = temporary_root / "state"
            subprocess.run(
                ["git", "init", "--bare", str(target)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            before_paths = sorted(
                path.relative_to(target).as_posix() for path in target.rglob("*")
            )
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-bare-fixture",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout)
            payload = response["report"]["payload"]
            self.assertEqual(response["kind"], "report")
            self.assertEqual(payload["outcome"], "blocked")
            self.assertEqual(
                payload["blocker"],
                {
                    "code": "blocked.repository.no_worktree",
                    "message": "The requested Git repository has no worktree.",
                    "resume_when": "Select or create a non-bare Git worktree, then retry this task.",
                },
            )
            snapshot = TaskStateStore(
                FilesystemAtomicPersistence(state_root)
            ).load("task-bare-fixture")
            self.assertEqual(snapshot.lifecycle_state, "Blocked")
            self.assertEqual(snapshot.resume_state, "Intake")
            self.assertEqual(
                sorted(path.relative_to(target).as_posix() for path in target.rglob("*")),
                before_paths,
            )

    def test_unborn_worktree_is_ready_with_required_worktree_digest(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "unborn"
            state_root = temporary_root / "state"
            target.mkdir()
            run_git(target, "init", "-b", "main")
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-unborn-fixture",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)["report"]["payload"]
            self.assertEqual(payload["outcome"], "ready")
            self.assertEqual(
                payload["repository"]["revision"],
                {
                    "head_state": "unborn",
                    "head": None,
                    "branch": None,
                    "dirty": False,
                    "worktree_digest": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                },
            )
            self.assertEqual(
                payload["gaps"],
                [
                    "entry_docs",
                    "repository_instructions",
                    "verification_commands",
                ],
            )
            snapshot = TaskStateStore(
                FilesystemAtomicPersistence(state_root)
            ).load("task-unborn-fixture")
            self.assertEqual(snapshot.lifecycle_state, "ContextReady")
            self.assertEqual(run_git(target, "status", "--porcelain=v1"), "")

    def test_dirty_digest_excludes_untracked_files_until_added_to_index(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "dirty"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            (target / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
            run_git(target, "add", ".gitignore")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(target),
                    "-c",
                    "user.name=AI Native DevKit Tests",
                    "-c",
                    "user.email=tests@example.invalid",
                    "commit",
                    "-m",
                    "ignore fixture",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            untracked = target / "new file.txt"
            ignored = target / "ignored.log"
            untracked.write_text("first\n", encoding="utf-8")
            ignored.write_text("ignored one\n", encoding="utf-8")
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            def inspect(task_id):
                completed = subprocess.run(
                    [sys.executable, str(CLI_PATH)],
                    input=json.dumps(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "operation": "init",
                            "task_id": task_id,
                            "repository": {"path": str(target)},
                            "user_request": "/init",
                        }
                    ),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=environment,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                revision = json.loads(completed.stdout)["report"]["payload"][
                    "repository"
                ]["revision"]
                return revision["worktree_digest"]

            first_digest = inspect("task-dirty-one")
            ignored.write_text("ignored two\n", encoding="utf-8")
            ignored_only_digest = inspect("task-dirty-two")
            untracked.write_text("second\n", encoding="utf-8")
            changed_untracked_digest = inspect("task-dirty-three")

            self.assertEqual(first_digest, ignored_only_digest)
            self.assertIsNone(first_digest)
            self.assertEqual(first_digest, changed_untracked_digest)
            run_git(target, "add", "new file.txt")
            staged_digest = inspect("task-dirty-four")
            self.assertIsNotNone(staged_digest)
            untracked.write_text("third\n", encoding="utf-8")
            changed_tracked_digest = inspect("task-dirty-five")
            self.assertNotEqual(staged_digest, changed_tracked_digest)

    def test_matching_ready_task_requires_reuse_or_new_choice_without_writing_state(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "ready-choice"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-ready-choice",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            first = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            store = TaskStateStore(FilesystemAtomicPersistence(state_root))
            before = store.load("task-ready-choice")

            repeated = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(
                json.loads(repeated.stdout),
                {
                    "schema_version": SCHEMA_VERSION,
                    "kind": "choice_required",
                    "reason": "init.ready_current",
                    "choices": ["reuse", "new"],
                },
            )
            self.assertEqual(store.load("task-ready-choice"), before)

            reuse_request = dict(request)
            reuse_request["choice"] = "reuse"
            reused = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(reuse_request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(reused.returncode, 0, reused.stderr)
            self.assertEqual(json.loads(reused.stdout), json.loads(first.stdout))
            self.assertEqual(store.load("task-ready-choice"), before)

    def test_stale_ready_task_allows_only_new_or_cancel_without_mutating_old_report(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "stale-choice"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-stale-choice",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            first = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            store = TaskStateStore(FilesystemAtomicPersistence(state_root))
            before = store.load("task-stale-choice")
            (target / "README.md").write_text("# Changed fixture\n", encoding="utf-8")

            repeated = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(
                json.loads(repeated.stdout),
                {
                    "schema_version": SCHEMA_VERSION,
                    "kind": "choice_required",
                    "reason": "init.ready_stale",
                    "choices": ["new", "cancel"],
                },
            )
            invalid_reuse = dict(request)
            invalid_reuse["choice"] = "reuse"
            rejected = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(invalid_reuse),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(json.loads(rejected.stdout)["kind"], "runtime_error")
            self.assertEqual(store.load("task-stale-choice"), before)

            cancel_request = dict(request)
            cancel_request["choice"] = "cancel"
            cancelled = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(cancel_request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
            self.assertEqual(
                json.loads(cancelled.stdout),
                {
                    "schema_version": SCHEMA_VERSION,
                    "kind": "choice_required",
                    "reason": "init.cancelled",
                    "choices": [],
                },
            )
            self.assertEqual(store.load("task-stale-choice"), before)

    def test_new_choice_creates_distinct_task_and_leaves_ready_task_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "new-choice"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-original-ready",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            first = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            store = TaskStateStore(FilesystemAtomicPersistence(state_root))
            original = store.load("task-original-ready")
            new_request = dict(request)
            new_request["choice"] = "new"

            created = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(new_request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(created.returncode, 0, created.stderr)
            response = json.loads(created.stdout)
            new_task_id = response["report"]["task_id"]
            self.assertEqual(response["kind"], "report")
            self.assertEqual(response["report"]["payload"]["outcome"], "ready")
            self.assertNotEqual(new_task_id, "task-original-ready")
            self.assertEqual(store.load("task-original-ready"), original)
            self.assertEqual(store.load(new_task_id).lifecycle_state, "ContextReady")

    def test_blocked_retry_supersedes_report_without_blocked_self_transition(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "still-not-git"
            state_root = temporary_root / "state"
            target.mkdir()
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-blocked-retry",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            first = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            first_response = json.loads(first.stdout)
            first_report = first_response["report"]

            retried = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(retried.returncode, 0, retried.stderr)
            retry_response = json.loads(retried.stdout)
            retry_report = retry_response["report"]
            self.assertEqual(retry_report["payload"]["outcome"], "blocked")
            self.assertNotEqual(retry_report["artifact_id"], first_report["artifact_id"])
            self.assertEqual(
                retry_report["payload"]["supersedes"], first_response["report_ref"]
            )
            self.assertEqual(
                retry_report["payload"]["artifact_refs"]["transition"],
                first_report["payload"]["artifact_refs"]["transition"],
            )
            snapshot = TaskStateStore(
                FilesystemAtomicPersistence(state_root)
            ).load("task-blocked-retry")
            self.assertEqual(snapshot.lifecycle_state, "Blocked")
            self.assertEqual(snapshot.resume_state, "Intake")
            self.assertEqual(
                [artifact["artifact_type"] for artifact in snapshot.artifacts],
                [
                    "task_request",
                    "evidence_record",
                    "transition",
                    "init_report",
                    "evidence_record",
                    "init_report",
                ],
            )
            persisted_first_report = next(
                artifact
                for artifact in snapshot.artifacts
                if artifact["artifact_id"] == first_report["artifact_id"]
            )
            self.assertEqual(persisted_first_report, first_report)

    def test_resolved_blocker_resumes_intake_and_produces_ready_superseding_report(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "becomes-git"
            state_root = temporary_root / "state"
            target.mkdir()
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-blocker-resolved",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            first = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            first_response = json.loads(first.stdout)
            run_git(target, "init", "-b", "main")
            (target / "README.md").write_text("# Resolved fixture\n", encoding="utf-8")
            (target / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            run_git(target, "add", "README.md", "AGENTS.md")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(target),
                    "-c",
                    "user.name=AI Native DevKit Tests",
                    "-c",
                    "user.email=tests@example.invalid",
                    "commit",
                    "-m",
                    "resolved fixture",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            retried = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(retried.returncode, 0, retried.stderr)
            retry_response = json.loads(retried.stdout)
            retry_report = retry_response["report"]
            self.assertEqual(retry_report["payload"]["outcome"], "ready")
            self.assertEqual(
                retry_report["payload"]["supersedes"], first_response["report_ref"]
            )
            snapshot = TaskStateStore(
                FilesystemAtomicPersistence(state_root)
            ).load("task-blocker-resolved")
            self.assertEqual(snapshot.lifecycle_state, "ContextReady")
            self.assertIsNone(snapshot.resume_state)
            transitions = [
                artifact["payload"]
                for artifact in snapshot.artifacts
                if artifact["artifact_type"] == "transition"
            ]
            self.assertEqual(
                [(item["from"], item["to"]) for item in transitions],
                [
                    ("Intake", "Blocked"),
                    ("Blocked", "Intake"),
                    ("Intake", "ContextReady"),
                ],
            )
            persisted_first = next(
                artifact
                for artifact in snapshot.artifacts
                if artifact["artifact_id"]
                == first_response["report"]["artifact_id"]
            )
            self.assertEqual(persisted_first, first_response["report"])

    def test_detached_descendant_invocation_retains_scope_and_normalizes_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "detached"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            descendant = target / "src" / "module"
            descendant.mkdir(parents=True)
            (descendant / "tracked.txt").write_text("fixture\n", encoding="utf-8")
            run_git(target, "add", "src/module/tracked.txt")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(target),
                    "-c",
                    "user.name=AI Native DevKit Tests",
                    "-c",
                    "user.email=tests@example.invalid",
                    "commit",
                    "-m",
                    "descendant fixture",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            head = run_git(target, "rev-parse", "HEAD")
            run_git(target, "checkout", "--detach", head)
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-detached-descendant",
                "repository": {"path": str(descendant)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            repository = json.loads(completed.stdout)["report"]["payload"][
                "repository"
            ]
            self.assertEqual(repository["requested_path"], str(descendant.resolve()))
            self.assertEqual(repository["root"], str(target.resolve()))
            self.assertEqual(repository["requested_scope"], "src/module")
            self.assertEqual(
                repository["revision"],
                {
                    "head_state": "detached",
                    "head": head,
                    "branch": None,
                    "dirty": False,
                    "worktree_digest": None,
                },
            )

    def test_selected_submodule_is_its_own_target_with_superproject_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            superproject = temporary_root / "superproject"
            submodule_source = temporary_root / "submodule-source"
            state_root = temporary_root / "state"
            create_committed_repository(superproject)
            create_committed_repository(submodule_source)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "protocol.file.allow=always",
                    "-C",
                    str(superproject),
                    "submodule",
                    "add",
                    str(submodule_source),
                    "modules/child",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(superproject),
                    "-c",
                    "user.name=AI Native DevKit Tests",
                    "-c",
                    "user.email=tests@example.invalid",
                    "commit",
                    "-am",
                    "submodule fixture",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            child = superproject / "modules" / "child"
            super_head = run_git(superproject, "rev-parse", "HEAD")
            child_head = run_git(child, "rev-parse", "HEAD")
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-submodule",
                "repository": {"path": str(child)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            repository = json.loads(completed.stdout)["report"]["payload"][
                "repository"
            ]
            self.assertEqual(repository["root"], str(child.resolve()))
            self.assertEqual(repository["revision"]["head"], child_head)
            self.assertEqual(
                repository["superproject"],
                {
                    "root": str(superproject.resolve()),
                    "revision": {
                        "head_state": "attached",
                        "head": super_head,
                        "branch": "main",
                        "dirty": False,
                        "worktree_digest": None,
                    },
                },
            )
            run_git(superproject, "submodule", "deinit", "-f", "modules/child")
            before_child_paths = sorted(
                path.relative_to(child).as_posix() for path in child.rglob("*")
            )
            parent_request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-superproject-only",
                "repository": {"path": str(superproject)},
                "user_request": "/init",
            }
            parent_completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(parent_request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(parent_completed.returncode, 0, parent_completed.stderr)
            self.assertEqual(
                sorted(path.relative_to(child).as_posix() for path in child.rglob("*")),
                before_child_paths,
            )
            self.assertFalse((child / ".git").exists())

    def test_corrupt_persisted_state_returns_runtime_error_instead_of_report(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "corrupt-state"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-corrupt-state",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            first = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            manifest_path = (
                state_root / "tasks" / "task-corrupt-state" / "manifest.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            operation = next(iter(manifest["operations"].values()))
            operation["receipt"]["store_version"] = "v1:tampered"
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )

            repeated = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertNotEqual(repeated.returncode, 0)
            response = json.loads(repeated.stdout)
            self.assertEqual(response["kind"], "runtime_error")
            self.assertEqual(response["code"], "state.corrupt")
            self.assertFalse(response["retryable"])
            self.assertNotIn(str(state_root), response["message"])

    def test_ready_freshness_includes_selected_source_hashes_beyond_git_revision(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "source-freshness"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            run_git(target, "rm", "AGENTS.md")
            (target / ".gitignore").write_text("AGENTS.md\n", encoding="utf-8")
            run_git(target, "add", ".gitignore")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(target),
                    "-c",
                    "user.name=AI Native DevKit Tests",
                    "-c",
                    "user.email=tests@example.invalid",
                    "commit",
                    "-m",
                    "ignored instruction fixture",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            instruction = target / "AGENTS.md"
            instruction.write_text("# First ignored instruction\n", encoding="utf-8")
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-source-freshness",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            first = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(run_git(target, "status", "--porcelain=v1"), "")
            instruction.write_text("# Changed ignored instruction\n", encoding="utf-8")

            repeated = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(
                json.loads(repeated.stdout),
                {
                    "schema_version": SCHEMA_VERSION,
                    "kind": "choice_required",
                    "reason": "init.ready_stale",
                    "choices": ["new", "cancel"],
                },
            )

    def test_state_root_inside_target_is_rejected_before_any_repository_write(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "unsafe-state-root"
            create_committed_repository(target)
            before_status = run_git(target, "status", "--porcelain=v1")
            unsafe_state_root = target / ".ai-native-devkit-state"
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-unsafe-state-root",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(unsafe_state_root)

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertNotEqual(completed.returncode, 0)
            response = json.loads(completed.stdout)
            self.assertEqual(response["kind"], "runtime_error")
            self.assertEqual(response["code"], "persistence.unsafe_state_root")
            self.assertFalse(unsafe_state_root.exists())
            self.assertEqual(
                run_git(target, "status", "--porcelain=v1"), before_status
            )

    def test_state_root_that_contains_target_is_rejected_before_permission_changes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "target"
            create_committed_repository(target)
            before_mode = temporary_root.stat().st_mode
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(temporary_root)

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "operation": "init",
                        "task_id": "unsafe-ancestor-state-root",
                        "repository": {"path": str(target)},
                        "user_request": "/init",
                    }
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertNotEqual(completed.returncode, 0)
            response = json.loads(completed.stdout)
            self.assertEqual(response["code"], "persistence.unsafe_state_root")
            self.assertEqual(temporary_root.stat().st_mode, before_mode)
            self.assertFalse((temporary_root / "tasks").exists())
            self.assertFalse((temporary_root / "locks").exists())
            self.assertEqual(run_git(target, "status", "--porcelain=v1"), "")

    def test_default_state_root_symlinked_into_target_is_rejected_without_target_writes(self):
        for linked_ancestor in (".codex", ".codex/state"):
            with self.subTest(linked_ancestor=linked_ancestor):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary_root = Path(temporary_directory)
                    target = temporary_root / "target"
                    fake_home = temporary_root / "home"
                    create_committed_repository(target)
                    fake_home.mkdir()
                    if linked_ancestor == ".codex":
                        (fake_home / ".codex").symlink_to(
                            target,
                            target_is_directory=True,
                        )
                    else:
                        (fake_home / ".codex").mkdir()
                        (fake_home / ".codex" / "state").symlink_to(
                            target,
                            target_is_directory=True,
                        )
                    before = {
                        path.relative_to(target).as_posix(): path.read_bytes()
                        for path in target.rglob("*")
                        if path.is_file()
                    }
                    environment = os.environ.copy()
                    environment.pop("AI_NATIVE_DEVKIT_STATE_ROOT", None)
                    environment["HOME"] = str(fake_home)

                    completed = subprocess.run(
                        [sys.executable, str(CLI_PATH)],
                        input=json.dumps(
                            {
                                "schema_version": SCHEMA_VERSION,
                                "operation": "init",
                                "task_id": "unsafe-default-state-root",
                                "repository": {"path": str(target)},
                                "user_request": "/init",
                            }
                        ),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=environment,
                    )

                    self.assertNotEqual(completed.returncode, 0)
                    response = json.loads(completed.stdout)
                    self.assertEqual(response["kind"], "runtime_error")
                    self.assertEqual(
                        response["code"],
                        "persistence.unsafe_state_root",
                    )
                    after = {
                        path.relative_to(target).as_posix(): path.read_bytes()
                        for path in target.rglob("*")
                        if path.is_file()
                    }
                    self.assertEqual(after, before)
                    self.assertEqual(
                        run_git(target, "status", "--porcelain=v1"),
                        "",
                    )

    def test_repeated_source_conflict_preserves_stable_partial_findings(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "conflicting-instructions"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            (target / "AGENTS.md").write_text("# Instructions\nAlways run tests.\n", encoding="utf-8")
            (target / "CLAUDE.md").write_text(
                "# Instructions\nNever run tests.\n",
                encoding="utf-8",
            )
            before_status = run_git(
                target,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            )
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-source-conflict-history",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            results = [
                subprocess.run(
                    [sys.executable, str(CLI_PATH)],
                    input=json.dumps(request),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=environment,
                )
                for _ in range(2)
            ]

            self.assertEqual([result.returncode for result in results], [0, 0])
            responses = [json.loads(result.stdout) for result in results]
            first_payload = responses[0]["report"]["payload"]
            retry_payload = responses[1]["report"]["payload"]
            self.assertEqual(first_payload["outcome"], "blocked")
            self.assertEqual(
                first_payload["blocker"]["code"],
                "blocked.repository.source_conflict",
            )
            self.assertIsNotNone(first_payload["repository"]["revision"])
            self.assertEqual(
                [source["path"] for source in first_payload["sources"]],
                [".", "README.md", "AGENTS.md", "CLAUDE.md"],
            )
            self.assertEqual(
                first_payload["findings"],
                {
                    "entry_docs": ["README.md"],
                    "repository_instructions": ["AGENTS.md", "CLAUDE.md"],
                    "verification_commands": [],
                },
            )
            for field in ("repository", "sources", "findings", "gaps", "blocker"):
                self.assertEqual(retry_payload[field], first_payload[field])
            self.assertEqual(retry_payload["supersedes"], responses[0]["report_ref"])

            snapshot = TaskStateStore(
                FilesystemAtomicPersistence(state_root)
            ).load("task-source-conflict-history")
            transitions = [
                artifact
                for artifact in snapshot.artifacts
                if artifact["artifact_type"] == "transition"
            ]
            self.assertEqual(len(transitions), 1)
            retry_evidence_id = retry_payload["artifact_refs"]["evidence"][-1][
                "artifact_id"
            ]
            retry_evidence = next(
                artifact
                for artifact in snapshot.artifacts
                if artifact["artifact_id"] == retry_evidence_id
            )
            self.assertEqual(
                retry_evidence["payload"]["observed_revision"],
                retry_payload["repository"]["revision"],
            )
            self.assertEqual(
                run_git(
                    target,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ),
                before_status,
            )

    def test_descendant_scope_collects_hierarchical_repository_instructions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "hierarchical-instructions"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            descendant = target / "src" / "module"
            descendant.mkdir(parents=True)
            (target / "src" / "AGENTS.md").write_text(
                "# Source instructions\n", encoding="utf-8"
            )
            (descendant / "AGENTS.md").write_text(
                "# Module instructions\n", encoding="utf-8"
            )
            run_git(target, "add", "src/AGENTS.md", "src/module/AGENTS.md")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(target),
                    "-c",
                    "user.name=AI Native DevKit Tests",
                    "-c",
                    "user.email=tests@example.invalid",
                    "commit",
                    "-m",
                    "hierarchical instructions",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-hierarchical-instructions",
                "repository": {"path": str(descendant)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            findings = json.loads(completed.stdout)["report"]["payload"]["findings"]
            self.assertEqual(
                findings["repository_instructions"],
                ["AGENTS.md", "src/AGENTS.md", "src/module/AGENTS.md"],
            )

    def test_make_test_target_is_reported_as_sourced_verification_command(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "verification-source"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            makefile_content = ".PHONY: test\ntest:\n\t@echo ok\n"
            (target / "Makefile").write_text(makefile_content, encoding="utf-8")
            run_git(target, "add", "Makefile")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(target),
                    "-c",
                    "user.name=AI Native DevKit Tests",
                    "-c",
                    "user.email=tests@example.invalid",
                    "commit",
                    "-m",
                    "verification source",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-verification-source",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)["report"]["payload"]
            self.assertEqual(payload["findings"]["verification_commands"], ["make test"])
            self.assertNotIn("verification_commands", payload["gaps"])
            self.assertIn(
                {
                    "id": "verification_source:Makefile",
                    "path": "Makefile",
                    "kind": "verification_source",
                    "hash": "sha256:"
                    + hashlib.sha256(makefile_content.encode("utf-8")).hexdigest(),
                },
                payload["sources"],
            )

    def test_explicit_task_id_overrides_caller_identity_and_caller_identity_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "task-identity"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            environment["CODEX_THREAD_ID"] = "caller-thread-identity"
            caller_request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }

            caller_result = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(caller_request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(caller_result.returncode, 0, caller_result.stderr)
            self.assertEqual(
                json.loads(caller_result.stdout)["report"]["task_id"],
                "caller-thread-identity",
            )
            repeated = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(caller_request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(json.loads(repeated.stdout)["kind"], "choice_required")

            explicit_request = dict(caller_request)
            explicit_request["task_id"] = "explicit-workflow-task"
            explicit_result = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(explicit_request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(explicit_result.returncode, 0, explicit_result.stderr)
            self.assertEqual(
                json.loads(explicit_result.stdout)["report"]["task_id"],
                "explicit-workflow-task",
            )

    def test_implicit_caller_identity_creates_a_new_task_for_an_explicitly_different_repository(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            first_target = temporary_root / "first-target"
            second_target = temporary_root / "second-target"
            state_root = temporary_root / "state"
            create_committed_repository(first_target)
            create_committed_repository(second_target)
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            environment["CODEX_THREAD_ID"] = "shared-caller-identity"

            def initialize(repository):
                return subprocess.run(
                    [sys.executable, str(CLI_PATH)],
                    input=json.dumps(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "operation": "init",
                            "repository": {"path": str(repository)},
                            "user_request": "Initialize the explicitly selected repository",
                        }
                    ),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=environment,
                )

            first_result = initialize(first_target)
            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            first_response = json.loads(first_result.stdout)
            first_task_id = first_response["report"]["task_id"]
            store = TaskStateStore(FilesystemAtomicPersistence(state_root))
            original_task_before = store.load(first_task_id)
            second_result = initialize(second_target)

            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            second_response = json.loads(second_result.stdout)
            self.assertEqual(first_response["kind"], "report")
            self.assertEqual(second_response["kind"], "report")
            second_task_id = second_response["report"]["task_id"]
            self.assertEqual(first_task_id, "shared-caller-identity")
            self.assertNotEqual(second_task_id, first_task_id)
            self.assertEqual(
                second_response["report"]["payload"]["repository"]["root"],
                str(second_target.resolve()),
            )

            self.assertEqual(store.load(first_task_id), original_task_before)
            self.assertEqual(store.load(second_task_id).lifecycle_state, "ContextReady")

    def test_cross_target_fallback_never_applies_to_explicit_followups(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            first_target = temporary_root / "followup-first-target"
            second_target = temporary_root / "followup-second-target"
            state_root = temporary_root / "state"
            create_committed_repository(first_target)
            create_committed_repository(second_target)
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            environment["CODEX_THREAD_ID"] = "followup-caller-identity"
            base_request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "repository": {"path": str(first_target)},
                "user_request": "Initialize the selected repository",
            }
            initialized = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(base_request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            store = TaskStateStore(FilesystemAtomicPersistence(state_root))
            before = store.load("followup-caller-identity")

            cases = {
                "explicit-task-id": {"task_id": "followup-caller-identity"},
                "choice": {"choice": "new"},
                "authority": {
                    "authority_grant": {
                        "capabilities": ["repository.read"],
                        "scopes": ["repository:v1:."],
                        "confirmed_at": "2026-08-25T01:00:00.000Z",
                        "provenance": "test:user-confirmation",
                    }
                },
            }
            for name, followup in cases.items():
                request = {
                    **base_request,
                    "repository": {"path": str(second_target)},
                    **followup,
                }
                with self.subTest(name=name):
                    completed = subprocess.run(
                        [sys.executable, str(CLI_PATH)],
                        input=json.dumps(request),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=environment,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    response = json.loads(completed.stdout)
                    self.assertEqual(response["code"], "init.task_target_mismatch")
                    self.assertEqual(store.load("followup-caller-identity"), before)

    def test_repository_path_never_selects_recent_task_when_identity_is_absent(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "identity-absent"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            environment.pop("CODEX_THREAD_ID", None)
            environment.pop("CODEX_TASK_ID", None)
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }

            results = [
                subprocess.run(
                    [sys.executable, str(CLI_PATH)],
                    input=json.dumps(request),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=environment,
                )
                for _ in range(2)
            ]

            self.assertEqual([result.returncode for result in results], [0, 0])
            responses = [json.loads(result.stdout) for result in results]
            self.assertEqual([response["kind"] for response in responses], ["report", "report"])
            task_ids = [response["report"]["task_id"] for response in responses]
            self.assertNotEqual(task_ids[0], task_ids[1])
            store = TaskStateStore(FilesystemAtomicPersistence(state_root))
            self.assertEqual(store.load(task_ids[0]).lifecycle_state, "ContextReady")
            self.assertEqual(store.load(task_ids[1]).lifecycle_state, "ContextReady")

    def test_missing_target_returns_resumable_repository_blocker(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "not-created-yet"
            state_root = temporary_root / "state"
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-missing-target",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)["report"]["payload"]
            self.assertEqual(payload["outcome"], "blocked")
            self.assertEqual(
                payload["blocker"],
                {
                    "code": "blocked.repository.not_found",
                    "message": "The requested repository path does not exist.",
                    "resume_when": "Create or select a non-bare Git worktree at the requested path, then retry this task.",
                },
            )
            snapshot = TaskStateStore(
                FilesystemAtomicPersistence(state_root)
            ).load("task-missing-target")
            self.assertEqual(snapshot.lifecycle_state, "Blocked")

    def test_target_cwd_and_relative_path_cannot_replace_git_executable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            target = temporary_root / "target"
            state_root = temporary_root / "state"
            create_committed_repository(target)
            marker = temporary_root / "target-git-ran"
            fake_git = target / "git"
            fake_git.write_text(
                "#!/bin/sh\n"
                f"touch {str(marker)!r}\n"
                "exit 99\n",
                encoding="utf-8",
            )
            fake_git.chmod(0o700)
            request = {
                "schema_version": SCHEMA_VERSION,
                "operation": "init",
                "task_id": "task-untrusted-path-git",
                "repository": {"path": str(target)},
                "user_request": "/init",
            }
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
            environment["PATH"] = ".:/usr/bin:/bin"

            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                cwd=target,
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

            response = json.loads(completed.stdout)
            self.assertFalse(marker.exists())
            if response["kind"] == "runtime_error":
                self.assertEqual(response["code"], "runtime.git_unavailable")
            else:
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(
                    response["report"]["payload"]["repository"]["root"],
                    str(target.resolve()),
                )


if __name__ == "__main__":
    unittest.main()
