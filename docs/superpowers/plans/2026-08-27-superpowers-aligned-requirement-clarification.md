# Superpowers-Aligned Requirement Clarification Implementation Plan

**Status:** Implemented in 0.4.0 and repository-verified on 2026-08-28.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace DevKit's checkpoint-based clarification baseline with Superpowers-aligned requirement discovery, a minimal committed requirements document, and approval bound to its exact Git identity.

**Architecture:** `$coding-sop` remains the only workflow owner. `$sop-clarify` performs the interview, `RequirementDocumentWriter` and `RequirementDocumentLoader` own the Git artifact boundary, and the existing runtime trace owns later-turn approval. `$sop-design` loads only an exact approved `RequirementDocRef`; TaskStateStore no longer owns clarification state.

**Tech Stack:** Python 3.9+ standard library, capability-checked Git CLI, append-only Execution Trace, Agent Skills Markdown, `unittest`, Codex Skill and plugin validators.

**Spec:** `docs/superpowers/specs/2026-08-27-superpowers-aligned-requirement-clarification-design.md`

## Global Constraints

- Implement this breaking pre-1.0 contract as plugin version `0.4.0`; do not install, reinstall, publish, or mutate a cached plugin.
- Add no repository-wide Git version floor. Before writing, probe the exact object-format and absolute-common-directory capabilities used by the Writer and fail typed before mutation when they are unavailable; real SHA-1/SHA-256 and native path-limited-commit tests lock the required behavior without rejecting a capable backport by version string.
- Keep `ai-native-devkit` as the plugin and Marketplace identity and keep `$coding-sop` as the single top-level orchestrator.
- Reuse the agreed Superpowers `6.3.0` `Understanding the idea` wording verbatim wherever DevKit semantics do not require an adaptation, but add no runtime dependency on Superpowers.
- Do not create a clarification checkpoint, structured task artifact, dedicated interview transcript, or repository file before the clarification interview is complete. Automatic Execution Trace collection remains active.
- A requirements document contains only a title, `Clarified Requirements`, and an optional `Sources` section. It contains no design, architecture, interfaces, test plan, implementation plan, risk plan, transcript, or blocking question.
- `RequirementDocRef` has exactly three required core fields: `path`, `commit`, and `blob_digest`. Use `git-sha1:<40 lowercase hex>` or `git-sha256:<64 lowercase hex>` for `blob_digest`; preserve compatible unknown JSON fields for forward compatibility.
- Bind runtime approval through `sha256(canonical_json_bytes(RequirementDocRef.to_dict()))`, including preserved extension fields. Trace stores this subject digest and kind, not requirement prose or source contents.
- Implement the approved spec's later-task handoff narrowly: when a later task explicitly supplies one exact `RequirementDocRef`, a completed approval may be found in a validated Codex-session Trace only for the same repository identity and exact current subject. This is neither incomplete-interview recovery nor a general approval-lifecycle or revocation system; pending, rejected, and changes-requested attempts are never approval evidence.
- Repository sources are checked automatically against their recorded revision. `$sop-design` re-reads external sources and compares their version or sync time because the runtime has no external-source adapter.
- Preserve unrelated staged, unstaged, and untracked work. Never use stash, reset, checkout, amend, destructive recovery, or history rewriting.
- Leave existing external TaskStateStore files untouched. They are neither migrated nor deleted; old clarification artifact types and operations simply become unsupported.
- Preserve compatible unknown fields on existing extensible/persisted contracts and on `RequirementDocRef`, while the new bounded CLI envelope and `RequirementSource` input use explicit field allow-lists. Preserve the remaining Init/Trace/Docs Hook/Handoff contracts while rejecting malformed core fields and invalid transitions.
- Every implementation task is test-first, ends with focused verification, and produces an independently reviewable commit.
- This plan, its approved spec, and their `docs/superpowers/README.md` index rows are committed execution inputs before Task 1 starts; later documentation commits may update their status without ever creating a dangling link to an untracked plan.

---

## Frozen Public Interfaces

```text
RequirementDocRef
  path: str
  commit: str
  blob_digest: str
  extra: Mapping[str, Any]  # recursively immutable extension JSON
  to_dict() -> Dict[str, Any]
  from_dict(value: Any) -> RequirementDocRef
  subject_digest() -> str
```

```text
@dataclass(frozen=True)
class RequirementSource:
    kind: str       # repository | external
    locator: str    # repository-relative path | stable URL/resource ID
    version: str    # full Git OID | external version/sync time
    supports: str   # short statement naming the supported requirement or fact
    from_dict(value: Any) -> RequirementSource
    to_dict() -> Dict[str, str]
```

```text
RequirementDocumentWriter(
  today: Callable[[], date] = date.today,
)

RequirementDocumentWriter.write_and_commit(
  *,
  repository_root: Path,
  title: str,
  clarified_requirements: str,
  sources: Sequence[RequirementSource] = (),
  supersedes: Optional[RequirementDocRef] = None,
) -> RequirementDocRef
```

```text
RequirementDocumentLoader.verify_current(
  *,
  repository_root: Path,
  reference: RequirementDocRef,
) -> str

RequirementDocumentLoader.load_approved(
  *,
  trace_store: ExecutionTraceStore,
  repository_root: Path,
  reference: RequirementDocRef,
  enforce_repository_source_freshness: bool = True,
) -> str
```

```text
RequirementApprovalAttempt
  trace_id: str
  repository_digest: str
  stage_run_id: str
  approval_id: str
  subject_digest: str
  requested_at: str
  request_seq: int
  request_turn_id: Optional[str]
  decision: Optional[str]
  resolved_at: Optional[str]
  resolution_turn_id: Optional[str]
  later_user_turn: bool
  terminal: bool

RequirementApprovalGate.project(
  records: Iterable[Dict[str, Any]],
) -> List[RequirementApprovalAttempt]

RequirementApprovalGate.require_later_user_turn(
  *,
  events: Sequence[Dict[str, Any]],
  request_event: Dict[str, Any],
) -> str

RequirementApprovalGate.require_approved(
  *,
  trace_store: ExecutionTraceStore,
  repository_root: Path,
  reference: RequirementDocRef,
) -> RequirementApprovalAttempt

RequirementApprovalGate.require_subject_approved(
  *,
  trace_store: ExecutionTraceStore,
  repository_digest_value: str,
  subject_digest: str,
  approval_id: Optional[str] = None,
) -> RequirementApprovalAttempt

ExecutionTraceStore.iter_records() -> Iterator[Dict[str, Any]]
```

`iter_records` is a narrow read projection over the existing Trace store: it enumerates atomically published `.sessions` mappings and uses the existing per-session lock to return coherent detached records. This plan does not replace the Trace root/storage lifecycle; descriptor-anchored root hardening remains a separate infrastructure concern outside the approved Clarify/Design slice.

The packaged `scripts/workflow_cli.py` remains the artifact boundary, but its operation set becomes exactly:

```text
requirements.write
requirements.load
```

The existing `scripts/runtime_cli.py` continues to own stage lifecycle and approval. Clarification uses `approval_kind: clarify.requirements` and the sequence:

```text
stage.start(clarify)
-> interview
-> requirements.write
-> approval.request(exact RequirementDocRef)
-> later user turn
-> approval.resolve
-> stage.complete(clarify, exact RequirementDocRef)
-> requirements.load
-> stage.start(design)
```

For an explicitly supplied, already approved reference in a later Codex session, `$coding-sop` uses the completed boundary without replaying the interview:

```text
stage.start(clarify)
-> stage.complete(clarify, exact RequirementDocRef; runtime imports exact completed approval)
-> requirements.load(purpose: design)
-> stage.start(design)
```

This is the minimum cross-session behavior needed by the approved spec's “later task” rule. It is not incomplete-interview recovery and creates no reconstructed baseline; it only materializes the explicitly referenced, already completed exact approval into the new workflow's ordered Trace.

## File Map

**Create:**

- `plugins/ai-native-devkit/scripts/ai_native_devkit/requirement_document.py`
- `plugins/ai-native-devkit/scripts/ai_native_devkit/requirement_approval.py`
- `plugins/ai-native-devkit/skills/sop-clarify/references/upstream-superpowers-brainstorming.md`
- `tests/modules/test_requirement_document.py`
- `tests/modules/test_requirement_approval.py`
- `docs/decisions/0006-git-versioned-requirements-handoff.md`

**Delete:**

- `plugins/ai-native-devkit/scripts/ai_native_devkit/clarification.py`
- `tests/modules/test_clarification_runtime.py`
- `tests/clarification_fixtures.py` after moving its Init-only helpers

**Replace in place:**

- `plugins/ai-native-devkit/scripts/ai_native_devkit/workflow_cli.py`
- `tests/integration/test_workflow_cli.py`

**Modify runtime and contracts:**

- `plugins/ai-native-devkit/scripts/ai_native_devkit/contracts.py`
- `plugins/ai-native-devkit/scripts/ai_native_devkit/errors.py`
- `plugins/ai-native-devkit/scripts/ai_native_devkit/runtime_cli.py`
- `plugins/ai-native-devkit/scripts/ai_native_devkit/execution_trace.py`
- `plugins/ai-native-devkit/scripts/ai_native_devkit/state_store.py`
- `plugins/ai-native-devkit/scripts/ai_native_devkit/__init__.py`
- `plugins/ai-native-devkit/.codex-plugin/plugin.json`

**Modify Skills and provenance:**

- `plugins/ai-native-devkit/skills/sop-clarify/SKILL.md`
- `plugins/ai-native-devkit/skills/sop-design/SKILL.md`
- `plugins/ai-native-devkit/skills/sop-sync-docs/SKILL.md`
- `plugins/ai-native-devkit/skills/sop-init/SKILL.md`
- `plugins/ai-native-devkit/skills/sop-init/references/init-contract.md`
- `plugins/ai-native-devkit/skills/coding-sop/SKILL.md`
- `plugins/ai-native-devkit/skills/coding-sop/references/workflow-contract.md`
- `plugins/ai-native-devkit/skills/coding-sop/references/execution-trace.md`
- `THIRD_PARTY_NOTICES.md`
- `plugins/ai-native-devkit/THIRD_PARTY_NOTICES.md`

**Modify project-doc templates and promotion:**

- `plugins/ai-native-devkit/skills/sop-init/assets/AGENTS.md`
- `plugins/ai-native-devkit/skills/sop-init/assets/docs-template/superpowers/README.md`
- `plugins/ai-native-devkit/skills/sop-init/assets/docs-template/decisions/README.md`
- `plugins/ai-native-devkit/skills/sop-init/scripts/validate_project_docs.py`
- `plugins/ai-native-devkit/skills/sop-sync-docs/scripts/validate_promoted_decision.py`
- `tests/fixtures/standard-project/docs/superpowers/README.md`
- `tests/fixtures/standard-project/docs/decisions/README.md`

**Modify tests:**

- `tests/contract/test_contracts.py`
- `tests/contract/test_task_state_store.py`
- `tests/modules/test_cli_preflight.py`
- `tests/modules/test_execution_trace.py`
- `tests/integration/test_runtime_trace_and_docs_hook.py`
- `tests/integration/test_trace_collector_cli.py`
- `tests/test_plugin_contract.py`
- `tests/test_skill_contract.py`
- `tests/test_development_skills.py`
- `tests/test_decision_promotion.py`
- `tests/test_docs_template.py`
- `tests/test_end_to_end_contract.py`

**Modify canonical documentation:**

- `AGENTS.md`
- `README.md`
- `plugins/ai-native-devkit/README.md`
- `docs/README.md`
- `docs/product-and-scope.md`
- `docs/方案总览.md`
- `docs/architecture.md`
- `docs/contracts.md`
- `docs/workflow.md`
- `docs/context-and-docs.md`
- `docs/roadmap-and-validation.md`
- `docs/skill-selection.md`
- `docs/evaluation-evidence.md`
- `docs/decisions/0002-task-artifacts-and-doc-promotion.md`
- `docs/decisions/0004-task-state-store-interface.md`
- `docs/decisions/0005-persist-and-promote-clarification-results.md`
- `docs/decisions/README.md`
- `docs/superpowers/README.md`

---

### Task 1: Add the Git requirement contract and safe writer

**Files:**

- Create: `plugins/ai-native-devkit/scripts/ai_native_devkit/requirement_document.py`
- Create: `tests/modules/test_requirement_document.py`
- Modify: `plugins/ai-native-devkit/scripts/ai_native_devkit/contracts.py`
- Modify: `plugins/ai-native-devkit/scripts/ai_native_devkit/errors.py`
- Modify: `tests/contract/test_contracts.py`

**Interfaces:**

- Consumes: `canonical_json_bytes(value: Any) -> bytes` and `sha256_digest(value: bytes) -> str` from `contracts.py`; a non-bare Git worktree; optional `RequirementSource` values.
- Produces: `RequirementDocRef.from_dict(value: Any) -> RequirementDocRef`, `RequirementDocRef.to_dict() -> Dict[str, Any]`, and `RequirementDocRef.subject_digest() -> str`.
- Produces: `RequirementSource.from_dict(value: Any) -> RequirementSource` and `RequirementSource.to_dict() -> Dict[str, str]` for the JSON/Writer boundary.
- Produces: `RequirementDocumentWriter(today: Callable[[], date] = date.today).write_and_commit(*, repository_root: Path, title: str, clarified_requirements: str, sources: Sequence[RequirementSource] = (), supersedes: Optional[RequirementDocRef] = None) -> RequirementDocRef`.
- Produces inside `requirement_document.py`: `_verify_current_document(*, repository_root: Path, reference: RequirementDocRef) -> bytes`, shared by revision writes and Task 4's public Loader.
- Produces: deterministic minimal Markdown and one exact Git commit without disturbing unrelated user work; initial writes never overwrite, while revisions require one exact prior reference.

- [x] **Step 1: Write failing `RequirementDocRef` contract tests**

Add these cases to `tests/contract/test_contracts.py`:

```python
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
```

- [x] **Step 2: Add the provided Writer fixture and failing test module**

Coverage in the concrete methods below is: minimal shape; source rendering and injection; non-ASCII slugging and collisions; dirty-index preservation; exact commit diff; revision history; repository/symlink/identity failures; native path-limited commit behavior; concurrent Writers and external-Git conflict detection; bounded runner/post-ref reconciliation; unborn repositories; and content filters. These are coverage labels inside one test-module edit, not empty independent steps.

Create `tests/modules/test_requirement_document.py` with this exact fixture and method bodies:

```python
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
        )

    def committed(self, reference):
        return self.git("show", f"{reference.commit}:{reference.path}").stdout.decode()

    def test_writer_commits_exact_minimal_document_and_returns_git_identity(self):
        reference = self.write()
        self.assertEqual(
            self.committed(reference),
            "# Login Policy\n\n## Clarified Requirements\n\n"
            "Only administrators may revoke active sessions.\n",
        )
        self.assertRegex(reference.commit, r"^[0-9a-f]{40}$")
        self.assertRegex(reference.blob_digest, r"^git-sha1:[0-9a-f]{40}$")

    def test_writer_omits_sources_section_when_sources_are_empty(self):
        self.assertNotIn("## Sources", self.committed(self.write()))

    def test_writer_rejects_document_over_byte_limit_before_writing(self):
        prefix = "# Login Policy\n\n## Clarified Requirements\n\n"
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
        self.assertIn("- Repository: `seed.txt` at `", content)
        self.assertIn("- External: `https://example.test/policy` at `v2`", content)
        self.assertIn("- External: `cooper_doc_123` at `sync-2026-08-27`", content)

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
```

- [x] **Step 3: Run the focused tests and verify the red state**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.contract.test_contracts \
  tests.modules.test_requirement_document -v
```

Expected: import failures for `RequirementDocRef` and `requirement_document`.

- [x] **Step 4: Implement the exact reference contract**

Add to `contracts.py` without adding either type to `ARTIFACT_TYPES`; import `json`, `Mapping` from `typing`, and `MappingProxyType` from `types` so extension identity is detached and recursively immutable:

```python
REQUIREMENT_PATH = re.compile(
    r"^docs/superpowers/requirements/"
    r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*-requirements(?:-\d+)?\.md$"
)

def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value

def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value

@dataclass(frozen=True)
class RequirementDocRef:
    path: str
    commit: str
    blob_digest: str
    extra: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not REQUIREMENT_PATH.fullmatch(self.path):
            raise ContractError("Requirement document path is invalid.")
        if not isinstance(self.commit, str) or not re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.commit
        ):
            raise ContractError("Requirement document commit is invalid.")
        expected = "git-sha1:" if len(self.commit) == 40 else "git-sha256:"
        oid_length = 40 if expected == "git-sha1:" else 64
        if not isinstance(self.blob_digest, str) or not re.fullmatch(
            re.escape(expected) + rf"[0-9a-f]{{{oid_length}}}", self.blob_digest
        ):
            raise ContractError("Requirement document blob digest is invalid.")
        if not isinstance(self.extra, Mapping) or any(
            not isinstance(key, str) or key in {"path", "commit", "blob_digest"}
            for key in self.extra
        ):
            raise ContractError("Requirement document extensions are invalid.")
        canonical_extra = canonical_json_bytes(_thaw_json(self.extra))
        if len(canonical_extra) > 16 * 1024:
            raise ContractError("Requirement document extensions are too large.")
        detached = json.loads(canonical_extra.decode("utf-8"))
        object.__setattr__(self, "extra", _freeze_json(detached))

    def to_dict(self) -> Dict[str, Any]:
        value = _thaw_json(self.extra)
        value.update({
            "path": self.path,
            "commit": self.commit,
            "blob_digest": self.blob_digest,
        })
        return value

    @classmethod
    def from_dict(cls, value: Any) -> "RequirementDocRef":
        required = {"path", "commit", "blob_digest"}
        if not isinstance(value, dict) or not required.issubset(value):
            raise ContractError("Requirement document reference is invalid.")
        if any(not isinstance(key, str) for key in value):
            raise ContractError("Requirement document extension keys are invalid.")
        extra = {key: item for key, item in value.items() if key not in required}
        return cls(value["path"], value["commit"], value["blob_digest"], extra)

    def subject_digest(self) -> str:
        return sha256_digest(canonical_json_bytes(self.to_dict()))
```

- [x] **Step 5: Implement requirement-source validation and Markdown rendering**

The code block below contains the document error/source value, token and locator validators, deterministic slug, and minimal renderer as one cohesive module edit.

Add `RequirementDocumentError` and `RequirementApprovalError` to `errors.py`. In `requirement_document.py`, add `RequirementSource`, fixed-root path validation, slug generation, and optional source rendering. Build the topic slug by NFKD-normalizing the title, dropping non-ASCII code points, lowercasing, replacing non-alphanumeric runs with `-`, and trimming separators. If that is empty, use `topic-` plus the first 12 lowercase hex characters of SHA-256 over the UTF-8 title. Render sources in this stable human-readable form:

```markdown
## Sources

- Repository: `src/policy.py` at `0123456789abcdef0123456789abcdef01234567` — supports the current policy behavior.
- External: `https://example.test/policy` at `v2` — supports the required policy version.
```

Use these concrete validators and renderer. Preserve a stable opaque resource ID exactly as supplied; HTTPS URLs and `resource://` URIs receive additional structural validation, while an opaque ID uses the bounded single-token grammar below:

```python
class RequirementDocumentError(AiNativeDevError):
    pass

class RequirementApprovalError(AiNativeDevError):
    pass

@dataclass(frozen=True)
class RequirementSource:
    kind: str
    locator: str
    version: str
    supports: str

    @classmethod
    def from_dict(cls, value: Any) -> "RequirementSource":
        fields = {"kind", "locator", "version", "supports"}
        if not isinstance(value, dict) or set(value) != fields:
            raise RequirementDocumentError(
                "requirements.source_invalid", "Requirement source is invalid."
            )
        return _validated_source(cls(**{field: value[field] for field in fields}))

    def to_dict(self) -> Dict[str, str]:
        return {
            "kind": self.kind, "locator": self.locator,
            "version": self.version, "supports": self.supports,
        }

def _source_token(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "`" in value
        or len(value.splitlines()) != 1
        or any(
            unicodedata.category(character) in {"Cc", "Zl", "Zp"}
            for character in value
        )
    ):
        raise RequirementDocumentError(
            "requirements.source_invalid", f"Source {field_name} is invalid."
        )
    return value

def _validated_external_locator(value: str) -> str:
    value = _source_token(value, "locator")
    if len(value.encode("utf-8")) > 2048:
        raise RequirementDocumentError(
            "requirements.source_invalid", "External source locator is too long."
        )
    if value.startswith(("https://", "resource://")):
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
        except ValueError as error:
            raise RequirementDocumentError(
                "requirements.source_invalid", "External source locator is invalid."
            ) from error
        https = (
            parsed.scheme == "https"
            and hostname is not None
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
        resource = (
            parsed.scheme == "resource"
            and bool(parsed.netloc)
            and parsed.path not in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )
        if not (https or resource):
            raise RequirementDocumentError(
                "requirements.source_invalid",
                "External source URL or resource URI is invalid.",
            )
    elif "://" in value or re.fullmatch(r"[\w][\w.:/@+\-]{0,2047}", value) is None:
        raise RequirementDocumentError(
            "requirements.source_invalid", "Opaque resource ID is invalid."
        )
    return value

def _validated_source(source: RequirementSource) -> RequirementSource:
    if source.kind == "repository":
        locator = _source_token(source.locator, "locator")
        path = PurePosixPath(locator)
        if path.is_absolute() or path.as_posix() != locator or ".." in path.parts:
            raise RequirementDocumentError(
                "requirements.source_invalid", "Repository source path is invalid."
            )
        if not isinstance(source.version, str) or not re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source.version
        ):
            raise RequirementDocumentError(
                "requirements.source_invalid", "Repository source revision is invalid."
            )
    elif source.kind == "external":
        _validated_external_locator(source.locator)
        _source_token(source.version, "version")
    else:
        raise RequirementDocumentError(
            "requirements.source_invalid", "Requirement source kind is invalid."
        )
    _source_token(source.supports, "supports")
    return source

def _render_document(
    title: str,
    clarified_requirements: str,
    sources: Sequence[RequirementSource],
) -> bytes:
    if isinstance(sources, (str, bytes)):
        raise RequirementDocumentError(
            "requirements.source_invalid", "Sources must be a bounded sequence."
        )
    try:
        source_count = len(sources)
    except TypeError as error:
        raise RequirementDocumentError(
            "requirements.source_invalid", "Sources must be a bounded sequence."
        ) from error
    if source_count > MAX_REQUIREMENT_SOURCES:
        raise RequirementDocumentError(
            "requirements.source_invalid", "At most 64 sources may be recorded."
        )
    title = " ".join(title.split())
    requirements = clarified_requirements.strip()
    if not title or not requirements or re.search(r"(?m)^#{1,6}\s", requirements):
        raise RequirementDocumentError(
            "requirements.document_invalid",
            "Requirements need a title and prose without additional headings.",
        )
    lines = [f"# {title}", "", "## Clarified Requirements", "", requirements]
    if sources:
        lines.extend(["", "## Sources", ""])
        for source in map(_validated_source, sources):
            label = "Repository" if source.kind == "repository" else "External"
            lines.append(
                f"- {label}: `{source.locator}` at `{source.version}` — {source.supports}"
            )
    rendered = ("\n".join(lines) + "\n").encode("utf-8")
    if len(rendered) > MAX_REQUIREMENT_DOCUMENT_BYTES:
        raise RequirementDocumentError(
            "requirements.document_too_large", "Requirements document is too large."
        )
    return rendered
```

Define `MAX_REQUIREMENT_DOCUMENT_BYTES = 256 * 1024` and `MAX_REQUIREMENT_SOURCES = 64` once in `requirement_document.py`. Writer enforces both on the typed input and fully rendered UTF-8 bytes before path selection, filesystem creation, object writes, or `HEAD` movement. Loader enforces the same source count while parsing and passes the byte constant to the descriptor-anchored regular-file reader; boundary tests prove exact-limit success and limit-plus-one rejection with unchanged repository state.

Repository locators must be canonical `PurePosixPath` values without an absolute root, `..`, backticks, control characters, C1 controls, or Unicode line/paragraph separators. Repository versions are full 40/64-character lowercase Git OIDs. Pass external versions and every `supports` value through `_source_token`; this makes every Writer output parseable by Task 4's `SOURCE_LINE`/`splitlines` grammar. Add unit cases for invalid kind, HTTP (not HTTPS), malformed bracketed hosts, path escape, wrong repository OID, and every ASCII/Unicode line-injection case. Each invalid value must fail before file creation or `HEAD` movement. Do not add `Sources` when the sequence is empty.

- [x] **Step 6a: Implement the bounded sanitized Git runner and repository preflight**

The code below resolves trusted Git, sanitizes its environment, returns typed status/timeout/output-cap results, and performs exact-root/non-bare/identity preflight.

Import `contextmanager`, `date`, `fcntl`, `hashlib`, `os`, `re`, `selectors`, `secrets`, `shutil`, `signal`, `stat`, `subprocess`, `time`, `unicodedata`, `urlsplit`, and the required `dataclasses`, `pathlib`, and `typing` names explicitly; do not use shell command strings.

Use one argv-only runner for every Git call. Resolve the Git executable itself from `os.defpath`, clear authority-changing `GIT_*` variables, force `GIT_NO_REPLACE_OBJECTS=1` and `GIT_GRAFT_FILE=/dev/null` so fixed OIDs retain raw object meaning, but preserve the caller's `PATH` for repository hooks and configured signing helpers (falling back to `os.defpath` only when `PATH` is absent):

```python
_GIT_ENV_KEYS = {
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_EXEC_PATH", "GIT_NAMESPACE", "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE",
    "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS",
    "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS",
    "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS",
}
MAX_GIT_CAPTURE_BYTES = 1024 * 1024
MAX_REPOSITORY_PROJECTION_BYTES = 64 * 1024 * 1024

@dataclass(frozen=True)
class _GitResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_exceeded: bool = False
    started: bool = True

def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

