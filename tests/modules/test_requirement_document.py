from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from typing import get_type_hints


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit import requirement_document
from ai_native_devkit.errors import RequirementDocumentError
from ai_native_devkit.execution_trace import ExecutionTraceStore
from ai_native_devkit.requirement_approval import RequirementApprovalGate
from ai_native_devkit.requirement_document import (
    MAX_REQUIREMENT_DOCUMENT_BYTES,
    RequirementDocumentLoader,
    RequirementDocumentWriter,
    RequirementSource,
)
from tests.modules.test_requirement_approval import emit_attempt


class RequirementDocumentWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repository"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "DevKit Test")
        self.git("config", "user.email", "devkit@example.test")
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        self.git("add", "seed.txt")
        self.git("commit", "-m", "seed")
        self.writer = RequirementDocumentWriter(today=lambda: date(2026, 8, 27))

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments, check=True):
        return subprocess.run(
            ["git", *arguments], cwd=self.repo, check=check,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def write(self, requirements="Only administrators may revoke active sessions.", **overrides):
        return self.writer.write_and_commit(
            repository_root=self.repo,
            title=overrides.pop("title", "Login Policy"),
            clarified_requirements=requirements,
            sources=overrides.pop("sources", ()),
            supersedes=overrides.pop("supersedes", None),
            **overrides,
        )

    def committed(self, reference):
        return self.git("show", f"{reference.commit}:{reference.path}").stdout.decode()

    def test_writer_commits_exact_minimal_document_and_returns_git_identity(self):
        reference = self.write()
        self.assertEqual(
            self.committed(reference),
            "# Login Policy\n\n## 已澄清的需求\n\n"
            "Only administrators may revoke active sessions.\n",
        )
        self.assertRegex(reference.commit, r"^[0-9a-f]{40}$")
        self.assertRegex(reference.blob_digest, r"^git-sha1:[0-9a-f]{40}$")

    def test_writer_omits_sources_section_when_sources_are_empty(self):
        self.assertNotIn("## 来源", self.committed(self.write()))

    def test_writer_honors_explicit_english_and_loader_reads_legacy_format(self):
        source = RequirementSource("external", "https://example.test/policy", "v2", "Policy.")
        reference = self.write(sources=(source,), document_language="en")
        content = self.committed(reference)
        self.assertIn("## Clarified Requirements", content)
        self.assertIn("## Sources\n\n- External:", content)
        self.assertEqual(requirement_document._parse_requirement_document(content), [source])
        RequirementDocumentLoader().verify_current(repository_root=self.repo, reference=reference)

    def test_writer_excludes_oversized_ignored_and_other_untracked_files(self):
        (self.repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        self.git("add", ".gitignore")
        self.git("commit", "-m", "ignore dependencies")
        paths = [self.repo / "node_modules/cache.bin", self.repo / "untracked.bin"]
        for path in paths:
            path.parent.mkdir(exist_ok=True)
            with path.open("wb") as stream:
                stream.truncate(65 * 1024 * 1024)
        before = {path: path.stat() for path in paths}
        reference = self.write()
        changed = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", reference.commit)
        self.assertEqual(changed.stdout.decode().splitlines(), [reference.path])
        for path in paths:
            self.assertEqual(path.stat().st_size, before[path].st_size)
            self.assertEqual(path.stat().st_mtime_ns, before[path].st_mtime_ns)

    def test_writer_rejects_document_over_byte_limit_before_writing(self):
        prefix = "# Login Policy\n\n## 已澄清的需求\n\n"
        exact = "x" * (MAX_REQUIREMENT_DOCUMENT_BYTES - len(prefix.encode()) - 1)
        self.write(exact)
        before = self.git("rev-parse", "HEAD").stdout
        with self.assertRaises(RequirementDocumentError) as caught:
            self.write(exact + "x")
        self.assertEqual(caught.exception.code, "requirements.document_too_large")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)

    def test_writer_renders_repository_and_external_sources(self):
        sources = (
            RequirementSource(
                "repository", "seed.txt", self.git("rev-parse", "HEAD").stdout.decode().strip(),
                "supports the existing repository behavior.",
            ),
            RequirementSource(
                "external", "https://example.test/policy", "v2",
                "supports the required external policy version.",
            ),
            RequirementSource(
                "external", "cooper_doc_123", "sync-2026-08-27",
                "supports the linked knowledge-base requirement.",
            ),
        )
        content = self.committed(self.write(sources=sources))
        self.assertIn("## 来源", content)
        self.assertIn("- 仓库: `seed.txt` 版本 `", content)
        self.assertIn("- 外部: `https://example.test/policy` 版本 `v2`", content)
        self.assertIn("- 外部: `cooper_doc_123` 版本 `sync-2026-08-27`", content)
        self.assertEqual(requirement_document._parse_requirement_document(content), list(sources))

    def test_requirement_source_round_trips_at_json_boundary(self):
        value = {
            "kind": "external",
            "locator": "resource://cooper/document/123",
            "version": "sync-2026-08-27",
            "supports": "supports the linked requirement.",
        }
        self.assertEqual(RequirementSource.from_dict(value).to_dict(), value)

    def test_writer_rejects_invalid_source_values_before_repository_mutation(self):
        head = self.git("rev-parse", "HEAD").stdout
        invalid = (
            RequirementSource("unknown", "policy", "v1", "supports it."),
            RequirementSource(
                "external", "http://example.test/policy", "v1", "supports it."
            ),
            RequirementSource(
                "external", "https://[invalid", "v1", "supports it."
            ),
            RequirementSource(
                "repository", "../outside.py", "a" * 40, "supports it."
            ),
            RequirementSource(
                "repository", "seed.txt", "short", "supports it."
            ),
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(RequirementDocumentError) as caught:
                    self.write(sources=(source,))
                self.assertEqual(caught.exception.code, "requirements.source_invalid")
                self.assertEqual(self.git("rev-parse", "HEAD").stdout, head)
                self.assertFalse(
                    (self.repo / "docs/superpowers/requirements").exists()
                )

    def test_writer_rejects_source_markdown_injection(self):
        valid = {
            "kind": "external", "locator": "https://example.test/policy",
            "version": "v2", "supports": "supports the policy.",
        }
        for field, value in (
            ("locator", "https://example.test/`bad"),
            ("locator", "http://example.test/not-allowed"),
            ("version", "v2\n## Injected"),
            ("version", "v2\u0085injected"),
            ("supports", "supports\u2028injected"),
            ("supports", "supports\u2029injected"),
            ("supports", "supports it.\r\n- External: `injected` at `v1`"),
        ):
            with self.subTest(field=field):
                source = RequirementSource(**{**valid, field: value})
                with self.assertRaises(RequirementDocumentError) as caught:
                    self.write(sources=(source,))
                self.assertEqual(caught.exception.code, "requirements.source_invalid")

    def test_writer_uses_hash_slug_for_non_ascii_title(self):
        reference = self.write(title="登录策略")
        digest = hashlib.sha256("登录策略".encode()).hexdigest()[:12]
        self.assertEqual(
            reference.path,
            f"docs/superpowers/requirements/2026-08-27-topic-{digest}-requirements.md",
        )

    def test_writer_bounds_long_ascii_slug_with_title_hash(self):
        title = "Very Long Login Policy " * 1000
        reference = self.write(title=title)
        filename = PurePosixPath(reference.path).name
        self.assertLessEqual(len(filename.encode("utf-8")), 128)
        self.assertIn(hashlib.sha256(title.encode()).hexdigest()[:12], filename)

    def test_writer_uses_deterministic_suffix_without_overwriting(self):
        occupied = self.repo / "docs/superpowers/requirements/2026-08-27-login-policy-requirements.md"
        occupied.parent.mkdir(parents=True)
        occupied.write_text("user file\n", encoding="utf-8")
        reference = self.write()
        self.assertTrue(reference.path.endswith("-requirements-2.md"))
        self.assertEqual(occupied.read_text(encoding="utf-8"), "user file\n")

    def test_writer_treats_symlink_or_directory_leaf_as_reserved(self):
        requirements = self.repo / "docs/superpowers/requirements"
        requirements.mkdir(parents=True)
        base = requirements / "2026-08-27-login-policy-requirements.md"
        outside = Path(self.temporary.name) / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        for kind in ("symlink", "directory"):
            with self.subTest(kind=kind):
                if base.is_symlink():
                    base.unlink()
                elif base.exists():
                    base.rmdir()
                if kind == "symlink":
                    base.symlink_to(outside)
                else:
                    base.mkdir()
                reference = self.write()
                self.assertTrue(reference.path.endswith("-requirements-2.md"))
                self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")
                created = self.repo / reference.path
                created.unlink()
                self.git("reset", "--hard", "HEAD^")

    def test_writer_reserves_path_found_only_in_history_after_committed_deletion(self):
        historical = self.repo / "docs/superpowers/requirements/2026-08-27-login-policy-requirements.md"
        historical.parent.mkdir(parents=True)
        historical.write_text("historical requirement\n", encoding="utf-8")
        self.git("add", str(historical.relative_to(self.repo)))
        self.git("commit", "-m", "record historical requirement")
        historical.unlink()
        self.git("add", "-u", str(historical.relative_to(self.repo)))
        self.git("commit", "-m", "delete historical requirement")
        cached_before = self.git("diff", "--cached", "--binary").stdout
        reference = self.write()
        self.assertTrue(reference.path.endswith("-requirements-2.md"))
        self.assertFalse(historical.exists())
        self.assertEqual(self.git("diff", "--cached", "--binary").stdout, cached_before)

    def test_writer_preserves_staged_unstaged_and_untracked_changes(self):
        (self.repo / "staged.txt").write_text("staged\n", encoding="utf-8")
        self.git("add", "staged.txt")
        staged_before = self.git("diff", "--cached", "--binary").stdout
        (self.repo / "seed.txt").write_text("dirty\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        self.write()
        self.assertEqual(self.git("diff", "--cached", "--binary").stdout, staged_before)
        self.assertEqual((self.repo / "seed.txt").read_text(), "dirty\n")
        self.assertEqual((self.repo / "untracked.txt").read_text(), "untracked\n")

    def test_writer_detects_textconv_hidden_unrelated_change(self):
        helper = Path(self.temporary.name) / "constant-textconv"
        helper.write_text("#!/bin/sh\nprintf 'constant\\n'\n", encoding="utf-8")
        helper.chmod(0o755)
        (self.repo / ".gitattributes").write_text(
            "seed.txt diff=hide\n", encoding="utf-8"
        )
        self.git("config", "diff.hide.textconv", str(helper))
        self.git("add", ".gitattributes")
        self.git("commit", "-m", "configure hiding textconv")
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text(
            "#!/bin/sh\nprintf 'hook-mutated\\n' > seed.txt\n", encoding="utf-8"
        )
        hook.chmod(0o755)
        with self.assertRaises(RequirementDocumentError) as caught:
            self.write()
        self.assertEqual(caught.exception.code, "requirements.commit_indeterminate")
        self.assertEqual(
            self.git("diff", "--quiet", "--", "seed.txt", check=False).returncode,
            0,
        )
        self.assertEqual(
            self.git(
                "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
                "--quiet", "--",
                "seed.txt", check=False,
            ).returncode,
            1,
        )

    def test_git_runner_disables_replace_refs_and_legacy_grafts(self):
        original = self.git("rev-parse", "HEAD").stdout.decode().strip()
        (self.repo / "seed.txt").write_text("replacement\n", encoding="utf-8")
        self.git("commit", "-am", "replacement candidate")
        replacement = self.git("rev-parse", "HEAD").stdout.decode().strip()
        self.git("reset", "--hard", original)
        self.git("replace", original, replacement)
        common = Path(
            self.git(
                "rev-parse", "--path-format=absolute", "--git-common-dir"
            ).stdout.decode().strip()
        )
        (common / "info/grafts").write_text(
            f"{original} {replacement}\n", encoding="utf-8"
        )
        self.assertEqual(
            requirement_document._git(
                self.repo, "cat-file", "blob", f"{original}:seed.txt"
            ),
            b"seed\n",
        )
        self.assertEqual(
            requirement_document._git(
                self.repo, "rev-list", "--parents", "-n", "1", original
            ).decode().split(),
            [original],
        )

    def test_git_runner_reports_timeout_and_output_cap_without_raising(self):
        timed = requirement_document._git_result(
            self.repo,
            "-c",
            "alias.pause=!sleep 5",
            "pause",
            timeout=0.05,
        )
        self.assertTrue(timed.started)
        self.assertTrue(timed.timed_out)

        (self.repo / "untracked-output.txt").write_text("output\n", encoding="utf-8")
        capped = requirement_document._git_result(
            self.repo, "status", "--short", output_limit=1
        )
        self.assertTrue(capped.started)
        self.assertTrue(capped.output_exceeded)

    def test_writer_rejects_invalid_document_language_before_repository_mutation(self):
        before = self.git("status", "--short").stdout
        for language in (None, [], "unsupported"):
            with self.subTest(language=language):
                with self.assertRaises(RequirementDocumentError) as caught:
                    self.write(document_language=language)
                self.assertEqual(caught.exception.code, "requirements.document_language_invalid")
        self.assertEqual(self.git("status", "--short").stdout, before)

    def test_writer_commit_diff_contains_only_requirement_document(self):
        reference = self.write()
        changed = self.git(
            "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", reference.commit
        ).stdout.decode().splitlines()
        self.assertEqual(changed, [reference.path])

    def test_writer_revision_reuses_path_and_preserves_old_blob(self):
        first = self.write()
        old_content = self.committed(first)
        second = self.write("Administrators must provide a reason.", supersedes=first)
        self.assertEqual(second.path, first.path)
        self.assertNotEqual(second.commit, first.commit)
        self.assertEqual(self.git("show", f"{first.commit}:{first.path}").stdout.decode(), old_content)

    def test_writer_rejects_manual_change_before_revision(self):
        first = self.write()
        (self.repo / first.path).write_text("manual edit\n", encoding="utf-8")
        with self.assertRaises(RequirementDocumentError) as caught:
            self.write("revised", supersedes=first)
        self.assertEqual(caught.exception.code, "requirements.document_worktree_drift")

    def test_writer_rejects_non_git_repository_and_symlink_escape(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        with self.assertRaises(RequirementDocumentError):
            self.writer.write_and_commit(
                repository_root=outside, title="Title", clarified_requirements="Requirement."
            )
        superpowers = self.repo / "docs/superpowers"
        superpowers.parent.mkdir()
        superpowers.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RequirementDocumentError) as caught:
            self.write()
        self.assertEqual(caught.exception.code, "requirements.path_unsafe")

    def test_writer_rejects_missing_git_identity(self):
        self.git("config", "--unset-all", "user.name")
        self.git("config", "--unset-all", "user.email")
        empty_home = Path(self.temporary.name) / "empty-home"
        empty_home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(empty_home)}):
            with self.assertRaises(RequirementDocumentError) as caught:
                self.write()
        self.assertEqual(caught.exception.code, "requirements.git_identity_missing")

    def test_writer_rejects_missing_git_capability_before_write(self):
        before = self.git("rev-parse", "HEAD").stdout
        with mock.patch.object(
            requirement_document, "_require_supported_git",
            side_effect=RequirementDocumentError(
                "requirements.repository_unsupported",
                "Required Git capabilities are unavailable.",
            ),
        ):
            with self.assertRaises(RequirementDocumentError) as caught:
                self.write()
        self.assertEqual(caught.exception.code, "requirements.repository_unsupported")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)
        self.assertFalse((self.repo / "docs/superpowers/requirements").exists())

    def test_writer_runs_commit_policy_hooks_with_native_path_limited_commit(self):
        hooks = self.repo / ".git/hooks"
        log = Path(self.temporary.name) / "hook-order.log"
        (self.repo / "staged.txt").write_text("staged\n", encoding="utf-8")
        self.git("add", "staged.txt")
        cached_before = self.git("diff", "--cached", "--binary").stdout
        scripts = {
            "pre-commit": f"#!/bin/sh\nprintf 'pre\\n' >> {shlex.quote(str(log))}\ngit diff --cached --quiet -- staged.txt\n! git diff --cached --quiet -- docs/superpowers/requirements/2026-08-27-login-policy-requirements.md\n",
            "prepare-commit-msg": f"#!/bin/sh\nprintf 'prepare\\n' >> {shlex.quote(str(log))}\nprintf '\\nPolicy-Checked: yes\\n' >> \"$1\"\n",
            "commit-msg": f"#!/bin/sh\nprintf 'message\\n' >> {shlex.quote(str(log))}\ngrep -q 'Policy-Checked: yes' \"$1\"\n",
            "post-commit": f"#!/bin/sh\nprintf 'post\\n' >> {shlex.quote(str(log))}\n",
        }
        for name, script in scripts.items():
            hook = hooks / name
            hook.write_text(script, encoding="utf-8")
            hook.chmod(0o755)
        reference = self.write()
        self.assertEqual(log.read_text(encoding="utf-8").splitlines(), [
            "pre", "prepare", "message", "post",
        ])
        self.assertIn(
            "Policy-Checked: yes",
            self.git("show", "-s", "--format=%B", reference.commit).stdout.decode(),
        )
        self.assertEqual(self.git("diff", "--cached", "--binary").stdout, cached_before)

    def test_writer_honors_required_commit_signing_and_cleans_up_failure(self):
        self.git("config", "commit.gpgSign", "true")
        self.git("config", "gpg.program", str(self.repo / "missing-gpg"))
        before_head = self.git("rev-parse", "HEAD").stdout
        before_index = self.git("diff", "--cached", "--binary").stdout
        with self.assertRaises(RequirementDocumentError) as caught:
            self.write()
        self.assertEqual(caught.exception.code, "requirements.commit_failed")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before_head)
        self.assertEqual(self.git("diff", "--cached", "--binary").stdout, before_index)
        self.assertFalse(
            (
                self.repo
                / "docs/superpowers/requirements/"
                "2026-08-27-login-policy-requirements.md"
            ).exists()
        )

    def test_pre_commit_failure_does_not_move_head_or_touch_unrelated_changes(self):
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        target = self.repo / (
            "docs/superpowers/requirements/"
            "2026-08-27-login-policy-requirements.md"
        )
        before_head = self.git("rev-parse", "HEAD").stdout
        before_index = self.git("diff", "--cached", "--binary").stdout
        with self.assertRaises(RequirementDocumentError) as caught:
            self.write()
        self.assertEqual(caught.exception.code, "requirements.commit_failed")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before_head)
        self.assertEqual(self.git("diff", "--cached", "--binary").stdout, before_index)
        self.assertFalse(target.exists())

    def test_pre_commit_failure_restores_exact_revision_bytes(self):
        first = self.write()
        prior = (self.repo / first.path).read_bytes()
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        before_head = self.git("rev-parse", "HEAD").stdout
        before_index = self.git("diff", "--cached", "--binary").stdout
        with self.assertRaises(RequirementDocumentError) as caught:
            self.write("Revised requirement.", supersedes=first)
        self.assertEqual(caught.exception.code, "requirements.commit_failed")
        self.assertEqual((self.repo / first.path).read_bytes(), prior)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before_head)
        self.assertEqual(self.git("diff", "--cached", "--binary").stdout, before_index)

    def test_reference_transaction_hook_failure_does_not_move_head(self):
        hook = self.repo / ".git/hooks/reference-transaction"
        hook.write_text(
            "#!/bin/sh\nif [ \"$1\" = prepared ]; then exit 1; fi\nexit 0\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        before_head = self.git("rev-parse", "HEAD").stdout
        (self.repo / "staged.txt").write_text("staged\n", encoding="utf-8")
        self.git("add", "staged.txt")
        before_index = self.git("diff", "--cached", "--binary").stdout
        with self.assertRaises(RequirementDocumentError) as caught:
            self.write()
        self.assertEqual(caught.exception.code, "requirements.commit_failed")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before_head)
        self.assertEqual(self.git("diff", "--cached", "--binary").stdout, before_index)
        self.assertFalse(
            (self.repo / "docs/superpowers/requirements/"
             "2026-08-27-login-policy-requirements.md").exists()
        )

    def test_writer_exposes_only_intent_to_add_before_native_commit(self):
        real = requirement_document._git_result
        observed = []
        (self.repo / "staged.txt").write_text("staged\n", encoding="utf-8")
        self.git("add", "staged.txt")
        unrelated_before = self.git(
            "diff", "--cached", "--binary", "--", "staged.txt"
        ).stdout

        def inspect_before_commit(root, *arguments, **kwargs):
            if arguments[:1] == ("commit",):
                cached = self.git(
                    "diff", "--cached", "--quiet", "--",
                    "docs/superpowers/requirements", check=False,
                )
                entry = self.git(
                    "ls-files", "--stage", "--",
                    "docs/superpowers/requirements",
                ).stdout
                observed.append((cached.returncode, entry))
                self.assertEqual(cached.returncode, 0)
                self.assertTrue(entry)
                self.assertEqual(
                    self.git("diff", "--cached", "--binary", "--", "staged.txt").stdout,
                    unrelated_before,
                )
            return real(root, *arguments, **kwargs)

        with mock.patch.object(requirement_document, "_git_result", inspect_before_commit):
            reference = self.write()
        self.assertTrue(observed)
        self.assertEqual(
            self.git("diff", "--cached", "--", reference.path).stdout, b""
        )

    def test_external_head_advance_before_native_commit_is_indeterminate(self):
        real = requirement_document._git_result
        advanced = False

        def advance_before_commit(root, *arguments, **kwargs):
            nonlocal advanced
            if arguments[:1] == ("commit",) and not advanced:
                advanced = True
                (self.repo / "competing.txt").write_text("competing\n", encoding="utf-8")
                self.git("add", "competing.txt")
                self.git("commit", "-m", "competing commit")
            return real(root, *arguments, **kwargs)

        with mock.patch.object(requirement_document, "_git_result", advance_before_commit):
            with self.assertRaises(RequirementDocumentError) as caught:
                self.write()
        self.assertEqual(caught.exception.code, "requirements.commit_indeterminate")

    def test_writer_fails_closed_when_requirements_ancestor_is_swapped_during_write(self):
        outside = Path(self.temporary.name) / "outside-requirements"
        outside.mkdir()
        original_install = requirement_document._RequirementDirectory.install_initial

        def install_then_swap(directory, filename, rendered):
            installed = original_install(directory, filename, rendered)
            ancestor = self.repo / "docs/superpowers"
            ancestor.rename(self.repo / "docs/superpowers-owned")
            ancestor.symlink_to(outside, target_is_directory=True)
            return installed

        before_head = self.git("rev-parse", "HEAD").stdout
        with mock.patch.object(
            requirement_document._RequirementDirectory,
            "install_initial",
            install_then_swap,
        ):
            with self.assertRaises(RequirementDocumentError) as caught:
                self.write()
        self.assertEqual(caught.exception.code, "requirements.path_unsafe")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before_head)
        self.assertEqual(list(outside.iterdir()), [])

    def test_writer_rejects_common_directory_identity_drift_before_return(self):
        original_read = requirement_document._read_head_attachment
        calls = 0

        def read_then_swap(root, **kwargs):
            nonlocal calls
            value = original_read(root, **kwargs)
            calls += 1
            if calls == 2:
                common = Path(
                    self.git(
                        "rev-parse", "--path-format=absolute", "--git-common-dir"
                    ).stdout.decode().strip()
                ).resolve(strict=True)
                replacement = Path(self.temporary.name) / "common-replacement"
                original = Path(self.temporary.name) / "common-original"
                shutil.copytree(common, replacement, symlinks=True)
                common.rename(original)
                replacement.rename(common)
            return value

        with mock.patch.object(
            requirement_document, "_read_head_attachment", read_then_swap
        ):
            with self.assertRaises(RequirementDocumentError) as caught:
                self.write()
        self.assertEqual(caught.exception.code, "requirements.commit_indeterminate")
        self.assertEqual(calls, 2)

    def test_cooperative_writers_serialize_and_commit_distinct_paths(self):
        def write(requirement):
            writer = RequirementDocumentWriter(today=lambda: date(2026, 8, 27))
            return writer.write_and_commit(
                repository_root=self.repo,
                title="Login Policy",
                clarified_requirements=requirement,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            references = list(
                executor.map(write, ("First requirement.", "Second requirement."))
            )
        self.assertEqual(
            {reference.path for reference in references},
            {
                "docs/superpowers/requirements/"
                "2026-08-27-login-policy-requirements.md",
                "docs/superpowers/requirements/"
                "2026-08-27-login-policy-requirements-2.md",
            },
        )

    def test_writer_detects_same_oid_head_detach_in_post_commit_hook(self):
        hook = self.repo / ".git/hooks/post-commit"
        hook.write_text(
            "#!/bin/sh\noid=$(git rev-parse HEAD)\n"
            "git update-ref --no-deref HEAD \"$oid\"\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        with self.assertRaises(RequirementDocumentError) as caught:
            self.write()
        self.assertEqual(caught.exception.code, "requirements.commit_indeterminate")
        self.assertEqual(
            self.git("symbolic-ref", "-q", "HEAD", check=False).returncode, 1
        )

    def test_writer_supports_an_unborn_repository(self):
        unborn = Path(self.temporary.name) / "unborn"
        unborn.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=unborn, check=True)
        subprocess.run(["git", "config", "user.name", "DevKit Test"], cwd=unborn, check=True)
        subprocess.run(["git", "config", "user.email", "devkit@example.test"], cwd=unborn, check=True)
        reference = self.writer.write_and_commit(
            repository_root=unborn, title="Login Policy",
            clarified_requirements="Only administrators may revoke active sessions.",
        )
        parents = subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", reference.commit],
            cwd=unborn, check=True, stdout=subprocess.PIPE,
        ).stdout.decode().split()
        self.assertEqual(parents, [reference.commit])

    def test_writer_rejects_active_content_filter_before_head_moves(self):
        attributes = self.repo / ".gitattributes"
        attributes.write_text(
            "docs/superpowers/requirements/*.md filter=example\n", encoding="utf-8"
        )
        self.git("add", ".gitattributes")
        self.git("commit", "-m", "add attributes")
        head = self.git("rev-parse", "HEAD").stdout
        with self.assertRaises(RequirementDocumentError) as caught:
            self.write()
        self.assertEqual(caught.exception.code, "requirements.content_transformed")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, head)


class RequirementDocumentLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repository"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "DevKit Test")
        self.git("config", "user.email", "devkit@example.test")
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        self.git("add", "seed.txt")
        self.git("commit", "-m", "seed")
        self.store = ExecutionTraceStore(Path(self.temporary.name) / "traces")
        self.writer = RequirementDocumentWriter(today=lambda: date(2026, 8, 27))
        self.loader = RequirementDocumentLoader()

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments, check=True, repository=None):
        return subprocess.run(
            ["git", *arguments], cwd=repository or self.repo, check=check,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def write(self, *, repository=None, sources=()):
        return self.writer.write_and_commit(
            repository_root=repository or self.repo,
            title="Login Policy",
            clarified_requirements="Only administrators may revoke sessions.",
            sources=sources,
        )

    def approve(self, reference, *, repository=None, session_id="approved-session"):
        root = repository or self.repo
        emit_attempt(
            self.store, session_id=session_id, repository_root=root,
            reference=reference,
        )

    def assert_loader_error(self, reference, code):
        with self.assertRaises(RequirementDocumentError) as caught:
            self.loader.load_approved(
                trace_store=self.store, repository_root=self.repo,
                reference=reference,
            )
        self.assertEqual(caught.exception.code, code)

    def test_loader_returns_exact_approved_committed_markdown(self):
        reference = self.write()
        committed_blob = self.git(
            "cat-file", "blob", reference.blob_digest.split(":", 1)[1]
        ).stdout
        self.approve(reference)
        loaded = self.loader.load_approved(
            trace_store=self.store, repository_root=self.repo,
            reference=reference,
        )
        self.assertEqual(loaded.encode("utf-8"), committed_blob)

    def test_sha256_repository_writer_approval_loader_round_trip(self):
        repository = Path(self.temporary.name) / "sha256-repository"
        repository.mkdir()
        self.git("init", "--object-format=sha256", "-b", "main", repository=repository)
        self.git("config", "user.name", "DevKit Test", repository=repository)
        self.git("config", "user.email", "devkit@example.test", repository=repository)
        (repository / "seed.txt").write_text("seed\n", encoding="utf-8")
        self.git("add", "seed.txt", repository=repository)
        self.git("commit", "-m", "seed", repository=repository)
        reference = self.write(repository=repository)
        self.assertRegex(reference.commit, r"^[0-9a-f]{64}$")
        self.assertRegex(reference.blob_digest, r"^git-sha256:[0-9a-f]{64}$")
        self.approve(reference, repository=repository, session_id="sha256-session")
        loaded = self.loader.load_approved(
            trace_store=self.store, repository_root=repository, reference=reference,
        )
        self.assertEqual(
            loaded.encode("utf-8"),
            self.git(
                "cat-file", "blob", reference.blob_digest.split(":", 1)[1],
                repository=repository,
            ).stdout,
        )

    def test_loader_classifies_index_worktree_missing_and_committed_drift(self):
        cases = (
            ("index", "requirements.document_index_drift"),
            ("worktree", "requirements.document_worktree_drift"),
            ("missing", "requirements.document_missing"),
            ("committed", "requirements.document_committed_drift"),
        )
        for mutation, expected in cases:
            with self.subTest(mutation=mutation):
                reference = self.write()
                self.approve(reference, session_id="approval-" + mutation)
                target = self.repo / reference.path
                if mutation == "index":
                    target.write_text("staged change\n", encoding="utf-8")
                    self.git("add", reference.path)
                elif mutation == "worktree":
                    target.write_text("worktree change\n", encoding="utf-8")
                elif mutation == "missing":
                    target.unlink()
                else:
                    target.write_text("committed change\n", encoding="utf-8")
                    self.git("add", reference.path)
                    self.git("commit", "-m", "change requirement")
                self.assert_loader_error(reference, expected)
                self.git("reset", "--hard", "HEAD~1" if mutation == "committed" else "HEAD")

    def test_loader_maps_missing_directory_and_unsafe_leaf_separately(self):
        reference = self.write()
        self.approve(reference)
        target = self.repo / reference.path
        shutil.rmtree(target.parent)
        self.assert_loader_error(reference, "requirements.document_missing")
        self.git("reset", "--hard", "HEAD")
        outside = Path(self.temporary.name) / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        target.unlink()
        target.symlink_to(outside)
        self.assert_loader_error(reference, "requirements.path_unsafe")

    def test_loader_rechecks_document_after_approval_scan(self):
        reference = self.write()
        self.approve(reference)
        target = self.repo / reference.path

        def mutate_after_authorization(**_kwargs):
            target.write_text("changed during scan\n", encoding="utf-8")
            return mock.sentinel.approval

        with mock.patch.object(
            RequirementApprovalGate, "require_approved",
            side_effect=mutate_after_authorization,
        ):
            self.assert_loader_error(reference, "requirements.document_worktree_drift")

    def test_loader_rejects_repository_path_swap_after_approval_lookup(self):
        reference = self.write()
        logical_root = Path(self.temporary.name) / "logical-repository"
        logical_root.symlink_to(self.repo, target_is_directory=True)
        replacement = Path(self.temporary.name) / "replacement-repository"
        self.git(
            "clone", "--no-hardlinks", str(self.repo), str(replacement),
            repository=Path(self.temporary.name),
        )
        self.approve(reference, repository=logical_root)
        require_approved = RequirementApprovalGate.require_approved

        def approve_then_swap(gate, **kwargs):
            approval = require_approved(gate, **kwargs)
            logical_root.unlink()
            logical_root.symlink_to(replacement, target_is_directory=True)
            return approval

        with mock.patch.object(
            RequirementApprovalGate, "require_approved", new=approve_then_swap
        ), self.assertRaises(RequirementDocumentError) as caught:
            self.loader.load_approved(
                trace_store=self.store,
                repository_root=logical_root,
                reference=reference,
            )
        self.assertEqual(caught.exception.code, "requirements.path_unsafe")

    def test_loader_rejects_changed_repository_source(self):
        source_revision = self.git("rev-parse", "HEAD").stdout.decode().strip()
        source = RequirementSource(
            "repository", "seed.txt", source_revision,
            "supports the existing repository behavior.",
        )
        reference = self.write(sources=(source,))
        self.approve(reference)
        (self.repo / "seed.txt").write_text("changed\n", encoding="utf-8")
        self.assert_loader_error(reference, "requirements.source_drift")

    def test_loader_detects_mode_drift_with_core_filemode_disabled(self):
        revision = self.git("rev-parse", "HEAD").stdout.decode().strip()
        source = RequirementSource(
            "repository", "seed.txt", revision,
            "supports the existing repository behavior.",
        )
        reference = self.write(sources=(source,))
        self.approve(reference)
        self.git("config", "core.filemode", "false")
        (self.repo / "seed.txt").chmod(0o755)
        self.assert_loader_error(reference, "requirements.source_drift")

    def test_loader_source_budget_exhaustion_is_typed_drift(self):
        revision = self.git("rev-parse", "HEAD").stdout.decode().strip()
        source = RequirementSource(
            "repository", "seed.txt", revision,
            "supports the existing repository behavior.",
        )
        reference = self.write(sources=(source,))
        self.approve(reference)
        with mock.patch.object(
            requirement_document, "MAX_SOURCE_SNAPSHOT_BYTES", 4
        ):
            self.assert_loader_error(reference, "requirements.source_drift")

    def test_loader_source_deadline_includes_repository_validation(self):
        revision = self.git("rev-parse", "HEAD").stdout.decode().strip()
        source = RequirementSource(
            "repository", "seed.txt", revision,
            "supports the existing repository behavior.",
        )
        now = [100.0]
        original = requirement_document._validated_repository_root

        def slow_validation(repository_root, **kwargs):
            root = original(repository_root, **kwargs)
            now[0] += requirement_document.SOURCE_SNAPSHOT_TIMEOUT_SECONDS + 1
            return root

        with mock.patch.object(
            requirement_document.time, "monotonic", side_effect=lambda: now[0]
        ), mock.patch.object(
            requirement_document, "_validated_repository_root",
            side_effect=slow_validation,
        ), self.assertRaises(RequirementDocumentError) as caught:
            requirement_document._verify_repository_sources(self.repo, (source,))
        self.assertEqual(caught.exception.code, "requirements.source_drift")

    def test_loader_rejects_transient_repository_swap_during_source_scan(self):
        revision = self.git("rev-parse", "HEAD").stdout.decode().strip()
        source = RequirementSource(
            "repository", "seed.txt", revision,
            "supports the existing repository behavior.",
        )
        reference = self.write(sources=(source,))
        self.approve(reference)
        replacement = Path(self.temporary.name) / "replacement-repository"
        self.git(
            "clone", "--no-hardlinks", str(self.repo), str(replacement),
            repository=Path(self.temporary.name),
        )
        (self.repo / "seed.txt").write_text("dirty original\n", encoding="utf-8")
        original_location = Path(self.temporary.name) / "original-repository"
        verify_sources = requirement_document._verify_repository_sources

        def verify_while_swapped(repository_root, sources, **kwargs):
            self.repo.rename(original_location)
            replacement.rename(self.repo)
            try:
                return verify_sources(repository_root, sources, **kwargs)
            finally:
                self.repo.rename(replacement)
                original_location.rename(self.repo)

        with mock.patch.object(
            requirement_document, "_verify_repository_sources",
            side_effect=verify_while_swapped,
        ), self.assertRaises(RequirementDocumentError) as caught:
            self.loader.load_approved(
                trace_store=self.store,
                repository_root=self.repo,
                reference=reference,
            )
        self.assertEqual(caught.exception.code, "requirements.source_drift")
        self.assertEqual((self.repo / "seed.txt").read_text(), "dirty original\n")

    def test_loader_public_signature_has_frozen_annotations(self):
        annotations = get_type_hints(RequirementDocumentLoader.load_approved)
        self.assertIs(annotations["trace_store"], ExecutionTraceStore)
        self.assertIs(annotations["repository_root"], Path)
        self.assertIs(annotations["reference"], requirement_document.RequirementDocRef)
        self.assertIs(annotations["enforce_repository_source_freshness"], bool)
        self.assertIs(annotations["return"], str)

    def test_loader_rechecks_requirement_after_source_scan(self):
        revision = self.git("rev-parse", "HEAD").stdout.decode().strip()
        source = RequirementSource(
            "repository", "seed.txt", revision,
            "supports the existing repository behavior.",
        )
        reference = self.write(sources=(source,))
        self.approve(reference)
        target = self.repo / reference.path
        original = requirement_document._verify_repository_sources

        def scan_then_mutate(repository_root, sources, **kwargs):
            original(repository_root, sources, **kwargs)
            target.write_text("changed after source scan\n", encoding="utf-8")

        with mock.patch.object(
            requirement_document, "_verify_repository_sources",
            side_effect=scan_then_mutate,
        ):
            self.assert_loader_error(
                reference, "requirements.document_worktree_drift"
            )
