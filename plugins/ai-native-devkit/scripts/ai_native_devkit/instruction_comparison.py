"""Conservative Markdown comparison; differences are evidence, not semantic verdicts."""

from difflib import SequenceMatcher
import re
from typing import Any, Dict, List

from .state_store import redact_persisted_text


MAX_BLOCKS = 2048
MAX_DIFFERENCES = 8
MAX_EXCERPT = 300
_DIRECTIVE = re.compile(r"\b(must|never|shall|required|always|forbid|allow|deny|should|optional|no|not)\b|必须|禁止|不得|不准|不要|不必|允许|应当", re.I)
_BULLET = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
_STARTUP = re.compile(r"启动规则|启动指引|startup\s+(?:rules|instructions)|start[- ]rules", re.I)
_HOST_STARTUP_LINK = re.compile(r"(?<=\()(?:\./)?(?:\.Codex|\.claude)/start-rule\.md(?=\))")


def _blocks(text: str) -> List[Dict[str, Any]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    blocks: List[Dict[str, Any]] = []
    first_content = True
    fence = None
    code = []
    code_start = 0
    list_indents = []
    for number, raw in enumerate(lines, 1):
        stripped = raw.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence is not None:
            code.append(raw)
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                blocks.append({"key": "code:" + "\n".join(code), "start": code_start, "end": number})
                fence = None
            continue
        if not stripped:
            continue
        if marker:
            first_content = False
            fence, code, code_start = marker.group(1), [raw], number
            continue
        # A document title is presentation; policy-bearing titles and section scopes are not.
        if first_content and re.match(r"^#\s+", stripped) and not _DIRECTIVE.search(stripped):
            first_content = False
            continue
        first_content = False
        bullet = _BULLET.match(raw)
        depth = 0
        if bullet:
            indent = len(raw.expandtabs(4)) - len(raw.expandtabs(4).lstrip())
            while list_indents and indent < list_indents[-1]:
                list_indents.pop()
            if not list_indents or indent > list_indents[-1]:
                list_indents.append(indent)
            depth = len(list_indents) - 1
        elif re.match(r"^#{1,6}\s", stripped):
            list_indents = []
        key = _BULLET.sub("", stripped)
        # Do not normalize inside inline code, where whitespace/characters may be executable.
        parts = re.split(r"(`+[^`]*`+)", key)
        for index in range(0, len(parts), 2):
            part = parts[index]
            part = re.sub(r"(\*\*|__)(.+?)\1", r"\2", part)
            part = re.sub(r"(?<!\w)(\*|_)([^\n]+?)\1(?!\w)", r"\2", part)
            if _STARTUP.search(key):
                part = _HOST_STARTUP_LINK.sub(".agent/start-rule.md", part)
            parts[index] = re.sub(r"\s+", " ", part)
        key = "".join(parts).strip()
        if depth:
            key = f"nested-list-{depth}:" + key
        blocks.append({"key": key, "start": number, "end": number})
    if fence is not None:
        blocks.append({"key": "code:" + "\n".join(code), "start": code_start, "end": len(lines)})
    return blocks


def _excerpt(lines, blocks, start, end):
    if start == end:
        return None
    first, last = blocks[start]["start"], blocks[end - 1]["end"]
    # Redact the complete range before truncating, including credentials crossing the cap.
    excerpt = redact_persisted_text("\n".join(lines[first - 1:last]))
    truncated = len(excerpt) > MAX_EXCERPT
    if truncated:
        # Leave space if the cut intersects a redaction token and the store normalizes it again.
        excerpt = redact_persisted_text(excerpt[:MAX_EXCERPT - len("[REDACTED]")])
    return {
        "line_start": first, "line_end": last,
        "excerpt": excerpt, "truncated": truncated,
    }


def compare_instructions(left: str, right: str) -> List[Dict[str, Any]]:
    """Return bounded differing rule ranges, excluding a small set of presentation changes."""
    left_blocks, right_blocks = _blocks(left), _blocks(right)
    left_keys = [item["key"] for item in left_blocks]
    right_keys = [item["key"] for item in right_blocks]
    def coalesced(keys):
        result, prose = [], []
        for key in keys:
            if key.startswith("code:") or re.match(r"^#{1,6}\s", key):
                if prose:
                    result.append(" ".join(prose))
                    prose = []
                result.append(key)
            else:
                prose.append(key)
        if prose:
            result.append(" ".join(prose))
        return result
    if coalesced(left_keys) == coalesced(right_keys):
        return []
    left_lines, right_lines = left.splitlines(), right.splitlines()
    if max(len(left_blocks), len(right_blocks)) > MAX_BLOCKS:
        return [{
            "left": _excerpt(left_lines, left_blocks, 0, len(left_blocks)),
            "right": _excerpt(right_lines, right_blocks, 0, len(right_blocks)),
            "comparison_limited": True,
        }]
    differences = []
    for tag, a, b, c, d in SequenceMatcher(None, left_keys, right_keys, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if len(differences) == MAX_DIFFERENCES:
            differences[-1]["more_differences"] = True
            break
        differences.append({
            "left": _excerpt(left_lines, left_blocks, a, b),
            "right": _excerpt(right_lines, right_blocks, c, d),
        })
    return differences
