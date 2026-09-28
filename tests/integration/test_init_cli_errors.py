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


class InitCliErrorTests(unittest.TestCase):
    def test_invalid_requests_emit_one_bounded_runtime_error_without_echoing_input(self):
        secret = "top-secret-cli-value"
        requests = [
            "{",
            json.dumps(
                {
                    "schema_version": "ai-native-devkit/v2",
                    "operation": "init",
                    "repository": {"path": "/tmp"},
                    "user_request": secret,
                }
            ),
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "operation": "unknown",
                    "repository": {"path": "/tmp"},
                    "user_request": secret,
                }
            ),
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "operation": "init",
                    "repository": {"path": "/tmp"},
                    "user_request": secret,
                    "choice": "invented-choice",
                }
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(
                Path(temporary_directory) / "state"
            )
            for request in requests:
                with self.subTest(request=request[:30]):
                    completed = subprocess.run(
                        [sys.executable, str(CLI_PATH)],
                        input=request,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=environment,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    response = json.loads(completed.stdout)
                    self.assertEqual(response["schema_version"], SCHEMA_VERSION)
                    self.assertEqual(response["kind"], "runtime_error")
                    self.assertEqual(response["code"], "rejected.contract")
                    self.assertLessEqual(len(response["message"]), 300)
                    self.assertNotIn(secret, completed.stdout)
                    self.assertNotIn(secret, completed.stderr)

    def test_oversized_request_is_rejected_without_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = os.environ.copy()
            environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(
                Path(temporary_directory) / "state"
            )
            completed = subprocess.run(
                [sys.executable, str(CLI_PATH)],
                input="x" * (1024 * 1024 + 1),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )

        self.assertNotEqual(completed.returncode, 0)
        response = json.loads(completed.stdout)
        self.assertEqual(response["kind"], "runtime_error")
        self.assertEqual(response["code"], "rejected.contract")


if __name__ == "__main__":
    unittest.main()