def _git_result(
    root: Path, *arguments: str, input_bytes: Optional[bytes] = None,
    timeout: float = 30, output_limit: int = MAX_GIT_CAPTURE_BYTES,
) -> _GitResult:
    candidate = shutil.which("git", path=os.defpath)
    if candidate is None:
        raise RequirementDocumentError(
            "requirements.repository_unsupported", "Git is unavailable."
        )
    try:
        executable = Path(candidate).resolve(strict=True)
    except OSError as error:
        raise RequirementDocumentError(
            "requirements.repository_unsupported", "Git is unavailable."
        ) from error
    environment = os.environ.copy()
    for key in list(environment):
        if key in _GIT_ENV_KEYS or key.startswith(
            ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
        ):
            environment.pop(key)
    # Exact requirement identities are raw object identities. Do not let
    # replace refs or legacy grafts reinterpret a fixed commit OID.
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_GRAFT_FILE"] = os.devnull
    environment["LC_ALL"] = "C"
    environment.setdefault("PATH", os.defpath)
    process = None
    try:
        process = subprocess.Popen(
            [str(executable), *arguments], cwd=root, env=environment,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        if input_bytes is not None:
            assert process.stdin is not None
            try:
                process.stdin.write(input_bytes)
            except BrokenPipeError:
                pass
            finally:
                process.stdin.close()
        streams = {process.stdout: bytearray(), process.stderr: bytearray()}
        selector = selectors.DefaultSelector()
        for stream in streams:
            assert stream is not None
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        timed_out = False
        output_exceeded = False
        terminated = False
        draining = False
        drain_deadline = None
        while selector.get_map():
            now = time.monotonic()
            remaining = deadline - now
            if not draining and process.poll() is not None:
                # A detached hook child may retain inherited pipes after Git exits.
                draining = True
                drain_deadline = now + 1.0
            if remaining <= 0 and not terminated and process.poll() is None:
                timed_out = True
                _kill_process_group(process)
                terminated = True
                draining = True
                drain_deadline = now + 1.0
            if draining and drain_deadline is not None and now >= drain_deadline:
                for key in list(selector.get_map().values()):
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                break
            wait_for = (
                min(max(drain_deadline - now, 0.0), 0.05)
                if draining and drain_deadline is not None
                else min(max(remaining, 0.0), 0.05)
            )
            for key, _ in selector.select(wait_for):
                try:
                    chunk = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                used = sum(len(value) for value in streams.values())
                room = max(0, output_limit - used)
                streams[key.fileobj].extend(chunk[:room])
                if len(chunk) > room:
                    output_exceeded = True
                    if process.poll() is None and not terminated:
                        _kill_process_group(process)
                        terminated = True
                    if not draining:
                        draining = True
                        drain_deadline = time.monotonic() + 1.0
        selector.close()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            process.wait(timeout=1.0)
        return _GitResult(
            process.returncode,
            bytes(streams[process.stdout]),
            bytes(streams[process.stderr]),
            timed_out,
            output_exceeded,
            True,
        )
    except OSError as error:
        started = process is not None
        if started and process.poll() is None:
            _kill_process_group(process)
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        return _GitResult(
            process.returncode if started and process.returncode is not None else 127,
            b"", str(error).encode("utf-8", "replace")[:1000],
            timed_out=started, output_exceeded=False, started=started,
        )

def _git(
    root: Path, *arguments: str, input_bytes: Optional[bytes] = None,
    timeout: float = 30, output_limit: int = MAX_GIT_CAPTURE_BYTES,
) -> bytes:
    result = _git_result(
        root, *arguments, input_bytes=input_bytes,
        timeout=timeout, output_limit=output_limit,
    )
    if result.timed_out or result.output_exceeded or result.returncode:
        raise RequirementDocumentError(
            "requirements.git_failed",
            (result.stderr or b"Git operation failed.").decode("utf-8", "replace")[:1000],
        )
    return result.stdout

def _require_supported_git(root: Path) -> None:
    try:
        object_format = _git(
            root, "rev-parse", "--show-object-format"
        ).decode("ascii", "strict").strip()
        common_dir = Path(
            _git(
                root, "rev-parse", "--path-format=absolute", "--git-common-dir"
            ).decode("utf-8", "strict").strip()
        )
    except (RequirementDocumentError, UnicodeDecodeError) as error:
        raise RequirementDocumentError(
            "requirements.repository_unsupported",
            "Required Git capabilities are unavailable.",
        ) from error
    if object_format not in {"sha1", "sha256"} or not common_dir.is_absolute():
        raise RequirementDocumentError(
            "requirements.repository_unsupported",
            "Repository object format or common directory is unsupported.",
        )
```

Use `_git_result` only where a specific nonzero status is expected, such as an unborn `HEAD`, an absent `HEAD:<path>`, a clean/dirty status probe, or the native `git commit` whose ref-moving outcome must be reconciled. It always returns typed timeout/output-cap outcomes rather than raising before the caller can re-read `HEAD`. `_git` treats either flag and every unexpected nonzero result as an error. Confirm that the caller's repository is the exact top-level non-bare worktree, then require `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT` to succeed.

- [x] **Step 6b: Anchor requirement filesystem operations to directory descriptors**

Open the already validated repository root with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC`, retain its `(st_dev, st_ino)`, and walk `docs`, `superpowers`, and `requirements` one component at a time with `os.open(..., dir_fd=parent_fd, O_DIRECTORY | O_NOFOLLOW)`; create a missing component with `os.mkdir(..., dir_fd=parent_fd)` and immediately reopen it without following links. Retain the final requirements-directory descriptor and identity. Implement initial `stat/open/unlink`, revision `open/temp/replace`, and directory `fsync` only through `dir_fd`/`src_dir_fd`/`dst_dir_fd`; no later Writer filesystem operation reopens `repository_root / relative_path`. `read_regular_snapshot(name, limit)` returns both bytes and `(st_dev, st_ino, st_mode, st_size, st_mtime_ns, st_ctime_ns)` from the same open descriptor so Loader can repeat and compare the read at the end of a stable snapshot. Fail closed with `requirements.repository_unsupported` if the platform lacks the required descriptor-relative or no-follow primitives.

Immediately before the first ref-moving command and again before returning a reference, reopen the logical repository root and requirements chain by the same no-follow walk and compare every retained directory identity. A rename/symlink swap before `HEAD` moves is `requirements.path_unsafe` after the owned pre-ref rollback; a mismatch after `HEAD` may have moved is `requirements.commit_indeterminate` and returns no reference. Add `test_writer_fails_closed_when_requirements_ancestor_is_swapped_during_write`: pause after the target bytes are fsynced, rename `docs/superpowers`, replace it with a symlink to an outside directory, then release. Assert the outside directory is untouched, `HEAD` is unchanged, and no reference is returned.

Use this concrete descriptor owner (the implementation may factor `_write_all`, but must preserve the same calls and checks):

```python
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC

def _identity(value: os.stat_result) -> Tuple[int, int, int]:
    return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode)

def _file_snapshot_identity(
    value: os.stat_result,
) -> Tuple[int, int, int, int, int, int]:
    return (
        value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode),
        value.st_size, value.st_mtime_ns, value.st_ctime_ns,
    )

def _write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise RequirementDocumentError(
                "requirements.repository_unsupported", "File write did not progress."
            )
        view = view[written:]

def _validated_repository_root(
    repository_root: Path, *, require_identity: bool = False
) -> Path:
    if not isinstance(repository_root, Path) or not repository_root.is_absolute():
        raise RequirementDocumentError(
            "requirements.repository_invalid", "Repository root must be absolute."
        )
    try:
        root = repository_root.resolve(strict=True)
    except OSError as error:
        raise RequirementDocumentError(
            "requirements.repository_invalid", "Repository root does not exist."
        ) from error
    _require_supported_git(root)
    top = Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve(
        strict=True
    )
    if root != top or _git(root, "rev-parse", "--is-bare-repository").strip() != b"false":
        raise RequirementDocumentError(
            "requirements.repository_invalid",
            "Repository root must be the exact top-level non-bare worktree.",
        )
    if _git(root, "rev-parse", "--show-object-format").strip() not in {b"sha1", b"sha256"}:
        raise RequirementDocumentError(
            "requirements.repository_unsupported", "Git object format is unsupported."
        )
    if require_identity:
        try:
            _git(root, "var", "GIT_AUTHOR_IDENT")
            _git(root, "var", "GIT_COMMITTER_IDENT")
        except RequirementDocumentError as error:
            raise RequirementDocumentError(
                "requirements.git_identity_missing",
                "Git author/committer identity is missing.",
            ) from error
    return root

@dataclass(frozen=True)
class _InstalledDocument:
    filename: str
    identity: Tuple[int, int, int, int, int, int]
    rendered: bytes
    previous_bytes: Optional[bytes]

class _RequirementDirectory:
    _COMPONENTS = ("docs", "superpowers", "requirements")

    def __init__(
        self, root: Path, fd: int, identities: Tuple[Tuple[int, int, int], ...]
    ) -> None:
        self.root = root
        self.fd = fd
        self.identities = identities

    @classmethod
    def open(cls, root: Path, *, create: bool) -> "_RequirementDirectory":
        try:
            current = os.open(str(root), _DIRECTORY_FLAGS)
            identities = [_identity(os.fstat(current))]
            for component in cls._COMPONENTS:
                try:
                    child = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(component, 0o755, dir_fd=current)
                    os.fsync(current)
                    child = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
                identities.append(_identity(os.fstat(child)))
                os.close(current)
                current = child
            return cls(root, current, tuple(identities))
        except FileNotFoundError:
            try:
                os.close(current)
            except (UnboundLocalError, OSError):
                pass
            raise
        except (OSError, NotImplementedError) as error:
            try:
                os.close(current)
            except (UnboundLocalError, OSError):
                pass
            raise RequirementDocumentError(
                "requirements.path_unsafe",
                "Requirements directory is missing, unsafe, or unsupported.",
            ) from error

    def __enter__(self) -> "_RequirementDirectory":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def require_same_logical_location(self) -> None:
        current = None
        try:
            current = os.open(str(self.root), _DIRECTORY_FLAGS)
            observed = [_identity(os.fstat(current))]
            for component in self._COMPONENTS:
                child = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
                os.close(current)
                current = child
                observed.append(_identity(os.fstat(current)))
            if tuple(observed) != self.identities or _identity(os.fstat(self.fd)) != observed[-1]:
                raise RequirementDocumentError(
                    "requirements.path_unsafe", "Requirements directory identity changed."
                )
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirements directory identity changed."
            ) from error
        finally:
            if current is not None:
                os.close(current)

    def stat_optional(self, filename: str) -> Optional[os.stat_result]:
        try:
            value = os.stat(filename, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirement target could not be inspected."
            ) from error
        if not stat.S_ISREG(value.st_mode):
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirement target is not a regular file."
            )
        return value

    def entry_exists(self, filename: str) -> bool:
        try:
            os.stat(filename, dir_fd=self.fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirement target could not be inspected."
            ) from error

    def read_regular_snapshot(
        self, filename: str, *, limit: int
    ) -> Tuple[bytes, Tuple[int, int, int, int, int, int]]:
        try:
            fd = os.open(filename, _FILE_READ_FLAGS, dir_fd=self.fd)
        except FileNotFoundError:
            raise
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirement target is unsafe."
            ) from error
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise RequirementDocumentError(
                    "requirements.document_invalid", "Requirement target is invalid."
                )
            chunks, total = [], 0
            while True:
                chunk = os.read(fd, min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > limit:
                    raise RequirementDocumentError(
                        "requirements.document_too_large", "Requirement target is too large."
                    )
            after = os.fstat(fd)
            identity = _file_snapshot_identity(after)
            if (
                _identity(before) != _identity(after)
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns
            ):
                raise RequirementDocumentError(
                    "requirements.document_changed_during_verification",
                    "Requirement target changed while it was read.",
                )
            return b"".join(chunks), identity
        except RequirementDocumentError:
            raise
        except (OSError, NotImplementedError) as error:
            raise RequirementDocumentError(
                "requirements.path_unsafe", "Requirement target could not be read safely."
            ) from error
        finally:
            os.close(fd)

    def install_initial(self, filename: str, rendered: bytes) -> _InstalledDocument:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            fd = os.open(filename, flags, 0o644, dir_fd=self.fd)
            created = _identity(os.fstat(fd))
        except OSError as error:
            raise RequirementDocumentError(
                "requirements.write_failed", "Requirement target could not be created."
            ) from error
        try:
            _write_all(fd, rendered)
            os.fsync(fd)
            installed = _file_snapshot_identity(os.fstat(fd))
        except Exception as error:
            os.close(fd)
            try:
                current = self.stat_optional(filename)
                if current is None or _identity(current) != created:
                    raise OSError("Writer no longer owns the partial target")
                os.unlink(filename, dir_fd=self.fd)
                os.fsync(self.fd)
            except (OSError, RequirementDocumentError) as cleanup_error:
                raise RequirementDocumentError(
                    "requirements.commit_indeterminate",
                    "Partial requirement write could not be cleaned up safely.",
                ) from cleanup_error
            raise RequirementDocumentError(
                "requirements.write_failed", "Requirement target write failed."
            ) from error
        else:
            os.close(fd)
        try:
            os.fsync(self.fd)
        except OSError as error:
            raise RequirementDocumentError(
                "requirements.commit_indeterminate",
                "Requirement directory durability is indeterminate.",
            ) from error
        return _InstalledDocument(filename, installed, rendered, None)

    def install_revision(
        self, filename: str, rendered: bytes, previous_bytes: bytes
    ) -> _InstalledDocument:
        previous, previous_identity = self.read_regular_snapshot(
            filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
        )
        if previous != previous_bytes:
            raise RequirementDocumentError(
                "requirements.document_worktree_drift", "Requirement target changed."
            )
        temporary = f".{filename}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            fd = os.open(temporary, flags, 0o644, dir_fd=self.fd)
            _write_all(fd, rendered)
            os.fsync(fd)
            installed = _file_snapshot_identity(os.fstat(fd))
        except Exception as error:
            if "fd" in locals():
                os.close(fd)
            try:
                os.unlink(temporary, dir_fd=self.fd)
                os.fsync(self.fd)
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                raise RequirementDocumentError(
                    "requirements.commit_indeterminate",
                    "Partial revision write could not be cleaned up safely.",
                ) from cleanup_error
            raise RequirementDocumentError(
                "requirements.write_failed", "Requirement revision write failed."
            ) from error
        else:
            os.close(fd)
        repeated, repeated_identity = self.read_regular_snapshot(
            filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
        )
        if repeated != previous_bytes or repeated_identity != previous_identity:
            os.unlink(temporary, dir_fd=self.fd)
            os.fsync(self.fd)
            raise RequirementDocumentError(
                "requirements.document_worktree_drift", "Requirement target changed."
            )
        try:
            os.replace(temporary, filename, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        except OSError as error:
            try:
                os.unlink(temporary, dir_fd=self.fd)
                os.fsync(self.fd)
            except OSError as cleanup_error:
                raise RequirementDocumentError(
                    "requirements.commit_indeterminate",
                    "Revision temporary file could not be cleaned up safely.",
                ) from cleanup_error
            raise RequirementDocumentError(
                "requirements.write_failed", "Requirement revision install failed."
            ) from error
        try:
            os.fsync(self.fd)
        except OSError as error:
            raise RequirementDocumentError(
                "requirements.commit_indeterminate",
                "Requirement revision durability is indeterminate.",
            ) from error
        installed_bytes, installed = self.read_regular_snapshot(
            filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
        )
        if installed_bytes != rendered:
            raise RequirementDocumentError(
                "requirements.commit_indeterminate",
                "Installed requirement revision bytes changed.",
            )
        return _InstalledDocument(filename, installed, rendered, previous_bytes)

    def rollback(self, installed: _InstalledDocument) -> None:
        try:
            current_bytes, current_identity = self.read_regular_snapshot(
                installed.filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
            )
        except FileNotFoundError as error:
            raise RequirementDocumentError(
                "requirements.commit_indeterminate", "Writer target disappeared."
            ) from error
        if (
            current_identity != installed.identity
            or current_bytes != installed.rendered
        ):
            raise RequirementDocumentError(
                "requirements.commit_indeterminate", "Writer no longer owns target bytes."
            )
        if installed.previous_bytes is None:
            os.unlink(installed.filename, dir_fd=self.fd)
        else:
            temporary = f".{installed.filename}.{secrets.token_hex(8)}.rollback"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            fd = os.open(temporary, flags, 0o644, dir_fd=self.fd)
            try:
                _write_all(fd, installed.previous_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(temporary, installed.filename, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        os.fsync(self.fd)
```

- [x] **Step 6c: Add repository-scoped Writer serialization**

Resolve the Git common directory through sanitized `rev-parse --path-format=absolute --git-common-dir`, canonicalize it once with `resolve(strict=True)` so platform aliases such as macOS `/var` do not become false symlink failures, and open the canonical directory with a no-follow component walk. Open `ai-native-devkit-requirements.lock` relative to that descriptor with `O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC`, then acquire `fcntl.flock(LOCK_EX | LOCK_NB)` with a monotonic five-second deadline. Hold this cooperative lock across path selection, filesystem write, native Git commit, verification, and any conditional cleanup. It serializes DevKit Writers across linked worktrees; external Git concurrency remains owned by Git's normal `index.lock` and ref-lock transaction.

```python
@contextmanager
def _writer_lock(root: Path) -> Iterator[None]:
    common_text = _git(
        root, "rev-parse", "--path-format=absolute", "--git-common-dir"
    ).decode().strip()
    try:
        common = Path(common_text).resolve(strict=True)
        common_fd = os.open(str(common), _DIRECTORY_FLAGS)
        lock_fd = os.open(
            "ai-native-devkit-requirements.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=common_fd,
        )
    except OSError as error:
        raise RequirementDocumentError(
            "requirements.repository_unsupported", "Writer lock is unavailable."
        ) from error
    finally:
        if "common_fd" in locals():
            os.close(common_fd)
    deadline = time.monotonic() + 5.0
    try:
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RequirementDocumentError(
                        "requirements.writer_busy", "Another requirement Writer is active.",
                        retryable=True,
                    )
                time.sleep(0.01)
        yield
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
```

- [x] **Step 6d: Capture a bounded preservation snapshot**

Capture `HEAD`; sorted exact unrelated `git ls-files --stage -z` records; unrelated cached and worktree binary diffs; and a bounded manifest of every pre-existing untracked entry, including ignored entries, before publishing requirement bytes. Exclude the target path from each projection. Run both diff projections with `--no-ext-diff --no-textconv --ignore-submodules=none`, and clear inherited external-diff variables, so repository diff drivers, text conversion, and `diff.ignoreSubmodules` cannot suppress a real Git-visible change. The untracked manifest uses sorted `git ls-files --others -z` entries and records a missing marker, symlink target, directory marker, special-file marker, or streaming SHA-256 plus mode. Call `lstat` first and never open a FIFO, socket, device, or other non-regular entry. Define `MAX_UNTRACKED_SNAPSHOT_BYTES = 64 * 1024 * 1024` and `UNRELATED_SNAPSHOT_TIMEOUT_SECONDS = 5.0`; exceeding either fails before the target write with `requirements.snapshot_unsupported`.

The preservation contract is Git-semantic for tracked content: it preserves the exact index records and the exact no-external-diff/no-textconv cached and worktree projections that existed before the operation, plus byte-level state for pre-existing untracked regular files. It does not claim to detect a repository hook that rewrites a previously clean tracked file into different raw bytes which Git's own clean/EOL normalization still considers identical. Such hook behavior is repository policy outside the Writer transaction; record this limitation in ADR 0006. Detectable hook mutations still make the result indeterminate and are never rolled back destructively.

The supported concurrency model is cooperative, not adversarial same-UID filesystem mutation: DevKit Writers honor the Writer lock and ordinary Git processes honor Git's own locks. Static symlink/path escapes are rejected; if a directory identity, hook side effect, or external Git mutation is observed during the operation, return `requirements.commit_indeterminate` and never attempt to undo unrelated bytes. Record this threat-model boundary in ADR 0006.

Implement the logical Git/worktree snapshot with these helpers; raw `.git/index` bytes are intentionally not part of the contract:

```python
@dataclass(frozen=True)
class _PreservationSnapshot:
    parent: Optional[str]
    head_attachment: bytes
    target_index_record: Optional[bytes]
    unrelated_index_records: Tuple[bytes, ...]
    unrelated_cached_diff: bytes
    unrelated_worktree_diff: bytes
    untracked_manifest: Tuple[Tuple[bytes, str, str], ...]

def _read_optional_head(root: Path, *, timeout: float = 30) -> Optional[str]:
    result = _git_result(
        root, "rev-parse", "--verify", "-q", "HEAD", timeout=timeout
    )
    if result.timed_out or result.output_exceeded:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git HEAD lookup did not complete."
        )
    if result.returncode == 1 and not result.stderr:
        return None
    if result.returncode:
        raise RequirementDocumentError(
            "requirements.git_failed",
            (result.stderr or b"Git HEAD lookup failed.")
            .decode("utf-8", "replace")[:1000],
        )
    value = result.stdout.decode("ascii").strip()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise RequirementDocumentError(
            "requirements.git_failed", "Git returned an invalid HEAD."
        )
    return value

def _read_head_attachment(root: Path, *, timeout: float = 30) -> bytes:
    result = _git_result(
        root, "symbolic-ref", "--no-recurse", "-q", "HEAD", timeout=timeout
    )
    if result.timed_out or result.output_exceeded:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git HEAD attachment lookup did not complete."
        )
    if result.returncode == 1 and not result.stderr:
        return b"DETACHED"
    if result.returncode:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git HEAD attachment lookup failed."
        )
    value = result.stdout.rstrip(b"\n")
    if not value.startswith(b"refs/") or b"\n" in value or b"\r" in value:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git returned an invalid HEAD attachment."
        )
    return value

def _index_records(root: Path, *, timeout: float = 30) -> Tuple[bytes, ...]:
    output = _git(
        root, "ls-files", "--stage", "-z",
        timeout=timeout,
        output_limit=MAX_REPOSITORY_PROJECTION_BYTES,
    )
    return tuple(item for item in output.split(b"\0") if item)

def _hidden_index_paths(root: Path) -> Tuple[bytes, ...]:
    output = _git(
        root, "ls-files", "-v", "-z",
        output_limit=MAX_REPOSITORY_PROJECTION_BYTES,
    )
    hidden = []
    for record in (item for item in output.split(b"\0") if item):
        if len(record) < 3 or record[1:2] != b" ":
            raise RequirementDocumentError(
                "requirements.git_failed", "Git returned malformed index flags."
            )
        tag = chr(record[0])
        if tag == "S" or tag.islower():
            hidden.append(record[2:])
    return tuple(hidden)

def _index_record_path(record: bytes) -> bytes:
    _, separator, path = record.partition(b"\t")
    if not separator:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git returned a malformed index record."
        )
    return path

def _unrelated_index_records(root: Path, target: str) -> Tuple[bytes, ...]:
    encoded = os.fsencode(target)
    return tuple(
        record for record in _index_records(root)
        if _index_record_path(record) != encoded
    )

def _target_index_record(root: Path, target: str) -> Optional[bytes]:
    encoded = os.fsencode(target)
    records = [
        record for record in _index_records(root)
        if _index_record_path(record) == encoded
    ]
    if len(records) > 1:
        raise RequirementDocumentError(
            "requirements.git_failed", "Requirement path has unmerged index entries."
        )
    return records[0] if records else None

def _unrelated_diff(root: Path, target: str, *, cached: bool) -> bytes:
    arguments = ["diff"]
    if cached:
        arguments.append("--cached")
    arguments.extend([
        "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
        "--binary", "--", ".",
        f":(top,literal,exclude){target}",
    ])
    return _git(root, *arguments, output_limit=MAX_REPOSITORY_PROJECTION_BYTES)

def _untracked_manifest(
    root: Path, target: str
) -> Tuple[Tuple[bytes, str, str], ...]:
    deadline = time.monotonic() + UNRELATED_SNAPSHOT_TIMEOUT_SECONDS
    remaining = MAX_UNTRACKED_SNAPSHOT_BYTES
    target_bytes = os.fsencode(target)
    paths = sorted(
        item for item in _git(
            root, "ls-files", "--others", "-z",
            output_limit=MAX_REPOSITORY_PROJECTION_BYTES,
        ).split(b"\0")
        if item and item != target_bytes
    )
    manifest = []
    for raw_path in paths:
        if time.monotonic() > deadline:
            raise RequirementDocumentError(
                "requirements.snapshot_unsupported", "Snapshot time budget was exceeded."
            )
        logical = PurePosixPath(os.fsdecode(raw_path))
        if logical.is_absolute() or ".." in logical.parts:
            raise RequirementDocumentError(
                "requirements.snapshot_unsupported", "Untracked path is unsafe."
            )
        candidate = root.joinpath(*logical.parts)
        try:
            value = os.lstat(candidate)
            mode = stat.S_IFMT(value.st_mode)
            if stat.S_ISLNK(value.st_mode):
                manifest.append((raw_path, "symlink", os.readlink(candidate)))
                continue
            if stat.S_ISDIR(value.st_mode):
                manifest.append((raw_path, "directory", oct(mode)))
                continue
            if not stat.S_ISREG(value.st_mode):
                manifest.append((raw_path, "special", oct(mode)))
                continue
            digest = hashlib.sha256()
            fd = os.open(candidate, _FILE_READ_FLAGS)
            try:
                while True:
                    if time.monotonic() > deadline:
                        raise RequirementDocumentError(
                            "requirements.snapshot_unsupported",
                            "Snapshot time budget was exceeded.",
                        )
                    chunk = os.read(fd, min(65536, remaining + 1))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise RequirementDocumentError(
                            "requirements.snapshot_unsupported",
                            "Snapshot byte budget was exceeded.",
                        )
                    digest.update(chunk)
            finally:
                os.close(fd)
            manifest.append((
                raw_path, f"regular:{oct(value.st_mode & 0o7777)}", digest.hexdigest()
            ))
        except FileNotFoundError:
            manifest.append((raw_path, "missing", ""))
        except RequirementDocumentError:
            raise
        except OSError as error:
            raise RequirementDocumentError(
                "requirements.snapshot_unsupported",
                "Untracked repository state could not be read safely.",
            ) from error
    return tuple(manifest)

def _capture_preservation(root: Path, target: str) -> _PreservationSnapshot:
    hidden = _hidden_index_paths(root)
    if hidden:
        raise RequirementDocumentError(
            "requirements.snapshot_unsupported",
            "skip-worktree or assume-unchanged paths must be cleared before writing.",
        )
    return _PreservationSnapshot(
        parent=_read_optional_head(root),
        head_attachment=_read_head_attachment(root),
        target_index_record=_target_index_record(root, target),
        unrelated_index_records=_unrelated_index_records(root, target),
        unrelated_cached_diff=_unrelated_diff(root, target, cached=True),
        unrelated_worktree_diff=_unrelated_diff(root, target, cached=False),
        untracked_manifest=_untracked_manifest(root, target),
    )

def _preservation_matches(
    root: Path, target: str, expected: _PreservationSnapshot
) -> bool:
    return (
        _read_optional_head(root) == expected.parent
        and _read_head_attachment(root) == expected.head_attachment
        and _unrelated_preservation_matches(root, target, expected)
    )

def _unrelated_preservation_matches(
    root: Path, target: str, expected: _PreservationSnapshot
) -> bool:
    return (
        not _hidden_index_paths(root)
        and _unrelated_index_records(root, target) == expected.unrelated_index_records
        and _unrelated_diff(root, target, cached=True) == expected.unrelated_cached_diff
        and _unrelated_diff(root, target, cached=False) == expected.unrelated_worktree_diff
        and _untracked_manifest(root, target) == expected.untracked_manifest
    )

def _owned_pre_ref_state_matches(
    *, root: Path, target: str, directory: _RequirementDirectory,
    installed: _InstalledDocument, expected: _PreservationSnapshot,
    owned_intent: Optional[bytes],
) -> bool:
    try:
        content, identity = directory.read_regular_snapshot(
            installed.filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
        )
        expected_index = owned_intent or expected.target_index_record
        return (
            _read_optional_head(root) == expected.parent
            and _read_head_attachment(root) == expected.head_attachment
            and _target_index_record(root, target) == expected_index
            and identity == installed.identity
            and content == installed.rendered
        )
    except (OSError, RequirementDocumentError):
        return False
```

- [x] **Step 6e: Delegate commit-policy and index/ref transactions to native Git**

Do not reimplement Git's temporary-index, hook, signing, reference-lock, or post-commit semantics with `commit-tree`/`update-ref`. Use one bounded sanitized `git commit --only --no-status -m <message> -- <path>` command. Git's path-limited commit records the working-tree content of the named, already-known path while disregarding unrelated staged entries; it honors repository signing configuration and runs the repository's normal pre-commit, prepare-commit-msg, commit-msg, reference-transaction, and post-commit hooks. For a new path only, first run bounded `git add -N -- <path>` and verify the resulting target entry is intent-to-add while every unrelated stage record and cached diff remains identical. A revision path is already tracked and must not be staged before the commit. The real capability, SHA-1/SHA-256, and hook tests lock this native behavior instead of depending on an emulated hook sequence. Add a `commit.gpgSign=true` fixture with an unavailable signer and require typed failure plus cooperative cleanup; the Writer must not override signing policy.

```python
def _require_untransformed_attributes(root: Path, target: str) -> None:
    fields = _git(
        root, "check-attr", "-z", "filter", "working-tree-encoding", "--", target
    ).split(b"\0")
    if fields[-1:] == [b""]:
        fields.pop()
    if len(fields) != 6:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git returned malformed attribute data."
        )
    triples = [fields[index:index + 3] for index in range(0, len(fields), 3)]
    if any(
        path != os.fsencode(target) or value not in {b"unspecified", b"unset"}
        for path, _attribute, value in triples
    ):
        raise RequirementDocumentError(
            "requirements.content_transformed",
            "Git attributes would transform the requirement document.",
        )

def _require_exact_git_blob(root: Path, target: str, rendered: bytes) -> str:
    raw = _git(root, "hash-object", "--stdin", input_bytes=rendered).decode().strip()
    path_aware = _git(
        root, "hash-object", "--path", target, "--stdin", input_bytes=rendered
    ).decode().strip()
    if raw != path_aware:
        raise RequirementDocumentError(
            "requirements.content_transformed",
            "Git attributes would transform the requirement document.",
        )
    return raw

def _require_intent_to_add(root: Path, target: str) -> bytes:
    record = _target_index_record(root, target)
    if record is None:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git did not create intent-to-add."
        )
    header, separator, returned_path = record.partition(b"\t")
    fields = header.split(b" ")
    empty_blob = _git(root, "hash-object", "--stdin", input_bytes=b"").strip()
    if (
        not separator or len(fields) != 3 or fields[0] != b"100644"
        or fields[1] != empty_blob or fields[2] != b"0"
        or returned_path != os.fsencode(target)
    ):
        raise RequirementDocumentError(
            "requirements.git_failed", "Target entry is not intent-to-add."
        )
    cached = _git_result(
        root, "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
        "--cached", "--quiet", "--", target,
    )
    worktree = _git_result(
        root, "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
        "--quiet", "--", target
    )
    if cached.returncode != 0 or worktree.returncode != 1:
        raise RequirementDocumentError(
            "requirements.git_failed", "Intent-to-add state is invalid."
        )
    return record

def _remove_owned_intent(
    root: Path, target: str, owned: bytes, expected: _PreservationSnapshot
) -> None:
    if (
        _target_index_record(root, target) != owned
        or _unrelated_index_records(root, target) != expected.unrelated_index_records
        or _unrelated_diff(root, target, cached=True) != expected.unrelated_cached_diff
    ):
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Writer no longer owns intent-to-add."
        )
    _git(root, "update-index", "--force-remove", "--", target)
    if _target_index_record(root, target) is not None:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Intent-to-add cleanup failed."
        )
```

- [x] **Step 7a: Implement deterministic non-overwriting initial paths**

For initial creation, inspect the descriptor-relative `stat(..., follow_symlinks=False)`, `git ls-files --stage -- <path>`, `git cat-file -e HEAD:<path>`, and non-empty `git log --all -1 --format=%H -- <path>` before choosing the base name, `-2`, `-3`, and so on. Any path present in reachable Git history remains reserved even after a clean committed deletion; a drift-recovery write can never reuse the old identity. Use `os.open(filename, dir_fd=requirements_fd, flags=O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC)` and record the created inode plus exact bytes as Writer ownership proof.

```python
def _topic_slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_title = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
    if not slug:
        return f"topic-{digest}"
    if len(slug) > 64:
        return f"{slug[:51].rstrip('-')}-{digest}"
    return slug

def _path_is_reserved(
    root: Path, directory: _RequirementDirectory, relative_path: str
) -> bool:
    filename = PurePosixPath(relative_path).name
    if directory.entry_exists(filename):
        return True
    if _git(root, "ls-files", "--stage", "--", relative_path):
        return True
    head = _read_optional_head(root)
    if head is not None:
        in_head = _git_result(root, "cat-file", "-e", f"{head}:{relative_path}")
        if in_head.timed_out or in_head.output_exceeded:
            raise RequirementDocumentError(
                "requirements.git_failed", "Git path lookup did not complete."
            )
        if in_head.returncode == 0:
            return True
    history = _git(
        root, "log", "--all", "-1", "--format=%H", "--", relative_path
    ).strip()
    return bool(history)

def _select_initial_path(
    *, root: Path, directory: _RequirementDirectory, day: date, slug: str
) -> str:
    ordinal = 1
    while True:
        suffix = "" if ordinal == 1 else f"-{ordinal}"
        filename = f"{day.isoformat()}-{slug}-requirements{suffix}.md"
        relative = f"docs/superpowers/requirements/{filename}"
        if not _path_is_reserved(root, directory, relative):
            return relative
        ordinal += 1
```

- [x] **Step 7b: Implement the shared current verifier and verified atomic revision writes**

Add the complete private verifier below in this task. Task 4 will expose the same helper through the public Loader and add parsing/source/approval checks; it does not supply missing Task 1 behavior. For revision, call this verifier, retain the bounded exact prior bytes and verified `(device, inode, type, size, mtime_ns, ctime_ns)` identity, write a temporary name through the retained requirements-directory descriptor with `O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC`, `fsync` it, use `os.replace(..., src_dir_fd=requirements_fd, dst_dir_fd=requirements_fd)` over the still-verified regular file, then `fsync` the directory descriptor. Never resolve or replace through a path and never replace a symlink.

```python
def _exact_tree_blob(root: Path, revision: str, path: str) -> str:
    records = [
        item for item in _git(root, "ls-tree", "-z", revision, "--", path).split(b"\0")
        if item
    ]
    if len(records) != 1:
        raise RequirementDocumentError(
            "requirements.document_committed_drift", "Requirement tree entry is missing."
        )
    header, separator, raw_path = records[0].partition(b"\t")
    fields = header.split(b" ")
    if (
        not separator or len(fields) != 3 or fields[0] != b"100644"
        or fields[1] != b"blob" or raw_path != os.fsencode(path)
        or re.fullmatch(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})", fields[2]) is None
    ):
        raise RequirementDocumentError(
            "requirements.document_committed_drift", "Requirement tree entry is invalid."
        )
    return fields[2].decode("ascii")

def _require_clean_target(root: Path, path: str) -> None:
    for cached, code in (
        (True, "requirements.document_index_drift"),
        (False, "requirements.document_worktree_drift"),
    ):
        arguments = [
            "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
        ]
        if cached:
            arguments.append("--cached")
        arguments.extend(["--quiet", "--", path])
        result = _git_result(root, *arguments)
        if result.timed_out or result.output_exceeded or result.returncode not in {0, 1}:
            raise RequirementDocumentError(
                "requirements.git_failed", "Requirement verification did not complete."
            )
        if result.returncode == 1:
            raise RequirementDocumentError(code, "Requirement document is not current.")

def _verify_current_document(
    *, repository_root: Path, reference: RequirementDocRef
) -> bytes:
    root = _validated_repository_root(repository_root)
    try:
        directory = _RequirementDirectory.open(root, create=False)
    except FileNotFoundError as error:
        raise RequirementDocumentError(
            "requirements.document_missing", "Requirement document is missing."
        ) from error
    try:
        start_head = _read_optional_head(root)
        start_attachment = _read_head_attachment(root)
        start_index = _index_records(root)
        if start_head is None:
            raise RequirementDocumentError(
                "requirements.commit_invalid", "Requirement commit is unavailable."
            )
        commit_type = _git_result(root, "cat-file", "-t", reference.commit)
        ancestor = _git_result(
            root, "merge-base", "--is-ancestor", reference.commit, start_head
        )
        if (
            commit_type.timed_out or commit_type.output_exceeded
            or commit_type.returncode != 0 or commit_type.stdout.strip() != b"commit"
            or ancestor.timed_out or ancestor.output_exceeded
            or ancestor.returncode not in {0, 1}
        ):
            raise RequirementDocumentError(
                "requirements.commit_invalid", "Requirement commit is invalid."
            )
        if ancestor.returncode == 1:
            raise RequirementDocumentError(
                "requirements.commit_stale", "Requirement commit is not current history."
            )
        object_format = _git(root, "rev-parse", "--show-object-format").decode().strip()
        referenced_blob = _exact_tree_blob(root, reference.commit, reference.path)
        if reference.blob_digest != f"git-{object_format}:{referenced_blob}":
            raise RequirementDocumentError(
                "requirements.blob_mismatch", "Requirement blob identity changed."
            )
        latest = _git(
            root, "log", "-1", "--format=%H", start_head, "--", reference.path
        ).decode().strip()
        head_blob = _exact_tree_blob(root, start_head, reference.path)
        if latest != reference.commit or head_blob != referenced_blob:
            raise RequirementDocumentError(
                "requirements.document_committed_drift",
                "Requirement document changed in Git history.",
            )
        _require_clean_target(root, reference.path)
        try:
            current, identity = directory.read_regular_snapshot(
                PurePosixPath(reference.path).name,
                limit=MAX_REQUIREMENT_DOCUMENT_BYTES,
            )
        except FileNotFoundError as error:
            raise RequirementDocumentError(
                "requirements.document_missing", "Requirement document is missing."
            ) from error
        if current != _git(root, "cat-file", "blob", referenced_blob):
            raise RequirementDocumentError(
                "requirements.document_worktree_drift",
                "Requirement document changed in the worktree.",
            )
        repeated, repeated_identity = directory.read_regular_snapshot(
            PurePosixPath(reference.path).name,
            limit=MAX_REQUIREMENT_DOCUMENT_BYTES,
        )
        _require_clean_target(root, reference.path)
        if (
            _read_optional_head(root) != start_head
            or _read_head_attachment(root) != start_attachment
            or _index_records(root) != start_index
            or repeated != current
            or repeated_identity != identity
        ):
            raise RequirementDocumentError(
                "requirements.document_changed_during_verification",
                "Requirement document changed during verification.",
            )
        directory.require_same_logical_location()
        return current
    finally:
        directory.close()
```

- [x] **Step 8: Implement cooperative cleanup and classify the native commit outcome**

If native Git returns a normal pre-commit failure and `HEAD`, directory identities, target identity, unrelated stage records/diffs, and the untracked manifest still match the Writer's cooperative snapshot, remove only an initial intent-to-add entry with `git update-index --force-remove -- <path>`, then remove the initial Writer-created file or atomically restore the retained prior revision bytes and fsync the requirements directory. Compare the target against its expected post-`add -N` state separately; never require raw index-file bytes to match. If any identity/state drift is observed, do not unlink, replace, reset, or repair: return `requirements.commit_indeterminate` and leave the target as visible failure evidence. Never clean up after `HEAD` moved. This is a best-effort cooperative cleanup, not an unlink-if-inode or replace-if-inode guarantee; Python/Git expose no such name-level CAS.

Keep the attribute check: `git check-attr -z filter working-tree-encoding -- <path>` must report only `unspecified` or `unset`; otherwise fail before adding intent or moving `HEAD`. Capture `parent = _read_optional_head(root)`, then run the exact native command through `_git_result`:

```python
message = f"docs: {'revise' if supersedes else 'record'} {slug} requirements"
result = _git_result(
    root,
    "commit", "--only", "--no-status",
    "-m", message, "--", relative_path,
)
observed = _read_optional_head(root)
```

Classify after re-reading `HEAD`:

- if `observed == parent`, the commit did not land; a normal nonzero result is `requirements.commit_failed` and may use Step 7c cleanup, while timeout/output-cap or any preservation drift is `requirements.commit_indeterminate` with no cleanup;
- if `observed` is missing, malformed, or has a first parent other than `parent` (except the expected zero-parent unborn case), return `requirements.commit_indeterminate`;
- if `HEAD` moved, do not trust the process status alone: continue to exact commit verification even after timeout/output-cap/nonzero status, because Git or a hook may have completed before the runner stopped;
- never retry inside the Writer after external `HEAD` movement; the caller may retry as a new operation after inspecting repository state.

- [x] **Step 9: Verify the native commit and return exact Git identity**

For a moved `HEAD`, require the commit to have exactly the captured parent (or no parent in an unborn repository), and parse `git diff-tree --root --no-commit-id --name-status -z -r <observed>` so its only entry is an add/modify of the exact requirement path. Parse `git ls-tree -z <observed> -- <path>` as one regular `100644` blob, load its bytes with `git cat-file blob <oid>`, and require equality with the rendered bytes. Reopen the descriptor-anchored worktree file, require the same bytes, and require cached and worktree `git diff --no-ext-diff --no-textconv --ignore-submodules=none --quiet -- <path>` to be zero. Repeat the unrelated stage records, cached/worktree diffs, bounded untracked manifest, and exact non-recursive symbolic/detached `HEAD` attachment and require exact equality with the pre-write snapshot. Recheck repository/common-directory identities and require `HEAD` still equals `observed` at the final boundary.

If any post-ref or hook-side-effect check fails, return `requirements.commit_indeterminate` without reset, checkout, stash, ref rewrite, or unrelated cleanup. Otherwise return:

```python
object_format = _git(root, "rev-parse", "--show-object-format").decode().strip()
return RequirementDocRef(
    path=relative_path,
    commit=observed,
    blob_digest=f"git-{object_format}:{tree_entry.oid}",
)
```

Implement the final verifier and public Writer orchestration as follows; small output parsers may be factored, but the order and failure classification are frozen:

```python
def _validate_native_commit(
    *, root: Path, directory: _RequirementDirectory,
    expected_parent: Optional[str], observed: str, target: str,
    rendered: bytes, expected_blob: str, created: bool,
    preservation: _PreservationSnapshot,
) -> RequirementDocRef:
    parents = _git(root, "rev-list", "--parents", "-n", "1", observed).decode().split()
    expected = [observed] if expected_parent is None else [observed, expected_parent]
    if parents != expected:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Requirement commit parent changed."
        )
    changed = [
        item for item in _git(
            root, "diff-tree", "--root", "--no-commit-id", "--name-status",
            "-z", "-r", observed,
        ).split(b"\0") if item
    ]
    if changed != [b"A" if created else b"M", os.fsencode(target)]:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Commit contains unexpected changes."
        )
    records = [
        item for item in _git(root, "ls-tree", "-z", observed, "--", target).split(b"\0")
        if item
    ]
    if len(records) != 1:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Commit has no exact target blob."
        )
    header, separator, returned_path = records[0].partition(b"\t")
    fields = header.split(b" ")
    if (
        not separator or len(fields) != 3 or fields[0] != b"100644"
        or fields[1] != b"blob" or returned_path != os.fsencode(target)
    ):
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Target tree entry is invalid."
        )
    blob = fields[2].decode("ascii")
    if blob != expected_blob or _git(root, "cat-file", "blob", blob) != rendered:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Committed requirement bytes changed."
        )
    for arguments in (
        (
            "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
            "--cached", "--quiet", "--", target,
        ),
        (
            "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
            "--quiet", "--", target,
        ),
    ):
        result = _git_result(root, *arguments)
        if result.timed_out or result.output_exceeded or result.returncode != 0:
            raise RequirementDocumentError(
                "requirements.commit_indeterminate", "Requirement target is not clean."
            )
    filename = PurePosixPath(target).name
    if directory.read_regular_snapshot(
        filename, limit=MAX_REQUIREMENT_DOCUMENT_BYTES
    )[0] != rendered:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Requirement worktree bytes changed."
        )
    if not _unrelated_preservation_matches(root, target, preservation):
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "Unrelated repository state changed."
        )
    if _read_head_attachment(root) != preservation.head_attachment:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "HEAD attachment changed."
        )
    directory.require_same_logical_location()
    if _read_optional_head(root) != observed:
        raise RequirementDocumentError(
            "requirements.commit_indeterminate", "HEAD changed during verification."
        )
    object_format = _git(root, "rev-parse", "--show-object-format").decode().strip()
    return RequirementDocRef(
        path=target, commit=observed, blob_digest=f"git-{object_format}:{blob}"
    )

class RequirementDocumentWriter:
    def __init__(self, today: Callable[[], date] = date.today) -> None:
        self._today = today

    def write_and_commit(
        self, *, repository_root: Path, title: str,
        clarified_requirements: str,
        sources: Sequence[RequirementSource] = (),
        supersedes: Optional[RequirementDocRef] = None,
    ) -> RequirementDocRef:
        rendered = _render_document(title, clarified_requirements, sources)
        if supersedes is not None and not isinstance(supersedes, RequirementDocRef):
            raise RequirementDocumentError(
                "requirements.reference_invalid", "supersedes must be an exact reference."
            )
        root = _validated_repository_root(repository_root, require_identity=True)
        slug = _topic_slug(title)
        with _writer_lock(root):
            previous = (
                _verify_current_document(repository_root=root, reference=supersedes)
                if supersedes is not None else None
            )
            with _RequirementDirectory.open(root, create=True) as directory:
                target = (
                    supersedes.path if supersedes is not None
                    else _select_initial_path(
                        root=root, directory=directory, day=self._today(), slug=slug
                    )
                )
                filename = PurePosixPath(target).name
                preservation = _capture_preservation(root, target)
                _require_untransformed_attributes(root, target)
                expected_blob = _require_exact_git_blob(root, target, rendered)
                installed = (
                    directory.install_initial(filename, rendered)
                    if previous is None
                    else directory.install_revision(filename, rendered, previous)
                )
                owned_intent = None
                cleanup_permitted = True
                ref_command_started = False
                try:
                    directory.require_same_logical_location()
                    if supersedes is None:
                        add_result = _git_result(root, "add", "-N", "--", target)
                        if (
                            add_result.timed_out or add_result.output_exceeded
                            or add_result.returncode != 0
                        ):
                            if (
                                not add_result.timed_out and not add_result.output_exceeded
                                and _target_index_record(root, target) is None
                                and _unrelated_preservation_matches(root, target, preservation)
                            ):
                                raise RequirementDocumentError(
                                    "requirements.commit_failed", "Git intent-to-add failed."
                                )
                            cleanup_permitted = False
                            raise RequirementDocumentError(
                                "requirements.commit_indeterminate",
                                "Git intent-to-add outcome is indeterminate.",
                            )
                        owned_intent = _require_intent_to_add(root, target)
                        if not _unrelated_preservation_matches(root, target, preservation):
                            raise RequirementDocumentError(
                                "requirements.commit_indeterminate",
                                "Intent-to-add changed unrelated repository state.",
                            )
                    directory.require_same_logical_location()
                    message = (
                        f"docs: {'revise' if supersedes else 'record'} "
                        f"{slug} requirements"
                    )
                    result = _git_result(
                        root, "commit", "--only", "--no-status",
                        "-m", message, "--", target,
                    )
                    ref_command_started = result.started
                    cleanup_permitted = not result.started
                    observed = _read_optional_head(root)
                    if observed == preservation.parent:
                        if (
                            not result.timed_out and not result.output_exceeded
                            and result.returncode != 0
                        ):
                            cleanup_permitted = True
                            raise RequirementDocumentError(
                                "requirements.commit_failed",
                                (result.stderr or b"Requirement commit failed.")
                                .decode("utf-8", "replace")[:1000],
                            )
                        cleanup_permitted = False
                        raise RequirementDocumentError(
                            "requirements.commit_indeterminate",
                            "Native Git commit outcome is indeterminate.",
                        )
                    if observed is None:
                        cleanup_permitted = False
                        raise RequirementDocumentError(
                            "requirements.commit_indeterminate", "HEAD became invalid."
                        )
                    return _validate_native_commit(
                        root=root, directory=directory,
                        expected_parent=preservation.parent, observed=observed,
                        target=target, rendered=rendered, expected_blob=expected_blob,
                        created=(supersedes is None), preservation=preservation,
                    )
                except Exception as original:
                    if not cleanup_permitted:
                        if ref_command_started:
                            raise RequirementDocumentError(
                                "requirements.commit_indeterminate",
                                "Native Git may have moved HEAD; post-commit verification failed.",
                            ) from original
                        raise
                    path_failure_before_ref = (
                        not ref_command_started
                        and isinstance(original, RequirementDocumentError)
                        and original.code == "requirements.path_unsafe"
                    )
                    owned_state = cleanup_permitted and _owned_pre_ref_state_matches(
                        root=root, target=target, directory=directory,
                        installed=installed, expected=preservation,
                        owned_intent=owned_intent,
                    )
                    unrelated_state = (
                        True if path_failure_before_ref
                        else _unrelated_preservation_matches(root, target, preservation)
                    )
                    if owned_state and unrelated_state:
                        try:
                            if owned_intent is not None:
                                _remove_owned_intent(root, target, owned_intent, preservation)
                            # Roll back through the retained requirements dirfd. This
                            # remains safe when only the logical ancestor was swapped.
                            directory.rollback(installed)
                        except Exception as cleanup_error:
                            raise RequirementDocumentError(
                                "requirements.commit_indeterminate",
                                "Commit failed and cooperative cleanup did not complete.",
                            ) from cleanup_error
                        raise
                    if cleanup_permitted:
                        raise RequirementDocumentError(
                            "requirements.commit_indeterminate",
                            "Failure occurred after repository drift; cleanup was not attempted.",
                        ) from original
                    raise
```

This native transaction is the complete commit algorithm used by `write_and_commit`; there is no private index publication, manual hook invocation, `commit-tree`, or `update-ref` path in the implementation.

- [x] **Step 10: Make the focused suite green**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.contract.test_contracts \
  tests.modules.test_requirement_document.RequirementDocumentWriterTests -v
git diff --check
```

Expected: all selected tests pass and `git diff --check` prints nothing.

- [x] **Step 11: Review and commit the writer slice**

Stage the exact paths, verify the staged-name allow-list, then commit:

```bash
set -euo pipefail
git add \
  plugins/ai-native-devkit/scripts/ai_native_devkit/contracts.py \
  plugins/ai-native-devkit/scripts/ai_native_devkit/errors.py \
  plugins/ai-native-devkit/scripts/ai_native_devkit/requirement_document.py \
  tests/contract/test_contracts.py \
  tests/modules/test_requirement_document.py
expected=$'plugins/ai-native-devkit/scripts/ai_native_devkit/contracts.py\nplugins/ai-native-devkit/scripts/ai_native_devkit/errors.py\nplugins/ai-native-devkit/scripts/ai_native_devkit/requirement_document.py\ntests/contract/test_contracts.py\ntests/modules/test_requirement_document.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "feat: commit exact requirement documents"
```

### Task 2: Add a coherent Trace record projection

**Files:**

- Modify: `plugins/ai-native-devkit/scripts/ai_native_devkit/execution_trace.py`
- Modify: `tests/modules/test_execution_trace.py`

**Interfaces:**

- Consumes: the existing `ExecutionTraceStore`, `.sessions` mapping format, per-session lock, and `project_summary(metadata, events)` projection.
- Produces: `ExecutionTraceStore.iter_records() -> Iterator[Dict[str, Any]]`, where each detached item has exact `metadata`, `events`, and `summary` keys loaded under the existing per-session lock from a validated `.sessions` mapping.

- [x] **Step 1a: Add narrow locked-snapshot tests**

Import `hashlib`, `time`, `StoreError`, and `project_summary`, then add these concrete methods to `ExecutionTraceStoreTests`. They use the existing append and lock paths; do not add a storage adapter or change the Trace on-disk/root lifecycle.

```python
def _two_session_store(self):
    trace_ids = iter((
        "00000000-0000-4000-8000-000000000011",
        "00000000-0000-4000-8000-000000000012",
    ))
    event_ids = iter(("event-a", "event-b", "event-c", "event-d"))
    return ExecutionTraceStore(
        self.root,
        id_factory=lambda: next(trace_ids),
        event_id_factory=lambda: next(event_ids),
        clock=lambda: "2026-08-27T01:00:00.000Z",
    )

def _append_session_event(self, store, session_id, event_type="session.started"):
    return store.append(
        session_id=session_id,
        event_type=event_type,
        actor="system",
        source="devkit_runtime",
        payload={},
        context={"cwd": "/private/project"},
    )

def test_iter_records_returns_each_mapped_trace_as_a_detached_record(self):
    store = self._two_session_store()
    self._append_session_event(store, "session-a")
    self._append_session_event(store, "session-b")
    records = list(store.iter_records())
    self.assertEqual(len(records), 2)
    self.assertTrue(all(set(record) == {"metadata", "events", "summary"}
                        for record in records))
    records[0]["metadata"]["capture_status"] = "mutated"
    records[0]["events"].clear()
    persisted = store.load_session(records[0]["metadata"]["session_id"])
    self.assertNotEqual(persisted["metadata"]["capture_status"], "mutated")
    self.assertTrue(persisted["events"])

def test_iter_records_ignores_only_strict_atomic_session_temp_files(self):
    store = self._two_session_store()
    self._append_session_event(store, "session-a")
    key = hashlib.sha256(b"crashed-session").hexdigest()
    temporary = self.root / ".sessions" / f".{key}.json-{'a' * 16}"
    temporary.write_text("{}", encoding="utf-8")
    self.assertEqual(len(list(store.iter_records())), 1)
    (self.root / ".sessions" / ".unknown").write_text("{}", encoding="utf-8")
    with self.assertRaises(StoreError) as caught:
        list(store.iter_records())
    self.assertEqual(caught.exception.code, "trace.session_index_invalid")

def test_iter_records_rejects_invalid_published_session_mapping(self):
    cases = ("unexpected", "wrong_hash", "mismatched_session", "malformed")
    for case in cases:
        with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "traces"
            store = ExecutionTraceStore(
                root,
                id_factory=lambda: "00000000-0000-4000-8000-000000000021",
                event_id_factory=lambda: "event-1",
                clock=lambda: "2026-08-27T01:00:00.000Z",
            )
            self._append_session_event(store, "session-a")
            session_root = root / ".sessions"
            published = next(session_root.glob("*.json"))
            if case == "unexpected":
                (session_root / "unexpected.txt").write_text("{}", encoding="utf-8")
            elif case == "wrong_hash":
                published.rename(session_root / ("f" * 64 + ".json"))
            elif case == "mismatched_session":
                value = json.loads(published.read_text(encoding="utf-8"))
                value["session_id"] = "session-other"
                published.write_text(json.dumps(value), encoding="utf-8")
            else:
                published.write_text("not-json", encoding="utf-8")
            with self.assertRaises(StoreError) as caught:
                list(store.iter_records())
            self.assertEqual(caught.exception.code, "trace.session_index_invalid")

def test_iter_records_rejects_symlinked_session_mapping(self):
    store = self._two_session_store()
    self._append_session_event(store, "session-a")
    session_root = self.root / ".sessions"
    outside = Path(self.temporary.name) / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (session_root / ("f" * 64 + ".json")).symlink_to(outside)
    with self.assertRaises(StoreError) as caught:
        list(store.iter_records())
    self.assertEqual(caught.exception.code, "trace.session_index_invalid")

def test_iter_records_waits_for_inflight_append_and_returns_coherent_record(self):
    writer = self._two_session_store()
    reader = ExecutionTraceStore(self.root)
    self._append_session_event(writer, "session-a")
    paused = threading.Event()
    release = threading.Event()
    original_append_event = writer._append_event

    def append_then_pause(trace_id, encoded):
        original_append_event(trace_id, encoded)
        if trace_id == "00000000-0000-4000-8000-000000000012":
            paused.set()
            self.assertTrue(release.wait(2))

    writer._append_event = append_then_pause
    append_error = []
    scan_error = []
    scanned = []
    append_thread = threading.Thread(
        target=lambda: self._capture_thread_error(
            append_error,
            lambda: self._append_session_event(writer, "session-b"),
        )
    )
    scan_thread = threading.Thread(
        target=lambda: self._capture_thread_error(
            scan_error, lambda: scanned.extend(reader.iter_records())
        )
    )
    append_thread.start()
    self.assertTrue(paused.wait(2))
    scan_thread.start()
    time.sleep(0.05)
    self.assertTrue(scan_thread.is_alive())
    release.set()
    append_thread.join(2)
    scan_thread.join(2)
    self.assertFalse(append_thread.is_alive())
    self.assertFalse(scan_thread.is_alive())
    self.assertEqual(append_error + scan_error, [])
    self.assertEqual(len(scanned), 2)
    for record in scanned:
        self.assertEqual(
            record["summary"],
            project_summary(record["metadata"], record["events"]),
        )

def _capture_thread_error(self, errors, operation):
    try:
        operation()
    except Exception as error:  # assertions below re-raise with context
        errors.append(error)
```

- [x] **Step 1b: Run the snapshot tests and verify the missing projection**

Run:

```bash
set -euo pipefail
python3 -m unittest   tests.modules.test_execution_trace.ExecutionTraceStoreTests.test_iter_records_returns_each_mapped_trace_as_a_detached_record   tests.modules.test_execution_trace.ExecutionTraceStoreTests.test_iter_records_waits_for_inflight_append_and_returns_coherent_record -v
```

Expected: ERROR because `iter_records` does not exist.

- [x] **Step 1c: Make one session load a coherent existing-lock snapshot**

Extract `_load_session_unlocked(session_id)` from the current `load_session`. Make public `load_session` call `_ensure_layout()`, acquire the existing `_session_lock(session_id)`, then load mapping, metadata, events, and summary through the private helper before releasing the lock. Existing `append` already holds that same lock across event, metadata, and summary writes, so no new lock type, Trace-root API, health behavior, or storage transaction is required.

```python
def _load_session_unlocked(self, session_id: str) -> Optional[Dict[str, Any]]:
    trace_id = self.trace_id_for_session(session_id)
    if trace_id is None:
        return None
    return {
        "metadata": self.load_metadata(trace_id),
        "events": self.load_events(trace_id),
        "summary": self.load_summary(trace_id),
    }

def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
    session_id = _bounded_text(session_id, "session_id")
    self._ensure_layout()
    with self._session_lock(session_id):
        return self._load_session_unlocked(session_id)
```

- [x] **Step 1d: Implement `.sessions`-indexed `iter_records`**

Add `Iterator` to the module's typing imports. List only `root/.sessions`. Ignore an atomic-write leftover only when its name exactly matches `.<64-lowercase-hex>.json-<16-lowercase-hex>` and it is a non-symlink regular file; reject every other hidden, symlinked, or unknown entry with `trace.session_index_invalid`. Require every published entry to be a non-symlink regular `.json` file. Decode its bounded mapping, remapping `_read_json` failures to `trace.session_index_invalid`, validate `session_id`/`trace_id`, and require the filename to equal the existing `_session_key(session_id) + ".json"`. Acquire that session's existing lock, re-read the mapping with the same error mapping, call `_load_session_unlocked`, validate the same trace ID, copy exact metadata/events/summary into a detached dictionary, release the lock, then yield. A mapping atomically published after the directory listing may be omitted until the next scan; a mapped session can never be read between append sub-writes. Do not enumerate orphan UUID directories or the root health file as approval evidence.

```python
def iter_records(self) -> Iterator[Dict[str, Any]]:
    self._ensure_layout()
    session_root = self.root / ".sessions"
    for path in sorted(session_root.iterdir(), key=lambda item: item.name):
        if path.name.startswith("."):
            try:
                temporary_metadata = path.lstat()
            except OSError as error:
                raise StoreError(
                    "trace.session_index_invalid",
                    "Execution trace session index is invalid.",
                    retryable=False,
                ) from error
            if (
                re.fullmatch(r"\.[0-9a-f]{64}\.json-[0-9a-f]{16}", path.name)
                and stat.S_ISREG(temporary_metadata.st_mode)
                and not stat.S_ISLNK(temporary_metadata.st_mode)
            ):
                continue
            raise StoreError(
                "trace.session_index_invalid",
                "Execution trace session index is invalid.",
                retryable=False,
            )
        try:
            metadata = path.lstat()
        except OSError as error:
            raise StoreError(
                "trace.session_index_invalid",
                "Execution trace session index is invalid.",
                retryable=False,
            ) from error
        if (
            not path.name.endswith(".json")
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise StoreError(
                "trace.session_index_invalid",
                "Execution trace session index is invalid.",
                retryable=False,
            )
        try:
            mapping = self._read_json(path)
        except StoreError as error:
            raise StoreError(
                "trace.session_index_invalid",
                "Execution trace session index is invalid.",
                retryable=False,
            ) from error
        session_id = _bounded_text(mapping.get("session_id"), "session_id")
        trace_id = self._validate_trace_id(mapping.get("trace_id"))
        if path.name != self._session_key(session_id) + ".json":
            raise StoreError(
                "trace.session_index_invalid",
                "Execution trace session index is invalid.",
                retryable=False,
            )
        with self._session_lock(session_id):
            try:
                current = self._read_json(path)
            except StoreError as error:
                raise StoreError(
                    "trace.session_index_invalid",
                    "Execution trace session index is invalid.",
                    retryable=False,
                ) from error
            if current != {"session_id": session_id, "trace_id": trace_id}:
                raise StoreError(
                    "trace.session_index_invalid",
                    "Execution trace session index changed during lookup.",
                    retryable=False,
                )
            record = self._load_session_unlocked(session_id)
            if record is None or record["metadata"].get("trace_id") != trace_id:
                raise StoreError(
                    "trace.session_index_invalid",
                    "Execution trace session index is invalid.",
                    retryable=False,
                )
            detached = json.loads(json.dumps(record))
        yield detached
```

- [x] **Step 1e: Run the focused Trace projection group**

Run: `python3 -m unittest tests.modules.test_execution_trace -v`

Expected: detached records, concurrent append snapshots, mapping validation, and all existing Trace cases pass. Record descriptor-anchored root hardening as a separate infrastructure risk rather than expanding this Clarify implementation.

- [x] **Step 1f: Review and commit the Trace projection**

```bash
set -euo pipefail
git add \
  plugins/ai-native-devkit/scripts/ai_native_devkit/execution_trace.py \
  tests/modules/test_execution_trace.py
expected=$'plugins/ai-native-devkit/scripts/ai_native_devkit/execution_trace.py\ntests/modules/test_execution_trace.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "feat: enumerate trace approval records"
```

### Task 3: Project exact requirement approval evidence

**Files:**

- Create: `plugins/ai-native-devkit/scripts/ai_native_devkit/requirement_approval.py`
- Create: `tests/modules/test_requirement_approval.py`

**Interfaces:**

- Consumes: Task 1's `RequirementDocRef`, Task 2's `ExecutionTraceStore.iter_records()`, and `repository_digest(cwd: Optional[str]) -> Optional[str]`.
- Produces: `RequirementApprovalGate.project(records: Iterable[Dict[str, Any]]) -> List[RequirementApprovalAttempt]`, `RequirementApprovalGate.require_approved(*, trace_store: ExecutionTraceStore, repository_root: Path, reference: RequirementDocRef) -> RequirementApprovalAttempt`, and `RequirementApprovalGate.require_subject_approved(*, trace_store: ExecutionTraceStore, repository_digest_value: str, subject_digest: str, approval_id: Optional[str] = None) -> RequirementApprovalAttempt`.
- Produces: `RequirementApprovalGate.require_later_user_turn(*, events: Sequence[Dict[str, Any]], request_event: Dict[str, Any]) -> str`, returning the distinct later user turn ID or raising `ContractError` when hook evidence is missing.

- [x] **Step 1: Add the approval projection fixture and failing test matrix**

The fixture and concrete table-driven cases cover exact cross-session and turn evidence; rejected, changes-requested, incomplete, pending, and foreign-repository attempts; exact terminal tuples; duplicates; wrong sources; and wrong ordering. Add this helper first:

```python
def emit_attempt(
    store, *, session_id, repository_root, reference, decision="approved",
    terminal=True, request_turn="turn-1", resolution_turn="turn-2",
    include_later_prompt=True, stop_later_turn=False, hour=1,
    repository_override=None, request_prompt_source="codex_hook",
    duplicate_request_prompt=False, later_prompt_source="codex_hook",
    duplicate_resolution=False,
):
    run_id = "clarify-run-" + session_id
    approval_id = "approval-" + session_id
    subject = reference.subject_digest()
    repository = repository_override or repository_digest(str(repository_root))
    append = store.append
    append(
        session_id=session_id, event_type="workflow.stage.started",
        actor="runtime", source="devkit_runtime", stage="clarify",
        correlation={"stage_run_id": run_id},
        payload={"stage": "clarify", "repository": repository},
        context={"cwd": str(repository_root)},
        timestamp=f"2026-08-27T{hour:02d}:00:00.000Z",
    )
    if request_turn is not None:
        append(
            session_id=session_id, event_type="turn.prompt_submitted",
            actor="user", source=request_prompt_source, stage="clarify",
            correlation={"turn_id": request_turn}, payload={},
            timestamp=f"2026-08-27T{hour:02d}:01:00.000Z",
        )
        if duplicate_request_prompt:
            append(
                session_id=session_id, event_type="turn.prompt_submitted",
                actor="user", source=request_prompt_source, stage="clarify",
                correlation={"turn_id": request_turn}, payload={},
                timestamp=f"2026-08-27T{hour:02d}:01:30.000Z",
            )
    append(
        session_id=session_id, event_type="approval.requested",
        actor="runtime", source="devkit_runtime", stage="clarify",
        correlation={
            "stage_run_id": run_id,
            **({"turn_id": request_turn} if request_turn is not None else {}),
        },
        payload={
            "approval_id": approval_id,
            "approval_kind": "clarify.requirements",
            "subject_kind": "requirement_document",
            "subject_digest": subject,
        },
        timestamp=f"2026-08-27T{hour:02d}:02:00.000Z",
    )
    if decision is None:
        return
    if include_later_prompt and resolution_turn is not None:
        append(
            session_id=session_id, event_type="turn.prompt_submitted",
            actor="user", source=later_prompt_source, stage="clarify",
            correlation={"turn_id": resolution_turn}, payload={},
            timestamp=f"2026-08-27T{hour:02d}:03:00.000Z",
        )
        if stop_later_turn:
            append(
                session_id=session_id, event_type="turn.stopped",
                actor="agent", source="codex_hook", stage="clarify",
                correlation={"turn_id": resolution_turn}, payload={},
                timestamp=f"2026-08-27T{hour:02d}:03:30.000Z",
            )
    append(
        session_id=session_id, event_type="approval.resolved",
        actor="runtime", source="devkit_runtime", stage="clarify",
        correlation={
            "stage_run_id": run_id,
            **({"turn_id": resolution_turn} if resolution_turn is not None else {}),
        },
        payload={
            "approval_id": approval_id,
            "approval_kind": "clarify.requirements",
            "subject_kind": "requirement_document",
            "subject_digest": subject,
            "decision": decision,
        },
        timestamp=f"2026-08-27T{hour:02d}:04:00.000Z",
    )
    if duplicate_resolution:
        append(
            session_id=session_id, event_type="approval.resolved",
            actor="runtime", source="devkit_runtime", stage="clarify",
            correlation={"stage_run_id": run_id, "turn_id": resolution_turn},
            payload={
                "approval_id": approval_id,
                "approval_kind": "clarify.requirements",
                "subject_kind": "requirement_document",
                "subject_digest": subject,
                "decision": decision,
            },
            timestamp=f"2026-08-27T{hour:02d}:04:30.000Z",
        )
    if terminal:
        append(
            session_id=session_id, event_type="workflow.stage.completed",
            actor="runtime", source="devkit_runtime", stage="clarify",
            correlation={
                "stage_run_id": run_id,
                **({"turn_id": resolution_turn} if resolution_turn is not None else {}),
            },
            payload={
                "stage": "clarify", "approval_id": approval_id,
                "subject_kind": "requirement_document",
                "subject_digest": subject,
            },
            timestamp=f"2026-08-27T{hour:02d}:05:00.000Z",
        )

class RequirementApprovalGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()
        self.store = ExecutionTraceStore(Path(self.temporary.name) / "traces")
        self.reference = RequirementDocRef.from_dict({
            "path": "docs/superpowers/requirements/2026-08-27-login-requirements.md",
            "commit": "a" * 40,
            "blob_digest": "git-sha1:" + "b" * 40,
        })

    def tearDown(self):
        self.temporary.cleanup()

    def assert_not_approved(self):
        with self.assertRaises(RequirementApprovalError):
            RequirementApprovalGate().require_approved(
                trace_store=self.store,
                repository_root=self.repository,
                reference=self.reference,
            )

    def test_exact_approval_is_reusable_from_another_session(self):
        emit_attempt(
            self.store, session_id="original-session",
            repository_root=self.repository, reference=self.reference,
        )
        evidence = RequirementApprovalGate().require_approved(
            trace_store=self.store, repository_root=self.repository, reference=self.reference,
        )
        self.assertEqual(evidence.approval_id, "approval-original-session")

    def test_missing_request_turn_is_not_approval(self):
        emit_attempt(
            self.store, session_id="missing-turn",
            repository_root=self.repository, reference=self.reference,
            request_turn=None,
        )
        self.assert_not_approved()

    def test_same_turn_or_missing_later_prompt_is_not_approval(self):
        for session_id, resolution_turn, include_prompt in (
            ("same-turn", "turn-1", False),
            ("missing-prompt", "turn-2", False),
        ):
            with self.subTest(session_id=session_id):
                emit_attempt(
                    self.store, session_id=session_id,
                    repository_root=self.repository,
                    reference=self.reference, resolution_turn=resolution_turn,
                    include_later_prompt=include_prompt,
                )
                self.assert_not_approved()

    def test_stopped_later_turn_is_not_persisted_approval_evidence(self):
        emit_attempt(
            self.store, session_id="stopped-turn",
            repository_root=self.repository, reference=self.reference,
            stop_later_turn=True,
        )
        attempts = RequirementApprovalGate.project(list(self.store.iter_records()))
        stopped = next(
            attempt for attempt in attempts
            if attempt.approval_id == "approval-stopped-turn"
        )
        self.assertFalse(stopped.later_user_turn)
        self.assertFalse(stopped.terminal)
        self.assert_not_approved()

    def test_rejected_changed_or_incomplete_attempt_is_not_approval(self):
        for hour, decision, terminal in (
            (1, "rejected", True), (2, "changes_requested", True),
            (3, "approved", False),
        ):
            emit_attempt(
                self.store, session_id=f"attempt-{hour}", hour=hour,
                repository_root=self.repository,
                reference=self.reference, decision=decision, terminal=terminal,
            )
            self.assert_not_approved()

    def test_pending_attempt_alone_is_not_approval(self):
        emit_attempt(
            self.store, session_id="pending",
            repository_root=self.repository,
            reference=self.reference, decision=None,
        )
        self.assert_not_approved()

    def test_approval_from_another_repository_is_not_reused(self):
        foreign = Path(self.temporary.name) / "foreign-repository"
        foreign.mkdir()
        emit_attempt(
            self.store, session_id="foreign", repository_root=foreign,
            reference=self.reference,
        )
        self.assert_not_approved()

    def test_terminal_must_match_the_exact_approval_tuple(self):
        emit_attempt(
            self.store, session_id="mismatched-terminal",
            repository_root=self.repository,
            reference=self.reference, terminal=False,
        )
        self.store.append(
            session_id="mismatched-terminal",
            event_type="workflow.stage.completed", actor="runtime",
            source="devkit_runtime", stage="clarify",
            correlation={"stage_run_id": "clarify-run-mismatched-terminal"},
            payload={
                "stage": "clarify", "approval_id": "approval-other",
                "subject_kind": "requirement_document",
                "subject_digest": self.reference.subject_digest(),
            },
            timestamp="2026-08-27T01:05:00.000Z",
        )
        self.assert_not_approved()

    def test_preterminal_resolution_is_valid_for_stage_completion_only(self):
        emit_attempt(
            self.store, session_id="preterminal",
            repository_root=self.repository,
            reference=self.reference, terminal=False,
        )
        attempt = RequirementApprovalGate.project(list(self.store.iter_records()))[-1]
        self.assertEqual(attempt.decision, "approved")
        self.assertTrue(attempt.later_user_turn)
        self.assertFalse(attempt.terminal)
        self.assert_not_approved()

    def test_untrusted_or_ambiguous_turn_evidence_is_not_approval(self):
        cases = (
            {"session_id": "wrong-request-source", "request_prompt_source": "codex_transcript_fallback"},
            {"session_id": "duplicate-request-prompt", "duplicate_request_prompt": True},
            {"session_id": "wrong-later-source", "later_prompt_source": "codex_transcript_fallback"},
            {"session_id": "duplicate-resolution", "duplicate_resolution": True},
        )
        for case in cases:
            with self.subTest(case=case["session_id"]):
                emit_attempt(
                    self.store, repository_root=self.repository,
                    reference=self.reference, **case,
                )
                self.assert_not_approved()
```

- [x] **Step 2: Run the projection tests and observe the missing gate**

Run: `python3 -m unittest tests.modules.test_requirement_approval -v`

Expected: import ERROR for `requirement_approval`.

- [x] **Step 3a: Implement the trusted later-user-turn helper**

In `requirement_approval.py`, define `REQUIREMENT_APPROVAL_DECISIONS = frozenset({"approved", "rejected", "changes_requested"})` and `RequirementApprovalAttempt` with the frozen fields in this plan. Implement `require_later_user_turn` once, then call it from both `project` and Task 6's runtime resolution:

```python
class RequirementApprovalGate:
    @staticmethod
    def _turn_was_stopped(
        *, events: Sequence[Dict[str, Any]], turn_id: str, after_seq: int
    ) -> bool:
        return any(
            event.get("seq", 0) > after_seq
            and event.get("event_type") == "turn.stopped"
            and event.get("actor") == "agent"
            and event.get("source") == "codex_hook"
            and event.get("stage") == "clarify"
            and event.get("correlation", {}).get("turn_id") == turn_id
            for event in events
        )

    @staticmethod
    def require_later_user_turn(
        *, events: Sequence[Dict[str, Any]], request_event: Dict[str, Any]
    ) -> str:
        request_turn = request_event.get("correlation", {}).get("turn_id")
        request_seq = request_event.get("seq")
        if not isinstance(request_turn, str) or not isinstance(request_seq, int):
            raise ContractError("Requirement approval request lacks user-turn evidence.")
        candidates = [
            event
            for event in events
            if event.get("seq", 0) > request_seq
            and event.get("event_type") == "turn.prompt_submitted"
            and event.get("actor") == "user"
            and event.get("source") == "codex_hook"
            and event.get("stage") == "clarify"
            and event.get("correlation", {}).get("turn_id") != request_turn
            and isinstance(event.get("correlation", {}).get("turn_id"), str)
            and not RequirementApprovalGate._turn_was_stopped(
                events=events,
                turn_id=event["correlation"]["turn_id"],
                after_seq=event["seq"],
            )
        ]
        if not candidates:
            raise ContractError("Requirement approval requires a later user-authored turn.")
        return candidates[-1]["correlation"]["turn_id"]
```

- [x] **Step 3b: Implement strict per-record approval projection**

`project` groups events by `trace_id + approval_id`, copies repository identity from the matching Clarify start, and accepts a resolution only when the complete request/resolution/terminal tuple matches. Fail closed on duplicate request, resolution, or terminal events for one `approval_id`. The ordered tuple must be `start < request < later codex_hook user prompt < resolution < terminal`; every non-prompt event has `stage: clarify`, `actor: runtime`, and `source: devkit_runtime`. The request must be a `clarify.requirements` request with `subject_kind: requirement_document`, a canonical SHA-256 subject digest, and the same `stage_run_id` as the earlier Clarify start.

Implement the grouping and authorization selection with this concrete structure (the predicates above fill `_valid_attempt` and must not be weakened):

```python
@dataclass(frozen=True)
class RequirementApprovalAttempt:
    trace_id: str
    repository_digest: str
    stage_run_id: str
    approval_id: str
    subject_digest: str
    requested_at: str
    request_seq: int
    request_turn_id: Optional[str]
    decision: Optional[str]
    resolved_at: Optional[str]
    resolution_turn_id: Optional[str]
    later_user_turn: bool
    terminal: bool

class RequirementApprovalGate:
    @staticmethod
    def _turn_was_stopped(
        *, events: Sequence[Dict[str, Any]], turn_id: str, after_seq: int
    ) -> bool:
        return any(
            event.get("seq", 0) > after_seq
            and event.get("event_type") == "turn.stopped"
            and event.get("actor") == "agent"
            and event.get("source") == "codex_hook"
            and event.get("stage") == "clarify"
            and event.get("correlation", {}).get("turn_id") == turn_id
            for event in events
        )

    @staticmethod
    def require_later_user_turn(
        *, events: Sequence[Dict[str, Any]], request_event: Dict[str, Any]
    ) -> str:
        request_turn = request_event.get("correlation", {}).get("turn_id")
        request_seq = request_event.get("seq")
        if not isinstance(request_turn, str) or not isinstance(request_seq, int):
            raise ContractError("Requirement approval request lacks user-turn evidence.")
        candidates = [
            event
            for event in events
            if event.get("seq", 0) > request_seq
            and event.get("event_type") == "turn.prompt_submitted"
            and event.get("actor") == "user"
            and event.get("source") == "codex_hook"
            and event.get("stage") == "clarify"
            and event.get("correlation", {}).get("turn_id") != request_turn
            and isinstance(event.get("correlation", {}).get("turn_id"), str)
            and not RequirementApprovalGate._turn_was_stopped(
                events=events,
                turn_id=event["correlation"]["turn_id"],
                after_seq=event["seq"],
            )
        ]
        if not candidates:
            raise ContractError("Requirement approval requires a later user-authored turn.")
        return candidates[-1]["correlation"]["turn_id"]

    @classmethod
    def project(cls, records):
        attempts = []
        for record in records:
            metadata = record["metadata"]
            events = record["events"]
            trace_id = metadata["trace_id"]
            metadata_repository = metadata.get("repository")
            raw_requests = [
                event for event in events
                if event.get("event_type") == "approval.requested"
            ]
            requests = [
                event for event in raw_requests
                if event.get("stage") == "clarify"
                and event.get("payload", {}).get("approval_kind")
                == "clarify.requirements"
            ]
            for request in requests:
                payload = request.get("payload", {})
                correlation = request.get("correlation", {})
                approval_id = payload.get("approval_id")
                subject_digest = payload.get("subject_digest")
                stage_run_id = correlation.get("stage_run_id")
                if not all(isinstance(item, str) for item in (
                    approval_id, subject_digest, stage_run_id
                )):
                    continue
                same_requests = [
                    event for event in raw_requests
                    if event.get("payload", {}).get("approval_id") == approval_id
                ]
                starts = [
                    event for event in events
                    if event.get("event_type") == "workflow.stage.started"
                    and event.get("correlation", {}).get("stage_run_id") == stage_run_id
                    and event.get("seq", 0) < request.get("seq", 0)
                ]
                resolutions = [
                    event for event in events
                    if event.get("event_type") == "approval.resolved"
                    and event.get("payload", {}).get("approval_id") == approval_id
                ]
                terminals = [
                    event for event in events
                    if event.get("event_type") == "workflow.stage.completed"
                    and event.get("payload", {}).get("approval_id") == approval_id
                ]
                start_repository = (
                    starts[0].get("payload", {}).get("repository")
                    if len(starts) == 1 else ""
                )
                request_turn_events = [
                    event for event in events
                    if event.get("event_type") == "turn.prompt_submitted"
                    and event.get("correlation", {}).get("turn_id")
                    == correlation.get("turn_id")
                    and event.get("seq", 0) < request.get("seq", 0)
                ]
                request_prompts = [
                    event for event in request_turn_events
                    if event.get("actor") == "user"
                    and event.get("source") == "codex_hook"
                    and event.get("stage") == "clarify"
                ]
                structural = (
                    len(same_requests) == len(starts) == 1
                    and len(request_turn_events) == len(request_prompts) == 1
                    and len(resolutions) <= 1
                    and len(terminals) <= 1
                    and starts[0].get("seq", 0)
                    < request_prompts[0].get("seq", 0)
                    < request.get("seq", 0)
                    and not cls._turn_was_stopped(
                        events=[
                            event for event in events
                            if event.get("seq", 0) < request.get("seq", 0)
                        ],
                        turn_id=correlation.get("turn_id"),
                        after_seq=request_prompts[0].get("seq", 0),
                    )
                    and request.get("actor") == "runtime"
                    and request.get("source") == "devkit_runtime"
                    and starts[0].get("stage") == "clarify"
                    and starts[0].get("actor") == "runtime"
                    and starts[0].get("source") == "devkit_runtime"
                    and payload.get("subject_kind") == "requirement_document"
                    and re.fullmatch(r"sha256:[0-9a-f]{64}", subject_digest) is not None
                    and isinstance(start_repository, str)
                    and re.fullmatch(r"sha256:[0-9a-f]{64}", start_repository) is not None
                    and start_repository == metadata_repository
                    and starts[0].get("payload", {}).get("stage") == "clarify"
                )
                resolution = resolutions[0] if len(resolutions) == 1 else None
                terminal = terminals[0] if len(terminals) == 1 else None
                valid = cls._valid_attempt(
                    events=events, request=request, resolution=resolution,
                    terminal=terminal, structural=structural,
                )
                attempts.append(RequirementApprovalAttempt(
                    trace_id=trace_id,
                    repository_digest=start_repository,
                    stage_run_id=stage_run_id,
                    approval_id=approval_id,
                    subject_digest=subject_digest,
                    requested_at=request.get("timestamp", ""),
                    request_seq=request.get("seq", 0),
                    request_turn_id=request.get("correlation", {}).get("turn_id"),
                    decision=(resolution or {}).get("payload", {}).get("decision"),
                    resolved_at=(resolution or {}).get("timestamp"),
                    resolution_turn_id=(resolution or {}).get("correlation", {}).get("turn_id"),
                    later_user_turn=valid["later_user_turn"],
                    terminal=valid["terminal"],
                ))
        return sorted(
            attempts,
            key=lambda item: (item.requested_at, item.trace_id, item.request_seq),
        )

    @classmethod
    def _valid_attempt(cls, *, events, request, resolution, terminal, structural):
        invalid = {"later_user_turn": False, "terminal": False}
        if not structural or resolution is None:
            return invalid
        requested = request["payload"]
        resolved = resolution.get("payload", {})
        run_id = request["correlation"]["stage_run_id"]
        resolution_matches = (
            resolution.get("stage") == "clarify"
            and resolution.get("actor") == "runtime"
            and resolution.get("source") == "devkit_runtime"
            and resolution.get("seq", 0) > request.get("seq", 0)
            and resolution.get("correlation", {}).get("stage_run_id") == run_id
            and resolved.get("approval_id") == requested["approval_id"]
            and resolved.get("approval_kind") == "clarify.requirements"
            and resolved.get("subject_kind") == "requirement_document"
            and resolved.get("subject_digest") == requested["subject_digest"]
            and resolved.get("decision") in REQUIREMENT_APPROVAL_DECISIONS
        )
        if not resolution_matches:
            return invalid
        try:
            later_turn = cls.require_later_user_turn(
                events=[
                    event for event in events
                    if event.get("seq", 0) < resolution["seq"]
                ],
                request_event=request,
            )
        except ContractError:
            return invalid
        later_matches = resolution.get("correlation", {}).get("turn_id") == later_turn
        if terminal is None:
            return {"later_user_turn": later_matches, "terminal": False}
        completed = terminal.get("payload", {})
        terminal_matches = (
            later_matches
            and terminal.get("stage") == "clarify"
            and terminal.get("actor") == "runtime"
            and terminal.get("source") == "devkit_runtime"
            and terminal.get("seq", 0) > resolution["seq"]
            and terminal.get("correlation", {}).get("stage_run_id") == run_id
            and completed.get("stage") == "clarify"
            and completed.get("approval_id") == requested["approval_id"]
            and completed.get("subject_kind") == "requirement_document"
            and completed.get("subject_digest") == requested["subject_digest"]
        )
        return {"later_user_turn": later_matches, "terminal": terminal_matches}

    def require_approved(self, *, trace_store, repository_root, reference):
        repository = repository_digest(str(repository_root))
        if not isinstance(repository, str):
            raise RequirementApprovalError(
                "requirements.repository_invalid", "Repository identity is unavailable."
            )
        return self.require_subject_approved(
            trace_store=trace_store,
            repository_digest_value=repository,
            subject_digest=reference.subject_digest(),
        )

    def require_subject_approved(
        self, *, trace_store, repository_digest_value, subject_digest,
        approval_id=None,
    ):
        if (
            not isinstance(repository_digest_value, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", repository_digest_value) is None
            or not isinstance(subject_digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", subject_digest) is None
            or (approval_id is not None and not isinstance(approval_id, str))
        ):
            raise RequirementApprovalError(
                "requirements.approval_invalid", "Approval lookup is invalid."
            )
        candidates = [
            attempt for attempt in self.project(trace_store.iter_records())
            if attempt.repository_digest == repository_digest_value
            and attempt.subject_digest == subject_digest
            and (approval_id is None or attempt.approval_id == approval_id)
            and attempt.decision == "approved"
            and attempt.later_user_turn
            and attempt.terminal
        ]
        if not candidates:
            raise RequirementApprovalError(
                "requirements.approval_missing",
                "The exact requirement document has no completed approval.",
            )
        return candidates[-1]
```

`_valid_attempt` is the only place that implements the full request/resolution/terminal tuple. Runtime resolution uses `require_later_user_turn`; stage completion and workflow completion use the same projected fields rather than rebuilding looser event scans.

When `require_later_user_turn` raises while projecting persisted history, record `later_user_turn=False` rather than aborting the scan. Return attempts sorted by `(requested_at, trace_id, request_seq)`. `require_approved` filters by current `repository_digest` and exact `reference.subject_digest()`, keeps only attempts whose decision is `approved`, `later_user_turn` is true, and `terminal` is true, then returns the most recent valid completed approval. A pending, rejected, or changes-requested attempt is never promoted to evidence, but it does not revoke a separately completed approval across traces. This one projection is reused by Loader, runtime completion, and workflow completion.

- [x] **Step 4: Run the projection tests and verify they pass**

Run: `python3 -m unittest tests.modules.test_requirement_approval -v`

Expected: PASS for valid cross-session approval and every stale/invalid case.

- [x] **Step 5: Review and commit the approval projection**

```bash
set -euo pipefail
git add \
  plugins/ai-native-devkit/scripts/ai_native_devkit/requirement_approval.py \
  tests/modules/test_requirement_approval.py
expected=$'plugins/ai-native-devkit/scripts/ai_native_devkit/requirement_approval.py\ntests/modules/test_requirement_approval.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "feat: project exact requirement approvals"
```

### Task 4: Load only exact approved requirement documents

**Files:**

- Modify: `plugins/ai-native-devkit/scripts/ai_native_devkit/requirement_document.py`
- Modify: `tests/modules/test_requirement_document.py`

**Interfaces:**

- Consumes: Task 1's `_verify_current_document(*, repository_root: Path, reference: RequirementDocRef) -> bytes`, Task 2's `ExecutionTraceStore.iter_records()`, and Task 3's approval gate.
- Produces: `RequirementDocumentLoader.verify_current(*, repository_root: Path, reference: RequirementDocRef) -> str` and `RequirementDocumentLoader.load_approved(*, trace_store: ExecutionTraceStore, repository_root: Path, reference: RequirementDocRef, enforce_repository_source_freshness: bool = True) -> str`.

- [x] **Step 1: Add the Loader real-Git fixture and identity/drift test matrix**

Add `RequirementDocumentLoaderTests` with real Git repositories. The fixture below creates the complete later-turn approval tuple instead of mocking the authorization boundary:

```python
from tests.modules.test_requirement_approval import emit_attempt


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

        def scan_then_mutate(repository_root, sources):
            original(repository_root, sources)
            target.write_text("changed after source scan\n", encoding="utf-8")

        with mock.patch.object(
            requirement_document, "_verify_repository_sources",
            side_effect=scan_then_mutate,
        ):
            self.assert_loader_error(
                reference, "requirements.document_worktree_drift"
            )
```

- [x] **Step 2: Run loader tests and observe the missing loader**

Run: `python3 -m unittest tests.modules.test_requirement_document.RequirementDocumentLoaderTests -v`

Expected: ERROR because `RequirementDocumentLoader` does not exist.

- [x] **Step 3a: Expose and extend Task 1's exact current-document Git verification**

Make `verify_current` delegate to Task 1's `_verify_current_document`. Replace that private helper with the stricter Loader-ready body below, preserving Task 1's interface while adding explicit tree parsing, UTF-8 validation, drift-code precedence, a repeated latest-path check, and stable-snapshot checks. It verifies exact root, commit type/ancestry, `commit:path` blob OID, latest path commit, `HEAD:path`, clean index/worktree, and exact UTF-8 blob bytes. Parse only this grammar:

```python
class RequirementDocumentLoader:
    def verify_current(
        self, *, repository_root: Path, reference: RequirementDocRef
    ) -> str:
        current = _verify_current_document(
            repository_root=repository_root,
            reference=reference,
        )
        try:
            return current.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RequirementDocumentError(
                "requirements.document_invalid", "Document is not UTF-8."
            ) from error
```

```python
SOURCE_LINE = re.compile(
    r"^- (Repository|External): `([^`]+)` at `([^`]+)` — (\S(?:.*\S)?)$"
)

def _parse_requirement_document(markdown: str) -> List[RequirementSource]:
    if not markdown.endswith("\n"):
        raise RequirementDocumentError(
            "requirements.document_invalid", "Requirements document is malformed."
        )
    body = markdown[:-1]
    parts = body.split("\n\n## Sources\n\n")
    if len(parts) > 2:
        raise RequirementDocumentError(
            "requirements.document_invalid", "Requirements document is malformed."
        )
    main = re.fullmatch(
        r"# ([^\n]+)\n\n## Clarified Requirements\n\n(.+)",
        parts[0], flags=re.DOTALL,
    )
    if main is None or main.group(1) != main.group(1).strip():
        raise RequirementDocumentError(
            "requirements.document_invalid", "Requirements document is malformed."
        )
    requirements = main.group(2)
    if requirements != requirements.strip() or re.search(r"(?m)^#{1,6}\s", requirements):
        raise RequirementDocumentError(
            "requirements.document_invalid", "Requirements document is malformed."
        )
    if len(parts) == 1:
        return []
    source_lines = parts[1].splitlines()
    if len(source_lines) > MAX_REQUIREMENT_SOURCES:
        raise RequirementDocumentError(
            "requirements.source_invalid", "At most 64 sources may be recorded."
        )
    sources = []
    for line in source_lines:
        match = SOURCE_LINE.fullmatch(line)
        if match is None:
            raise RequirementDocumentError(
                "requirements.source_invalid", "Requirement source is malformed."
            )
        sources.append(_validated_source(RequirementSource(
            kind=match.group(1).lower(), locator=match.group(2),
            version=match.group(3), supports=match.group(4),
        )))
    if not sources:
        raise RequirementDocumentError(
            "requirements.source_invalid", "Sources section is empty."
        )
    return sources
```

Use this command order inside `_verify_current_document`; `_require_git_status` accepts only the explicitly listed return codes and converts every other result to `RequirementDocumentError`:

```python
@dataclass(frozen=True)
class _TreeEntry:
    mode: str
    type: str
    oid: str
    path: str

def _parse_single_ls_tree(output: bytes, expected_path: str) -> _TreeEntry:
    records = [item for item in output.split(b"\0") if item]
    if len(records) != 1:
        raise RequirementDocumentError(
            "requirements.document_committed_drift", "Git tree entry is missing."
        )
    header, separator, raw_path = records[0].partition(b"\t")
    fields = header.split(b" ")
    try:
        path = raw_path.decode("utf-8")
        mode, object_type, oid = (field.decode("ascii") for field in fields)
    except (UnicodeDecodeError, ValueError) as error:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git returned a malformed tree entry."
        ) from error
    if (
        not separator or len(fields) != 3 or path != expected_path
        or mode != "100644" or object_type != "blob"
        or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid)
    ):
        raise RequirementDocumentError(
            "requirements.document_committed_drift", "Git tree entry is invalid."
        )
    return _TreeEntry(mode, object_type, oid, path)

def _require_git_zero_or_change(
    result: _GitResult, *, change_code: str
) -> None:
    if result.timed_out or result.output_exceeded or result.returncode not in {0, 1}:
        raise RequirementDocumentError(
            "requirements.git_failed", "Git verification did not complete."
        )
    if result.returncode == 1:
        raise RequirementDocumentError(change_code, "Requirement identity is not current.")

def _git_index_snapshot(root: Path, *, timeout: float = 30) -> Tuple[bytes, ...]:
    return _index_records(root, timeout=timeout)

def _verify_current_document(*, repository_root: Path, reference: RequirementDocRef) -> bytes:
    root = _validated_repository_root(repository_root)
    try:
        requirement_dir = _RequirementDirectory.open(root, create=False)
    except FileNotFoundError as error:
        raise RequirementDocumentError(
            "requirements.document_missing", "Document is missing from the worktree."
        ) from error
    start_head = _read_optional_head(root)
    start_attachment = _read_head_attachment(root)
    start_index = _git_index_snapshot(root)
    if start_head is None:
        raise RequirementDocumentError("requirements.commit_invalid", "HEAD is unborn.")
    commit_type = _git_result(root, "cat-file", "-t", reference.commit)
    if (
        commit_type.timed_out or commit_type.output_exceeded
        or commit_type.returncode != 0 or commit_type.stdout.strip() != b"commit"
    ):
        raise RequirementDocumentError("requirements.commit_invalid", "Commit is invalid.")
    _require_git_zero_or_change(
        _git_result(root, "merge-base", "--is-ancestor", reference.commit, start_head),
        change_code="requirements.commit_stale",
    )
    object_format = _git(root, "rev-parse", "--show-object-format").decode().strip()
    expected_prefix = f"git-{object_format}:"
    tree_entry = _parse_single_ls_tree(
        _git(root, "ls-tree", "-z", reference.commit, "--", reference.path),
        reference.path,
    )
    if tree_entry.type != "blob" or reference.blob_digest != expected_prefix + tree_entry.oid:
        raise RequirementDocumentError("requirements.blob_mismatch", "Blob identity changed.")
    latest = _git(
        root, "log", "-1", "--format=%H", start_head, "--", reference.path
    ).decode().strip()
    head_bytes = _git(root, "ls-tree", "-z", start_head, "--", reference.path)
    if latest != reference.commit or not head_bytes:
        raise RequirementDocumentError(
            "requirements.document_committed_drift", "Document changed in Git history."
        )
    head_entry = _parse_single_ls_tree(head_bytes, reference.path)
    if head_entry.oid != tree_entry.oid:
        raise RequirementDocumentError(
            "requirements.document_committed_drift", "Document changed in Git history."
        )
    _require_git_zero_or_change(
        _git_result(
            root, "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
            "--cached", "--quiet", "--", reference.path,
        ),
        change_code="requirements.document_index_drift",
    )
    try:
        current, target_identity = requirement_dir.read_regular_snapshot(
            PurePosixPath(reference.path).name,
            limit=MAX_REQUIREMENT_DOCUMENT_BYTES,
        )
    except FileNotFoundError as error:
        raise RequirementDocumentError(
            "requirements.document_missing", "Document is missing from the worktree."
        ) from error
    _require_git_zero_or_change(
        _git_result(
            root, "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
            "--quiet", "--", reference.path,
        ),
        change_code="requirements.document_worktree_drift",
    )
    committed = _git(root, "cat-file", "blob", tree_entry.oid)
    if current != committed:
        raise RequirementDocumentError(
            "requirements.document_worktree_drift", "Document changed in the worktree."
        )
    try:
        current.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RequirementDocumentError(
            "requirements.document_invalid", "Document is not UTF-8."
        ) from error
    try:
        repeated, repeated_identity = requirement_dir.read_regular_snapshot(
            PurePosixPath(reference.path).name,
            limit=MAX_REQUIREMENT_DOCUMENT_BYTES,
        )
    except FileNotFoundError as error:
        raise RequirementDocumentError(
            "requirements.document_missing", "Document disappeared during verification."
        ) from error
    repeated_latest = _git(
        root, "log", "-1", "--format=%H", start_head, "--", reference.path
    ).decode().strip()
    _require_git_zero_or_change(
        _git_result(
            root, "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
            "--cached", "--quiet", "--", reference.path,
        ),
        change_code="requirements.document_index_drift",
    )
    _require_git_zero_or_change(
        _git_result(
            root, "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
            "--quiet", "--", reference.path,
        ),
        change_code="requirements.document_worktree_drift",
    )
    if (
        _read_optional_head(root) != start_head
        or _read_head_attachment(root) != start_attachment
        or _git_index_snapshot(root) != start_index
        or repeated_latest != reference.commit
        or repeated_identity != target_identity
        or repeated != current
    ):
        raise RequirementDocumentError(
            "requirements.document_changed_during_verification",
            "Document or repository state changed during verification.",
        )
    requirement_dir.require_same_logical_location()
    requirement_dir.close()
    return current
```

Wrap the helper body in `try/finally` so `requirement_dir.close()` always runs; it is shown at the success edge above only to keep the command-order snippet readable. `_open_requirements_directory` is the Step 6b descriptor-relative no-follow walk shared by Writer and Loader. `read_regular` uses `os.open(filename, dir_fd=fd, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)`, checks `fstat` for a regular file and the byte limit, and reads from that descriptor. `require_same_logical_location` reopens and compares every retained directory identity, so an ancestor swap cannot redirect a Loader read or pass final verification.

`_require_git_zero_or_change` returns only for status 0, maps status 1 to the named domain-change code, and maps timeouts or every other status to `requirements.git_failed`. Tests lock this precedence: a later commit touching/deleting the path is `requirements.document_committed_drift`; a staged change/deletion is `requirements.document_index_drift`; an unstaged byte change is `requirements.document_worktree_drift`; and an unstaged deletion is `requirements.document_missing`. `_parse_single_ls_tree` must require exactly one NUL-terminated entry whose mode is a regular blob mode and whose returned path exactly equals `reference.path`; do not parse Git output with whitespace splitting.

- [x] **Step 3b: Implement exact Markdown/source parsing and repository freshness**

When `enforce_repository_source_freshness` is true, compare every repository source's `revision:path`, `HEAD:path`, and clean worktree path; any mismatch raises `RequirementDocumentError("requirements.source_drift", "A cited repository source changed.")`. External source locators and versions remain in the Markdown for `$sop-design` to re-check; the Loader does not fetch external systems.

Implement `_verify_repository_sources` as a stable snapshot, not a one-pass check. Capture exact `HEAD`, its non-recursive symbolic/detached attachment, and logical index records before the source loop. For each validated source, require `git cat-file -t <version>` to be `commit`, parse exact `git ls-tree -z <version> -- <locator>` and `git ls-tree -z <captured-head> -- <locator>` entries, require equal `(mode, blob OID)` pairs, require both cached and worktree `git diff --no-ext-diff --no-textconv --ignore-submodules=none --quiet -- <locator>` results to be zero, and compare both the descriptor-anchored worktree executable bit and blob hash with the tree entry. Open the stable repository-root descriptor, walk every parent component of the canonical `PurePosixPath` locator with `openat(O_DIRECTORY | O_NOFOLLOW)`, then open the final regular file with `O_RDONLY | O_NOFOLLOW`; never join and reopen the locator as a path. Retain each first `(mode, identity, blob hash, directory identities)` tuple. At the end, reopen every locator and repeat its mode/identity/hash, `HEAD` tree entry, cached/worktree diffs, plus the exact global `HEAD`, attachment, and logical index snapshot; any difference is `requirements.source_drift`. This mode comparison remains mandatory with `core.filemode=false`. Reopen the logical root/component chain and compare retained directory identities before accepting. Share a 64 MiB descriptor-read budget across both file passes and a five-second total deadline across every descriptor read and Git probe for at most 64 sources; each Git subprocess receives only the remaining deadline and retains the runner's per-call output cap. Exhausting either bound raises typed `requirements.source_drift` rather than blocking without limit. Map any missing, dirty, mode-changed, content-changed, symlink-swapped, non-commit, or budget-exhausted case to `requirements.source_drift`; propagate malformed source syntax as `requirements.source_invalid`. The mode, budget, and post-source-scan methods in Step 1 lock these branches.

Use a descriptor-relative blob hash so source verification is not limited by the Git runner's 1 MiB output cap:

```python
@dataclass(frozen=True)
class _SourceSnapshot:
    locator: str
    file_identity: Tuple[int, int, int, int, int, int]
    directory_identities: Tuple[Tuple[int, int, int], ...]
    git_mode: str
    blob_oid: str

MAX_SOURCE_SNAPSHOT_BYTES = 64 * 1024 * 1024
SOURCE_SNAPSHOT_TIMEOUT_SECONDS = 5.0

@dataclass
class _SourceReadBudget:
    remaining: int
    deadline: float

    def timeout(self) -> float:
        remaining_time = self.deadline - time.monotonic()
        if remaining_time <= 0:
            raise RequirementDocumentError(
                "requirements.source_drift",
                "Repository source verification time budget was exceeded.",
            )
        return min(30.0, remaining_time)

    def consume(self, count: int) -> None:
        self.timeout()
        if count > self.remaining:
            raise RequirementDocumentError(
                "requirements.source_drift",
                "Repository source verification budget was exceeded.",
            )
        self.remaining -= count

def _source_checked(budget: _SourceReadBudget, operation: Callable[[float], Any]) -> Any:
    try:
        return operation(budget.timeout())
    except RequirementDocumentError as error:
        raise RequirementDocumentError(
            "requirements.source_drift",
            "Repository source verification did not complete.",
        ) from error

def _source_tree_entry(
    root: Path, revision: str, locator: str, budget: _SourceReadBudget
) -> _TreeEntry:
    records = [
        item for item in _source_checked(
            budget,
            lambda timeout: _git(
                root, "ls-tree", "-z", revision, "--", locator,
                timeout=timeout,
            ),
        ).split(b"\0")
        if item
    ]
    if len(records) != 1:
        raise RequirementDocumentError(
            "requirements.source_drift", "A cited repository source is missing."
        )
    header, separator, raw_path = records[0].partition(b"\t")
    fields = header.split(b" ")
    if (
        not separator or len(fields) != 3 or fields[0] not in {b"100644", b"100755"}
        or fields[1] != b"blob" or raw_path != os.fsencode(locator)
    ):
        raise RequirementDocumentError(
            "requirements.source_drift", "A cited repository source is not a regular blob."
        )
    return _TreeEntry(
        fields[0].decode("ascii"), "blob", fields[2].decode("ascii"), locator
    )

def _worktree_source_snapshot(
    root: Path, locator: str, object_format: str, budget: _SourceReadBudget
) -> _SourceSnapshot:
    logical = PurePosixPath(locator)
    current = os.open(str(root), _DIRECTORY_FLAGS)
    identities = [_identity(os.fstat(current))]
    try:
        for component in logical.parts[:-1]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=current)
            os.close(current)
            current = child
            identities.append(_identity(os.fstat(current)))
        fd = os.open(logical.name, _FILE_READ_FLAGS, dir_fd=current)
        try:
            budget.consume(0)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise OSError("source is not regular")
            algorithm = "sha1" if object_format == "sha1" else "sha256"
            digest = hashlib.new(algorithm)
            digest.update(f"blob {before.st_size}\0".encode("ascii"))
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                budget.consume(len(chunk))
                digest.update(chunk)
            after = os.fstat(fd)
            file_identity = (
                after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode),
                after.st_size, after.st_mtime_ns, after.st_ctime_ns,
            )
            if (
                _identity(before) != _identity(after)
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns
            ):
                raise OSError("source changed while read")
            return _SourceSnapshot(
                locator, file_identity, tuple(identities),
                "100755" if before.st_mode & 0o111 else "100644",
                digest.hexdigest(),
            )
        finally:
            os.close(fd)
    except OSError as error:
        raise RequirementDocumentError(
            "requirements.source_drift", "A cited repository source is unavailable."
        ) from error
    finally:
        os.close(current)

