"""Safe creation and Git commit of exact clarified-requirement documents."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
import fcntl
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import secrets
import shutil
import signal
import stat
import subprocess
import time
import unicodedata
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .contracts import RequirementDocRef
from .errors import RequirementDocumentError
from .execution_trace import ExecutionTraceStore
from .requirement_approval import RequirementApprovalGate


MAX_REQUIREMENT_DOCUMENT_BYTES = 256 * 1024
MAX_REQUIREMENT_SOURCES = 64
MAX_SOURCE_SNAPSHOT_BYTES = 64 * 1024 * 1024
SOURCE_SNAPSHOT_TIMEOUT_SECONDS = 5.0

SOURCE_LINE = re.compile(
    r"^- (Repository|External|仓库|外部): `([^`]+)` (?:at|版本) `([^`]+)` — (\S(?:.*\S)?)$"
)
DOCUMENT_LANGUAGES = frozenset({"zh-CN", "en"})


@dataclass(frozen=True)
class RequirementSource:
    kind: str
    locator: str
    version: str
    supports: str

    @classmethod
    def from_dict(cls, value: Any) -> "RequirementSource":
        fields = {"kind", "locator", "version", "supports"}
        if not isinstance(value, dict) or set(value) != fields:
            raise RequirementDocumentError(
                "requirements.source_invalid", "Requirement source is invalid."
            )
        return _validated_source(cls(**{field: value[field] for field in fields}))

    def to_dict(self) -> Dict[str, str]:
        return {
            "kind": self.kind, "locator": self.locator,
            "version": self.version, "supports": self.supports,
        }

def _source_token(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "`" in value
        or len(value.splitlines()) != 1
        or any(
            unicodedata.category(character) in {"Cc", "Zl", "Zp"}
            for character in value
        )
    ):
        raise RequirementDocumentError(
            "requirements.source_invalid", f"Source {field_name} is invalid."
        )
    return value

def _validated_external_locator(value: str) -> str:
    value = _source_token(value, "locator")
    if len(value.encode("utf-8")) > 2048:
        raise RequirementDocumentError(
            "requirements.source_invalid", "External source locator is too long."
        )
    if value.startswith(("https://", "resource://")):
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
        except ValueError as error:
            raise RequirementDocumentError(
                "requirements.source_invalid", "External source locator is invalid."
            ) from error
        https = (
            parsed.scheme == "https"
            and hostname is not None
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
        resource = (
            parsed.scheme == "resource"
            and bool(parsed.netloc)
            and parsed.path not in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )
        if not (https or resource):
            raise RequirementDocumentError(
                "requirements.source_invalid",
                "External source URL or resource URI is invalid.",
            )
    elif "://" in value or re.fullmatch(r"[\w][\w.:/@+\-]{0,2047}", value) is None:
        raise RequirementDocumentError(
            "requirements.source_invalid", "Opaque resource ID is invalid."
        )
    return value

def _validated_source(source: RequirementSource) -> RequirementSource:
    if source.kind == "repository":
        locator = _source_token(source.locator, "locator")
        path = PurePosixPath(locator)
        if path.is_absolute() or path.as_posix() != locator or ".." in path.parts:
            raise RequirementDocumentError(
                "requirements.source_invalid", "Repository source path is invalid."
            )
        if not isinstance(source.version, str) or not re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source.version
        ):
            raise RequirementDocumentError(
                "requirements.source_invalid", "Repository source revision is invalid."
            )
    elif source.kind == "external":
        _validated_external_locator(source.locator)
        _source_token(source.version, "version")
    else:
        raise RequirementDocumentError(
            "requirements.source_invalid", "Requirement source kind is invalid."
        )
    _source_token(source.supports, "supports")
    return source

def _render_document(
    title: str,
    clarified_requirements: str,
    sources: Sequence[RequirementSource],
    document_language: str = "zh-CN",
) -> bytes:
    if not isinstance(document_language, str) or document_language not in DOCUMENT_LANGUAGES:
        raise RequirementDocumentError(
            "requirements.document_language_invalid", "Document language must be zh-CN or en."
        )
    if isinstance(sources, (str, bytes)):
        raise RequirementDocumentError(
            "requirements.source_invalid", "Sources must be a bounded sequence."
        )
    try:
        source_count = len(sources)
    except TypeError as error:
        raise RequirementDocumentError(
            "requirements.source_invalid", "Sources must be a bounded sequence."
        ) from error
    if source_count > MAX_REQUIREMENT_SOURCES:
        raise RequirementDocumentError(
            "requirements.source_invalid", "At most 64 sources may be recorded."
        )
    title = " ".join(title.split())
    requirements = clarified_requirements.strip()
    if not title or not requirements or re.search(r"(?m)^#{1,6}\s", requirements):
        raise RequirementDocumentError(
            "requirements.document_invalid",
            "Requirements need a title and prose without additional headings.",
        )
    chinese = document_language == "zh-CN"
    requirements_heading = "已澄清的需求" if chinese else "Clarified Requirements"
    sources_heading = "来源" if chinese else "Sources"
    lines = [f"# {title}", "", f"## {requirements_heading}", "", requirements]
    if sources:
        lines.extend(["", f"## {sources_heading}", ""])
        labels = {"repository": "仓库", "external": "外部"} if chinese else {
            "repository": "Repository", "external": "External",
        }
        version_label = "版本" if chinese else "at"
        for source in map(_validated_source, sources):
            label = labels[source.kind]
            lines.append(
                f"- {label}: `{source.locator}` {version_label} `{source.version}` — {source.supports}"
            )
    rendered = ("\n".join(lines) + "\n").encode("utf-8")
    if len(rendered) > MAX_REQUIREMENT_DOCUMENT_BYTES:
        raise RequirementDocumentError(
            "requirements.document_too_large", "Requirements document is too large."
        )
    return rendered

def _parse_requirement_document(markdown: str) -> List[RequirementSource]:
    if not markdown.endswith("\n"):
        raise RequirementDocumentError(
            "requirements.document_invalid", "Requirements document is malformed."
        )
    body = markdown[:-1]
    # Existing approved English blobs remain valid without rewriting their identity.
    parts = re.split(r"\n\n## (?:Sources|来源)\n\n", body)
    if len(parts) > 2:
        raise RequirementDocumentError(
            "requirements.document_invalid", "Requirements document is malformed."
        )
    main = re.fullmatch(
        r"# ([^\n]+)\n\n## (?:Clarified Requirements|已澄清的需求)\n\n(.+)",
        parts[0], flags=re.DOTALL,
    )
    if main is None or main.group(1) != main.group(1).strip():
        raise RequirementDocumentError(
            "requirements.document_invalid", "Requirements document is malformed."
        )
    requirements = main.group(2)
    if requirements != requirements.strip() or re.search(
        r"(?m)^#{1,6}\s", requirements
    ):
        raise RequirementDocumentError(
            "requirements.document_invalid", "Requirements document is malformed."
        )
    if len(parts) == 1:
        return []
    source_lines = parts[1].splitlines()
    if len(source_lines) > MAX_REQUIREMENT_SOURCES:
        raise RequirementDocumentError(
            "requirements.source_invalid", "At most 64 sources may be recorded."
        )
    sources = []
    for line in source_lines:
        match = SOURCE_LINE.fullmatch(line)
        if match is None:
            raise RequirementDocumentError(
                "requirements.source_invalid", "Requirement source is malformed."
            )
        sources.append(_validated_source(RequirementSource(
            kind={"Repository": "repository", "External": "external",
                  "仓库": "repository", "外部": "external"}[match.group(1)],
            locator=match.group(2),
            version=match.group(3), supports=match.group(4),
        )))
    if not sources:
        raise RequirementDocumentError(
            "requirements.source_invalid", "Sources section is empty."
        )
    return sources
_GIT_ENV_KEYS = {
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_EXEC_PATH", "GIT_NAMESPACE", "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE",
    "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS",
    "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS",
    "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS",
}
MAX_GIT_CAPTURE_BYTES = 1024 * 1024
MAX_REPOSITORY_PROJECTION_BYTES = 64 * 1024 * 1024

@dataclass(frozen=True)
class _GitResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_exceeded: bool = False
    started: bool = True

def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

def _git_result(
    root: Path, *arguments: str, input_bytes: Optional[bytes] = None,
    timeout: float = 30, output_limit: int = MAX_GIT_CAPTURE_BYTES,
) -> _GitResult:
    candidate = shutil.which("git", path=os.defpath)
    if candidate is None:
        raise RequirementDocumentError(
            "requirements.repository_unsupported", "Git is unavailable."
        )
    try:
        executable = Path(candidate).resolve(strict=True)
    except OSError as error:
        raise RequirementDocumentError(
            "requirements.repository_unsupported", "Git is unavailable."
        ) from error
    environment = os.environ.copy()
    for key in list(environment):
        if key in _GIT_ENV_KEYS or key.startswith(
            ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
        ):
            environment.pop(key)
    # Exact requirement identities are raw object identities. Do not let
    # replace refs or legacy grafts reinterpret a fixed commit OID.
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_GRAFT_FILE"] = os.devnull
    environment["LC_ALL"] = "C"
    environment.setdefault("PATH", os.defpath)
    process = None
    try:
        process = subprocess.Popen(
            [str(executable), *arguments], cwd=root, env=environment,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        if input_bytes is not None:
            assert process.stdin is not None
            try:
                process.stdin.write(input_bytes)
            except BrokenPipeError:
                pass
            finally:
                process.stdin.close()
        streams = {process.stdout: bytearray(), process.stderr: bytearray()}
        selector = selectors.DefaultSelector()
        for stream in streams:
            assert stream is not None
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        timed_out = False
        output_exceeded = False
        terminated = False
        draining = False
        drain_deadline = None
        while selector.get_map():
            now = time.monotonic()
            remaining = deadline - now
            if not draining and process.poll() is not None:
                # A detached hook child may retain inherited pipes after Git exits.
                draining = True
                drain_deadline = now + 1.0
            if remaining <= 0 and not terminated and process.poll() is None:
                timed_out = True
                _kill_process_group(process)
                terminated = True
                draining = True
                drain_deadline = now + 1.0
            if draining and drain_deadline is not None and now >= drain_deadline:
                for key in list(selector.get_map().values()):
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                break
            wait_for = (
                min(max(drain_deadline - now, 0.0), 0.05)
                if draining and drain_deadline is not None
                else min(max(remaining, 0.0), 0.05)
            )
            for key, _ in selector.select(wait_for):
                try:
                    chunk = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                used = sum(len(value) for value in streams.values())
                room = max(0, output_limit - used)
                streams[key.fileobj].extend(chunk[:room])
                if len(chunk) > room:
                    output_exceeded = True
                    if process.poll() is None and not terminated:
                        _kill_process_group(process)
                        terminated = True
                    if not draining:
                        draining = True
                        drain_deadline = time.monotonic() + 1.0
        selector.close()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            process.wait(timeout=1.0)
        return _GitResult(
            process.returncode,
            bytes(streams[process.stdout]),
            bytes(streams[process.stderr]),
            timed_out,
            output_exceeded,
            True,
        )
    except OSError as error:
        started = process is not None
        if started and process.poll() is None:
            _kill_process_group(process)
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        return _GitResult(
            process.returncode if started and process.returncode is not None else 127,
            b"", str(error).encode("utf-8", "replace")[:1000],
            timed_out=started, output_exceeded=False, started=started,
        )

def _git(
    root: Path, *arguments: str, input_bytes: Optional[bytes] = None,
    timeout: float = 30, output_limit: int = MAX_GIT_CAPTURE_BYTES,
) -> bytes:
    result = _git_result(
        root, *arguments, input_bytes=input_bytes,
        timeout=timeout, output_limit=output_limit,
    )
    if result.timed_out or result.output_exceeded or result.returncode:
        raise RequirementDocumentError(
            "requirements.git_failed",
            (result.stderr or b"Git operation failed.").decode("utf-8", "replace")[:1000],
        )
    return result.stdout

def _deadline_git(
    root: Path, *arguments: str,
    timeout_provider: Optional[Callable[[], float]] = None,
) -> bytes:
    timeout = 30 if timeout_provider is None else timeout_provider()
    output = _git(root, *arguments, timeout=timeout)
    if timeout_provider is not None:
        timeout_provider()
    return output

def _deadline_filesystem(
    operation: Callable[[], Any],
    timeout_provider: Optional[Callable[[], float]],
) -> Any:
    if timeout_provider is not None:
        timeout_provider()
    value = operation()
    if timeout_provider is not None:
        timeout_provider()
    return value

def _require_supported_git(
    root: Path,
    *,
    timeout_provider: Optional[Callable[[], float]] = None,
) -> None:
    try:
        object_format = _deadline_git(
            root, "rev-parse", "--show-object-format",
            timeout_provider=timeout_provider,
        ).decode("ascii", "strict").strip()
        common_dir = Path(
            _deadline_git(
                root, "rev-parse", "--path-format=absolute", "--git-common-dir",
                timeout_provider=timeout_provider,
            ).decode("utf-8", "strict").strip()
        )
    except (RequirementDocumentError, UnicodeDecodeError) as error:
        raise RequirementDocumentError(
            "requirements.repository_unsupported",
            "Required Git capabilities are unavailable.",
        ) from error
    if object_format not in {"sha1", "sha256"} or not common_dir.is_absolute():
        raise RequirementDocumentError(
            "requirements.repository_unsupported",
            "Repository object format or common directory is unsupported.",
        )
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC

def _identity(value: os.stat_result) -> Tuple[int, int, int]:
    return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode)

def _file_snapshot_identity(
    value: os.stat_result,
) -> Tuple[int, int, int, int, int, int]:
    return (
        value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode),
        value.st_size, value.st_mtime_ns, value.st_ctime_ns,
    )

def _write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise RequirementDocumentError(
                "requirements.repository_unsupported", "File write did not progress."
            )
        view = view[written:]

def _validated_repository_root(
    repository_root: Path, *, require_identity: bool = False,
    timeout_provider: Optional[Callable[[], float]] = None,
) -> Path:
    if not isinstance(repository_root, Path) or not repository_root.is_absolute():
        raise RequirementDocumentError(
            "requirements.repository_invalid", "Repository root must be absolute."
        )
    try:
        root = _deadline_filesystem(
            lambda: repository_root.resolve(strict=True), timeout_provider
        )
    except OSError as error:
        raise RequirementDocumentError(
            "requirements.repository_invalid", "Repository root does not exist."
        ) from error
    _require_supported_git(root, timeout_provider=timeout_provider)
    try:
        top = _deadline_filesystem(
            lambda: Path(
                _deadline_git(
                    root, "rev-parse", "--show-toplevel",
                    timeout_provider=timeout_provider,
                ).decode("utf-8", "strict").strip()
            ).resolve(strict=True),
            timeout_provider,
        )
    except (OSError, UnicodeDecodeError) as error:
        raise RequirementDocumentError(
            "requirements.repository_invalid", "Repository top level is unavailable."
        ) from error
    if (
        root != top
        or _deadline_git(
            root, "rev-parse", "--is-bare-repository",
            timeout_provider=timeout_provider,
        ).strip() != b"false"
    ):
        raise RequirementDocumentError(
            "requirements.repository_invalid",
            "Repository root must be the exact top-level non-bare worktree.",
        )
    if _deadline_git(
        root, "rev-parse", "--show-object-format",
        timeout_provider=timeout_provider,
    ).strip() not in {b"sha1", b"sha256"}:
        raise RequirementDocumentError(
            "requirements.repository_unsupported", "Git object format is unsupported."
        )
    if require_identity:
        try:
            _deadline_git(
                root, "-c", "user.useConfigOnly=true", "var", "GIT_AUTHOR_IDENT",
                timeout_provider=timeout_provider,
            )
            _deadline_git(
                root, "-c", "user.useConfigOnly=true", "var", "GIT_COMMITTER_IDENT",
                timeout_provider=timeout_provider,
            )
        except RequirementDocumentError as error:
            raise RequirementDocumentError(
                "requirements.git_identity_missing",
                "Git author/committer identity is missing.",
            ) from error
    return root

@dataclass(frozen=True)
class _InstalledDocument:
    filename: str
    identity: Tuple[int, int, int, int, int, int]
    rendered: bytes
    previous_bytes: Optional[bytes]

class _RequirementDirectory:
    _COMPONENTS = ("docs", "superpowers", "requirements")

    def __init__(
        self, root: Path, fd: int, identities: Tuple[Tuple[int, int, int], ...]
    ) -> None:
        self.root = root
        self.fd = fd
        self.identities = identities

    @classmethod
    def open(cls, root: Path, *, create: bool) -> "_RequirementDirectory":
        try:
            current = os.open(str(root), _DIRECTORY_FLAGS)
            identities = [_identity(os.fstat(current))]
            for component in cls._COMPONENTS:
                try:
                    child = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(component, 0o755, dir_fd=current)
                    os.fsync(current)
                    child = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
                identities.append(_identity(os.fstat(child)))
                os.close(current)
                current = child
            return cls(root, current, tuple(identities))
        except FileNotFoundError:
            try:
                os.close(current)
            except (UnboundLocalError, OSError):
                pass
            raise
        except (OSError, NotImplementedError) as error:
            try:
                os.close(current)
            except (UnboundLocalError, OSError):
                pass
            raise RequirementDocumentError(
                "requirements.path_unsafe",
                "Requirements directory is missing, unsafe, or unsupported.",
            ) from error

    def __enter__(self) -> "_RequirementDirectory":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def require_same_logical_location(self) -> None:
        current = None
        try:
            current = os.open(str(self.root), _DIRECTORY_FLAGS)
            observed = [_identity(os.fstat(current))]
            for component in self._COMPONENTS:
                child = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
                os.close(current)
                current = child
                observed.append(_identity(os.fstat(current)))
            if tuple(observed) != self.identities or _identity(os.fstat(self.fd)) != observed[-1]:
                raise RequirementDocumentError(
                    "requirements.path_unsafe", "Requirements directory identity changed."
                )
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirements directory identity changed."
            ) from error
        finally:
            if current is not None:
                os.close(current)

    def stat_optional(self, filename: str) -> Optional[os.stat_result]:
        try:
            value = os.stat(filename, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirement target could not be inspected."
            ) from error
        if not stat.S_ISREG(value.st_mode):
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirement target is not a regular file."
            )
        return value

    def entry_exists(self, filename: str) -> bool:
        try:
            os.stat(filename, dir_fd=self.fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirement target could not be inspected."
            ) from error

    def read_regular_snapshot(
        self, filename: str, *, limit: int
    ) -> Tuple[bytes, Tuple[int, int, int, int, int, int]]:
        try:
            fd = os.open(filename, _FILE_READ_FLAGS, dir_fd=self.fd)
        except FileNotFoundError:
            raise
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirement target is unsafe."
            ) from error
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise RequirementDocumentError(
                    "requirements.document_invalid", "Requirement target is invalid."
                )
            chunks, total = [], 0
            while True:
                chunk = os.read(fd, min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > limit:
                    raise RequirementDocumentError(
                        "requirements.document_too_large", "Requirement target is too large."
                    )
            after = os.fstat(fd)
            identity = _file_snapshot_identity(after)
            if (
                _identity(before) != _identity(after)
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns
            ):
                raise RequirementDocumentError(
                    "requirements.document_changed_during_verification",
                    "Requirement target changed while it was read.",
                )
            return b"".join(chunks), identity
        except RequirementDocumentError:
            raise
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirement target could not be read safely."
            ) from error
        finally:
            os.close(fd)

    def install_initial(self, filename: str, rendered: bytes) -> _InstalledDocument:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            fd = os.open(filename, flags, 0o644, dir_fd=self.fd)
            created = _identity(os.fstat(fd))
        except OSError as error:
            raise RequirementDocumentError(
                "requirements.write_failed", "Requirement target could not be created."
            ) from error
        try:
            _write_all(fd, rendered)
            os.fsync(fd)
            installed = _file_snapshot_identity(os.fstat(fd))
        except Exception as error:
            os.close(fd)
            try:
                current = self.stat_optional(filename)
                if current is None or _identity(current) != created:
                    raise OSError("Writer no longer owns the partial target")
                os.unlink(filename, dir_fd=self.fd)
                os.fsync(self.fd)
            except (OSError, RequirementDocumentError) as cleanup_error:
                raise RequirementDocumentError(
                    "requirements.commit_indeterminate",
                    "Partial requirement write could not be cleaned up safely.",
                ) from cleanup_error
            raise RequirementDocumentError(
                "requirements.write_failed", "Requirement target write failed."
            ) from error
        else:
            os.close(fd)
        try:
            os.fsync(self.fd)
        except OSError as error:
            raise RequirementDocumentError(
                "requirements.commit_indeterminate",
                "Requirement directory durability is indeterminate.",
            ) from error
        return _InstalledDocument(filename, installed, rendered, None)

    def install_revision(
        self, filename: str, rendered: bytes, previous_bytes: bytes
    ) -> _InstalledDocument:
        previous, previous_identity = self.read_regular_snapshot(
            filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
        )
        if previous != previous_bytes:
            raise RequirementDocumentError(
                "requirements.document_worktree_drift", "Requirement target changed."
            )
        temporary = f".{filename}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            fd = os.open(temporary, flags, 0o644, dir_fd=self.fd)
            _write_all(fd, rendered)
            os.fsync(fd)
            installed = _file_snapshot_identity(os.fstat(fd))
        except Exception as error:
            if "fd" in locals():
                os.close(fd)
            try:
                os.unlink(temporary, dir_fd=self.fd)
                os.fsync(self.fd)
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                raise RequirementDocumentError(
                    "requirements.commit_indeterminate",
                    "Partial revision write could not be cleaned up safely.",
                ) from cleanup_error
            raise RequirementDocumentError(
                "requirements.write_failed", "Requirement revision write failed."
            ) from error
        else:
            os.close(fd)
        repeated, repeated_identity = self.read_regular_snapshot(
            filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
        )
        if repeated != previous_bytes or repeated_identity != previous_identity:
            os.unlink(temporary, dir_fd=self.fd)
            os.fsync(self.fd)
            raise RequirementDocumentError(
                "requirements.document_worktree_drift", "Requirement target changed."
            )
        try:
            os.replace(temporary, filename, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        except OSError as error:
            try:
                os.unlink(temporary, dir_fd=self.fd)
                os.fsync(self.fd)
            except OSError as cleanup_error:
                raise RequirementDocumentError(
                    "requirements.commit_indeterminate",
                    "Revision temporary file could not be cleaned up safely.",
                ) from cleanup_error
            raise RequirementDocumentError(
                "requirements.write_failed", "Requirement revision install failed."
            ) from error
        try:
            os.fsync(self.fd)
        except OSError as error:
            raise RequirementDocumentError(
                "requirements.commit_indeterminate",
                "Requirement revision durability is indeterminate.",
            ) from error
        installed_bytes, installed = self.read_regular_snapshot(
            filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
        )
        if installed_bytes != rendered:
            raise RequirementDocumentError(
                "requirements.commit_indeterminate",
                "Installed requirement revision bytes changed.",
            )
        return _InstalledDocument(filename, installed, rendered, previous_bytes)

    def rollback(self, installed: _InstalledDocument) -> None:
        try:
            current_bytes, current_identity = self.read_regular_snapshot(
                installed.filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
            )
        except FileNotFoundError as error:
            raise RequirementDocumentError(
                "requirements.commit_indeterminate", "Writer target disappeared."
            ) from error
        if (
            current_identity != installed.identity
            or current_bytes != installed.rendered
        ):
            raise RequirementDocumentError(
                "requirements.commit_indeterminate", "Writer no longer owns target bytes."
            )
        if installed.previous_bytes is None:
            os.unlink(installed.filename, dir_fd=self.fd)
        else:
            temporary = f".{installed.filename}.{secrets.token_hex(8)}.rollback"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            fd = os.open(temporary, flags, 0o644, dir_fd=self.fd)
            try:
                _write_all(fd, installed.previous_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(temporary, installed.filename, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        os.fsync(self.fd)


class _CommonDirectoryAnchor:
    def __init__(
        self, path: Path, fd: int, identities: Tuple[Tuple[int, int, int], ...]
    ) -> None:
        self.path = path
        self.fd = fd
        self.identities = identities

    @staticmethod
    def _open_chain(
        path: Path,
    ) -> Tuple[int, Tuple[Tuple[int, int, int], ...]]:
        current = None
        try:
            current = os.open(os.path.sep, _DIRECTORY_FLAGS)
            identities = [_identity(os.fstat(current))]
            for component in path.parts[1:]:
                child = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
                os.close(current)
                current = child
                identities.append(_identity(os.fstat(current)))
            return current, tuple(identities)
        except (OSError, NotImplementedError):
            if current is not None:
                os.close(current)
            raise

    @classmethod
    def open(cls, path: Path) -> "_CommonDirectoryAnchor":
        if not path.is_absolute():
            raise OSError("Git common directory is not absolute")
        fd, identities = cls._open_chain(path)
        return cls(path, fd, identities)

    def require_same_logical_location(self) -> None:
        current = None
        try:
            current, observed = self._open_chain(self.path)
            if (
                observed != self.identities
                or _identity(os.fstat(self.fd)) != observed[-1]
            ):
                raise RequirementDocumentError(
                    "requirements.path_unsafe", "Git common directory identity changed."
                )
        except RequirementDocumentError:
            raise
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Git common directory identity changed."
            ) from error
        finally:
            if current is not None:
                os.close(current)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


class _RepositoryRootAnchor:
    def __init__(
        self, logical_root: Path, root: Path, anchor: _CommonDirectoryAnchor
    ) -> None:
        self.logical_root = logical_root
        self.root = root
        self.anchor = anchor

    @classmethod
    def open(cls, repository_root: Path) -> "_RepositoryRootAnchor":
        root = _validated_repository_root(repository_root)
        try:
            return cls(repository_root, root, _CommonDirectoryAnchor.open(root))
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Repository root identity is unsafe."
            ) from error

    def require_same_logical_location(self) -> None:
        try:
            observed = self.logical_root.resolve(strict=True)
        except OSError as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Repository root identity changed."
            ) from error
        self.anchor.require_same_logical_location()
        if observed != self.root:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Repository root identity changed."
            )

    def close(self) -> None:
        self.anchor.close()


@contextmanager
def _writer_lock(root: Path) -> Iterator[_CommonDirectoryAnchor]:
    common_text = _git(
        root, "rev-parse", "--path-format=absolute", "--git-common-dir"
    ).decode().strip()
    deadline = time.monotonic() + 5.0
    anchor = None
    try:
        common = Path(common_text).resolve(strict=True)
        anchor = _CommonDirectoryAnchor.open(common)
        while True:
            try:
                lock_fd = os.open(
                    "ai-native-devkit-requirements.lock",
                    os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=anchor.fd,
                )
                break
            except FileNotFoundError:
                # Darwin may transiently report ENOENT when two callers race to
                # create the same no-follow file. Retrying preserves O_NOFOLLOW.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
    except (OSError, NotImplementedError) as error:
        if anchor is not None:
            anchor.close()
        raise RequirementDocumentError(
            "requirements.repository_unsupported", "Writer lock is unavailable."
        ) from error
    try:
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RequirementDocumentError(
                        "requirements.writer_busy", "Another requirement Writer is active.",
                        retryable=True,
                    )
                time.sleep(0.01)
        anchor.require_same_logical_location()
        yield anchor
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            try:
                os.close(lock_fd)
            finally:
                anchor.close()


@dataclass(frozen=True)
class _PreservationSnapshot:
    parent: Optional[str]
    head_attachment: bytes
    target_index_record: Optional[bytes]
    unrelated_index_records: Tuple[bytes, ...]
    unrelated_cached_diff: bytes
    unrelated_worktree_diff: bytes

def _read_optional_head(root: Path, *, timeout: float = 30) -> Optional[str]:
    result = _git_result(
        root, "rev-parse", "--verify", "-q", "HEAD", timeout=timeout
    )
    if result.timed_out or result.output_exceeded:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git HEAD lookup did not complete."
        )
    if result.returncode == 1 and not result.stderr:
        return None
    if result.returncode:
        raise RequirementDocumentError(
            "requirements.git_failed",
            (result.stderr or b"Git HEAD lookup failed.")
            .decode("utf-8", "replace")[:1000],
        )
    value = result.stdout.decode("ascii").strip()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise RequirementDocumentError(
            "requirements.git_failed", "Git returned an invalid HEAD."
        )
    return value

def _read_head_attachment(root: Path, *, timeout: float = 30) -> bytes:
    result = _git_result(
        root, "symbolic-ref", "--no-recurse", "-q", "HEAD", timeout=timeout
    )
    if result.timed_out or result.output_exceeded:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git HEAD attachment lookup did not complete."
        )
    if result.returncode == 1 and not result.stderr:
        return b"DETACHED"
    if result.returncode:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git HEAD attachment lookup failed."
        )
    value = result.stdout.rstrip(b"\n")
    if not value.startswith(b"refs/") or b"\n" in value or b"\r" in value:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git returned an invalid HEAD attachment."
        )
    return value

def _index_records(root: Path, *, timeout: float = 30) -> Tuple[bytes, ...]:
    output = _git(
        root, "ls-files", "--stage", "-z",
        timeout=timeout,
        output_limit=MAX_REPOSITORY_PROJECTION_BYTES,
    )
    return tuple(item for item in output.split(b"\0") if item)

def _hidden_index_paths(root: Path) -> Tuple[bytes, ...]:
    output = _git(
        root, "ls-files", "-v", "-z",
        output_limit=MAX_REPOSITORY_PROJECTION_BYTES,
    )
    hidden = []
    for record in (item for item in output.split(b"\0") if item):
        if len(record) < 3 or record[1:2] != b" ":
            raise RequirementDocumentError(
                "requirements.git_failed", "Git returned malformed index flags."
            )
        tag = chr(record[0])
        if tag == "S" or tag.islower():
            hidden.append(record[2:])
    return tuple(hidden)

def _index_record_path(record: bytes) -> bytes:
    _, separator, path = record.partition(b"\t")
    if not separator:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git returned a malformed index record."
        )
    return path

def _unrelated_index_records(root: Path, target: str) -> Tuple[bytes, ...]:
    encoded = os.fsencode(target)
    return tuple(
        record for record in _index_records(root)
        if _index_record_path(record) != encoded
    )

def _target_index_record(root: Path, target: str) -> Optional[bytes]:
    encoded = os.fsencode(target)
    records = [
        record for record in _index_records(root)
        if _index_record_path(record) == encoded
    ]
    if len(records) > 1:
        raise RequirementDocumentError(
            "requirements.git_failed", "Requirement path has unmerged index entries."
        )
    return records[0] if records else None

def _unrelated_diff(root: Path, target: str, *, cached: bool) -> bytes:
    arguments = ["diff"]
    if cached:
        arguments.append("--cached")
    arguments.extend([
        "--no-ext-diff", "--no-textconv", "--ignore-submodules=untracked",
        "--binary", "--", ".",
        f":(top,literal,exclude){target}",
    ])
    return _git(root, *arguments, output_limit=MAX_REPOSITORY_PROJECTION_BYTES)

def _capture_preservation(root: Path, target: str) -> _PreservationSnapshot:
    hidden = _hidden_index_paths(root)
    if hidden:
        raise RequirementDocumentError(
            "requirements.snapshot_unsupported",
            "skip-worktree or assume-unchanged paths must be cleared before writing.",
        )
    return _PreservationSnapshot(
        parent=_read_optional_head(root),
        head_attachment=_read_head_attachment(root),
        target_index_record=_target_index_record(root, target),
        unrelated_index_records=_unrelated_index_records(root, target),
        unrelated_cached_diff=_unrelated_diff(root, target, cached=True),
        unrelated_worktree_diff=_unrelated_diff(root, target, cached=False),
    )

def _preservation_matches(
    root: Path, target: str, expected: _PreservationSnapshot
) -> bool:
    return (
        _read_optional_head(root) == expected.parent
        and _read_head_attachment(root) == expected.head_attachment
        and _unrelated_preservation_matches(root, target, expected)
    )

def _unrelated_preservation_matches(
    root: Path, target: str, expected: _PreservationSnapshot
) -> bool:
    return (
        not _hidden_index_paths(root)
        and _unrelated_index_records(root, target) == expected.unrelated_index_records
        and _unrelated_diff(root, target, cached=True) == expected.unrelated_cached_diff
        and _unrelated_diff(root, target, cached=False) == expected.unrelated_worktree_diff
    )

def _owned_pre_ref_state_matches(
    *, root: Path, target: str, directory: _RequirementDirectory,
    installed: _InstalledDocument, expected: _PreservationSnapshot,
    owned_intent: Optional[bytes],
) -> bool:
    try:
        content, identity = directory.read_regular_snapshot(
            installed.filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
        )
        expected_index = owned_intent or expected.target_index_record
        return (
            _read_optional_head(root) == expected.parent
            and _read_head_attachment(root) == expected.head_attachment
            and _target_index_record(root, target) == expected_index
            and identity == installed.identity
            and content == installed.rendered
        )
    except (OSError, RequirementDocumentError):
        return False
def _require_untransformed_attributes(root: Path, target: str) -> None:
    fields = _git(
        root, "check-attr", "-z", "filter", "working-tree-encoding", "--", target
    ).split(b"\0")
    if fields[-1:] == [b""]:
        fields.pop()
    if len(fields) != 6:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git returned malformed attribute data."
        )
    triples = [fields[index:index + 3] for index in range(0, len(fields), 3)]
    if any(
        path != os.fsencode(target) or value not in {b"unspecified", b"unset"}
        for path, _attribute, value in triples
    ):
        raise RequirementDocumentError(
            "requirements.content_transformed",
            "Git attributes would transform the requirement document.",
        )

def _require_exact_git_blob(root: Path, target: str, rendered: bytes) -> str:
    raw = _git(root, "hash-object", "--stdin", input_bytes=rendered).decode().strip()
    path_aware = _git(
        root, "hash-object", "--path", target, "--stdin", input_bytes=rendered
    ).decode().strip()
    if raw != path_aware:
        raise RequirementDocumentError(
            "requirements.content_transformed",
            "Git attributes would transform the requirement document.",
        )
    return raw

def _require_intent_to_add(root: Path, target: str) -> bytes:
    record = _target_index_record(root, target)
    if record is None:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git did not create intent-to-add."
        )
    header, separator, returned_path = record.partition(b"\t")
    fields = header.split(b" ")
    empty_blob = _git(root, "hash-object", "--stdin", input_bytes=b"").strip()
    if (
        not separator or len(fields) != 3 or fields[0] != b"100644"
        or fields[1] != empty_blob or fields[2] != b"0"
        or returned_path != os.fsencode(target)
    ):
        raise RequirementDocumentError(
            "requirements.git_failed", "Target entry is not intent-to-add."
        )
    cached = _git_result(
        root, "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
        "--cached", "--quiet", "--", target,
    )
    worktree = _git_result(
        root, "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
        "--quiet", "--", target
    )
    if cached.returncode != 0 or worktree.returncode != 1:
        raise RequirementDocumentError(
            "requirements.git_failed", "Intent-to-add state is invalid."
        )
    return record

def _remove_owned_intent(
    root: Path, target: str, owned: bytes, expected: _PreservationSnapshot
) -> None:
    if (
        _target_index_record(root, target) != owned
        or _unrelated_index_records(root, target) != expected.unrelated_index_records
        or _unrelated_diff(root, target, cached=True) != expected.unrelated_cached_diff
    ):
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Writer no longer owns intent-to-add."
        )
    _git(root, "update-index", "--force-remove", "--", target)
    if _target_index_record(root, target) is not None:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Intent-to-add cleanup failed."
        )
def _topic_slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
    if not slug:
        return f"topic-{digest}"
    if len(slug) > 64:
        return f"{slug[:51].rstrip('-')}-{digest}"
    return slug

def _path_is_reserved(
    root: Path, directory: _RequirementDirectory, relative_path: str
) -> bool:
    filename = PurePosixPath(relative_path).name
    if directory.entry_exists(filename):
        return True
    if _git(root, "ls-files", "--stage", "--", relative_path):
        return True
    head = _read_optional_head(root)
    if head is not None:
        in_head = _git_result(root, "cat-file", "-e", f"{head}:{relative_path}")
        if in_head.timed_out or in_head.output_exceeded:
            raise RequirementDocumentError(
                "requirements.git_failed", "Git path lookup did not complete."
            )
        if in_head.returncode == 0:
            return True
    history = _git(
        root, "log", "--all", "-1", "--format=%H", "--", relative_path
    ).strip()
    return bool(history)

def _select_initial_path(
    *, root: Path, directory: _RequirementDirectory, day: date, slug: str
) -> str:
    ordinal = 1
    while True:
        suffix = "" if ordinal == 1 else f"-{ordinal}"
        filename = f"{day.isoformat()}-{slug}-requirements{suffix}.md"
        relative = f"docs/superpowers/requirements/{filename}"
        if not _path_is_reserved(root, directory, relative):
            return relative
        ordinal += 1
@dataclass(frozen=True)
class _TreeEntry:
    mode: str
    type: str
    oid: str
    path: str

def _parse_single_ls_tree(output: bytes, expected_path: str) -> _TreeEntry:
    records = [item for item in output.split(b"\0") if item]
    if len(records) != 1:
        raise RequirementDocumentError(
            "requirements.document_committed_drift", "Git tree entry is missing."
        )
    header, separator, raw_path = records[0].partition(b"\t")
    fields = header.split(b" ")
    try:
        path = raw_path.decode("utf-8")
        mode, object_type, oid = (field.decode("ascii") for field in fields)
    except (UnicodeDecodeError, ValueError) as error:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git returned a malformed tree entry."
        ) from error
    if (
        not separator or len(fields) != 3 or path != expected_path
        or mode != "100644" or object_type != "blob"
        or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid)
    ):
        raise RequirementDocumentError(
            "requirements.document_committed_drift", "Git tree entry is invalid."
        )
    return _TreeEntry(mode, object_type, oid, path)

def _require_git_zero_or_change(
    result: _GitResult, *, change_code: str
) -> None:
    if result.timed_out or result.output_exceeded or result.returncode not in {0, 1}:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git verification did not complete."
        )
    if result.returncode == 1:
        raise RequirementDocumentError(
            change_code, "Requirement identity is not current."
        )

def _git_index_snapshot(root: Path, *, timeout: float = 30) -> Tuple[bytes, ...]:
    return _index_records(root, timeout=timeout)

def _verify_current_document(
    *, repository_root: Path, reference: RequirementDocRef
) -> bytes:
    if not isinstance(reference, RequirementDocRef):
        raise RequirementDocumentError(
            "requirements.reference_invalid", "An exact requirement reference is required."
        )
    root = _validated_repository_root(repository_root)
    try:
        requirement_dir = _RequirementDirectory.open(root, create=False)
    except FileNotFoundError as error:
        raise RequirementDocumentError(
            "requirements.document_missing", "Document is missing from the worktree."
        ) from error
    try:
        start_head = _read_optional_head(root)
        start_attachment = _read_head_attachment(root)
        start_index = _git_index_snapshot(root)
        if start_head is None:
            raise RequirementDocumentError(
                "requirements.commit_invalid", "HEAD is unborn."
            )
        commit_type = _git_result(root, "cat-file", "-t", reference.commit)
        if (
            commit_type.timed_out or commit_type.output_exceeded
            or commit_type.returncode != 0 or commit_type.stdout.strip() != b"commit"
        ):
            raise RequirementDocumentError(
                "requirements.commit_invalid", "Commit is invalid."
            )
        _require_git_zero_or_change(
            _git_result(
                root, "merge-base", "--is-ancestor", reference.commit, start_head
            ),
            change_code="requirements.commit_stale",
        )
        object_format = _git(root, "rev-parse", "--show-object-format").decode().strip()
        expected_prefix = f"git-{object_format}:"
        tree_entry = _parse_single_ls_tree(
            _git(root, "ls-tree", "-z", reference.commit, "--", reference.path),
            reference.path,
        )
        if (
            tree_entry.type != "blob"
            or reference.blob_digest != expected_prefix + tree_entry.oid
        ):
            raise RequirementDocumentError(
                "requirements.blob_mismatch", "Blob identity changed."
            )
        latest = _git(
            root, "log", "-1", "--format=%H", start_head, "--", reference.path
        ).decode().strip()
        head_bytes = _git(root, "ls-tree", "-z", start_head, "--", reference.path)
        if latest != reference.commit or not head_bytes:
            raise RequirementDocumentError(
                "requirements.document_committed_drift",
                "Document changed in Git history.",
            )
        head_entry = _parse_single_ls_tree(head_bytes, reference.path)
        if head_entry.oid != tree_entry.oid:
            raise RequirementDocumentError(
                "requirements.document_committed_drift",
                "Document changed in Git history.",
            )
        _require_git_zero_or_change(
            _git_result(
                root, "diff", "--no-ext-diff", "--no-textconv",
                "--ignore-submodules=none", "--cached", "--quiet", "--",
                reference.path,
            ),
            change_code="requirements.document_index_drift",
        )
        try:
            current, target_identity = requirement_dir.read_regular_snapshot(
                PurePosixPath(reference.path).name,
                limit=MAX_REQUIREMENT_DOCUMENT_BYTES,
            )
        except FileNotFoundError as error:
            raise RequirementDocumentError(
                "requirements.document_missing", "Document is missing from the worktree."
            ) from error
        _require_git_zero_or_change(
            _git_result(
                root, "diff", "--no-ext-diff", "--no-textconv",
                "--ignore-submodules=none", "--quiet", "--", reference.path,
            ),
            change_code="requirements.document_worktree_drift",
        )
        committed = _git(root, "cat-file", "blob", tree_entry.oid)
        if current != committed:
            raise RequirementDocumentError(
                "requirements.document_worktree_drift",
                "Document changed in the worktree.",
            )
        try:
            current.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RequirementDocumentError(
                "requirements.document_invalid", "Document is not UTF-8."
            ) from error
        try:
            repeated, repeated_identity = requirement_dir.read_regular_snapshot(
                PurePosixPath(reference.path).name,
                limit=MAX_REQUIREMENT_DOCUMENT_BYTES,
            )
        except FileNotFoundError as error:
            raise RequirementDocumentError(
                "requirements.document_missing", "Document disappeared during verification."
            ) from error
        repeated_latest = _git(
            root, "log", "-1", "--format=%H", start_head, "--", reference.path
        ).decode().strip()
        _require_git_zero_or_change(
            _git_result(
                root, "diff", "--no-ext-diff", "--no-textconv",
                "--ignore-submodules=none", "--cached", "--quiet", "--",
                reference.path,
            ),
            change_code="requirements.document_index_drift",
        )
        _require_git_zero_or_change(
            _git_result(
                root, "diff", "--no-ext-diff", "--no-textconv",
                "--ignore-submodules=none", "--quiet", "--", reference.path,
            ),
            change_code="requirements.document_worktree_drift",
        )
        if (
            _read_optional_head(root) != start_head
            or _read_head_attachment(root) != start_attachment
            or _git_index_snapshot(root) != start_index
            or repeated_latest != reference.commit
            or repeated_identity != target_identity
            or repeated != current
        ):
            raise RequirementDocumentError(
                "requirements.document_changed_during_verification",
                "Document or repository state changed during verification.",
            )
        requirement_dir.require_same_logical_location()
        return current
    finally:
        requirement_dir.close()

@dataclass(frozen=True)
class _SourceSnapshot:
    locator: str
    file_identity: Tuple[int, int, int, int, int, int]
    directory_identities: Tuple[Tuple[int, int, int], ...]
    git_mode: str
    blob_oid: str

@dataclass
class _SourceReadBudget:
    remaining: int
    deadline: float

    def timeout(self) -> float:
        remaining_time = self.deadline - time.monotonic()
        if remaining_time <= 0:
            raise RequirementDocumentError(
                "requirements.source_drift",
                "Repository source verification time budget was exceeded.",
            )
        return min(30.0, remaining_time)

    def consume(self, count: int) -> None:
        self.timeout()
        if count > self.remaining:
            raise RequirementDocumentError(
                "requirements.source_drift",
                "Repository source verification budget was exceeded.",
            )
        self.remaining -= count

def _source_checked(
    budget: _SourceReadBudget, operation: Callable[[float], Any],
    repository_anchor: Optional[_RepositoryRootAnchor] = None,
) -> Any:
    try:
        if repository_anchor is not None:
            budget.timeout()
            repository_anchor.require_same_logical_location()
            budget.timeout()
        value = operation(budget.timeout())
        budget.timeout()
        if repository_anchor is not None:
            repository_anchor.require_same_logical_location()
            budget.timeout()
        return value
    except RequirementDocumentError as error:
        raise RequirementDocumentError(
            "requirements.source_drift",
            "Repository source verification did not complete.",
        ) from error

def _source_probe(budget: _SourceReadBudget, operation: Callable[[], Any]) -> Any:
    budget.timeout()
    value = operation()
    budget.timeout()
    return value

def _source_tree_entry(
    root: Path, revision: str, locator: str, budget: _SourceReadBudget,
    repository_anchor: Optional[_RepositoryRootAnchor] = None,
) -> _TreeEntry:
    records = [
        item for item in _source_checked(
            budget,
            lambda timeout: _git(
                root, "ls-tree", "-z", revision, "--", locator,
                timeout=timeout,
            ),
            repository_anchor,
        ).split(b"\0")
        if item
    ]
    if len(records) != 1:
        raise RequirementDocumentError(
            "requirements.source_drift", "A cited repository source is missing."
        )
    header, separator, raw_path = records[0].partition(b"\t")
    fields = header.split(b" ")
    if (
        not separator or len(fields) != 3
        or fields[0] not in {b"100644", b"100755"}
        or fields[1] != b"blob" or raw_path != os.fsencode(locator)
        or re.fullmatch(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})", fields[2]) is None
    ):
        raise RequirementDocumentError(
            "requirements.source_drift",
            "A cited repository source is not a regular blob.",
        )
    try:
        return _TreeEntry(
            fields[0].decode("ascii"), "blob", fields[2].decode("ascii"), locator
        )
    except UnicodeDecodeError as error:
        raise RequirementDocumentError(
            "requirements.source_drift", "A cited repository source is malformed."
        ) from error

def _worktree_source_snapshot(
    root: Path, locator: str, object_format: str, budget: _SourceReadBudget,
    *, root_fd: Optional[int] = None,
) -> _SourceSnapshot:
    logical = PurePosixPath(locator)
    current = None
    fd = None
    try:
        current = _source_probe(
            budget,
            lambda: (
                os.dup(root_fd)
                if root_fd is not None
                else os.open(str(root), _DIRECTORY_FLAGS)
            ),
        )
        identities = [_identity(_source_probe(budget, lambda: os.fstat(current)))]
        for component in logical.parts[:-1]:
            child = _source_probe(
                budget,
                lambda component=component: os.open(
                    component, _DIRECTORY_FLAGS, dir_fd=current
                ),
            )
            os.close(current)
            current = child
            identities.append(
                _identity(_source_probe(budget, lambda: os.fstat(current)))
            )
        fd = _source_probe(
            budget,
            lambda: os.open(logical.name, _FILE_READ_FLAGS, dir_fd=current),
        )
        before = _source_probe(budget, lambda: os.fstat(fd))
        if not stat.S_ISREG(before.st_mode):
            raise OSError("source is not regular")
        algorithm = "sha1" if object_format == "sha1" else "sha256"
        digest = _source_probe(budget, lambda: hashlib.new(algorithm))
        _source_probe(
            budget,
            lambda: digest.update(f"blob {before.st_size}\0".encode("ascii")),
        )
        while True:
            chunk = _source_probe(budget, lambda: os.read(fd, 65536))
            budget.consume(len(chunk))
            if not chunk:
                break
            _source_probe(budget, lambda: digest.update(chunk))
        after = _source_probe(budget, lambda: os.fstat(fd))
        file_identity = (
            after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode),
            after.st_size, after.st_mtime_ns, after.st_ctime_ns,
        )
        if (
            _identity(before) != _identity(after)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise OSError("source changed while read")
        blob_oid = _source_probe(budget, digest.hexdigest)
        return _SourceSnapshot(
            locator, file_identity, tuple(identities),
            "100755" if before.st_mode & 0o111 else "100644",
            blob_oid,
        )
    except RequirementDocumentError:
        raise
    except (OSError, NotImplementedError) as error:
        raise RequirementDocumentError(
            "requirements.source_drift", "A cited repository source is unavailable."
        ) from error
    finally:
        if fd is not None:
            os.close(fd)
        if current is not None:
            os.close(current)

def _source_diff_is_clean(
    root: Path, locator: str, budget: _SourceReadBudget,
    repository_anchor: Optional[_RepositoryRootAnchor] = None,
) -> None:
    for arguments in (
        (
            "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
            "--cached", "--quiet", "--", locator,
        ),
        (
            "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
            "--quiet", "--", locator,
        ),
    ):
        probe = _source_checked(
            budget,
            lambda timeout: _git_result(root, *arguments, timeout=timeout),
            repository_anchor,
        )
        if probe.timed_out or probe.output_exceeded or probe.returncode != 0:
            raise RequirementDocumentError(
                "requirements.source_drift", "A cited repository source is dirty."
            )

def _verify_repository_sources(
    repository_root: Path, sources: Sequence[RequirementSource],
    *, repository_anchor: Optional[_RepositoryRootAnchor] = None,
) -> None:
    if len(sources) > MAX_REQUIREMENT_SOURCES:
        raise RequirementDocumentError(
            "requirements.source_invalid", "At most 64 sources may be recorded."
        )
    repository_sources = [
        _validated_source(source) for source in sources
        if source.kind == "repository"
    ]
    if not repository_sources:
        return
    budget = _SourceReadBudget(
        remaining=MAX_SOURCE_SNAPSHOT_BYTES,
        deadline=time.monotonic() + SOURCE_SNAPSHOT_TIMEOUT_SECONDS,
    )
    if repository_anchor is None:
        root = _source_checked(
            budget,
            lambda _timeout: _validated_repository_root(
                repository_root, timeout_provider=budget.timeout
            ),
        )
        root_fd = None
    else:
        root = repository_anchor.root
        root_fd = repository_anchor.anchor.fd
        _source_checked(
            budget, lambda _timeout: None, repository_anchor
        )
    start_head = _source_checked(
        budget, lambda timeout: _read_optional_head(root, timeout=timeout),
        repository_anchor,
    )
    if start_head is None:
        raise RequirementDocumentError(
            "requirements.source_drift", "Repository has no current revision."
        )
    start_attachment = _source_checked(
        budget, lambda timeout: _read_head_attachment(root, timeout=timeout),
        repository_anchor,
    )
    start_index = _source_checked(
        budget, lambda timeout: _git_index_snapshot(root, timeout=timeout),
        repository_anchor,
    )
    raw_object_format = _source_checked(
        budget,
        lambda timeout: _git(
            root, "rev-parse", "--show-object-format", timeout=timeout
        ),
        repository_anchor,
    )
    try:
        object_format = raw_object_format.decode("ascii", "strict").strip()
    except UnicodeDecodeError as error:
        raise RequirementDocumentError(
            "requirements.source_drift", "Repository object format is malformed."
        ) from error
    if object_format not in {"sha1", "sha256"}:
        raise RequirementDocumentError(
            "requirements.source_drift", "Repository object format is unsupported."
        )
    first = []
    for source in repository_sources:
        commit_type = _source_checked(
            budget,
            lambda timeout: _git_result(
                root, "cat-file", "-t", source.version, timeout=timeout
            ),
            repository_anchor,
        )
        ancestor = _source_checked(
            budget,
            lambda timeout: _git_result(
                root, "merge-base", "--is-ancestor", source.version, start_head,
                timeout=timeout,
            ),
            repository_anchor,
        )
        if (
            commit_type.timed_out or commit_type.output_exceeded
            or commit_type.returncode != 0 or commit_type.stdout.strip() != b"commit"
            or ancestor.timed_out or ancestor.output_exceeded
            or ancestor.returncode != 0
        ):
            raise RequirementDocumentError(
                "requirements.source_drift",
                "A cited source revision is not current history.",
            )
        recorded = _source_tree_entry(
            root, source.version, source.locator, budget, repository_anchor
        )
        current = _source_tree_entry(
            root, start_head, source.locator, budget, repository_anchor
        )
        if (recorded.mode, recorded.oid) != (current.mode, current.oid):
            raise RequirementDocumentError(
                "requirements.source_drift", "A cited repository source changed."
            )
        _source_diff_is_clean(root, source.locator, budget, repository_anchor)
        snapshot = _worktree_source_snapshot(
            root, source.locator, object_format, budget, root_fd=root_fd
        )
        if (snapshot.git_mode, snapshot.blob_oid) != (current.mode, current.oid):
            raise RequirementDocumentError(
                "requirements.source_drift", "A cited repository source changed."
            )
        first.append((source, current.mode, current.oid, snapshot))
    if (
        _source_checked(
            budget, lambda timeout: _read_optional_head(root, timeout=timeout),
            repository_anchor,
        ) != start_head
        or _source_checked(
            budget, lambda timeout: _read_head_attachment(root, timeout=timeout),
            repository_anchor,
        ) != start_attachment
        or _source_checked(
            budget, lambda timeout: _git_index_snapshot(root, timeout=timeout),
            repository_anchor,
        ) != start_index
    ):
        raise RequirementDocumentError(
            "requirements.source_drift", "Repository changed during source verification."
        )
    for source, expected_mode, expected_oid, expected_snapshot in first:
        repeated_entry = _source_tree_entry(
            root, start_head, source.locator, budget, repository_anchor
        )
        repeated_snapshot = _worktree_source_snapshot(
            root, source.locator, object_format, budget, root_fd=root_fd
        )
        _source_diff_is_clean(root, source.locator, budget, repository_anchor)
        if (
            (repeated_entry.mode, repeated_entry.oid) != (expected_mode, expected_oid)
            or repeated_snapshot != expected_snapshot
        ):
            raise RequirementDocumentError(
                "requirements.source_drift", "A cited source changed during verification."
            )
    if (
        _source_checked(
            budget, lambda timeout: _read_optional_head(root, timeout=timeout),
            repository_anchor,
        ) != start_head
        or _source_checked(
            budget, lambda timeout: _read_head_attachment(root, timeout=timeout),
            repository_anchor,
        ) != start_attachment
        or _source_checked(
            budget, lambda timeout: _git_index_snapshot(root, timeout=timeout),
            repository_anchor,
        ) != start_index
    ):
        raise RequirementDocumentError(
            "requirements.source_drift", "Repository changed during source verification."
        )
def _validate_native_commit(
    *, root: Path, directory: _RequirementDirectory,
    common_directory: _CommonDirectoryAnchor,
    expected_parent: Optional[str], observed: str, target: str,
    rendered: bytes, expected_blob: str, created: bool,
    preservation: _PreservationSnapshot,
) -> RequirementDocRef:
    parents = _git(root, "rev-list", "--parents", "-n", "1", observed).decode().split()
    expected = [observed] if expected_parent is None else [observed, expected_parent]
    if parents != expected:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Requirement commit parent changed."
        )
    changed = [
        item for item in _git(
            root, "diff-tree", "--root", "--no-commit-id", "--name-status",
            "-z", "-r", observed,
        ).split(b"\0") if item
    ]
    if changed != [b"A" if created else b"M", os.fsencode(target)]:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Commit contains unexpected changes."
        )
    records = [
        item for item in _git(root, "ls-tree", "-z", observed, "--", target).split(b"\0")
        if item
    ]
    if len(records) != 1:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Commit has no exact target blob."
        )
    header, separator, returned_path = records[0].partition(b"\t")
    fields = header.split(b" ")
    if (
        not separator or len(fields) != 3 or fields[0] != b"100644"
        or fields[1] != b"blob" or returned_path != os.fsencode(target)
    ):
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Target tree entry is invalid."
        )
    blob = fields[2].decode("ascii")
    if blob != expected_blob or _git(root, "cat-file", "blob", blob) != rendered:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Committed requirement bytes changed."
        )
    for arguments in (
        (
            "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
            "--cached", "--quiet", "--", target,
        ),
        (
            "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
            "--quiet", "--", target,
        ),
    ):
        result = _git_result(root, *arguments)
        if result.timed_out or result.output_exceeded or result.returncode != 0:
            raise RequirementDocumentError(
                "requirements.commit_indeterminate", "Requirement target is not clean."
            )
    filename = PurePosixPath(target).name
    if directory.read_regular_snapshot(
        filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
    )[0] != rendered:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Requirement worktree bytes changed."
        )
    if not _unrelated_preservation_matches(root, target, preservation):
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Unrelated repository state changed."
        )
    if _read_head_attachment(root) != preservation.head_attachment:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "HEAD attachment changed."
        )
    directory.require_same_logical_location()
    if _read_optional_head(root) != observed:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "HEAD changed during verification."
        )
    object_format = _git(root, "rev-parse", "--show-object-format").decode().strip()
    common_directory.require_same_logical_location()
    return RequirementDocRef(
        path=target, commit=observed, blob_digest=f"git-{object_format}:{blob}"
    )

class RequirementDocumentWriter:
    def __init__(self, today: Callable[[], date] = date.today) -> None:
        self._today = today

    def write_and_commit(
        self, *, repository_root: Path, title: str,
        clarified_requirements: str,
        sources: Sequence[RequirementSource] = (),
        supersedes: Optional[RequirementDocRef] = None,
        document_language: str = "zh-CN",
    ) -> RequirementDocRef:
        rendered = _render_document(title, clarified_requirements, sources, document_language)
        if supersedes is not None and not isinstance(supersedes, RequirementDocRef):
            raise RequirementDocumentError(
                "requirements.reference_invalid", "supersedes must be an exact reference."
            )
        root = _validated_repository_root(repository_root, require_identity=True)
        slug = _topic_slug(title)
        with _writer_lock(root) as common_directory:
            previous = (
                _verify_current_document(repository_root=root, reference=supersedes)
                if supersedes is not None else None
            )
            with _RequirementDirectory.open(root, create=True) as directory:
                target = (
                    supersedes.path if supersedes is not None
                    else _select_initial_path(
                        root=root, directory=directory, day=self._today(), slug=slug
                    )
                )
                filename = PurePosixPath(target).name
                preservation = _capture_preservation(root, target)
                _require_untransformed_attributes(root, target)
                expected_blob = _require_exact_git_blob(root, target, rendered)
                installed = (
                    directory.install_initial(filename, rendered)
                    if previous is None
                    else directory.install_revision(filename, rendered, previous)
                )
                owned_intent = None
                cleanup_permitted = True
                ref_command_started = False
                try:
                    directory.require_same_logical_location()
                    if supersedes is None:
                        add_result = _git_result(root, "add", "-N", "--", target)
                        if (
                            add_result.timed_out or add_result.output_exceeded
                            or add_result.returncode != 0
                        ):
                            if (
                                not add_result.timed_out and not add_result.output_exceeded
                                and _target_index_record(root, target) is None
                                and _unrelated_preservation_matches(root, target, preservation)
                            ):
                                raise RequirementDocumentError(
                                    "requirements.commit_failed", "Git intent-to-add failed."
                                )
                            cleanup_permitted = False
                            raise RequirementDocumentError(
                                "requirements.commit_indeterminate",
                                "Git intent-to-add outcome is indeterminate.",
                            )
                        owned_intent = _require_intent_to_add(root, target)
                        if not _unrelated_preservation_matches(root, target, preservation):
                            raise RequirementDocumentError(
                                "requirements.commit_indeterminate",
                                "Intent-to-add changed unrelated repository state.",
                            )
                    directory.require_same_logical_location()
                    common_directory.require_same_logical_location()
                    message = (
                        f"docs: {'revise' if supersedes else 'record'} "
                        f"{slug} requirements"
                    )
                    result = _git_result(
                        root, "commit", "--only", "--no-status",
                        "-m", message, "--", target,
                    )
                    ref_command_started = result.started
                    cleanup_permitted = not result.started
                    observed = _read_optional_head(root)
                    if observed == preservation.parent:
                        if (
                            not result.timed_out and not result.output_exceeded
                            and result.returncode != 0
                        ):
                            cleanup_permitted = True
                            raise RequirementDocumentError(
                                "requirements.commit_failed",
                                (result.stderr or b"Requirement commit failed.")
                                .decode("utf-8", "replace")[:1000],
                            )
                        cleanup_permitted = False
                        raise RequirementDocumentError(
                            "requirements.commit_indeterminate",
                            "Native Git commit outcome is indeterminate.",
                        )
                    if observed is None:
                        cleanup_permitted = False
                        raise RequirementDocumentError(
                            "requirements.commit_indeterminate", "HEAD became invalid."
                        )
                    return _validate_native_commit(
                        root=root, directory=directory,
                        common_directory=common_directory,
                        expected_parent=preservation.parent, observed=observed,
                        target=target, rendered=rendered, expected_blob=expected_blob,
                        created=(supersedes is None), preservation=preservation,
                    )
                except Exception as original:
                    if not cleanup_permitted:
                        if ref_command_started:
                            raise RequirementDocumentError(
                                "requirements.commit_indeterminate",
                                "Native Git may have moved HEAD; post-commit verification failed.",
                            ) from original
                        raise
                    path_failure_before_ref = (
                        not ref_command_started
                        and isinstance(original, RequirementDocumentError)
                        and original.code == "requirements.path_unsafe"
                    )
                    owned_state = cleanup_permitted and _owned_pre_ref_state_matches(
                        root=root, target=target, directory=directory,
                        installed=installed, expected=preservation,
                        owned_intent=owned_intent,
                    )
                    unrelated_state = (
                        True if path_failure_before_ref
                        else _unrelated_preservation_matches(root, target, preservation)
                    )
                    if owned_state and unrelated_state:
                        try:
                            if owned_intent is not None:
                                _remove_owned_intent(root, target, owned_intent, preservation)
                            # Roll back through the retained requirements dirfd. This
                            # remains safe when only the logical ancestor was swapped.
                            directory.rollback(installed)
                        except Exception as cleanup_error:
                            raise RequirementDocumentError(
                                "requirements.commit_indeterminate",
                                "Commit failed and cooperative cleanup did not complete.",
                            ) from cleanup_error
                        raise
                    if cleanup_permitted:
                        raise RequirementDocumentError(
                            "requirements.commit_indeterminate",
                            "Failure occurred after repository drift; cleanup was not attempted.",
                        ) from original
                    raise


class RequirementDocumentLoader:
    def verify_current(
        self, *, repository_root: Path, reference: RequirementDocRef
    ) -> str:
        current = _verify_current_document(
            repository_root=repository_root,
            reference=reference,
        )
        try:
            return current.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RequirementDocumentError(
                "requirements.document_invalid", "Document is not UTF-8."
            ) from error

    def load_approved(
        self, *, trace_store: ExecutionTraceStore, repository_root: Path,
        reference: RequirementDocRef,
        enforce_repository_source_freshness: bool = True,
    ) -> str:
        repository = _RepositoryRootAnchor.open(repository_root)
        try:
            repository.require_same_logical_location()
            before = _verify_current_document(
                repository_root=repository.root, reference=reference
            )
            repository.require_same_logical_location()
            RequirementApprovalGate().require_approved(
                trace_store=trace_store,
                repository_root=repository_root,
                reference=reference,
            )
            repository.require_same_logical_location()
            after = _verify_current_document(
                repository_root=repository.root, reference=reference
            )
            repository.require_same_logical_location()
            if before != after:
                raise RequirementDocumentError(
                    "requirements.document_worktree_drift",
                    "Document changed during approval lookup.",
                )
            try:
                markdown = after.decode("utf-8")
            except UnicodeDecodeError as error:
                raise RequirementDocumentError(
                    "requirements.document_invalid", "Document is not UTF-8."
                ) from error
            sources = _parse_requirement_document(markdown)
            if enforce_repository_source_freshness:
                _verify_repository_sources(
                    repository.root, sources, repository_anchor=repository
                )
            repository.require_same_logical_location()
            final = _verify_current_document(
                repository_root=repository.root, reference=reference
            )
            repository.require_same_logical_location()
            if final != after:
                raise RequirementDocumentError(
                    "requirements.document_changed_during_verification",
                    "Document changed during source verification.",
                )
            return final.decode("utf-8")
        finally:
            repository.close()
