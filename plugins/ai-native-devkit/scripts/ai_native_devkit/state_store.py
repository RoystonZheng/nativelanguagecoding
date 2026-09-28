"""Shared TaskStateStore policy over atomic byte adapters."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import PurePosixPath
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import uuid

from .contracts import (
    ARTIFACT_TYPES,
    PRODUCER,
    REPOSITORY_SCOPE_PREFIX,
    SCHEMA_VERSION,
    ArtifactDraft,
    ArtifactRef,
    CommitReceipt,
    LocalRef,
    RepositoryRevision,
    TaskCommit,
    TaskSnapshot,
    Transition,
    canonical_json_bytes,
    decode_repository_scope,
    make_envelope,
    reference_for,
    sha256_digest,
)
from .errors import ContractError, StoreError
from .persistence import PersistenceConflict
from .instruction_selection import validate_instruction_selection, validate_instruction_differences


TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ALLOWED_TRANSITIONS = {
    ("Intake", "ContextReady"),
    ("Intake", "Blocked"),
    ("Blocked", "Intake"),
}
FORBIDDEN_PERSISTED_KEYS = {
    "chain_of_thought",
    "context_bundle",
    "documentation_patch_plan",
    "hidden_reasoning",
    "private_reasoning",
    "raw_source_contents",
    "raw_source_content",
    "raw_command_output",
    "rendered_markdown",
    "route_decision",
    "cookie",
    "cookies",
    "authorization",
}
FORBIDDEN_INIT_REPORT_KEYS = {
    "context_bundle",
    "documentation_patch_plan",
    "rendered_markdown",
    "report_id",
    "route_decision",
}
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(token|password|passwd|secret|api[_-]?key)\s*[:=]\s*([^\s,;]+)"
)
BEARER_CREDENTIAL = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
PREFIX_CREDENTIAL = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_-]{8,})\b"
)
SLACK_CREDENTIAL = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}\b")
JWT_CREDENTIAL = re.compile(
    r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
COOKIE_CREDENTIAL = re.compile(
    r"(?im)\b(set-cookie|cookie)(\s*[:=]\s*)[^\r\n]*"
)
MAX_ARTIFACT_PAYLOAD_BYTES = 256 * 1024


class _MissingTask:
    pass


MISSING = _MissingTask()


def validate_task_id(task_id: str) -> None:
    if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
        raise ContractError("Task identifier is invalid.")
    if (
        PREFIX_CREDENTIAL.search(task_id)
        or SLACK_CREDENTIAL.search(task_id)
        or JWT_CREDENTIAL.search(task_id)
    ):
        raise ContractError("Task identifier resembles a credential and is unsafe.")


def _normalized_key(key: str) -> str:
    with_word_boundaries = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[^a-z0-9]+", "_", with_word_boundaries.lower()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalized_key(key)
    parts = set(normalized.split("_"))
    if parts.intersection({"token", "password", "passwd", "secret", "credential", "credentials"}):
        return True
    return normalized in {"api_key", "access_key", "private_key"} or normalized.endswith(
        ("_api_key", "_access_key", "_private_key")
    )


def redact_persisted_text(value: str) -> str:
    """Apply the single persistence redaction policy to free-form text."""

    value = COOKIE_CREDENTIAL.sub(
        lambda match: match.group(1) + match.group(2) + "[REDACTED]",
        value,
    )
    value = SENSITIVE_ASSIGNMENT.sub(
        lambda match: match.group(1) + "=[REDACTED]", value
    )
    value = BEARER_CREDENTIAL.sub("Bearer [REDACTED]", value)
    value = PREFIX_CREDENTIAL.sub("[REDACTED]", value)
    value = SLACK_CREDENTIAL.sub("[REDACTED]", value)
    return JWT_CREDENTIAL.sub("[REDACTED]", value)


def sanitize_persisted_value(value: Any) -> Any:
    """Return the exact representation accepted at the persistence boundary."""

    if isinstance(value, str):
        return redact_persisted_text(value)
    if isinstance(value, list):
        return [sanitize_persisted_value(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("Persisted object keys must be strings.")
            if redact_persisted_text(key) != key:
                raise ContractError("Persisted object key contains sensitive content.")
            normalized = _normalized_key(key)
            if normalized in FORBIDDEN_PERSISTED_KEYS:
                raise ContractError("Contract contains a forbidden persisted field.")
            if _is_sensitive_key(key):
                result[key] = "[REDACTED]"
            else:
                result[key] = sanitize_persisted_value(item)
        return result
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, LocalRef):
        return {"$local_ref": value.name}
    if isinstance(value, ArtifactRef):
        return value.to_dict()
    if isinstance(value, RepositoryRevision):
        return value.to_dict()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _commit_fingerprint(commit: TaskCommit) -> str:
    value = {
        "task_id": commit.task_id,
        "expected_store_version": commit.expected_store_version,
        "operation_id": commit.operation_id,
        "artifact_drafts": [
            {
                "local_ref": draft.local_ref,
                "artifact_type": draft.artifact_type,
                "payload": _jsonable(draft.payload),
            }
            for draft in commit.artifact_drafts
        ],
        "transition_intent": (
            {
                "local_ref": commit.transition_intent.local_ref,
                "to": commit.transition_intent.to_state,
                "reason": commit.transition_intent.reason,
                "input_refs": _jsonable(commit.transition_intent.input_refs),
                "output_ref": _jsonable(commit.transition_intent.output_ref),
                "actor": commit.transition_intent.actor,
            }
            if commit.transition_intent
            else None
        ),
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _local_dependencies(value: Any) -> Set[str]:
    if isinstance(value, LocalRef):
        return {value.name}
    if isinstance(value, list):
        result: Set[str] = set()
        for item in value:
            result.update(_local_dependencies(item))
        return result
    if isinstance(value, dict):
        result = set()
        for item in value.values():
            result.update(_local_dependencies(item))
        return result
    return set()


def _resolve(value: Any, materialized: Dict[str, ArtifactRef]) -> Any:
    if isinstance(value, LocalRef):
        try:
            return materialized[value.name].to_dict()
        except KeyError as error:
            raise ContractError("Commit contains an unresolved local reference.") from error
    if isinstance(value, ArtifactRef):
        return value.to_dict()
    if isinstance(value, list):
        return [_resolve(item, materialized) for item in value]
    if isinstance(value, dict):
        return {key: _resolve(item, materialized) for key, item in value.items()}
    return value


def _deduplicate_refs(values: Iterable[Any]) -> List[ArtifactRef]:
    result: List[ArtifactRef] = []
    seen = set()
    for value in values:
        if value is None:
            continue
        reference = ArtifactRef.from_dict(value)
        key = (reference.artifact_id, reference.artifact_type, reference.digest)
        if key not in seen:
            seen.add(key)
            result.append(reference)
    return result


def _payload_input_refs(artifact_type: str, payload: Dict[str, Any]) -> List[ArtifactRef]:
    if artifact_type == "task_request":
        return []
    if artifact_type == "evidence_record":
        return _deduplicate_refs(payload.get("artifact_refs", []))
    if artifact_type == "transition":
        return _deduplicate_refs(
            list(payload.get("input_refs", [])) + [payload.get("output_ref")]
        )
    if artifact_type == "init_report":
        named = payload.get("artifact_refs", {})
        return _deduplicate_refs(
            [named.get("task_request"), named.get("transition")]
            + list(named.get("evidence", []))
            + [payload.get("supersedes")]
            + ([payload["instruction_selection"]["report_ref"]] if payload.get("instruction_selection") else [])
        )
    raise ContractError("Artifact type is not registered.")


class TaskStateStore:
    def __init__(self, persistence):
        self._persistence = persistence

    def load(self, task_id: str):
        validate_task_id(task_id)
        raw = self._load_raw(task_id)
        if raw is None:
            return MISSING
        manifest = self._decode_manifest(task_id, raw)
        latest = manifest["latest_report_ref"]
        return TaskSnapshot(
            task_id=task_id,
            store_version=manifest["store_version"],
            lifecycle_state=manifest["lifecycle_state"],
            resume_state=manifest["resume_state"],
            artifacts=manifest["artifacts"],
            latest_report_ref=ArtifactRef.from_dict(latest) if latest else None,
        )

    def commit(self, commit: TaskCommit) -> CommitReceipt:
        validate_task_id(commit.task_id)
        if not commit.operation_id or len(commit.operation_id) > 200:
            raise ContractError("Operation identifier is invalid.")
        commit = self._sanitize_commit(commit)

        raw = self._load_raw(commit.task_id)
        manifest = (
            self._decode_manifest(commit.task_id, raw) if raw is not None else None
        )
        fingerprint = _commit_fingerprint(commit)
        if manifest is not None and commit.operation_id in manifest["operations"]:
            recorded = manifest["operations"][commit.operation_id]
            if recorded["fingerprint"] != fingerprint:
                raise StoreError(
                    "rejected.idempotency_conflict",
                    "Operation identifier was reused with different content.",
                    retryable=False,
                )
            return CommitReceipt.from_dict(recorded["receipt"])

        if manifest is None:
            if commit.expected_store_version is not None:
                raise StoreError(
                    "rejected.concurrent_update",
                    "Task state changed before the commit.",
                    retryable=True,
                )
            self._validate_creation(commit)
            current_state = "Intake"
            resume_state = None
            artifacts: List[Dict[str, Any]] = []
            operations: Dict[str, Any] = {}
            version_number = 0
        else:
            if commit.expected_store_version != manifest["store_version"]:
                raise StoreError(
                    "rejected.concurrent_update",
                    "Task state changed before the commit.",
                    retryable=True,
                )
            current_state = manifest["lifecycle_state"]
            resume_state = manifest["resume_state"]
            artifacts = list(manifest["artifacts"])
            operations = dict(manifest["operations"])
            version_number = int(manifest["store_version"].split(":", 1)[1])
            if any(draft.artifact_type == "task_request" for draft in commit.artifact_drafts):
                raise ContractError("TaskRequest is immutable and may only be created once.")

        existing_refs = {
            envelope["artifact_id"]: reference_for(envelope) for envelope in artifacts
        }
        new_envelopes, materialized, transition_ref, next_state, next_resume = (
            self._materialize(
                commit,
                current_state,
                resume_state,
                existing_refs,
            )
        )
        self._validate_batch_invariants(
            commit,
            current_state,
            artifacts,
            new_envelopes,
            transition_ref,
        )
        artifacts.extend(new_envelopes)
        latest_report_ref = None
        for envelope in artifacts:
            if envelope["artifact_type"] == "init_report":
                latest_report_ref = reference_for(envelope).to_dict()

        new_version = "v1:" + str(version_number + 1)
        receipt = CommitReceipt(
            task_id=commit.task_id,
            store_version=new_version,
            materialized_refs=materialized,
            transition_ref=transition_ref,
        )
        operations[commit.operation_id] = {
            "fingerprint": fingerprint,
            "receipt": receipt.to_dict(),
        }
        replacement_manifest = {
            "schema_version": SCHEMA_VERSION,
            "task_id": commit.task_id,
            "store_version": new_version,
            "lifecycle_state": next_state,
            "resume_state": next_resume,
            "artifacts": artifacts,
            "latest_report_ref": latest_report_ref,
            "operations": operations,
        }
        replacement_manifest["integrity"] = {
            "digest": sha256_digest(canonical_json_bytes(replacement_manifest))
        }
        replacement = canonical_json_bytes(replacement_manifest)
        try:
            self._persistence.compare_and_commit(commit.task_id, raw, replacement)
        except PersistenceConflict as error:
            recovered = self._recover_receipt(commit, fingerprint)
            if recovered is not None:
                return recovered
            raise StoreError(
                "rejected.concurrent_update",
                "Task state changed before the commit.",
                retryable=True,
            ) from error
        except Exception as error:
            try:
                recovered = self._recover_receipt(commit, fingerprint)
            except StoreError:
                raise
            except Exception as reload_error:
                raise StoreError(
                    "persistence.write_failed",
                    "Task state could not be committed or safely recovered.",
                    retryable=True,
                ) from reload_error
            if recovered is not None:
                return recovered
            raise StoreError(
                "persistence.write_failed",
                "Task state could not be committed or safely recovered.",
                retryable=True,
            ) from error
        return receipt

    def _sanitize_commit(self, commit: TaskCommit) -> TaskCommit:
        if (
            not isinstance(commit.operation_id, str)
            or self._redact_text(commit.operation_id) != commit.operation_id
            or _is_sensitive_key(commit.operation_id)
        ):
            raise ContractError("Operation identifier contains sensitive content.")
        local_names = [draft.local_ref for draft in commit.artifact_drafts]
        if commit.transition_intent is not None:
            local_names.append(commit.transition_intent.local_ref)
        if any(
            not isinstance(name, str)
            or self._redact_text(name) != name
            or _is_sensitive_key(name)
            for name in local_names
        ):
            raise ContractError("Commit local reference contains sensitive content.")
        drafts = [
            ArtifactDraft(
                local_ref=draft.local_ref,
                artifact_type=draft.artifact_type,
                payload=self._sanitize_value(draft.payload),
            )
            for draft in commit.artifact_drafts
        ]
        intent = commit.transition_intent
        if intent is not None:
            intent = type(intent)(
                local_ref=intent.local_ref,
                to_state=intent.to_state,
                reason=self._redact_text(intent.reason),
                input_refs=self._sanitize_value(intent.input_refs),
                output_ref=self._sanitize_value(intent.output_ref),
                actor=intent.actor,
            )
        return TaskCommit(
            task_id=commit.task_id,
            expected_store_version=commit.expected_store_version,
            operation_id=commit.operation_id,
            artifact_drafts=drafts,
            transition_intent=intent,
        )

    def _sanitize_value(self, value: Any) -> Any:
        return sanitize_persisted_value(value)

    def _redact_text(self, value: str) -> str:
        return redact_persisted_text(value)

    def _recover_receipt(
        self, commit: TaskCommit, fingerprint: str
    ) -> Optional[CommitReceipt]:
        winner_raw = self._load_raw(commit.task_id)
        if winner_raw is None:
            return None
        winner = self._decode_manifest(commit.task_id, winner_raw)
        recorded = winner["operations"].get(commit.operation_id)
        if recorded is None:
            return None
        if recorded["fingerprint"] != fingerprint:
            raise StoreError(
                "rejected.idempotency_conflict",
                "Operation identifier was reused with different content.",
                retryable=False,
            )
        return CommitReceipt.from_dict(recorded["receipt"])

    def _load_raw(self, task_id: str) -> Optional[bytes]:
        try:
            return self._persistence.load_bytes(task_id)
        except StoreError:
            raise
        except Exception as error:
            raise StoreError(
                "persistence.read_failed",
                "Task state could not be read safely.",
                retryable=True,
            ) from error

    def _validate_batch_invariants(
        self,
        commit: TaskCommit,
        current_state: str,
        existing_envelopes: List[Dict[str, Any]],
        envelopes: List[Dict[str, Any]],
        transition_ref: Optional[ArtifactRef],
    ) -> None:
        reports = [
            envelope
            for envelope in envelopes
            if envelope["artifact_type"] == "init_report"
        ]
        if len(reports) > 1:
            raise ContractError("A TaskCommit may contain only one InitReport.")
        intent = commit.transition_intent
        latest_existing_report = next(
            (
                reference_for(envelope)
                for envelope in reversed(existing_envelopes)
                if envelope["artifact_type"] == "init_report"
            ),
            None,
        )
        new_evidence_ids = {
            envelope["artifact_id"]
            for envelope in envelopes
            if envelope["artifact_type"] == "evidence_record"
        }
        if reports:
            report = reports[0]["payload"]
            expected_supersedes = (
                latest_existing_report.to_dict()
                if latest_existing_report is not None
                else None
            )
            if report["supersedes"] != expected_supersedes:
                raise ContractError(
                    "InitReport supersedes must reference the latest prior report."
                )
            report_evidence = [
                ArtifactRef.from_dict(reference)
                for reference in report["artifact_refs"]["evidence"]
            ]
            if not any(
                reference.artifact_id in new_evidence_ids
                for reference in report_evidence
            ):
                raise ContractError(
                    "Each InitReport requires fresh evidence in the same commit."
                )
        if intent is not None and intent.to_state in {"ContextReady", "Blocked"}:
            if len(reports) != 1 or transition_ref is None:
                raise ContractError(
                    "A readiness transition requires an InitReport in the same commit."
                )
            expected_outcome = (
                "ready" if intent.to_state == "ContextReady" else "blocked"
            )
            report = reports[0]["payload"]
            if report["outcome"] != expected_outcome:
                raise ContractError(
                    "InitReport outcome does not match the lifecycle transition."
                )
            if ArtifactRef.from_dict(
                report["artifact_refs"]["transition"]
            ) != transition_ref:
                raise ContractError(
                    "InitReport must reference its lifecycle transition."
                )
        elif reports:
            report = reports[0]["payload"]
            if current_state != "Blocked" or report["outcome"] != "blocked":
                raise ContractError(
                    "An InitReport without a new transition is valid only for a blocked retry."
                )
            establishing_transition = next(
                (
                    reference_for(envelope)
                    for envelope in reversed(existing_envelopes)
                    if envelope["artifact_type"] == "transition"
                    and envelope["payload"]["to"] == "Blocked"
                ),
                None,
            )
            if establishing_transition is None or ArtifactRef.from_dict(
                report["artifact_refs"]["transition"]
            ) != establishing_transition:
                raise ContractError(
                    "Blocked retry must reference the transition that established the current block."
                )

    def _validate_creation(self, commit: TaskCommit) -> None:
        if commit.transition_intent is not None:
            raise ContractError("Task creation cannot fabricate an Intake transition.")
        if len(commit.artifact_drafts) != 1:
            raise ContractError("Task creation must contain exactly one TaskRequest.")
        if commit.artifact_drafts[0].artifact_type != "task_request":
            raise ContractError("Task creation must contain exactly one TaskRequest.")

    def _materialize(
        self,
        commit: TaskCommit,
        current_state: str,
        resume_state: Optional[str],
        existing_refs: Dict[str, ArtifactRef],
    ) -> Tuple[
        List[Dict[str, Any]],
        Dict[str, ArtifactRef],
        Optional[ArtifactRef],
        str,
        Optional[str],
    ]:
        local_names = [draft.local_ref for draft in commit.artifact_drafts]
        if commit.transition_intent:
            local_names.append(commit.transition_intent.local_ref)
        if len(local_names) != len(set(local_names)) or any(not name for name in local_names):
            raise ContractError("Commit local references must be unique and non-empty.")

        pending = {draft.local_ref: draft for draft in commit.artifact_drafts}
        materialized: Dict[str, ArtifactRef] = {}
        envelopes: List[Dict[str, Any]] = []
        transition_pending = commit.transition_intent
        transition_ref = None
        next_state = current_state
        next_resume = resume_state

        while pending or transition_pending:
            progressed = False
            if transition_pending is not None:
                dependencies = _local_dependencies(transition_pending.input_refs)
                dependencies.update(_local_dependencies(transition_pending.output_ref))
                if dependencies.issubset(materialized):
                    if (current_state, transition_pending.to_state) not in ALLOWED_TRANSITIONS:
                        raise ContractError("Requested lifecycle transition is invalid.")
                    payload = Transition(
                        from_state=current_state,
                        to_state=transition_pending.to_state,
                        reason=transition_pending.reason,
                        input_refs=_resolve(
                            transition_pending.input_refs, materialized
                        ),
                        output_ref=_resolve(
                            transition_pending.output_ref, materialized
                        ),
                        actor=transition_pending.actor,
                    ).to_payload()
                    self._validate_payload("transition", payload)
                    inputs = _payload_input_refs("transition", payload)
                    self._validate_references(inputs, existing_refs, materialized)
                    envelope = make_envelope(
                        "transition",
                        commit.task_id,
                        payload,
                        None,
                        inputs,
                        "ai-native-devkit/task-state-store@0.4.1",
                    )
                    transition_ref = reference_for(envelope)
                    materialized[transition_pending.local_ref] = transition_ref
                    envelopes.append(envelope)
                    if transition_pending.to_state == "Blocked":
                        next_resume = current_state
                    elif current_state == "Blocked":
                        next_resume = None
                    next_state = transition_pending.to_state
                    transition_pending = None
                    progressed = True

            for local_name, draft in list(pending.items()):
                dependencies = _local_dependencies(draft.payload)
                if dependencies.issubset(materialized):
                    if draft.artifact_type not in ARTIFACT_TYPES:
                        raise ContractError("Artifact type is not registered.")
                    if draft.artifact_type == "transition":
                        raise ContractError(
                            "Transition artifacts must be created from transition_intent."
                        )
                    payload = _resolve(draft.payload, materialized)
                    self._validate_payload(draft.artifact_type, payload)
                    inputs = _payload_input_refs(draft.artifact_type, payload)
                    self._validate_references(inputs, existing_refs, materialized)
                    repo_revision = None
                    if draft.artifact_type == "init_report":
                        repo_revision = self._optional_revision_from_dict(
                            payload["repository"]["revision"]
                        )
                    if draft.artifact_type == "evidence_record":
                        repo_revision = self._optional_revision_from_dict(
                            payload["observed_revision"]
                        )
                    if draft.artifact_type == "task_request":
                        repo_revision = None
                    envelope = make_envelope(
                        draft.artifact_type,
                        commit.task_id,
                        payload,
                        repo_revision,
                        inputs,
                        PRODUCER,
                    )
                    reference = reference_for(envelope)
                    materialized[local_name] = reference
                    envelopes.append(envelope)
                    del pending[local_name]
                    progressed = True
            if not progressed:
                raise ContractError("Commit contains cyclic or missing local references.")

        if commit.transition_intent is None:
            next_state = current_state
            next_resume = resume_state
        return envelopes, materialized, transition_ref, next_state, next_resume

    def _optional_revision_from_dict(
        self, value: Any
    ) -> Optional[RepositoryRevision]:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ContractError("Repository revision must be an object.")
        try:
            revision = RepositoryRevision(
                head_state=value["head_state"],
                head=value["head"],
                branch=value["branch"],
                dirty=value["dirty"],
                worktree_digest=value["worktree_digest"],
            )
        except KeyError as error:
            raise ContractError("Repository revision is missing a required field.") from error
        if revision.head_state not in {"attached", "detached", "unborn"}:
            raise ContractError("Repository head state is invalid.")
        if not isinstance(revision.dirty, bool):
            raise ContractError("Repository dirty flag must be boolean.")
        if revision.head_state == "unborn":
            if revision.head is not None or revision.branch is not None:
                raise ContractError("An unborn repository cannot have head or branch.")
        else:
            if not isinstance(revision.head, str) or not re.fullmatch(
                r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision.head
            ):
                raise ContractError("Repository head must be a Git object identifier.")
            if revision.head_state == "attached":
                if not isinstance(revision.branch, str) or not revision.branch:
                    raise ContractError("An attached repository requires a branch.")
            elif revision.branch is not None:
                raise ContractError("A detached repository cannot have a branch.")
        digest_required = revision.dirty or revision.head_state == "unborn"
        if digest_required:
            if not isinstance(revision.worktree_digest, str) or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", revision.worktree_digest
            ):
                raise ContractError(
                    "Dirty and unborn repositories require a worktree digest."
                )
        elif revision.worktree_digest is not None:
            raise ContractError(
                "A clean established repository must not carry a worktree digest."
            )
        return revision

    def _validate_references(
        self,
        references: List[ArtifactRef],
        existing_refs: Dict[str, ArtifactRef],
        materialized: Dict[str, ArtifactRef],
    ) -> None:
        available = dict(existing_refs)
        available.update(
            {reference.artifact_id: reference for reference in materialized.values()}
        )
        for reference in references:
            if available.get(reference.artifact_id) != reference:
                raise ContractError("Artifact reference is invalid for this task.")

    def _decode_manifest(self, task_id: str, raw: bytes) -> Dict[str, Any]:
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StoreError(
                "state.corrupt",
                "Persisted task state is corrupt.",
                retryable=False,
            ) from error
        try:
            if not isinstance(manifest, dict):
                raise ContractError("Persisted task state must be an object.")
            self._validate_persisted_safety(manifest)
            integrity = manifest.get("integrity")
            if not isinstance(integrity, dict) or set(integrity) != {"digest"}:
                raise ContractError("Persisted task integrity record is invalid.")
            unsigned_manifest = dict(manifest)
            del unsigned_manifest["integrity"]
            expected_integrity = sha256_digest(
                canonical_json_bytes(unsigned_manifest)
            )
            if integrity["digest"] != expected_integrity:
                raise ContractError("Persisted task integrity check failed.")
            if manifest["schema_version"] != SCHEMA_VERSION:
                raise ContractError("Persisted schema version is incompatible.")
            if manifest["task_id"] != task_id:
                raise ContractError("Persisted task identifier does not match.")
            artifacts = manifest["artifacts"]
            if not isinstance(artifacts, list):
                raise ContractError("Persisted artifacts must be a list.")
            references: Dict[str, ArtifactRef] = {}
            task_requests = 0
            latest_report = None
            state = "Intake"
            resume_state = None
            for envelope in artifacts:
                self._validate_envelope(task_id, envelope)
                self._validate_payload(envelope["artifact_type"], envelope["payload"])
                reference = reference_for(envelope)
                if reference.artifact_id in references:
                    raise ContractError("Persisted artifact identifiers must be unique.")
                references[reference.artifact_id] = reference
                inputs = _payload_input_refs(
                    envelope["artifact_type"], envelope["payload"]
                )
                if envelope["input_refs"] != [item.to_dict() for item in inputs]:
                    raise ContractError("Persisted artifact input references drifted.")
                for input_reference in inputs:
                    if references.get(input_reference.artifact_id) != input_reference:
                        raise ContractError("Persisted artifact reference is invalid.")
                if envelope["artifact_type"] == "task_request":
                    task_requests += 1
                elif envelope["artifact_type"] == "transition":
                    payload = envelope["payload"]
                    if payload["from"] != state or (
                        payload["from"], payload["to"]
                    ) not in ALLOWED_TRANSITIONS:
                        raise ContractError("Persisted lifecycle transition is invalid.")
                    if payload["to"] == "Blocked":
                        resume_state = state
                    elif state == "Blocked":
                        resume_state = None
                    state = payload["to"]
                elif envelope["artifact_type"] == "init_report":
                    latest_report = reference.to_dict()
            if task_requests != 1:
                raise ContractError("Persisted task must contain one TaskRequest.")
            if manifest["lifecycle_state"] != state:
                raise ContractError("Persisted lifecycle projection is invalid.")
            if manifest["resume_state"] != resume_state:
                raise ContractError("Persisted resume projection is invalid.")
            if manifest["latest_report_ref"] != latest_report:
                raise ContractError("Persisted latest report projection is invalid.")
            if not isinstance(manifest["operations"], dict):
                raise ContractError("Persisted operations must be an object.")
            artifact_versions, artifact_operation_ids = self._validate_operations(
                task_id,
                manifest["store_version"],
                manifest["operations"],
                references,
            )
            self._validate_artifact_history(
                artifacts, artifact_versions, artifact_operation_ids
            )
            return manifest
        except (KeyError, TypeError, ValueError, ContractError) as error:
            raise StoreError(
                "state.corrupt",
                "Persisted task state is corrupt.",
                retryable=False,
            ) from error

    def _validate_persisted_safety(self, value: Any) -> None:
        if isinstance(value, str):
            if self._redact_text(value) != value:
                raise ContractError("Persisted state contains unredacted content.")
            return
        if isinstance(value, list):
            for item in value:
                self._validate_persisted_safety(item)
            return
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("Persisted object keys must be strings.")
            if self._redact_text(key) != key:
                raise ContractError("Persisted object key contains sensitive content.")
            normalized = _normalized_key(key)
            if normalized in FORBIDDEN_PERSISTED_KEYS:
                raise ContractError("Persisted state contains a forbidden field.")
            if _is_sensitive_key(key):
                if item != "[REDACTED]":
                    raise ContractError(
                        "Persisted state contains an unredacted sensitive field."
                    )
                continue
            self._validate_persisted_safety(item)

    def _validate_envelope(self, task_id: str, envelope: Any) -> None:
        if not isinstance(envelope, dict):
            raise ContractError("Artifact envelope must be an object.")
        if envelope.get("schema_version") != SCHEMA_VERSION:
            raise ContractError("Artifact schema version is incompatible.")
        if envelope.get("artifact_type") not in ARTIFACT_TYPES:
            raise ContractError("Artifact type is not registered.")
        if envelope.get("task_id") != task_id:
            raise ContractError("Artifact belongs to a different task.")
        for key in ("artifact_id", "created_at", "producer"):
            if not isinstance(envelope.get(key), str) or not envelope[key]:
                raise ContractError("Artifact envelope field is invalid.")
        try:
            parsed_artifact_id = uuid.UUID(envelope["artifact_id"])
        except ValueError as error:
            raise ContractError("Artifact identifier must be a UUID.") from error
        if str(parsed_artifact_id) != envelope["artifact_id"]:
            raise ContractError("Artifact identifier must use canonical UUID form.")
        self._validate_timestamp(envelope["created_at"])
        if len(envelope["producer"]) > 200:
            raise ContractError("Artifact producer exceeds the size limit.")
        if not isinstance(envelope.get("input_refs"), list):
            raise ContractError("Artifact input_refs must be a list.")
        for value in envelope["input_refs"]:
            ArtifactRef.from_dict(value)
        if not isinstance(envelope.get("payload"), dict):
            raise ContractError("Artifact payload must be an object.")
        repo_revision = self._optional_revision_from_dict(
            envelope.get("repo_revision")
        )
        artifact_type = envelope["artifact_type"]
        if artifact_type in {
            "task_request",
            "transition",
        } and repo_revision is not None:
            raise ContractError(
                "This artifact producer cannot claim a repository observation."
            )
        if artifact_type == "evidence_record":
            if envelope["payload"].get("observed_revision") != _jsonable(
                repo_revision
            ):
                raise ContractError(
                    "EvidenceRecord revision must match its envelope revision."
                )
        if artifact_type == "init_report":
            repository = envelope["payload"].get("repository")
            if not isinstance(repository, dict) or repository.get(
                "revision"
            ) != _jsonable(repo_revision):
                raise ContractError(
                    "InitReport revision must match its envelope revision."
                )

    def _validate_operations(
        self,
        task_id: str,
        current_store_version: Any,
        operations: Dict[str, Any],
        references: Dict[str, ArtifactRef],
    ) -> Tuple[Dict[str, int], Dict[str, str]]:
        current_match = (
            re.fullmatch(r"v1:([1-9][0-9]*)", current_store_version)
            if isinstance(current_store_version, str)
            else None
        )
        if current_match is None:
            raise ContractError("Persisted store version is invalid.")
        current_number = int(current_match.group(1))
        if len(operations) != current_number:
            raise ContractError("Persisted operation count does not match its version.")
        observed_versions = set()
        artifact_versions: Dict[str, int] = {}
        artifact_operation_ids: Dict[str, str] = {}
        for operation_id, record in operations.items():
            if not isinstance(operation_id, str) or not operation_id:
                raise ContractError("Persisted operation identifier is invalid.")
            if not isinstance(record, dict) or not {
                "fingerprint",
                "receipt",
            }.issubset(record):
                raise ContractError("Persisted operation record is invalid.")
            if not isinstance(record["fingerprint"], str) or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", record["fingerprint"]
            ):
                raise ContractError("Persisted operation fingerprint is invalid.")
            receipt = CommitReceipt.from_dict(record["receipt"])
            if receipt.task_id != task_id:
                raise ContractError("Persisted receipt belongs to a different task.")
            version_match = re.fullmatch(r"v1:([1-9][0-9]*)", receipt.store_version)
            if version_match is None:
                raise ContractError("Persisted receipt version is invalid.")
            version_number = int(version_match.group(1))
            if version_number > current_number or version_number in observed_versions:
                raise ContractError("Persisted receipt version history is invalid.")
            observed_versions.add(version_number)
            for reference in receipt.materialized_refs.values():
                if references.get(reference.artifact_id) != reference:
                    raise ContractError("Persisted receipt reference is invalid.")
                if reference.artifact_id in artifact_versions:
                    raise ContractError(
                        "Persisted artifact is claimed by multiple operations."
                    )
                artifact_versions[reference.artifact_id] = version_number
                artifact_operation_ids[reference.artifact_id] = operation_id
            if receipt.transition_ref is not None:
                if receipt.transition_ref.artifact_type != "transition":
                    raise ContractError("Persisted transition receipt type is invalid.")
                if references.get(receipt.transition_ref.artifact_id) != receipt.transition_ref:
                    raise ContractError("Persisted transition receipt is invalid.")
                if receipt.transition_ref not in receipt.materialized_refs.values():
                    raise ContractError(
                        "Persisted transition receipt is missing its local reference."
                    )
        if observed_versions != set(range(1, current_number + 1)):
            raise ContractError("Persisted receipt version history is incomplete.")
        if set(artifact_versions) != set(references):
            raise ContractError(
                "Persisted operation history does not account for every artifact."
            )
        return artifact_versions, artifact_operation_ids

    def _validate_artifact_history(
        self,
        artifacts: List[Dict[str, Any]],
        artifact_versions: Dict[str, int],
        artifact_operation_ids: Dict[str, str],
    ) -> None:
        state = "Intake"
        resume_state = None
        latest_report_ref: Optional[ArtifactRef] = None
        latest_transition_ref: Optional[ArtifactRef] = None
        blocking_transition_ref: Optional[ArtifactRef] = None
        terminal_transitions: List[Tuple[ArtifactRef, int, str]] = []
        reports_by_transition: Dict[str, List[Tuple[int, str]]] = {}
        prior_version = 0

        for envelope in artifacts:
            reference = reference_for(envelope)
            version = artifact_versions[reference.artifact_id]
            if version < prior_version:
                raise ContractError(
                    "Persisted artifacts are not ordered by commit version."
                )
            prior_version = version
            artifact_type = envelope["artifact_type"]
            payload = envelope["payload"]

            if artifact_type == "transition":
                if payload["from"] != state or (
                    payload["from"], payload["to"]
                ) not in ALLOWED_TRANSITIONS:
                    raise ContractError("Persisted lifecycle transition is invalid.")
                prior_state = state
                state = payload["to"]
                latest_transition_ref = reference
                if state == "Blocked":
                    resume_state = prior_state
                    blocking_transition_ref = reference
                elif prior_state == "Blocked":
                    resume_state = None
                    blocking_transition_ref = None
                if state in {"ContextReady", "Blocked"}:
                    terminal_transitions.append((reference, version, state))
                continue

            if artifact_type != "init_report":
                continue

            expected_supersedes = (
                latest_report_ref.to_dict() if latest_report_ref is not None else None
            )
            if payload["supersedes"] != expected_supersedes:
                raise ContractError(
                    "Persisted InitReport supersedes chain is disconnected."
                )
            report_transition = ArtifactRef.from_dict(
                payload["artifact_refs"]["transition"]
            )
            if payload["outcome"] == "ready":
                if state != "ContextReady" or report_transition != latest_transition_ref:
                    raise ContractError(
                        "Persisted ready report references the wrong transition."
                    )
            elif state != "Blocked" or report_transition != blocking_transition_ref:
                raise ContractError(
                    "Persisted blocked report references the wrong transition."
                )
            evidence_refs = [
                ArtifactRef.from_dict(item)
                for item in payload["artifact_refs"]["evidence"]
            ]
            if not any(
                artifact_versions[ref.artifact_id] == version
                for ref in evidence_refs
            ):
                raise ContractError(
                    "Persisted InitReport lacks same-commit fresh evidence."
                )
            reports_by_transition.setdefault(
                report_transition.artifact_id, []
            ).append((version, payload["outcome"]))
            latest_report_ref = reference

        for transition_ref, version, to_state in terminal_transitions:
            expected_outcome = "ready" if to_state == "ContextReady" else "blocked"
            matching_reports = [
                item
                for item in reports_by_transition.get(transition_ref.artifact_id, [])
                if item == (version, expected_outcome)
            ]
            if len(matching_reports) != 1:
                raise ContractError(
                    "Persisted readiness transition and report were not committed atomically."
                )
    def _validate_payload(self, artifact_type: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise ContractError("Artifact payload must be an object.")
        if len(canonical_json_bytes(payload)) > MAX_ARTIFACT_PAYLOAD_BYTES:
            raise ContractError("Artifact payload exceeds the persistence size limit.")
        if artifact_type == "init_report":
            self._validate_init_report_payload(payload)
            return
        if artifact_type == "evidence_record":
            self._validate_evidence_payload(payload)
            return
        if artifact_type == "transition":
            self._validate_transition_payload(payload)
            return
        if artifact_type != "task_request":
            return
        required = {
            "intent",
            "user_request",
            "repository",
            "constraints",
            "attachments",
        }
        if not required.issubset(payload):
            raise ContractError("TaskRequest is missing a required field.")
        if payload["intent"] not in {
            "init",
            "clarify",
            "design",
            "plan",
            "execute",
            "debug",
            "verify",
            "sync-docs",
            "workflow",
        }:
            raise ContractError("TaskRequest intent is invalid.")
        if not isinstance(payload["user_request"], str) or not payload["user_request"]:
            raise ContractError("TaskRequest user_request must be a non-empty string.")
        repository = payload["repository"]
        if not isinstance(repository, dict):
            raise ContractError("TaskRequest repository must be an object.")
        repository_fields = {
            "requested_path",
            "observed_root",
            "requested_scope",
            "expected_revision",
        }
        if not repository_fields.issubset(repository):
            raise ContractError("TaskRequest repository is missing a required field.")
        requested_path = repository["requested_path"]
        if not isinstance(requested_path, str) or not os.path.isabs(requested_path):
            raise ContractError("TaskRequest requested_path must be absolute.")
        observed_root = repository["observed_root"]
        if observed_root is not None and (
            not isinstance(observed_root, str) or not os.path.isabs(observed_root)
        ):
            raise ContractError("TaskRequest observed_root must be absolute or null.")
        requested_scope = repository["requested_scope"]
        if requested_scope is not None:
            self._validate_relative_path(requested_scope)
        if observed_root is None:
            if requested_scope is not None:
                raise ContractError(
                    "TaskRequest scope requires an observed repository root."
                )
        else:
            expected_path = os.path.normpath(
                os.path.join(observed_root, requested_scope or "")
            )
            if os.path.normpath(requested_path) != expected_path:
                raise ContractError(
                    "TaskRequest requested path does not match its root and scope."
                )
        if repository["expected_revision"] is not None:
            self._optional_revision_from_dict(repository["expected_revision"])
        constraints = payload["constraints"]
        if not isinstance(constraints, dict):
            raise ContractError("TaskRequest constraints must be an object.")
        if not {"scope", "permissions", "destructive_actions"}.issubset(constraints):
            raise ContractError("TaskRequest constraints are missing a required field.")
        if not isinstance(constraints["permissions"], list):
            raise ContractError("TaskRequest permissions must be a list.")
        if constraints["destructive_actions"] not in {"allowed", "denied"}:
            raise ContractError("TaskRequest destructive_actions is invalid.")
        if not isinstance(payload["attachments"], list):
            raise ContractError("TaskRequest attachments must be a list.")

    def _validate_init_report_payload(self, payload: Dict[str, Any]) -> None:
        if "instruction_selection" in payload:
            validate_instruction_selection(payload["instruction_selection"], persisted=True)
        forbidden = {
            _normalized_key(key) for key in payload
        }.intersection(FORBIDDEN_INIT_REPORT_KEYS)
        if forbidden:
            raise ContractError("InitReport contains a field forbidden in S0.")
        required = {
            "repository",
            "sources",
            "findings",
            "gaps",
            "outcome",
            "blocker",
            "artifact_refs",
            "supersedes",
        }
        if not required.issubset(payload):
            raise ContractError("InitReport is missing a required field.")
        outcome = payload["outcome"]
        if outcome not in {"ready", "blocked"}:
            raise ContractError("InitReport outcome is invalid.")
        blocker = payload["blocker"]
        if outcome == "ready" and blocker is not None:
            raise ContractError("A ready InitReport cannot contain a blocker.")
        if outcome == "blocked":
            if not isinstance(blocker, dict) or not {
                "code",
                "message",
                "resume_when",
            }.issubset(blocker):
                raise ContractError("A blocked InitReport requires a typed blocker.")
            if not all(
                isinstance(blocker[key], str) and blocker[key]
                for key in ("code", "message", "resume_when")
            ):
                raise ContractError("InitReport blocker fields must be non-empty strings.")
            if len(blocker["message"]) > 500 or len(blocker["resume_when"]) > 500:
                raise ContractError("InitReport blocker text exceeds the size limit.")
            details = blocker.get("details")
            if isinstance(details, dict) and "instruction_differences" in details:
                validate_instruction_differences(details)

        repository = payload["repository"]
        if not isinstance(repository, dict) or not {
            "requested_path",
            "root",
            "requested_scope",
            "revision",
            "superproject",
        }.issubset(repository):
            raise ContractError("InitReport repository is invalid.")
        if not isinstance(repository["requested_path"], str) or not os.path.isabs(
            repository["requested_path"]
        ):
            raise ContractError("InitReport requested_path must be absolute.")
        if repository["root"] is not None and (
            not isinstance(repository["root"], str)
            or not os.path.isabs(repository["root"])
        ):
            raise ContractError("InitReport root must be absolute or null.")
        requested_scope = repository["requested_scope"]
        if requested_scope is not None:
            self._validate_relative_path(requested_scope)
        if repository["root"] is None:
            if requested_scope is not None:
                raise ContractError(
                    "InitReport scope requires an established repository root."
                )
        else:
            expected_path = os.path.normpath(
                os.path.join(repository["root"], requested_scope or "")
            )
            if os.path.normpath(repository["requested_path"]) != expected_path:
                raise ContractError(
                    "InitReport requested path does not match its root and scope."
                )
        revision = self._optional_revision_from_dict(repository["revision"])
        if outcome == "ready" and revision is None:
            raise ContractError("A ready InitReport requires a repository revision.")
        superproject = repository["superproject"]
        if superproject is not None:
            if not isinstance(superproject, dict) or not {
                "root",
                "revision",
            }.issubset(superproject):
                raise ContractError("InitReport superproject is invalid.")
            if not isinstance(superproject["root"], str) or not os.path.isabs(
                superproject["root"]
            ):
                raise ContractError("InitReport superproject root must be absolute.")
            self._optional_revision_from_dict(superproject["revision"])

        if not isinstance(payload["sources"], list):
            raise ContractError("InitReport sources must be a list.")
        source_ids = set()
        for source in payload["sources"]:
            if not isinstance(source, dict) or not {
                "id",
                "path",
                "kind",
                "hash",
            }.issubset(source):
                raise ContractError("InitReport source is invalid.")
            if not isinstance(source["id"], str) or not source["id"]:
                raise ContractError("InitReport source id is invalid.")
            if source["id"] in source_ids:
                raise ContractError("InitReport source ids must be unique.")
            source_ids.add(source["id"])
            self._validate_relative_path(source["path"], allow_dot=True)
            if source["kind"] not in {
                "entry_doc",
                "repository_instruction",
                "verification_source",
                "repository",
            }:
                raise ContractError("InitReport source kind is invalid.")
            if not isinstance(source["hash"], str) or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", source["hash"]
            ):
                raise ContractError("InitReport source hash is invalid.")

        instruction_hashes = {
            source["path"]: source["hash"] for source in payload["sources"]
            if source["kind"] == "repository_instruction"
        }
        if outcome == "blocked" and isinstance(blocker.get("details"), dict):
            for group in blocker["details"].get("instruction_differences", []):
                if any(instruction_hashes.get(group[side]["path"]) != group[side]["hash"] for side in ("left", "right")):
                    raise ContractError("Instruction differences must reference inspected source versions.")
        findings = payload["findings"]
        if outcome == "ready" and payload.get("instruction_selection"):
            if instruction_hashes != payload["instruction_selection"]["source_hashes"]:
                raise ContractError("Ready instruction authority must match the inspected source versions.")
        if not isinstance(findings, dict) or not {
            "entry_docs",
            "repository_instructions",
            "verification_commands",
        }.issubset(findings):
            raise ContractError("InitReport findings are invalid.")
        for key in (
            "entry_docs",
            "repository_instructions",
            "verification_commands",
        ):
            if not isinstance(findings[key], list) or not all(
                isinstance(item, str) for item in findings[key]
            ):
                raise ContractError("InitReport finding values must be string lists.")
        if not isinstance(payload["gaps"], list) or not all(
            isinstance(item, str) and item for item in payload["gaps"]
        ):
            raise ContractError("InitReport gaps must be a list of strings.")

        named_refs = payload["artifact_refs"]
        if not isinstance(named_refs, dict) or not {
            "task_request",
            "transition",
            "evidence",
        }.issubset(named_refs):
            raise ContractError("InitReport artifact_refs is invalid.")
        self._require_ref_type(named_refs["task_request"], "task_request")
        self._require_ref_type(named_refs["transition"], "transition")
        if not isinstance(named_refs["evidence"], list):
            raise ContractError("InitReport evidence references must be a list.")
        for reference in named_refs["evidence"]:
            self._require_ref_type(reference, "evidence_record")
        if payload["supersedes"] is not None:
            self._require_ref_type(payload["supersedes"], "init_report")

    def _validate_evidence_payload(self, payload: Dict[str, Any]) -> None:
        required = {
            "kind",
            "invocation",
            "observed_revision",
            "started_at",
            "duration_ms",
            "exit_status",
            "summary",
            "artifact_refs",
            "authority_grant",
        }
        if not required.issubset(payload):
            raise ContractError("EvidenceRecord is missing a required field.")
        if payload["kind"] not in {
            "test",
            "build",
            "lint",
            "manual",
            "browser",
            "api",
            "inspection",
            "authority",
        }:
            raise ContractError("EvidenceRecord kind is invalid.")
        if not isinstance(payload["invocation"], str) or not payload["invocation"]:
            raise ContractError("EvidenceRecord invocation must be a non-empty string.")
        if len(payload["invocation"]) > 500:
            raise ContractError("EvidenceRecord invocation exceeds the size limit.")
        self._optional_revision_from_dict(payload["observed_revision"])
        self._validate_timestamp(payload["started_at"])
        duration = payload["duration_ms"]
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            raise ContractError("EvidenceRecord duration_ms must be non-negative.")
        if payload["exit_status"] not in {"pass", "fail", "unavailable"}:
            raise ContractError("EvidenceRecord exit_status is invalid.")
        if not isinstance(payload["summary"], str) or len(payload["summary"]) > 2000:
            raise ContractError("EvidenceRecord summary is invalid or too large.")
        if not isinstance(payload["artifact_refs"], list):
            raise ContractError("EvidenceRecord artifact_refs must be a list.")
        for value in payload["artifact_refs"]:
            reference = ArtifactRef.from_dict(value)
            if reference.artifact_type not in ARTIFACT_TYPES:
                raise ContractError("EvidenceRecord reference type is invalid.")
        authority = payload["authority_grant"]
        if payload["kind"] == "authority":
            if not isinstance(authority, dict) or not {
                "granted_by",
                "capabilities",
                "scopes",
                "confirmed_at",
                "provenance",
            }.issubset(authority):
                raise ContractError("Authority evidence requires an authority_grant.")
            if authority["granted_by"] != "user":
                raise ContractError("Authority evidence must be granted by the user.")
            capabilities = authority["capabilities"]
            if not isinstance(capabilities, list) or not capabilities:
                raise ContractError("Authority capabilities must be a non-empty list.")
            if not all(
                isinstance(item, str)
                and re.fullmatch(r"[a-z0-9][a-z0-9._:/-]{0,127}", item)
                for item in capabilities
            ) or len(capabilities) != len(set(capabilities)):
                raise ContractError(
                    "Authority capabilities contain an invalid or duplicate identifier."
                )
            scopes = authority["scopes"]
            if not isinstance(scopes, list) or not scopes:
                raise ContractError("Authority scopes must be a non-empty list.")
            if not all(isinstance(item, str) for item in scopes) or len(
                scopes
            ) != len(set(scopes)):
                raise ContractError(
                    "Authority scopes contain an invalid or duplicate identifier."
                )
            for scope in scopes:
                if scope.startswith(REPOSITORY_SCOPE_PREFIX):
                    decode_repository_scope(scope)
                elif re.fullmatch(r"[a-z0-9][a-z0-9._:/-]{0,127}", scope) is None:
                    raise ContractError(
                        "Authority scopes contain an invalid or duplicate identifier."
                    )
            self._validate_timestamp(authority["confirmed_at"])
            if not isinstance(authority["provenance"], str) or not authority[
                "provenance"
            ]:
                raise ContractError("Authority provenance must be a non-empty string.")
        elif authority is not None:
            raise ContractError("Non-authority evidence cannot contain authority_grant.")

    def _validate_transition_payload(self, payload: Dict[str, Any]) -> None:
        required = {"from", "to", "reason", "input_refs", "output_ref", "actor"}
        if not required.issubset(payload):
            raise ContractError("Transition is missing a required field.")
        if not isinstance(payload["from"], str) or not isinstance(payload["to"], str):
            raise ContractError("Transition states must be strings.")
        if not isinstance(payload["reason"], str) or not payload["reason"]:
            raise ContractError("Transition reason must be a non-empty string.")
        if len(payload["reason"]) > 500:
            raise ContractError("Transition reason exceeds the size limit.")
        if payload["actor"] not in {"runtime", "user", "stage module"}:
            raise ContractError("Transition actor is invalid.")
        if not isinstance(payload["input_refs"], list):
            raise ContractError("Transition input_refs must be a list.")
        for reference in payload["input_refs"]:
            ArtifactRef.from_dict(reference)
        if payload["output_ref"] is not None:
            ArtifactRef.from_dict(payload["output_ref"])

    def _require_ref_type(self, value: Any, artifact_type: str) -> None:
        reference = ArtifactRef.from_dict(value)
        if reference.artifact_type != artifact_type:
            raise ContractError("Artifact reference type does not match its slot.")

    def _validate_relative_path(self, value: Any, allow_dot: bool = False) -> None:
        if not isinstance(value, str) or not value:
            raise ContractError("Repository-relative path must be a non-empty string.")
        if value == "." and allow_dot:
            return
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value == ".":
            raise ContractError("Repository-relative path is invalid.")

    def _validate_timestamp(self, value: Any) -> None:
        if not isinstance(value, str) or not value:
            raise ContractError("Timestamp must be a non-empty string.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ContractError("Timestamp is not valid ISO 8601.") from error
        if parsed.tzinfo is None:
            raise ContractError("Timestamp must include a timezone.")
