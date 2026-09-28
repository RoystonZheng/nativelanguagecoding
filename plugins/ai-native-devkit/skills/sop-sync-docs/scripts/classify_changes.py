#!/usr/bin/env python3
import json
from pathlib import Path
import sys


PLUGIN_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(PLUGIN_SCRIPTS))

from ai_native_devkit.docs_hook import classify_changes  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: classify_changes.py CHANGED_FILES_PATH"}))
        return 2
    paths = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    result = classify_changes(paths)
    result.pop("changedPaths")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
