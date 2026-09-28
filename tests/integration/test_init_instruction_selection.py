import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins/ai-native-devkit/scripts"
sys.path.insert(0, str(SCRIPTS))

from ai_native_devkit.contracts import utc_now
from ai_native_devkit.init_engine import InitEngine
from ai_native_devkit.persistence import InMemoryAtomicPersistence
from ai_native_devkit.repository import RepositoryInspector
from ai_native_devkit.state_store import TaskStateStore
from tests.modules.test_repository_inspector import create_repository


class InitInstructionSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repository = self.root / "repository"
        create_repository(self.repository)
        (self.repository / "AGENTS.md").write_text("# Codex\n\n## Verification\n- Always run tests.\n")
        (self.repository / "CLAUDE.md").write_text("# Claude\n\n## Verification\n- Never run tests.\n")
        self.environment = {**os.environ, "AI_NATIVE_DEVKIT_STATE_ROOT": str(self.root / "state")}
        self.environment.pop("CODEX_THREAD_ID", None)
        self.environment.pop("CODEX_TASK_ID", None)

    def run_init(self, **extra):
        request = {
            "schema_version": "ai-native-devkit/v1alpha1", "operation": "init",
            "task_id": "instruction-test", "repository": {"path": str(self.repository)},
            "user_request": "Fix the reported issue", **extra,
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "init_cli.py")], input=json.dumps(request),
            text=True, capture_output=True, env=self.environment,
        )
        return result.returncode, json.loads(result.stdout)

    def selection(self, report, source="AGENTS.md"):
        return {
            "report_ref": report["report_ref"], "preferred_sources": [source],
            "confirmed_at": utc_now(), "provenance": "later user turn: prefer selected source for this task",
        }

    def test_rule_differences_are_actionable_and_user_choice_resumes_without_file_edits(self):
        _, blocked = self.run_init()
        diff = blocked["report"]["payload"]["blocker"]["details"]["instruction_differences"][0]
        self.assertEqual(diff["left"]["path"], "AGENTS.md")
        self.assertEqual(diff["right"]["path"], "CLAUDE.md")
        self.assertEqual(diff["changes"][0]["left"]["line_start"], 4)
        self.assertIn("Always", diff["changes"][0]["left"]["excerpt"])
        before = {p.name: p.read_bytes() for p in self.repository.glob("*.md")}
        status, ready = self.run_init(instruction_selection={**self.selection(blocked), "extension": {"note": "preserve me"}})
        self.assertEqual(status, 0, ready)
        payload = ready["report"]["payload"]
        self.assertEqual(payload["outcome"], "ready")
        self.assertEqual(payload["instruction_selection"]["extension"], {"note": "preserve me"})
        self.assertEqual(payload["findings"]["repository_instructions"], ["AGENTS.md"])
        self.assertEqual({s["path"] for s in payload["sources"] if s["kind"] == "repository_instruction"}, {"AGENTS.md", "CLAUDE.md"})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.repository.glob("*.md")})
        _, current = self.run_init()
        self.assertEqual(current["reason"], "init.ready_current")
        _, reused = self.run_init(choice="reuse")
        self.assertEqual(reused["report_ref"], ready["report_ref"])
        _, fresh_task = self.run_init(task_id="other-task")
        self.assertEqual(fresh_task["report"]["payload"]["outcome"], "blocked")

    def test_claude_can_be_selected_instead(self):
        _, blocked = self.run_init()
        status, ready = self.run_init(instruction_selection=self.selection(blocked, "CLAUDE.md"))
        self.assertEqual(status, 0, ready)
        self.assertEqual(ready["report"]["payload"]["findings"]["repository_instructions"], ["CLAUDE.md"])

    def test_presentation_only_differences_do_not_block_init(self):
        (self.repository / "AGENTS.md").write_text("# Codex\n- 修改后运行**测试**。\n- 启动规则：[启动规则](.Codex/start-rule.md)\n")
        (self.repository / "CLAUDE.md").write_text("# Claude\n* 修改后运行测试。\n* 启动规则：[启动规则](.claude/start-rule.md)\n")
        status, response = self.run_init()
        self.assertEqual(status, 0, response)
        self.assertEqual(response["report"]["payload"]["outcome"], "ready")

    def test_changed_source_invalidates_choice_and_reports_new_rule_lines(self):
        _, blocked = self.run_init()
        choice = self.selection(blocked)
        (self.repository / "CLAUDE.md").write_text("# Claude\nNever run tests or lint.\n")
        status, changed = self.run_init(instruction_selection=choice)
        self.assertEqual(status, 0, changed)
        payload = changed["report"]["payload"]
        self.assertEqual(payload["blocker"]["code"], "blocked.repository.instruction_selection_stale")
        self.assertNotIn("instruction_selection", payload)
        self.assertIn("lint", payload["blocker"]["details"]["instruction_differences"][0]["changes"][0]["right"]["excerpt"])

    def test_stale_report_and_unreported_source_cannot_select_authority(self):
        _, blocked = self.run_init()
        self.run_init()
        status, result = self.run_init(instruction_selection=self.selection(blocked))
        self.assertEqual(status, 1)
        self.assertEqual(result["code"], "init.instruction_selection_stale")
        _, current = self.run_init()
        status, result = self.run_init(instruction_selection=self.selection(current, "sub/AGENTS.md"))
        self.assertEqual(status, 1)
        self.assertEqual(result["code"], "init.instruction_selection_not_applicable")

    def test_recorded_choice_survives_interrupted_reinspection(self):
        store = TaskStateStore(InMemoryAtomicPersistence())
        engine = InitEngine(store, RepositoryInspector())
        args = {"task_id": "interrupted-choice", "requested_path": str(self.repository), "user_request": "Fix the issue"}
        blocked = engine.run(**args)
        with patch.object(engine, "_inspect", side_effect=RuntimeError("interrupted")):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                engine.run(**args, instruction_selection=self.selection(blocked))
        ready = InitEngine(store, RepositoryInspector()).run(**args)
        self.assertEqual(ready["report"]["payload"]["outcome"], "ready")
        self.assertEqual(ready["report"]["payload"]["findings"]["repository_instructions"], ["AGENTS.md"])

    def test_rule_excerpts_are_redacted_before_persistence(self):
        (self.repository / "CLAUDE.md").write_text("# Claude\nUse token=private-fixture-value\n" + "token=x " * 100)
        _, blocked = self.run_init()
        self.assertEqual(blocked["report"]["payload"]["outcome"], "blocked")
        self.assertNotIn("private-fixture-value", json.dumps(blocked))
        self.assertNotIn("token=x", json.dumps(blocked))
        self.assertIn("[REDACTED]", json.dumps(blocked))

    def test_nested_directory_selections_can_be_resolved_incrementally(self):
        nested = self.repository / "sub"
        nested.mkdir()
        (nested / "AGENTS.md").write_text("# Sub\nRun unit tests.\n")
        (nested / "CLAUDE.md").write_text("# Sub\nRun integration tests.\n")
        request = {"repository": {"path": str(nested)}}
        _, blocked = self.run_init(**request)
        status, partial = self.run_init(**request, instruction_selection=self.selection(blocked))
        self.assertEqual(status, 0, partial)
        groups = partial["report"]["payload"]["blocker"]["details"]["instruction_differences"]
        self.assertEqual([group["directory"] for group in groups], ["sub"])
        status, ready = self.run_init(**request, instruction_selection=self.selection(partial, "sub/CLAUDE.md"))
        self.assertEqual(status, 0, ready)
        self.assertEqual(ready["report"]["payload"]["findings"]["repository_instructions"], ["AGENTS.md", "sub/CLAUDE.md"])

    def test_invalid_choices_do_not_change_private_state(self):
        _, blocked = self.run_init()
        baseline = {str(path): path.read_bytes() for path in (self.root / "state").rglob("*") if path.is_file()}
        variants = [
            {"preferred_sources": ["../AGENTS.md"]},
            {"preferred_sources": ["AGENTS.md", "CLAUDE.md"]},
            {"confirmed_at": "2000-01-01T00:00:00Z"},
            {"confirmed_at": "2999-01-01T00:00:00Z"},
            {"source_hashes": {"AGENTS.md": "sha256:" + "a" * 64}},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                status, result = self.run_init(instruction_selection={**self.selection(blocked), **variant})
                self.assertEqual(status, 1, result)
                self.assertEqual(baseline, {str(path): path.read_bytes() for path in (self.root / "state").rglob("*") if path.is_file()})
        status, result = self.run_init(task_id="new-selection-task", instruction_selection=self.selection(blocked))
        self.assertEqual(status, 1, result)
        self.assertEqual(result["code"], "init.instruction_selection_not_applicable")


if __name__ == "__main__":
    unittest.main()
