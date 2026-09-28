from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/ai-native-devkit/scripts"))

from ai_native_devkit.instruction_comparison import compare_instructions


class InstructionComparisonTests(unittest.TestCase):
    def test_soft_wrapping_and_blank_lines_do_not_change_prose_rules(self):
        self.assertEqual(compare_instructions(
            "# Agent\nRun the tests before submitting changes.\n",
            "# Claude\nRun the tests before\n\nsubmitting changes.\n",
        ), [])

    def test_document_titles_bullets_emphasis_and_host_startup_links_are_presentation(self):
        result = compare_instructions(
            "# Codex 项目指南\n\n- 修改后运行**测试**。\n- 启动规则：[启动规则](.Codex/start-rule.md)\n",
            "# Claude 项目指南\n\n* 修改后运行测试。\n* 启动规则：[启动规则](.claude/start-rule.md)\n",
        )
        self.assertEqual(result, [])

    def test_conflicting_rules_include_original_line_numbers(self):
        result = compare_instructions(
            "# Codex\n\n## 提交\n- 修改后必须运行测试。\n",
            "# Claude\n\n## 提交\n- 修改后不要运行测试。\n",
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["left"]["line_start"], 4)
        self.assertEqual(result[0]["right"]["line_start"], 4)
        self.assertIn("必须", result[0]["left"]["excerpt"])
        self.assertIn("不要", result[0]["right"]["excerpt"])

    def test_regular_links_scoped_headings_and_commands_remain_meaningful(self):
        pairs = [
            ("# A\n使用 [规则](docs/a.md)", "# B\n使用 [规则](docs/b.md)"),
            ("# A\n## 生产\n允许部署", "# B\n## 测试\n允许部署"),
            ("# A\n```sh\nrm -rf build\n```", "# B\n```sh\nrm -rf /\n```"),
            ("# A\n必须执行检查", "# B\n不必执行检查"),
            ("# A\n启动规则：[规则](.Codex/a.md)", "# B\n启动规则：[规则](.claude/b.md)"),
            ("# 不要运行测试\n正文", "# 必须运行测试\n正文"),
            ("# A\n- Production\n  - Never deploy\n", "# B\n- Production\n- Never deploy\n"),
            ("# A\nRun `x  y`", "# B\nRun `x y`"),
            ("# A\n启动规则：[规则](..Codex/start-rule.md)", "# B\n启动规则：[规则](.claude/start-rule.md)"),
        ]
        for left, right in pairs:
            with self.subTest(left=left):
                self.assertTrue(compare_instructions(left, right))

    def test_large_excerpts_and_differences_remain_bounded(self):
        result = compare_instructions("# A\n" + "token=x " * 100, "# B\nUse defaults.")
        item = result[0]["left"]
        self.assertTrue(item["truncated"])
        self.assertLessEqual(len(item["excerpt"]), 300)
        self.assertNotIn("token=x", item["excerpt"])
        # A credential starting just before the excerpt limit must be redacted in full first.
        result = compare_instructions(
            "# A\n" + "a " * 148 + "s" + "k-" + "privatefixturevalue",
            "# B\nUse defaults.",
        )
        self.assertNotIn("sk-", result[0]["left"]["excerpt"])
        result = compare_instructions("a\n" * 2050, "b\n" * 2050)
        self.assertTrue(result[0]["comparison_limited"])


if __name__ == "__main__":
    unittest.main()
