import io
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import scripts.validate_all as validate_all


class ValidationEntrypointTests(unittest.TestCase):
    def test_relative_codex_home_resolves_to_absolute_validator_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            launch_directory = Path(temporary) / "launch"
            launch_directory.mkdir()
            original_directory = Path.cwd()
            try:
                os.chdir(launch_directory)
                with mock.patch.dict(
                    os.environ, {"CODEX_HOME": "relative-codex-home"}
                ):
                    initialized = runpy.run_path(
                        validate_all.__file__,
                        run_name="validate_all_relative_home_fixture",
                    )
            finally:
                os.chdir(original_directory)

        expected_home = (launch_directory / "relative-codex-home").resolve()
        self.assertEqual(initialized["CODEX_HOME"], expected_home)
        self.assertEqual(
            initialized["SKILL_VALIDATOR"],
            expected_home
            / "skills/.system/skill-creator/scripts/quick_validate.py",
        )
        self.assertEqual(
            initialized["PLUGIN_VALIDATOR"],
            expected_home
            / "skills/.system/plugin-creator/scripts/validate_plugin.py",
        )

    def _layout(self, root: Path) -> dict[str, Path]:
        plugin = root / "plugins" / "ai-native-devkit"
        skills = plugin / "skills"
        for name in ("zeta", "alpha"):
            skill = skills / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: fixture\n---\n"
            )
        non_skill = skills / "references"
        non_skill.mkdir()
        (non_skill / "README.md").write_text("not a skill\n")

        skill_validator = root / "codex" / "quick_validate.py"
        plugin_validator = root / "codex" / "validate_plugin.py"
        skill_validator.parent.mkdir()
        skill_validator.touch()
        plugin_validator.touch()
        return {
            "plugin": plugin,
            "skills": skills,
            "skill_validator": skill_validator,
            "plugin_validator": plugin_validator,
        }

    def _patch_layout(self, root: Path, layout: dict[str, Path]):
        return mock.patch.multiple(
            validate_all,
            ROOT=root,
            PLUGIN=layout["plugin"],
            SKILLS=layout["skills"],
            SKILL_VALIDATOR=layout["skill_validator"],
            PLUGIN_VALIDATOR=layout["plugin_validator"],
            create=True,
        )

    def test_runs_each_packaged_skill_validator_before_plugin_validator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = self._layout(root)
            completed = subprocess.CompletedProcess([], 0)
            with self._patch_layout(root, layout), mock.patch.object(
                validate_all.subprocess, "run", return_value=completed
            ) as run:
                self.assertEqual(validate_all.main(), 0)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            commands,
            [
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-v",
                ],
                [
                    sys.executable,
                    str(layout["skill_validator"]),
                    str(layout["skills"] / "alpha"),
                ],
                [
                    sys.executable,
                    str(layout["skill_validator"]),
                    str(layout["skills"] / "zeta"),
                ],
                [
                    sys.executable,
                    str(layout["plugin_validator"]),
                    str(layout["plugin"]),
                ],
            ],
        )
        self.assertTrue(
            all(call.kwargs == {"cwd": root} for call in run.call_args_list)
        )

    def test_stops_before_remaining_skills_and_plugin_on_skill_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = self._layout(root)

            def result_for(command, cwd):
                del cwd
                return subprocess.CompletedProcess(
                    command,
                    7 if command[-1] == str(layout["skills"] / "alpha") else 0,
                )

            with self._patch_layout(root, layout), mock.patch.object(
                validate_all.subprocess, "run", side_effect=result_for
            ) as run:
                self.assertEqual(validate_all.main(), 7)

        self.assertEqual(len(run.call_args_list), 2)
        self.assertEqual(
            run.call_args_list[-1].args[0],
            [
                sys.executable,
                str(layout["skill_validator"]),
                str(layout["skills"] / "alpha"),
            ],
        )

    def test_missing_skill_validator_reports_actionable_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = self._layout(root)
            layout["skill_validator"].unlink()
            stderr = io.StringIO()
            with self._patch_layout(root, layout), mock.patch.object(
                validate_all.subprocess, "run"
            ) as run, redirect_stderr(stderr):
                self.assertEqual(validate_all.main(), 2)

        run.assert_not_called()
        self.assertIn("Skill quick validator not found", stderr.getvalue())
        self.assertIn(str(layout["skill_validator"]), stderr.getvalue())
        self.assertIn("CODEX_HOME", stderr.getvalue())

    def test_missing_plugin_validator_is_reported_after_skill_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layout = self._layout(root)
            layout["plugin_validator"].unlink()
            stderr = io.StringIO()
            completed = subprocess.CompletedProcess([], 0)
            with self._patch_layout(root, layout), mock.patch.object(
                validate_all.subprocess, "run", return_value=completed
            ) as run, redirect_stderr(stderr):
                self.assertEqual(validate_all.main(), 2)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(commands), 3)
        self.assertNotIn(
            [
                sys.executable,
                str(layout["plugin_validator"]),
                str(layout["plugin"]),
            ],
            commands,
        )
        self.assertIn("Plugin validator not found", stderr.getvalue())
        self.assertIn(str(layout["plugin_validator"]), stderr.getvalue())
        self.assertIn("CODEX_HOME", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