def _verify_repository_sources(
    repository_root: Path, sources: Sequence[RequirementSource]
) -> None:
    if len(sources) > MAX_REQUIREMENT_SOURCES:
        raise RequirementDocumentError(
            "requirements.source_invalid", "At most 64 sources may be recorded."
        )
    repository_sources = [
        _validated_source(source) for source in sources if source.kind == "repository"
    ]
    if not repository_sources:
        return
    root = _validated_repository_root(repository_root)
    budget = _SourceReadBudget(
        remaining=MAX_SOURCE_SNAPSHOT_BYTES,
        deadline=time.monotonic() + SOURCE_SNAPSHOT_TIMEOUT_SECONDS,
    )
    start_head = _source_checked(
        budget, lambda timeout: _read_optional_head(root, timeout=timeout)
    )
    if start_head is None:
        raise RequirementDocumentError(
            "requirements.source_drift", "Repository has no current revision."
        )
    start_attachment = _source_checked(
        budget, lambda timeout: _read_head_attachment(root, timeout=timeout)
    )
    start_index = _source_checked(
        budget, lambda timeout: _git_index_snapshot(root, timeout=timeout)
    )
    object_format = _source_checked(
        budget,
        lambda timeout: _git(
            root, "rev-parse", "--show-object-format", timeout=timeout
        ),
    ).decode().strip()
    if object_format not in {"sha1", "sha256"}:
        raise RequirementDocumentError(
            "requirements.source_drift", "Repository object format is unsupported."
        )
    first = []
    for source in repository_sources:
        commit_type = _git_result(
            root, "cat-file", "-t", source.version, timeout=budget.timeout()
        )
        ancestor = _git_result(
            root, "merge-base", "--is-ancestor", source.version, start_head,
            timeout=budget.timeout(),
        )
        if (
            commit_type.timed_out or commit_type.output_exceeded
            or commit_type.returncode != 0 or commit_type.stdout.strip() != b"commit"
            or ancestor.timed_out or ancestor.output_exceeded or ancestor.returncode != 0
        ):
            raise RequirementDocumentError(
                "requirements.source_drift", "A cited source revision is not current history."
            )
        recorded = _source_tree_entry(root, source.version, source.locator, budget)
        current = _source_tree_entry(root, start_head, source.locator, budget)
        if (recorded.mode, recorded.oid) != (current.mode, current.oid):
            raise RequirementDocumentError(
                "requirements.source_drift", "A cited repository source changed."
            )
        for arguments in (
            (
                "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
                "--cached", "--quiet", "--", source.locator,
            ),
            (
                "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
                "--quiet", "--", source.locator,
            ),
        ):
            probe = _git_result(root, *arguments, timeout=budget.timeout())
            if probe.timed_out or probe.output_exceeded or probe.returncode != 0:
                raise RequirementDocumentError(
                    "requirements.source_drift", "A cited repository source is dirty."
                )
        snapshot = _worktree_source_snapshot(
            root, source.locator, object_format, budget
        )
        if (snapshot.git_mode, snapshot.blob_oid) != (current.mode, current.oid):
            raise RequirementDocumentError(
                "requirements.source_drift", "A cited repository source changed."
            )
        first.append((source, current.mode, current.oid, snapshot))
    if (
        _source_checked(
            budget, lambda timeout: _read_optional_head(root, timeout=timeout)
        ) != start_head
        or _source_checked(
            budget, lambda timeout: _read_head_attachment(root, timeout=timeout)
        ) != start_attachment
        or _source_checked(
            budget, lambda timeout: _git_index_snapshot(root, timeout=timeout)
        ) != start_index
    ):
        raise RequirementDocumentError(
            "requirements.source_drift", "Repository changed during source verification."
        )
    for source, expected_mode, expected_oid, expected_snapshot in first:
        repeated_entry = _source_tree_entry(root, start_head, source.locator, budget)
        repeated_snapshot = _worktree_source_snapshot(
            root, source.locator, object_format, budget
        )
        for arguments in (
            (
                "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
                "--cached", "--quiet", "--", source.locator,
            ),
            (
                "diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none",
                "--quiet", "--", source.locator,
            ),
        ):
            probe = _git_result(root, *arguments, timeout=budget.timeout())
            if probe.timed_out or probe.output_exceeded or probe.returncode != 0:
                raise RequirementDocumentError(
                    "requirements.source_drift", "A cited repository source is dirty."
                )
        if (
            (repeated_entry.mode, repeated_entry.oid) != (expected_mode, expected_oid)
            or repeated_snapshot != expected_snapshot
        ):
            raise RequirementDocumentError(
                "requirements.source_drift", "A cited source changed during verification."
            )
    if (
        _source_checked(
            budget, lambda timeout: _read_optional_head(root, timeout=timeout)
        ) != start_head
        or _source_checked(
            budget, lambda timeout: _read_head_attachment(root, timeout=timeout)
        ) != start_attachment
        or _source_checked(
            budget, lambda timeout: _git_index_snapshot(root, timeout=timeout)
        ) != start_index
    ):
        raise RequirementDocumentError(
            "requirements.source_drift", "Repository changed during source verification."
        )
