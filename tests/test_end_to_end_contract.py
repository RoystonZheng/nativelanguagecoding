import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BLANK = ROOT / "tests/fixtures/blank-project"
LEGACY = ROOT / "tests/fixtures/legacy-docs-project"
STANDARD = ROOT / "tests/fixtures/standard-project"
PLUGIN = ROOT / "plugins/ai-native-devkit"
DOCS_VALIDATOR = PLUGIN / "skills/sop-init/scripts/validate_project_docs.py"
SKILLS = PLUGIN / "skills"
EXPECTED_SKILLS = {
    "coding-sop", "diagnosing-bugs", "sop-init", "sop-clarify", "sop-design", "sop-plan",
    "sop-execute", "sop-debug", "sop-verify", "sop-sync-docs",
}
INSTALL_BLOCK = """python3 scripts/validate_all.py
codex plugin marketplace add \"$(pwd)\"
codex plugin add ai-native-devkit@ai-native-devkit"""
REMOVAL_BLOCK = "codex plugin remove ai-native-devkit@ai-native-devkit"
UPDATE_BLOCK = """python3 \"${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/read_marketplace_name.py\" --marketplace-path .agents/plugins/marketplace.json
python3 \"${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py\" plugins/ai-native-devkit
codex plugin add ai-native-devkit@ai-native-devkit"""


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def discovered_skill_names() -> set[str]:
    return {path.name for path in SKILLS.iterdir() if (path / "SKILL.md").is_file()}


