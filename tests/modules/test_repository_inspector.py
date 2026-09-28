import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "plugins" / "ai-native-devkit" / "scripts"

sys.path.insert(0, str(SCRIPTS_ROOT))

from ai_native_devkit import repository as repository_module
from ai_native_devkit.repository import RepositoryInspector
from ai_native_devkit.errors import RepositoryError


def run_git(repository, *arguments, env=None):
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    ).stdout.strip()


def create_repository(repository):
    repository.mkdir()
    run_git(repository, "init", "-b", "main")
    (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (repository / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
    (repository / ".gitattributes").write_text(
        "README.md diff=repository-helper\n"
        "global-diff.txt diff=global-helper\n"
        "filtered.txt filter=malicious\n",
        encoding="utf-8",
    )
    (repository / "filtered.txt").write_text("original\n", encoding="utf-8")
    (repository / "global-diff.txt").write_text("original\n", encoding="utf-8")
    run_git(repository, "add", ".")
    run_git(
        repository,
        "-c",
        "user.name=AI Native DevKit Tests",
        "-c",
        "user.email=tests@example.invalid",
        "commit",
        "-m",
        "fixture",
    )


class RepositoryInspectorTests(unittest.TestCase):
    def test_git_process_isolated_from_lazy_fetch_credentials_and_external_files(self):
        inspector = RepositoryInspector()
        environment = inspector._git_environment()
        prefix = inspector._git_prefix()

        self.assertTrue(Path(prefix[0]).is_absolute())
        self.assertEqual(
            environment["PATH"],
            repository_module.TRUSTED_EXECUTABLE_SEARCH_PATH,
        )
        self.assertEqual(environment["GIT_NO_LAZY_FETCH"], "1")
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
        self.assertIn(f"core.attributesFile={os.devnull}", prefix)
        self.assertIn(f"core.excludesFile={os.devnull}", prefix)
        self.assertIn("protocol.allow=never", prefix)
        self.assertIn("credential.helper=", prefix)

    def test_relative_configured_git_executable_is_rejected_before_use(self):
        with self.assertRaises(RepositoryError) as raised:
            RepositoryInspector(git_executable="git")

        self.assertEqual(raised.exception.code, "runtime.git_unavailable")

    def test_oversized_sparse_source_is_blocked_without_path_read_bytes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            oversized = repository / "README.rst"
            with oversized.open("wb") as source:
                source.truncate(repository_module.MAX_SOURCE_BYTES + 1)
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))

            with mock.patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("selected sources must use bounded I/O"),
            ):
                with self.assertRaises(RepositoryError) as raised:
                    inspector.inspect(classification)

            self.assertEqual(
                raised.exception.code,
                "blocked.repository.source_too_large",
            )
            self.assertIsNotNone(raised.exception.observation)
            self.assertEqual(
                [source["path"] for source in raised.exception.observation.sources],
                [".", "README.md"],
            )

    def test_large_untracked_file_is_excluded_from_revision(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))
            before = inspector.inspect(classification).revision
            oversized = repository / "large-untracked.bin"
            with oversized.open("wb") as stream:
                stream.truncate(65 * 1024 * 1024)
            self.assertEqual(inspector.inspect(classification).revision, before)
            (repository / "new.txt").write_text("new source\n")
            run_git(repository, "add", "new.txt")
            staged = inspector.inspect(classification).revision
            self.assertTrue(staged.dirty)
            self.assertNotEqual(staged, before)
            (repository / "new.txt").write_text("edited source\n")
            self.assertNotEqual(inspector.inspect(classification).revision, staged)

    def test_superproject_untracked_files_do_not_block_child_observation(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            superproject = temporary_root / "superproject"
            child_source = temporary_root / "child-source"
            create_repository(superproject)
            create_repository(child_source)
            run_git(
                superproject,
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                str(child_source),
                "modules/child",
            )
            run_git(
                superproject,
                "-c",
                "user.name=AI Native DevKit Tests",
                "-c",
                "user.email=tests@example.invalid",
                "commit",
                "-am",
                "submodule fixture",
            )
            child = (superproject / "modules" / "child").resolve()
            child_head = run_git(child, "rev-parse", "HEAD")
            oversized = superproject / "large-untracked.bin"
            with oversized.open("wb") as untracked:
                untracked.truncate(65 * 1024 * 1024)
            inspector = RepositoryInspector()
            classification = inspector.classify(str(child))

            original_observe_revision = inspector._observe_revision
            observed_roots = []

            def record_observed_root(root):
                observed_roots.append(root.resolve())
                return original_observe_revision(root)

            with mock.patch.object(
                inspector,
                "_observe_revision",
                side_effect=record_observed_root,
            ):
                observation = inspector.inspect(classification)

            self.assertIsNotNone(observation)
            self.assertEqual(observation.revision.head, child_head)
            self.assertEqual(observation.repository["root"], str(child))
            self.assertEqual(
                observation.findings,
                {
                    "entry_docs": ["README.md"],
                    "repository_instructions": ["AGENTS.md"],
                    "verification_commands": [],
                },
            )
            self.assertEqual(
                [source["path"] for source in observation.sources],
                [".", "README.md", "AGENTS.md"],
            )
            self.assertGreaterEqual(observed_roots.count(child), 2)

    def test_git_stdout_over_limit_is_a_typed_repository_blocker(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            for index in range(20):
                (repository / f"long-untracked-name-{index:02d}.txt").write_text(
                    "content\n",
                    encoding="utf-8",
                )
            run_git(repository, "add", ".")
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))

            with mock.patch.object(repository_module, "MAX_GIT_OUTPUT_BYTES", 128):
                with self.assertRaises(RepositoryError) as raised:
                    inspector.inspect(classification)

            self.assertEqual(
                raised.exception.code,
                "blocked.repository.git_output_too_large",
            )

    def test_tracked_deletions_change_the_public_worktree_digest(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))

            (repository / "filtered.txt").unlink()
            first = inspector.inspect(classification).revision
            run_git(repository, "restore", "filtered.txt")
            (repository / "global-diff.txt").unlink()
            second = inspector.inspect(classification).revision

            self.assertTrue(first.dirty)
            self.assertTrue(second.dirty)
            self.assertIsNotNone(first.worktree_digest)
            self.assertIsNotNone(second.worktree_digest)
            self.assertNotEqual(first.worktree_digest, second.worktree_digest)

    def test_tracked_handoff_changes_are_excluded_from_revision_and_digest(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            root_handoff = repository / "handoff/private.md"
            legacy_handoff = repository / "docs/handoff/private.md"
            root_handoff.parent.mkdir(parents=True)
            legacy_handoff.parent.mkdir(parents=True)
            root_handoff.write_text("root baseline\n", encoding="utf-8")
            legacy_handoff.write_text("legacy baseline\n", encoding="utf-8")
            run_git(repository, "add", "handoff", "docs/handoff")
            run_git(
                repository,
                "-c",
                "user.name=AI Native DevKit Tests",
                "-c",
                "user.email=tests@example.invalid",
                "commit",
                "-m",
                "handoff fixture",
            )
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))
            clean = inspector.inspect(classification).revision

            root_handoff.write_text("staged root secret\n", encoding="utf-8")
            run_git(repository, "add", "handoff/private.md")
            legacy_handoff.write_text("unstaged legacy secret\n", encoding="utf-8")

            self.assertEqual(inspector.inspect(classification).revision, clean)

            visible = repository / "filtered.txt"
            visible.write_text("visible version one\n", encoding="utf-8")
            first_visible = inspector.inspect(classification).revision
            root_handoff.write_text("different staged root secret\n", encoding="utf-8")
            run_git(repository, "add", "handoff/private.md")
            legacy_handoff.write_text(
                "different unstaged legacy secret\n",
                encoding="utf-8",
            )
            second_visible = inspector.inspect(classification).revision

            self.assertTrue(first_visible.dirty)
            self.assertEqual(
                first_visible.worktree_digest,
                second_visible.worktree_digest,
            )

            visible.write_text("visible version two\n", encoding="utf-8")
            third_visible = inspector.inspect(classification).revision
            self.assertNotEqual(
                second_visible.worktree_digest,
                third_visible.worktree_digest,
            )

    def test_untracked_handoff_changes_are_excluded_from_revision_and_digest(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))
            clean = inspector.inspect(classification).revision
            root_handoff = repository / "handoff/private.bin"
            legacy_handoff = repository / "docs/handoff/private.bin"
            root_handoff.parent.mkdir(parents=True)
            legacy_handoff.parent.mkdir(parents=True)
            for private_file in (root_handoff, legacy_handoff):
                with private_file.open("wb") as private_content:
                    private_content.truncate(65 * 1024 * 1024)

            self.assertEqual(inspector.inspect(classification).revision, clean)

            visible = repository / "visible-tracked.txt"
            visible.write_text("visible version one\n", encoding="utf-8")
            run_git(repository, "add", "visible-tracked.txt")
            first_visible = inspector.inspect(classification).revision
            for private_file in (root_handoff, legacy_handoff):
                with private_file.open("r+b") as private_content:
                    private_content.truncate(66 * 1024 * 1024)
            second_visible = inspector.inspect(classification).revision

            self.assertTrue(first_visible.dirty)
            self.assertEqual(
                first_visible.worktree_digest,
                second_visible.worktree_digest,
            )

            visible.write_text("visible version two\n", encoding="utf-8")
            third_visible = inspector.inspect(classification).revision
            self.assertNotEqual(
                second_visible.worktree_digest,
                third_visible.worktree_digest,
            )


    def test_superproject_revision_excludes_handoff_changes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            superproject = temporary_root / "superproject"
            child_source = temporary_root / "child-source"
            create_repository(superproject)
            create_repository(child_source)
            root_handoff = superproject / "handoff/private.md"
            legacy_handoff = superproject / "docs/handoff/private.md"
            root_handoff.parent.mkdir(parents=True)
            legacy_handoff.parent.mkdir(parents=True)
            root_handoff.write_text("root baseline\n", encoding="utf-8")
            legacy_handoff.write_text("legacy baseline\n", encoding="utf-8")
            run_git(superproject, "add", "handoff", "docs/handoff")
            run_git(
                superproject,
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                str(child_source),
                "modules/child",
            )
            run_git(
                superproject,
                "-c",
                "user.name=AI Native DevKit Tests",
                "-c",
                "user.email=tests@example.invalid",
                "commit",
                "-am",
                "superproject fixture",
            )
            child = (superproject / "modules/child").resolve()
            inspector = RepositoryInspector()
            classification = inspector.classify(str(child))
            clean = inspector.inspect(classification).repository["superproject"][
                "revision"
            ]

            root_handoff.write_text("staged root secret\n", encoding="utf-8")
            run_git(superproject, "add", "handoff/private.md")
            legacy_handoff.write_text("unstaged legacy secret\n", encoding="utf-8")
            excluded = inspector.inspect(classification).repository["superproject"][
                "revision"
            ]

            self.assertEqual(excluded, clean)

            visible = superproject / "visible-tracked.txt"
            visible.write_text("visible version one\n", encoding="utf-8")
            run_git(superproject, "add", "visible-tracked.txt")
            first_visible = inspector.inspect(classification).repository[
                "superproject"
            ]["revision"]
            root_handoff.write_text("different root secret\n", encoding="utf-8")
            run_git(superproject, "add", "handoff/private.md")
            legacy_handoff.write_text("different legacy secret\n", encoding="utf-8")
            second_visible = inspector.inspect(classification).repository[
                "superproject"
            ]["revision"]

            self.assertTrue(first_visible["dirty"])
            self.assertEqual(
                first_visible["worktree_digest"],
                second_visible["worktree_digest"],
            )

            visible.write_text("visible version two\n", encoding="utf-8")
            third_visible = inspector.inspect(classification).repository[
                "superproject"
            ]["revision"]
            self.assertNotEqual(
                second_visible["worktree_digest"],
                third_visible["worktree_digest"],
            )


    def test_dirty_digest_distinguishes_index_state_hidden_by_worktree_reversal(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            readme = repository / "README.md"
            original = readme.read_text(encoding="utf-8")
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))

            readme.write_text("staged version one\n", encoding="utf-8")
            run_git(repository, "add", "README.md")
            readme.write_text(original, encoding="utf-8")
            first = inspector.inspect(classification).revision.worktree_digest

            readme.write_text("staged version two\n", encoding="utf-8")
            run_git(repository, "add", "README.md")
            readme.write_text(original, encoding="utf-8")
            second = inspector.inspect(classification).revision.worktree_digest

            self.assertNotEqual(first, second)

    def test_unborn_dirty_digest_covers_unstaged_change_to_staged_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "unborn"
            repository.mkdir()
            run_git(repository, "init", "-b", "main")
            tracked = repository / "tracked.txt"
            tracked.write_text("staged content\n", encoding="utf-8")
            run_git(repository, "add", "tracked.txt")
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))

            tracked.write_text("working version one\n", encoding="utf-8")
            first = inspector.inspect(classification).revision.worktree_digest
            tracked.write_text("working version two\n", encoding="utf-8")
            second = inspector.inspect(classification).revision.worktree_digest

            self.assertNotEqual(first, second)

    def test_selected_source_symlink_does_not_escape_repository_boundary(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository = temporary_root / "target"
            create_repository(repository)
            external = temporary_root / "outside-secret"
            external.write_text("external content\n", encoding="utf-8")
            (repository / "README.md").unlink()
            (repository / "README.md").symlink_to(external)
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))

            with self.assertRaises(RepositoryError) as raised:
                inspector.inspect(classification)

            self.assertEqual(
                raised.exception.code,
                "blocked.repository.source_outside_root",
            )

    def test_repository_location_git_environment_cannot_redirect_inspection(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository = temporary_root / "target"
            create_repository(repository)
            inspector = RepositoryInspector()

            with mock.patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(temporary_root / "missing-git-dir"),
                    "GIT_WORK_TREE": str(temporary_root / "wrong-worktree"),
                    "GIT_INDEX_FILE": str(temporary_root / "wrong-index"),
                },
                clear=False,
            ):
                classification = inspector.classify(str(repository))
                inspection = inspector.inspect(classification)

            self.assertEqual(classification.kind, "worktree")
            self.assertEqual(classification.root, str(repository.resolve()))
            self.assertEqual(inspection.repository["root"], str(repository.resolve()))

    def test_inspection_does_not_execute_repository_or_global_git_helpers(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository = temporary_root / "target"
            create_repository(repository)
            helper = temporary_root / "git-helper.sh"
            helper.write_text(
                "#!/bin/sh\n"
                "touch \"$1\"\n"
                "if [ -f \"$2\" ]; then cat \"$2\"; else cat; fi\n",
                encoding="utf-8",
            )
            helper.chmod(0o700)
            fsmonitor_marker = temporary_root / "fsmonitor-ran"
            repository_textconv_marker = temporary_root / "repository-textconv-ran"
            global_textconv_marker = temporary_root / "global-textconv-ran"
            filter_marker = temporary_root / "filter-ran"
            trace_marker = repository / "git-trace.log"
            run_git(
                repository,
                "config",
                "core.fsmonitor",
                f"{helper} {fsmonitor_marker}",
            )
            run_git(
                repository,
                "config",
                "diff.repository-helper.textconv",
                f"{helper} {repository_textconv_marker}",
            )
            run_git(
                repository,
                "config",
                "filter.malicious.clean",
                f"{helper} {filter_marker}",
            )
            global_config = temporary_root / "global-gitconfig"
            global_config.write_text(
                '[diff "global-helper"]\n'
                f"\ttextconv = {helper} {global_textconv_marker}\n",
                encoding="utf-8",
            )
            (repository / "README.md").write_text("# Changed\n", encoding="utf-8")
            (repository / "global-diff.txt").write_text(
                "changed\n",
                encoding="utf-8",
            )
            (repository / "filtered.txt").write_text("changed\n", encoding="utf-8")
            inspector = RepositoryInspector()

            with mock.patch.dict(
                os.environ,
                {
                    "GIT_CONFIG_GLOBAL": str(global_config),
                    "GIT_TRACE": str(trace_marker),
                },
                clear=False,
            ):
                classification = inspector.classify(str(repository))
                inspection = inspector.inspect(classification)

            self.assertTrue(inspection.revision.dirty)
            self.assertFalse(fsmonitor_marker.exists())
            self.assertFalse(repository_textconv_marker.exists())
            self.assertFalse(global_textconv_marker.exists())
            self.assertFalse(filter_marker.exists())
            self.assertFalse(trace_marker.exists())

    def test_inspection_blocks_when_revision_changes_while_sources_are_read(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            first_head = run_git(repository, "rev-parse", "HEAD")
            run_git(
                repository,
                "-c",
                "user.name=AI Native DevKit Tests",
                "-c",
                "user.email=tests@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "concurrent revision",
            )
            second_head = run_git(repository, "rev-parse", "HEAD")
            run_git(repository, "reset", "--hard", first_head)
            canonical_repository = repository.resolve()
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))
            original_read_source = inspector._read_selected_source
            changed = False

            def read_source_and_advance_head(root, relative_path):
                nonlocal changed
                content = original_read_source(root, relative_path)
                if (
                    root == canonical_repository
                    and relative_path == "README.md"
                    and not changed
                ):
                    run_git(repository, "update-ref", "HEAD", second_head)
                    changed = True
                return content

            with mock.patch.object(
                inspector,
                "_read_selected_source",
                side_effect=read_source_and_advance_head,
            ):
                with self.assertRaises(RepositoryError) as raised:
                    inspector.inspect(classification)

            self.assertTrue(changed)
            self.assertEqual(
                raised.exception.code,
                "blocked.repository.changed_during_inspection",
            )
            self.assertTrue(raised.exception.retryable)
            self.assertIsNone(raised.exception.observation)

    def test_different_instruction_files_in_one_directory_are_a_source_conflict(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            (repository / "AGENTS.md").write_text("# Instructions\nAlways run tests.\n", encoding="utf-8")
            (repository / "CLAUDE.md").write_text(
                "# Instructions\nNever run tests.\n",
                encoding="utf-8",
            )
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))

            with self.assertRaises(RepositoryError) as raised:
                inspector.inspect(classification)

            self.assertEqual(
                raised.exception.code,
                "blocked.repository.source_conflict",
            )
            observation = raised.exception.observation
            self.assertIsNotNone(observation)
            self.assertEqual(observation.revision.head, run_git(repository, "rev-parse", "HEAD"))
            self.assertEqual(
                observation.findings["repository_instructions"],
                ["AGENTS.md", "CLAUDE.md"],
            )
            self.assertTrue(all(source["hash"].startswith("sha256:") for source in observation.sources))

    def test_identical_instruction_files_in_one_directory_are_both_selected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            (repository / "CLAUDE.md").write_text(
                "# Instructions\n",
                encoding="utf-8",
            )
            inspector = RepositoryInspector()
            classification = inspector.classify(str(repository))

            inspection = inspector.inspect(classification)

            self.assertEqual(
                inspection.findings["repository_instructions"],
                ["AGENTS.md", "CLAUDE.md"],
            )

    def test_different_instruction_files_at_different_layers_do_not_conflict(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory) / "target"
            create_repository(repository)
            scope = repository / "service"
            scope.mkdir()
            (scope / "CLAUDE.md").write_text(
                "# Service-specific instructions\n",
                encoding="utf-8",
            )
            inspector = RepositoryInspector()
            classification = inspector.classify(str(scope))

            inspection = inspector.inspect(classification)

            self.assertEqual(
                inspection.findings["repository_instructions"],
                ["AGENTS.md", "service/CLAUDE.md"],
            )


if __name__ == "__main__":
    unittest.main()
