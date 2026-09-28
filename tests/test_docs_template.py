import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/ai-native-devkit/skills/sop-init"
PREFLIGHT = SKILL / "scripts/preflight_docs_scan.py"
REQUIRED = {"overview", "references", "decisions", "design", "api", "runbooks", "pitfalls", "superpowers"}
FIXED_OVERVIEW = {
    "product.md",
    "domain-model.md",
    "architecture.md",
    "technical-stack.md",
    "implementation-status.md",
}
MANAGED_RUNBOOKS = {
    "rds-schema-change.md",
    "rds-data-query.md",
    "apollo-config.md",
    "kms-secret.md",
}


def copy_canonical_project(project: Path) -> None:
    shutil.copytree(SKILL / "assets/docs-template", project / "docs")
    shutil.copy2(SKILL / "assets/AGENTS.md", project / "AGENTS.md")


class DocsTemplateTest(unittest.TestCase):
    def test_superpowers_template_classifies_all_workflow_record_directories(self):
        template = (
            SKILL / "assets/docs-template/superpowers/README.md"
        ).read_text(encoding="utf-8")
        fixture = (
            ROOT / "tests/fixtures/standard-project/docs/superpowers/README.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(template, fixture)
        for text in (template, fixture):
            for directory in ("requirements/", "specs/", "plans/"):
                self.assertIn(directory, text)
            self.assertIn("版本化工作记录", text)
            self.assertIn("不是 CurrentState", text)

    def test_decision_template_uses_exact_requirement_git_provenance(self):
        template = (
            SKILL / "assets/docs-template/decisions/README.md"
        ).read_text(encoding="utf-8")
        fixture = (
            ROOT / "tests/fixtures/standard-project/docs/decisions/README.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(template, fixture)
        for field in (
            "source_requirement_path",
            "source_requirement_commit",
            "source_requirement_blob_digest",
        ):
            self.assertIn(field, template)
        for legacy in (
            "source_task_id",
            "source_artifact_id",
            "clarification_result",
        ):
            self.assertNotIn(legacy, template)

    def test_agents_template_routes_workflow_records_without_promoting_state(self):
        agents = (SKILL / "assets/AGENTS.md").read_text(encoding="utf-8")
        for directory in ("requirements", "specs", "plans"):
            self.assertIn(directory, agents)
        for field in (
            "source_requirement_path",
            "source_requirement_commit",
            "source_requirement_blob_digest",
        ):
            self.assertIn(field, agents)
        self.assertIn("不得把", agents)
        self.assertIn("CurrentState", agents)

    def test_init_excludes_workflow_records_even_when_preflight_reports_them_safe(self):
        sentinel = "HISTORICAL_REQUIREMENT_MUST_NOT_BECOME_CURRENT"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            requirement = (
                project
                / "docs/superpowers/requirements/2026-08-27-old-requirements.md"
            )
            requirement.parent.mkdir()
            requirement.write_text(sentinel, encoding="utf-8")
            result = subprocess.run(
                ["python3", str(PREFLIGHT), project], text=True, capture_output=True,
            )
            self.assertIn(
                str(requirement.relative_to(project)),
                json.loads(result.stdout)["safePaths"],
            )
            for path in (
                SKILL / "SKILL.md",
                SKILL / "references/init-contract.md",
            ):
                contract = " ".join(path.read_text(encoding="utf-8").split())
                for directory in ("requirements/", "specs/", "plans/"):
                    self.assertIn(directory, contract)
                self.assertIn("exclude from semantic inventory", contract)
                self.assertIn("do not open", contract)
                self.assertIn("deterministic index/link preservation", contract)
            self.assertEqual(requirement.read_text(encoding="utf-8"), sentinel)

    def test_validator_prunes_workflow_records_without_opening_them(self):
        records = {
            "requirements/2026-08-27-private-requirements.md": b"\xffprivate\n",
            "specs/2026-08-27-old-design.md": b"# Old\n[missing](gone.md)\n",
            "plans/2026-08-27-old-plan.md": b"# Old plan\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            superpowers = project / "docs/superpowers"
            for relative, content in records.items():
                path = superpowers / relative
                path.parent.mkdir()
                path.write_bytes(content)

            validator = SKILL / "scripts/validate_project_docs.py"
            result = subprocess.run(
                ["python3", str(validator), project],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(set(payload), {"valid", "missing", "brokenLinks"})
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["missing"], [])
            self.assertEqual(payload["brokenLinks"], [])
            self.assertEqual(
                {
                    relative: (superpowers / relative).read_bytes()
                    for relative in records
                },
                records,
            )

            index = superpowers / "README.md"
            index.write_text(
                index.read_text(encoding="utf-8").replace(
                    "# 版本化工作记录", "# Broken workflow index"
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["python3", str(validator), project],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(set(payload), {"valid", "missing", "brokenLinks"})
            self.assertIn(
                "contract marker missing: docs/superpowers/README.md -> "
                "# 版本化工作记录",
                payload["brokenLinks"],
            )

    def test_current_design_default_routes_directly_to_child_indexes(self):
        design = (ROOT / "docs/context-and-docs.md").read_text(encoding="utf-8")
        structure = design.split("## Recommended project-doc structure", 1)[1].split(
            "## Source roles", 1
        )[0]
        self.assertNotIn("README.md                 # docs entry", structure)
        self.assertIn("overview/", structure)

    def test_preflight_accepts_canonical_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)

            result = subprocess.run(
                ["python3", str(PREFLIGHT), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(payload["safeToInspect"])
            self.assertEqual(payload["unsafeAliases"], [])
            self.assertIn("AGENTS.md", payload["safePaths"])
            self.assertNotIn("docs/README.md", payload["safePaths"])

    def test_preflight_skips_non_runbooks_alias_into_handoff_without_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            handoff = project / "docs/handoff"
            handoff.mkdir()
            (handoff / "private.md").write_bytes(b"\xff")
            shutil.rmtree(project / "docs/references")
            (project / "docs/references").symlink_to(
                "handoff", target_is_directory=True
            )

            result = subprocess.run(
                ["python3", str(PREFLIGHT), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(payload["safeToInspect"])
            self.assertNotIn("handoffDetected", payload)
            self.assertNotIn("handoffMigrationSuggested", payload)
            self.assertEqual(payload["unsafeAliases"], ["docs/references"])
            self.assertNotIn("docs/references/private.md", payload["safePaths"])

    def test_template_has_required_entries_and_no_handoff_child(self):
        template = SKILL / "assets/docs-template"
        actual = {p.name for p in template.iterdir() if p.is_dir()}
        self.assertEqual(actual, REQUIRED)
        self.assertFalse((template / "README.md").exists())
        self.assertFalse((template / "handoff").exists())
        for name in REQUIRED:
            self.assertTrue((template / name / "README.md").is_file())

    def test_template_matches_approved_chinese_contract(self):
        template = SKILL / "assets/docs-template"
        agents = (SKILL / "assets/AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("# 项目协作规则", agents)
        self.assertIn("### docs 目录索引", agents)
        self.assertIn("### 文档更新规则", agents)
        self.assertNotIn("docs/handoff", agents)
        self.assertFalse((template / "README.md").exists())

        index_headings = {
            "overview": "## 文件索引",
            "references": "## 文件索引",
            "decisions": "## 决策索引",
            "design": "## 文件索引",
            "api": "## 文件索引",
            "runbooks": "## 文件索引",
            "pitfalls": "## 文件索引",
            "superpowers": "## 目录索引",
        }
        template_headings = {
            "overview": "## 文档结构",
            "references": "## 文档模板",
            "decisions": "## ADR 模板",
            "design": "## 文档模板",
            "api": "## 文档模板",
            "runbooks": "## 文档模板",
            "pitfalls": "## 问题模板",
            "superpowers": "## 文档模板",
        }
        for name in REQUIRED:
            text = (template / name / "README.md").read_text(encoding="utf-8")
            self.assertIn(index_headings[name], text)
            self.assertIn("## 维护规则", text)
            self.assertIn(template_headings[name], text)

    def test_template_bundles_fixed_overview_documents(self):
        overview = SKILL / "assets/docs-template/overview"
        actual = {path.name for path in overview.glob("*.md") if path.name != "README.md"}
        self.assertEqual(actual, FIXED_OVERVIEW)
        index = (overview / "README.md").read_text(encoding="utf-8")
        for filename in FIXED_OVERVIEW:
            self.assertIn(f"./{filename}", index)

    def test_template_bundles_managed_platform_runbooks(self):
        runbooks = SKILL / "assets/docs-template/runbooks"
        actual = {path.name for path in runbooks.glob("*.md") if path.name != "README.md"}
        self.assertTrue(MANAGED_RUNBOOKS.issubset(actual))
        index = (runbooks / "README.md").read_text(encoding="utf-8")
        self.assertIn("|---|---|---|", index)
        self.assertNotIn("|---|---|---|---|", index)
        for filename in MANAGED_RUNBOOKS:
            self.assertIn(f"./{filename}", index)

    def test_validator_rejects_blank_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), tmp],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(payload["valid"])
            self.assertNotIn("docs/README.md", payload["missing"])
            self.assertIn("docs/overview/README.md", payload["missing"])

    def test_validator_usage_preserves_public_output_shape(self):
        result = subprocess.run(
            ["python3", str(SKILL / "scripts/validate_project_docs.py")],
            text=True, capture_output=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(set(payload), {"valid", "missing", "brokenLinks"})

    def test_validator_accepts_canonical_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(payload["valid"])
            self.assertEqual(set(payload), {"valid", "missing", "brokenLinks"})
            self.assertEqual(payload["brokenLinks"], [])

    def test_validator_preserves_an_optional_existing_docs_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            readme = project / "docs/README.md"
            readme.write_text(
                "# Existing project-specific docs governance\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(payload["valid"])

    def test_validator_rejects_missing_fixed_overview_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            required = project / "docs/overview/product.md"
            if not required.exists():
                required.write_text("# 项目目标\n", encoding="utf-8")
            required.unlink()

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn("docs/overview/product.md", payload["missing"])

    def test_validator_rejects_missing_managed_runbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            required = project / "docs/runbooks/apollo-config.md"
            if not required.exists():
                required.write_text("# Apollo 配置管理和接入\n", encoding="utf-8")
            required.unlink()

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn("docs/runbooks/apollo-config.md", payload["missing"])

    def test_validator_rejects_empty_fixed_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            (project / "docs/overview/product.md").write_text("", encoding="utf-8")

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "empty fixed document: docs/overview/product.md",
                payload["brokenLinks"],
            )

    def test_validator_rejects_aliased_fixed_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            product = project / "docs/overview/product.md"
            product.unlink()
            product.symlink_to("domain-model.md")

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "fixed document must be a regular file: docs/overview/product.md",
                payload["brokenLinks"],
            )

    def test_validator_rejects_missing_project_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            (project / "AGENTS.md").unlink()

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn("AGENTS.md or CLAUDE.md", payload["missing"])

    def test_validator_rejects_nonstandard_overview_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            extra = project / "docs/overview/project-overview.md"
            extra.write_text("# Project Overview\n", encoding="utf-8")
            index = project / "docs/overview/README.md"
            index.write_text(
                index.read_text(encoding="utf-8")
                + "\n- [Project Overview](./project-overview.md)\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "nonstandard overview document: docs/overview/project-overview.md",
                payload["brokenLinks"],
            )

    def test_validator_rejects_nested_overview_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            extra = project / "docs/overview/extra/project-overview.md"
            extra.parent.mkdir()
            extra.write_text("# Project Overview\n", encoding="utf-8")
            index = project / "docs/overview/README.md"
            index.write_text(
                index.read_text(encoding="utf-8")
                + "\n- [Project Overview](./extra/project-overview.md)\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "nonstandard overview document: docs/overview/extra/project-overview.md",
                payload["brokenLinks"],
            )

    def test_validator_rejects_non_chinese_contract_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            entry = project / "AGENTS.md"
            entry.write_text(
                entry.read_text(encoding="utf-8").replace("# 项目协作规则", "# Project Rules"),
                encoding="utf-8",
            )

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "contract marker missing: AGENTS.md -> # 项目协作规则",
                payload["brokenLinks"],
            )

    def test_validator_rejects_unindexed_document_until_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            document = project / "docs/design/unindexed.md"
            document.write_text("# Unindexed\n", encoding="utf-8")

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(payload["valid"])
            self.assertIn(
                "unindexed: docs/design/unindexed.md",
                payload["brokenLinks"],
            )

            index = project / "docs/design/README.md"
            index.write_text(
                index.read_text(encoding="utf-8")
                + "\n- [Unindexed](./unindexed.md#unindexed)\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["brokenLinks"], [])

    def test_validator_ignores_legacy_handoff_subtree(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            handoff = project / "docs/handoff"
            handoff.mkdir()
            private = handoff / "private.md"
            private.write_bytes(b"\xff")
            index = project / "docs/design/README.md"
            index.write_text(
                index.read_text(encoding="utf-8")
                + "\n[Legacy private map](../handoff/private.md)\n",
                encoding="utf-8",
            )
            (project / "docs/overview/legacy-link.md").symlink_to(private)

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["brokenLinks"], [])

    def test_handoff_symlink_cannot_disable_docs_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            (project / "docs/handoff").symlink_to(".", target_is_directory=True)
            (project / "docs/overview/unindexed.md").write_text(
                "# Must remain visible to validation\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn(
                "unindexed: docs/overview/unindexed.md",
                payload["brokenLinks"],
            )

    def test_symlinked_handoff_alias_is_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            legacy = project / "legacy-handoff"
            legacy.mkdir()
            (legacy / "private.md").write_bytes(b"\xff")
            (project / "docs/handoff").symlink_to(legacy, target_is_directory=True)
            (project / "docs/overview/legacy-link.md").symlink_to(
                "../handoff/private.md"
            )

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["brokenLinks"], [])

    def test_symlinked_parent_alias_into_handoff_is_rejected_without_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            legacy = project / "legacy-handoff"
            legacy.mkdir()
            (legacy / "README.md").write_bytes(b"\xff")
            shutil.rmtree(project / "docs/overview")
            (project / "docs/handoff").symlink_to(legacy, target_is_directory=True)
            (project / "docs/overview").symlink_to("handoff", target_is_directory=True)

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["valid"])
            self.assertIn(
                "excluded handoff alias: docs/overview/README.md",
                payload["brokenLinks"],
            )

    def test_symlinked_required_index_into_handoff_is_rejected_without_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            handoff = project / "docs/handoff"
            handoff.mkdir()
            (handoff / "README.md").write_bytes(b"\xff")
            overview_index = project / "docs/overview/README.md"
            overview_index.unlink()
            overview_index.symlink_to("../handoff/README.md")

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["valid"])
            self.assertIn(
                "excluded handoff alias: docs/overview/README.md",
                payload["brokenLinks"],
            )

    def test_symlinked_runbooks_parent_into_handoff_is_rejected_without_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            copy_canonical_project(project)
            handoff = project / "docs/handoff"
            handoff.mkdir()
            (handoff / "README.md").write_bytes(b"\xff")
            for filename in MANAGED_RUNBOOKS:
                (handoff / filename).write_bytes(b"\xff")
            shutil.rmtree(project / "docs/runbooks")
            (project / "docs/runbooks").symlink_to(
                "handoff", target_is_directory=True
            )

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(
                "excluded handoff alias: docs/runbooks/README.md",
                payload["brokenLinks"],
            )

    def test_symlinked_runbooks_parent_outside_project_is_rejected_without_reading(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external:
            project = Path(tmp)
            copy_canonical_project(project)
            outside = Path(external)
            (outside / "README.md").write_bytes(b"\xff")
            for filename in MANAGED_RUNBOOKS:
                (outside / filename).write_bytes(b"\xff")
            shutil.rmtree(project / "docs/runbooks")
            (project / "docs/runbooks").symlink_to(
                outside, target_is_directory=True
            )

            result = subprocess.run(
                ["python3", str(SKILL / "scripts/validate_project_docs.py"), project],
                text=True, capture_output=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(
                "unsafe symlink component: docs/runbooks/README.md",
                payload["brokenLinks"],
            )


if __name__ == "__main__":
    unittest.main()