```

- [x] **Step 3c: Implement approval loading with post-scan re-verification**

Implement the public method in this order:

```python
class RequirementDocumentLoader:
    def verify_current(
        self, *, repository_root: Path, reference: RequirementDocRef
    ) -> str:
        current = _verify_current_document(
            repository_root=repository_root, reference=reference
        )
        try:
            return current.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RequirementDocumentError(
                "requirements.document_invalid", "Document is not UTF-8."
            ) from error

    def load_approved(
        self, *, trace_store, repository_root, reference,
        enforce_repository_source_freshness=True,
    ) -> str:
        before = _verify_current_document(
            repository_root=repository_root, reference=reference
        )
        RequirementApprovalGate().require_approved(
            trace_store=trace_store,
            repository_root=repository_root,
            reference=reference,
        )
        after = _verify_current_document(
            repository_root=repository_root, reference=reference
        )
        if before != after:
            raise RequirementDocumentError(
                "requirements.document_worktree_drift",
                "Document changed during approval lookup.",
            )
        sources = _parse_requirement_document(after.decode("utf-8"))
        if enforce_repository_source_freshness:
            _verify_repository_sources(repository_root, sources)
        final = _verify_current_document(
            repository_root=repository_root, reference=reference
        )
        if final != after:
            raise RequirementDocumentError(
                "requirements.document_changed_during_verification",
                "Document changed during source verification.",
            )
        return final.decode("utf-8")
