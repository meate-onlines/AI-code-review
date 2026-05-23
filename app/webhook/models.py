"""GitLab Webhook payload 精简模型。

只解析我们关心的字段；GitLab 实际 payload 字段非常多，全部建模容易过时，
用 ``extra='ignore'`` 让多余字段被静默忽略，向前向后都兼容。
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class LastCommit(BaseModel):
    id: str = ""


class MRAttributes(BaseModel):
    model_config = ConfigDict(extra="ignore")

    iid: int
    state: str = ""
    action: str = ""
    target_branch: str = ""
    source_branch: str = ""
    title: str = ""
    work_in_progress: bool = False
    draft: bool = False
    last_commit: LastCommit = Field(default_factory=LastCommit)


class Project(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    path_with_namespace: str = ""


class GitLabMRPayload(BaseModel):
    """``Merge Request Hook`` 事件 payload 的核心字段。"""

    model_config = ConfigDict(extra="ignore")

    object_kind: str = ""
    event_type: str = ""
    project: Project
    object_attributes: MRAttributes

    # 触发审查的动作集合：opened / update / reopen
    REVIEW_ACTIONS: ClassVar[frozenset[str]] = frozenset({"open", "reopen", "update"})

    def should_review(self) -> bool:
        attrs = self.object_attributes
        if self.object_kind not in {"merge_request"}:
            return False
        if attrs.action not in self.REVIEW_ACTIONS:
            return False
        if attrs.state in {"closed", "merged"}:
            return False
        if attrs.work_in_progress or attrs.draft:
            return False
        return True

    @property
    def head_sha(self) -> str:
        return self.object_attributes.last_commit.id or ""
