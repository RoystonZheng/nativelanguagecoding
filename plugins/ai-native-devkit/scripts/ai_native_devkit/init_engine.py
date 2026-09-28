"""Policy-owning `/init` engine."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Dict
import uuid

from .contracts import (
    ArtifactDraft,
    EvidenceRecord,
    InitReport,
    LocalRef,
    TaskCommit,
    TaskRequest,
    TransitionIntent,
    canonical_json_bytes,
    encode_repository_scope,
    utc_now,
    ArtifactRef,
    reference_for,
)
from .errors import RepositoryError, StoreError
from .repository import RepositoryInspector
from .instruction_selection import validate_instruction_selection
from .state_store import MISSING, TaskStateStore


class InitEngine:
    def __init__(self, store: TaskStateStore, inspector: RepositoryInspector):
        self._store = store
        self._inspector = inspector

    def run(
        self,
        task_id: str,
        requested_path: str,
        user_request: str,
        choice: str = None,
        authority_grant: Dict[str, Any] = None,
        instruction_selection: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        supersedes = None
        resume_transition_ref = None
        inspection = None
        authority_ref = None
        initial_store_version = None
        creation_was_overtaken = False
        classification = self._inspector.classify(requested_path)
        snapshot = self._store.load(task_id)
        if snapshot is not MISSING:
            self._validate_bound_target(snapshot, classification)
        if instruction_selection is not None:
            if choice is not None or authority_grant is not None:
                raise StoreError("init.instruction_selection_not_applicable", "Instruction selection cannot be combined with another Init choice or authority grant.")
            snapshot = self._record_instruction_selection(snapshot, task_id, instruction_selection)
        selected_instructions = self._instruction_selection(snapshot)
        if choice is not None and (
            snapshot is MISSING or snapshot.lifecycle_state != "ContextReady"
        ):
            raise StoreError(
                "init.invalid_choice",
                "An init follow-up choice is valid only for a ready task.",
                retryable=False,
            )
        if authority_grant is not None and (
            snapshot is MISSING or snapshot.lifecycle_state != "Blocked"
        ):
            raise StoreError(
                "init.authority_not_applicable",
                "A later authority grant is valid only when retrying a blocked task.",
                retryable=False,
            )
        if authority_grant is not None:
            self._validate_authority_grant(
                snapshot, classification, authority_grant
            )
        if snapshot is MISSING:
            request = TaskRequest(
                user_request=user_request,
                requested_path=classification.requested_path,
                observed_root=classification.root,
                requested_scope=classification.requested_scope,
            )
            request_payload = request.to_payload()
            create_receipt = self._store.commit(
                TaskCommit(
                    task_id=task_id,
                    expected_store_version=None,
                    operation_id=self._operation_id("create", request_payload),
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="task_request",
                            artifact_type="task_request",
                            payload=request_payload,
                        )
                    ],
                    transition_intent=None,
                )
            )
            task_request_ref = create_receipt.materialized_refs["task_request"]
            snapshot = self._store.load(task_id)
            self._validate_bound_target(snapshot, classification)
            initial_store_version = create_receipt.store_version
            creation_was_overtaken = (
                snapshot.store_version != create_receipt.store_version
            )
        elif snapshot.lifecycle_state == "Intake":
            task_request_envelope = next(
                envelope
                for envelope in snapshot.artifacts
                if envelope["artifact_type"] == "task_request"
            )
            from .contracts import reference_for

            task_request_ref = reference_for(task_request_envelope)
            if snapshot.latest_report_ref is not None:
                latest_report = self._latest_report(snapshot)
                if latest_report["payload"]["outcome"] != "blocked":
                    raise StoreError(
                        "state.corrupt",
                        "An Intake resume checkpoint has an incompatible latest report.",
                        retryable=False,
                    )
                supersedes = reference_for(latest_report)
                resume_transitions = [
                    envelope
                    for envelope in snapshot.artifacts
                    if envelope["artifact_type"] == "transition"
                    and envelope["payload"]["from"] == "Blocked"
                    and envelope["payload"]["to"] == "Intake"
                ]
                if not resume_transitions:
                    raise StoreError(
                        "state.corrupt",
                        "An Intake resume checkpoint is missing its resume transition.",
                        retryable=False,
                    )
                resume_transition = resume_transitions[-1]
                resume_transition_ref = reference_for(resume_transition)
                from .contracts import ArtifactRef

                for input_ref_value in resume_transition["payload"]["input_refs"]:
                    input_ref = ArtifactRef.from_dict(input_ref_value)
                    if input_ref.artifact_type != "evidence_record":
                        continue
                    evidence = next(
                        envelope
                        for envelope in snapshot.artifacts
                        if envelope["artifact_id"] == input_ref.artifact_id
                    )
                    if evidence["payload"]["kind"] == "authority":
                        authority_ref = input_ref
        elif snapshot.lifecycle_state == "ContextReady":
            latest_report = self._latest_report(snapshot)
            is_current = False
            if classification.kind == "worktree":
                try:
                    current_inspection = self._inspect(classification, selected_instructions)
                except RepositoryError as error:
                    if not error.code.startswith("blocked."):
                        raise
                else:
                    prior_repository = latest_report["payload"]["repository"]
                    is_current = (
                        prior_repository == current_inspection.repository
                        and latest_report["payload"]["sources"]
                        == current_inspection.sources
                        and latest_report["payload"]["findings"]
                        == current_inspection.findings
                        and latest_report["payload"]["gaps"]
                        == current_inspection.gaps
                    )
            if choice is None:
                return {
                    "schema_version": "ai-native-devkit/v1alpha1",
                    "kind": "choice_required",
                    "reason": "init.ready_current" if is_current else "init.ready_stale",
                    "choices": ["reuse", "new"] if is_current else ["new", "cancel"],
                }
            if choice == "reuse" and is_current:
                return self._report_response(latest_report)
            if choice == "new":
                return self.run(
                    str(uuid.uuid4()), requested_path, user_request, choice=None
                )
            if choice == "cancel" and not is_current:
                return {
                    "schema_version": "ai-native-devkit/v1alpha1",
                    "kind": "choice_required",
                    "reason": "init.cancelled",
                    "choices": [],
                }
            raise StoreError(
                "init.invalid_choice",
                "The selected init follow-up choice is not valid for current task state.",
                retryable=False,
            )
        elif snapshot.lifecycle_state == "Blocked":
            task_request_ref = self._task_request_ref(snapshot)
            latest_report = self._latest_report(snapshot)
            from .contracts import ArtifactRef, reference_for

            supersedes = reference_for(latest_report)
            existing_transition_ref = ArtifactRef.from_dict(
                latest_report["payload"]["artifact_refs"]["transition"]
            )
            if classification.kind != "worktree":
                return self._blocked_repository_report(
                    task_id,
                    snapshot,
                    task_request_ref,
                    classification,
                    transition_ref=existing_transition_ref,
                    supersedes=supersedes,
                    authority_grant=authority_grant,
                )
            try:
                inspection = self._inspect(classification, selected_instructions)
            except RepositoryError as error:
                if error.code.startswith("blocked."):
                    return self._blocked_repository_report(
                        task_id,
                        snapshot,
                        task_request_ref,
                        classification,
                        transition_ref=existing_transition_ref,
                        supersedes=supersedes,
                        blocker_error=error,
                        authority_grant=authority_grant,
                    )
                raise
            authority_drafts = []
            resume_inputs = [supersedes]
            if authority_grant is not None:
                authority_drafts.append(
                    ArtifactDraft(
                        local_ref="authority",
                        artifact_type="evidence_record",
                        payload=self._authority_evidence(authority_grant).to_payload(),
                    )
                )
                resume_inputs.append(LocalRef("authority"))
            resume_receipt = self._store.commit(
                TaskCommit(
                    task_id=task_id,
                    expected_store_version=snapshot.store_version,
                    operation_id="init:resume:" + str(uuid.uuid4()),
                    artifact_drafts=authority_drafts,
                    transition_intent=TransitionIntent(
                        local_ref="resume_transition",
                        to_state=snapshot.resume_state,
                        reason="init.blocker_resolved",
                        input_refs=resume_inputs,
                        output_ref=None,
                        actor="stage module",
                    ),
                )
            )
            resume_transition_ref = resume_receipt.transition_ref
            authority_ref = resume_receipt.materialized_refs.get("authority")
            snapshot = self._store.load(task_id)
        else:
            raise StoreError(
                "init.existing_task_requires_choice",
                "An existing initialized task requires an explicit follow-up choice.",
                retryable=False,
            )

        if classification.kind != "worktree":
            return self._blocked_repository_report(
                task_id,
                snapshot,
                task_request_ref,
                classification,
                supersedes=supersedes,
                resume_transition_ref=resume_transition_ref,
                expected_store_version=initial_store_version,
                concurrent_create_request=(
                    (requested_path, user_request)
                    if creation_was_overtaken
                    else None
                ),
            )

        if inspection is None:
            try:
                inspection = self._inspect(classification, selected_instructions)
            except RepositoryError as error:
                if error.code.startswith("blocked."):
                    return self._blocked_repository_report(
                        task_id,
                        snapshot,
                        task_request_ref,
                        classification,
                        blocker_error=error,
                        supersedes=supersedes,
                        resume_transition_ref=resume_transition_ref,
                        expected_store_version=initial_store_version,
                        concurrent_create_request=(
                            (requested_path, user_request)
                            if creation_was_overtaken
                            else None
                        ),
                    )
                raise
        evidence = EvidenceRecord(
            observed_revision=inspection.revision,
            started_at=inspection.started_at,
            duration_ms=inspection.duration_ms,
            summary="Inspected Git worktree and bounded project entry sources.",
        )
        report = InitReport(
            repository=inspection.repository,
            sources=inspection.sources,
            findings=inspection.findings,
            gaps=inspection.gaps,
            outcome="ready",
            blocker=None,
            task_request_ref=task_request_ref,
            transition_ref=LocalRef("transition"),
            evidence_refs=[LocalRef("inspection")],
            supersedes=supersedes,
            instruction_selection=selected_instructions,
        )
        if authority_ref is not None:
            report = InitReport(
                repository=report.repository,
                sources=report.sources,
                findings=report.findings,
                gaps=report.gaps,
                outcome=report.outcome,
                blocker=report.blocker,
                task_request_ref=report.task_request_ref,
                transition_ref=report.transition_ref,
                evidence_refs=[authority_ref, LocalRef("inspection")],
                supersedes=report.supersedes,
                instruction_selection=report.instruction_selection,
            )
        try:
            commit_receipt = self._store.commit(
                TaskCommit(
                    task_id=task_id,
                    expected_store_version=(
                        initial_store_version or snapshot.store_version
                    ),
                    operation_id="init:inspection-attempt:" + str(uuid.uuid4()),
                    artifact_drafts=[
                        ArtifactDraft(
                            local_ref="inspection",
                            artifact_type="evidence_record",
                            payload=evidence.to_payload(),
                        ),
                        ArtifactDraft(
                            local_ref="report",
                            artifact_type="init_report",
                            payload=report.to_payload(),
                        ),
                    ],
                    transition_intent=TransitionIntent(
                        local_ref="transition",
                        to_state="ContextReady",
                        reason="init.inspection_ready",
                        input_refs=[task_request_ref, LocalRef("inspection")]
                        + ([resume_transition_ref] if resume_transition_ref else []),
                        output_ref=None,
                        actor="stage module",
                    ),
                )
            )
        except StoreError as error:
            if (
                error.code != "rejected.concurrent_update"
                or supersedes is not None
                or resume_transition_ref is not None
                or authority_ref is not None
            ):
                raise
            winner_report = self._equivalent_initial_report(
                task_id,
                expected_state="ContextReady",
                intended_payload=report.to_payload(),
            )
            if winner_report is None:
                if creation_was_overtaken:
                    return self.run(task_id, requested_path, user_request)
                raise
            return self._report_response(winner_report)
        final_snapshot = self._store.load(task_id)
        report_ref = commit_receipt.materialized_refs["report"]
        report_envelope = next(
            envelope
            for envelope in final_snapshot.artifacts
            if envelope["artifact_id"] == report_ref.artifact_id
        )
        return self._report_response(report_envelope)

    def _blocked_repository_report(
        self,
        task_id,
        snapshot,
        task_request_ref,
        classification,
        transition_ref=None,
        supersedes=None,
        blocker_error=None,
        authority_grant=None,
        resume_transition_ref=None,
        expected_store_version=None,
        concurrent_create_request=None,
    ) -> Dict[str, Any]:
        if blocker_error is not None:
            code = blocker_error.code
            message = blocker_error.message
            resume_when = {
                "blocked.repository.read_authority": (
                    "Grant the required bounded repository read authority, then retry this task."
                ),
                "blocked.repository.read_failed": (
                    "Restore bounded read access to the selected repository sources, then retry this task."
                ),
                "blocked.repository.source_too_large": (
                    "Reduce or explicitly exclude the oversized source, then retry this task."
                ),
                "blocked.repository.worktree_too_large": (
                    "Reduce or ignore the oversized untracked content, then retry this task."
                ),
                "blocked.repository.git_output_too_large": (
                    "Reduce the repository change set inspected by Git, then retry this task."
                ),
                "blocked.repository.source_conflict": (
                    "Review the paired rule ranges, choose the authoritative file for this task, and retry with instruction_selection bound to this report_ref."
                ),
                "blocked.repository.instruction_selection_stale": (
                    "The prior file selection no longer matches the source versions. Review the current differences and make a fresh selection."
                ),
                "blocked.repository.changed_during_inspection": (
                    "Retry when the repository is no longer changing during inspection."
                ),
                "blocked.repository.source_outside_root": (
                    "Replace the selected source symlink with a bounded repository file, then retry this task."
                ),
            }.get(
                code,
                "Resolve the repository inspection blocker, then retry this task.",
            )
        elif classification.kind == "missing":
            code = "blocked.repository.not_found"
            message = "The requested repository path does not exist."
            resume_when = (
                "Create or select a non-bare Git worktree at the requested path, then retry this task."
            )
        elif classification.kind == "not_directory":
            code = "blocked.repository.not_directory"
            message = "The requested repository path is not a directory."
            resume_when = (
                "Select a non-bare Git worktree directory, then retry this task."
            )
        elif classification.kind == "bare":
            code = "blocked.repository.no_worktree"
            message = "The requested Git repository has no worktree."
            resume_when = "Select or create a non-bare Git worktree, then retry this task."
        else:
            code = "blocked.repository.not_git"
            message = "The requested path is not a Git worktree."
            resume_when = (
                "Select or initialize a non-bare Git worktree, then retry this task."
            )
        observation = (
            blocker_error.observation
            if blocker_error is not None
            and getattr(blocker_error, "observation", None) is not None
            else None
        )
        evidence = EvidenceRecord(
            observed_revision=(observation.revision if observation is not None else None),
            started_at=(observation.started_at if observation is not None else utc_now()),
            duration_ms=(observation.duration_ms if observation is not None else 0),
            summary=message,
            exit_status="fail",
        )
        artifact_drafts = []
        evidence_refs = []
        if authority_grant is not None:
            artifact_drafts.append(
                ArtifactDraft(
                    local_ref="authority",
                    artifact_type="evidence_record",
                    payload=self._authority_evidence(authority_grant).to_payload(),
                )
            )
            evidence_refs.append(LocalRef("authority"))
        evidence_refs.append(LocalRef("inspection"))
        report = InitReport(
            repository=(
                observation.repository
                if observation is not None
                else {
                    "requested_path": classification.requested_path,
                    "root": (
                        classification.root if blocker_error is not None else None
                    ),
                    "requested_scope": (
                        classification.requested_scope
                        if blocker_error is not None
                        else None
                    ),
                    "revision": None,
                    "superproject": None,
                }
            ),
            sources=(observation.sources if observation is not None else []),
            findings=(
                observation.findings
                if observation is not None
                else {
                    "entry_docs": [],
                    "repository_instructions": [],
                    "verification_commands": [],
                }
            ),
            gaps=(
                observation.gaps
                if observation is not None
                else [
                    "repository_inspection"
                    if blocker_error is not None
                    else "eligible_repository"
                ]
            ),
            outcome="blocked",
            blocker={
                "code": code,
                "message": message,
                "resume_when": resume_when,
                **({"details": blocker_error.details} if blocker_error is not None and blocker_error.details is not None else {}),
            },
            task_request_ref=task_request_ref,
            transition_ref=transition_ref or LocalRef("transition"),
            evidence_refs=evidence_refs,
            supersedes=supersedes,
            instruction_selection=(
                None if code == "blocked.repository.instruction_selection_stale"
                else self._instruction_selection(snapshot)
            ),
        )
        transition_intent = None
        if transition_ref is None:
            transition_intent = TransitionIntent(
                local_ref="transition",
                to_state="Blocked",
                reason=code,
                input_refs=[task_request_ref, LocalRef("inspection")]
                + ([resume_transition_ref] if resume_transition_ref else []),
                output_ref=None,
                actor="stage module",
            )
            operation_id = "init:blocked-attempt:" + str(uuid.uuid4())
        else:
            operation_id = "init:blocked-retry:" + str(uuid.uuid4())
        artifact_drafts.extend(
            [
                ArtifactDraft(
                    local_ref="inspection",
                    artifact_type="evidence_record",
                    payload=evidence.to_payload(),
                ),
                ArtifactDraft(
                    local_ref="report",
                    artifact_type="init_report",
                    payload=report.to_payload(),
                ),
            ]
        )
        if transition_intent is not None and authority_grant is not None:
            transition_intent = TransitionIntent(
                local_ref=transition_intent.local_ref,
                to_state=transition_intent.to_state,
                reason=transition_intent.reason,
                input_refs=transition_intent.input_refs + [LocalRef("authority")],
                output_ref=transition_intent.output_ref,
                actor=transition_intent.actor,
            )
        try:
            receipt = self._store.commit(
                TaskCommit(
                    task_id=task_id,
                    expected_store_version=(
                        expected_store_version or snapshot.store_version
                    ),
                    operation_id=operation_id,
                    artifact_drafts=artifact_drafts,
                    transition_intent=transition_intent,
                )
            )
        except StoreError as error:
            if (
                error.code != "rejected.concurrent_update"
                or supersedes is not None
                or transition_ref is not None
                or authority_grant is not None
                or resume_transition_ref is not None
            ):
                raise
            winner_report = self._equivalent_initial_report(
                task_id,
                expected_state="Blocked",
                intended_payload=report.to_payload(),
            )
            if winner_report is None:
                if concurrent_create_request is not None:
                    return self.run(
                        task_id,
                        concurrent_create_request[0],
                        concurrent_create_request[1],
                    )
                raise
            return self._report_response(winner_report)
        final_snapshot = self._store.load(task_id)
        report_ref = receipt.materialized_refs["report"]
        report_envelope = next(
            envelope
            for envelope in final_snapshot.artifacts
            if envelope["artifact_id"] == report_ref.artifact_id
        )
        return self._report_response(report_envelope)

    def _latest_report(self, snapshot):
        if snapshot.latest_report_ref is None:
            raise StoreError(
                "state.corrupt",
                "Task state has no latest init report.",
                retryable=False,
            )
        return next(
            envelope
            for envelope in snapshot.artifacts
            if envelope["artifact_id"] == snapshot.latest_report_ref.artifact_id
        )

    def _instruction_selection(self, snapshot):
        if snapshot is MISSING or snapshot.latest_report_ref is None:
            return None
        return self._latest_report(snapshot)["payload"].get("instruction_selection")

    def _inspect(self, classification, selection):
        if selection is None:
            return self._inspector.inspect(classification)
        return self._inspector.inspect(classification, instruction_selection=selection)

    def _record_instruction_selection(self, snapshot, task_id, selection):
        validate_instruction_selection(selection)
        if snapshot is MISSING or snapshot.lifecycle_state != "Blocked":
            raise StoreError("init.instruction_selection_not_applicable", "Select instruction authority only for an existing blocked task.")
        latest = self._latest_report(snapshot)
        prior = latest["payload"]
        if (prior.get("blocker") or {}).get("code") not in {
            "blocked.repository.source_conflict", "blocked.repository.instruction_selection_stale"
        }:
            raise StoreError("init.instruction_selection_not_applicable", "Instruction selection cannot bypass another Init blocker.")
        reference = reference_for(latest)
        if ArtifactRef.from_dict(selection["report_ref"]) != reference:
            raise StoreError("init.instruction_selection_stale", "Instruction selection must reference the exact latest blocked report.")
        confirmed = datetime.fromisoformat(selection["confirmed_at"][:-1] + "+00:00")
        created = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
        if confirmed < created or confirmed > datetime.now(timezone.utc):
            raise StoreError("init.instruction_confirmation_invalid", "Instruction selection must cite a user confirmation after the report was produced.")
        differences = (prior["blocker"].get("details") or {}).get("instruction_differences", [])
        pairs = [{group["left"]["path"], group["right"]["path"]} for group in differences]
        if any(not any(path in pair for pair in pairs) for path in selection["preferred_sources"]):
            raise StoreError("init.instruction_selection_not_applicable", "Choose a file from the reported instruction differences.")
        preferred = {
            PurePosixPath(path).parent.as_posix(): path
            for path in (prior.get("instruction_selection") or {}).get("preferred_sources", [])
        }
        preferred.update({PurePosixPath(path).parent.as_posix(): path for path in selection["preferred_sources"]})
        bound = {
            **selection,
            "preferred_sources": list(preferred.values()),
            "source_hashes": {
                source["path"]: source["hash"] for source in prior["sources"]
                if source["kind"] == "repository_instruction"
            },
        }
        validate_instruction_selection(bound, persisted=True)
        evidence = EvidenceRecord(
            observed_revision=None, started_at=selection["confirmed_at"], duration_ms=0,
            kind="manual", invocation="user-confirmed instruction authority",
            summary="User selected task-local instruction authority; exact source versions will be rechecked.",
            artifact_refs=[reference],
        )
        payload = {
            **prior, "instruction_selection": bound, "supersedes": reference,
            "artifact_refs": {
                **prior["artifact_refs"],
                "evidence": [*prior["artifact_refs"]["evidence"], LocalRef("selection")],
            },
        }
        self._store.commit(TaskCommit(
            task_id=task_id, expected_store_version=snapshot.store_version,
            operation_id=self._operation_id("instruction-selection", bound),
            artifact_drafts=[
                ArtifactDraft(local_ref="selection", artifact_type="evidence_record", payload=evidence.to_payload()),
                ArtifactDraft(local_ref="report", artifact_type="init_report", payload=payload),
            ],
            transition_intent=None,
        ))
        return self._store.load(task_id)

    def _equivalent_initial_report(
        self, task_id, expected_state, intended_payload
    ):
        """Return a concurrent winner only when its durable result is equivalent."""
        winner = self._store.load(task_id)
        if winner is MISSING or winner.lifecycle_state != expected_state:
            return None
        winner_report = self._latest_report(winner)
        winner_payload = winner_report["payload"]
        reports = [
            envelope
            for envelope in winner.artifacts
            if envelope["artifact_type"] == "init_report"
        ]
        if len(reports) != 1 or reports[0]["artifact_id"] != winner_report["artifact_id"]:
            return None
        intended_task_request = intended_payload["artifact_refs"]["task_request"]
        if hasattr(intended_task_request, "to_dict"):
            intended_task_request = intended_task_request.to_dict()
        if (
            winner_payload["artifact_refs"]["task_request"]
            != intended_task_request
        ):
            return None
        projection_fields = (
            "repository",
            "sources",
            "findings",
            "gaps",
            "outcome",
            "blocker",
        )
        if any(
            winner_payload[field] != intended_payload[field]
            for field in projection_fields
        ):
            return None
        if winner_payload.get("instruction_selection") != intended_payload.get("instruction_selection"):
            return None
        if winner_payload.get("supersedes") is not None:
            return None
        return winner_report

    def _task_request_ref(self, snapshot):
        from .contracts import reference_for

        task_request = next(
            envelope
            for envelope in snapshot.artifacts
            if envelope["artifact_type"] == "task_request"
        )
        return reference_for(task_request)

    def _validate_bound_target(self, snapshot, classification) -> None:
        task_request = next(
            envelope
            for envelope in snapshot.artifacts
            if envelope["artifact_type"] == "task_request"
        )
        bound = task_request["payload"]["repository"]
        target_changed = bound["requested_path"] != classification.requested_path
        if bound["observed_root"] is not None:
            target_changed = target_changed or (
                bound["observed_root"] != classification.root
                or bound["requested_scope"] != classification.requested_scope
            )
        if target_changed:
            raise StoreError(
                "init.task_target_mismatch",
                "The existing task is bound to a different repository target.",
                retryable=False,
            )

    def _report_response(self, report_envelope):
        from .contracts import reference_for

        return {
            "schema_version": "ai-native-devkit/v1alpha1",
            "kind": "report",
            "report": report_envelope,
            "report_ref": reference_for(report_envelope).to_dict(),
        }

    def _authority_evidence(self, authority_grant):
        grant = {
            "granted_by": "user",
            "capabilities": authority_grant["capabilities"],
            "scopes": authority_grant["scopes"],
            "confirmed_at": authority_grant["confirmed_at"],
            "provenance": authority_grant["provenance"],
        }
        return EvidenceRecord(
            observed_revision=None,
            started_at=authority_grant["confirmed_at"],
            duration_ms=0,
            summary="User granted bounded repository read authority.",
            kind="authority",
            invocation="user-confirmed authority grant",
            authority_grant=grant,
        )

    def _validate_authority_grant(
        self, snapshot, classification, authority_grant
    ) -> None:
        latest_report = self._latest_report(snapshot)
        blocker = latest_report["payload"].get("blocker") or {}
        if blocker.get("code") != "blocked.repository.read_authority":
            raise StoreError(
                "init.authority_not_applicable",
                "Repository read authority is not applicable to the task's latest blocker.",
                retryable=False,
            )

        capabilities = authority_grant.get("capabilities")
        scopes = authority_grant.get("scopes")
        expected_scope = encode_repository_scope(classification.requested_scope)
        if (
            capabilities != ["repository.read"]
            or scopes != [expected_scope]
        ):
            raise StoreError(
                "init.authority_bounds_mismatch",
                "Repository authority must include repository.read for the exact requested scope.",
                retryable=False,
            )

    def _operation_id(self, kind: str, value: Dict[str, Any]) -> str:
        digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
        return "init:" + kind + ":" + digest
