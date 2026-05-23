"""Review 链路的输入 / 输出数据模型。

所有跨模块流动的数据都用 Pydantic 模型描述，便于：
- 让 LLM 通过 ``with_structured_output`` 直接产出结构化结果；
- 统一类型，去掉旧版本的 ``{success, data, message}`` 字典判断；
- 关联 ``standard_id``，做命中统计与团队规范迭代闭环。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "critical"]
_SEVERITY_ORDER: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}


class ReviewInput(BaseModel):
    """单次审查任务的输入快照。"""

    file_path: str
    language: str
    code: str
    diff: str | None = None
    standards_block: str = ""
    applied_skill_ids: list[str] = Field(default_factory=list)


class Issue(BaseModel):
    """AI 找到的单个问题。"""

    standard_id: str | None = Field(
        default=None,
        description="违反的规范 id，对应 skills/<name>；若不属于团队规范填 null",
    )
    severity: Severity = Field(description="问题严重度")
    category: str = Field(description="问题类型，如 bug / security / perf / style / readability")
    line: int | None = Field(default=None, description="新文件中的行号（1-based），若无法定位填 null")
    message: str = Field(description="问题简要描述，控制在 200 字内")
    suggestion: str | None = Field(default=None, description="可选：具体修复建议")


class ReviewResult(BaseModel):
    """单文件审查的最终输出。"""

    summary: str = Field(description="对该文件改动的整体评价，1-2 句话")
    issues: list[Issue] = Field(default_factory=list)
    skip: bool = Field(
        default=False,
        description="是否为配置/数据/生成代码等无需审查的内容；为 true 时调用方应跳过评论",
    )
    applied_skill_ids: list[str] = Field(
        default_factory=list,
        description="本次审查实际注入的规范 id，由调度层在链外回填，便于统计",
    )

    def filter_by_min_severity(self, min_level: Severity) -> "ReviewResult":
        """根据最低严重度阈值过滤 issue。"""
        threshold = _SEVERITY_ORDER[min_level]
        kept = [i for i in self.issues if _SEVERITY_ORDER[i.severity] >= threshold]
        return self.model_copy(update={"issues": kept})
