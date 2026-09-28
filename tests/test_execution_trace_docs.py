import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExecutionTraceDocsTests(unittest.TestCase):
    def test_current_docs_describe_implemented_execution_trace_and_docs_hook(self):
        contracts = (ROOT / "docs/contracts.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
        workflow = (ROOT / "docs/workflow.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "docs/roadmap-and-validation.md").read_text(encoding="utf-8")

        self.assertIn("## Execution Trace (0.3 implemented)", contracts)
        self.assertIn("## Automatic Docs Hook result", contracts)
        self.assertIn("ExecutionTraceStore", architecture)
        self.assertIn("CollectorService", architecture)
        self.assertIn("DocsImpactHook", architecture)
        self.assertIn("Init CLI", architecture)
        self.assertIn("Automatic Execution Trace and Docs Hook", workflow)
        self.assertIn("Execution Trace Collector and Docs Hook", roadmap)
        self.assertIn("Sessions that do not use the plugin do not create a Trace", workflow)
        self.assertIn("non-plugin Sessions are not persisted", architecture)

    def test_old_evaluation_trace_is_absent_from_implemented_contracts(self):
        current = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in (
                "docs/contracts.md",
                "docs/architecture.md",
                "docs/workflow.md",
                "plugins/ai-native-devkit/skills/coding-sop/references/execution-trace.md",
            )
        )
        for removed in (
            "evaluation.start",
            "evaluation.update",
            "evaluation.finish",
            "trace_mode: development",
            "hook_should_trigger: boolean",
        ):
            self.assertNotIn(removed, current)


if __name__ == "__main__":
    unittest.main()
