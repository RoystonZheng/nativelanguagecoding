import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SCRIPTS = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

from ai_native_devkit.docs_init_observer import DocsInitObserver


INIT_CLI = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts" / "init_cli.py"
DOCS_VALIDATOR = (
    PROJECT_ROOT
    / "plugins"
    / "ai-native-devkit"
    / "skills"
    / "sop-init"
    / "scripts"
    / "validate_project_docs.py"
)
SCHEMA_VERSION = "ai-native-devkit/v1alpha1"


def git(repository, *arguments):
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def create_repository(path):
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.com")
    (path / "README.md").write_text("# Project\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-m", "initial")


def run_init(state_root, repository, session_id, **overrides):
    request = {
        "schema_version": SCHEMA_VERSION,
        "operation": "init",
        "repository": {"path": str(repository)},
        "user_request": "$sop-init",
        **overrides,
    }
    environment = os.environ.copy()
    environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
    environment["CODEX_THREAD_ID"] = session_id
    return subprocess.run(
        [sys.executable, str(INIT_CLI)],
        input=json.dumps(request),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


def load_trace(state_root, session_id):
    session_key = __import__("hashlib").sha256(session_id.encode("utf-8")).hexdigest()
    trace_root = state_root / "execution-traces"
    index = json.loads(
        (trace_root / ".sessions" / f"{session_key}.json").read_text(encoding="utf-8")
    )
    trace_dir = trace_root / index["trace_id"]
    return {
        "metadata": json.loads((trace_dir / "metadata.json").read_text(encoding="utf-8")),
        "events": [
            json.loads(line)
            for line in (trace_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ],
        "summary": json.loads((trace_dir / "summary.json").read_text(encoding="utf-8")),
    }


def run_validator(state_root, repository, session_id):
    environment = os.environ.copy()
    environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
    environment["CODEX_THREAD_ID"] = session_id
    return subprocess.run(
        [sys.executable, str(DOCS_VALIDATOR), str(repository)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


class InitRuntimeTraceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.repository = self.root / "repository"
        create_repository(self.repository)

    def tearDown(self):
        self.temporary.cleanup()

    def test_init_cli_automatically_emits_redacted_runtime_stage_facts(self):
        completed = run_init(self.state, self.repository, "session-init-trace")

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertEqual(json.loads(completed.stdout)["kind"], "report")
        trace = load_trace(self.state, "session-init-trace")
        self.assertEqual(
            [event["event_type"] for event in trace["events"]],
            [
                "workflow.started",
                "workflow.stage.started",
                "init.mode.selected",
                "init.context.inspected",
            ],
        )
        self.assertTrue(
            all(event["source"] == "devkit_runtime" for event in trace["events"])
        )
        stage_run_ids = {
            event["correlation"]["stage_run_id"] for event in trace["events"][1:]
        }
        self.assertEqual(len(stage_run_ids), 1)
        self.assertNotIn("task_id", json.dumps(trace))
        self.assertNotIn(str(self.repository), json.dumps(trace))
        self.assertEqual(trace["metadata"]["workflow_name"], "coding-sop")
        self.assertEqual(
            trace["summary"]["actual_stages"],
            [
                {
                    "duration_ms": None,
                    "ended_at": None,
                    "repository": trace["events"][1]["payload"]["repository"],
                    "stage": "init",
                    "stage_run_id": trace["events"][1]["correlation"]["stage_run_id"],
                    "started_at": trace["events"][1]["timestamp"],
                    "status": "started",
                }
            ],
        )
        self.assertEqual(trace["summary"]["init_result"]["outcome"], "ready")
        self.assertEqual(
            trace["summary"]["init_result"]["phase"], "context_inspection"
        )
        self.assertEqual(
            trace["summary"]["init_result"]["gaps"],
            ["repository_instructions", "verification_commands"],
        )

    def test_init_choice_is_recorded_without_agent_logging(self):
        session_id = "session-init-choice"
        first = run_init(self.state, self.repository, session_id)
        self.assertEqual(first.returncode, 0, first.stdout)
        task_id = json.loads(first.stdout)["report"]["task_id"]

        choice_required = run_init(self.state, self.repository, session_id)
        self.assertEqual(json.loads(choice_required.stdout)["kind"], "choice_required")
        reused = run_init(
            self.state,
            self.repository,
            session_id,
            task_id=task_id,
            choice="reuse",
        )

        self.assertEqual(reused.returncode, 0, reused.stderr or reused.stdout)
        trace = load_trace(self.state, session_id)
        approval_events = [
            event
            for event in trace["events"]
            if event["event_type"] in {"approval.requested", "approval.resolved"}
        ]
        self.assertEqual(
            [event["event_type"] for event in approval_events],
            ["approval.requested", "approval.resolved"],
        )
        self.assertEqual(approval_events[0]["payload"]["reason"], "init.ready_current")
        self.assertEqual(approval_events[1]["payload"]["decision"], "reuse")
        self.assertEqual(
            approval_events[0]["payload"]["approval_id"],
            approval_events[1]["payload"]["approval_id"],
        )
        self.assertTrue(
            all("task_id" not in event["payload"] for event in trace["events"])
        )

    def test_different_repository_workflow_task_stays_in_the_same_session_trace(self):
        session_id = "session-cross-repository"
        other = self.root / "other"
        create_repository(other)

        first = run_init(self.state, self.repository, session_id)
        second = run_init(self.state, other, session_id)

        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertEqual(second.returncode, 0, second.stdout)
        first_task_id = json.loads(first.stdout)["report"]["task_id"]
        second_task_id = json.loads(second.stdout)["report"]["task_id"]
        self.assertNotEqual(first_task_id, second_task_id)
        trace = load_trace(self.state, session_id)
        self.assertEqual(
            sum(event["event_type"] == "workflow.started" for event in trace["events"]),
            1,
        )
        self.assertEqual(
            sum(
                event["event_type"] == "init.context.inspected"
                for event in trace["events"]
            ),
            2,
        )
        self.assertTrue(
            all("task_id" not in event["payload"] for event in trace["events"])
        )
        self.assertNotIn(second_task_id, json.dumps(trace))

    def test_docs_validator_completes_init_with_deterministic_file_details(self):
        fixture = PROJECT_ROOT / "tests" / "fixtures" / "standard-project"
        for source in fixture.rglob("*"):
            target = self.repository / source.relative_to(fixture)
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        session_id = "session-init-docs-details"
        initialized = run_init(self.state, self.repository, session_id)
        self.assertEqual(initialized.returncode, 0, initialized.stdout)

        product = self.repository / "docs/overview/product.md"
        product.write_text(
            product.read_text(encoding="utf-8") + "\n已验证补充。\n",
            encoding="utf-8",
        )
        generated = self.repository / "docs/generated.txt"
        generated.write_text("generated\n", encoding="utf-8")
        validated = run_validator(self.state, self.repository, session_id)

        self.assertEqual(validated.returncode, 0, validated.stderr or validated.stdout)
        trace = load_trace(self.state, session_id)
        result = trace["summary"]["init_result"]
        self.assertEqual(result["mode"], "Refresh")
        self.assertIn("docs/generated.txt", result["generated"])
        self.assertIn("docs/overview/product.md", result["overwritten"])
        self.assertIn("docs/api/README.md", result["preserved"])
        self.assertEqual(result["conflicts"], [])
        stage = trace["summary"]["actual_stages"][0]
        self.assertEqual(stage["status"], "completed")
        self.assertIsNotNone(stage["started_at"])
        self.assertIsNotNone(stage["ended_at"])

    def test_init_docs_observer_excludes_workflow_record_subtrees(self):
        fixture = PROJECT_ROOT / "tests" / "fixtures" / "standard-project"
        for source in fixture.rglob("*"):
            target = self.repository / source.relative_to(fixture)
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

        records = {
            "docs/superpowers/requirements/2026-08-27-private-requirements.md": (
                b"\xffprivate requirement\n"
            ),
            "docs/superpowers/specs/2026-08-27-private-design.md": (
                b"private design\n"
            ),
            "docs/superpowers/plans/2026-08-27-private-plan.md": (
                b"private plan\n"
            ),
        }
        for relative, content in records.items():
            target = self.repository / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        protected = self.repository / next(
            relative for relative in records if "/specs/" in relative
        )
        protected.chmod(0)

        observer = DocsInitObserver(
            self.state,
            "session-init-excludes-workflow-records",
            self.repository,
        )
        try:
            before = observer.prepare()
            observed_before = set(before["files"]) | set(before["conflicts"])
            for directory in ("requirements", "specs", "plans"):
                prefix = f"docs/superpowers/{directory}/"
                self.assertFalse(
                    any(path.startswith(prefix) for path in observed_before),
                    observed_before,
                )
            self.assertIn("docs/superpowers/README.md", before["files"])
            self.assertIn("docs/overview/product.md", before["files"])

            product = self.repository / "docs/overview/product.md"
            product.write_text(
                product.read_text(encoding="utf-8") + "\nObserved change.\n",
                encoding="utf-8",
            )
            payload = observer.complete(
                {"valid": True, "missing": [], "brokenLinks": []}
            )
        finally:
            protected.chmod(0o600)

        self.assertIsNotNone(payload)
        assert payload is not None
        observed_after = {
            path
            for field in (
                "recognized",
                "generated",
                "overwritten",
                "preserved",
                "removed",
                "conflicts",
            )
            for path in payload[field]
        }
        for directory in ("requirements", "specs", "plans"):
            prefix = f"docs/superpowers/{directory}/"
            self.assertFalse(
                any(path.startswith(prefix) for path in observed_after),
                observed_after,
            )
        self.assertIn("docs/superpowers/README.md", payload["preserved"])
        self.assertIn("docs/overview/product.md", payload["overwritten"])
        self.assertEqual(
            {
                relative: (self.repository / relative).read_bytes()
                for relative in records
            },
            records,
        )

    def test_init_docs_observer_sanitizes_resumed_v1_workflow_records(self):
        superpowers = self.repository / "docs/superpowers"
        superpowers.mkdir(parents=True)
        index = superpowers / "README.md"
        index.write_text("# Workflow records\n", encoding="utf-8")
        index_digest = "sha256:" + __import__("hashlib").sha256(
            index.read_bytes()
        ).hexdigest()
        records = {
            "docs/superpowers/requirements/2026-08-27-old-requirements.md": (
                b"\xffold requirement\n"
            ),
            "docs/superpowers/specs/2026-08-27-old-design.md": b"old design\n",
            "docs/superpowers/plans/2026-08-27-old-plan.md": b"old plan\n",
        }
        for relative, content in records.items():
            target = self.repository / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        self.state.mkdir(mode=0o700)
        self.state.chmod(0o700)

        def seed_active(observer, *, files, conflicts, mode):
            observer.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            observer.root.chmod(0o700)
            record = {
                "schema_version": "ai-native-devkit/init-docs-observation/v1",
                "repository": str(observer.repository),
                "stage_run_id": str(__import__("uuid").uuid4()),
                "mode": mode,
                "files": files,
                "conflicts": conflicts,
                "status": "active",
                "compatible_extension": {"retained": True},
            }
            observer.path.write_text(json.dumps(record), encoding="utf-8")
            observer.path.chmod(0o600)

        excluded_digests = {
            relative: "sha256:" + character * 64
            for relative, character in zip(records, "abc")
        }
        observer = DocsInitObserver(
            self.state,
            "session-resume-old-init-observation",
            self.repository,
        )
        seed_active(
            observer,
            files={
                "docs/superpowers/README.md": index_digest,
                **excluded_digests,
            },
            conflicts=[next(iter(records))],
            mode="Adapt",
        )

        prepared = observer.prepare()
        self.assertEqual(
            prepared["files"],
            {"docs/superpowers/README.md": index_digest},
        )
        self.assertEqual(prepared["conflicts"], [])
        self.assertEqual(prepared["mode"], "Adapt")
        self.assertEqual(
            prepared["compatible_extension"], {"retained": True}
        )
        self.assertEqual(observer.prepare(), prepared)
        persisted = json.loads(observer.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted, prepared)

        trace = load_trace(self.state, "session-resume-old-init-observation")
        serialized_trace = json.dumps(trace)
        for directory in ("requirements", "specs", "plans"):
            self.assertNotIn(f"docs/superpowers/{directory}/", serialized_trace)
        for digest in excluded_digests.values():
            self.assertNotIn(digest, serialized_trace)

        payload = observer.complete(
            {"valid": True, "missing": [], "brokenLinks": []}
        )
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["recognized"], ["docs/superpowers/README.md"])
        self.assertEqual(payload["preserved"], ["docs/superpowers/README.md"])
        self.assertEqual(payload["removed"], [])
        self.assertEqual(payload["conflicts"], [])
        serialized_trace = json.dumps(
            load_trace(self.state, "session-resume-old-init-observation")
        )
        for directory in ("requirements", "specs", "plans"):
            self.assertNotIn(f"docs/superpowers/{directory}/", serialized_trace)
        self.assertEqual(
            {
                relative: (self.repository / relative).read_bytes()
                for relative in records
            },
            records,
        )

        excluded_only = DocsInitObserver(
            self.state,
            "session-resume-excluded-only-observation",
            self.repository,
        )
        seed_active(
            excluded_only,
            files=excluded_digests,
            conflicts=list(records),
            mode="Adapt",
        )
        excluded_only_prepared = excluded_only.prepare()
        self.assertEqual(excluded_only_prepared["files"], {})
        self.assertEqual(excluded_only_prepared["conflicts"], [])
        self.assertEqual(excluded_only_prepared["mode"], "Bootstrap")
        self.assertEqual(
            excluded_only_prepared["compatible_extension"], {"retained": True}
        )
        excluded_only_payload = excluded_only.complete(
            {"valid": True, "missing": [], "brokenLinks": []}
        )
        self.assertIsNotNone(excluded_only_payload)
        assert excluded_only_payload is not None
        self.assertEqual(excluded_only_payload["recognized"], [])
        self.assertEqual(excluded_only_payload["removed"], [])
        self.assertEqual(excluded_only_payload["conflicts"], [])
        excluded_only_trace = json.dumps(
            load_trace(self.state, "session-resume-excluded-only-observation")
        )
        for directory in ("requirements", "specs", "plans"):
            self.assertNotIn(
                f"docs/superpowers/{directory}/",
                excluded_only_trace,
            )
        for digest in excluded_digests.values():
            self.assertNotIn(digest, excluded_only_trace)

    def test_trace_storage_failure_does_not_block_init(self):
        (self.state / "execution-traces").mkdir(parents=True)
        self.state.chmod(0o700)
        (self.state / "execution-traces").chmod(0o700)
        (self.state / "execution-traces" / ".sessions").write_text(
            "not a directory", encoding="utf-8"
        )

        completed = run_init(self.state, self.repository, "session-trace-failure")

        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        self.assertEqual(json.loads(completed.stdout)["kind"], "report")


if __name__ == "__main__":
    unittest.main()
