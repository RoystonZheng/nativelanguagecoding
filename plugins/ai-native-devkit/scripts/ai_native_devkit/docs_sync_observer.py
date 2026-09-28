"""Private before/after inventory for automatic Docs Sync facts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Dict, Optional

from .docs_init_observer import _bounded_paths, _inventory


class DocsSyncObserver:
    """Persist content hashes privately and return only changed document paths."""

    def __init__(
        self,
        state_root: Path,
        session_id: str,
        repository: Path,
        stage_run_id: str,
    ):
        self.state_root = state_root.expanduser().absolute()
        self.session_id = session_id
        self.repository = repository.expanduser().resolve(strict=False)
        self.stage_run_id = stage_run_id
        key_source = (
            f"{session_id}\0{self.repository}\0{stage_run_id}".encode("utf-8")
        )
        self.key = hashlib.sha256(key_source).hexdigest()
        self.root = self.state_root / "docs-sync-observations"
        self.path = self.root / f"{self.key}.json"

    def prepare(self) -> None:
        existing = self._load()
        if existing is not None:
            return
        files, conflicts = _inventory(self.repository)
        self._write(
            {
                "schema_version": "ai-native-devkit/docs-sync-observation/v1",
                "session_id": self.session_id,
                "repository": str(self.repository),
                "stage_run_id": self.stage_run_id,
                "files": files,
                "conflicts": conflicts,
                "status": "active",
            }
        )

    def complete(self) -> Dict[str, Any]:
        record = self._load()
        if record is None:
            raise OSError("Docs Sync observation baseline is missing.")
        if record.get("status") == "completed":
            result = record.get("result")
            if isinstance(result, dict):
                return result
            raise OSError("Docs Sync observation result is invalid.")

        before = record.get("files")
        if not isinstance(before, dict):
            raise OSError("Docs Sync observation baseline is invalid.")
        after, current_conflicts = _inventory(self.repository)
        created = [path for path in after if path not in before]
        modified = [
            path for path in after if path in before and after[path] != before[path]
        ]
        removed = [path for path in before if path not in after]
        applied, omitted = _bounded_paths([*created, *modified, *removed])
        conflicts, conflicts_omitted = _bounded_paths(
            [*(record.get("conflicts") or []), *current_conflicts]
        )
        result = {
            "appliedChanges": applied,
            "appliedChangesCount": len(set([*created, *modified, *removed])),
            "appliedChangesOmittedCount": omitted,
            "createdCount": len(created),
            "modifiedCount": len(modified),
            "removedCount": len(removed),
            "observationConflicts": conflicts,
            "observationConflictsOmittedCount": conflicts_omitted,
            "fullCapture": not conflicts and conflicts_omitted == 0,
        }
        record["status"] = "completed"
        record["result"] = result
        self._write(record)
        return result

    def _load(self) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        metadata = self.path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError("Docs Sync observation must be a regular file.")
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("session_id") != self.session_id
            or value.get("repository") != str(self.repository)
            or value.get("stage_run_id") != self.stage_run_id
        ):
            raise OSError("Docs Sync observation identity is invalid.")
        return value

    def _write(self, value: Dict[str, Any]) -> None:
        if self.state_root.is_symlink():
            raise OSError("AI Native DevKit state root cannot be a symlink.")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        temporary = self.root / f".{self.path.name}-{secrets.token_hex(8)}"
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("Docs Sync observation write made no progress.")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