```

Setting the flag false skips only cited-source freshness so Clarify can revise a drifted approved document; it never skips document identity, repeated verification, parsing, or approval. `test_loader_rechecks_requirement_after_source_scan` proves the final `_verify_current_document` rejects a mutation after source verification.

- [x] **Step 4: Run loader tests and verify they pass**

Run: `python3 -m unittest tests.modules.test_requirement_document.RequirementDocumentLoaderTests -v`

Expected: PASS.

- [x] **Step 5: Review and commit the approved Loader**

```bash
set -euo pipefail
git add \
  plugins/ai-native-devkit/scripts/ai_native_devkit/requirement_document.py \
  tests/modules/test_requirement_document.py
expected=$'plugins/ai-native-devkit/scripts/ai_native_devkit/requirement_document.py\ntests/modules/test_requirement_document.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "feat: load approved requirement documents"
```

### Task 5: Replace the workflow artifact CLI

**Files:**

- Replace: `plugins/ai-native-devkit/scripts/ai_native_devkit/workflow_cli.py`
- Keep wrapper: `plugins/ai-native-devkit/scripts/workflow_cli.py`
- Replace: `tests/integration/test_workflow_cli.py`

**Interfaces:**

- Consumes: Task 1's Writer and exact requirement references, Task 2's coherent Trace projection, Task 3's approval gate, Task 4's approved Loader, and the existing `repository_digest` and Trace-root validation helpers.
- Produces: only `requirements.write` and `requirements.load`, with authoritative host-session binding, exact active-stage gates, bounded request validation, and the frozen response envelopes below.

- [x] **Step 1: Write failing CLI integration tests**

Replace `tests/integration/test_workflow_cli.py` with the existing subprocess helper plus this concrete fixture. The normal request omits `session_id`; `CODEX_THREAD_ID` is the host authority.

```python
class WorkflowCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.state = Path(self.temporary.name) / "state"
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "DevKit Test")
        self.git("config", "user.email", "devkit@example.test")
        (self.repository / "seed.txt").write_text("seed\n", encoding="utf-8")
        self.git("add", "seed.txt")
        self.git("commit", "-m", "seed")

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments, check=True):
        return subprocess.run(
            ["git", *arguments], cwd=self.repository, check=check,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def _start_stage(self, *, session_id="session-1", stage="clarify"):
        ExecutionTraceStore(self.state / "execution-traces").append(
            session_id=session_id,
            event_type="workflow.stage.started",
            actor="runtime", source="devkit_runtime", stage=stage,
            correlation={"stage_run_id": f"{stage}-run"},
            payload={
                "stage": stage,
                "repository": repository_digest(str(self.repository)),
            },
            context={"cwd": str(self.repository)},
        )

    def _request(self, operation):
        common = {
            "schema_version": SCHEMA_VERSION,
            "operation": operation,
            "cwd": str(self.repository),
        }
        if operation == "requirements.write":
            return {
                **common,
                "title": "Login Policy",
                "clarified_requirements": "Only administrators may revoke sessions.",
            }
        return {
            **common,
            "purpose": "design",
            "reference": {
                "path": "docs/superpowers/requirements/2026-08-27-login-requirements.md",
                "commit": "a" * 40,
                "blob_digest": "git-sha1:" + "b" * 40,
            },
        }

    def _assert_contract_rejection(self, request, *, session_id="session-1"):
        before = self.git("rev-parse", "HEAD").stdout
        result = run_cli(self.state, request, session_id=session_id)
        self.assertNotEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertEqual(response["kind"], "runtime_error")
        self.assertEqual(response["code"], "rejected.contract")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)
        self.assertFalse((self.repository / "docs/superpowers/requirements").exists())

    def test_operations_reject_malformed_required_core_fields(self):
        invalid = []
        for operation in ("requirements.write", "requirements.load"):
            valid = self._request(operation)
            for field in valid:
                missing = dict(valid)
                missing.pop(field)
                invalid.append(missing)
                for replacement in (None, [], ""):
                    malformed = dict(valid)
                    malformed[field] = replacement
                    invalid.append(malformed)
        write = self._request("requirements.write")
        load = self._request("requirements.load")
        invalid.extend((
            {**write, "cwd": "relative/repository"},
            {**write, "session_id": []},
            {**write, "sources": {}},
            {**write, "sources": [{}] * 65},
            {**write, "supersedes": []},
            {**load, "reference": []},
            {**load, "purpose": "unknown"},
        ))
        for request in invalid:
            with self.subTest(request=request):
                self._assert_contract_rejection(request)

    def test_write_uses_host_session_and_commits_sources(self):
        self._start_stage()
        request = self._request("requirements.write")
        request["sources"] = [{
            "kind": "external",
            "locator": "https://example.test/policy",
            "version": "v2",
            "supports": "Supports the required revocation policy.",
        }]
        result = run_cli(self.state, request, session_id="session-1")
        self.assertEqual(result.returncode, 0, result.stdout)
        response = json.loads(result.stdout)
        self.assertEqual(response["kind"], "requirement_document")
        self.assertRegex(response["reference"]["commit"], r"^[0-9a-f]{40}$")
        self.assertIn(
            "https://example.test/policy",
            (self.repository / response["reference"]["path"]).read_text(),
        )

    def test_old_operations_and_session_spoof_are_rejected(self):
        for operation in (
            "clarification.checkpoint", "clarification.approval.request",
            "clarification.finalize", "clarification.load",
        ):
            with self.subTest(operation=operation):
                self._assert_contract_rejection({
                    "schema_version": SCHEMA_VERSION,
                    "operation": operation,
                    "cwd": str(self.repository),
                })
        self._start_stage()
        self._assert_contract_rejection(
            {**self._request("requirements.write"), "session_id": "another-session"}
        )
```

Add this exact terminal-stage matrix so a completed-only implementation cannot pass:

```python
def _seed_terminal_stage(self, *, session_id, stage, terminal_event):
    store = ExecutionTraceStore(self.state / "execution-traces")
    run_id = f"{stage}-{terminal_event.rsplit('.', 1)[-1]}"
    common = {
        "session_id": session_id,
        "actor": "runtime",
        "source": "devkit_runtime",
        "stage": stage,
        "correlation": {"stage_run_id": run_id},
        "context": {"cwd": str(self.repository)},
    }
    store.append(
        **common,
        event_type="workflow.stage.started",
        payload={
            "stage": stage,
            "repository": repository_digest(str(self.repository)),
        },
    )
    store.append(
        **common,
        event_type=terminal_event,
        payload={"stage": stage},
    )

def test_terminal_stage_never_authorizes_artifact_operation(self):
    reference = {
        "path": "docs/superpowers/requirements/2026-08-27-login-requirements.md",
        "commit": "a" * 40,
        "blob_digest": "git-sha1:" + "b" * 40,
    }
    cases = (
        ("clarify", {
            "operation": "requirements.write",
            "title": "Login Policy",
            "clarified_requirements": "Administrators revoke sessions.",
        }),
        ("clarify", {
            "operation": "requirements.load",
            "purpose": "clarify_revision",
            "reference": reference,
        }),
        ("sync-docs", {
            "operation": "requirements.load",
            "purpose": "docs_promotion",
            "reference": reference,
        }),
    )
    original_head = self.git("rev-parse", "HEAD").stdout
    for terminal_event in (
        "workflow.stage.completed",
        "workflow.stage.failed",
        "workflow.stage.skipped",
    ):
        for ordinal, (stage, request) in enumerate(cases):
            with self.subTest(terminal=terminal_event, stage=stage, request=request):
                session_id = f"session-{terminal_event}-{ordinal}"
                self._seed_terminal_stage(
                    session_id=session_id,
                    stage=stage,
                    terminal_event=terminal_event,
                )
                result = run_cli(
                    self.state,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "cwd": str(self.repository),
                        **request,
                    },
                    session_id=session_id,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
    self.assertEqual(self.git("rev-parse", "HEAD").stdout, original_head)
    self.assertFalse((self.repository / "docs/superpowers/requirements").exists())
```

- [x] **Step 2: Run CLI tests and verify the old operation set fails**

Run: `python3 -m unittest tests.integration.test_workflow_cli -v`

Expected: `requirements.write` is rejected as an invalid operation.

- [x] **Step 3: Replace the workflow CLI operation boundary**

Keep bounded JSON/error envelopes and define:

```python
OPERATIONS = {"requirements.write", "requirements.load"}
ALLOWED_FIELDS = {
    "requirements.write": {
        "schema_version", "operation", "session_id", "cwd", "title",
        "clarified_requirements", "sources", "supersedes",
    },
    "requirements.load": {
        "schema_version", "operation", "session_id", "cwd", "reference", "purpose",
    },
}

REQUIRED_FIELDS = {
    "requirements.write": {
        "schema_version", "operation", "cwd", "title", "clarified_requirements",
    },
    "requirements.load": {
        "schema_version", "operation", "cwd", "reference", "purpose",
    },
}

