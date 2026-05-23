"""文件后缀 → 语言名映射。

输出值会作为 prompt 中 ``language`` 变量和 skill 触发条件的 key，
所以全部用小写英文短名（与社区习惯一致）。
"""

from __future__ import annotations

from pathlib import PurePosixPath

_EXT_LANG_MAP: dict[str, str] = {
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".py": "python",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".vue": "vue",
    ".rb": "ruby",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".scala": "scala",
    ".swift": "swift",
    ".sh": "bash",
    ".sql": "sql",
    ".xml": "xml",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".md": "markdown",
}


def detect_language(file_path: str) -> str:
    """根据后缀推断语言，未知后缀回落到 ``text``。"""
    suffix = PurePosixPath(file_path).suffix.lower()
    return _EXT_LANG_MAP.get(suffix, "text")
