import contextlib
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit import cli
from ai_native_devkit.persistence import InMemoryAtomicPersistence
from tests.init_fixtures import ReadyInspector


class CliPreflightTests(unittest.TestCase):
    def _captured_main(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = cli.main()
        return status, json.loads(output.getvalue())

    def test_unsupported_python_returns_one_typed_runtime_error(self):
        with mock.patch.object(cli.sys, "version_info", (3, 8, 18)):
            status, response = self._captured_main()

        self.assertNotEqual(status, 0)
        self.assertEqual(response["kind"], "runtime_error")
        self.assertEqual(response["code"], "runtime.unsupported_python")
        self.assertFalse(response["retryable"])

    def test_unsupported_host_returns_one_typed_runtime_error(self):
        with mock.patch.object(cli.platform, "system", return_value="Windows"):
            status, response = self._captured_main()

        self.assertNotEqual(status, 0)
        self.assertEqual(response["kind"], "runtime_error")
        self.assertEqual(response["code"], "runtime.unsupported_host")
        self.assertFalse(response["retryable"])

    def test_concurrent_implicit_identity_with_different_targets_creates_two_tasks(self):
        class RacingPersistence(InMemoryAtomicPersistence):
            """Force both callers to read MISSING before either create commits."""

            def __init__(self):
                super().__init__()
                self._thread_loads = threading.local()
                self._load_barriers = [
                    threading.Barrier(2),
                    threading.Barrier(2),
                ]

            def load_bytes(self, task_id):
                with self._lock:
                    value = self._values.get(task_id)
                load_index = getattr(self._thread_loads, "count", 0)
                self._thread_loads.count = load_index + 1
                if task_id == "shared-caller" and load_index < len(
                    self._load_barriers
                ):
                    self._load_barriers[load_index].wait(timeout=5)
                return value

        requests = {
            "first": {
                "schema_version": cli.SCHEMA_VERSION,
                "operation": "init",
                "repository": {"path": "/tmp/first"},
                "user_request": "Initialize first",
            },
            "second": {
                "schema_version": cli.SCHEMA_VERSION,
                "operation": "init",
                "repository": {"path": "/tmp/second"},
                "user_request": "Initialize second",
            },
        }
        persistence = RacingPersistence()
        responses = []
        errors = []

        def read_request():
            return requests[threading.current_thread().name]

        def initialize():
            try:
                responses.append(cli.run())
            except Exception as error:
                errors.append(error)

        with (
            mock.patch.object(cli, "_preflight"),
            mock.patch.object(cli, "_read_request", side_effect=read_request),
            mock.patch.object(cli, "_state_root", return_value=Path("/tmp/test-state")),
            mock.patch.object(cli, "_validate_state_root"),
            mock.patch.object(cli, "RepositoryInspector", ReadyInspector),
            mock.patch.object(
                cli,
                "FilesystemAtomicPersistence",
                return_value=persistence,
            ),
            mock.patch.dict(
                cli.os.environ,
                {"CODEX_THREAD_ID": "shared-caller", "CODEX_TASK_ID": ""},
            ),
        ):
            threads = [
                threading.Thread(name=name, target=initialize) for name in requests
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(responses), 2)
        self.assertEqual(
            {
                response["report"]["payload"]["repository"]["root"]
                for response in responses
            },
            {"/tmp/first", "/tmp/second"},
        )
        task_ids = {response["report"]["task_id"] for response in responses}
        self.assertEqual(len(task_ids), 2)
        self.assertIn("shared-caller", task_ids)


if __name__ == "__main__":
    unittest.main()