def _required_text(request: Dict[str, Any], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ContractError(f"Workflow operation requires a valid {field}.")
    return value

def _absolute_cwd(request: Dict[str, Any]) -> Path:
    value = _required_text(request, "cwd")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ContractError("Workflow operation cwd must be absolute.")
    return candidate

def _validate_request_fields(request: Dict[str, Any]) -> None:
    operation = request.get("operation")
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ContractError("CLI workflow operation is invalid.")
    if request.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("CLI request schema version is incompatible.")
    if set(request) - ALLOWED_FIELDS[operation]:
        raise ContractError("CLI workflow operation contains unknown fields.")
    if not REQUIRED_FIELDS[operation].issubset(request):
        raise ContractError("CLI workflow operation is missing required fields.")
    _absolute_cwd(request)
    supplied_session = request.get("session_id")
    if supplied_session is not None and (
        not isinstance(supplied_session, str) or not supplied_session.strip()
    ):
        raise ContractError("Workflow session_id must be a non-empty string.")
    if operation == "requirements.write":
        _required_text(request, "title")
        _required_text(request, "clarified_requirements")
        sources = request.get("sources", [])
        if not isinstance(sources, list) or len(sources) > 64:
            raise ContractError("Requirement sources must be a list of at most 64 items.")
        if request.get("supersedes") is not None and not isinstance(
            request["supersedes"], dict
        ):
            raise ContractError("supersedes must be an object when provided.")
    else:
        if not isinstance(request.get("reference"), dict):
            raise ContractError("Requirement reference must be an object.")
        purpose = _required_text(request, "purpose")
        if purpose not in {"design", "clarify_revision", "docs_promotion"}:
            raise ContractError("Requirement load purpose is invalid.")

def _session_id(request: Dict[str, Any]) -> str:
    host = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_TASK_ID")
    supplied = request.get("session_id")
    if host and supplied is not None and supplied != host:
        raise ContractError("Session identity does not match the active Codex task.")
    value = host or supplied
    if not isinstance(value, str) or not value.strip():
        raise ContractError("Workflow operation requires a Codex session identity.")
    return value
```

Make `_read_request` parse the bounded JSON object and call `_validate_request_fields` before returning. Dispatch in exactly this order: validate required/allowed core fields and absolute `cwd`; derive the authoritative host session with `_session_id`; run `_preflight`; validate the Trace root and construct the existing path-based `ExecutionTraceStore`; require the matching active stage when the operation/purpose needs one; only then parse `RequirementSource`, `RequirementDocRef`, and `supersedes`; finally call Writer or Loader. No malformed core value may reach `Path`, `.strip()`, Trace lookup, or a domain constructor first.

Use this dispatch skeleton; `_require_active_run` reads the authoritative session's coherent Trace snapshot and requires one non-terminal run whose start payload has the exact stage and `repository_digest(str(cwd))`:

```python
def _require_active_run(
    store: ExecutionTraceStore, session_id: str, stage: str, cwd: Path
) -> str:
    try:
        record = store.load_session(session_id)
    except StoreError as error:
        raise ContractError(
            f"Workflow operation requires one active {stage} run for this repository."
        ) from error
    if not isinstance(record, dict) or not isinstance(record.get("events"), list):
        raise ContractError(
            f"Workflow operation requires one active {stage} run for this repository."
        )
    events = record["events"]
    expected_repository = repository_digest(str(cwd))
    starts = [
        event for event in events
        if event.get("event_type") == "workflow.stage.started"
        and event.get("stage") == stage
        and event.get("actor") == "runtime"
        and event.get("source") == "devkit_runtime"
        and event.get("payload", {}).get("stage") == stage
        and event.get("payload", {}).get("repository") == expected_repository
        and isinstance(event.get("correlation", {}).get("stage_run_id"), str)
    ]
    active = []
    for start in starts:
        run_id = start["correlation"]["stage_run_id"]
        terminal = any(
            event.get("event_type") in {
                "workflow.stage.completed",
                "workflow.stage.failed",
                "workflow.stage.skipped",
            }
            and event.get("correlation", {}).get("stage_run_id") == run_id
            and event.get("seq", 0) > start.get("seq", 0)
            for event in events
        )
        if not terminal:
            active.append(run_id)
    if len(active) != 1:
        raise ContractError(
            f"Workflow operation requires one active {stage} run for this repository."
        )
    return active[0]

def run() -> Dict[str, Any]:
    request = _read_request()
    cwd = _absolute_cwd(request)
    session_id = _session_id(request)
    _preflight()
    root = trace_root()
    validate_trace_root(root, str(cwd))
    trace_store = ExecutionTraceStore(root)
    operation = request["operation"]

    if operation == "requirements.write":
        _require_active_run(trace_store, session_id, "clarify", cwd)
        sources = tuple(
            RequirementSource.from_dict(value)
            for value in request.get("sources", [])
        )
        supersedes = (
            RequirementDocRef.from_dict(request["supersedes"])
            if request.get("supersedes") is not None
            else None
        )
        reference = RequirementDocumentWriter().write_and_commit(
            repository_root=cwd,
            title=request["title"],
            clarified_requirements=request["clarified_requirements"],
            sources=sources,
            supersedes=supersedes,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "requirement_document",
            "reference": reference.to_dict(),
        }

    purpose = request["purpose"]
    if purpose == "clarify_revision":
        _require_active_run(trace_store, session_id, "clarify", cwd)
    elif purpose == "docs_promotion":
        _require_active_run(trace_store, session_id, "sync-docs", cwd)
    reference = RequirementDocRef.from_dict(request["reference"])
    markdown = RequirementDocumentLoader().load_approved(
        trace_store=trace_store,
        repository_root=cwd,
        reference=reference,
        enforce_repository_source_freshness=(purpose != "clarify_revision"),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "approved_requirement_document",
        "reference": reference.to_dict(),
        "markdown": markdown,
    }
```

For `requirements.write`, convert every source with `RequirementSource.from_dict`; do not pass raw dictionaries into the Writer. Convert a non-null `supersedes` with `RequirementDocRef.from_dict`. The write requires an active Clarify start for the same session and repository; the CLI tests may seed that start directly.

For `requirements.load`, convert `reference` with `RequirementDocRef.from_dict`, require `purpose: design | clarify_revision | docs_promotion`, and scan all validated Trace snapshots through the shared approval gate. `design` enforces repository-source freshness before Design starts. `clarify_revision` skips only cited-source freshness and is accepted only when the authoritative host session has an active Clarify run for the same repository; a caller cannot use the purpose field by itself to bypass Design's drift gate. `docs_promotion` enforces the same document/approval/source freshness as Design and additionally requires an active `sync-docs` run in the authoritative host session for the same repository. It returns the same exact approved Markdown response and cannot be used before Sync Docs starts.

- [x] **Step 5: Run the complete artifact-boundary tests**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.modules.test_execution_trace \
  tests.modules.test_requirement_approval \
  tests.modules.test_requirement_document \
  tests.integration.test_workflow_cli -v
git diff --check
```

Expected: all selected tests pass; old operations produce structured invalid-operation responses; cross-session exact approval succeeds; wrong/mutated artifacts fail.

- [x] **Step 6: Review and commit the artifact handoff slice**

```bash
set -euo pipefail
git add \
  plugins/ai-native-devkit/scripts/ai_native_devkit/workflow_cli.py \
  tests/integration/test_workflow_cli.py
expected=$'plugins/ai-native-devkit/scripts/ai_native_devkit/workflow_cli.py\ntests/integration/test_workflow_cli.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "feat: expose requirement document workflow operations"
```

### Task 6: Bind Clarify lifecycle and approval to the exact document subject

**Files:**

- Modify: `plugins/ai-native-devkit/scripts/ai_native_devkit/runtime_cli.py`
- Modify: `plugins/ai-native-devkit/scripts/ai_native_devkit/execution_trace.py`
- Modify: `tests/integration/test_runtime_trace_and_docs_hook.py`
- Modify: `tests/integration/test_trace_collector_cli.py`
- Modify: `tests/modules/test_execution_trace.py`
- Modify: `tests/integration/test_workflow_cli.py`

**Interfaces:**

- Consumes: Task 1's `RequirementDocRef.from_dict`, Task 3's `RequirementApprovalGate.project` and `RequirementApprovalGate.require_later_user_turn`, Task 4's `RequirementDocumentLoader.verify_current`, and Task 5's artifact CLI boundary.
- Produces: existing runtime operations `stage.start`, `approval.request`, `approval.resolve`, and `stage.complete` for `stage: clarify` and `approval_kind: clarify.requirements`.
- Produces: `approval.requested`, `approval.resolved`, and `workflow.stage.completed` payloads containing the same `approval_id`, `subject_kind: requirement_document`, and canonical `subject_digest`.
- Guarantees: host session identity is authoritative; older approval, wrong subject, absent user-turn evidence, same-turn resolution, and mismatched idempotent completion are rejected.

- [x] **Step 1: Add a real-repository Clarify lifecycle fixture**

Import `date`, `RequirementDocumentWriter`, and `RequirementSource` in `tests/integration/test_runtime_trace_and_docs_hook.py`, then add these helpers to `RuntimeTraceAndDocsHookTests`:

```python
def write_requirement(self, title="Login Policy", requirements="Administrators revoke sessions."):
    return RequirementDocumentWriter(today=lambda: date(2026, 8, 27)).write_and_commit(
        repository_root=self.repository,
        title=title,
        clarified_requirements=requirements,
    )

def record_prompt(self, turn_id, session_id="session-runtime-01"):
    return ExecutionTraceStore(self.state / "execution-traces").append(
        session_id=session_id,
        event_type="turn.prompt_submitted",
        actor="user",
        source="codex_hook",
        stage="clarify",
        correlation={"turn_id": turn_id},
        payload={"prompt_chars": 7},
        context={"cwd": str(self.repository)},
    )

def start_clarify(self, session_id="session-runtime-01"):
    routed = run_cli(self.state, {
        "operation": "workflow.route", "cwd": str(self.repository),
        "intent": "development", "workflow_tier": "strict",
        "route": "development", "change_kind": "feature",
    }, session_id=session_id)
    self.assertEqual(routed.returncode, 0, routed.stdout)
    started = run_cli(self.state, {
        "operation": "stage.start", "stage": "clarify",
        "cwd": str(self.repository),
    }, session_id=session_id)
    self.assertEqual(started.returncode, 0, started.stdout)
    return json.loads(started.stdout)

def request_requirement_approval(self, started, reference, session_id="session-runtime-01"):
    return run_cli(self.state, {
        "operation": "approval.request", "stage": "clarify",
        "stage_run_id": started["stage_run_id"],
        "approval_kind": "clarify.requirements",
        "subject": reference.to_dict(), "cwd": str(self.repository),
    }, session_id=session_id)

def approve_and_complete_requirement(self, started, reference, session_id):
    self.record_prompt("turn-request", session_id)
    requested = json.loads(
        self.request_requirement_approval(started, reference, session_id).stdout
    )
    self.record_prompt("turn-approval", session_id)
    resolved = run_cli(self.state, {
        "operation": "approval.resolve", "approval_id": requested["approval_id"],
        "decision": "approved", "cwd": str(self.repository),
    }, session_id=session_id)
    self.assertEqual(resolved.returncode, 0, resolved.stdout)
    completed = run_cli(self.state, {
        "operation": "stage.complete", "stage": "clarify",
        "stage_run_id": started["stage_run_id"],
        "subject": reference.to_dict(), "cwd": str(self.repository),
    }, session_id=session_id)
    self.assertEqual(completed.returncode, 0, completed.stdout)
    return requested
```

- [x] **Step 2: Write the failing exact-subject happy-path test**

Add this end-to-end runtime case:

```python
def test_clarify_completion_requires_exact_subject_and_later_turn(self):
    self.assertEqual(
        self.route("development", "strict", "development", "feature").returncode,
        0,
    )
    started = json.loads(run_cli(self.state, {
        "operation": "stage.start", "stage": "clarify",
        "cwd": str(self.repository),
    }).stdout)
    self.record_prompt("turn-request")
    reference = self.write_requirement()
    requested = json.loads(run_cli(self.state, {
        "operation": "approval.request", "stage": "clarify",
        "stage_run_id": started["stage_run_id"],
        "approval_kind": "clarify.requirements",
        "subject": reference.to_dict(), "cwd": str(self.repository),
    }).stdout)

    same_turn = run_cli(self.state, {
        "operation": "approval.resolve", "approval_id": requested["approval_id"],
        "decision": "approved", "cwd": str(self.repository),
    })
    self.assertNotEqual(same_turn.returncode, 0)
    self.assertEqual(json.loads(same_turn.stdout)["code"], "rejected.contract")

    self.record_prompt("turn-approval")
    resolved = run_cli(self.state, {
        "operation": "approval.resolve", "approval_id": requested["approval_id"],
        "decision": "approved", "cwd": str(self.repository),
    })
    completed = run_cli(self.state, {
        "operation": "stage.complete", "stage": "clarify",
        "stage_run_id": started["stage_run_id"],
        "subject": reference.to_dict(), "cwd": str(self.repository),
    })
    self.assertEqual(resolved.returncode, 0, resolved.stdout)
    self.assertEqual(completed.returncode, 0, completed.stdout)

    trace = json.loads(run_cli(self.state, {"operation": "trace.load"}).stdout)["trace"]
    terminal = next(
        event for event in trace["events"]
        if event["event_type"] == "workflow.stage.completed"
        and event["stage"] == "clarify"
    )
    self.assertEqual(terminal["payload"]["approval_id"], requested["approval_id"])
    self.assertEqual(terminal["payload"]["subject_kind"], "requirement_document")
    self.assertEqual(terminal["payload"]["subject_digest"], reference.subject_digest())
    serialized = json.dumps(trace)
    for private_token in (
        "markdown", "clarified_requirements", "sources",
        "Administrators revoke sessions.",
    ):
        self.assertNotIn(private_token, serialized)
```

- [x] **Step 3: Add malformed, changed, spoofed, and cross-session cases**

Add these concrete methods beside the happy path. They reuse only the fixture helpers defined in Step 1:

```python
def test_runtime_rejects_non_string_operation_before_dispatch(self):
    trace_root = self.state / "execution-traces"
    for operation in (None, [], {}):
        with self.subTest(operation=operation):
            result = run_cli(self.state, {
                "operation": operation, "cwd": str(self.repository),
            })
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
    self.assertFalse(trace_root.exists())

def test_clarify_rejects_malformed_or_no_longer_current_reference(self):
    started = self.start_clarify()
    self.record_prompt("turn-request")
    first = self.write_requirement()
    variants = (
        {"path": first.path},
        {**first.to_dict(), "commit": "a" * len(first.commit)},
        {**first.to_dict(), "blob_digest": "git-sha1:" + "b" * 40},
    )
    for subject in variants:
        with self.subTest(subject=subject):
            result = run_cli(self.state, {
                "operation": "approval.request", "stage": "clarify",
                "stage_run_id": started["stage_run_id"],
                "approval_kind": "clarify.requirements", "subject": subject,
                "cwd": str(self.repository),
            })
            self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
    RequirementDocumentWriter(today=lambda: date(2026, 8, 27)).write_and_commit(
        repository_root=self.repository, title="Login Policy",
        clarified_requirements="Administrators must record a reason.",
        supersedes=first,
    )
    stale = self.request_requirement_approval(started, first)
    self.assertEqual(json.loads(stale.stdout)["code"], "rejected.contract")

def test_host_session_spoof_is_rejected_before_append(self):
    self.start_clarify()
    before = ExecutionTraceStore(
        self.state / "execution-traces"
    ).load_session("session-runtime-01")["events"]
    result = run_cli(self.state, {
        "operation": "stage.start", "stage": "clarify",
        "cwd": str(self.repository), "session_id": "session-foreign",
    }, session_id="session-runtime-01")
    self.assertEqual(json.loads(result.stdout)["code"], "rejected.contract")
    after = ExecutionTraceStore(
        self.state / "execution-traces"
    ).load_session("session-runtime-01")["events"]
    self.assertEqual(after, before)

def test_later_session_imports_only_the_exact_completed_approval(self):
    session_a = "session-runtime-01"
    started_a = self.start_clarify(session_a)
    self.record_prompt("turn-request", session_a)
    reference = self.write_requirement()
    requested = json.loads(
        self.request_requirement_approval(started_a, reference, session_a).stdout
    )
    self.record_prompt("turn-approval", session_a)
    self.assertEqual(run_cli(self.state, {
        "operation": "approval.resolve", "approval_id": requested["approval_id"],
        "decision": "approved", "cwd": str(self.repository),
    }, session_id=session_a).returncode, 0)
    self.assertEqual(run_cli(self.state, {
        "operation": "stage.complete", "stage": "clarify",
        "stage_run_id": started_a["stage_run_id"],
        "subject": reference.to_dict(), "cwd": str(self.repository),
    }, session_id=session_a).returncode, 0)

    session_b = "session-runtime-02"
    started_b = self.start_clarify(session_b)
    imported = run_cli(self.state, {
        "operation": "stage.complete", "stage": "clarify",
        "stage_run_id": started_b["stage_run_id"],
        "subject": reference.to_dict(), "cwd": str(self.repository),
    }, session_id=session_b)
    self.assertEqual(imported.returncode, 0, imported.stdout)
    terminal = ExecutionTraceStore(
        self.state / "execution-traces"
    ).load_session(session_b)["events"][-1]
    self.assertEqual(terminal["payload"]["approval_id"], requested["approval_id"])
    self.assertEqual(terminal["payload"]["subject_digest"], reference.subject_digest())
    self.assertNotIn("markdown", json.dumps(terminal))

def test_completed_clarify_retry_rejects_a_different_subject(self):
    started = self.start_clarify()
    approved = self.write_requirement(title="Login Policy")
    self.approve_and_complete_requirement(
        started, approved, "session-runtime-01"
    )
    different = self.write_requirement(title="Audit Policy")
    retry = run_cli(self.state, {
        "operation": "stage.complete", "stage": "clarify",
        "stage_run_id": started["stage_run_id"],
        "subject": different.to_dict(), "cwd": str(self.repository),
    })
    self.assertEqual(json.loads(retry.stdout)["code"], "rejected.contract")

def test_local_pending_subject_blocks_cross_session_approval_fallback(self):
    session_a = "session-runtime-01"
    started_a = self.start_clarify(session_a)
    approved = self.write_requirement(title="Login Policy")
    self.approve_and_complete_requirement(started_a, approved, session_a)

    session_b = "session-runtime-02"
    started_b = self.start_clarify(session_b)
    self.record_prompt("turn-request-b", session_b)
    pending = self.write_requirement(title="Audit Policy")
    requested_b = self.request_requirement_approval(
        started_b, pending, session_b
    )
    self.assertEqual(requested_b.returncode, 0, requested_b.stdout)
    fallback = run_cli(self.state, {
        "operation": "stage.complete", "stage": "clarify",
        "stage_run_id": started_b["stage_run_id"],
        "subject": approved.to_dict(), "cwd": str(self.repository),
    }, session_id=session_b)
    self.assertEqual(json.loads(fallback.stdout)["code"], "rejected.contract")

def test_imported_approval_satisfies_full_workflow_finish(self):
    session_a = "session-runtime-01"
    started_a = self.start_clarify(session_a)
    reference = self.write_requirement()
    self.approve_and_complete_requirement(started_a, reference, session_a)

    session_b = "session-runtime-02"
    routed = run_cli(self.state, {
        "operation": "workflow.route", "cwd": str(self.repository),
        "intent": "development", "workflow_tier": "strict",
        "route": "development", "change_kind": "feature",
    }, session_id=session_b)
    self.assertEqual(routed.returncode, 0, routed.stdout)
    store = ExecutionTraceStore(self.state / "execution-traces")

    def append(event_type, stage, run_id, payload):
        store.append(
            session_id=session_b, event_type=event_type,
            actor="runtime", source="devkit_runtime", stage=stage,
            correlation={"stage_run_id": run_id}, payload=payload,
            context={"cwd": str(self.repository)},
        )

    def complete(stage, approval_kind=None):
        run_id = stage + "-run"
        append("workflow.stage.started", stage, run_id, {
            "stage": stage,
            "repository": repository_digest(str(self.repository)),
        })
        if approval_kind is not None:
            approval_id = stage + "-approval"
            append("approval.requested", stage, run_id, {
                "approval_id": approval_id, "approval_kind": approval_kind,
            })
            append("approval.resolved", stage, run_id, {
                "approval_id": approval_id, "approval_kind": approval_kind,
                "decision": "approved",
            })
        if stage == "verify":
            append("verification.completed", stage, run_id, {"passed": True})
        if stage == "sync-docs":
            append("docs.impact.classified", stage, run_id, {
                "docsImpact": "NO_CHANGE", "askHandoff": False,
            })
        append("workflow.stage.completed", stage, run_id, {"stage": stage})

    complete("init")
    started_b = json.loads(run_cli(self.state, {
        "operation": "stage.start", "stage": "clarify",
        "cwd": str(self.repository),
    }, session_id=session_b).stdout)
    imported = run_cli(self.state, {
        "operation": "stage.complete", "stage": "clarify",
        "stage_run_id": started_b["stage_run_id"],
        "subject": reference.to_dict(), "cwd": str(self.repository),
    }, session_id=session_b)
    self.assertEqual(imported.returncode, 0, imported.stdout)
    complete("design", "design.solution")
    complete("plan", "plan.implementation")
    complete("execute")
    complete("verify")
    complete("sync-docs")
    finished = run_cli(self.state, {
        "operation": "workflow.finish", "cwd": str(self.repository),
    }, session_id=session_b)
    self.assertEqual(finished.returncode, 0, finished.stdout)
```

- [x] **Step 4: Write the failing pending-subject test**

```python
def test_pending_request_is_idempotent_only_for_the_same_subject(self):
    started = self.start_clarify()
    self.record_prompt("turn-request")
    reference_a = self.write_requirement(title="Login Policy")
    reference_b = self.write_requirement(title="Audit Policy")
    request_a = json.loads(
        self.request_requirement_approval(started, reference_a).stdout
    )
    request_a_retry = json.loads(
        self.request_requirement_approval(started, reference_a).stdout
    )
    request_b_while_a_pending = self.request_requirement_approval(
        started, reference_b
    )
    self.assertEqual(request_a_retry["approval_id"], request_a["approval_id"])
    self.assertEqual(
        json.loads(request_b_while_a_pending.stdout)["code"],
        "rejected.contract",
    )
```

- [x] **Step 5: Write the deterministic later-turn stop race test**

Import `io`, `mock`, and `ai_native_devkit.runtime_cli as runtime_cli` in `tests/integration/test_runtime_trace_and_docs_hook.py`, then add this deterministic check/write race. It inserts a trusted stop through the same per-session Store immediately before the real resolution append, so the post-append projection—not timing luck—must reject it:

```python
def test_stop_sequenced_before_resolution_is_rejected_by_post_append_projection(self):
    self.route("development", "strict", "development", "feature")
    started = json.loads(run_cli(self.state, {
        "operation": "stage.start", "stage": "clarify",
        "cwd": str(self.repository),
    }).stdout)
    self.record_prompt("turn-request")
    reference = self.write_requirement()
    requested = json.loads(run_cli(self.state, {
        "operation": "approval.request", "stage": "clarify",
        "stage_run_id": started["stage_run_id"],
        "approval_kind": "clarify.requirements",
        "subject": reference.to_dict(), "cwd": str(self.repository),
    }).stdout)
    self.record_prompt("turn-approval")
    original_emit = CollectorService.emit_runtime

    def stop_then_emit(service, value):
        if value.get("event_type") == "approval.resolved":
            service.store.append(
                session_id="session-runtime-01",
                event_type="turn.stopped",
                actor="agent",
                source="codex_hook",
                stage="clarify",
                correlation={"turn_id": "turn-approval"},
                payload={},
                context={"cwd": str(self.repository)},
            )
        return original_emit(service, value)

    request = {
        "schema_version": SCHEMA_VERSION,
        "operation": "approval.resolve",
        "approval_id": requested["approval_id"],
        "decision": "approved",
        "cwd": str(self.repository),
    }
    stdin = io.TextIOWrapper(io.BytesIO(json.dumps(request).encode("utf-8")))
    stdout = io.StringIO()
    with mock.patch.object(CollectorService, "emit_runtime", new=stop_then_emit), \
         mock.patch.object(sys, "stdin", stdin), \
         mock.patch.object(sys, "stdout", stdout), \
         mock.patch.dict(os.environ, {
             "AI_NATIVE_DEVKIT_STATE_ROOT": str(self.state),
             "CODEX_THREAD_ID": "session-runtime-01",
         }, clear=False):
        self.assertEqual(runtime_cli.main(), 1)
    self.assertEqual(json.loads(stdout.getvalue())["code"], "rejected.contract")
    completion = run_cli(self.state, {
        "operation": "stage.complete", "stage": "clarify",
        "stage_run_id": started["stage_run_id"],
        "subject": reference.to_dict(), "cwd": str(self.repository),
    })
    self.assertEqual(json.loads(completion.stdout)["code"], "rejected.contract")
```

- [x] **Step 6: Run the focused runtime tests and verify the red state**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.integration.test_runtime_trace_and_docs_hook \
  tests.integration.test_trace_collector_cli \
  tests.modules.test_execution_trace -v
```

Expected: Clarify start and `clarify.requirements` requests are rejected by the current constants and gates.

- [x] **Step 7: Register Clarify and validate the exact subject**

Update the runtime constants:

```python
RUNTIME_STARTABLE_STAGES = frozenset(
    {"clarify", "design", "plan", "execute", "debug", "verify", "sync-docs", "handoff"}
)
RUNTIME_TERMINAL_STAGES = frozenset(
    {"clarify", "design", "plan", "execute", "debug", "sync-docs", "handoff"}
)
APPROVAL_KIND_BY_STAGE = {
    "clarify": "clarify.requirements",
    "design": "design.solution",
    "plan": "plan.implementation",
    "handoff": "handoff.full_scan",
}
APPROVAL_KINDS_BY_STAGE["clarify"] = frozenset({"clarify.requirements"})
```

For `clarify.requirements`, parse the full request `subject` with `RequirementDocRef.from_dict`, call `RequirementDocumentLoader.verify_current`, and derive the canonical digest. Reject missing `cwd`, wrong repository, unsafe path, missing commit, mismatched blob, or changed document before emitting `approval.requested`.

Use one helper from both approval request and stage completion:

```python
def _require_current_requirement_subject(request, cwd):
    if not isinstance(cwd, str) or not cwd:
        raise ContractError("Requirement approval requires a repository path.")
    reference = RequirementDocRef.from_dict(request.get("subject"))
    try:
        RequirementDocumentLoader().verify_current(
            repository_root=Path(cwd), reference=reference
        )
    except RequirementDocumentError as error:
        raise ContractError("Requirement approval subject is not current.") from error
    return reference, reference.subject_digest()

def _require_runtime_approved_subject(
    *, store, cwd, subject_digest, approval_id=None
):
    try:
        return RequirementApprovalGate().require_subject_approved(
            trace_store=store,
            repository_digest_value=repository_digest(cwd),
            subject_digest=subject_digest,
            approval_id=approval_id,
        )
    except (RequirementApprovalError, RequirementDocumentError) as error:
        raise ContractError("Clarify requires exact approved requirements.") from error
```

This conversion is specific to the runtime lifecycle boundary: every malformed, wrong, stale, missing, or unapproved subject is a `rejected.contract` workflow transition. The artifact CLI in Task 5 continues to expose the more specific `requirements.*` codes for typed drift routing.

Make the host environment authoritative in `_session_id`, so production cannot select another session by request payload while tests without Codex environment variables can still supply an explicit ID:

```python
def _session_id(request: Dict[str, Any]) -> str:
    host = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_TASK_ID")
    supplied = request.get("session_id")
    if host and supplied is not None and supplied != host:
        raise ContractError("Session identity does not match the active Codex task.")
    value = host or supplied
    if not isinstance(value, str) or not value.strip():
        raise ContractError("Runtime operation requires a Codex session identity.")
    return value
```

Also harden the existing runtime `_read_request` dispatch guard before membership lookup:

```python
operation = value.get("operation")
if not isinstance(operation, str) or operation not in OPERATIONS:
    raise ContractError("Runtime operation is invalid.")
```

- [x] **Step 8: Make request and resolution subject-aware**

Emit only:

```python
payload = {
    "approval_id": approval_id,
    "approval_kind": "clarify.requirements",
    "subject_kind": "requirement_document",
    "subject_digest": reference.subject_digest(),
}
```

Before emitting a Clarify approval request, require `_current_turn_id(store, session_id)` to be non-null so the request is correlated with the active user turn; missing hook evidence returns `rejected.contract` without creating an unresolvable pending request. Retrying the same pending subject returns its `approval_id`. A different pending subject is rejected until the first request is resolved. `approval.resolve` copies both subject fields from the request and never accepts them from the caller. Before resolution, compute `later_turn = RequirementApprovalGate.require_later_user_turn(events=_events(store, session_id), request_event=requested)` and require `_current_turn_id(store, session_id) == later_turn`; unlike the old generic behavior, Clarify fails closed when request evidence is missing, the later prompt is absent, or that later user turn has already stopped.

Implement the pending branch with the unresolved request event, not only stage and kind:

```python
def _pending_approval_for_run(
    events: Sequence[Dict[str, Any]], stage_run_id: str, approval_kind: str
) -> Optional[Dict[str, Any]]:
    requests = [
        event for event in events
        if event.get("event_type") == "approval.requested"
        and event.get("correlation", {}).get("stage_run_id") == stage_run_id
        and event.get("payload", {}).get("approval_kind") == approval_kind
    ]
    unresolved = []
    for requested in requests:
        approval_id = requested.get("payload", {}).get("approval_id")
        if not isinstance(approval_id, str):
            raise ContractError("Pending approval request is malformed.")
        resolutions = [
            event for event in events
            if event.get("event_type") == "approval.resolved"
            and event.get("payload", {}).get("approval_id") == approval_id
        ]
        if len(resolutions) > 1:
            raise ContractError("Approval request has duplicate resolutions.")
        if not resolutions:
            unresolved.append(requested)
    if len(unresolved) > 1:
        raise ContractError("Workflow stage has duplicate pending approvals.")
    return unresolved[0] if unresolved else None

def _approval_response(event: Dict[str, Any]) -> Dict[str, Any]:
    payload = event["payload"]
    correlation = event["correlation"]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "approval_request",
        "trace_id": event["trace_id"],
        "stage": event["stage"],
        "stage_run_id": correlation["stage_run_id"],
        "approval_id": payload["approval_id"],
    }

pending = _pending_approval_for_run(events, stage_run_id, "clarify.requirements")
if pending is not None:
    if pending["payload"].get("subject_digest") != subject_digest:
        raise ContractError("Resolve the pending requirement approval before replacing it.")
    return _approval_response(pending)
turn_id = _current_turn_id(store, session_id)
if turn_id is None:
    raise ContractError("Requirement approval requires active user-turn evidence.")
requested = collector.emit_runtime({
    "session_id": session_id,
    "event_type": "approval.requested",
    "stage": "clarify",
    "correlation": {"stage_run_id": stage_run_id, "turn_id": turn_id},
    "cwd": cwd,
    "payload": {
        "approval_id": str(uuid.uuid4()),
        "approval_kind": "clarify.requirements",
        "subject_kind": "requirement_document",
        "subject_digest": subject_digest,
    },
})["event"]
```

In `approval.resolve`, build the payload by copying `approval_kind`, `subject_kind`, and `subject_digest` from `requested["payload"]`, and set correlation to the helper-validated active `later_turn`. After either appending a new resolution or finding an idempotent existing one, reload the current record, project the exact `approval_id`, and require one attempt whose `decision` equals the requested decision and whose `later_user_turn` is true. The per-session append lock gives the resolution and any concurrent `turn.stopped` a total event order: a stop sequenced before resolution makes this post-append projection fail with `rejected.contract`; a stop sequenced after resolution does not retroactively invalidate the user decision. The failed response leaves an auditable invalid resolution event and Clarify active; the next request uses a new approval ID.

```python
if resolved is None:
    resolved = collector.emit_runtime(resolution_request)["event"]
record = store.load_session(session_id)
attempts = [
    attempt for attempt in RequirementApprovalGate.project([record])
    if attempt.approval_id == approval_id
]
if (
    len(attempts) != 1
    or attempts[0].decision != decision
    or not attempts[0].later_user_turn
):
    raise ContractError("Approval resolution did not occur in an active later user turn.")
```

- [x] **Step 9: Make stage and workflow completion subject-aware**

For Clarify `stage.complete`, require `subject`, re-run current Git verification, and use `RequirementApprovalGate.project` over the current trace to require the latest request on the run to resolve `approved`. Emit its `approval_id`, `subject_kind`, and `subject_digest` on `workflow.stage.completed`. On a terminal retry, recompute the supplied digest and require equality with the terminal event.

Use this selection before emitting the terminal event:

```python
record = store.load_session(session_id)
run_attempts = [
    attempt for attempt in RequirementApprovalGate.project([record])
    if attempt.stage_run_id == stage_run_id
]
attempt = max(run_attempts, key=lambda item: item.request_seq, default=None)
if attempt is not None:
    if (
        attempt.subject_digest != subject_digest
        or attempt.decision != "approved"
        or not attempt.later_user_turn
    ):
        raise ContractError("Clarify completion requires exact approved requirements.")
else:
    attempt = _require_runtime_approved_subject(
        store=store, cwd=cwd, subject_digest=subject_digest
    )
payload.update({
    "approval_id": attempt.approval_id,
    "subject_kind": "requirement_document",
    "subject_digest": subject_digest,
})
```

For a local first completion, `attempt.terminal` is expected to be false because the completion event has not yet been emitted. If the current run has no approval request, the fallback permits `$coding-sop` to materialize Clarify completion from a completed exact approval in another validated Trace; any local pending/rejected/changes-requested attempt blocks that fallback. `workflow.finish` reads the current Clarify terminal and calls `_require_runtime_approved_subject` with the current repository, terminal `subject_digest`, and terminal `approval_id`; this verifies either the local original attempt or the exact imported attempt through the same global projection while keeping runtime failures at `rejected.contract`.

Change workflow completion from the old kind to `clarify.requirements`. For a local flow, the shared projection requires request → approved resolution → completion to share `stage_run_id`, `approval_id`, and `subject_digest` in order. For an imported flow, the current Trace contains only its own Clarify start/terminal with the current `stage_run_id`; the terminal's exact `approval_id` and `subject_digest` must resolve through `require_subject_approved` to an original completed attempt in another Trace, whose `stage_run_id` is expected to differ. Never require or fabricate cross-Trace run-ID equality.

- [x] **Step 10: Extend the trace projection without new event types**

Keep the existing event registry. Project optional `subject_kind` and `subject_digest` into the Clarify stage and approval summaries. Do not project the caller's full `subject` object.

```python
for field in ("approval_id", "subject_kind", "subject_digest"):
    value = payload.get(field)
    if isinstance(value, str):
        run[field] = value
```

Keep the existing approval summary's `**payload` projection; the runtime payload is already the privacy allow-list asserted in Step 2.

- [x] **Step 11: Make the runtime suite green**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.integration.test_runtime_trace_and_docs_hook \
  tests.integration.test_trace_collector_cli \
  tests.modules.test_execution_trace \
  tests.integration.test_workflow_cli -v
git diff --check
```

Expected: all selected tests pass, including changed-document invalidation and later-turn approval.

- [x] **Step 12: Review and commit the runtime approval slice**

```bash
set -euo pipefail
git add \
  plugins/ai-native-devkit/scripts/ai_native_devkit/runtime_cli.py \
  plugins/ai-native-devkit/scripts/ai_native_devkit/execution_trace.py \
  tests/integration/test_runtime_trace_and_docs_hook.py \
  tests/integration/test_trace_collector_cli.py \
  tests/integration/test_workflow_cli.py \
  tests/modules/test_execution_trace.py
expected=$'plugins/ai-native-devkit/scripts/ai_native_devkit/execution_trace.py\nplugins/ai-native-devkit/scripts/ai_native_devkit/runtime_cli.py\ntests/integration/test_runtime_trace_and_docs_hook.py\ntests/integration/test_trace_collector_cli.py\ntests/integration/test_workflow_cli.py\ntests/modules/test_execution_trace.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "feat: bind clarify approval to git identity"
```

### Task 7: Rewrite Clarify and Design around the Superpowers-aligned handoff

**Files:**

- Create: `plugins/ai-native-devkit/skills/sop-clarify/references/upstream-superpowers-brainstorming.md`
- Modify: `plugins/ai-native-devkit/skills/sop-clarify/SKILL.md`
- Modify: `plugins/ai-native-devkit/skills/sop-design/SKILL.md`
- Modify: `plugins/ai-native-devkit/skills/sop-sync-docs/SKILL.md`
- Modify: `plugins/ai-native-devkit/skills/coding-sop/SKILL.md`
- Modify: `plugins/ai-native-devkit/skills/coding-sop/references/workflow-contract.md`
- Modify: `plugins/ai-native-devkit/skills/coding-sop/references/execution-trace.md`
- Modify: `THIRD_PARTY_NOTICES.md`
- Modify: `plugins/ai-native-devkit/THIRD_PARTY_NOTICES.md`
- Modify: `tests/test_skill_contract.py`
- Modify: `tests/test_development_skills.py`

**Interfaces:**

- Consumes: Task 1's exact `RequirementDocRef`/Writer, Task 3's approval projection, Task 4's Loader, Task 5's artifact CLI, and Task 6's runtime `stage.start/complete` plus `approval.request/resolve` behavior.
- Produces from `$sop-clarify`: confirmed prose and optional `RequirementSource` entries, then one committed and approved `RequirementDocRef`; when invoked with `supersedes`, revises only that exact document.
- Produces from `$sop-design`: an approved design derived only from `requirements.load`; requirement-document drift and cited-source drift each produce a distinct typed return-to-Clarify handoff before Design starts.
- Guarantees: the source fork is self-contained and auditable without invoking `superpowers:brainstorming` at runtime.

- [x] **Step 1: Replace the old Skill assertions with failing behavior and provenance tests**

In `tests/test_development_skills.py` and `tests/test_skill_contract.py`, require these exact upstream lines in `sop-clarify/SKILL.md`:

```python
UPSTREAM_LINES = (
    "Check out the current project state first (files, docs, recent commits)",
    "Before asking detailed questions, assess scope: if the request describes multiple independent subsystems (e.g., \"build a platform with chat, file storage, billing, and analytics\"), flag this immediately. Don't spend questions refining details of a project that needs to be decomposed first.",
    "For appropriately-scoped projects, ask questions one at a time to refine the idea",
    "Prefer multiple choice questions when possible, but open-ended is fine too",
    "Only one question per message - if a topic needs more exploration, break it into multiple questions",
    "Focus on understanding: purpose, constraints, success criteria",
)
ADAPTED_DECOMPOSITION = (
    "If the project is too large for a single requirements document, help the user "
    "decompose into sub-projects: what are the independent pieces, how do they relate, "
    "what order should they be built? Then clarify the first sub-project through this "
    "requirement-understanding flow. Each sub-project gets its own requirements → design "
    "→ plan → implementation cycle."
)
```

