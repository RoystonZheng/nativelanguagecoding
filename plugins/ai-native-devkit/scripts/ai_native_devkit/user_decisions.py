"""Scoped user directions, projected from immutable runtime evidence.

These are process exceptions, never approvals or successful check results.
One route selection is the lifetime of a decision; a new run does not inherit
another run's waived checks.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from .errors import ContractError


GATES = {
    "init": {"input", "method", "stage_result"},
    "clarify": {"input", "approval", "method", "stage_result"},
    "design": {"input", "approval", "method", "stage_result"},
    "plan": {"input", "approval", "method", "stage_result"},
    "execute": {"input", "method", "stage_result"},
    "debug": {"method", "stage_result"},
    "verify": {"method", "verification"},
    "sync-docs": {"approval", "docs_classification", "docs_capture", "method", "stage_result"},
}
UPSTREAM = {"design": "clarify", "plan": "design", "execute": "plan"}


class UserDecisions:
    def __init__(self, events: Sequence[Dict[str, Any]], repository: str):
        self.events = events
        self.repository = repository
        self.route = next((event for event in reversed(events)
                           if event["event_type"] == "workflow.route.selected"
                           and event.get("payload", {}).get("repository") == repository), None)
        self.route_id = self.route["event_id"] if self.route else None
        self.decisions = [event for event in events
                          if event["event_type"] == "workflow.user_decision"
                          and event.get("payload", {}).get("repository") == repository
                          and event["payload"].get("route_event_id") == self.route_id]

    def require_open_route(self, *, allow_failed: bool = False) -> None:
        boundary = next((event for event in reversed(self.events)
                         if self.route and event["seq"] > self.route["seq"]
                         and event["event_type"] in {"workflow.completed", "workflow.failed", "workflow.user_decision"}
                         and event.get("payload", {}).get("repository", self.repository) == self.repository), None)
        closed = boundary and boundary["event_type"] in {"workflow.completed", "workflow.failed"}
        if self.route is None or (closed and not (allow_failed and boundary["event_type"] == "workflow.failed")):
            raise ContractError("User direction requires an open route for this repository.")

    def waived(self, stage: str, run_id: str, gate: str) -> bool:
        return any(event.get("stage") == stage
                   and event.get("correlation", {}).get("stage_run_id") == run_id
                   and event["payload"].get("action") == "waive_blocker"
                   and event["payload"].get("gate") == gate
                   for event in self.decisions)

    def latest_stage(self, stage: str, *, before_seq: Optional[int] = None) -> Optional[Dict[str, Any]]:
        candidates = [event for event in self.events
                      if event.get("stage") == stage
                      and event.get("payload", {}).get("repository") == self.repository
                      and event["event_type"].startswith("workflow.stage.")
                      and (before_seq is None or event["seq"] < before_seq)]
        return candidates[-1] if candidates else None

    def skipped(self, stage: str, *, before_seq: Optional[int] = None) -> bool:
        latest = self.latest_stage(stage, before_seq=before_seq)
        return latest is not None and self.is_user_skip(latest)

    def is_user_skip(self, terminal: Dict[str, Any]) -> bool:
        return terminal["event_type"] == "workflow.stage.skipped" and any(
            event["payload"].get("action") == "skip_stage"
            and event["payload"].get("decision_id") == terminal.get("payload", {}).get("decision_id")
            and event.get("stage") == terminal.get("stage")
            and event.get("correlation", {}).get("stage_run_id")
            == terminal.get("correlation", {}).get("stage_run_id")
            for event in self.decisions)

    def input_optional(self, stage: str, run_id: str, *, before_seq: Optional[int] = None) -> bool:
        if self.waived(stage, run_id, "input"):
            return True
        if stage not in UPSTREAM:
            return False
        # A user may remove the missing upstream step after this run hit its
        # input gate. Retain historical valid handoffs when later runs start.
        upstream_events = (
            self.latest_stage(UPSTREAM[stage], before_seq=before_seq),
            self.latest_stage(UPSTREAM[stage]),
        )
        return any(event is not None and (self.is_user_skip(event) or self.accepted_failure(event))
                   for event in upstream_events)

    def accepted_failure(self, terminal: Dict[str, Any]) -> bool:
        return terminal["event_type"] == "workflow.stage.failed" and self.waived(
            terminal.get("stage"), terminal.get("correlation", {}).get("stage_run_id"), "stage_result"
        )
