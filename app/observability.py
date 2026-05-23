"""可观测性：LangSmith 接入 + 本地 token / skill 命中统计。

设计要点：
- LangSmith 的开关与本地统计完全解耦——没有 LangSmith API key 也能用本地汇总；
- 每次 chain 调用通过 ``RunnableConfig`` 注入 metadata（file_path / skills / mr）与 tags，
  这样在 LangSmith UI 上可按 skill / 文件 / MR 自由过滤；
- token 数从 LLM 的 ``response.llm_output["token_usage"]`` 或 ``AIMessage.usage_metadata`` 中读取。
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from app.settings import LangSmithConfig

logger = logging.getLogger(__name__)


def configure_langsmith(cfg: LangSmithConfig) -> bool:
    """根据配置设置 LangSmith 环境变量；返回是否真正启用。

    LangChain 通过环境变量 ``LANGCHAIN_TRACING_V2`` 等启用追踪，
    本函数把 settings 中的字段映射到对应变量，保证一处配置全局生效。
    """
    if not cfg.enabled:
        os.environ.pop("LANGCHAIN_TRACING_V2", None)
        return False
    if cfg.api_key is None:
        logger.warning("LangSmith enabled 但未提供 api_key，跳过启用")
        return False

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"] = cfg.endpoint
    os.environ["LANGCHAIN_API_KEY"] = cfg.api_key.get_secret_value()
    os.environ["LANGCHAIN_PROJECT"] = cfg.project
    logger.info("LangSmith 已启用，project=%s endpoint=%s", cfg.project, cfg.endpoint)
    return True


# ---------------------------------------------------------------------------
# 本地 UsageCollector
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class _RunStats:
    file_path: str
    language: str
    applied_skills: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str | None = None
    error: str | None = None


@dataclass(slots=True)
class UsageSummary:
    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    by_file: list[_RunStats] = field(default_factory=list)
    skill_hits: Counter = field(default_factory=Counter)
    skill_issue_counts: Counter = field(default_factory=Counter)
    errors: int = 0

    def add_run(self, stats: _RunStats) -> None:
        self.total_calls += 1
        self.total_prompt_tokens += stats.prompt_tokens
        self.total_completion_tokens += stats.completion_tokens
        self.total_tokens += stats.total_tokens
        if stats.error:
            self.errors += 1
        for skill in stats.applied_skills:
            self.skill_hits[skill] += 1
        self.by_file.append(stats)

    def add_issue(self, standard_id: str | None) -> None:
        if standard_id:
            self.skill_issue_counts[standard_id] += 1


class UsageCollector(BaseCallbackHandler):
    """LangChain BaseCallbackHandler，按 run_id 聚合每次 LLM 调用的 token。

    通过 ``RunnableConfig.metadata`` 把文件信息和命中规范带进来，
    on_llm_end 时再从 response.llm_output 把 token usage 取出来落盘到 summary。
    """

    raise_error = False
    run_inline = True

    def __init__(self) -> None:
        self.summary = UsageSummary()
        # run_id → 临时持有的元数据（在 on_llm_start 写入，on_llm_end 消费）
        self._pending: dict[UUID, _RunStats] = {}

    # ------------------------------------------------------------------
    # LLM lifecycle
    # ------------------------------------------------------------------
    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        meta = metadata or {}
        self._pending[run_id] = _RunStats(
            file_path=meta.get("file_path", "<unknown>"),
            language=meta.get("language", "text"),
            applied_skills=list(meta.get("applied_skills", []) or []),
            model=meta.get("ls_model_name") or meta.get("model"),
        )

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        # chat 模型走的是 on_chat_model_start，路由到统一处理
        self.on_llm_start(serialized, [], run_id=run_id, metadata=metadata, **kwargs)

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        stats = self._pending.pop(run_id, None)
        if stats is None:
            return

        usage = self._extract_token_usage(response)
        stats.prompt_tokens = usage.get("prompt_tokens", 0)
        stats.completion_tokens = usage.get("completion_tokens", 0)
        stats.total_tokens = usage.get("total_tokens",
                                       stats.prompt_tokens + stats.completion_tokens)
        if response.llm_output and "model_name" in response.llm_output:
            stats.model = response.llm_output["model_name"]

        self.summary.add_run(stats)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        stats = self._pending.pop(run_id, None)
        if stats is None:
            stats = _RunStats(file_path="<unknown>", language="text")
        stats.error = type(error).__name__
        self.summary.add_run(stats)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_token_usage(response: LLMResult) -> dict[str, int]:
        """优先从 llm_output 取，其次从每条 generation.message.usage_metadata 累加。"""
        if response.llm_output:
            usage = response.llm_output.get("token_usage") or response.llm_output.get("usage")
            if usage:
                return {
                    "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                    "completion_tokens": int(usage.get("completion_tokens", 0)),
                    "total_tokens": int(usage.get("total_tokens", 0)),
                }

        prompt = completion = total = 0
        for gens in response.generations:
            for gen in gens:
                message = getattr(gen, "message", None)
                usage = getattr(message, "usage_metadata", None) if message else None
                if usage:
                    prompt += int(usage.get("input_tokens", 0))
                    completion += int(usage.get("output_tokens", 0))
                    total += int(usage.get("total_tokens", 0))
        return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


# ---------------------------------------------------------------------------
# 终端汇总打印（rich 表格）
# ---------------------------------------------------------------------------
def print_usage_summary(summary: UsageSummary) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    overview = Table(title="AI Review 运行汇总", show_header=False, expand=False)
    overview.add_column("项")
    overview.add_column("值", justify="right")
    overview.add_row("LLM 调用次数", str(summary.total_calls))
    overview.add_row("错误次数", str(summary.errors))
    overview.add_row("prompt tokens", f"{summary.total_prompt_tokens:,}")
    overview.add_row("completion tokens", f"{summary.total_completion_tokens:,}")
    overview.add_row("total tokens", f"{summary.total_tokens:,}")
    console.print(overview)

    if summary.skill_hits:
        skills = Table(title="Skills 命中分布", show_lines=False)
        skills.add_column("Skill")
        skills.add_column("注入次数", justify="right")
        skills.add_column("AI 命中 issue 次数", justify="right")
        for name, hits in summary.skill_hits.most_common():
            skills.add_row(name, str(hits), str(summary.skill_issue_counts.get(name, 0)))
        console.print(skills)

    if summary.by_file:
        by_file = Table(title="按文件的 token 消耗 (Top 20)", show_lines=False)
        by_file.add_column("文件")
        by_file.add_column("语言")
        by_file.add_column("prompt", justify="right")
        by_file.add_column("completion", justify="right")
        by_file.add_column("total", justify="right")
        by_file.add_column("skills", justify="right")
        ranked = sorted(summary.by_file, key=lambda s: s.total_tokens, reverse=True)[:20]
        for s in ranked:
            by_file.add_row(
                s.file_path,
                s.language,
                f"{s.prompt_tokens:,}",
                f"{s.completion_tokens:,}",
                f"{s.total_tokens:,}",
                str(len(s.applied_skills)),
            )
        console.print(by_file)

    if summary.errors:
        console.print(Panel(f"出现 {summary.errors} 次 LLM 调用错误，详见日志", style="bold red"))


# ---------------------------------------------------------------------------
# 工具：把文件级元数据组装成 RunnableConfig
# ---------------------------------------------------------------------------
def build_run_config(
    *,
    file_path: str,
    language: str,
    applied_skills: list[str],
    mr_iid: int | None = None,
    project_id: int | None = None,
    collector: UsageCollector | None = None,
    extra_tags: list[str] | None = None,
) -> dict[str, Any]:
    """构造 ``chain.ainvoke(..., config=...)`` 用的 RunnableConfig。"""
    tags = [f"lang:{language}"]
    if mr_iid is not None:
        tags.append(f"mr:{mr_iid}")
    if project_id is not None:
        tags.append(f"project:{project_id}")
    tags += [f"skill:{s}" for s in applied_skills]
    if extra_tags:
        tags += extra_tags

    metadata = {
        "file_path": file_path,
        "language": language,
        "applied_skills": applied_skills,
    }
    if mr_iid is not None:
        metadata["mr_iid"] = mr_iid
    if project_id is not None:
        metadata["project_id"] = project_id

    cfg: dict[str, Any] = {
        "tags": tags,
        "metadata": metadata,
        "run_name": f"review:{file_path}",
    }
    if collector is not None:
        cfg["callbacks"] = [collector]
    return cfg


# 用于在外部安全获取 by-skill 汇总（CLI/测试报告复用）
def issue_distribution(summary: UsageSummary) -> dict[str, int]:
    return dict(summary.skill_issue_counts)


# 仅为类型完备；外部模块可直接用 collections.defaultdict
__all__ = [
    "UsageCollector",
    "UsageSummary",
    "build_run_config",
    "configure_langsmith",
    "issue_distribution",
    "print_usage_summary",
]