Add these literal contract methods after the constants above:

```python
def test_clarify_reuses_only_the_upstream_requirement_understanding_behavior(self):
    clarify = (SKILLS / "sop-clarify/SKILL.md").read_text()
    for line in UPSTREAM_LINES:
        self.assertIn(line, clarify)
    self.assertIn(ADAPTED_DECOMPOSITION, clarify)
    for token in (
        "requirements.write", "clarify.requirements", "RequirementDocRef",
        "approval.resolve", "stage.complete", "purpose: clarify_revision",
        "supersedes", "stop the current assistant turn",
        "a later user-authored response",
        "[upstream-superpowers-brainstorming.md](references/upstream-superpowers-brainstorming.md)",
    ):
        self.assertIn(token, clarify)
    for forbidden in (
        "clarification.checkpoint", "ClarificationResult",
        "Three Paths", "approach exploration", "solution design",
        "spec authoring", "implementation planning",
    ):
        self.assertNotIn(forbidden, clarify)
    self.assertIn(
        "Never invoke `superpowers:brainstorming` at runtime.", clarify
    )
    self.assertIn(
        "Do not create a checkpoint,\nstructured baseline", clarify
    )
    self.assertNotIn(
        "REQUIRED SUB-SKILL: Use superpowers:brainstorming", clarify
    )
    self.assertLess(clarify.index("Check out the current project state first"),
                    clarify.index("ask questions one at a time"))
    self.assertLess(clarify.index("requirements.write"),
                    clarify.index("approval.request"))

def test_design_loads_exact_approval_before_design_and_maps_drift(self):
    design = (SKILLS / "sop-design/SKILL.md").read_text()
    for token in (
        "RequirementDocRef", "requirements.load", "purpose: design",
        "requirements.source_drift", "requirements_source_drift",
        "requirements.document_worktree_drift", "requirements.document_index_drift",
        "requirements.document_committed_drift", "requirements.document_missing",
        "requirements_document_drift", "changed", "unavailable",
        "version_uncomparable", "worktree", "index", "committed", "missing",
        ".scratch/ai-native-devkit/tasks/requirement-<64-hex>/design.md",
        "refuse to overwrite", "full RequirementDocRef",
    ):
        self.assertIn(token, design)
    for forbidden in ("task_id", "ClarificationResult", "clarification_ref"):
        self.assertNotIn(forbidden, design)
    self.assertLess(design.index("requirements.load"), design.index("stage.start"))

def test_router_and_docs_sync_use_the_exact_handoff_sequences(self):
    router = (SKILLS / "coding-sop/SKILL.md").read_text()
    sync = (SKILLS / "sop-sync-docs/SKILL.md").read_text()
    for token in (
        "stage.start(clarify)", "stage.complete(clarify, exact subject)",
        "requirements.load(purpose: design)", "requirements_source_drift",
        "requirements_document_drift", "purpose: clarify_revision",
        "without supersedes", "suffixed new path",
    ):
        self.assertIn(token, router)
    self.assertLess(router.index("stage.complete(clarify, exact subject)"),
                    router.index("requirements.load(purpose: design)"))
    self.assertLess(router.index("requirements.load(purpose: design)"),
                    router.index("stage.start(design)"))
    self.assertIn("stage.start", sync)
    self.assertIn("stage: sync-docs", sync)
    self.assertIn("requirements.load", sync)
    self.assertIn("purpose: docs_promotion", sync)
    self.assertIn("exact approved RequirementDocRef", sync)
    self.assertLess(sync.index("stage.start"), sync.index("purpose: docs_promotion"))

def test_packaged_provenance_is_linked_and_independent(self):
    clarify = (SKILLS / "sop-clarify/SKILL.md").read_text()
    provenance = (
        SKILLS / "sop-clarify/references/upstream-superpowers-brainstorming.md"
    ).read_text()
    self.assertIn("references/upstream-superpowers-brainstorming.md", clarify)
    for token in (
        "obra/superpowers", "superpowers@6.3.0",
        "skills/brainstorming/SKILL.md", "Understanding the idea",
        "MIT", "Jesse Vincent",
    ):
        self.assertIn(token, provenance)
    self.assertIn(
        "Never invoke `superpowers:brainstorming` at runtime.", clarify
    )
    self.assertNotIn(
        "REQUIRED SUB-SKILL: Use superpowers:brainstorming", clarify
    )
```

- [x] **Step 2: Run the contract tests and verify they fail on the checkpoint Skill**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.test_skill_contract \
  tests.test_development_skills -v
```

Expected: failures show missing upstream wording and the presence of old checkpoint/result tokens.

- [x] **Step 3: Add the packaged upstream provenance record**

Create `references/upstream-superpowers-brainstorming.md` with:

```markdown
# Upstream provenance: Superpowers brainstorming

- Repository: `https://github.com/obra/superpowers`
- Packaged source version: `superpowers@6.3.0`
- Source file: `skills/brainstorming/SKILL.md`
- Reused section: `Understanding the idea`
- License: MIT
- Copyright: Copyright (c) 2025 Jesse Vincent

AI Native DevKit packages adapted Skill text and behavior. It does not import,
invoke, or require the Superpowers plugin at runtime.
```

Update both `THIRD_PARTY_NOTICES.md` copies with the same version, file, and reused section, then assert the two notice files remain byte-identical.

- [x] **Step 4: Rewrite `$sop-clarify` as the narrow interview Skill**

Replace `sop-clarify/SKILL.md` with this complete file:

````markdown
---
name: sop-clarify
description: Clarify goals, scope, constraints, success criteria, and domain decisions into one minimal committed requirements document with exact later-turn approval.
---

# SOP Clarify

Use this Skill only for requirement understanding. `$coding-sop` owns the
workflow. Resolve `PLUGIN_ROOT` from this Skill directory as `../..`,
`RUNTIME_CLI` as `PLUGIN_ROOT/scripts/runtime_cli.py`, and `WORKFLOW_CLI` as
`PLUGIN_ROOT/scripts/workflow_cli.py`; invoke both with `python3` and bounded
JSON on standard input. Never invoke `superpowers:brainstorming` at runtime.

This behavior adapts Superpowers 6.3.0. See
[upstream-superpowers-brainstorming.md](references/upstream-superpowers-brainstorming.md)
for source and license provenance.

## Understanding the idea

- Check out the current project state first (files, docs, recent commits)
- Before asking detailed questions, assess scope: if the request describes multiple independent subsystems (e.g., "build a platform with chat, file storage, billing, and analytics"), flag this immediately. Don't spend questions refining details of a project that needs to be decomposed first.
- If the project is too large for a single requirements document, help the user decompose into sub-projects: what are the independent pieces, how do they relate, what order should they be built? Then clarify the first sub-project through this requirement-understanding flow. Each sub-project gets its own requirements → design → plan → implementation cycle.
- For appropriately-scoped projects, ask questions one at a time to refine the idea
- Prefer multiple choice questions when possible, but open-ended is fine too
- Only one question per message - if a topic needs more exploration, break it into multiple questions
- Focus on understanding: purpose, constraints, success criteria

Do not explore approaches, design solutions, architecture, interfaces, specs,
tests, implementation steps, risks, or plans here. Do not create a checkpoint,
structured baseline, transcript, task artifact, or repository file while any
requirement question remains open. An interrupted pre-document interview can
continue only in this original Codex conversation.

## Start and interview

At entry, call `stage.start` with `stage: clarify`, the absolute repository
`cwd`, and no fabricated session ID if there is no active Clarify run. Inspect
only project context needed for the request. Record sources in working memory
only when they actually support a confirmed requirement:

- repository: repository-relative path, exact Git revision, and supported fact;
- external: stable HTTPS URL, resource URI, or opaque resource ID, recorded
  version or sync time, and supported fact.

Ask one question per assistant message. Continue until purpose, scope,
constraints, success criteria, and required domain decisions have no blocking
ambiguity. The confirmed prose is natural language, not a schema.

## Write the completed requirement

Only after the interview is complete, call `requirements.write`:

```json
{
  "schema_version": "ai-native-devkit/v1alpha1",
  "operation": "requirements.write",
  "cwd": "/absolute/repository",
  "title": "confirmed topic",
  "clarified_requirements": "confirmed requirement prose only",
  "sources": []
}
```

For an in-conversation revision, add `supersedes` with the exact previously
returned `RequirementDocRef`. Never pass a path alone. The response must be
`kind: requirement_document` with exact `path`, `commit`, and
algorithm-qualified `blob_digest`.

Present the committed file and exact reference. Do not add approval metadata
to the file or create another baseline.

## Request and resolve exact approval

Call `approval.request` with `stage: clarify`, the active `stage_run_id`,
`approval_kind: clarify.requirements`, and the exact reference as `subject`.
Present that approval ID and committed file, ask for approval, and stop the
current assistant turn.

The original request, silence, broad autonomy, an Agent-authored confirmation,
or a response in the request turn is not approval. Only a later user-authored
response may be passed to `approval.resolve` for that exact `approval_id`:

- `approved`: resolve, then call `stage.complete` with `stage: clarify`, the
  active run ID, and the same exact reference as `subject`;
- `changes_requested`: keep Clarify active, ask only affected questions, and
  call `requirements.write` with the already-held exact reference as
  `supersedes`; do not call the approved-only Loader for this decision;
- `rejected`: resolve, keep Clarify active, do not complete it, and wait for
  explicit user direction.

Every changed requirement creates a new commit and a new approval request.
Never amend or reuse the earlier approval.

## Explicit revision and drift entry modes

For an explicitly supplied approved reference whose cited source drifted, start
Clarify and call `requirements.load` with `purpose: clarify_revision`. Ask only
questions affected by the source change, then write with that exact reference
as `supersedes` and request a new approval. Never discover a reference by path
or recency.

For `requirements_document_drift`, the old reference is not current and cannot
be loaded or superseded. Start Clarify in `document_drift` mode, inspect the
changed or missing path only as repository state, re-confirm every affected
requirement, then call initial `requirements.write` without `supersedes`. The
Writer must choose a suffixed new path. Never restore, overwrite, or treat the
changed historical path as approved input.

Return the exact pending approval or completed `RequirementDocRef` to
`$coding-sop`. Do not enter Design, Plan, Execute, Docs Sync, or Handoff here.
````

- [x] **Step 5: Rewrite `$sop-design` to load before starting**

Replace the existing requirement-input, resume, and local-draft sections with this exact content; retain the existing approach exploration and `design.solution` approval sections after it:

````markdown
## Load the only design input

Require one complete `RequirementDocRef` containing `path`, `commit`, and
algorithm-qualified `blob_digest`. Reject a path alone, chat prose, a task ID,
`ClarificationResult`, `clarification_ref`, or any attempt to reconstruct input
from conversation history.

Before `stage.start(design)`, call the packaged workflow CLI:

```json
{
  "schema_version": "ai-native-devkit/v1alpha1",
  "operation": "requirements.load",
  "cwd": "/absolute/repository",
  "purpose": "design",
  "reference": {"path": "...", "commit": "...", "blob_digest": "git-sha1:..."}
}
```

The exact reference may have completed approval in another validated Codex
Execution Trace for the same repository only because the caller explicitly
supplied it. Never select a recent path or approval.

Map Loader failures before Design starts:

| Loader code | Result kind | Reason |
|---|---|---|
| `requirements.document_worktree_drift` | `requirements_document_drift` | `worktree` |
| `requirements.document_index_drift` | `requirements_document_drift` | `index` |
| `requirements.document_committed_drift` | `requirements_document_drift` | `committed` |
| `requirements.document_missing` | `requirements_document_drift` | `missing` |
| `requirements.source_drift` | `requirements_source_drift` | `changed` |

Every typed result contains the exact input `reference`. A document-drift
result returns to fresh Clarify `document_drift` mode without `supersedes`; the
changed or deleted historical path is neither restored nor reused. A source
drift result returns to Clarify with that exact reference as `supersedes`.

For each external source line, route its HTTPS URL, `resource://` URI, or
preserved opaque resource ID to the mechanism that supplied it. Re-read it and
compare the recorded version or sync time. Return
`requirements_source_drift` with `reason: changed` for a different value,
`reason: unavailable` for an inaccessible or unroutable locator, or
`reason: version_uncomparable` when no stable comparison exists. Do not call
`stage.start(design)` for any of those results.

Only after the exact approved Markdown and every source are current, call
`stage.start` with `stage: design`, then perform the existing solution-design
and `design.solution` approval flow.

## Optional ignored design view

Compute `RequirementDocRef.subject_digest()` and use all 64 hex characters in
`.scratch/ai-native-devkit/tasks/requirement-<64-hex>/design.md`. Write only
when that exact path is already ignored. Put the full reference in the header
and refuse to overwrite a file whose header names a different reference. This
view is never authority, never reconstructs resume state, is never committed,
and never changes `.gitignore`. Otherwise return the design only in Codex.
````

- [x] **Step 6: Propagate the handoff through router and Docs Sync guidance**

Insert this verbatim in `$coding-sop` and both workflow references:

```markdown
## Exact Clarify handoff

- normal: `stage.start(clarify) -> interview -> requirements.write -> approval.request/resolve -> stage.complete(clarify, exact subject) -> requirements.load(purpose: design) -> stage.start(design)`
- later task with explicit approved ref: `stage.start(clarify) -> stage.complete(clarify, exact subject) -> requirements.load(purpose: design) -> stage.start(design)`; import the exact completed approval, do not replay the interview or request approval again
- cited-source drift: `requirements_source_drift -> stage.start(clarify) -> requirements.load(purpose: clarify_revision) -> requirements.write with exact supersedes -> new approval`
- requirement-document drift: `requirements_document_drift -> stage.start(clarify, document_drift) -> inspect and re-confirm -> requirements.write without supersedes -> suffixed new path -> new approval`

A local request, resolution, and Clarify terminal share one `stage_run_id`. An
imported terminal uses the current Clarify run ID and cites the exact
`approval_id + subject_digest` of an original completed attempt whose run ID may
differ. `$coding-sop` remains the only top-level orchestrator.
```

Replace the requirement-provenance paragraph in `$sop-sync-docs` with:

```markdown
When promotion uses a requirements workflow record, first call `stage.start`
with `stage: sync-docs`. Then call `requirements.load` with
`purpose: docs_promotion` and the exact approved `RequirementDocRef`. Record
its Git path, commit, and blob identity in decision provenance. Do not use
`purpose: design`, `purpose: clarify_revision`, a TaskStateStore artifact, a
path alone, or chat prose as promotion authority.
```

- [x] **Step 7: Run Skill tests and quick validation for every touched Skill**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.test_skill_contract \
  tests.test_development_skills -v

python3 /Users/didi/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  plugins/ai-native-devkit/skills/coding-sop
python3 /Users/didi/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  plugins/ai-native-devkit/skills/sop-clarify
python3 /Users/didi/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  plugins/ai-native-devkit/skills/sop-design
python3 /Users/didi/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  plugins/ai-native-devkit/skills/sop-sync-docs
git diff --check
```

Expected: tests and all four validators exit 0; the Clarify Skill contains the locked upstream lines and none of the old runtime contract.

- [x] **Step 8: Review and commit the Skill slice**

```bash
set -euo pipefail
git add \
  THIRD_PARTY_NOTICES.md \
  plugins/ai-native-devkit/THIRD_PARTY_NOTICES.md \
  plugins/ai-native-devkit/skills/coding-sop/SKILL.md \
  plugins/ai-native-devkit/skills/coding-sop/references/execution-trace.md \
  plugins/ai-native-devkit/skills/coding-sop/references/workflow-contract.md \
  plugins/ai-native-devkit/skills/sop-clarify/SKILL.md \
  plugins/ai-native-devkit/skills/sop-clarify/references/upstream-superpowers-brainstorming.md \
  plugins/ai-native-devkit/skills/sop-design/SKILL.md \
  plugins/ai-native-devkit/skills/sop-sync-docs/SKILL.md \
  tests/test_skill_contract.py \
  tests/test_development_skills.py
expected=$'THIRD_PARTY_NOTICES.md\nplugins/ai-native-devkit/THIRD_PARTY_NOTICES.md\nplugins/ai-native-devkit/skills/coding-sop/SKILL.md\nplugins/ai-native-devkit/skills/coding-sop/references/execution-trace.md\nplugins/ai-native-devkit/skills/coding-sop/references/workflow-contract.md\nplugins/ai-native-devkit/skills/sop-clarify/SKILL.md\nplugins/ai-native-devkit/skills/sop-clarify/references/upstream-superpowers-brainstorming.md\nplugins/ai-native-devkit/skills/sop-design/SKILL.md\nplugins/ai-native-devkit/skills/sop-sync-docs/SKILL.md\ntests/test_development_skills.py\ntests/test_skill_contract.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "feat: align clarification with superpowers"
```

### Task 8: Remove the checkpoint/result compatibility path and release 0.4 contracts

**Files:**

- Delete: `plugins/ai-native-devkit/scripts/ai_native_devkit/clarification.py`
- Delete: `tests/modules/test_clarification_runtime.py`
- Create: `tests/init_fixtures.py`
- Delete: `tests/clarification_fixtures.py`
- Modify: `plugins/ai-native-devkit/scripts/ai_native_devkit/contracts.py`
- Modify: `plugins/ai-native-devkit/scripts/ai_native_devkit/state_store.py`
- Modify: `plugins/ai-native-devkit/scripts/ai_native_devkit/__init__.py`
- Modify: `plugins/ai-native-devkit/.codex-plugin/plugin.json`
- Modify: `tests/modules/test_cli_preflight.py`
- Modify: `tests/contract/test_contracts.py`
- Modify: `tests/contract/test_task_state_store.py`
- Modify: `tests/test_plugin_contract.py`
- Modify: `tests/test_end_to_end_contract.py`

**Interfaces:**

- Consumes: the new Git artifact, approval, Loader, artifact CLI, and runtime path from Tasks 1–6; existing `TaskStateStore` Init contracts and compatibility tests.
- Produces: `ARTIFACT_TYPES` without the two old clarification artifact names and `ALLOWED_TRANSITIONS` without `("ContextReady", "Clarified")`.
- Produces: remaining TaskStateStore behavior compatible with unknown fields, valid Init artifacts, and supported historical non-clarification producers.
- Produces: package, manifest, workflow producer, and new TaskStateStore envelopes at `0.4.0`. This pre-1.0 minor bump identifies the clean break required by the approved spec.

- [x] **Step 1: Write the breaking-contract tests before deleting code**

Add assertions that:

```python
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
self.assertNotIn(("ContextReady", "Clarified"), ALLOWED_TRANSITIONS)
```

Update the plugin contract expectation to `0.4.0`, and keep its existing assertion that manifest, package, workflow producer, and TaskStateStore producer versions match.

- [x] **Step 2: Run focused tests and verify they fail while old contracts remain**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.contract.test_contracts \
  tests.contract.test_task_state_store \
  tests.test_plugin_contract -v
```

Expected: old artifact types and `ContextReady -> Clarified` are still accepted, and version assertions still see `0.3.0`.

- [x] **Step 3: Remove the old contract registration and dataclasses**

Delete `ClarificationCheckpoint`, `ClarificationResult`, and both artifact names from `contracts.py`. Remove `("ContextReady", "Clarified")` and the clarification field constants from `state_store.py`.

- [x] **Step 4: Run contract tests after the registry removal**

Run: `python3 -m unittest tests.contract.test_contracts tests.contract.test_task_state_store -v`

Expected: the new removal assertions pass; failures now point only to clarification-specific payload/history code that imports or expects the deleted registrations.

- [x] **Step 5a: Remove clarification input-reference and fact helpers**

Delete the `clarification_checkpoint` and `clarification_result` branches in `_payload_input_refs`; delete `clarification_content`, `CLARIFICATION_CONTENT_FIELDS`, `CLARIFICATION_RUNTIME_FIELDS`, and `LEGACY_DRAFT_APPROVAL_PRODUCERS`. Run `python3 -m unittest tests.contract.test_task_state_store -v`; expected failures remain limited to payload, batch, and replay/history cases.

- [x] **Step 5b: Remove checkpoint/result payload validators**

Delete the two clarification branches in `_validate_payload` and delete `_validate_clarification_payload`. Do not alter validation for any remaining artifact type. Rerun `python3 -m unittest tests.contract.test_task_state_store -v`; expected failures remain limited to batch and replay/history cases.

- [x] **Step 5c: Remove clarification batch and approval-evidence branches**

Delete only these remaining clarification branches from `_validate_batch_invariants` and `_validate_evidence_payload`:

- draft/approval/result batch invariants;
- `approval` from the allowed `EvidenceRecord.kind` set and its clarification-only metadata/artifact-ref branch.

After these callers and Step 5b's payload caller are gone, use `rg` to prove `_validate_string_collection`, `_validate_fact_sources`, and `_validate_decision_dependencies` have no remaining caller, then delete those three private helpers.

Do not weaken the remaining malformed-core-field, transition, reference, provenance, repository-revision, concurrency, or unknown-field tests.

- [x] **Step 6: Run TaskStateStore tests after payload cleanup**

Run: `python3 -m unittest tests.contract.test_task_state_store -v`

Expected: remaining failures identify only old clarification replay/history assertions in the test file or implementation.

- [x] **Step 7a: Remove clarification replay collections and linkage checks**

Delete `clarification_results`, checkpoint/result replay collections, the legacy-producer exception, and approval/result linkage from `_validate_artifact_history`. Run `python3 -m unittest tests.contract.test_task_state_store -v` and confirm only old `Clarified` atomicity cases fail.

- [x] **Step 7b: Remove old Clarified atomicity checks and tests**

Delete the `Clarified` transition atomicity checks and only their corresponding old test cases. Retain every Init, corruption, reference, concurrency, and unknown-field case.

- [x] **Step 8: Run the full contract store suite**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.contract.test_contracts \
  tests.contract.test_task_state_store -v
```

Expected: PASS.

- [x] **Step 9: Delete the old runtime and preserve Init-only fixtures**

Delete `clarification.py` and `tests/modules/test_clarification_runtime.py`. Move only `FIXED_REVISION` and `ReadyInspector` from `tests/clarification_fixtures.py` to `tests/init_fixtures.py`, update `tests/modules/test_cli_preflight.py`, then delete the misleading old fixture module.

Do not delete or recreate `workflow_cli.py`; Task 5 already replaced it with the new artifact boundary.

- [x] **Step 10: Bump the package contract to 0.4.0**

Update exactly:

```python
# ai_native_devkit/__init__.py
__version__ = "0.4.0"

