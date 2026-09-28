"""Atomic byte persistence adapters used behind TaskStateStore."""

from __future__ import annotations

try:
    import fcntl
except ImportError:  # The CLI preflight reports unsupported hosts before adapter use.
    fcntl = None
import hashlib
import os
from pathlib import Path
import secrets
import stat
import threading
import time
from typing import Dict, Optional


MAX_MANIFEST_BYTES = 16 * 1024 * 1024


class PersistenceConflict(Exception):
    pass


class InMemoryAtomicPersistence:
    def __init__(self):
        self._values: Dict[str, bytes] = {}
        self._lock = threading.Lock()

    def load_bytes(self, task_id: str) -> Optional[bytes]:
        with self._lock:
            return self._values.get(task_id)

    def compare_and_commit(
        self, task_id: str, expected: Optional[bytes], replacement: bytes
    ) -> None:
        if len(replacement) > MAX_MANIFEST_BYTES:
            raise OSError("Task-state manifest exceeds the persistence size limit.")
        with self._lock:
            current = self._values.get(task_id)
            if current != expected:
                raise PersistenceConflict()
            self._values[task_id] = replacement


class FilesystemAtomicPersistence:
    _DIRECTORY_FLAGS = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    _FILE_FLAGS = (
        getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )

    def __init__(self, state_root: Path):
        self.state_root = state_root
        self.tasks_root = state_root / "tasks"
        self.locks_root = state_root / "locks"

    def _task_directory(self, task_id: str) -> Path:
        return self.tasks_root / task_id

    def _manifest_path(self, task_id: str) -> Path:
        return self._task_directory(task_id) / "manifest.json"

    def _lock_path(self, task_id: str) -> Path:
        name = hashlib.sha256(task_id.encode("utf-8")).hexdigest() + ".lock"
        return self.locks_root / name

    def load_bytes(self, task_id: str) -> Optional[bytes]:
        self._validate_task_component(task_id)
        state_descriptor = self._open_state_root(create=False)
        if state_descriptor is None:
            return None
        try:
            tasks_descriptor, _ = self._open_directory_at(
                state_descriptor, "tasks", create=False
            )
            if tasks_descriptor is None:
                return None
            try:
                task_descriptor, _ = self._open_directory_at(
                    tasks_descriptor, task_id, create=False
                )
                if task_descriptor is None:
                    return None
                try:
                    return self._read_manifest(task_descriptor)
                finally:
                    os.close(task_descriptor)
            finally:
                os.close(tasks_descriptor)
        finally:
            os.close(state_descriptor)

    def compare_and_commit(
        self, task_id: str, expected: Optional[bytes], replacement: bytes
    ) -> None:
        if len(replacement) > MAX_MANIFEST_BYTES:
            raise OSError("Task-state manifest exceeds the persistence size limit.")
        if fcntl is None:
            raise OSError("Filesystem task locking is unavailable on this host.")
        self._validate_task_component(task_id)
        state_descriptor = self._open_state_root(create=True)
        if state_descriptor is None:  # pragma: no cover - create=True guarantees it.
            raise OSError("Task-state root could not be created.")
        tasks_descriptor = None
        locks_descriptor = None
        try:
            tasks_descriptor, tasks_created = self._open_directory_at(
                state_descriptor, "tasks", create=True, private=True
            )
            try:
                locks_descriptor, locks_created = self._open_directory_at(
                    state_descriptor, "locks", create=True, private=True
                )
            except Exception:
                if tasks_descriptor is not None:
                    os.close(tasks_descriptor)
                    tasks_descriptor = None
                raise
            if tasks_descriptor is None or locks_descriptor is None:
                if tasks_descriptor is not None:
                    os.close(tasks_descriptor)
                    tasks_descriptor = None
                if locks_descriptor is not None:
                    os.close(locks_descriptor)
                    locks_descriptor = None
                raise OSError("Task-state directories could not be created.")
            try:
                if tasks_created or locks_created:
                    self._fsync_descriptor(state_descriptor)
                lock_descriptor, lock_created = self._open_lock(
                    locks_descriptor, task_id
                )
                try:
                    if lock_created:
                        self._fsync_descriptor(locks_descriptor)
                    lock_file = os.fdopen(lock_descriptor, "rb+")
                    lock_descriptor = -1
                    with lock_file:
                        self._acquire_lock(lock_file.fileno())
                        task_descriptor = None
                        try:
                            task_descriptor, task_created = self._open_directory_at(
                                tasks_descriptor,
                                task_id,
                                create=False,
                                private=True,
                            )
                            if task_descriptor is None:
                                current = None
                            else:
                                current = self._read_manifest(task_descriptor)
                            if current != expected:
                                raise PersistenceConflict()

                            if task_descriptor is None:
                                task_descriptor, task_created = (
                                    self._open_directory_at(
                                        tasks_descriptor,
                                        task_id,
                                        create=True,
                                        private=True,
                                    )
                                )
                                if task_descriptor is None:
                                    raise OSError(
                                        "Task-state directory could not be created."
                                    )
                            if task_created:
                                self._fsync_descriptor(tasks_descriptor)
                            self._replace_manifest(task_descriptor, replacement)
                        finally:
                            if task_descriptor is not None:
                                os.close(task_descriptor)
                finally:
                    if lock_descriptor >= 0:
                        os.close(lock_descriptor)
            finally:
                if tasks_descriptor is not None:
                    os.close(tasks_descriptor)
                if locks_descriptor is not None:
                    os.close(locks_descriptor)
        finally:
            os.close(state_descriptor)

    def _validate_task_component(self, task_id: str) -> None:
        if (
            not task_id
            or task_id in {".", ".."}
            or os.sep in task_id
            or (os.altsep is not None and os.altsep in task_id)
        ):
            raise OSError("Task identifier is not a safe path component.")

    def _open_state_root(self, create: bool) -> Optional[int]:
        created = False
        if create:
            try:
                self.state_root.mkdir(mode=0o700, parents=True, exist_ok=False)
                created = True
            except FileExistsError:
                pass
        try:
            descriptor = os.open(self.state_root, self._DIRECTORY_FLAGS)
        except FileNotFoundError:
            if create:
                raise
            return None
        try:
            if created:
                os.fchmod(descriptor, 0o700)
            metadata = os.fstat(descriptor)
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise OSError(
                    "Task-state root permissions must not allow group or other access."
                )
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def _open_directory_at(
        self, parent_descriptor: int, name: str, create: bool, private: bool = False
    ):
        created = False
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
                created = True
            except FileExistsError:
                pass
        try:
            descriptor = os.open(
                name, self._DIRECTORY_FLAGS, dir_fd=parent_descriptor
            )
        except FileNotFoundError:
            if create:
                raise
            return None, False
        if private:
            os.fchmod(descriptor, 0o700)
        return descriptor, created

    def _read_manifest(self, task_descriptor: int) -> Optional[bytes]:
        try:
            descriptor = os.open(
                "manifest.json",
                os.O_RDONLY | self._FILE_FLAGS,
                dir_fd=task_descriptor,
            )
        except FileNotFoundError:
            return None
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("Task-state manifests must be regular files.")
            if metadata.st_size > MAX_MANIFEST_BYTES:
                raise OSError("Task-state manifest exceeds the supported size limit.")
            with os.fdopen(descriptor, "rb") as manifest_file:
                descriptor = -1
                content = manifest_file.read(MAX_MANIFEST_BYTES + 1)
                if len(content) > MAX_MANIFEST_BYTES:
                    raise OSError(
                        "Task-state manifest exceeds the supported size limit."
                    )
                return content
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _open_lock(self, locks_descriptor: int, task_id: str):
        name = hashlib.sha256(task_id.encode("utf-8")).hexdigest() + ".lock"
        flags = os.O_RDWR | self._FILE_FLAGS
        try:
            descriptor = os.open(
                name,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=locks_descriptor,
            )
            created = True
        except FileExistsError:
            descriptor = os.open(name, flags, dir_fd=locks_descriptor)
            created = False
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise OSError("Task-state locks must be private regular files.")
            os.fchmod(descriptor, 0o600)
            return descriptor, created
        except Exception:
            os.close(descriptor)
            raise

    def _acquire_lock(self, descriptor: int) -> None:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out acquiring the task-state lock.")
                time.sleep(0.05)

    def _replace_manifest(self, task_descriptor: int, replacement: bytes) -> None:
        temporary_name = None
        for _ in range(100):
            candidate = ".manifest-" + secrets.token_hex(16)
            try:
                temporary_descriptor = os.open(
                    candidate,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | self._FILE_FLAGS,
                    0o600,
                    dir_fd=task_descriptor,
                )
                temporary_name = candidate
                break
            except FileExistsError:
                continue
        if temporary_name is None:
            raise OSError("A unique task-state temporary file could not be created.")
        try:
            os.fchmod(temporary_descriptor, 0o600)
            with os.fdopen(temporary_descriptor, "wb") as temporary_file:
                temporary_descriptor = -1
                temporary_file.write(replacement)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(
                temporary_name,
                "manifest.json",
                src_dir_fd=task_descriptor,
                dst_dir_fd=task_descriptor,
            )
            temporary_name = None
            self._fsync_descriptor(task_descriptor)
        finally:
            if temporary_descriptor >= 0:
                os.close(temporary_descriptor)
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=task_descriptor)
                except FileNotFoundError:
                    pass

    def _fsync_descriptor(self, descriptor: int) -> None:
        os.fsync(descriptor)
