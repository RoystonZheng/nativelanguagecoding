import subprocess
import sys
from pathlib import Path
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit.docs_hook import DocsImpactHook, classify_changes


def git(repository, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


class DocsImpactHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()
        git(self.repository, "init", "-b", "main")
        git(self.repository, "config", "user.name", "Test User")
        git(self.repository, "config", "user.email", "test@example.com")
        (self.repository / "README.md").write_text("# Project\n", encoding="utf-8")
        git(self.repository, "add", "README.md")
        git(self.repository, "commit", "-m", "initial")
        self.baseline = git(self.repository, "rev-parse", "HEAD")

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, path, content="changed\n"):
        target = self.repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def evaluate(self, intent, passed=True, change_kind=None):
        return DocsImpactHook().after_verification(
            repository=self.repository,
            baseline_revision=self.baseline,
            verification_passed=passed,
            intent=intent,
            change_kind=change_kind,
        )

    def test_every_passed_task_runs_docs_check_without_handoff_output(self):
        self.write("tests/test_feature.py")
        result = self.evaluate("debug")

        self.assertTrue(result["triggered"])
        report = result["report"]
        self.assertEqual(report["docsImpact"], "NO_CHANGE")
        self.assertFalse(report["requiresUserConfirmation"])
        self.assertEqual(report["appliedChanges"], [])
        self.assertNotIn("handoffSignal", report)
        self.assertNotIn("askHandoff", report)

    def test_ordinary_debug_source_change_has_no_docs_impact(self):
        self.write("src/service.py")
        report = self.evaluate("debug")["report"]

        self.assertEqual(report["docsImpact"], "NO_CHANGE")
        self.assertFalse(report["requiresUserConfirmation"])
        self.assertNotIn("handoffSignal", report)
        self.assertNotIn("askHandoff", report)

    def test_internal_refactor_development_change_has_no_docs_impact(self):
        self.write("src/service.py")
        report = self.evaluate("development", change_kind="refactor")["report"]

        self.assertEqual(report["docsImpact"], "NO_CHANGE")
        self.assertFalse(report["requiresUserConfirmation"])
        self.assertNotIn("handoffSignal", report)
        self.assertNotIn("askHandoff", report)

    def test_development_behavior_change_requires_semantic_preview(self):
        self.write("src/service.py")
        report = self.evaluate("development", change_kind="feature")["report"]

        self.assertEqual(report["docsImpact"], "SEMANTIC_REVIEW")
        self.assertTrue(report["requiresUserConfirmation"])
        self.assertEqual(report["proposedChanges"][0]["kind"], "semantic_docs_preview")
        self.assertNotIn("handoffSignal", report)
        self.assertNotIn("askHandoff", report)

    def test_public_contract_change_requires_only_semantic_docs_review(self):
        self.write("api/order.proto")
        report = self.evaluate("debug")["report"]

        self.assertEqual(report["docsImpact"], "SEMANTIC_REVIEW")
        self.assertTrue(report["requiresUserConfirmation"])
        self.assertNotIn("handoffSignal", report)
        self.assertNotIn("askHandoff", report)

    def test_failed_verification_does_not_trigger_docs_hook(self):
        self.write("api/order.proto")
        result = self.evaluate("development", passed=False)

        self.assertFalse(result["triggered"])
        self.assertEqual(result["reason"], "verification_not_passed")
        self.assertIsNone(result["report"])

    def test_classifier_rejects_oracle_fields_and_keeps_only_actual_paths(self):
        result = classify_changes(["tests/a.py", "docs/design/a.md"], intent="debug")

        self.assertEqual(set(result), {"docsImpact", "reasons", "changedPaths"})
        self.assertEqual(result["changedPaths"], ["docs/design/a.md", "tests/a.py"])
        self.assertNotIn("expected_route", result)
        self.assertNotIn("hook_should_trigger", result)


if __name__ == "__main__":
    unittest.main()
