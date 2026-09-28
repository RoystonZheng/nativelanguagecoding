import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "plugins/ai-native-devkit/skills"


class DevelopmentSkillTest(unittest.TestCase):
    def test_contract_tokens(self):
        cases = {
            "sop-clarify": ["requirements.write", "one question per assistant message", "clarify.requirements", "RequirementDocRef"],
            "sop-design": ["RequirementDocRef", "2-3 different approaches", "trade-offs", "design.solution"],
            "sop-plan": [
                "approved DesignDoc", "来源设计", "设计约束",
                "验收覆盖", "ordered vertical slices", "设计依据",
                "涉及位置", "先写测试", "预期：", "完成条件",
                "最终集成验证",
            ],
        }
        for name, tokens in cases.items():
            text = (ROOT / name / "SKILL.md").read_text()
            for token in tokens:
                self.assertIn(token, text, f"{name}: {token}")

    def test_init_contract_excludes_versioned_workflow_records(self):
        for relative in ("SKILL.md", "references/init-contract.md"):
            text = " ".join((ROOT / "sop-init" / relative).read_text().split())
            for directory in ("requirements/", "specs/", "plans/"):
                self.assertIn(directory, text)
            self.assertIn("exclude from semantic inventory", text)
            self.assertIn("do not open", text)
            self.assertIn("deterministic index/link preservation", text)

    def test_plan_hands_execution_to_bundled_skill(self):
        text = (ROOT / "sop-plan/SKILL.md").read_text()
        self.assertIn("$sop-execute", text)
        self.assertNotIn("superpowers:", text)

    def test_plan_is_detailed_without_becoming_a_task_graph(self):
        text = (ROOT / "sop-plan/SKILL.md").read_text()
        for forbidden in (
            "TicketGraph", "depends_on", "cycle detection", "frontier",
            "write_scope", "risk score", "frequent git commit",
        ):
            self.assertNotIn(forbidden, text)

    def test_plan_closes_the_runtime_stage_when_design_cannot_be_translated(self):
        text = " ".join((ROOT / "sop-plan/SKILL.md").read_text().split())
        self.assertIn("stage.fail", text)
        self.assertIn("plan.design_gap", text)
        self.assertIn("does not continue to Execute", text)


if __name__ == "__main__":
    unittest.main()
