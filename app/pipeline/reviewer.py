"""审查编排：拉文件 → 选 skill → 并发调 AI → 回写评论。

把"读 MR / 审查 / 写评论"三段拆开，链路里只剩纯函数与异步调度。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.adapters.gitlab_client import GitLabClient, MRFileChange, file_matches
from app.adapters.language_detect import detect_language
from app.chains import ReviewResult, build_review_chain
from app.observability import (
    UsageCollector,
    build_run_config,
    configure_langsmith,
    print_usage_summary,
)
from app.settings import Settings
from app.skills.prompt_builder import render_standards_block
from app.skills.registry import SkillRegistry
from app.skills.selector import ReviewContext, SkillSelector
from app.skills.semantic import SemanticIndex

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ReviewTask:
    """单个文件审查的内部任务对象。"""

    change: MRFileChange
    language: str
    code: str
    inputs: dict
    skill_ids: list[str]


class Reviewer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gitlab = GitLabClient(settings.gitlab)

        if settings.skills.enabled:
            registry = SkillRegistry.from_dir(settings.skills.standards_dir)

            semantic_index: SemanticIndex | None = None
            if settings.skills.semantic.enabled:
                try:
                    semantic_index = SemanticIndex(settings)
                    semantic_index.build(registry.all())
                    if len(semantic_index) == 0:
                        logger.warning("语义索引为空，本次仅用硬匹配")
                        semantic_index = None
                except Exception as exc:
                    logger.warning("语义索引初始化失败，回退为纯硬匹配：%s", exc)
                    semantic_index = None

            self.selector: SkillSelector | None = SkillSelector(
                registry,
                max_skills=settings.skills.max_skills_per_file,
                semantic_index=semantic_index,
                hard_match_floor=settings.skills.hard_match_floor,
                semantic_top_k=settings.skills.semantic.top_k,
                semantic_min_score=settings.skills.semantic.min_score,
            )
            logger.info(
                "Skills 已启用，共加载 %d 条规范（语义索引：%s）",
                len(registry), "on" if semantic_index else "off",
            )
        else:
            self.selector = None
            logger.info("Skills 未启用")

        # 必须在构造 LLM 之前设置 LangSmith 环境变量，
        # ChatOpenAI 内部会在 invoke 时读取这些 env 决定是否上报追踪
        configure_langsmith(settings.langsmith)
        self.chain = build_review_chain(settings)
        self.collector = UsageCollector()

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    async def run_today(self) -> None:
        """审查今天有更新的所有 MR。"""
        mrs = self.gitlab.list_mrs_updated_today()
        logger.info("发现 %d 个待审查 MR", len(mrs))
        for mr_summary in mrs:
            try:
                await self.review_mr(mr_summary.project_id, mr_summary.iid)
            except Exception as exc:
                logger.exception("MR 审查失败 project=%s iid=%s: %s",
                                 mr_summary.project_id, mr_summary.iid, exc)
        self._print_summary_if_needed()

    async def review_mr(
        self,
        project_id: int,
        mr_iid: int,
        *,
        print_summary: bool = False,
        full_diff: bool = False,
    ) -> None:
        """审查单个 MR。

        - ``print_summary=True``：结束后立即打印本次 MR 的 usage 汇总；
          ``run_today`` 中由调用方在最末尾统一打印，避免每个 MR 都打印一次。
        - ``full_diff=True``：审查 MR 的完整累积变更（webhook 模式适用），
          否则只审查"今日 commit"触及的文件（cron 模式，与旧版行为一致）。
        """
        _, mr = self.gitlab.get_mr(project_id, mr_iid)
        logger.info("开始审查 MR: %s !%s - %s", project_id, mr_iid, getattr(mr, "title", ""))

        tasks = list(self._build_tasks(mr, full_diff=full_diff))
        if not tasks:
            logger.info("MR 内无需审查的文件，跳过")
            if print_summary:
                self._print_summary_if_needed()
            return

        sem = asyncio.Semaphore(self.settings.review.concurrency)

        async def _bounded(task: _ReviewTask) -> tuple[_ReviewTask, ReviewResult | None]:
            async with sem:
                try:
                    run_cfg = build_run_config(
                        file_path=task.change.file_path,
                        language=task.language,
                        applied_skills=task.skill_ids,
                        mr_iid=mr_iid,
                        project_id=project_id,
                        collector=self.collector,
                    )
                    result: ReviewResult = await self.chain.ainvoke(task.inputs, config=run_cfg)
                    result.applied_skill_ids = task.skill_ids
                    return task, result
                except Exception as exc:
                    logger.exception("AI 审查异常 file=%s: %s", task.change.file_path, exc)
                    return task, None

        results = await asyncio.gather(*[_bounded(t) for t in tasks])

        for task, result in results:
            if result is None:
                continue
            # 把命中的规范统计到 collector（issue 维度，便于后续算"哪条规范最有效"）
            for issue in result.issues:
                self.collector.summary.add_issue(issue.standard_id)
            self._publish(mr, task, result)

        if print_summary:
            self._print_summary_if_needed()

    def _print_summary_if_needed(self) -> None:
        if self.settings.langsmith.local_summary and self.collector.summary.total_calls > 0:
            print_usage_summary(self.collector.summary)

    async def review_mr_full(
        self,
        project_id: int,
        mr_iid: int,
        *,
        print_summary: bool = False,
    ) -> None:
        """Webhook 模式入口：审查 MR 的完整累积变更。"""
        await self.review_mr(project_id, mr_iid, print_summary=print_summary, full_diff=True)

    # ------------------------------------------------------------------
    # 任务构造（同步部分；网络 IO 多但量小，保持简单）
    # ------------------------------------------------------------------
    def _build_tasks(self, mr, *, full_diff: bool = False) -> list[_ReviewTask]:
        rv = self.settings.review
        tasks: list[_ReviewTask] = []

        change_iter = (
            self.gitlab.iter_mr_full_changes(mr) if full_diff
            else self.gitlab.iter_today_changes(mr)
        )
        for change in change_iter:
            if change.deleted_file:
                continue
            if not file_matches(change.file_path, rv.include_patterns, rv.exclude_patterns):
                logger.debug("跳过不在白名单的文件：%s", change.file_path)
                continue

            content = self.gitlab.get_file_content(
                change.project_id, change.file_path, change.source_branch
            )
            if not content:
                continue
            if len(content.encode("utf-8")) > rv.max_file_size_kb * 1024:
                logger.info("文件过大，跳过：%s", change.file_path)
                continue

            language = detect_language(change.file_path)
            ctx = ReviewContext(
                file_path=change.file_path,
                language=language,
                diff=change.diff,
                code=content,
            )

            skill_ids: list[str] = []
            standards_block = "（本次未匹配到适用的团队规范，按通用最佳实践审查）"
            if self.selector is not None:
                matched = self.selector.match(ctx)
                if not matched and self.settings.skills.require_match:
                    logger.info("未命中规范且 require_match=true，跳过：%s", change.file_path)
                    continue
                standards_block, chosen = render_standards_block(
                    matched, token_budget=rv.standards_token_budget
                )
                skill_ids = [s.name for s in chosen]
                logger.info("文件 %s 命中规范：%s", change.file_path, skill_ids)

            tasks.append(
                _ReviewTask(
                    change=change,
                    language=language,
                    code=content,
                    inputs={
                        "file_path": change.file_path,
                        "language": language,
                        "code": content,
                        "diff": change.diff,
                        "standards_block": standards_block,
                    },
                    skill_ids=skill_ids,
                )
            )

        return tasks

    # ------------------------------------------------------------------
    # 评论回写
    # ------------------------------------------------------------------
    def _publish(self, mr, task: _ReviewTask, result: ReviewResult) -> None:
        if self.settings.review.respect_skip_flag and result.skip:
            logger.info("AI 标记为可跳过：%s", task.change.file_path)
            return

        filtered = result.filter_by_min_severity(self.settings.review.comment_min_severity)
        if not filtered.issues:
            logger.info("无达阈 issue，跳过评论：%s", task.change.file_path)
            return

        for issue in filtered.issues:
            body = self._format_issue(task, result, issue)
            self.gitlab.post_inline_note(
                mr=mr,
                body=body,
                file_path=task.change.file_path,
                new_line=issue.line,
            )
            logger.info(
                "已发评论 file=%s line=%s severity=%s standard=%s",
                task.change.file_path, issue.line, issue.severity, issue.standard_id,
            )

    @staticmethod
    def _format_issue(task: _ReviewTask, result: ReviewResult, issue) -> str:
        head = f"**AI Review · {issue.severity.upper()} · {issue.category}**"
        if issue.standard_id:
            head += f"  \n违反规范：`{issue.standard_id}`"
        loc = f"行号：{issue.line}" if issue.line else "（未定位到具体行）"
        body = [
            head,
            "",
            loc,
            "",
            issue.message,
        ]
        if issue.suggestion:
            body += ["", "**修复建议：**", issue.suggestion]
        if result.summary:
            body += ["", "---", f"_本文件总评：{result.summary}_"]
        if task.skill_ids:
            body += ["", f"_本次注入规范：{', '.join(task.skill_ids)}_"]
        return "\n".join(body)
