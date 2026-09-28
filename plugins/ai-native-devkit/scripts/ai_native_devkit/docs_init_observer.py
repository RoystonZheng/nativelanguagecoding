"""Deterministic Init docs inventory and trace projection."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Dict, Optional, Tuple
import uuid

from .execution_trace import repository_digest
from .runtime_trace import RuntimeTrace


STANDARD_PATHS = frozenset(
    {
        "docs/overview/README.md",
        "docs/overview/product.md",
        "docs/overview/domain-model.md",
        "docs/overview/architecture.md",
        "docs/overview/technical-stack.md",
        "docs/overview/implementation-status.md",
        "docs/references/README.md",
        "docs/decisions/README.md",
        "docs/design/README.md",
        "docs/api/README.md",
        "docs/runbooks/README.md",
        "docs/runbooks/rds-schema-change.md",
        "docs/runbooks/rds-data-query.md",
        "docs/runbooks/apollo-config.md",
        "docs/runbooks/kms-secret.md",
        "docs/pitfalls/README.md",
        "docs/superpowers/README.md",
    }
)
MAX_DETAIL_PATHS = 64
MAX_DETAIL_PATH_CHARS = 256
MAX_OBSERVED_FILES = 4096
MAX_OBSERVED_FILE_BYTES = 8 * 1024 * 1024
INIT_EXCLUDED_DOCS_SUBTREES = (
    "docs/superpowers/requirements",
    "docs/superpowers/specs",
    "docs/superpowers/plans",
)


def _hash_file(path: Path) -> str:
    if path.stat().st_size > MAX_OBSERVED_FILE_BYTES:
        raise ValueError("document exceeds the observation size limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _is_excluded_subtree(relative: str, excluded_subtrees: Tuple[str, ...]) -> bool:
    return any(
        relative == subtree or relative.startswith(subtree + "/")
        for subtree in excluded_subtrees
    )


def _inventory(
    repository: Path,
    *,
    excluded_subtrees: Tuple[str, ...] = (),
) -> Tuple[Dict[str, str], list[str]]:
    files: Dict[str, str] = {}
    conflicts = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = repository / name
        if path.is_symlink():
            conflicts.append(name)
        elif path.is_file():
            try:
                files[name] = _hash_file(path)
            except (OSError, ValueError):
                conflicts.append(name)
        elif path.exists():
            conflicts.append(name)

    docs = repository / "docs"
    if docs.is_symlink():
        conflicts.append("docs")
        return files, sorted(conflicts)
    if not docs.exists():
        return files, sorted(conflicts)
    if not docs.is_dir():
        conflicts.append("docs")
        return files, sorted(conflicts)

    for current, directories, filenames in os.walk(docs, followlinks=False):
        current_path = Path(current)
        current_relative = current_path.relative_to(repository).as_posix()
        if _is_excluded_subtree(current_relative, excluded_subtrees):
            directories[:] = []
            continue
        if current_path == docs:
            directories[:] = [name for name in directories if name != "handoff"]
        safe_directories = []
        for name in directories:
            candidate = current_path / name
            relative = candidate.relative_to(repository).as_posix()
            if _is_excluded_subtree(relative, excluded_subtrees):
                continue
            if candidate.is_symlink():
                conflicts.append(relative)
            else:
                safe_directories.append(name)
        directories[:] = safe_directories
        for name in filenames:
            if len(files) >= MAX_OBSERVED_FILES:
                conflicts.append("docs:inventory_limit")
                return dict(sorted(files.items())), sorted(set(conflicts))
            candidate = current_path / name
            relative = candidate.relative_to(repository).as_posix()
            try:
                metadata = candidate.lstat()
            except (OSError, ValueError):
                conflicts.append(relative)
                continue
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                conflicts.append(relative)
                continue
            try:
                files[relative] = _hash_file(candidate)
            except (OSError, ValueError):
                conflicts.append(relative)
    return dict(sorted(files.items())), sorted(set(conflicts))


def _init_inventory(repository: Path) -> Tuple[Dict[str, str], list[str]]:
    return _inventory(
        repository,
        excluded_subtrees=INIT_EXCLUDED_DOCS_SUBTREES,
    )


def _mode(files: Dict[str, str]) -> str:
    if STANDARD_PATHS.issubset(files):
        return "Refresh"
    if files:
        return "Adapt"
    return "Bootstrap"


def _sanitize_init_observation(record: Dict[str, Any]) -> Dict[str, Any]:
    """Remove workflow records from a loaded Init-only observation."""
    sanitized = dict(record)
    files = record.get("files")
    if isinstance(files, dict):
        sanitized_files = {
            path: digest
            for path, digest in files.items()
            if not _is_excluded_subtree(path, INIT_EXCLUDED_DOCS_SUBTREES)
        }
        sanitized["files"] = sanitized_files
        sanitized["mode"] = _mode(sanitized_files)

    conflicts = record.get("conflicts")
    if isinstance(conflicts, list):
        sanitized["conflicts"] = [
            conflict
            for conflict in conflicts
            if not (
                isinstance(conflict, str)
                and _is_excluded_subtree(
                    conflict,
                    INIT_EXCLUDED_DOCS_SUBTREES,
                )
            )
        ]
    return sanitized


def _bounded_paths(paths: list[str]) -> Tuple[list[str], int]:
    unique = sorted(set(paths))
    selected = [path[:MAX_DETAIL_PATH_CHARS] for path in unique[:MAX_DETAIL_PATHS]]
    return selected, max(0, len(unique) - len(selected))


class DocsInitObserver:
    """Persist a private baseline and emit only deterministic docs facts."""

    def __init__(self, state_root: Path, session_id: str, repository: Path):
        self.state_root = state_root
        self.session_id = session_id
        self.repository = repository.expanduser().resolve(strict=False)
        key_source = f"{session_id}\0{self.repository}".encode("utf-8")
        self.key = hashlib.sha256(key_source).hexdigest()
        self.root = state_root / "init-docs-observations"
        self.path = self.root / f"{self.key}.json"
        self.trace = RuntimeTrace(state_root, session_id, str(self.repository))

    @classmethod
    def for_current_session(
        cls, state_root: Path, repository: Path
    ) -> Optional["DocsInitObserver"]:
        session_id = os.environ.get("CODEX_THREAD_ID") or os.environ.get(
            "CODEX_TASK_ID"
        )
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        return cls(state_root, session_id, repository)

    def prepare(self) -> Dict[str, Any]:
        if self.state_root.is_symlink():
            raise OSError("AI Native DevKit state root cannot be a symlink.")
        if not self.state_root.exists():
            self.state_root.mkdir(mode=0o700, parents=True, exist_ok=False)
        metadata = self.state_root.stat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise OSError("AI Native DevKit state root must be a private directory.")
        existing = self._load()
        if existing and existing.get("status") == "active":
            self._ensure_trace(existing)
            return existing

        files, conflicts = _init_inventory(self.repository)
        record = {
            "schema_version": "ai-native-devkit/init-docs-observation/v1",
            "repository": str(self.repository),
            "stage_run_id": str(uuid.uuid4()),
            "mode": _mode(files),
            "files": files,
            "conflicts": conflicts,
            "status": "active",
        }
        self._write(record)
        self._ensure_trace(record)
        return record

    def complete(self, validation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        record = self._load()
        if not record:
            return None
        if record.get("status") == "completed":
            return None
        if record.get("status") == "failed" and validation.get("valid") is True:
            record["stage_run_id"] = str(uuid.uuid4())
            record["status"] = "active"
            self._write(record)
            self._ensure_trace(record)

        before = record.get("files") or {}
        after, current_conflicts = _init_inventory(self.repository)
        recognized, recognized_omitted = _bounded_paths(list(before))
        generated, generated_omitted = _bounded_paths(
            [path for path in after if path not in before]
        )
        overwritten, overwritten_omitted = _bounded_paths(
            [path for path in after if path in before and after[path] != before[path]]
        )
        preserved, preserved_omitted = _bounded_paths(
            [path for path in after if path in before and after[path] == before[path]]
        )
        removed, removed_omitted = _bounded_paths(
            [path for path in before if path not in after]
        )
        validation_conflicts = [
            *(validation.get("missing") or []),
            *(validation.get("brokenLinks") or []),
        ]
        conflicts, conflicts_omitted = _bounded_paths(
            [*(record.get("conflicts") or []), *current_conflicts, *validation_conflicts]
        )
        payload = {
            "phase": "project_docs",
            "mode": record["mode"],
            "outcome": "ready" if validation.get("valid") is True else "invalid",
            "recognized": recognized,
            "generated": generated,
            "overwritten": overwritten,
            "preserved": preserved,
            "removed": removed,
            "conflicts": conflicts,
            "omitted_counts": {
                "recognized": recognized_omitted,
                "generated": generated_omitted,
                "overwritten": overwritten_omitted,
                "preserved": preserved_omitted,
                "removed": removed_omitted,
                "conflicts": conflicts_omitted,
            },
            "validation": {
                "valid": validation.get("valid") is True,
                "missing_count": len(validation.get("missing") or []),
                "broken_links_count": len(validation.get("brokenLinks") or []),
            },
        }
        correlation = {"stage_run_id": record["stage_run_id"]}
        self.trace.emit_once(
            "init.completed",
            stage="init",
            correlation=correlation,
            payload=payload,
        )
        terminal = (
            "workflow.stage.completed"
            if validation.get("valid") is True
            else "workflow.stage.failed"
        )
        self.trace.emit_once(
            terminal,
            stage="init",
            correlation=correlation,
            payload={
                "stage": "init",
                "phase": "project_docs",
                "outcome": payload["outcome"],
            },
        )
        record["status"] = (
            "completed" if validation.get("valid") is True else "failed"
        )
        self._write(record)
        return payload

    def abandon(self) -> None:
        record = self._load()
        if record and record.get("status") == "active":
            record["status"] = "cancelled"
            self._write(record)

    def _ensure_trace(self, record: Dict[str, Any]) -> None:
        self.trace.ensure_workflow_started()
        stage_run_id = self.trace.ensure_stage_started(
            "init",
            stage_run_id=record["stage_run_id"],
            payload={
                "phase": "context_and_project_docs",
                "repository": repository_digest(str(self.repository)),
            },
        )
        if stage_run_id is None:
            return
        record["stage_run_id"] = stage_run_id
        recognized, omitted = _bounded_paths(list((record.get("files") or {}).keys()))
        conflicts, conflicts_omitted = _bounded_paths(record.get("conflicts") or [])
        correlation = {"stage_run_id": stage_run_id}
        self.trace.emit_once(
            "init.mode.selected",
            stage="init",
            correlation=correlation,
            payload={
                "mode": record["mode"],
                "recognized": recognized,
                "conflicts": conflicts,
                "omitted_counts": {
                    "recognized": omitted,
                    "conflicts": conflicts_omitted,
                },
            },
        )
        self._write(record)

    def _load(self) -> Optional[Dict[str, Any]]:
        try:
            metadata = self.path.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) & 0o077
                or metadata.st_size > 4 * 1024 * 1024
            ):
                return None
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if (
            not isinstance(value, dict)
            or value.get("schema_version")
            != "ai-native-devkit/init-docs-observation/v1"
            or value.get("repository") != str(self.repository)
        ):
            return None
        return _sanitize_init_observation(value)

    def _write(self, value: Dict[str, Any]) -> None:
        if self.root.is_symlink():
            raise OSError("Init docs observation root cannot be a symlink.")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = self.root.stat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise OSError("Init docs observation root must be a private directory.")
        temporary = self.root / f".{self.path.name}-{secrets.token_hex(8)}"
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
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
                    raise OSError("Init docs observation write made no progress.")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self.path)
