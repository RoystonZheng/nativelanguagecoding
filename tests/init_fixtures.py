from ai_native_devkit.contracts import RepositoryRevision
from ai_native_devkit.repository import RepositoryClassification, RepositoryInspection


FIXED_REVISION = RepositoryRevision(
    head_state="attached",
    head="c" * 40,
    branch="main",
    dirty=False,
    worktree_digest=None,
)


class ReadyInspector:
    def classify(self, requested_path):
        return RepositoryClassification(
            requested_path=requested_path,
            root=requested_path,
            requested_scope=None,
            kind="worktree",
        )

    def inspect(self, classification):
        return RepositoryInspection(
            repository={
                "requested_path": classification.requested_path,
                "root": classification.root,
                "requested_scope": None,
                "revision": FIXED_REVISION.to_dict(),
                "superproject": None,
            },
            revision=FIXED_REVISION,
            sources=[
                {
                    "id": "repository:.",
                    "path": ".",
                    "kind": "repository",
                    "hash": "sha256:" + "a" * 64,
                },
                {
                    "id": "entry_doc:docs/overview/accounts.md",
                    "path": "docs/overview/accounts.md",
                    "kind": "entry_doc",
                    "hash": "sha256:" + "b" * 64,
                },
            ],
            findings={
                "entry_docs": ["README.md"],
                "repository_instructions": ["AGENTS.md"],
                "verification_commands": ["python -m unittest"],
            },
            gaps=[],
            started_at="2026-08-24T01:00:00.000Z",
            duration_ms=1,
        )
