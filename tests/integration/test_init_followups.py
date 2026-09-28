import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts" / "init_cli.py"
SCHEMA_VERSION = "ai-native-devkit/v1alpha1"


def run_cli(request, state_root, extra_environment=None):
    environment = os.environ.copy()
    environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
    if extra_environment:
        environment.update(extra_environment)
    return subprocess.run(
        [sys.executable, str(CLI_PATH)],
        input=json.dumps(request),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


class InitFollowupTests(unittest.TestCase):
    def test_empty_explicit_task_id_is_rejected_instead_of_using_caller_identity(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            completed = run_cli(
                {
                    "schema_version": SCHEMA_VERSION,
                    "operation": "init",
                    "task_id": "",
                    "repository": {"path": "/tmp"},
                    "user_request": "/init",
                },
                Path(temporary_directory) / "state",
                {"CODEX_THREAD_ID": "caller-must-not-win"},
            )

        self.assertNotEqual(completed.returncode, 0)
        response = json.loads(completed.stdout)
        self.assertEqual(response["kind"], "runtime_error")
        self.assertEqual(response["code"], "rejected.contract")

    def test_empty_repository_path_is_rejected_before_path_resolution(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            completed = run_cli(
                {
                    "schema_version": SCHEMA_VERSION,
                    "operation": "init",
                    "task_id": "task-empty-repository-path",
                    "repository": {"path": ""},
                    "user_request": "/init",
                },
                Path(temporary_directory) / "state",
            )

        self.assertNotEqual(completed.returncode, 0)
        response = json.loads(completed.stdout)
        self.assertEqual(response["kind"], "runtime_error")
        self.assertEqual(response["code"], "rejected.contract")


if __name__ == "__main__":
    unittest.main()
