"""Webhook 业务处理：受 Semaphore 控制的并发审查 + summary 日志输出。"""

from __future__ import annotations

import asyncio
import logging

from app.observability import UsageSummary
from app.pipeline import Reviewer
from app.settings import Settings
from app.webhook.dedupe import CommitDedupe
from app.webhook.models import GitLabMRPayload

logger = logging.getLogger(__name__)


class WebhookHandler:
    """单实例长生命周期，由 FastAPI 应用启动时构造一次。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.reviewer = Reviewer(settings)
        self.dedupe = CommitDedupe(ttl_seconds=settings.webhook.dedupe_ttl_seconds)
        self._sem = asyncio.Semaphore(settings.webhook.max_concurrent_reviews)
        # 启动时记录基线 token 计数，每次 MR 完成时算 delta
        self._baseline_calls = 0

    async def warmup(self) -> None:
        """启动时连一下 GitLab，确保配置正确。"""
        if not self.settings.webhook.warmup_on_start:
            return
        # GitLabClient 在构造时已经 .auth()，这里只做轻量探测
        try:
            self.reviewer.gitlab.list_mrs_updated_today()
            logger.info("GitLab 预热成功")
        except Exception as exc:
            logger.error("GitLab 预热失败：%s", exc)
            raise

    async def handle_mr_event(self, payload: GitLabMRPayload) -> str:
        """对接收到的 MR 事件做调度；返回一个状态字符串供日志/响应使用。"""
        if not payload.should_review():
            return "skipped:not-reviewable"

        project_id = payload.project.id
        mr_iid = payload.object_attributes.iid
        head_sha = payload.head_sha

        if not self.dedupe.claim(project_id, mr_iid, head_sha):
            logger.info("命中 dedupe，跳过 project=%s mr=%s sha=%s",
                        project_id, mr_iid, head_sha[:8])
            return "skipped:duplicate"

        # 异步触发，不阻塞 webhook 响应
        asyncio.create_task(self._run(project_id, mr_iid, head_sha))
        return "queued"

    async def _run(self, project_id: int, mr_iid: int, head_sha: str) -> None:
        async with self._sem:
            logger.info("开始审查 project=%s mr=%s sha=%s",
                        project_id, mr_iid, head_sha[:8])
            try:
                before = _snapshot(self.reviewer.collector.summary)
                await self.reviewer.review_mr_full(project_id, mr_iid)
                after = _snapshot(self.reviewer.collector.summary)
                if self.settings.webhook.log_summary_per_mr:
                    _log_delta(project_id, mr_iid, before, after)
            except Exception as exc:
                logger.exception("审查失败 project=%s mr=%s: %s", project_id, mr_iid, exc)
                self.dedupe.forget(project_id, mr_iid, head_sha)


def _snapshot(summary: UsageSummary) -> dict[str, int]:
    return {
        "calls": summary.total_calls,
        "prompt_tokens": summary.total_prompt_tokens,
        "completion_tokens": summary.total_completion_tokens,
        "total_tokens": summary.total_tokens,
    }


def _log_delta(project_id: int, mr_iid: int, before: dict[str, int], after: dict[str, int]) -> None:
    delta = {k: after[k] - before[k] for k in after}
    logger.info(
        "MR 审查完成 project=%s mr=%s calls=+%d prompt=+%d completion=+%d total=+%d",
        project_id, mr_iid,
        delta["calls"], delta["prompt_tokens"],
        delta["completion_tokens"], delta["total_tokens"],
    )
