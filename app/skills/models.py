"""Skill 数据模型。

一个 Skill 对应 ``standards/`` 下的一个 Markdown 文件：
- YAML front-matter 描述触发条件、严重度等元数据；
- 正文 Markdown 是真正注入到 prompt 的规则正文。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "critical"]


class SkillTriggers(BaseModel):
    """决定 skill 是否被选中的硬性条件。"""

    languages: list[str] = Field(
        default_factory=list,
        description="语言关键字（小写）；为空表示语言无关",
    )
    file_patterns: list[str] = Field(
        default_factory=list,
        description="glob 模式（基于 fnmatch），任一命中即可；为空表示路径无关",
    )
    path_excludes: list[str] = Field(
        default_factory=list,
        description="glob 模式，命中任一则排除",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="diff 或 code 中必须出现的关键词，命中任一即触发；为空不约束",
    )


class Skill(BaseModel):
    """单条规范的运行时表示。"""

    name: str = Field(description="唯一 id，建议 kebab-case")
    description: str = Field(description="一句话说明何时使用，会作为元数据呈现给模型")
    severity: Severity = "warning"
    version: str = "1.0"
    tags: list[str] = Field(default_factory=list)
    owner: str | None = None
    triggers: SkillTriggers = Field(default_factory=SkillTriggers)
    body: str = Field(description="规范正文（Markdown），将被注入到 system prompt")
    source_path: str | None = Field(
        default=None, description="原始文件路径，便于报错定位"
    )

    def render(self) -> str:
        """渲染成 prompt 中单条规范块。"""
        return (
            f"## [{self.name}] (severity={self.severity})\n"
            f"{self.description}\n\n"
            f"{self.body.strip()}\n"
        )
