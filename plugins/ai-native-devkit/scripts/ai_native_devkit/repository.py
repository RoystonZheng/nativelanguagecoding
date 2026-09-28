"""Bounded, read-only Git and source inspection for S0 `/init`."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import time
from typing import Any, Dict, List, Optional

from .contracts import RepositoryRevision, canonical_json_bytes, sha256_digest, utc_now
from .errors import RepositoryError
from .instruction_comparison import compare_instructions


MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 32 * 1024 * 1024
IO_CHUNK_BYTES = 64 * 1024
GIT_TIMEOUT_SECONDS = 10
ENTRY_DOC_NAMES = ("README.md", "README.rst", "README.txt", "README")
INSTRUCTION_NAMES = ("AGENTS.md", "CLAUDE.md")
REVISION_PATHSPECS = (
    ".",
    ":(top,exclude)handoff",
    ":(top,exclude)handoff/**",
    ":(top,exclude)docs/handoff",
    ":(top,exclude)docs/handoff/**",
)
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
TRUSTED_EXECUTABLE_SEARCH_PATH = os.defpath


@dataclass(frozen=True)
class RepositoryClassification:
    requested_path: str
    root: Optional[str]
    requested_scope: Optional[str]
    kind: str


@dataclass(frozen=True)
class RepositoryInspection:
    repository: Dict[str, Any]
    revision: RepositoryRevision
    sources: List[Dict[str, str]]
    findings: Dict[str, List[str]]
    gaps: List[str]
    started_at: str
    duration_ms: int


class RepositoryInspector:
    def __init__(self, git_executable: Optional[str] = None):
        self._git_executable = self._resolve_git_executable(git_executable)

    def classify(self, requested_path: str) -> RepositoryClassification:
        path = Path(requested_path).expanduser()
        try:
            absolute = path.resolve(strict=False)
        except OSError as error:
            raise RepositoryError(
                "runtime.repository_path_failed",
                "The requested repository path could not be resolved safely.",
                retryable=False,
            ) from error
        if not absolute.exists():
            return RepositoryClassification(str(absolute), None, None, "missing")
        if not absolute.is_dir():
            return RepositoryClassification(
                str(absolute), None, None, "not_directory"
            )
        root_result = self._git(absolute, "rev-parse", "--show-toplevel", check=False)
        if root_result.returncode != 0:
            bare_result = self._git(
                absolute, "rev-parse", "--is-bare-repository", check=False
            )
            kind = "bare" if bare_result.stdout.strip() == "true" else "non_git"
            return RepositoryClassification(str(absolute), None, None, kind)
        root = Path(root_result.stdout.strip()).resolve()
        scope = None if absolute == root else absolute.relative_to(root).as_posix()
        return RepositoryClassification(str(absolute), str(root), scope, "worktree")

    def inspect(
        self, classification: RepositoryClassification, *, instruction_selection=None
    ) -> RepositoryInspection:
        if classification.kind != "worktree" or classification.root is None:
            raise RepositoryError(
                "blocked.repository.unsupported",
                "The requested path is not an eligible Git worktree.",
                retryable=False,
            )
        started_at = utc_now()
        started = time.monotonic()
        root = Path(classification.root)
        revision = self._observe_revision(root)
        sources: List[Dict[str, str]] = [
            {
                "id": "repository:.",
                "path": ".",
                "kind": "repository",
                "hash": sha256_digest(canonical_json_bytes(revision.to_dict())),
            }
        ]
        try:
            entry_docs = self._existing_sources(
                root, ENTRY_DOC_NAMES, "entry_doc", sources
            )
            instructions = self._instruction_sources(
                root, classification.requested_scope, sources, instruction_selection
            )
            verification_commands = self._verification_commands(root, sources)
            gaps = []
            if not entry_docs:
                gaps.append("entry_docs")
            if not instructions:
                gaps.append("repository_instructions")
            if not verification_commands:
                gaps.append("verification_commands")
            superproject = self._superproject(root)
        except RepositoryError as error:
            self._attach_stable_partial_observation(
                error,
                classification,
                root,
                revision,
                sources,
                started_at,
                started,
            )
            raise
        if self._observe_revision(root) != revision:
            raise RepositoryError(
                "blocked.repository.changed_during_inspection",
                "The repository changed while its selected sources were inspected.",
                retryable=True,
            )
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        return RepositoryInspection(
            repository={
                "requested_path": classification.requested_path,
                "root": classification.root,
                "requested_scope": classification.requested_scope,
                "revision": revision.to_dict(),
                "superproject": superproject,
            },
            revision=revision,
            sources=sources,
            findings={
                "entry_docs": entry_docs,
                "repository_instructions": instructions,
                "verification_commands": verification_commands,
            },
            gaps=gaps,
            started_at=started_at,
            duration_ms=duration_ms,
        )

    def _attach_stable_partial_observation(
        self,
        error: RepositoryError,
        classification: RepositoryClassification,
        root: Path,
        revision: RepositoryRevision,
        sources: List[Dict[str, str]],
        started_at: str,
        started: float,
    ) -> None:
        if not error.code.startswith("blocked.repository."):
            return
        try:
            current_revision = self._observe_revision(root)
        except RepositoryError:
            return
        if current_revision != revision:
            return
        entry_docs = [
            source["path"] for source in sources if source["kind"] == "entry_doc"
        ]
        instructions = [
            source["path"]
            for source in sources
            if source["kind"] == "repository_instruction"
        ]
        verification_commands = (
            ["make test"]
            if any(source["kind"] == "verification_source" for source in sources)
            else []
        )
        gaps = ["repository_inspection"]
        if not entry_docs:
            gaps.append("entry_docs")
        if not instructions:
            gaps.append("repository_instructions")
        if not verification_commands:
            gaps.append("verification_commands")
        error.observation = RepositoryInspection(
            repository={
                "requested_path": classification.requested_path,
                "root": classification.root,
                "requested_scope": classification.requested_scope,
                "revision": revision.to_dict(),
                "superproject": None,
            },
            revision=revision,
            sources=list(sources),
            findings={
                "entry_docs": entry_docs,
                "repository_instructions": instructions,
                "verification_commands": verification_commands,
            },
            gaps=gaps,
            started_at=started_at,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    def _observe_revision(self, root: Path) -> RepositoryRevision:
        head_result = self._git(root, "rev-parse", "--verify", "HEAD", check=False)
        if head_result.returncode == 0:
            head = head_result.stdout.strip()
            branch_result = self._git(
                root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False
            )
            if branch_result.returncode == 0:
                head_state = "attached"
                branch = branch_result.stdout.strip()
            else:
                head_state = "detached"
                branch = None
        else:
            head_state = "unborn"
            head = None
            branch = None
        status = self._git(
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
            "--ignore-submodules=untracked",
            "--ignored=no",
            "--",
            *REVISION_PATHSPECS,
        ).stdout
        dirty = bool(status)
        worktree_digest = (
            self._worktree_digest(root, head_state)
            if dirty or head_state == "unborn"
            else None
        )
        revision = RepositoryRevision(
            head_state=head_state,
            head=head,
            branch=branch,
            dirty=dirty,
            worktree_digest=worktree_digest,
        )
        return revision

    def _existing_sources(
        self,
        root: Path,
        names,
        kind: str,
        sources: List[Dict[str, str]],
    ) -> List[str]:
        found = []
        for name in names:
            content = self._read_selected_source(root, name)
            if content is None:
                continue
            found.append(name)
            sources.append(
                {
                    "id": kind + ":" + name,
                    "path": name,
                    "kind": kind,
                    "hash": sha256_digest(content),
                }
            )
        return found

    def _instruction_sources(
        self,
        root: Path,
        requested_scope: Optional[str],
        sources: List[Dict[str, str]],
        selection=None,
    ) -> List[str]:
        relative_paths = list(INSTRUCTION_NAMES)
        if requested_scope:
            parts = Path(requested_scope).parts
            for depth in range(1, len(parts) + 1):
                directory = Path(*parts[:depth])
                for name in INSTRUCTION_NAMES:
                    relative_paths.append((directory / name).as_posix())
        found, content, by_directory = [], {}, {}
        for name in relative_paths:
            raw = self._read_selected_source(root, name)
            if raw is None:
                continue
            source = {
                "id": "repository_instruction:" + name,
                "path": name, "kind": "repository_instruction", "hash": sha256_digest(raw),
            }
            sources.append(source)
            found.append(name)
            try:
                content[name] = raw.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise RepositoryError(
                    "blocked.repository.instruction_encoding",
                    "Repository instructions must be readable UTF-8 Markdown.", retryable=True,
                ) from error
            by_directory.setdefault(Path(name).parent.as_posix(), {})[Path(name).name] = source
        observed_hashes = {
            source["path"]: source["hash"] for source in sources
            if source["kind"] == "repository_instruction"
        }
        stale = selection is not None and selection["source_hashes"] != observed_hashes
        preferred = set(selection["preferred_sources"]) if selection and not stale else set()
        differences, excluded = [], set()
        for directory, pair in by_directory.items():
            if not set(INSTRUCTION_NAMES).issubset(pair):
                continue
            left, right = (pair[name] for name in INSTRUCTION_NAMES)
            changes = compare_instructions(content[left["path"]], content[right["path"]])
            chosen = preferred.intersection({left["path"], right["path"]})
            if chosen:
                excluded.update({left["path"], right["path"]} - chosen)
            elif changes:
                differences.append({
                    "directory": directory,
                    "left": {key: left[key] for key in ("path", "hash")},
                    "right": {key: right[key] for key in ("path", "hash")},
                    "changes": changes,
                })
        if differences or stale:
            raise RepositoryError(
                "blocked.repository.instruction_selection_stale" if stale else "blocked.repository.source_conflict",
                "Instruction files changed after the selected report; review their current differences."
                if stale else "Repository instruction rules differ; review the paired rule ranges and select the authoritative file for this task.",
                retryable=True,
                details={"instruction_differences": differences[:32], "omitted_groups": max(0, len(differences) - 32)},
            )
        return [path for path in found if path not in excluded]

    def _verification_commands(
        self, root: Path, sources: List[Dict[str, str]]
    ) -> List[str]:
        content = self._read_selected_source(root, "Makefile")
        if content is None:
            return []
        text = content.decode("utf-8", "replace")
        if not re.search(r"(?m)^test\s*:", text):
            return []
        sources.append(
            {
                "id": "verification_source:Makefile",
                "path": "Makefile",
                "kind": "verification_source",
                "hash": sha256_digest(content),
            }
        )
        return ["make test"]

    def _read_selected_source(
        self, root: Path, relative_path: str
    ) -> Optional[bytes]:
        parent = self._open_repository_parent(root, relative_path)
        if parent is None:
            return None
        parent_fd, leaf = parent
        file_fd = None
        try:
            try:
                file_fd = os.open(
                    leaf,
                    os.O_RDONLY
                    | os.O_CLOEXEC
                    | os.O_NOFOLLOW
                    | os.O_NONBLOCK,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                return None
            except OSError as error:
                if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise self._source_outside_root_error() from error
                raise self._source_read_error() from error

            metadata = os.fstat(file_fd)
            if stat.S_ISDIR(metadata.st_mode):
                return None
            if not stat.S_ISREG(metadata.st_mode):
                raise self._source_read_error()
            if metadata.st_size > MAX_SOURCE_BYTES:
                raise self._source_too_large_error()

            content = bytearray()
            while True:
                chunk = os.read(file_fd, IO_CHUNK_BYTES)
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_SOURCE_BYTES:
                    raise self._source_too_large_error()
            return bytes(content)
        except OSError as error:
            raise self._source_read_error() from error
        finally:
            if file_fd is not None:
                os.close(file_fd)
            os.close(parent_fd)

    def _open_repository_parent(
        self, root: Path, relative_path: str
    ) -> Optional[tuple]:
        path = Path(relative_path)
        parts = path.parts
        if (
            path.is_absolute()
            or not parts
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise self._source_outside_root_error()
        directory_flags = (
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
        )
        try:
            directory_fd = os.open(root, directory_flags)
        except OSError as error:
            raise self._source_read_error() from error
        try:
            for part in parts[:-1]:
                try:
                    next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                except FileNotFoundError:
                    os.close(directory_fd)
                    return None
                except OSError as error:
                    if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise self._source_outside_root_error() from error
                    raise self._source_read_error() from error
                os.close(directory_fd)
                directory_fd = next_fd
            return directory_fd, parts[-1]
        except Exception:
            os.close(directory_fd)
            raise

    def _source_outside_root_error(self) -> RepositoryError:
        return RepositoryError(
            "blocked.repository.source_outside_root",
            "A selected repository source crosses a symbolic-link boundary and cannot be bounded safely.",
            retryable=False,
        )

    def _source_read_error(self) -> RepositoryError:
        return RepositoryError(
            "blocked.repository.read_failed",
            "A selected repository source could not be read safely.",
            retryable=True,
        )

    def _source_too_large_error(self) -> RepositoryError:
        return RepositoryError(
            "blocked.repository.source_too_large",
            "A selected repository source exceeds the S0 read limit.",
            retryable=False,
        )

    def _worktree_digest(self, root: Path, head_state: str) -> str:
        digest = hashlib.sha256()
        if head_state == "unborn":
            index_diff = self._git_bytes(
                root,
                "diff",
                "--cached",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                "--ignore-submodules=untracked",
                "--full-index",
                "--",
                *REVISION_PATHSPECS,
            ).stdout
        else:
            index_diff = self._git_bytes(
                root,
                "diff",
                "--cached",
                "HEAD",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                "--ignore-submodules=untracked",
                "--full-index",
                "--",
                *REVISION_PATHSPECS,
            ).stdout
        worktree_diff = self._git_bytes(
            root,
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--ignore-submodules=untracked",
            "--full-index",
            "--",
            *REVISION_PATHSPECS,
        ).stdout
        if index_diff:
            digest.update(b"index\0")
            digest.update(index_diff)
            digest.update(b"\0")
        if worktree_diff:
            digest.update(b"worktree\0")
            digest.update(worktree_diff)
            digest.update(b"\0")

        return "sha256:" + digest.hexdigest()

    def _superproject(self, root: Path) -> Optional[Dict[str, Any]]:
        result = self._git(
            root, "rev-parse", "--show-superproject-working-tree", check=False
        )
        value = result.stdout.strip()
        if result.returncode != 0 or not value:
            return None
        super_root = Path(value).resolve()
        revision = self._observe_revision(super_root)
        return {"root": str(super_root), "revision": revision.to_dict()}

    def _git(self, path: Path, *arguments: str, check: bool = True):
        self._ensure_git_outside_inspection_root(path)
        return self._run_git_bounded(
            [
                *self._git_prefix(),
                *self._filter_overrides(path),
                "-C",
                str(path),
                *arguments,
            ],
            check=check,
            text=True,
        )

    def _git_bytes(self, path: Path, *arguments: str, check: bool = True):
        self._ensure_git_outside_inspection_root(path)
        return self._run_git_bounded(
            [
                *self._git_prefix(),
                *self._filter_overrides(path),
                "-C",
                str(path),
                *arguments,
            ],
            check=check,
            text=False,
        )

    def _run_git_bounded(self, command, *, check: bool, text: bool):
        process = None
        selector = selectors.DefaultSelector()
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self._git_environment(),
            )
            if process.stdout is None:
                raise OSError("Git stdout pipe was not created")
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
            chunks = []
            output_size = 0
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, GIT_TIMEOUT_SECONDS)
                events = selector.select(remaining)
                if not events:
                    raise subprocess.TimeoutExpired(command, GIT_TIMEOUT_SECONDS)
                for key, _ in events:
                    chunk = os.read(key.fd, IO_CHUNK_BYTES)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output_size += len(chunk)
                    if output_size > MAX_GIT_OUTPUT_BYTES:
                        raise RepositoryError(
                            "blocked.repository.git_output_too_large",
                            "Git inspection output exceeds the S0 read limit.",
                            retryable=False,
                        )
                    chunks.append(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, GIT_TIMEOUT_SECONDS)
            returncode = process.wait(timeout=remaining)
            if check and returncode != 0:
                raise subprocess.CalledProcessError(returncode, command)
            output_bytes = b"".join(chunks)
            output = (
                output_bytes.decode("utf-8", "replace") if text else output_bytes
            )
            return subprocess.CompletedProcess(
                command,
                returncode,
                stdout=output,
                stderr="" if text else b"",
            )
        except RepositoryError:
            raise
        except (OSError, subprocess.SubprocessError) as error:
            raise RepositoryError(
                "runtime.git_failed",
                "Git inspection could not complete safely.",
                retryable=True,
            ) from error
        finally:
            selector.close()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=1)
                except subprocess.SubprocessError:
                    pass
                if process.stdout is not None:
                    process.stdout.close()

    def _git_prefix(self) -> List[str]:
        return [
            str(self._git_executable),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "diff.external=",
            "-c",
            f"core.attributesFile={os.devnull}",
            "-c",
            f"core.excludesFile={os.devnull}",
            "-c",
            "protocol.allow=never",
            "-c",
            "credential.helper=",
        ]

    def _filter_overrides(self, path: Path) -> List[str]:
        self._ensure_git_outside_inspection_root(path)
        result = self._run_git_bounded(
            [
                *self._git_prefix(),
                "-C",
                str(path),
                "config",
                "--includes",
                "--null",
                "--name-only",
                "--get-regexp",
                r"^filter\..*\.(clean|smudge|process|required)$",
            ],
            check=False,
            text=True,
        )
        if result.returncode not in {0, 1}:
            raise RepositoryError(
                "runtime.git_failed",
                "Git inspection could not complete safely.",
                retryable=True,
            )
        prefixes = {
            name.rsplit(".", 1)[0]
            for name in result.stdout.split("\0")
            if re.fullmatch(
                r"filter\..+\.(?:clean|smudge|process|required)", name
            )
        }
        overrides: List[str] = []
        for prefix in sorted(prefixes):
            for suffix, value in (
                ("clean", ""),
                ("smudge", ""),
                ("process", ""),
                ("required", "false"),
            ):
                overrides.extend(("-c", f"{prefix}.{suffix}={value}"))
        return overrides

    def _git_environment(self) -> Dict[str, str]:
        environment = os.environ.copy()
        environment["PATH"] = TRUSTED_EXECUTABLE_SEARCH_PATH
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        environment["GIT_NO_LAZY_FETCH"] = "1"
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        environment["GIT_CONFIG_GLOBAL"] = os.devnull
        environment["GIT_ATTR_NOSYSTEM"] = "1"
        environment["GIT_PAGER"] = "cat"
        environment.pop("GIT_EXTERNAL_DIFF", None)
        environment.pop("GIT_CONFIG_PARAMETERS", None)
        environment.pop("GIT_CONFIG_COUNT", None)
        for name in (
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR",
            "GIT_DIR",
            "GIT_EXEC_PATH",
            "GIT_INDEX_FILE",
            "GIT_NAMESPACE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_PREFIX",
            "GIT_SHALLOW_FILE",
            "GIT_WORK_TREE",
        ):
            environment.pop(name, None)
        for name in list(environment):
            if name.startswith("GIT_TRACE") or re.fullmatch(
                r"GIT_CONFIG_(?:KEY|VALUE)_\d+", name
            ):
                environment.pop(name)
        return environment

    def _resolve_git_executable(self, configured: Optional[str]) -> Path:
        if configured is None:
            located = shutil.which(
                "git",
                path=TRUSTED_EXECUTABLE_SEARCH_PATH,
            )
            if located is None:
                raise self._git_unavailable_error()
            candidate = Path(located)
        else:
            candidate = Path(configured)
            if not candidate.is_absolute():
                raise self._git_unavailable_error()
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.stat()
        except OSError as error:
            raise self._git_unavailable_error() from error
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not os.access(resolved, os.X_OK)
            or self._path_is_within(resolved, PLUGIN_ROOT)
        ):
            raise self._git_unavailable_error()
        return resolved

    def _ensure_git_outside_inspection_root(self, path: Path) -> None:
        try:
            inspection_root = path.resolve(strict=False)
        except OSError as error:
            raise RepositoryError(
                "runtime.repository_path_failed",
                "The requested repository path could not be resolved safely.",
                retryable=False,
            ) from error
        if self._path_is_within(self._git_executable, inspection_root):
            raise self._git_unavailable_error()

    @staticmethod
    def _path_is_within(path: Path, root: Path) -> bool:
        return path == root or path.is_relative_to(root)

    def _git_unavailable_error(self) -> RepositoryError:
        return RepositoryError(
            "runtime.git_unavailable",
            "A trusted system Git executable is unavailable for repository inspection.",
            retryable=False,
        )
