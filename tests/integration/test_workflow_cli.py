import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = (
    PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts" / "workflow_cli.py"
)
RUNTIME_CLI_PATH = CLI_PATH.with_name("runtime_cli.py")
SCRIPTS_ROOT = CLI_PATH.parent
SCHEMA_VERSION = "ai-native-devkit/v1alpha1"
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit.execution_trace import ExecutionTraceStore, repository_digest
from ai_native_devkit.requirement_document import (
    RequirementDocumentWriter,
    RequirementSource,
)


def run_cli(state_root, request, session_id=None):
    environment = os.environ.copy()
    environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
    environment.pop("CODEX_THREAD_ID", None)
    environment.pop("CODEX_TASK_ID", None)
    if session_id is not None:
        environment["CODEX_THREAD_ID"] = session_id
    return subprocess.run(
        [sys.executable, str(CLI_PATH)],
        input=json.dumps(request),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


def run_runtime_cli(state_root, request, session_id):
    environment = os.environ.copy()
    environment["AI_NATIVE_DEVKIT_STATE_ROOT"] = str(state_root)
    environment["CODEX_THREAD_ID"] = session_id
    return subprocess.run(
        [sys.executable, str(RUNTIME_CLI_PATH)],
        input=json.dumps({"schema_version": SCHEMA_VERSION, **request}),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


class WorkflowCliTests(unittest.TestCase):
    def test_write_defaults_to_chinese_and_accepts_explicit_english(self):
        self._start_stage()
        for language, heading in ((None, "## 已澄清的需求"), ("en", "## Clarified Requirements")):
            with self.subTest(language=language):
                request = {
                    "schema_version": SCHEMA_VERSION, "operation": "requirements.write",
                    "cwd": str(self.repository), "title": "登录策略",
                    "clarified_requirements": "仅管理员可以撤销会话。",
                }
                if language is not None:
                    request["document_language"] = language
                result = run_cli(self.state, request, "session-1")
                self.assertEqual(result.returncode, 0, result.stdout)
                reference = json.loads(result.stdout)["reference"]
                content = (self.repository / reference["path"]).read_text()
                self.assertIn(heading, content)
                self.assertIn("仅管理员可以撤销会话。", content)
        for language in (None, [], "unsupported"):
            request["document_language"] = language
            result = run_cli(self.state, request, "session-1")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state = Path(self.temporary.name) / "state"
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "DevKit Test")
        self.git("config", "user.email", "devkit@example.test")
        (self.repository / "seed.txt").write_text("seed\n", encoding="utf-8")
        self.git("add", "seed.txt")
        self.git("commit", "-m", "seed")

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments, check=True):
        return subprocess.run(
            ["git", *arguments], cwd=self.repository, check=check,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def _start_stage(
        self, *, session_id="session-1", stage="clarify", state=None
    ):
        ExecutionTraceStore((state or self.state) / "execution-traces").append(
            session_id=session_id,
            event_type="workflow.stage.started",
            actor="runtime", source="devkit_runtime", stage=stage,
            correlation={"stage_run_id": f"{stage}-run"},
            payload={
                "stage": stage,
                "repository": repository_digest(str(self.repository)),
            },
            context={"cwd": str(self.repository)},
        )

    def _approve(self, reference, *, session_id="approval-session"):
        store = ExecutionTraceStore(self.state / "execution-traces")
        run_id = f"clarify-{session_id}"
        approval_id = f"approval-{session_id}"
        subject_digest = reference.subject_digest()
        common = {
            "session_id": session_id,
            "stage": "clarify",
            "context": {"cwd": str(self.repository)},
        }
        store.append(
            **common,
            event_type="workflow.stage.started",
            actor="runtime",
            source="devkit_runtime",
            correlation={"stage_run_id": run_id},
            payload={
                "stage": "clarify",
                "repository": repository_digest(str(self.repository)),
            },
        )
        store.append(
            **common,
            event_type="turn.prompt_submitted",
            actor="user",
            source="codex_hook",
            correlation={"turn_id": "request-turn"},
            payload={},
        )
        store.append(
            **common,
            event_type="approval.requested",
            actor="runtime",
            source="devkit_runtime",
            correlation={"stage_run_id": run_id, "turn_id": "request-turn"},
            payload={
                "approval_id": approval_id,
                "approval_kind": "clarify.requirements",
                "subject_kind": "requirement_document",
                "subject_digest": subject_digest,
            },
        )
        store.append(
            **common,
            event_type="turn.prompt_submitted",
            actor="user",
            source="codex_hook",
            correlation={"turn_id": "approval-turn"},
            payload={},
        )
        store.append(
            **common,
            event_type="approval.resolved",
            actor="runtime",
            source="devkit_runtime",
            correlation={"stage_run_id": run_id, "turn_id": "approval-turn"},
            payload={
                "approval_id": approval_id,
                "approval_kind": "clarify.requirements",
                "subject_kind": "requirement_document",
                "subject_digest": subject_digest,
                "decision": "approved",
            },
        )
        store.append(
            **common,
            event_type="workflow.stage.completed",
            actor="runtime",
            source="devkit_runtime",
            correlation={"stage_run_id": run_id, "turn_id": "approval-turn"},
            payload={
                "stage": "clarify",
                "approval_id": approval_id,
                "subject_kind": "requirement_document",
                "subject_digest": subject_digest,
            },
        )

    def _request(self, operation):
        common = {
            "schema_version": SCHEMA_VERSION,
            "operation": operation,
            "cwd": str(self.repository),
        }
        if operation == "requirements.write":
            return {
                **common,
                "title": "Login Policy",
                "clarified_requirements": "Only administrators may revoke sessions.",
            }
        return {
            **common,
            "purpose": "design",
            "reference": {
                "path": "docs/superpowers/requirements/2026-08-27-login-requirements.md",
                "commit": "a" * 40,
                "blob_digest": "git-sha1:" + "b" * 40,
            },
        }

    def _assert_contract_rejection(self, request, *, session_id="session-1"):
        before = self.git("rev-parse", "HEAD").stdout
        result = run_cli(self.state, request, session_id=session_id)
        self.assertNotEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertEqual(response["kind"], "runtime_error")
        self.assertEqual(response["code"], "rejected.contract")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)
        self.assertFalse((self.repository / "docs/superpowers/requirements").exists())

    def test_operations_reject_malformed_required_core_fields(self):
        invalid = []
        for operation in ("requirements.write", "requirements.load"):
            valid = self._request(operation)
            for field in valid:
                missing = dict(valid)
                missing.pop(field)
                invalid.append(missing)
                for replacement in (None, [], ""):
                    malformed = dict(valid)
                    malformed[field] = replacement
                    invalid.append(malformed)
        write = self._request("requirements.write")
        load = self._request("requirements.load")
        invalid.extend((
            {**write, "cwd": "relative/repository"},
            {**write, "session_id": []},
            {**write, "sources": {}},
            {**write, "sources": [{}] * 65},
            {**write, "supersedes": []},
            {**load, "reference": []},
            {**load, "purpose": "unknown"},
        ))
        for request in invalid:
            with self.subTest(request=request):
                self._assert_contract_rejection(request)

    def test_write_uses_host_session_and_commits_sources(self):
        self._start_stage()
        request = self._request("requirements.write")
        request["sources"] = [{
            "kind": "external",
            "locator": "https://example.test/policy",
            "version": "v2",
            "supports": "Supports the required revocation policy.",
        }]
        result = run_cli(self.state, request, session_id="session-1")
        self.assertEqual(result.returncode, 0, result.stdout)
        response = json.loads(result.stdout)
        self.assertEqual(response["kind"], "requirement_document")
        self.assertRegex(response["reference"]["commit"], r"^[0-9a-f]{40}$")
        self.assertIn(
            "https://example.test/policy",
            (self.repository / response["reference"]["path"]).read_text(),
        )

    def test_runtime_approved_reference_loads_through_artifact_boundary(self):
        session_id = "session-runtime-artifact"
        routed = run_runtime_cli(self.state, {
            "operation": "workflow.route", "cwd": str(self.repository),
            "intent": "development", "workflow_tier": "strict",
            "route": "development", "change_kind": "feature",
        }, session_id)
        self.assertEqual(routed.returncode, 0, routed.stdout)
        started = json.loads(run_runtime_cli(self.state, {
            "operation": "stage.start", "stage": "clarify",
            "cwd": str(self.repository),
        }, session_id).stdout)
        written = run_cli(
            self.state, self._request("requirements.write"), session_id=session_id
        )
        self.assertEqual(written.returncode, 0, written.stdout)
        reference = json.loads(written.stdout)["reference"]
        store = ExecutionTraceStore(self.state / "execution-traces")
        store.append(
            session_id=session_id, event_type="turn.prompt_submitted",
            actor="user", source="codex_hook", stage="clarify",
            correlation={"turn_id": "request-turn"}, payload={},
            context={"cwd": str(self.repository)},
        )
        requested = json.loads(run_runtime_cli(self.state, {
            "operation": "approval.request", "stage": "clarify",
            "stage_run_id": started["stage_run_id"],
            "approval_kind": "clarify.requirements", "subject": reference,
            "cwd": str(self.repository),
        }, session_id).stdout)
        store.append(
            session_id=session_id, event_type="turn.prompt_submitted",
            actor="user", source="codex_hook", stage="clarify",
            correlation={"turn_id": "approval-turn"}, payload={},
            context={"cwd": str(self.repository)},
        )
        resolved = run_runtime_cli(self.state, {
            "operation": "approval.resolve", "approval_id": requested["approval_id"],
            "decision": "approved", "cwd": str(self.repository),
        }, session_id)
        self.assertEqual(resolved.returncode, 0, resolved.stdout)
        completed = run_runtime_cli(self.state, {
            "operation": "stage.complete", "stage": "clarify",
            "stage_run_id": started["stage_run_id"], "subject": reference,
            "cwd": str(self.repository),
        }, session_id)
        self.assertEqual(completed.returncode, 0, completed.stdout)
        loaded = run_cli(self.state, {
            "schema_version": SCHEMA_VERSION, "operation": "requirements.load",
            "cwd": str(self.repository), "reference": reference, "purpose": "design",
        }, session_id=session_id)
        self.assertEqual(loaded.returncode, 0, loaded.stdout)
        self.assertIn("Only administrators may revoke sessions.",
                      json.loads(loaded.stdout)["markdown"])

    def test_old_operations_and_session_spoof_are_rejected(self):
        for operation in (
            "clarification.checkpoint", "clarification.approval.request",
            "clarification.finalize", "clarification.load",
        ):
            with self.subTest(operation=operation):
                self._assert_contract_rejection({
                    "schema_version": SCHEMA_VERSION,
                    "operation": operation,
                    "cwd": str(self.repository),
                })
        self._start_stage()
        self._assert_contract_rejection(
            {**self._request("requirements.write"), "session_id": "another-session"}
        )

    def _seed_terminal_stage(self, *, session_id, stage, terminal_event):
        store = ExecutionTraceStore(self.state / "execution-traces")
        run_id = f"{stage}-{terminal_event.rsplit('.', 1)[-1]}"
        common = {
            "session_id": session_id,
            "actor": "runtime",
            "source": "devkit_runtime",
            "stage": stage,
            "correlation": {"stage_run_id": run_id},
            "context": {"cwd": str(self.repository)},
        }
        store.append(
            **common,
            event_type="workflow.stage.started",
            payload={
                "stage": stage,
                "repository": repository_digest(str(self.repository)),
            },
        )
        store.append(
            **common,
            event_type=terminal_event,
            payload={"stage": stage},
        )

    def test_terminal_stage_never_authorizes_artifact_operation(self):
        reference = {
            "path": "docs/superpowers/requirements/2026-08-27-login-requirements.md",
            "commit": "a" * 40,
            "blob_digest": "git-sha1:" + "b" * 40,
        }
        cases = (
            ("clarify", {
                "operation": "requirements.write",
                "title": "Login Policy",
                "clarified_requirements": "Administrators revoke sessions.",
            }),
            ("clarify", {
                "operation": "requirements.load",
                "purpose": "clarify_revision",
                "reference": reference,
            }),
            ("sync-docs", {
                "operation": "requirements.load",
                "purpose": "docs_promotion",
                "reference": reference,
            }),
        )
        original_head = self.git("rev-parse", "HEAD").stdout
        for terminal_event in (
            "workflow.stage.completed",
            "workflow.stage.failed",
            "workflow.stage.skipped",
        ):
            for ordinal, (stage, request) in enumerate(cases):
                with self.subTest(terminal=terminal_event, stage=stage, request=request):
                    session_id = f"session-{terminal_event}-{ordinal}"
                    self._seed_terminal_stage(
                        session_id=session_id,
                        stage=stage,
                        terminal_event=terminal_event,
                    )
                    result = run_cli(
                        self.state,
                        {
                            "schema_version": SCHEMA_VERSION,
                            "cwd": str(self.repository),
                            **request,
                        },
                        session_id=session_id,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, original_head)
        self.assertFalse((self.repository / "docs/superpowers/requirements").exists())

    def test_active_stage_rejects_remapped_session_and_inconsistent_summary(self):
        for mutation in ("remapped-session", "inconsistent-summary"):
            with self.subTest(mutation=mutation):
                state = self.state / mutation
                store = ExecutionTraceStore(state / "execution-traces")
                if mutation == "remapped-session":
                    self._start_stage(session_id="foreign-session", state=state)
                    foreign_trace = store.trace_id_for_session("foreign-session")
                    session_path = (
                        state
                        / "execution-traces"
                        / ".sessions"
                        / (hashlib.sha256(b"host-session").hexdigest() + ".json")
                    )
                    session_path.write_text(
                        json.dumps(
                            {
                                "session_id": "host-session",
                                "trace_id": foreign_trace,
                            }
                        ),
                        encoding="utf-8",
                    )
                else:
                    self._start_stage(session_id="host-session", state=state)
                    trace_id = store.trace_id_for_session("host-session")
                    summary_path = (
                        state / "execution-traces" / trace_id / "summary.json"
                    )
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    summary["task_result"] = "passed"
                    summary_path.write_text(json.dumps(summary), encoding="utf-8")

                result = run_cli(
                    state,
                    self._request("requirements.write"),
                    session_id="host-session",
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
                self.assertFalse(
                    (self.repository / "docs/superpowers/requirements").exists()
                )

    def test_load_purposes_return_exact_approved_markdown_and_gate_source_drift(self):
        source_revision = self.git("rev-parse", "HEAD").stdout.decode().strip()
        source = RequirementSource(
            "repository",
            "seed.txt",
            source_revision,
            "Supports the existing repository behavior.",
        )
        reference = RequirementDocumentWriter().write_and_commit(
            repository_root=self.repository,
            title="Login Policy",
            clarified_requirements="Only administrators may revoke sessions.",
            sources=(source,),
        )
        expected_markdown = (self.repository / reference.path).read_text(
            encoding="utf-8"
        )
        expected_response = {
            "schema_version": SCHEMA_VERSION,
            "kind": "approved_requirement_document",
            "reference": reference.to_dict(),
            "markdown": expected_markdown,
        }
        self._approve(reference)

        design = run_cli(
            self.state,
            {
                "schema_version": SCHEMA_VERSION,
                "operation": "requirements.load",
                "cwd": str(self.repository),
                "purpose": "design",
                "reference": reference.to_dict(),
            },
            session_id="design-session",
        )
        self.assertEqual(design.returncode, 0, design.stdout)
        self.assertEqual(json.loads(design.stdout), expected_response)

        self._start_stage(session_id="docs-session", stage="sync-docs")
        docs_request = {
            "schema_version": SCHEMA_VERSION,
            "operation": "requirements.load",
            "cwd": str(self.repository),
            "purpose": "docs_promotion",
            "reference": reference.to_dict(),
        }
        docs = run_cli(self.state, docs_request, session_id="docs-session")
        self.assertEqual(docs.returncode, 0, docs.stdout)
        self.assertEqual(json.loads(docs.stdout), expected_response)

        (self.repository / "seed.txt").write_text("source drift\n", encoding="utf-8")
        self._start_stage(session_id="revision-session")
        revision = run_cli(
            self.state,
            {
                "schema_version": SCHEMA_VERSION,
                "operation": "requirements.load",
                "cwd": str(self.repository),
                "purpose": "clarify_revision",
                "reference": reference.to_dict(),
            },
            session_id="revision-session",
        )
        self.assertEqual(revision.returncode, 0, revision.stdout)
        self.assertEqual(json.loads(revision.stdout), expected_response)

        for request, session_id in (
            (
                {
                    **self._request("requirements.load"),
                    "reference": reference.to_dict(),
                },
                "design-session",
            ),
            (docs_request, "docs-session"),
        ):
            with self.subTest(purpose=request["purpose"]):
                rejected = run_cli(self.state, request, session_id=session_id)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(
                    json.loads(rejected.stdout)["code"], "requirements.source_drift"
                )


if __name__ == "__main__":
    unittest.main()
