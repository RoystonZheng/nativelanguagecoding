#!/usr/bin/env python3
import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Optional

SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSETS = SKILL_ROOT / "assets"
MANIFEST = ASSETS / "managed-docs.json"


def file_hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def has_symlink_component(root: Path, relative: Path) -> bool:
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def classify_hash(local_hash: str, entry: dict) -> tuple[str, Optional[str]]:
    current = entry["currentVersion"]
    versions = entry["versions"]
    if local_hash == versions[current]:
        return "CURRENT", current
    for version, known_hash in versions.items():
        if local_hash == known_hash:
            return "OUTDATED_UNMODIFIED", version
    return "LOCAL_MODIFIED", None


def load_manifest(path: Path = MANIFEST) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1 or not isinstance(data.get("documents"), dict):
        raise ValueError("managed docs manifest must use schemaVersion 1")

    for target, entry in data["documents"].items():
        target_path = Path(target)
        if (
            target_path.is_absolute()
            or ".." in target_path.parts
            or target_path.parts[:2] != ("docs", "runbooks")
        ):
            raise ValueError(f"unsafe managed target: {target}")
        source_path = Path(entry.get("source", ""))
        if source_path.is_absolute() or ".." in source_path.parts:
            raise ValueError(f"unsafe managed source: {source_path}")
        source = ASSETS / source_path
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"managed source must be a regular file: {source_path}")
        versions = entry.get("versions")
        current = entry.get("currentVersion")
        if not isinstance(versions, dict) or current not in versions:
            raise ValueError(f"missing current managed version: {target}")
        if file_hash(source) != versions[current]:
            raise ValueError(f"managed source hash mismatch: {target}")
    return data


def inspect(project_root: Path, manifest: dict) -> dict:
    documents = []
    for target, entry in manifest["documents"].items():
        relative = Path(target)
        path = project_root / relative
        item = {
            "path": target,
            "source": entry["source"],
            "currentVersion": entry["currentVersion"],
            "matchedVersion": None,
            "localHash": None,
        }
        if has_symlink_component(project_root, relative):
            item["status"] = "LOCAL_MODIFIED"
        elif not path.exists():
            item["status"] = "MISSING"
        elif not path.is_file():
            item["status"] = "LOCAL_MODIFIED"
        else:
            local_hash = file_hash(path)
            status, version = classify_hash(local_hash, entry)
            item["status"] = status
            item["matchedVersion"] = version
            item["localHash"] = local_hash
        documents.append(item)
    return {"valid": True, "documents": documents}


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"valid": False, "documents": [], "error": "PROJECT_ROOT required"}))
        return 2
    try:
        manifest = load_manifest()
        result = inspect(Path(sys.argv[1]).resolve(), manifest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"valid": False, "documents": [], "error": str(error)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