# contracts.py
PRODUCER = "ai-native-devkit/workflow-runtime@0.4.0"
```

Set `.codex-plugin/plugin.json` to `0.4.0` and update the TaskStateStore producer used for new transition/materialization envelopes. Keep reading valid older non-clarification Init artifacts when the existing compatibility rules permit it.

- [x] **Step 11: Update clean-package assertions without installing the plugin**

Import `sys`, retain the packaged `scripts/workflow_cli.py` assertion, and replace the old clarification smoke with this isolated copied-package flow; it does not call `codex plugin add`:

```python
def test_copied_package_requirement_flow_preserves_external_state(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        installed_root = root / "copied-plugin"
        shutil.copytree(PLUGIN, installed_root)
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
```

- [x] **Step 12: Run the clean-break tests and scan runtime/Skill code for old symbols**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.contract.test_contracts \
  tests.contract.test_task_state_store \
  tests.modules.test_cli_preflight \
  tests.test_plugin_contract \
  tests.test_end_to_end_contract -v

if matches="$(rg -n \
  'ClarificationCheckpoint|ClarificationResult|ClarificationRuntime|clarification\.(checkpoint|checkpoint\.load|approval\.request|finalize|load)|clarification_checkpoint|clarification_result|clarification_ref|clarify\.baseline' \
  plugins/ai-native-devkit/scripts \
  plugins/ai-native-devkit/skills/coding-sop \
  plugins/ai-native-devkit/skills/sop-clarify \
  plugins/ai-native-devkit/skills/sop-design \
  plugins/ai-native-devkit/skills/sop-sync-docs/SKILL.md)"; then
  printf '%s\n' "$matches"
  exit 1
elif test "$?" -ne 1; then
  exit 1
fi
git diff --check
```

Expected: selected tests pass; the runtime and lifecycle-Skill scan produces no
matches; no external state file is altered. The `sop-init` decision template and
the Docs Sync promotion validator still carry their historical artifact
provenance until Task 9 replaces both and runs the package-wide scan.

- [x] **Step 13: Review and commit the clean break**

```bash
set -euo pipefail
git add -A -- \
  plugins/ai-native-devkit/.codex-plugin/plugin.json \
  plugins/ai-native-devkit/scripts/ai_native_devkit/__init__.py \
  plugins/ai-native-devkit/scripts/ai_native_devkit/clarification.py \
  plugins/ai-native-devkit/scripts/ai_native_devkit/contracts.py \
  plugins/ai-native-devkit/scripts/ai_native_devkit/state_store.py \
  tests/clarification_fixtures.py \
  tests/init_fixtures.py \
  tests/contract/test_contracts.py \
  tests/contract/test_task_state_store.py \
  tests/modules/test_clarification_runtime.py \
  tests/modules/test_cli_preflight.py \
  tests/test_plugin_contract.py \
  tests/test_end_to_end_contract.py
expected=$'plugins/ai-native-devkit/.codex-plugin/plugin.json\nplugins/ai-native-devkit/scripts/ai_native_devkit/__init__.py\nplugins/ai-native-devkit/scripts/ai_native_devkit/clarification.py\nplugins/ai-native-devkit/scripts/ai_native_devkit/contracts.py\nplugins/ai-native-devkit/scripts/ai_native_devkit/state_store.py\ntests/clarification_fixtures.py\ntests/contract/test_contracts.py\ntests/contract/test_task_state_store.py\ntests/init_fixtures.py\ntests/modules/test_clarification_runtime.py\ntests/modules/test_cli_preflight.py\ntests/test_end_to_end_contract.py\ntests/test_plugin_contract.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "refactor: remove clarification task state"
```

### Task 9: Change decision promotion and project templates to Git provenance

**Files:**

- Modify: `plugins/ai-native-devkit/skills/sop-init/SKILL.md`
- Modify: `plugins/ai-native-devkit/skills/sop-init/references/init-contract.md`
- Modify: `plugins/ai-native-devkit/skills/sop-sync-docs/scripts/validate_promoted_decision.py`
- Modify: `plugins/ai-native-devkit/skills/sop-init/assets/docs-template/decisions/README.md`
- Modify: `plugins/ai-native-devkit/skills/sop-init/assets/docs-template/superpowers/README.md`
- Modify: `plugins/ai-native-devkit/skills/sop-init/assets/AGENTS.md`
- Modify: `plugins/ai-native-devkit/skills/sop-init/scripts/validate_project_docs.py`
- Modify: `tests/fixtures/standard-project/docs/decisions/README.md`
- Modify: `tests/fixtures/standard-project/docs/superpowers/README.md`
- Modify: `tests/test_decision_promotion.py`
- Modify: `tests/test_development_skills.py`
- Modify: `tests/test_docs_template.py`

**Interfaces:**

- Consumes: exact `RequirementDocRef` core fields from Task 1 and approved requirement Markdown loaded by `$sop-sync-docs` in Task 7.
- Produces: ADR frontmatter keys `source_requirement_path`, `source_requirement_commit`, and `source_requirement_blob_digest` with matching Git algorithms.
- Produces: project templates that classify `requirements/`, `specs/`, and `plans/` as workflow records, never CurrentState.
- Guarantees: `$sop-init` never opens requirements/specs/plans as current-requirement evidence or promotion material merely because Phase 0 returned them in `safePaths`.
- Preserves: `validate_project_docs.py` output shape `{"valid": bool, "missing": list, "brokenLinks": list}`.

- [x] **Step 1: Write failing promotion tests for the new frontmatter**

Replace the old artifact provenance fixture with:

```yaml
---
status: accepted
state_class: RequestedState
implementation_status: not_implemented
source_requirement_path: docs/superpowers/requirements/2026-08-27-login-requirements.md
source_requirement_commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
source_requirement_blob_digest: git-sha1:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
---
```

Replace `decision_frontmatter` and add the table-driven validator methods:

```python
def decision_frontmatter(
    *, algorithm="sha1", state_class="RequestedState",
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

def test_sha1_and_sha256_requirement_provenance_are_valid(self):
    for algorithm in ("sha1", "sha256"):
        with self.subTest(algorithm=algorithm), tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "0042-login-policy.md"
            path.write_text(decision_frontmatter(algorithm=algorithm), encoding="utf-8")
            self.assertEqual(validate(path), {"valid": True, "errors": []})

def test_inexact_or_legacy_requirement_provenance_is_rejected(self):
    valid = decision_frontmatter()
    invalid = (
        valid.replace(
            "docs/superpowers/requirements/2026-08-27-login-requirements.md",
            "../outside.md",
        ),
        valid.replace("source_requirement_commit: " + "a" * 40,
                      "source_requirement_commit: " + "a" * 12),
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
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "0042-login-policy.md"
        path.write_text(
            decision_frontmatter(implementation_status="implemented"),
            encoding="utf-8",
        )
        self.assertFalse(validate(path)["valid"])
```

- [x] **Step 2: Write failing template tests**

Add these literal template and Init-boundary methods:

```python
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
    for field in (
        "source_requirement_path", "source_requirement_commit",
        "source_requirement_blob_digest",
    ):
        self.assertIn(field, template)
    for legacy in ("source_task_id", "source_artifact_id", "clarification_result"):
        self.assertNotIn(legacy, template)

def test_init_excludes_workflow_records_even_when_preflight_reports_them_safe(self):
    sentinel = "HISTORICAL_REQUIREMENT_MUST_NOT_BECOME_CURRENT"
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        copy_canonical_project(project)
        requirement = (
            project / "docs/superpowers/requirements/2026-08-27-old-requirements.md"
        )
        requirement.parent.mkdir()
        requirement.write_text(sentinel, encoding="utf-8")
        result = subprocess.run(
            ["python3", str(PREFLIGHT), project], text=True, capture_output=True,
        )
        self.assertIn(
            str(requirement.relative_to(project)), json.loads(result.stdout)["safePaths"]
        )
        for path in (
            SKILL / "SKILL.md", SKILL / "references/init-contract.md",
        ):
            contract = " ".join(path.read_text(encoding="utf-8").split())
            for directory in ("requirements/", "specs/", "plans/"):
                self.assertIn(directory, contract)
            self.assertIn("exclude from semantic inventory", contract)
            self.assertIn("do not open", contract)
            self.assertIn("deterministic index/link preservation", contract)
        self.assertEqual(requirement.read_text(encoding="utf-8"), sentinel)
```

- [x] **Step 3: Run the focused tests and verify the red state**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.test_decision_promotion \
  tests.test_development_skills \
  tests.test_docs_template -v
```

Expected: the old artifact frontmatter and historical-specs-only template fail the new assertions.

- [x] **Step 4: Implement exact Git provenance validation**

In `validate_promoted_decision.py`, require exactly the new fields and validate:

```python
REQUIREMENT_PATH = re.compile(
    r"docs/superpowers/requirements/"
    r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*-requirements(?:-\d+)?\.md"
)
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
BLOB = re.compile(r"(?:git-sha1:[0-9a-f]{40}|git-sha256:[0-9a-f]{64})")
```

Require commit length and blob algorithm to agree. Keep the existing `RequestedState -> not_implemented` rule.

- [x] **Step 5: Update templates, fixture, and validator markers**

Write this exact `superpowers/README.md` to the asset and standard fixture:

```markdown
# 版本化工作记录

本目录保存 requirements、specs 和 plans 工作流记录。它们用于追溯，不是 CurrentState，不能替代当前 overview、design、API 或 ADR。

## 目录索引

| 目录 | 内容 | 什么时候读取 |
|---|---|---|
| `requirements/` | 已澄清的需求记录 | 仅通过显式的已批准精确 Git 引用 |
| `specs/` | 已批准设计规格 | 回顾方案形成过程时 |
| `plans/` | 实施计划 | 执行或追溯对应任务时 |

## 维护规则

保留历史文件；不把它们自动解释为当前需求或已实施事实。只允许确定性索引和链接修复。

## 文档模板

文件名称和格式由对应 Skill 管理，本索引不重复维护模板。
```

Use this exact marker entry in `validate_project_docs.py`:

```python
DOC_MARKERS["superpowers/README.md"] = (
    "# 版本化工作记录", "## 目录索引", "## 维护规则", "## 文档模板",
)
```

Replace the provenance fields in the decisions template with the YAML from Step 1. Insert this same paragraph before semantic inventory in both `$sop-init` and `references/init-contract.md`:

```markdown
Exclude every descendant of `docs/superpowers/requirements/`,
`docs/superpowers/specs/`, and `docs/superpowers/plans/` from semantic
inventory even when Phase 0 reports it in `safePaths`. Preserve those files
byte-for-byte; do not open, summarize, migrate, promote, or use them to infer
the current task. Deterministic index/link preservation is allowed. A routed
stage may consume an explicitly supplied approved reference later.
```

Update the bundled `AGENTS.md` promotion paragraph to name the three exact `source_requirement_*` fields. Do not pre-create `requirements/`; the Writer creates it only after clarification completes.

- [x] **Step 6: Make template and promotion tests green**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.test_decision_promotion \
  tests.test_development_skills \
  tests.test_docs_template \
  tests.test_managed_docs -v
python3 /Users/didi/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  plugins/ai-native-devkit/skills/sop-init
python3 /Users/didi/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  plugins/ai-native-devkit/skills/sop-sync-docs

if matches="$(rg -n \
  'ClarificationCheckpoint|ClarificationResult|ClarificationRuntime|clarification\.(checkpoint|checkpoint\.load|approval\.request|finalize|load)|clarification_checkpoint|clarification_result|clarification_ref|clarify\.baseline' \
  plugins/ai-native-devkit/scripts plugins/ai-native-devkit/skills)"; then
  printf '%s\n' "$matches"
  exit 1
elif test "$?" -ne 1; then
  exit 1
fi
git diff --check
```

Expected: tests and both Skill validators pass with the validator's public JSON
shape unchanged, and the package-wide old-symbol scan produces no matches.

- [x] **Step 7: Review and commit the docs-workflow provenance slice**

```bash
set -euo pipefail
git add \
  plugins/ai-native-devkit/skills/sop-init/SKILL.md \
  plugins/ai-native-devkit/skills/sop-init/assets/AGENTS.md \
  plugins/ai-native-devkit/skills/sop-init/assets/docs-template/decisions/README.md \
  plugins/ai-native-devkit/skills/sop-init/assets/docs-template/superpowers/README.md \
  plugins/ai-native-devkit/skills/sop-init/references/init-contract.md \
  plugins/ai-native-devkit/skills/sop-init/scripts/validate_project_docs.py \
  plugins/ai-native-devkit/skills/sop-sync-docs/scripts/validate_promoted_decision.py \
  tests/fixtures/standard-project/docs/decisions/README.md \
  tests/fixtures/standard-project/docs/superpowers/README.md \
  tests/test_decision_promotion.py \
  tests/test_development_skills.py \
  tests/test_docs_template.py
expected=$'plugins/ai-native-devkit/skills/sop-init/SKILL.md\nplugins/ai-native-devkit/skills/sop-init/assets/AGENTS.md\nplugins/ai-native-devkit/skills/sop-init/assets/docs-template/decisions/README.md\nplugins/ai-native-devkit/skills/sop-init/assets/docs-template/superpowers/README.md\nplugins/ai-native-devkit/skills/sop-init/references/init-contract.md\nplugins/ai-native-devkit/skills/sop-init/scripts/validate_project_docs.py\nplugins/ai-native-devkit/skills/sop-sync-docs/scripts/validate_promoted_decision.py\ntests/fixtures/standard-project/docs/decisions/README.md\ntests/fixtures/standard-project/docs/superpowers/README.md\ntests/test_decision_promotion.py\ntests/test_development_skills.py\ntests/test_docs_template.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "feat: promote requirements by git provenance"
```

### Task 10: Supersede the clarification decisions and prepare candidate documentation

**Files:**

- Create: `docs/decisions/0006-git-versioned-requirements-handoff.md`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `plugins/ai-native-devkit/README.md`
- Modify: `docs/README.md`
- Modify: `docs/product-and-scope.md`
- Modify: `docs/方案总览.md`
- Modify: `docs/architecture.md`
- Modify: `docs/contracts.md`
- Modify: `docs/workflow.md`
- Modify: `docs/context-and-docs.md`
- Modify: `docs/roadmap-and-validation.md`
- Modify: `docs/skill-selection.md`
- Modify: `docs/evaluation-evidence.md`
- Modify: `docs/decisions/0002-task-artifacts-and-doc-promotion.md`
- Modify: `docs/decisions/0004-task-state-store-interface.md`
- Modify: `docs/decisions/0005-persist-and-promote-clarification-results.md`
- Modify: `docs/decisions/README.md`
- Modify: `docs/superpowers/README.md`
- Modify: `tests/test_skill_contract.py`
- Modify: `tests/test_end_to_end_contract.py`

**Interfaces:**

- Consumes: code, tests, Skill contracts, templates, and provenance from Tasks 1–9 plus the approved design spec.
- Produces: candidate `0.4.0` documentation explicitly marked `RequestedState / validation pending`; it does not claim Current or Implemented status in this task.
- Produces: accepted ADR 0006 for the Git document/Trace approval boundary; ADRs 0002, 0004, and 0005 retain their historical text and receive supersession notes for clarification clauses.
- Preserves: historical A/B evaluation measurements while distinguishing them from the 2026-08-27 product decision.

- [x] **Step 1: Change documentation contract tests first**

Replace the old checkpoint/caller-asserted methods with these literal assertions:

```python
def test_candidate_docs_describe_exact_requirement_handoff_without_current_claim(self):
    contracts = (ROOT / "docs/contracts.md").read_text(encoding="utf-8")
    workflow = (ROOT / "docs/workflow.md").read_text(encoding="utf-8")
    context = (ROOT / "docs/context-and-docs.md").read_text(encoding="utf-8")
    combined = "\n".join((contracts, workflow, context))
    for token in (
        "Candidate 0.4.0 — validation pending", "RequirementDocRef",
        "path", "commit", "blob_digest", "clarify.requirements",
        "later user-authored", "same repository", "exact subject",
        "versioned workflow records", "not canonical CurrentState",
    ):
        self.assertIn(token, combined)
    self.assertNotIn("Current 0.4.0", combined)
    self.assertNotIn("0.4.0 implemented", combined)

def test_candidate_package_docs_index_new_contract_without_premature_current_state(self):
    manifest = json.loads(
        (PLUGIN / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
    )
    self.assertEqual(manifest["version"], "0.4.0")
    adr = ROOT / "docs/decisions/0006-git-versioned-requirements-handoff.md"
    self.assertTrue(adr.is_file())
    self.assertIn("Status: Accepted", adr.read_text(encoding="utf-8"))
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
        self.assertIn("validation pending", text)
        self.assertNotIn("0.4.0 implemented", text)
```

- [x] **Step 2: Run the documentation contract tests and verify they fail**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.test_skill_contract \
  tests.test_end_to_end_contract -v
```

Expected: canonical docs still describe the `0.3.0` checkpoint/result behavior.

- [x] **Step 3a: Write ADR 0006**

Create `docs/decisions/0006-git-versioned-requirements-handoff.md` with this complete text:

```markdown
# ADR 0006: Hand Clarify to Design through a Git requirement document

Status: Accepted
Date: 2026-08-27

## Context

Clarify should reuse the requirement-understanding behavior of Superpowers
`brainstorming` without requiring that plugin at runtime. The former DevKit
flow persisted every clarification checkpoint and an approved structured
`ClarificationResult` in TaskStateStore. That made the clarification stage a
second persistence workflow and mixed requirement understanding with a schema
that later design work no longer needs.

The replacement still needs an auditable cross-turn approval, exact later-task
input, optional human-readable sources, and safe behavior in repositories with
unrelated staged, unstaged, or untracked work.

## Decision

After the interview is complete, `RequirementDocumentWriter` creates and
commits one minimal Markdown file below `docs/superpowers/requirements/`. Its
public identity is `RequirementDocRef(path, commit, blob_digest)`. The file
contains confirmed natural-language requirements and optional source lines; it
contains no transcript, design, plan, or approval claim.

The runtime records `clarify.requirements` approval against the canonical
SHA-256 digest of the complete reference. A request can resolve only in a later
trusted user turn. Design receives only an explicitly supplied exact reference,
then `RequirementDocumentLoader` verifies repository, path, commit, blob,
worktree/index freshness, source freshness, and a completed approval before
returning Markdown. A later Codex task may reuse a completed approval only for
the same repository and exact current subject. This is a narrow handoff rule,
not a global revocation or latest-approval service.

Repository sources record a relative path and commit. External sources retain
a stable HTTPS URL, resource URI, or opaque resource ID plus version or sync
time. Repository drift is verified by the Loader; Design re-reads external
sources and returns to Clarify when comparison fails.

The Writer delegates commit policy, signing, native temporary-index behavior,
and ref locking to `git commit --only`; a new file is exposed to Git with
`git add -N` first. See [`git commit`](https://git-scm.com/docs/git-commit) and
[`git add`](https://git-scm.com/docs/git-add). It snapshots unrelated
Git-visible state before and after the commit. Detected hook or repository drift
makes the outcome indeterminate and returns no reference; DevKit never uses
stash, reset, checkout, amend, or destructive rollback of hook side effects.

Git clean/EOL normalization can treat different raw bytes as equivalent. Such
repository-policy hook side effects are outside the Writer's Git-semantic
preservation claim and are not rolled back. Repositories with pre-existing
`skip-worktree` or `assume-unchanged` entries are rejected before a write
because Git intentionally hides those worktree changes from normal projections.

`ClarificationCheckpoint`, `ClarificationResult`, their CLI operations, and
their clarification-only TaskStateStore rules are removed without migration.
Existing external state files are left untouched but unsupported.

## Consequences

- Clarification writes no requirement document, checkpoint, transcript, or
  TaskStateStore artifact before the interview is complete; automatic
  Execution Trace remains active.
- Requirements history is human-readable and reviewable in Git.
- Every semantic change produces a new commit and approval subject.
- Design and Docs Sync must carry the exact reference explicitly.
- Historical requirement files are workflow records, not CurrentState docs.
- Interrupted pre-document interviews can continue only in the original Codex
  conversation.
- Writer failure can leave visible diagnostic state when safe cleanup cannot be
  proven; no reference or approval is emitted in that case.

## Alternatives considered

1. Keep TaskStateStore checkpoints and only change Skill wording. Rejected
   because it preserves the structured baseline and resume model being removed.
2. Store requirements only in chat. Rejected because Design would lack an exact,
   reviewable handoff.
3. Approve a path without commit/blob identity. Rejected because content could
   change after review.
4. Copy Superpowers as a runtime dependency. Rejected because packaged DevKit
   must remain independently installable.
5. Implement commits with `commit-tree` and manual hook emulation. Rejected
   because it bypasses or incompletely reproduces repository commit policy.

## Related docs

- `docs/superpowers/specs/2026-08-27-superpowers-aligned-requirement-clarification-design.md`
- `docs/contracts.md`
- `docs/workflow.md`
- `docs/context-and-docs.md`
```

- [x] **Step 3b: Mark ADR 0005 superseded without rewriting it**

Replace only its status line:

```diff
-Status: Accepted
+Status: Superseded by ADR 0006
```

- [x] **Step 3c: Append narrow supersession notes to ADRs 0002 and 0004**

Append these exact sections without changing historical body text:

```markdown
## Clarification supersession (2026-08-27)

ADR 0006 supersedes this decision only for Clarify: incomplete interviews are
not persisted, and completed requirements use the Git document plus exact Trace
approval boundary. The remaining TaskStateStore and canonical-doc promotion
rules stay accepted.
```

```markdown
## Clarification supersession (2026-08-27)

ADR 0006 supersedes the clarification-specific ownership note above. Clarify no
longer writes TaskStateStore artifacts; the small `load` / `commit` interface
continues to govern the remaining persisted task contracts.
```

- [x] **Step 4: Draft candidate contract and architecture documentation**

Insert under `## Contract goals` in `docs/contracts.md`:

```markdown
## Candidate 0.4.0 — validation pending

This candidate replaces the clarification checkpoint/result boundary only after
Task 11 verifies the final committed tree. Current 0.3 contracts remain labeled
below until then.

`RequirementDocRef` has required `path`, `commit`, and algorithm-qualified
`blob_digest` fields and preserves compatible extension identity. The artifact
CLI accepts only `requirements.write` and `requirements.load`. Write returns one
exact reference; load requires that full reference and returns exact approved
Markdown. `clarify.requirements` approval stores only `subject_kind:
requirement_document` and the canonical subject digest. Raw requirement prose,
source contents, and chat text never enter Execution Trace.

The sequence is `stage.start(clarify) -> requirements.write ->
approval.request -> later user-authored approval.resolve ->
stage.complete(clarify, exact subject) -> requirements.load(purpose: design) ->
stage.start(design)`. A later session may materialize Clarify completion only
when its caller explicitly supplies a reference whose exact completed approval
exists in a validated Trace for the same repository.

`ClarificationCheckpoint`, `ClarificationResult`, `ContextReady -> Clarified`,
and the old checkpoint/load/finalize operations are absent from the candidate.
Existing external state is not migrated or deleted.
```

Insert under `## Deep modules` in `docs/architecture.md`:

```markdown
### Candidate 0.4.0 Clarify/Design boundary — validation pending

`$coding-sop` remains the only orchestrator. `$sop-clarify` owns dialogue;
`RequirementDocumentWriter` hides safe path creation and the one-file Git
commit; runtime Trace owns exact later-turn approval; and
`RequirementDocumentLoader` hides repository, Git identity, approval, and
source-freshness checks. TaskStateStore is not part of this clarification path.
Requirements files are versioned workflow records rather than canonical
CurrentState. This section becomes Current only after Task 11 succeeds.
```

- [x] **Step 5: Draft candidate workflow and context documentation**

Insert under `## Lifecycle` in `docs/workflow.md`:

```markdown
### Candidate 0.4.0 Clarify handoff — validation pending

`inspect -> scope assessment -> one-question interview -> requirements.write ->
clarify.requirements request -> later-turn resolution -> exact Clarify terminal
-> requirements.load(purpose: design) -> Design start`.

`requirements_source_drift` returns to Clarify with the exact current reference
as `supersedes`. `requirements_document_drift` returns to fresh
`document_drift` Clarify without `supersedes`; the changed, staged, committed,
or deleted historical path is not restored or overwritten, and the Writer
creates a suffixed document with a new approval. Rejected or
changes-requested approval keeps Clarify active. Interrupted pre-document
interviews have no repository-level resume.
```

Replace the clarification subsection under `## Task artifacts` in
`docs/context-and-docs.md` with:

```markdown
### Candidate requirement workflow records — validation pending

`docs/superpowers/requirements/`, `specs/`, and `plans/` are versioned workflow
records, not canonical CurrentState. Init preserves and indexes them but does
not infer the current task or current requirements from their contents. Design
and Docs Sync read a requirement only through an explicitly supplied exact
approved `RequirementDocRef`. Durable implemented knowledge is promoted to the
normal overview, design, API, decision, runbook, and pitfall documents through
the existing semantic preview/approval boundary.
```

- [x] **Step 6a: Draft candidate contributor and README status**

Apply this exact insertion map:

| File | Insert after | Literal text |
|---|---|---|
| `AGENTS.md` | `## Start here` list | `Candidate 0.4.0 — validation pending replaces only Clarify/Design handoff after final verification. Until then preserve Current 0.3, historical 0.2, and Planned V1 labels.` |
| `README.md` | opening status paragraph | `Candidate 0.4.0 — validation pending: Superpowers-aligned requirement discovery writes one exact approved Git requirement record; it is not Current until final verification.` |
| `plugins/ai-native-devkit/README.md` | `## 当前验证范围` | `Candidate 0.4.0 — validation pending：Clarify 产出 Git requirements 记录，Design 只读取显式的已批准精确引用。当前已实施边界仍为 0.3.0。` |
| `docs/README.md` | `## 状态口径` | `Candidate 0.4.0 — validation pending is RequestedState. Requirements/specs/plans are versioned workflow records, not canonical CurrentState.` |

- [x] **Step 6b: Draft candidate product and overview semantics**

Insert after `## Delivery status` in `docs/product-and-scope.md` and after
`## 当前实现边界` in `docs/方案总览.md`:

```markdown
### Candidate 0.4.0 — validation pending

Clarify reuses the Superpowers requirement-understanding behavior without a
runtime dependency, then writes one minimal Git requirements workflow record.
Approval binds its exact path, commit, and blob; Design accepts only that
explicit approved reference. The old checkpoint/result contract is removed
without migrating or deleting external state. Workflow records do not claim
implemented CurrentState.
```

- [x] **Step 6c: Draft candidate Skill routing documentation**

In `docs/skill-selection.md`, replace the entire section beginning at
<code>## `$sop-clarify`</code>, from that heading up to but not including the
existing <code>## `$sop-design`</code> heading, with this exact block:

```markdown
## `$sop-clarify`

Candidate 0.4.0 — validation pending. Inspect project state, assess scope,
decompose oversized requests, and ask one purpose/constraint/success question
per message. Do not design or persist partial answers. After clarification,
write one minimal requirements record, request later-turn approval for its
exact `RequirementDocRef`, and complete Clarify only for that subject.
```

Then insert this exact paragraph immediately after the existing
<code>## `$sop-design`</code> heading:

```markdown
**Candidate 0.4.0 input rule — validation pending.**

Load only an explicitly supplied approved `RequirementDocRef`; never infer it
from Init, chat, repository recency, or historical workflow records. Return
source or document drift to Clarify before Design starts. `$sop-sync-docs`
promotes durable decisions with exact Git provenance and the existing semantic
preview/approval gate. Old external clarification state remains untouched and
unsupported.
```

- [x] **Step 7: Update candidate roadmap, evidence, and indexes**

Apply these exact additions without deleting measured historical evidence:

| File | Anchor | Literal addition |
|---|---|---|
| `docs/roadmap-and-validation.md` | <code>### S2 — `$sop-clarify`</code> | `Candidate 0.4.0 — validation pending: replace checkpoint/result persistence with the exact Git requirement document and Trace approval boundary defined by ADR 0006.` |
| `docs/evaluation-evidence.md` | end of `### Requirement clarification` | `Later product decision (2026-08-27): despite the historical A/B measurement, the approved target now reuses Superpowers 6.3.0 requirement-understanding behavior and retains DevKit source references plus exact approval. This does not alter the recorded measurement.` |
| `docs/decisions/README.md` | decision index | ``- [ADR 0006](0006-git-versioned-requirements-handoff.md) — Accepted; candidate implementation validation pending`` |
| `docs/superpowers/README.md` | implementation-plan row | `Candidate / validation pending` |

Keep the approved spec row `Approved RequestedState`; do not label the
requirements implementation plan Current or Implemented in this task.

- [x] **Step 8: Make the candidate documentation contract tests green**

Run:

```bash
set -euo pipefail
python3 -m unittest \
  tests.test_skill_contract \
  tests.test_end_to_end_contract \
  tests.test_execution_trace_docs -v
git diff --check
```

Expected: tests pass, `git diff --check` prints nothing, and no document claims candidate `0.4.0` is Current. Historical roadmap, evaluation, ADR, spec, and plan evidence remains present and labeled.

- [x] **Step 9: Review and commit the candidate documentation**

```bash
set -euo pipefail
git add \
  AGENTS.md \
  README.md \
  plugins/ai-native-devkit/README.md \
  docs/README.md \
  docs/product-and-scope.md \
  docs/方案总览.md \
  docs/architecture.md \
  docs/contracts.md \
  docs/workflow.md \
  docs/context-and-docs.md \
  docs/roadmap-and-validation.md \
  docs/skill-selection.md \
  docs/evaluation-evidence.md \
  docs/decisions/0002-task-artifacts-and-doc-promotion.md \
  docs/decisions/0004-task-state-store-interface.md \
  docs/decisions/0005-persist-and-promote-clarification-results.md \
  docs/decisions/0006-git-versioned-requirements-handoff.md \
  docs/decisions/README.md \
  docs/superpowers/README.md \
  tests/test_skill_contract.py \
  tests/test_end_to_end_contract.py
expected=$'AGENTS.md\nREADME.md\ndocs/README.md\ndocs/architecture.md\ndocs/context-and-docs.md\ndocs/contracts.md\ndocs/decisions/0002-task-artifacts-and-doc-promotion.md\ndocs/decisions/0004-task-state-store-interface.md\ndocs/decisions/0005-persist-and-promote-clarification-results.md\ndocs/decisions/0006-git-versioned-requirements-handoff.md\ndocs/decisions/README.md\ndocs/evaluation-evidence.md\ndocs/product-and-scope.md\ndocs/roadmap-and-validation.md\ndocs/skill-selection.md\ndocs/superpowers/README.md\ndocs/workflow.md\ndocs/方案总览.md\nplugins/ai-native-devkit/README.md\ntests/test_end_to_end_contract.py\ntests/test_skill_contract.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "docs: prepare git requirement handoff"
```

### Task 11: Run repository-wide verification and record fresh evidence

**Files:**

- Modify after successful preflight verification: `AGENTS.md`
- Modify after successful preflight verification: `README.md`
- Modify after successful preflight verification: `plugins/ai-native-devkit/README.md`
- Modify after successful preflight verification: `docs/README.md`
- Modify after successful preflight verification: `docs/product-and-scope.md`
- Modify after successful preflight verification: `docs/方案总览.md`
- Modify after successful preflight verification: `docs/architecture.md`
- Modify after successful preflight verification: `docs/contracts.md`
- Modify after successful preflight verification: `docs/workflow.md`
- Modify after successful preflight verification: `docs/context-and-docs.md`
- Modify after successful preflight verification: `docs/roadmap-and-validation.md`
- Modify after successful preflight verification: `docs/skill-selection.md`
- Modify after successful preflight verification: `docs/evaluation-evidence.md`
- Modify after successful preflight verification: `docs/superpowers/README.md`
- Modify after successful preflight verification: `docs/superpowers/specs/2026-08-27-superpowers-aligned-requirement-clarification-design.md`
- Modify while executing: `docs/superpowers/plans/2026-08-27-superpowers-aligned-requirement-clarification.md`
- Modify after successful preflight verification: `tests/test_skill_contract.py`
- Modify after successful preflight verification: `tests/test_end_to_end_contract.py`

**Interfaces:**

- Consumes: Task 10's candidate documentation and every verified implementation slice.
- Produces: fresh evidence for all acceptance criteria, every Skill quick validator, the plugin validator, and the complete repository suite.
- Produces: Current/Implemented `0.4.0` status only after the candidate tree passes preflight verification, then verifies the exact final tree again before and after commit.

- [x] **Step 1: Run the complete focused acceptance suite**

```bash
set -euo pipefail
python3 -m unittest \
  tests.contract.test_contracts \
  tests.contract.test_task_state_store \
  tests.modules.test_requirement_approval \
  tests.modules.test_requirement_document \
  tests.modules.test_execution_trace \
  tests.integration.test_workflow_cli \
  tests.integration.test_runtime_trace_and_docs_hook \
  tests.integration.test_trace_collector_cli \
  tests.test_plugin_contract \
  tests.test_skill_contract \
  tests.test_development_skills \
  tests.test_decision_promotion \
  tests.test_docs_template \
  tests.test_end_to_end_contract -v
```

Expected: every selected test passes. If one fails, fix the owning slice, rerun its focused test, then rerun this entire command.

- [x] **Step 2: Run the quick validator for every packaged Skill**

```bash
set -euo pipefail
for skill_dir in plugins/ai-native-devkit/skills/*; do
  python3 /Users/didi/.codex/skills/.system/skill-creator/scripts/quick_validate.py "$skill_dir"
done
```

Expected: every Skill exits 0. Do not stop after validating only the three changed stage Skills.

- [x] **Step 3: Run the plugin creator validator**

```bash
set -euo pipefail
python3 /Users/didi/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py \
  plugins/ai-native-devkit
```

Expected: exit 0 with a valid `ai-native-devkit` plugin. Do not install or publish it.

- [x] **Step 4: Run the complete repository validation suite**

```bash
set -euo pipefail
python3 scripts/validate_all.py
```

Expected: all discovered tests and the plugin validator pass with fresh output.

- [x] **Step 5: Run final residue, formatting, and worktree checks**

```bash
set -euo pipefail
if matches="$(rg -n \
  'ClarificationCheckpoint|ClarificationResult|ClarificationRuntime|clarification\.(checkpoint|checkpoint\.load|approval\.request|finalize|load)|clarification_checkpoint|clarification_result|clarification_ref|clarify\.baseline' \
  plugins/ai-native-devkit/scripts plugins/ai-native-devkit/skills)"; then
  printf '%s\n' "$matches"
  exit 1
elif test "$?" -ne 1; then
  exit 1
fi

git diff --check
git status --short
```

Expected: no old runtime/Skill contract matches and no whitespace errors. The only allowed unstaged path is this plan when earlier task checkboxes were updated for tracking; any other path must be explained and resolved before promotion.

- [x] **Step 6: Promote candidate wording to Current and record evidence**

Only after Steps 1–5 are green, replace candidate/validation-pending markers with Current/Implemented `0.4.0` in every file listed for this task, reclassify the former `Current 0.3` clarification contract as Historical, and remove it from Current-only interface tables. Update the two documentation contract tests to require Current status. In `docs/roadmap-and-validation.md`, record the date, commands, pass counts, validator results, and genuine remaining risks. Mark the design, plan, and index rows Implemented and mark this plan's completed checkboxes without changing its technical instructions.

- [x] **Step 7: Re-run documentation and Skill validation on the final tree**

```bash
set -euo pipefail
python3 -m unittest \
  tests.test_skill_contract \
  tests.test_end_to_end_contract \
  tests.test_execution_trace_docs -v
for skill_dir in plugins/ai-native-devkit/skills/*; do
  python3 /Users/didi/.codex/skills/.system/skill-creator/scripts/quick_validate.py "$skill_dir"
done
python3 /Users/didi/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py \
  plugins/ai-native-devkit
git diff --check
```

Expected: every command exits 0 after the status/evidence edits.

- [x] **Step 8: Re-run the complete repository suite on the final tree**

Run:

```bash
set -euo pipefail
python3 scripts/validate_all.py
```

Expected: all discovered tests and the plugin validator pass on the exact tree about to be committed.

- [x] **Step 9: Review and commit the verified implementation record**

```bash
set -euo pipefail
git add \
  AGENTS.md \
  README.md \
  plugins/ai-native-devkit/README.md \
  docs/README.md \
  docs/product-and-scope.md \
  docs/方案总览.md \
  docs/architecture.md \
  docs/contracts.md \
  docs/workflow.md \
  docs/context-and-docs.md \
  docs/roadmap-and-validation.md \
  docs/skill-selection.md \
  docs/evaluation-evidence.md \
  docs/superpowers/README.md \
  docs/superpowers/specs/2026-08-27-superpowers-aligned-requirement-clarification-design.md \
  docs/superpowers/plans/2026-08-27-superpowers-aligned-requirement-clarification.md \
  tests/test_skill_contract.py \
  tests/test_end_to_end_contract.py
expected=$'AGENTS.md\nREADME.md\ndocs/README.md\ndocs/architecture.md\ndocs/context-and-docs.md\ndocs/contracts.md\ndocs/evaluation-evidence.md\ndocs/product-and-scope.md\ndocs/roadmap-and-validation.md\ndocs/skill-selection.md\ndocs/superpowers/README.md\ndocs/superpowers/plans/2026-08-27-superpowers-aligned-requirement-clarification.md\ndocs/superpowers/specs/2026-08-27-superpowers-aligned-requirement-clarification-design.md\ndocs/workflow.md\ndocs/方案总览.md\nplugins/ai-native-devkit/README.md\ntests/test_end_to_end_contract.py\ntests/test_skill_contract.py'
actual="$(git diff --cached --name-only | sort)"
test "$actual" = "$(printf '%s\n' "$expected" | sort)"
git commit -m "test: verify requirement clarification migration"
```

- [x] **Step 10: Verify the exact committed revision**

```bash
set -euo pipefail
verified_head="$(git rev-parse HEAD)"
python3 scripts/validate_all.py
for skill_dir in plugins/ai-native-devkit/skills/*; do
  python3 /Users/didi/.codex/skills/.system/skill-creator/scripts/quick_validate.py "$skill_dir"
done
test "$(git rev-parse HEAD)" = "$verified_head"
git status --short
printf 'Verified revision: %s\n' "$verified_head"
```

Expected: every command exits 0, `HEAD` is byte-for-byte the captured `verified_head`, and `git status --short` prints nothing. Report the printed OID only in the final human-facing implementation handoff; do not edit a repository evidence file after this check, because that would invalidate the clean verified revision. If a failure requires a fix, make a new focused commit and repeat this step from a newly captured OID; do not amend away the verified history.

- [x] **Step 11: Confirm the final handoff state**

```bash
set -euo pipefail
git status --short --branch
git log --oneline --decorate -8
```

Expected: the worktree is clean, the eleven planned slice commits (plus any focused follow-up fix commits) are visible, the exact `HEAD` equals the OID recorded by Step 10's fresh verification, and no installation or publication action has occurred.
