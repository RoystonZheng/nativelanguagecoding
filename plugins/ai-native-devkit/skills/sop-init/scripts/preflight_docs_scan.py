#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path


def scan_directory(
    project_root: Path,
    directory: Path,
    safe_paths: list[str],
    unsafe_aliases: list[str],
    blocked_paths: list[str],
) -> None:
    try:
        with os.scandir(directory) as iterator:
            entries = list(iterator)
    except OSError:
        blocked_paths.append(str(directory.relative_to(project_root)))
        return

    for entry in entries:
        path = Path(entry.path)
        relative = path.relative_to(project_root)
        if directory == project_root / "docs" and entry.name == "handoff":
            continue
        if entry.is_symlink():
            unsafe_aliases.append(str(relative))
            continue
        if entry.is_dir(follow_symlinks=False):
            scan_directory(
                project_root,
                path,
                safe_paths,
                unsafe_aliases,
                blocked_paths,
            )
            continue
        if entry.is_file(follow_symlinks=False):
            safe_paths.append(str(relative))
        else:
            blocked_paths.append(str(relative))


def inspect(project_root: Path) -> dict:
    safe_paths = []
    unsafe_aliases = []
    blocked_paths = []

    for name in ("AGENTS.md", "CLAUDE.md"):
        path = project_root / name
        if path.is_symlink():
            unsafe_aliases.append(name)
        elif path.is_file():
            safe_paths.append(name)
        elif path.exists():
            blocked_paths.append(name)

    docs = project_root / "docs"
    if docs.is_symlink():
        unsafe_aliases.append("docs")
    elif docs.is_dir():
        scan_directory(
            project_root,
            docs,
            safe_paths,
            unsafe_aliases,
            blocked_paths,
        )
    elif docs.exists():
        blocked_paths.append("docs")

    unsafe_aliases.sort()
    blocked_paths.sort()
    return {
        "safeToInspect": not unsafe_aliases and not blocked_paths,
        "safePaths": sorted(safe_paths),
        "unsafeAliases": unsafe_aliases,
        "blockedPaths": blocked_paths,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(
            json.dumps(
                {
                    "safeToInspect": False,
                    "safePaths": [],
                    "unsafeAliases": [],
                    "blockedPaths": [],
                    "error": "PROJECT_ROOT required",
                }
            )
        )
        return 2
    try:
        result = inspect(Path(sys.argv[1]).resolve())
    except OSError as error:
        print(
            json.dumps(
                {
                    "safeToInspect": False,
                    "safePaths": [],
                    "unsafeAliases": [],
                    "blockedPaths": [],
                    "error": str(error),
                }
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
