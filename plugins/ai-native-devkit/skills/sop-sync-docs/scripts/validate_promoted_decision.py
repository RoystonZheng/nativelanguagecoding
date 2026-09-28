#!/usr/bin/env python3
"""Validate provenance and state labels on a promoted decision record."""

import json
from pathlib import Path
import re
import sys


REQUIRED = {
    "status",
    "state_class",
    "implementation_status",
    "source_requirement_path",
    "source_requirement_commit",
    "source_requirement_blob_digest",
}
LEGACY_PROVENANCE = {
    "source_task_id",
    "source_artifact_id",
    "source_artifact_type",
    "source_artifact_digest",
}
REQUIREMENT_PATH = re.compile(
    r"docs/superpowers/requirements/"
    r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*-requirements(?:-\d+)?\.md"
)
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
BLOB = re.compile(r"(?:git-sha1:[0-9a-f]{40}|git-sha256:[0-9a-f]{64})")


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}
    values = {}
    for line in lines[1:]:
        if line == "---":
            return values
        if ":" not in line:
            return {}
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return {}


def validate(path: Path) -> dict:
    errors = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {"valid": False, "errors": ["decision could not be read"]}
    values = parse_frontmatter(text)
    missing = sorted(REQUIRED.difference(values))
    if missing:
        errors.append("missing frontmatter: " + ", ".join(missing))
    legacy = sorted(LEGACY_PROVENANCE.intersection(values))
    if legacy:
        errors.append("legacy provenance is unsupported: " + ", ".join(legacy))
    if values.get("status") not in {"accepted", "superseded", "deprecated"}:
        errors.append("status is invalid")
    state_class = values.get("state_class")
    implementation = values.get("implementation_status")
    if state_class not in {"CurrentState", "RequestedState", "ProposedState"}:
        errors.append("state_class is invalid")
    if implementation not in {"implemented", "not_implemented"}:
        errors.append("implementation_status is invalid")
    if state_class == "RequestedState" and implementation != "not_implemented":
        errors.append("RequestedState must remain not_implemented")
    if state_class == "CurrentState" and implementation != "implemented":
        errors.append("CurrentState requires implemented evidence")
    requirement_path = values.get("source_requirement_path", "")
    commit = values.get("source_requirement_commit", "")
    blob = values.get("source_requirement_blob_digest", "")
    if not REQUIREMENT_PATH.fullmatch(requirement_path):
        errors.append("source_requirement_path is invalid")
    if not COMMIT.fullmatch(commit):
        errors.append("source_requirement_commit is invalid")
    if not BLOB.fullmatch(blob):
        errors.append("source_requirement_blob_digest is invalid")
    if COMMIT.fullmatch(commit) and BLOB.fullmatch(blob):
        expected_algorithm = "git-sha1:" if len(commit) == 40 else "git-sha256:"
        if not blob.startswith(expected_algorithm):
            errors.append("requirement commit and blob algorithms do not match")
    if not re.search(r"^# \d{4}\. \S", text, re.MULTILINE):
        errors.append("decision title is missing")
    return {"valid": not errors, "errors": errors}


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"valid": False, "errors": ["usage: DECISION_PATH"]}))
        return 2
    result = validate(Path(sys.argv[1]))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
