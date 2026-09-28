"""Deterministic documentation-impact hook triggered by verified revisions."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import subprocess
from typing import Any, Dict, Iterable, List, Optional

from .errors import ContractError


DOCS_PREFIX = "docs/"
HANDOFF_PREFIX = "handoff/"
SEMANTIC_PREFIXES = ("api/", "migrations/", "schema/", "proto/")
SOURCE_PREFIXES = ("src/", "app/", "lib/", "services/", "cmd/", "pkg/")
NO_IMPACT_PREFIXES = (
    "tests/",
    "test/",
    "src/internal/",
    "internal/",
    ".scratch/",
    ".tmp/",
    "tmp/",
    "coverage/",
)
NO_IMPACT_NAMES = frozenset(
    {".DS_Store", ".coverage", "coverage.xml", "test-results.xml"}
)
INTENTS = frozenset({"development", "debug"})
CHANGE_KINDS = frozenset({"feature", "bug", "test", "refactor", "temporary", "contract"})


def _normalize_paths(paths: Iterable[str]) -> List[str]:
    normalized = []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise ContractError("Docs Hook changed paths must be non-empty strings.")
        path = PurePosixPath(raw.strip())
        value = path.as_posix()
        if path.is_absolute() or ".." in path.parts or value in {"", "."}:
            raise ContractError("Docs Hook changed path is unsafe.")
        if value not in normalized:
            normalized.append(value)
    return sorted(normalized)


def classify_changes(
    paths: Iterable[str],
    *,
    intent: Optional[str] = None,
    change_kind: Optional[str] = None,
) -> Dict[str, Any]:
    if intent is not None and intent not in INTENTS:
        raise ContractError("Docs Hook workflow intent is invalid.")
    if change_kind is not None and change_kind not in CHANGE_KINDS:
        raise ContractError("Docs Hook change kind is invalid.")
    normalized = _normalize_paths(paths)
    reasons: List[str] = []
    docs_impact = "NO_CHANGE"

    for path in normalized:
        name = PurePosixPath(path).name
        if path.startswith(HANDOFF_PREFIX):
            reasons.append(f"human handoff content changed outside Docs Hook ownership: {path}")
            continue
        if path.startswith(SEMANTIC_PREFIXES):
            docs_impact = "SEMANTIC_REVIEW"
            reasons.append(f"public contract or data model changed: {path}")
            continue
        if path.startswith(DOCS_PREFIX):
            if docs_impact == "NO_CHANGE":
                docs_impact = "DETERMINISTIC"
            reasons.append(f"Agent-facing docs changed: {path}")
            continue
        if path.startswith(NO_IMPACT_PREFIXES) or name in NO_IMPACT_NAMES:
            reasons.append(f"routine internal or test-only change: {path}")
            continue
        if path.startswith(SOURCE_PREFIXES):
            if intent == "development" and change_kind not in {
                "test",
                "refactor",
                "temporary",
            }:
                docs_impact = "SEMANTIC_REVIEW"
                reasons.append(f"development behavior may change durable project knowledge: {path}")
            else:
                reasons.append(f"ordinary debug or unclassified source change: {path}")

    return {
        "docsImpact": docs_impact,
        "reasons": reasons,
        "changedPaths": normalized,
    }


class GitChangedPaths:
    def collect(self, repository: Path, baseline_revision: str) -> Dict[str, Any]:
        repository = repository.expanduser().resolve(strict=True)
        if not repository.is_dir():
            raise ContractError("Docs Hook repository must be a directory.")
        root = self._git(repository, ["rev-parse", "--show-toplevel"]).strip()
        if Path(root).resolve(strict=True) != repository:
            raise ContractError("Docs Hook repository path must be the Git worktree root.")
        baseline = self._git(
            repository, ["rev-parse", "--verify", f"{baseline_revision}^{{commit}}"]
        ).strip()
        head = self._git(repository, ["rev-parse", "--verify", "HEAD"]).strip()
        committed = self._git_bytes(
            repository,
            ["diff", "--name-only", "-z", "--diff-filter=ACDMRTUXB", baseline, "HEAD"],
        )
        working = self._git_bytes(
            repository,
            ["diff", "--name-only", "-z", "--diff-filter=ACDMRTUXB", "HEAD"],
        )
        untracked = self._git_bytes(
            repository, ["ls-files", "--others", "--exclude-standard", "-z"]
        )
        paths = _normalize_paths(
            item.decode("utf-8")
            for item in (committed + working + untracked).split(b"\0")
            if item
        )
        return {"baselineRevision": baseline, "candidateRevision": head, "paths": paths}

    def _git(self, repository: Path, args: List[str]) -> str:
        return self._git_bytes(repository, args).decode("utf-8")

    def _git_bytes(self, repository: Path, args: List[str]) -> bytes:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=repository,
                capture_output=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ContractError("Docs Hook Git inspection failed.") from error
        if result.returncode:
            raise ContractError("Docs Hook Git evidence is invalid or unavailable.")
        return result.stdout


class DocsImpactHook:
    def __init__(self, changed_paths: Optional[GitChangedPaths] = None):
        self._changed_paths = changed_paths or GitChangedPaths()

    def after_verification(
        self,
        *,
        repository: Path,
        baseline_revision: str,
        verification_passed: bool,
        intent: Optional[str],
        change_kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(verification_passed, bool):
            raise ContractError("Docs Hook verification result must be boolean.")
        if not verification_passed:
            return {
                "triggered": False,
                "reason": "verification_not_passed",
                "report": None,
            }
        return self.classify(repository=repository, baseline_revision=baseline_revision,
                             intent=intent, change_kind=change_kind)

    def classify(self, *, repository: Path, baseline_revision: str,
                 intent: Optional[str], change_kind: Optional[str] = None) -> Dict[str, Any]:
        """Inspect actual changes independently of the workflow's test result."""
        try:
            evidence = self._changed_paths.collect(repository, baseline_revision)
            classification = classify_changes(
                evidence["paths"], intent=intent, change_kind=change_kind
            )
        except ContractError as error:
            return {
                "triggered": True,
                "reason": "evidence_conflict",
                "report": {
                    "docsImpact": "CONFLICT",
                    "reasons": [error.message],
                    "proposedChanges": [],
                    "appliedChanges": [],
                    "conflicts": ["git_evidence_unavailable"],
                    "verification": {"status": "failed"},
                    "sourceArtifactRefs": [],
                    "requiresUserConfirmation": False,
                },
            }

        docs_impact = classification["docsImpact"]
        report = {
            **classification,
            "proposedChanges": (
                [{"kind": "semantic_docs_preview", "paths": classification["changedPaths"]}]
                if docs_impact == "SEMANTIC_REVIEW"
                else []
            ),
            "appliedChanges": [],
            "conflicts": [],
            "verification": {
                "status": "passed",
                "baselineRevision": evidence["baselineRevision"],
                "candidateRevision": evidence["candidateRevision"],
            },
            "sourceArtifactRefs": [],
            "requiresUserConfirmation": docs_impact == "SEMANTIC_REVIEW",
        }
        return {"triggered": True, "reason": "verification_completed", "report": report}
