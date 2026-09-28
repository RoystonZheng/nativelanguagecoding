import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER = ROOT / "plugins/ai-native-devkit/skills/sop-sync-docs/scripts/classify_changes.py"

CASES = {
    "tests/foo_test.py": (
        "NO_CHANGE",
        ["routine internal or test-only change: tests/foo_test.py"],
    ),
    "src/internal/cache.py": (
        "NO_CHANGE",
        ["routine internal or test-only change: src/internal/cache.py"],
    ),
    "api/order.proto": (
        "SEMANTIC_REVIEW",
        ["public contract or data model changed: api/order.proto"],
    ),
    "migrations/002_move_owner.sql": (
        "SEMANTIC_REVIEW",
        ["public contract or data model changed: migrations/002_move_owner.sql"],
    ),
    "docs/design/order.md": (
        "DETERMINISTIC",
        ["Agent-facing docs changed: docs/design/order.md"],
    ),
}


class ClassifyChangesTest(unittest.TestCase):
    def test_classifies_changed_paths(self):
        for changed_path, expected in CASES.items():
            with self.subTest(changed_path=changed_path), tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".txt"
            ) as changed_files:
                changed_files.write(f"{changed_path}\n")
                changed_files.flush()
                result = subprocess.run(
                    ["python3", str(CLASSIFIER), changed_files.name],
                    capture_output=True,
                    check=False,
                    text=True,
                )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(set(payload), {"docsImpact", "reasons"})
            self.assertEqual(payload["docsImpact"], expected[0])
            self.assertIsInstance(payload["reasons"], list)
            self.assertEqual(payload["reasons"], expected[1])


if __name__ == "__main__":
    unittest.main()
