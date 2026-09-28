import os
import stat
import sys
from pathlib import Path
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit.persistence import (
    MAX_MANIFEST_BYTES,
    FilesystemAtomicPersistence,
)


class FilesystemAtomicPersistenceSecurityTests(unittest.TestCase):
    def test_commit_rejects_tasks_symlink_without_writing_through_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            target_repository = root / "target-repository"
            state_root.mkdir()
            target_repository.mkdir()
            (state_root / "tasks").symlink_to(
                target_repository, target_is_directory=True
            )
            persistence = FilesystemAtomicPersistence(state_root)

            with self.assertRaises(OSError):
                persistence.compare_and_commit("task-one", None, b"new state")

            self.assertEqual(list(target_repository.iterdir()), [])

    def test_load_rejects_tasks_symlink_without_reading_through_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            target_repository = root / "target-repository"
            state_root.mkdir()
            target_repository.mkdir()
            (target_repository / "task-one").mkdir()
            (target_repository / "task-one" / "manifest.json").write_bytes(
                b"repository data"
            )
            (state_root / "tasks").symlink_to(
                target_repository, target_is_directory=True
            )
            persistence = FilesystemAtomicPersistence(state_root)

            with self.assertRaises(OSError):
                persistence.load_bytes("task-one")

    def test_commit_rejects_task_directory_symlink_without_writing_through_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            target_repository = root / "target-repository"
            (state_root / "tasks").mkdir(parents=True)
            target_repository.mkdir()
            (state_root / "tasks" / "task-one").symlink_to(
                target_repository, target_is_directory=True
            )
            persistence = FilesystemAtomicPersistence(state_root)

            with self.assertRaises(OSError):
                persistence.compare_and_commit("task-one", None, b"new state")

            self.assertEqual(list(target_repository.iterdir()), [])

    def test_load_rejects_task_directory_symlink_without_reading_through_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            target_repository = root / "target-repository"
            (state_root / "tasks").mkdir(parents=True)
            target_repository.mkdir()
            (target_repository / "manifest.json").write_bytes(b"repository data")
            (state_root / "tasks" / "task-one").symlink_to(
                target_repository, target_is_directory=True
            )
            persistence = FilesystemAtomicPersistence(state_root)

            with self.assertRaises(OSError):
                persistence.load_bytes("task-one")

    def test_commit_rejects_locks_symlink_without_creating_external_lock(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            target_repository = root / "target-repository"
            state_root.mkdir()
            target_repository.mkdir()
            (state_root / "locks").symlink_to(
                target_repository, target_is_directory=True
            )
            persistence = FilesystemAtomicPersistence(state_root)

            with self.assertRaises(OSError):
                persistence.compare_and_commit("task-one", None, b"new state")

            self.assertEqual(list(target_repository.iterdir()), [])

    def test_commit_rejects_lock_file_symlink(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            external_file = root / "repository-file"
            persistence = FilesystemAtomicPersistence(state_root)
            persistence.compare_and_commit("task-one", None, b"first state")
            lock_path = next((state_root / "locks").iterdir())
            lock_path.unlink()
            external_file.write_bytes(b"repository data")
            lock_path.symlink_to(external_file)

            with self.assertRaises(OSError):
                persistence.compare_and_commit(
                    "task-one", b"first state", b"second state"
                )

            self.assertEqual(external_file.read_bytes(), b"repository data")
            self.assertEqual(persistence.load_bytes("task-one"), b"first state")

    def test_commit_rejects_state_root_symlink_without_writing_through_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            target_repository = root / "target-repository"
            target_repository.mkdir()
            state_root.symlink_to(target_repository, target_is_directory=True)
            persistence = FilesystemAtomicPersistence(state_root)

            with self.assertRaises(OSError):
                persistence.compare_and_commit("task-one", None, b"new state")

            self.assertEqual(list(target_repository.iterdir()), [])

    def test_load_rejects_state_root_symlink_without_reading_through_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state_root = root / "state"
            target_repository = root / "target-repository"
            (target_repository / "tasks" / "task-one").mkdir(parents=True)
            (
                target_repository / "tasks" / "task-one" / "manifest.json"
            ).write_bytes(b"repository data")
            state_root.symlink_to(target_repository, target_is_directory=True)
            persistence = FilesystemAtomicPersistence(state_root)

            with self.assertRaises(OSError):
                persistence.load_bytes("task-one")

    def test_commit_creates_private_directories_and_files_independent_of_umask(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            persistence = FilesystemAtomicPersistence(state_root)
            previous_umask = os.umask(0)
            try:
                persistence.compare_and_commit("task-one", None, b"new state")
            finally:
                os.umask(previous_umask)

            private_directories = [
                state_root,
                state_root / "tasks",
                state_root / "locks",
                state_root / "tasks" / "task-one",
            ]
            private_files = [
                state_root / "tasks" / "task-one" / "manifest.json",
                next((state_root / "locks").iterdir()),
            ]
            for directory in private_directories:
                with self.subTest(path=directory):
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for file_path in private_files:
                with self.subTest(path=file_path):
                    self.assertEqual(stat.S_IMODE(file_path.stat().st_mode), 0o600)

    def test_commit_rejects_nonprivate_preexisting_state_root_without_chmod(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            state_root.mkdir(mode=0o755)
            state_root.chmod(0o755)
            persistence = FilesystemAtomicPersistence(state_root)

            with self.assertRaises(OSError):
                persistence.compare_and_commit("task-one", None, b"new state")

            self.assertEqual(stat.S_IMODE(state_root.stat().st_mode), 0o755)
            self.assertFalse((state_root / "tasks").exists())
            self.assertFalse((state_root / "locks").exists())

    def test_load_rejects_nonprivate_preexisting_state_root_without_chmod(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            state_root.mkdir(mode=0o755)
            state_root.chmod(0o755)
            persistence = FilesystemAtomicPersistence(state_root)

            with self.assertRaises(OSError):
                persistence.load_bytes("task-one")

            self.assertEqual(stat.S_IMODE(state_root.stat().st_mode), 0o755)

    def test_commit_restores_private_permissions_on_existing_child_paths(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            persistence = FilesystemAtomicPersistence(state_root)
            persistence.compare_and_commit("task-one", None, b"first state")
            task_directory = state_root / "tasks" / "task-one"
            manifest_path = task_directory / "manifest.json"
            lock_path = next((state_root / "locks").iterdir())
            directories = [
                state_root / "tasks",
                state_root / "locks",
                task_directory,
            ]
            for directory in directories:
                directory.chmod(0o755)
            manifest_path.chmod(0o644)
            lock_path.chmod(0o644)

            persistence.compare_and_commit(
                "task-one", b"first state", b"second state"
            )

            for directory in directories:
                with self.subTest(path=directory):
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for file_path in (manifest_path, lock_path):
                with self.subTest(path=file_path):
                    self.assertEqual(stat.S_IMODE(file_path.stat().st_mode), 0o600)

    def test_load_rejects_manifest_larger_than_configured_limit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            persistence = FilesystemAtomicPersistence(state_root)
            persistence.compare_and_commit("task-one", None, b"first state")
            manifest_path = state_root / "tasks" / "task-one" / "manifest.json"
            with manifest_path.open("r+b") as manifest_file:
                manifest_file.truncate(MAX_MANIFEST_BYTES + 1)

            with self.assertRaises(OSError):
                persistence.load_bytes("task-one")

    def test_commit_rejects_manifest_larger_than_configured_limit_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_root = Path(temporary_directory) / "state"
            persistence = FilesystemAtomicPersistence(state_root)

            with self.assertRaises(OSError):
                persistence.compare_and_commit(
                    "task-one", None, b"x" * (MAX_MANIFEST_BYTES + 1)
                )

            self.assertFalse(state_root.exists())


if __name__ == "__main__":
    unittest.main()
