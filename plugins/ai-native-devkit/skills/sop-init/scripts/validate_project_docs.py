#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import unquote


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_SCRIPTS = PLUGIN_ROOT / "scripts"
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

from ai_native_devkit.cli import _state_root
from ai_native_devkit.docs_init_observer import DocsInitObserver

REQUIRED = (
    "overview", "references", "decisions", "design",
    "api", "runbooks", "pitfalls", "superpowers",
)
FIXED_DOCUMENTS = (
    "overview/product.md",
    "overview/domain-model.md",
    "overview/architecture.md",
    "overview/technical-stack.md",
    "overview/implementation-status.md",
    "runbooks/rds-schema-change.md",
    "runbooks/rds-data-query.md",
    "runbooks/apollo-config.md",
    "runbooks/kms-secret.md",
)
FIXED_OVERVIEW = {
    "product.md",
    "domain-model.md",
    "architecture.md",
    "technical-stack.md",
    "implementation-status.md",
}
WORKFLOW_RECORD_DIRECTORIES = ("requirements", "specs", "plans")
FIXED_DOCUMENT_MARKERS = {
    "overview/product.md": "# 项目目标",
    "overview/domain-model.md": "# 业务模型",
    "overview/architecture.md": "# 系统架构",
    "overview/technical-stack.md": "# 技术栈",
    "overview/implementation-status.md": "# 实现状态",
    "runbooks/rds-schema-change.md": "# RDS 数据库结构变更",
    "runbooks/rds-data-query.md": "# RDS 安全查数",
    "runbooks/apollo-config.md": "# Apollo 配置管理和接入",
    "runbooks/kms-secret.md": "# KMS 凭证管理和接入",
}
ENTRY_MARKERS = (
    "# 项目协作规则",
    "### docs 目录索引",
    "### 文档更新规则",
)
DOC_MARKERS = {
    "overview/README.md": ("# 项目总览", "## 文件索引", "## 维护规则", "## 文档结构"),
    "references/README.md": ("# 上游参考资料", "## 文件索引", "## 维护规则", "## 文档模板"),
    "decisions/README.md": ("# 决策记录", "## 决策索引", "## 维护规则", "## ADR 模板"),
    "design/README.md": ("# 模块设计", "## 文件索引", "## 维护规则", "## 文档模板"),
    "api/README.md": ("# 接口契约", "## 文件索引", "## 维护规则", "## 文档模板"),
    "runbooks/README.md": ("# 操作手册", "## 文件索引", "## 维护规则", "## 文档模板"),
    "pitfalls/README.md": ("# 常见问题", "## 文件索引", "## 维护规则", "## 问题模板"),
    "superpowers/README.md": (
        "# 版本化工作记录", "## 目录索引", "## 维护规则", "## 文档模板",
    ),
}
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def is_excluded_workflow_record_path(path: Path, docs: Path) -> bool:
    lexical_path = Path(os.path.abspath(path))
    workflow_root = Path(os.path.abspath(docs / "superpowers"))
    return any(
        lexical_path.is_relative_to(workflow_root / directory)
        for directory in WORKFLOW_RECORD_DIRECTORIES
    )


def markdown_documents(root: Path, docs: Path):
    for current, directories, filenames in os.walk(root):
        current_path = Path(current)
        if is_excluded_workflow_record_path(current_path, docs):
            directories[:] = []
            continue
        directories[:] = [
            name
            for name in directories
            if not (current_path == docs and name == "handoff")
            and not is_excluded_workflow_record_path(current_path / name, docs)
        ]
        for filename in filenames:
            if filename.endswith(".md"):
                yield current_path / filename


def link_candidate(source: Path, raw_target: str) -> Optional[Path]:
    target = unquote(raw_target.split("#", 1)[0].strip())
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return None
    return Path(os.path.abspath(source.parent / target))


def is_excluded_handoff_path(
    path: Path,
    lexical_handoff: Path,
) -> bool:
    lexical_path = Path(os.path.abspath(path))
    if lexical_path.is_relative_to(lexical_handoff):
        return True

    seen = set()
    current = Path(lexical_path.anchor)
    pending = list(lexical_path.parts[1:])
    while pending:
        current = Path(os.path.normpath(current / pending.pop(0)))
        if current.is_relative_to(lexical_handoff):
            return True
        if not current.is_symlink():
            continue
        if current in seen:
            break
        seen.add(current)
        target = Path(os.readlink(current))
        alias = target if target.is_absolute() else current.parent / target
        alias = Path(os.path.abspath(alias))
        if alias.is_relative_to(lexical_handoff):
            return True
        current = Path(alias.anchor)
        pending = list(alias.parts[1:]) + pending

    return False


def first_symlink_component(path: Path, project_root: Path) -> Optional[Path]:
    lexical_path = Path(os.path.abspath(path))
    if not lexical_path.is_relative_to(project_root):
        return lexical_path

    current = project_root
    for part in lexical_path.relative_to(project_root).parts:
        current /= part
        if current.is_symlink():
            return current
    return None


