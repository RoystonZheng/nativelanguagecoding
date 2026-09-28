import sys
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit.contracts import (
    ARTIFACT_TYPES,
    ArtifactEnvelope,
    RequirementDocRef,
    canonical_json_bytes,
    decode_repository_scope,
    encode_repository_scope,
    make_envelope,
    reference_for,
)
from ai_native_devkit.errors import ContractError


class CanonicalContractTests(unittest.TestCase):
    def test_removed_clarification_artifacts_are_not_registered(self):
        self.assertNotIn("clarification_checkpoint", ARTIFACT_TYPES)
        self.assertNotIn("clarification_result", ARTIFACT_TYPES)
        with self.assertRaises(ContractError):
            make_envelope(
                "clarification_result",
                "task-1",
                {},
                None,
                [],
                "ai-native-devkit/workflow-runtime@0.4.0",
            )

    def test_requirement_doc_ref_round_trips_and_hashes_canonical_identity(self):
        reference = RequirementDocRef.from_dict(
            {
                "path": "docs/superpowers/requirements/2026-08-27-login-requirements.md",
                "commit": "a" * 40,
                "blob_digest": "git-sha1:" + "b" * 40,
            }
        )
        self.assertEqual(reference, RequirementDocRef.from_dict(reference.to_dict()))
        self.assertEqual(
            reference.subject_digest(),
            "sha256:9e73e6a3e983a7cd3d4459854831fdd34dbe7ff8f6ffa7881d07d1112620527f",
        )

    def test_requirement_doc_ref_preserves_compatible_unknown_fields(self):
        value = {
            "path": "docs/superpowers/requirements/2026-08-27-login-requirements.md",
            "commit": "a" * 40,
            "blob_digest": "git-sha1:" + "b" * 40,
            "future_identity": {"mode": "strict", "revision": 2},
        }
        self.assertEqual(RequirementDocRef.from_dict(value).to_dict(), value)

    def test_requirement_doc_ref_extension_identity_cannot_be_mutated(self):
        value = {
            "path": "docs/superpowers/requirements/2026-08-27-login-requirements.md",
            "commit": "a" * 40,
            "blob_digest": "git-sha1:" + "b" * 40,
            "future_identity": {"modes": ["strict"]},
        }
        reference = RequirementDocRef.from_dict(value)
        digest = reference.subject_digest()
        value["future_identity"]["modes"].append("mutated")
        exported = reference.to_dict()
        exported["future_identity"]["modes"].append("also-mutated")
        with self.assertRaises(TypeError):
            reference.extra["other"] = True
        self.assertEqual(reference.subject_digest(), digest)
        self.assertEqual(reference.to_dict()["future_identity"], {"modes": ["strict"]})

    def test_requirement_doc_ref_direct_constructor_validates_and_freezes_extra(self):
        extra = {"future_identity": {"modes": ["strict"]}}
        reference = RequirementDocRef(
            "docs/superpowers/requirements/2026-08-27-login-requirements.md",
            "a" * 40,
            "git-sha1:" + "b" * 40,
            extra,
        )
        digest = reference.subject_digest()
        extra["future_identity"]["modes"].append("mutated")
        self.assertEqual(reference.subject_digest(), digest)
        with self.assertRaises(TypeError):
            reference.extra["future_identity"]["modes"] += ("mutated",)
        with self.assertRaises(ContractError):
            RequirementDocRef("unsafe.md", "short", "git-sha1:bad", {})

    def test_requirement_doc_ref_rejects_path_only(self):
        with self.assertRaises(ContractError):
            RequirementDocRef.from_dict({"path": "docs/superpowers/requirements/x.md"})

    def test_requirement_doc_ref_rejects_mismatched_hash_algorithm(self):
        with self.assertRaises(ContractError):
            RequirementDocRef.from_dict(
                {
                    "path": "docs/superpowers/requirements/2026-08-27-login-requirements.md",
                    "commit": "a" * 40,
                    "blob_digest": "git-sha256:" + "b" * 64,
                }
            )

    def test_canonical_envelope_bytes_and_digest_are_frozen(self):
        envelope = {
            "schema_version": "ai-native-devkit/v1alpha1",
            "artifact_type": "task_request",
            "artifact_id": "00000000-0000-4000-8000-000000000001",
            "task_id": "fixture-task",
            "created_at": "2026-08-24T00:00:00.000Z",
            "producer": "fixture@1.0.0",
            "repo_revision": None,
            "input_refs": [],
            "payload": {
                "intent": "init",
                "user_request": "/init",
                "repository": {
                    "requested_path": "/tmp/repo",
                    "observed_root": "/tmp/repo",
                    "requested_scope": None,
                    "expected_revision": None,
                },
                "constraints": {
                    "scope": None,
                    "permissions": [],
                    "destructive_actions": "denied",
                },
                "attachments": [],
                "future": {"β": True},
            },
            "future_envelope": {"value": 7},
        }
        expected = (
            '{"artifact_id":"00000000-0000-4000-8000-000000000001",'
            '"artifact_type":"task_request","created_at":"2026-08-24T00:00:00.000Z",'
            '"future_envelope":{"value":7},"input_refs":[],"payload":'
            '{"attachments":[],"constraints":{"destructive_actions":"denied",'
            '"permissions":[],"scope":null},"future":{"β":true},"intent":"init",'
            '"repository":{"expected_revision":null,"observed_root":"/tmp/repo",'
            '"requested_path":"/tmp/repo","requested_scope":null},'
            '"user_request":"/init"},"producer":"fixture@1.0.0",'
            '"repo_revision":null,"schema_version":"ai-native-devkit/v1alpha1",'
            '"task_id":"fixture-task"}'
        ).encode("utf-8")

        self.assertEqual(canonical_json_bytes(envelope), expected)
        self.assertEqual(
            reference_for(envelope).digest,
            "sha256:9ebef81a5b30950d426090c4bcbe3fba7fa8bbb410403275b0cca1b278de17d0",
        )
        self.assertEqual(ArtifactEnvelope.from_dict(envelope).to_dict(), envelope)

    def test_repository_authority_scope_has_reversible_canonical_encoding(self):
        examples = [
            (None, "repository:v1:."),
            (
                "Sub Directory/中文%:A",
                "repository:v1:Sub%20Directory/%E4%B8%AD%E6%96%87%25%3AA",
            ),
            ("a" * 200, "repository:v1:" + "a" * 200),
        ]

        for requested_scope, encoded in examples:
            with self.subTest(requested_scope=requested_scope):
                self.assertEqual(encode_repository_scope(requested_scope), encoded)
                self.assertEqual(decode_repository_scope(encoded), requested_scope)

    def test_repository_authority_scope_rejects_noncanonical_or_unsafe_encodings(self):
        invalid = [
            "repository:.",
            "repository:v1:%41",
            "repository:v1:%e4%b8%ad",
            "repository:v1:%FF",
            "repository:v1:../outside",
            "repository:v1:a//b",
        ]

        for encoded in invalid:
            with self.subTest(encoded=encoded):
                with self.assertRaises(ContractError):
                    decode_repository_scope(encoded)


if __name__ == "__main__":
    unittest.main()
