import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/ai-native-devkit/skills/sop-init"
ASSETS = SKILL / "assets"
MANIFEST = ASSETS / "managed-docs.json"
CHECKER = SKILL / "scripts/check_managed_docs.py"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ManagedDocsTest(unittest.TestCase):
    def test_manifest_versions_match_bundled_sources(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(len(data["documents"]), 4)
        for target, entry in data["documents"].items():
            self.assertTrue(target.startswith("docs/runbooks/"))
            current = entry["currentVersion"]
            expected = entry["versions"][current]
            source = ASSETS / entry["source"]
            actual = "sha256:" + sha256(source.read_bytes()).hexdigest()
            self.assertEqual(actual, expected)

    def test_checker_distinguishes_current_and_locally_modified_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            shutil.copytree(ASSETS / "docs-template", project / "docs")

            result = subprocess.run(
                ["python3", str(CHECKER), str(project)],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                {item["status"] for item in payload["documents"]},
                {"CURRENT"},
            )

            target = project / "docs/runbooks/apollo-config.md"
            target.write_text(
                target.read_text(encoding="utf-8") + "\n本地修改。\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["python3", str(CHECKER), str(project)],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            statuses = {item["path"]: item["status"] for item in payload["documents"]}
            self.assertEqual(statuses["docs/runbooks/apollo-config.md"], "LOCAL_MODIFIED")

    def test_checker_does_not_read_through_a_runbooks_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            docs = project / "docs"
            handoff = docs / "handoff"
            handoff.mkdir(parents=True)
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
            for target in data["documents"]:
                (handoff / Path(target).name).write_bytes(b"\xff")
            (docs / "runbooks").symlink_to("handoff", target_is_directory=True)

            result = subprocess.run(
                ["python3", str(CHECKER), str(project)],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                {item["status"] for item in payload["documents"]},
                {"LOCAL_MODIFIED"},
            )
            self.assertEqual(
                {item["localHash"] for item in payload["documents"]},
                {None},
            )

    def test_checker_rejects_a_runbooks_symlink_outside_the_project(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external:
            project = Path(tmp)
            docs = project / "docs"
            docs.mkdir()
            outside = Path(external)
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
            for target in data["documents"]:
                (outside / Path(target).name).write_bytes(b"\xff")
            (docs / "runbooks").symlink_to(outside, target_is_directory=True)

            result = subprocess.run(
                ["python3", str(CHECKER), str(project)],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                {item["status"] for item in payload["documents"]},
                {"LOCAL_MODIFIED"},
            )
            self.assertEqual(
                {item["localHash"] for item in payload["documents"]},
                {None},
            )

    def test_classifier_recognizes_an_untouched_prior_version(self):
        checker = load_module(CHECKER)
        old = b"old managed content\n"
        entry = {
            "currentVersion": "2",
            "versions": {
                "1": "sha256:" + sha256(old).hexdigest(),
                "2": "sha256:" + sha256(b"new managed content\n").hexdigest(),
            },
        }
        self.assertEqual(
            checker.classify_hash("sha256:" + sha256(old).hexdigest(), entry),
            ("OUTDATED_UNMODIFIED", "1"),
        )


if __name__ == "__main__":
    unittest.main()