def validate(project_root: Path) -> dict:
    project_root = project_root.resolve()
    docs = project_root / "docs"
    excluded_handoff = docs / "handoff"
    required_files = [
        *[docs / name / "README.md" for name in REQUIRED],
        *[docs / path for path in FIXED_DOCUMENTS],
    ]
    missing = []
    broken_links = []
    unsafe_required = set()

    for path in required_files:
        display = path.relative_to(project_root)
        if is_excluded_handoff_path(path, excluded_handoff):
            broken_links.append(f"excluded handoff alias: {display}")
            unsafe_required.add(path)
            continue
        symlink = first_symlink_component(path, project_root)
        if symlink is not None:
            if symlink == path and str(path.relative_to(docs)) in FIXED_DOCUMENT_MARKERS:
                broken_links.append(f"fixed document must be a regular file: {display}")
            else:
                broken_links.append(f"unsafe symlink component: {display}")
            unsafe_required.add(path)
            continue
        if not path.is_file():
            missing.append(str(display))

    entry_candidates = [project_root / "AGENTS.md", project_root / "CLAUDE.md"]
    valid_entry = False
    found_entry = False
    entry_errors = []
    for entry in entry_candidates:
        symlink = first_symlink_component(entry, project_root)
        if symlink is not None:
            found_entry = True
            entry_errors.append(
                f"unsafe symlink component: {entry.relative_to(project_root)}"
            )
            continue
        if not entry.is_file():
            continue
        found_entry = True
        text = entry.read_text(encoding="utf-8")
        missing_markers = [marker for marker in ENTRY_MARKERS if marker not in text]
        if not missing_markers:
            valid_entry = True
            break
        entry_errors.extend(
            f"contract marker missing: {entry.relative_to(project_root)} -> {marker}"
            for marker in missing_markers
        )
    if not found_entry:
        missing.append("AGENTS.md or CLAUDE.md")
    elif not valid_entry:
        broken_links.extend(entry_errors)

    for relative, markers in DOC_MARKERS.items():
        source = docs / relative
        if source in unsafe_required or not source.is_file():
            continue
        text = source.read_text(encoding="utf-8")
        broken_links.extend(
            f"contract marker missing: {source.relative_to(project_root)} -> {marker}"
            for marker in markers
            if marker not in text
        )

    fixed_inodes = {}
    for relative, marker in FIXED_DOCUMENT_MARKERS.items():
        source = docs / relative
        display = source.relative_to(project_root)
        if source in unsafe_required or not source.is_file():
            continue
        inode = (source.lstat().st_dev, source.lstat().st_ino)
        if inode in fixed_inodes:
            broken_links.append(
                f"fixed documents must be distinct: {display} -> {fixed_inodes[inode]}"
            )
            continue
        fixed_inodes[inode] = display
        text = source.read_text(encoding="utf-8")
        if not text.strip():
            broken_links.append(f"empty fixed document: {display}")
        elif marker not in text:
            broken_links.append(f"contract marker missing: {display} -> {marker}")

    if first_symlink_component(docs, project_root) is None and docs.is_dir():
        overview = docs / "overview"
        if (
            not is_excluded_handoff_path(overview, excluded_handoff)
            and first_symlink_component(overview, project_root) is None
            and overview.is_dir()
        ):
            for document in markdown_documents(overview, docs):
                if document == overview / "README.md" or (
                    document.parent == overview and document.name in FIXED_OVERVIEW
                ):
                    continue
                if is_excluded_handoff_path(document, excluded_handoff):
                    continue
                if first_symlink_component(document, project_root) is not None:
                    broken_links.append(
                        f"unsafe symlink component: {document.relative_to(project_root)}"
                    )
                    continue
                broken_links.append(
                    f"nonstandard overview document: {document.relative_to(project_root)}"
                )

        for source in markdown_documents(docs, docs):
            if is_excluded_handoff_path(source, excluded_handoff):
                continue
            if first_symlink_component(source, project_root) is not None:
                message = f"unsafe symlink component: {source.relative_to(project_root)}"
                if message not in broken_links:
                    broken_links.append(message)
                continue
            for raw_target in LINK.findall(source.read_text(encoding="utf-8")):
                candidate = link_candidate(source, raw_target)
                if candidate is None or is_excluded_handoff_path(
                    candidate, excluded_handoff
                ):
                    continue
                resolved = candidate.resolve()
                if not resolved.is_relative_to(project_root) or not resolved.exists():
                    broken_links.append(f"{source.relative_to(project_root)} -> {raw_target}")

        for name in REQUIRED:
            section = docs / name
            if is_excluded_handoff_path(section, excluded_handoff):
                continue
            if first_symlink_component(section, project_root) is not None:
                continue
            index = section / "README.md"
            indexed = set()
            if (
                not is_excluded_handoff_path(index, excluded_handoff)
                and first_symlink_component(index, project_root) is None
                and index.is_file()
            ):
                for raw_target in LINK.findall(index.read_text(encoding="utf-8")):
                    candidate = link_candidate(index, raw_target)
                    if candidate is None or is_excluded_handoff_path(
                        candidate, excluded_handoff
                    ):
                        continue
                    indexed.add(candidate.resolve())
            if section.is_dir():
                for document in markdown_documents(section, docs):
                    if document == index:
                        continue
                    if is_excluded_handoff_path(document, excluded_handoff):
                        continue
                    if first_symlink_component(document, project_root) is not None:
                        message = (
                            "unsafe symlink component: "
                            f"{document.relative_to(project_root)}"
                        )
                        if message not in broken_links:
                            broken_links.append(message)
                        continue
                    if document.resolve() not in indexed:
                        broken_links.append(
                            f"unindexed: {document.relative_to(project_root)}"
                        )
    return {
        "valid": not missing and not broken_links,
        "missing": sorted(missing),
        "brokenLinks": sorted(broken_links),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"valid": False, "missing": [], "brokenLinks": []}))
        return 2
    project_root = Path(sys.argv[1])
    result = validate(project_root)
    try:
        observer = DocsInitObserver.for_current_session(_state_root(), project_root)
        if observer is not None:
            observer.complete(result)
    except Exception:
        # Trace collection is fail-open and never changes validation semantics.
        pass
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
