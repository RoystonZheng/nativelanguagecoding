"""Typed S0 values and canonical JSON helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote, unquote_to_bytes
import uuid

from .errors import ContractError


SCHEMA_VERSION = "ai-native-devkit/v1alpha1"
PRODUCER = "ai-native-devkit/workflow-runtime@0.4.1"
ARTIFACT_TYPES = frozenset(
    {
        "task_request",
        "transition",
        "evidence_record",
        "init_report",
    }
)
REPOSITORY_SCOPE_PREFIX = "repository:v1:"
MAX_REPOSITORY_SCOPE_BYTES = 4096
REQUIREMENT_PATH = re.compile(
    r"^docs/superpowers/requirements/"
    r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*-requirements(?:-\d+)?\.md$"
)


def canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ContractError("Contract value is not canonical JSON.") from error
    return encoded.encode("utf-8")


def sha256_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class RequirementDocRef:
    path: str
    commit: str
    blob_digest: str
    extra: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not REQUIREMENT_PATH.fullmatch(self.path):
            raise ContractError("Requirement document path is invalid.")
        if not isinstance(self.commit, str) or not re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.commit
        ):
            raise ContractError("Requirement document commit is invalid.")
        expected = "git-sha1:" if len(self.commit) == 40 else "git-sha256:"
        oid_length = 40 if expected == "git-sha1:" else 64
        if not isinstance(self.blob_digest, str) or not re.fullmatch(
            re.escape(expected) + rf"[0-9a-f]{{{oid_length}}}", self.blob_digest
        ):
            raise ContractError("Requirement document blob digest is invalid.")
        if not isinstance(self.extra, Mapping) or any(
            not isinstance(key, str) or key in {"path", "commit", "blob_digest"}
            for key in self.extra
        ):
            raise ContractError("Requirement document extensions are invalid.")
        canonical_extra = canonical_json_bytes(_thaw_json(self.extra))
        if len(canonical_extra) > 16 * 1024:
            raise ContractError("Requirement document extensions are too large.")
        detached = json.loads(canonical_extra.decode("utf-8"))
        object.__setattr__(self, "extra", _freeze_json(detached))

    def to_dict(self) -> Dict[str, Any]:
        value = _thaw_json(self.extra)
        value.update(
            {
                "path": self.path,
                "commit": self.commit,
                "blob_digest": self.blob_digest,
            }
        )
        return value

    @classmethod
    def from_dict(cls, value: Any) -> "RequirementDocRef":
        required = {"path", "commit", "blob_digest"}
        if not isinstance(value, dict) or not required.issubset(value):
            raise ContractError("Requirement document reference is invalid.")
        if any(not isinstance(key, str) for key in value):
            raise ContractError("Requirement document extension keys are invalid.")
        extra = {key: item for key, item in value.items() if key not in required}
        return cls(value["path"], value["commit"], value["blob_digest"], extra)

    def subject_digest(self) -> str:
        return sha256_digest(canonical_json_bytes(self.to_dict()))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def encode_repository_scope(requested_scope: Optional[str]) -> str:
    """Encode an optional repository-relative scope as a canonical authority ID."""

    if requested_scope is None:
        path = "."
    else:
        _validate_repository_scope_path(requested_scope)
        path = requested_scope
    return REPOSITORY_SCOPE_PREFIX + quote(
        path,
        safe="/-._~",
        encoding="utf-8",
        errors="strict",
    )


def decode_repository_scope(value: Any) -> Optional[str]:
    """Decode and verify the canonical form of a repository authority scope."""

    if not isinstance(value, str) or not value.startswith(REPOSITORY_SCOPE_PREFIX):
        raise ContractError("Repository authority scope prefix is invalid.")
    encoded = value[len(REPOSITORY_SCOPE_PREFIX) :]
    if not encoded:
        raise ContractError("Repository authority scope is empty.")
    try:
        decoded_bytes = unquote_to_bytes(encoded)
        path = decoded_bytes.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise ContractError("Repository authority scope is not valid UTF-8.") from error
    if len(decoded_bytes) > MAX_REPOSITORY_SCOPE_BYTES:
        raise ContractError("Repository authority scope exceeds the size limit.")
    if path == ".":
        requested_scope = None
    else:
        _validate_repository_scope_path(path)
        requested_scope = path
    if encode_repository_scope(requested_scope) != value:
        raise ContractError("Repository authority scope is not canonically encoded.")
    return requested_scope


def _validate_repository_scope_path(value: Any) -> None:
    if not isinstance(value, str) or not value or value == "." or "\x00" in value:
        raise ContractError("Repository authority scope path is invalid.")
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError as error:
        raise ContractError("Repository authority scope path is not valid UTF-8.") from error
    if len(encoded) > MAX_REPOSITORY_SCOPE_BYTES:
        raise ContractError("Repository authority scope exceeds the size limit.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise ContractError("Repository authority scope path is not canonical.")


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    artifact_type: str
    digest: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ArtifactRef":
        if not isinstance(value, dict):
            raise ContractError("Artifact reference must be an object.")
        required = {"artifact_id", "artifact_type", "digest"}
        if not required.issubset(value):
            raise ContractError("Artifact reference is missing a required field.")
        if not all(isinstance(value[key], str) for key in required):
            raise ContractError("Artifact reference fields must be strings.")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value["digest"]):
            raise ContractError("Artifact reference digest must use sha256.")
        return cls(value["artifact_id"], value["artifact_type"], value["digest"])


@dataclass(frozen=True)
class LocalRef:
    name: str


@dataclass(frozen=True)
class RepositoryRevision:
    head_state: str
    head: Optional[str]
    branch: Optional[str]
    dirty: bool
    worktree_digest: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "head_state": self.head_state,
            "head": self.head,
            "branch": self.branch,
            "dirty": self.dirty,
            "worktree_digest": self.worktree_digest,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "RepositoryRevision":
        if not isinstance(value, dict):
            raise ContractError("Repository revision must be an object.")
        try:
            return cls(
                head_state=value["head_state"],
                head=value["head"],
                branch=value["branch"],
                dirty=value["dirty"],
                worktree_digest=value["worktree_digest"],
            )
        except KeyError as error:
            raise ContractError(
                "Repository revision is missing a required field."
            ) from error


@dataclass(frozen=True)
class ArtifactEnvelope:
    schema_version: str
    artifact_type: str
    artifact_id: str
    task_id: str
    created_at: str
    producer: str
    repo_revision: Optional[RepositoryRevision]
    input_refs: List[ArtifactRef]
    payload: Dict[str, Any]
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        value = dict(self.extra)
        value.update(
            {
                "schema_version": self.schema_version,
                "artifact_type": self.artifact_type,
                "artifact_id": self.artifact_id,
                "task_id": self.task_id,
                "created_at": self.created_at,
                "producer": self.producer,
                "repo_revision": (
                    self.repo_revision.to_dict() if self.repo_revision else None
                ),
                "input_refs": [reference.to_dict() for reference in self.input_refs],
                "payload": self.payload,
            }
        )
        return value

    @classmethod
    def from_dict(cls, value: Any) -> "ArtifactEnvelope":
        if not isinstance(value, dict):
            raise ContractError("Artifact envelope must be an object.")
        known = {
            "schema_version",
            "artifact_type",
            "artifact_id",
            "task_id",
            "created_at",
            "producer",
            "repo_revision",
            "input_refs",
            "payload",
        }
        if not known.issubset(value):
            raise ContractError("Artifact envelope is missing a required field.")
        if not isinstance(value["input_refs"], list) or not isinstance(
            value["payload"], dict
        ):
            raise ContractError("Artifact envelope collections are invalid.")
        return cls(
            schema_version=value["schema_version"],
            artifact_type=value["artifact_type"],
            artifact_id=value["artifact_id"],
            task_id=value["task_id"],
            created_at=value["created_at"],
            producer=value["producer"],
            repo_revision=(
                RepositoryRevision.from_dict(value["repo_revision"])
                if value["repo_revision"] is not None
                else None
            ),
            input_refs=[ArtifactRef.from_dict(item) for item in value["input_refs"]],
            payload=value["payload"],
            extra={key: item for key, item in value.items() if key not in known},
        )


@dataclass(frozen=True)
class TaskRequest:
    user_request: str
    requested_path: str
    observed_root: Optional[str]
    requested_scope: Optional[str]
    expected_revision: Optional[RepositoryRevision] = None
    constraints: Dict[str, Any] = field(
        default_factory=lambda: {
            "scope": None,
            "permissions": [],
            "destructive_actions": "denied",
        }
    )
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        if not isinstance(self.user_request, str) or not self.user_request:
            raise ContractError("TaskRequest.user_request must be a non-empty string.")
        return {
            "intent": "init",
            "user_request": self.user_request,
            "repository": {
                "requested_path": self.requested_path,
                "observed_root": self.observed_root,
                "requested_scope": self.requested_scope,
                "expected_revision": (
                    self.expected_revision.to_dict() if self.expected_revision else None
                ),
            },
            "constraints": self.constraints,
            "attachments": self.attachments,
        }


@dataclass(frozen=True)
class EvidenceRecord:
    observed_revision: Optional[RepositoryRevision]
    started_at: str
    duration_ms: int
    summary: str
    exit_status: str = "pass"
    kind: str = "inspection"
    invocation: str = "ai-native-devkit:init-inspection"
    artifact_refs: List[Any] = field(default_factory=list)
    authority_grant: Optional[Dict[str, Any]] = None

    def to_payload(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "invocation": self.invocation,
            "observed_revision": (
                self.observed_revision.to_dict() if self.observed_revision else None
            ),
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "exit_status": self.exit_status,
            "summary": self.summary,
            "artifact_refs": self.artifact_refs,
            "authority_grant": self.authority_grant,
        }


@dataclass(frozen=True)
class Transition:
    from_state: str
    to_state: str
    reason: str
    input_refs: List[Any]
    output_ref: Optional[Any]
    actor: str

    def to_payload(self) -> Dict[str, Any]:
        return {
            "from": self.from_state,
            "to": self.to_state,
            "reason": self.reason,
            "input_refs": self.input_refs,
            "output_ref": self.output_ref,
            "actor": self.actor,
        }


@dataclass(frozen=True)
class InitReport:
    repository: Dict[str, Any]
    sources: List[Dict[str, Any]]
    findings: Dict[str, List[str]]
    gaps: List[str]
    outcome: str
    blocker: Optional[Dict[str, Any]]
    task_request_ref: Any
    transition_ref: Any
    evidence_refs: List[Any]
    supersedes: Optional[Any] = None
    instruction_selection: Optional[Dict[str, Any]] = None

    def to_payload(self) -> Dict[str, Any]:
        if self.outcome not in {"ready", "blocked"}:
            raise ContractError("InitReport outcome must be ready or blocked.")
        if (self.outcome == "ready") != (self.blocker is None):
            raise ContractError("InitReport blocker does not match its outcome.")
        payload = {
            "repository": self.repository,
            "sources": self.sources,
            "findings": self.findings,
            "gaps": self.gaps,
            "outcome": self.outcome,
            "blocker": self.blocker,
            "artifact_refs": {
                "task_request": self.task_request_ref,
                "transition": self.transition_ref,
                "evidence": self.evidence_refs,
            },
            "supersedes": self.supersedes,
        }
        if self.instruction_selection is not None:
            payload["instruction_selection"] = self.instruction_selection
        return payload


@dataclass(frozen=True)
class ArtifactDraft:
    local_ref: str
    artifact_type: str
    payload: Dict[str, Any]


@dataclass(frozen=True)
class TransitionIntent:
    local_ref: str
    to_state: str
    reason: str
    input_refs: List[Any]
    output_ref: Optional[Any]
    actor: str


@dataclass(frozen=True)
class TaskCommit:
    task_id: str
    expected_store_version: Optional[str]
    operation_id: str
    artifact_drafts: List[ArtifactDraft]
    transition_intent: Optional[TransitionIntent]


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    store_version: str
    lifecycle_state: str
    resume_state: Optional[str]
    artifacts: List[Dict[str, Any]]
    latest_report_ref: Optional[ArtifactRef]


@dataclass(frozen=True)
class CommitReceipt:
    task_id: str
    store_version: str
    materialized_refs: Dict[str, ArtifactRef]
    transition_ref: Optional[ArtifactRef]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "store_version": self.store_version,
            "materialized_refs": {
                key: value.to_dict() for key, value in self.materialized_refs.items()
            },
            "transition_ref": (
                self.transition_ref.to_dict() if self.transition_ref else None
            ),
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "CommitReceipt":
        return cls(
            task_id=value["task_id"],
            store_version=value["store_version"],
            materialized_refs={
                key: ArtifactRef.from_dict(reference)
                for key, reference in value["materialized_refs"].items()
            },
            transition_ref=(
                ArtifactRef.from_dict(value["transition_ref"])
                if value["transition_ref"] is not None
                else None
            ),
        )


def make_envelope(
    artifact_type: str,
    task_id: str,
    payload: Dict[str, Any],
    repo_revision: Optional[RepositoryRevision],
    input_refs: List[ArtifactRef],
    producer: str,
) -> Dict[str, Any]:
    if artifact_type not in ARTIFACT_TYPES:
        raise ContractError("Artifact type is not registered.")
    return ArtifactEnvelope(
        schema_version=SCHEMA_VERSION,
        artifact_type=artifact_type,
        artifact_id=str(uuid.uuid4()),
        task_id=task_id,
        created_at=utc_now(),
        producer=producer,
        repo_revision=repo_revision,
        input_refs=input_refs,
        payload=payload,
    ).to_dict()


def reference_for(envelope: Dict[str, Any]) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=envelope["artifact_id"],
        artifact_type=envelope["artifact_type"],
        digest=sha256_digest(canonical_json_bytes(envelope)),
    )
