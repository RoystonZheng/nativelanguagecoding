"""Validation for a user-selected, version-bound repository instruction authority."""

from datetime import datetime
from pathlib import PurePosixPath
import re

from .contracts import ArtifactRef
from .errors import ContractError


def validate_instruction_selection(value, *, persisted=False):
    required = {"report_ref", "preferred_sources", "confirmed_at", "provenance"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise ContractError("Instruction selection requires an exact report, sources and user confirmation.")
    reference = ArtifactRef.from_dict(value["report_ref"])
    if reference.artifact_type != "init_report":
        raise ContractError("Instruction selection must reference an InitReport.")
    sources = value["preferred_sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
        raise ContractError("Instruction selection must contain 1 to 32 preferred sources.")
    directories = set()
    for source in sources:
        if not isinstance(source, str):
            raise ContractError("Instruction selection source must be a relative path.")
        path = PurePosixPath(source)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != source or path.name not in {"AGENTS.md", "CLAUDE.md"}:
            raise ContractError("Instruction selection source must name a scoped AGENTS.md or CLAUDE.md.")
        if path.parent in directories:
            raise ContractError("Choose only one instruction source per directory.")
        directories.add(path.parent)
    timestamp = value["confirmed_at"]
    try:
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            raise ValueError()
        datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as error:
        raise ContractError("Instruction selection requires a UTC confirmation timestamp.") from error
    if not isinstance(value["provenance"], str) or not 1 <= len(value["provenance"]) <= 500:
        raise ContractError("Instruction selection requires bounded user-confirmation provenance.")
    if persisted:
        hashes = value.get("source_hashes")
        if not isinstance(hashes, dict) or not hashes or len(hashes) > 256:
            raise ContractError("Persisted instruction selection requires bounded source hashes.")
        for path, digest in hashes.items():
            if not isinstance(path, str) or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or PurePosixPath(path).as_posix() != path or PurePosixPath(path).name not in {"AGENTS.md", "CLAUDE.md"}:
                raise ContractError("Instruction selection source hash path is invalid.")
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ContractError("Instruction selection source hash is invalid.")
        if not set(sources).issubset(hashes):
            raise ContractError("Preferred sources require exact hashes.")
    elif "source_hashes" in value:
        raise ContractError("Instruction source hashes come from the referenced report, not the caller.")


def validate_instruction_differences(details):
    if not isinstance(details, dict) or not {"instruction_differences", "omitted_groups"}.issubset(details):
        raise ContractError("Instruction differences require bounded groups and an omitted count.")
    groups, omitted = details["instruction_differences"], details["omitted_groups"]
    if not isinstance(groups, list) or len(groups) > 32 or type(omitted) is not int or omitted < 0:
        raise ContractError("Instruction difference groups are invalid.")
    for group in groups:
        if not isinstance(group, dict) or not {"directory", "left", "right", "changes"}.issubset(group):
            raise ContractError("Instruction difference group is invalid.")
        for side, name in (("left", "AGENTS.md"), ("right", "CLAUDE.md")):
            source = group[side]
            if not isinstance(source, dict) or not isinstance(source.get("path"), str):
                raise ContractError("Instruction difference source is invalid.")
            path = PurePosixPath(source["path"])
            if path.is_absolute() or ".." in path.parts or path.as_posix() != source["path"] or path.name != name or path.parent.as_posix() != group["directory"]:
                raise ContractError("Instruction difference sources must share their declared directory.")
            if not isinstance(source.get("hash"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", source["hash"]):
                raise ContractError("Instruction difference source hash is invalid.")
        changes = group["changes"]
        if not isinstance(changes, list) or not 1 <= len(changes) <= 8:
            raise ContractError("Instruction difference ranges are invalid.")
        for change in changes:
            if not isinstance(change, dict) or not {"left", "right"}.issubset(change) or change["left"] is None and change["right"] is None:
                raise ContractError("Instruction difference requires at least one rule range.")
            if any(flag in change and type(change[flag]) is not bool for flag in ("comparison_limited", "more_differences")):
                raise ContractError("Instruction difference truncation flags must be booleans.")
            for side in ("left", "right"):
                item = change[side]
                if item is None:
                    continue
                if not isinstance(item, dict) or not {"line_start", "line_end", "excerpt", "truncated"}.issubset(item):
                    raise ContractError("Instruction rule range is invalid.")
                if type(item["line_start"]) is not int or type(item["line_end"]) is not int or not 1 <= item["line_start"] <= item["line_end"]:
                    raise ContractError("Instruction rule line numbers are invalid.")
                if not isinstance(item["excerpt"], str) or len(item["excerpt"]) > 300 or type(item["truncated"]) is not bool:
                    raise ContractError("Instruction rule excerpt is invalid.")
