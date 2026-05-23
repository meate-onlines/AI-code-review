"""Skill 单测的数据模型。

测试集文件示例（``standards/java/naming-convention.tests.yml``）：

    skill: java-naming-convention
    cases:
      - name: 类名小写应被检出
        file_path: src/main/java/com/foo/user_service.java
        language: java                 # 可选；不填按 file_path 后缀推断
        code: |
          public class user_service { }
        expect:
          skill_should_hit: true       # selector 是否必须命中本 skill
          ai_should_find_issue: true   # AI 是否必须返回至少一个 issue
          min_severity: warning        # 至少一个 issue 严重度 >= 该值
          issue_keywords: ["命名", "驼峰"]   # 至少一个 issue.message 命中其一
          must_reference_standard: true     # issue.standard_id 必须等于 skill name
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "critical"]


class Expect(BaseModel):
    """单个用例的期望结果。所有字段都是可选的，未设置则不校验。"""

    skill_should_hit: bool | None = None
    ai_should_find_issue: bool | None = None
    min_severity: Severity | None = None
    issue_keywords: list[str] = Field(default_factory=list)
    must_reference_standard: bool = False
    # 反向：不希望出现的关键词（误报检测）
    forbid_issue_keywords: list[str] = Field(default_factory=list)


class SkillTestCase(BaseModel):
    name: str
    file_path: str
    language: str | None = None
    code: str = ""
    diff: str | None = None
    expect: Expect = Field(default_factory=Expect)


class SkillTestSuite(BaseModel):
    skill: str = Field(description="被测 skill name")
    cases: list[SkillTestCase] = Field(default_factory=list)
    source_path: str | None = None


# ---------------------------------------------------------------------------
# 结果模型
# ---------------------------------------------------------------------------
class CaseResult(BaseModel):
    case_name: str
    skill: str
    file_path: str
    passed: bool
    skipped: bool = False
    duration_ms: int = 0
    failures: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    ai_issue_count: int = 0
    notes: list[str] = Field(default_factory=list)


class SuiteResult(BaseModel):
    skill: str
    source_path: str | None
    cases: list[CaseResult] = Field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed and not c.skipped)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.cases if not c.passed and not c.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for c in self.cases if c.skipped)


def default_tests_dir(standards_dir: Path) -> Path:
    """约定：tests 文件与 skill 同目录，命名为 ``<skill>.tests.yml``。"""
    return Path(standards_dir)