def fixture_contents(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def normalized_bash_blocks(markdown: str) -> list[str]:
    return [
        re.sub(r"\\\n\s*", "", block.strip())
        for block in re.findall(r"```bash\n(.*?)\n```", markdown, re.DOTALL)
    ]


validate_docs = load_module(DOCS_VALIDATOR).validate


class EndToEndContractTest(unittest.TestCase):
    def test_evaluation_fixtures_exercise_docs_validator_without_mutation(self):
        before = {root: fixture_contents(root) for root in (BLANK, LEGACY, STANDARD)}
        self.assertFalse(validate_docs(BLANK)["valid"])
        self.assertTrue((LEGACY / "docs/handoff/README.md").is_file())
        self.assertFalse((LEGACY / "handoff").exists())
        self.assertTrue(validate_docs(STANDARD)["valid"])
        after = {root: fixture_contents(root) for root in (BLANK, LEGACY, STANDARD)}
        self.assertEqual(after, before)

    def test_all_public_skills_are_discoverable(self):
        self.assertEqual(discovered_skill_names(), EXPECTED_SKILLS)

    def test_readme_documents_installation_updates_and_public_contract(self):
        readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith("# AI Native DevKit\n"))
        bash_blocks = normalized_bash_blocks(readme)
        self.assertIn(INSTALL_BLOCK, bash_blocks)
        self.assertIn(REMOVAL_BLOCK, bash_blocks)
        self.assertIn(UPDATE_BLOCK, bash_blocks)

        required = {
            *{f"${name}" for name in EXPECTED_SKILLS},
        }
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, readme)

        for heading in (
            "## 安装",
            "## 调用方式",
            "## 开发流程与 Skill",
            "## 文档边界",
            "## 本地开发更新",
            "## 当前验证范围",
            "## 0.4.0 版本边界",
            "## Historical 0.3.0 版本边界",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, readme)
        self.assertNotIn("## Install", readme)
        self.assertNotIn("## Invocation", readme)

    def test_repository_readme_and_third_party_notices_are_publishable(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("# AI Native DevKit", readme)
        self.assertIn("`0.3.0` 新增", readme)
        self.assertIn("ai-native-devkit@ai-native-devkit", readme)
        self.assertIn("plugins/ai-native-devkit", readme)

        status_docs = {
            ROOT / "AGENTS.md": "Current 0.4.0 implements",
            ROOT / "docs/README.md": "0.4.0 implemented",
            ROOT / "docs/product-and-scope.md": "0.4.0 implemented",
            ROOT / "docs/方案总览.md": "0.4.0 implemented",
            ROOT / "docs/roadmap-and-validation.md": "0.4.0 implemented",
        }
        for path, token in status_docs.items():
            with self.subTest(status_document=path):
                self.assertIn(token, path.read_text(encoding="utf-8"))

        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for token in (
            "Superpowers",
            "Jesse Vincent",
            "https://github.com/obra/superpowers",
            "Matt Pocock",
            "https://github.com/mattpocock/skills",
            "skills/engineering/diagnosing-bugs/SKILL.md",
            "MIT License",
        ):
            with self.subTest(token=token):
                self.assertIn(token, notices)

        plugin_notices = (PLUGIN / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertEqual(plugin_notices, notices)

    def test_current_package_docs_index_implemented_requirement_contract(self):
        manifest = json.loads(
            (PLUGIN / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["version"], "0.4.1")
        adr = ROOT / "docs/decisions/0006-git-versioned-requirements-handoff.md"
        self.assertTrue(adr.is_file())
        self.assertIn("Status: Accepted", adr.read_text(encoding="utf-8"))
        decisions_index = (ROOT / "docs/decisions/README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("ADR 0006", decisions_index)
        self.assertIn("Implemented in 0.4.0", decisions_index)
        self.assertNotIn("validation pending", decisions_index)
        template = (
            PLUGIN / "skills/sop-init/assets/docs-template/superpowers/README.md"
        ).read_text(encoding="utf-8")
        self.assertIn("requirements/", template)
        notices = (PLUGIN / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for token in ("superpowers@6.3.0", "Understanding the idea"):
            self.assertIn(token, notices)
        for path in (
            ROOT / "README.md", PLUGIN / "README.md", ROOT / "docs/README.md",
        ):
            text = path.read_text(encoding="utf-8")
            normalized = " ".join(text.split())
            self.assertIn("0.4.0", normalized)
            self.assertTrue(
                "Current 0.4.0" in normalized or "0.4.0 implemented" in normalized,
                path,
            )
            self.assertNotIn("validation pending", normalized)

    def test_copied_package_requirement_flow_preserves_external_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed_root = root / "copied-plugin"
            shutil.copytree(PLUGIN, installed_root)
            self.assertTrue((installed_root / "scripts/workflow_cli.py").is_file())
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True)
            subprocess.run(
                ["git", "config", "user.name", "DevKit Test"],
                cwd=repository, check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "devkit@example.test"],
                cwd=repository, check=True,
            )
            (repository / "seed.txt").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "add", "seed.txt"], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-m", "seed"], cwd=repository, check=True)
            state = root / "external-state"
            state.mkdir()
            sentinel = state / "legacy-user-state.json"
            sentinel.write_bytes(b'{"legacy":"untouched"}\n')
            environment = os.environ.copy()
            environment.update({
                "AI_NATIVE_DEVKIT_STATE_ROOT": str(state),
                "CODEX_THREAD_ID": "clean-package-session",
            })

            def call(script, payload, *, schema=True):
                request = (
                    {"schema_version": "ai-native-devkit/v1alpha1", **payload}
                    if schema else payload
                )
                return subprocess.run(
                    [sys.executable, str(installed_root / "scripts" / script)],
                    input=json.dumps(request),
                    env=environment, text=True, capture_output=True,
                )

            routed = call("runtime_cli.py", {
                "operation": "workflow.route", "cwd": str(repository),
                "intent": "development", "workflow_tier": "strict",
                "route": "development", "change_kind": "feature",
            })
            self.assertEqual(routed.returncode, 0, routed.stdout)
            started = json.loads(call("runtime_cli.py", {
                "operation": "stage.start", "stage": "clarify",
                "cwd": str(repository),
            }).stdout)
            prompt = lambda turn: call("trace_collector.py", {
                "session_id": "clean-package-session", "cwd": str(repository),
                "hook_event_name": "UserPromptSubmit", "turn_id": turn,
                "prompt": "review", "permission_mode": "default", "model": "test",
            }, schema=False)
            self.assertEqual(prompt("turn-request").returncode, 0)
            written = json.loads(call("workflow_cli.py", {
                "operation": "requirements.write", "cwd": str(repository),
                "title": "Login Policy",
                "clarified_requirements": "Only administrators revoke sessions.",
            }).stdout)
            reference = written["reference"]
            requested = json.loads(call("runtime_cli.py", {
                "operation": "approval.request", "stage": "clarify",
                "stage_run_id": started["stage_run_id"],
                "approval_kind": "clarify.requirements", "subject": reference,
                "cwd": str(repository),
            }).stdout)
            self.assertEqual(prompt("turn-approval").returncode, 0)
            self.assertEqual(call("runtime_cli.py", {
                "operation": "approval.resolve",
                "approval_id": requested["approval_id"], "decision": "approved",
                "cwd": str(repository),
            }).returncode, 0)
            self.assertEqual(call("runtime_cli.py", {
                "operation": "stage.complete", "stage": "clarify",
                "stage_run_id": started["stage_run_id"], "subject": reference,
                "cwd": str(repository),
            }).returncode, 0)
            loaded = call("workflow_cli.py", {
                "operation": "requirements.load", "purpose": "design",
                "reference": reference, "cwd": str(repository),
            })
            self.assertEqual(loaded.returncode, 0, loaded.stdout)
            self.assertIn(
                "Only administrators revoke sessions.",
                json.loads(loaded.stdout)["markdown"],
            )
            self.assertEqual(sentinel.read_bytes(), b'{"legacy":"untouched"}\n')


if __name__ == "__main__":
    unittest.main()
