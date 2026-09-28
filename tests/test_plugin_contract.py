import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PluginContractTest(unittest.TestCase):
    def test_marketplace_exposes_ai_native_devkit(self):
        data = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(data["name"], "ai-native-devkit")
        self.assertEqual(data["interface"]["displayName"], "AI Native DevKit")
        entry = data["plugins"][0]
        self.assertEqual(entry["name"], "ai-native-devkit")
        self.assertEqual(entry["source"]["path"], "./plugins/ai-native-devkit")
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")
        self.assertEqual(entry["category"], "Developer Tools")

    def test_manifest_has_stable_identity(self):
        path = ROOT / "plugins/ai-native-devkit/.codex-plugin/plugin.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["name"], "ai-native-devkit")
        self.assertEqual(data["version"], "0.4.1")
        self.assertEqual(data["skills"], "./skills/")

    def test_default_plugin_hook_is_packaged_without_manifest_override(self):
        plugin = ROOT / "plugins/ai-native-devkit"
        manifest = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
        self.assertNotIn("hooks", manifest)
        hooks = json.loads((plugin / "hooks/hooks.json").read_text())
        self.assertIn("SessionStart", hooks["hooks"])
        self.assertIn("SessionEnd", hooks["hooks"])
        self.assertIn("Stop", hooks["hooks"])

    def test_manifest_package_and_producer_versions_match(self):
        plugin = ROOT / "plugins/ai-native-devkit"
        manifest = json.loads(
            (plugin / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )

        def string_assignment(path, name):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                    continue
                target = node.targets[0]
                if (
                    isinstance(target, ast.Name)
                    and target.id == name
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    return node.value.value
            self.fail(f"{name} is missing from {path}")

        package = plugin / "scripts/ai_native_devkit"
        package_version = string_assignment(package / "__init__.py", "__version__")
        producer = string_assignment(package / "contracts.py", "PRODUCER")
        self.assertEqual(package_version, manifest["version"])
        self.assertEqual(
            producer,
            "ai-native-devkit/workflow-runtime@" + manifest["version"],
        )
        state_store = (package / "state_store.py").read_text(encoding="utf-8")
        self.assertIn(
            '"ai-native-devkit/task-state-store@' + manifest["version"] + '"',
            state_store,
        )


if __name__ == "__main__":
    unittest.main()
