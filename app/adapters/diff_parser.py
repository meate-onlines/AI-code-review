"""diff 解析纯函数集合。

旧版本把 diff 解析散落在 ``parse_diffs`` 里、与 GitLab 副作用耦合，
这里抽成无副作用的纯函数，方便单测和复用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


@dataclass(slots=True)
class HunkRange:
    """一个 diff hunk 在新文件中的行号范围（1-based，包含起止）。"""

    start_line: int
    end_line: int


def extract_hunk_ranges(diff: str) -> list[HunkRange]:
    """从 diff 文本里提取所有 hunk 的新文件行号范围。"""
    ranges: list[HunkRange] = []
    for match in _HUNK_HEADER.finditer(diff or ""):
        start = int(match.group(1))
        length = int(match.group(2) or "1")
        end = start + max(length - 1, 0)
        ranges.append(HunkRange(start_line=start, end_line=end))
    return ranges


def strip_diff_noise(diff: str) -> str:
    """去掉删除行与空白，保留新增和上下文行的关键信息。

    旧实现里有类似函数，但写在 ``code.py`` 顶层并依赖隐式约定；这里规范化输出。
    """
    if not diff:
        return ""
    kept = []
    for line in diff.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("-") and not stripped.startswith("---"):
            continue
        kept.append(line)
    return "\n".join(kept)


def has_meaningful_content(text: str) -> bool:
    """判断文本是否包含至少一个字母字符（否则视为纯标点/数字，没必要审查）。"""
    return bool(re.search(r"[A-Za-z]", text or ""))
