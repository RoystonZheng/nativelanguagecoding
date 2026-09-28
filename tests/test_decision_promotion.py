import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = (
    ROOT
    / "plugins/ai-native-devkit/skills/sop-sync-docs/scripts/validate_promoted_decision.py"
)


def load_validator():
    spec = importlib.util.spec_from_file_location("decision_validator", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.validate


validate = load_validator()


def decision_frontmatter(
    *,
    algorithm="sha1",
    state_class="RequestedState",
    implementation_status="not_implemented",
):
    width = 40 if algorithm == "sha1" else 64
    return f"""---
status: accepted
state_class: {state_class}
implementation_status: {implementation_status}
source_requirement_path: docs/superpowers/requirements/2026-08-27-login-requirements.md
source_requirement_commit: {'a' * width}
source_requirement_blob_digest: git-{algorithm}:{'b' * width}
---

# 0042. Persist Approved Login Policy

## Decision

Use the approved login policy.
"""


class DecisionPromotionTest(unittest.TestCase):
    def test_sha1_and_sha256_requirement_provenance_are_valid(self):
        for algorithm in ("sha1", "sha256"):
            with self.subTest(algorithm=algorithm), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "0042-login-policy.md"
                path.write_text(
                    decision_frontmatter(algorithm=algorithm), encoding="utf-8"
                )
                self.assertEqual(validate(path), {"valid": True, "errors": []})

    def test_inexact_or_legacy_requirement_provenance_is_rejected(self):
        valid = decision_frontmatter()
        invalid = (
            valid.replace(
                "docs/superpowers/requirements/2026-08-27-login-requirements.md",
                "../outside.md",
            ),
            valid.replace(
                "source_requirement_commit: " + "a" * 40,
                "source_requirement_commit: " + "a" * 12,
            ),
            valid.replace("git-sha1:" + "b" * 40, "git-sha256:" + "b" * 64),
            valid.replace("source_requirement_commit: " + "a" * 40 + "\n", ""),
            valid.replace(
                "source_requirement_path:",
                "source_task_id: workflow-task-42\nsource_requirement_path:",
            ),
        )
        for ordinal, content in enumerate(invalid):
            with self.subTest(case=ordinal), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "0042-login-policy.md"
                path.write_text(content, encoding="utf-8")
                self.assertFalse(validate(path)["valid"])

    def test_requested_state_cannot_claim_implemented_behavior(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "0042-login-policy.md"
            path.write_text(
                decision_frontmatter(implementation_status="implemented"),
                encoding="utf-8",
            )
            result = validate(path)
            self.assertFalse(result["valid"])
            self.assertIn(
                "RequestedState must remain not_implemented", result["errors"]
            )

    def test_compatible_unknown_frontmatter_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "0042-login-policy.md"
            path.write_text(
                decision_frontmatter().replace(
                    "status: accepted\n", "status: accepted\nowner: platform-team\n"
                ),
                encoding="utf-8",
            )
            self.assertEqual(validate(path), {"valid": True, "errors": []})


if __name__ == "__main__":
    unittest.main()
