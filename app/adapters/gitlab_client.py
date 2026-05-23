"""GitLab IO 封装。

所有与 GitLab 通信的逻辑收敛到本模块，向外只暴露领域对象（MR/文件改动），
便于切换数据源（如 GitHub）或在测试中替换为内存实现。
"""

from __future__ import annotations

import hmac
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Iterator

import gitlab
from gitlab.exceptions import GitlabGetError

from app.settings import GitLabConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MRFileChange:
    """合并请求中单个文件的改动。"""

    project_id: int
    mr_iid: int
    file_path: str
    diff: str
    source_branch: str
    new_file: bool
    deleted_file: bool


class GitLabClient:
    def __init__(self, config: GitLabConfig) -> None:
        self._gl = gitlab.Gitlab(
            config.url,
            private_token=config.token.get_secret_value(),
            timeout=config.timeout,
        )
        self._gl.auth()

    def list_mrs_updated_today(self) -> list:
        """列出今天有更新的、处于 opened 状态的 MR。"""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        start = today_start.isoformat()
        end = today_end.isoformat()

        all_mrs: list = []
        for project in self._gl.projects.list(all=True):
            try:
                mrs = project.mergerequests.list(
                    state="opened",
                    updated_after=start,
                    updated_before=end,
                )
                all_mrs.extend(mrs)
            except Exception as exc:
                logger.warning("拉取 project %s 的 MR 列表失败：%s", project.id, exc)
        return all_mrs

    def get_mr(self, project_id: int, mr_iid: int):
        project = self._gl.projects.get(project_id)
        return project, project.mergerequests.get(mr_iid)

    def iter_today_changes(self, mr) -> Iterator[MRFileChange]:
        """遍历某个 MR 在"今天"提交所触及的文件改动，去重后逐个 yield。"""
        project = self._gl.projects.get(mr.project_id)
        mr = project.mergerequests.get(mr.iid)
        today = datetime.now().date()
        processed: set[str] = set()

        for commit in mr.commits():
            try:
                commit_date = datetime.strptime(
                    commit.committed_date, "%Y-%m-%dT%H:%M:%S.%fZ"
                ).date()
            except ValueError:
                continue
            if commit_date != today:
                continue

            for change in commit.diff(get_all=True, deleted_file=False, diff=True):
                path = change.get("new_path") or change.get("old_path")
                if not path or path in processed:
                    continue
                processed.add(path)
                yield MRFileChange(
                    project_id=mr.project_id,
                    mr_iid=mr.iid,
                    file_path=path,
                    diff=change.get("diff", ""),
                    source_branch=mr.source_branch,
                    new_file=bool(change.get("new_file")),
                    deleted_file=bool(change.get("deleted_file")),
                )

    def iter_mr_full_changes(self, mr) -> Iterator[MRFileChange]:
        """遍历 MR 的完整累积变更（webhook 模式）。

        与 ``iter_today_changes`` 不同：这里不按 commit 切片，而是直接读
        ``mr.changes()``，保证审查的是"从 source 分支到 target 分支的全部变化"，
        避免重复触发时漏看历史 commit 中的问题文件。
        """
        project = self._gl.projects.get(mr.project_id)
        mr = project.mergerequests.get(mr.iid)
        try:
            data = mr.changes()
        except Exception as exc:
            logger.warning("拉取 mr.changes 失败 project=%s iid=%s: %s",
                           mr.project_id, mr.iid, exc)
            return

        for change in data.get("changes", []) or []:
            path = change.get("new_path") or change.get("old_path")
            if not path:
                continue
            if change.get("deleted_file"):
                continue
            yield MRFileChange(
                project_id=mr.project_id,
                mr_iid=mr.iid,
                file_path=path,
                diff=change.get("diff", ""),
                source_branch=mr.source_branch,
                new_file=bool(change.get("new_file")),
                deleted_file=bool(change.get("deleted_file")),
            )

    def get_file_content(self, project_id: int, file_path: str, ref: str) -> str | None:
        """读取指定 ref 下的文件文本；不存在返回 None。"""
        try:
            project = self._gl.projects.get(project_id)
            return project.files.get(file_path, ref=ref).decode().decode("utf-8")
        except GitlabGetError:
            logger.info("文件读取失败（可能已删除或路径不可达）：%s @ %s", file_path, ref)
            return None
        except UnicodeDecodeError:
            logger.info("文件非 UTF-8，跳过：%s", file_path)
            return None

    def post_inline_note(
        self,
        mr,
        body: str,
        file_path: str,
        new_line: int | None,
    ) -> None:
        """在 MR 上发表评论。

        - ``new_line`` 为 None 时退化为普通评论（不绑定行号）；
        - 否则使用 GitLab 行内评论（绑定到 head_sha 的新文件行）。
        """
        if new_line is None:
            mr.notes.create({"body": body})
            return
        try:
            mr.discussions.create(
                {
                    "body": body,
                    "position": {
                        "base_sha": mr.diff_refs.get("base_sha", ""),
                        "head_sha": mr.diff_refs.get("head_sha", ""),
                        "start_sha": mr.diff_refs.get("start_sha", ""),
                        "position_type": "text",
                        "file_path": file_path,
                        "new_path": file_path,
                        "new_line": new_line,
                    },
                }
            )
        except Exception as exc:
            logger.warning("行内评论失败 %s:%s，回退为普通评论：%s", file_path, new_line, exc)
            mr.notes.create({"body": body})


def verify_webhook_token(expected: str | None, received: str | None) -> bool:
    """常数时间比较 GitLab Webhook 的 X-Gitlab-Token。

    - 未配置 secret 时（expected 为 None/空），不校验直接放行；
    - 配置了但 header 缺失 / 不一致时拒绝。
    """
    if not expected:
        return True
    if not received:
        return False
    return hmac.compare_digest(expected, received)


def file_matches(file_path: str, includes: Iterable[str], excludes: Iterable[str]) -> bool:
    """供 pipeline 层使用的小工具：路径白名单/黑名单过滤。"""
    from fnmatch import fnmatch

    inc = list(includes)
    exc = list(excludes)
    if inc and not any(fnmatch(file_path, p) for p in inc):
        return False
    if any(fnmatch(file_path, p) for p in exc):
        return False
    # 兜底：跳过明显的二进制资源
    if re.search(r"\.(png|jpg|jpeg|gif|webp|ico|pdf|zip|tar|gz|jar|class)$", file_path, re.IGNORECASE):
        return False
    return True
