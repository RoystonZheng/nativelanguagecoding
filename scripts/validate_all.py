#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODEX_HOME = Path(
    os.environ.get("CODEX_HOME") or Path.home() / ".codex"
).expanduser().resolve()
PLUGIN = ROOT / "plugins/ai-native-devkit"
SKILLS = PLUGIN / "skills"
SKILL_VALIDATOR = (
    CODEX_HOME / "skills/.system/skill-creator/scripts/quick_validate.py"
).resolve()
PLUGIN_VALIDATOR = (
    CODEX_HOME / "skills/.system/plugin-creator/scripts/validate_plugin.py"
).resolve()
TEST_COMMAND = [
    sys.executable,
    "-m",
    "unittest",
    "discover",
    "-s",
    "tests",
    "-v",
]


def _missing_validator(label: str, path: Path, relative_path: str) -> int:
    print(
        f"{label} not found at {path}. Set CODEX_HOME to a Codex home "
        f"containing {relative_path}.",
        file=sys.stderr,
    )
    return 2


def _packaged_skills() -> list[Path]:
    return sorted(
        (
            path
            for path in SKILLS.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        ),
        key=lambda path: path.name,
    )


def main() -> int:
    if not SKILL_VALIDATOR.is_file():
        return _missing_validator(
            "Skill quick validator",
            SKILL_VALIDATOR,
            "skills/.system/skill-creator/scripts/quick_validate.py",
        )

    result = subprocess.run(TEST_COMMAND, cwd=ROOT)
    if result.returncode:
        return result.returncode

    if not SKILLS.is_dir():
        print(f"Packaged skills directory not found at {SKILLS}.", file=sys.stderr)
        return 2

    skills = _packaged_skills()
    if not skills:
        print(f"No packaged Skills found under {SKILLS}.", file=sys.stderr)
        return 2

    for skill in skills:
        result = subprocess.run(
            [sys.executable, str(SKILL_VALIDATOR), str(skill)],
            cwd=ROOT,
        )
        if result.returncode:
            return result.returncode

    if not PLUGIN_VALIDATOR.is_file():
        return _missing_validator(
            "Plugin validator",
            PLUGIN_VALIDATOR,
            "skills/.system/plugin-creator/scripts/validate_plugin.py",
        )

    result = subprocess.run(
        [sys.executable, str(PLUGIN_VALIDATOR), str(PLUGIN)],
        cwd=ROOT,
    )
    if result.returncode:
        return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
