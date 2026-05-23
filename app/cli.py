"""Typer CLI 入口。

子命令：
- ``review today``       审查今天有更新的所有 MR（替代旧 main.py）
- ``review mr``          审查指定 project_id + mr_iid，方便本地调试
- ``review file``        离线跑单个文件，纯调 AI 不写评论，调 prompt 用
- ``skills list``        打印当前加载到的所有 skill
- ``skills match``       给定文件路径，查看会命中哪些 skill
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer

from app.adapters.language_detect import detect_language
from app.chains import build_review_chain
from app.observability import (
    UsageCollector,
    build_run_config,
    configure_langsmith,
    print_usage_summary,
)
from app.pipeline import Reviewer
from app.settings import get_settings
from app.skills.prompt_builder import render_standards_block
from app.skills.registry import SkillRegistry
from app.skills.selector import ReviewContext, SkillSelector
from app.skills.semantic import SemanticIndex
from app.testing.runner import SkillTestRunner, print_results as print_test_results

app = typer.Typer(add_completion=False, help="AI Code Review (LangChain 重构版)")
review_app = typer.Typer(help="代码审查相关命令")
skills_app = typer.Typer(help="规范（skills）管理命令")
skills_index_app = typer.Typer(help="语义索引（embeddings）相关命令")
app.add_typer(review_app, name="review")
app.add_typer(skills_app, name="skills")
skills_app.add_typer(skills_index_app, name="index")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )


# ----------------------------------------------------------------------
# review 子命令
# ----------------------------------------------------------------------
@review_app.command("today")
def review_today(
    config: str = typer.Option("config.yml", "--config", "-c", help="配置文件路径"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """审查今天有更新的所有 MR。"""
    _configure_logging(verbose)
    settings = get_settings(config)
    reviewer = Reviewer(settings)
    asyncio.run(reviewer.run_today())
    typer.echo("今日代码审查完毕")


@review_app.command("mr")
def review_mr(
    project_id: int = typer.Argument(..., help="GitLab 项目 id"),
    mr_iid: int = typer.Argument(..., help="MR 在项目下的 iid"),
    config: str = typer.Option("config.yml", "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """审查指定 MR（本地调试常用），结束后打印 token 与 skill 命中汇总。"""
    _configure_logging(verbose)
    settings = get_settings(config)
    reviewer = Reviewer(settings)
    asyncio.run(reviewer.review_mr(project_id, mr_iid, print_summary=True))
    typer.echo(f"MR {project_id}!{mr_iid} 审查完毕")


@review_app.command("file")
def review_file(
    file_path: Path = typer.Argument(..., exists=True, readable=True, help="本地文件路径"),
    config: str = typer.Option("config.yml", "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    show_usage: bool = typer.Option(True, "--usage/--no-usage", help="结束后打印 token 与 skill 命中"),
) -> None:
    """离线跑单文件审查（不调 GitLab，不写评论），用于调 prompt / skill 触发。"""
    _configure_logging(verbose)
    settings = get_settings(config)
    configure_langsmith(settings.langsmith)

    code = file_path.read_text(encoding="utf-8")
    language = detect_language(str(file_path))

    standards_block = "（未启用 skills）"
    applied: list[str] = []
    if settings.skills.enabled:
        registry = SkillRegistry.from_dir(settings.skills.standards_dir)
        selector = SkillSelector(registry, max_skills=settings.skills.max_skills_per_file)
        matched = selector.match(
            ReviewContext(file_path=str(file_path), language=language, code=code)
        )
        standards_block, chosen = render_standards_block(
            matched, token_budget=settings.review.standards_token_budget
        )
        applied = [s.name for s in chosen]
        typer.echo(f"命中规范：{applied or '（无）'}")

    collector = UsageCollector()
    chain = build_review_chain(settings)
    run_cfg = build_run_config(
        file_path=str(file_path),
        language=language,
        applied_skills=applied,
        collector=collector,
        extra_tags=["adhoc"],
    )
    result = asyncio.run(
        chain.ainvoke(
            {
                "file_path": str(file_path),
                "language": language,
                "code": code,
                "diff": None,
                "standards_block": standards_block,
            },
            config=run_cfg,
        )
    )
    result.applied_skill_ids = applied
    for issue in result.issues:
        collector.summary.add_issue(issue.standard_id)
    typer.echo(result.model_dump_json(indent=2, exclude_none=False))
    if show_usage:
        print_usage_summary(collector.summary)


# ----------------------------------------------------------------------
# skills 子命令
# ----------------------------------------------------------------------
@skills_app.command("list")
def skills_list(
    config: str = typer.Option("config.yml", "--config", "-c"),
) -> None:
    """列出当前加载到的所有 skill。"""
    settings = get_settings(config)
    registry = SkillRegistry.from_dir(settings.skills.standards_dir)
    if len(registry) == 0:
        typer.echo("未加载到任何 skill")
        return
    for s in registry.all():
        langs = ",".join(s.triggers.languages) or "*"
        typer.echo(f"- [{s.severity:8}] {s.name:40} langs={langs:20} tags={s.tags}")


@skills_app.command("match")
def skills_match(
    file_path: str = typer.Argument(..., help="模拟的文件路径，用于触发匹配"),
    config: str = typer.Option("config.yml", "--config", "-c"),
) -> None:
    """给定文件路径，查看会命中哪些 skill。"""
    settings = get_settings(config)
    registry = SkillRegistry.from_dir(settings.skills.standards_dir)
    selector = SkillSelector(registry, max_skills=settings.skills.max_skills_per_file)
    language = detect_language(file_path)
    matched = selector.match(ReviewContext(file_path=file_path, language=language))
    if not matched:
        typer.echo(f"language={language} 未命中任何 skill")
        return
    typer.echo(f"language={language}，共命中 {len(matched)} 条：")
    for s in matched:
        typer.echo(f"  - [{s.severity}] {s.name} — {s.description}")


@skills_index_app.command("rebuild")
def skills_index_rebuild(
    config: str = typer.Option("config.yml", "--config", "-c"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """强制重新构建语义索引（忽略缓存，重新调用 embedding API）。"""
    _configure_logging(verbose)
    settings = get_settings(config)
    if not settings.skills.semantic.enabled:
        typer.echo("settings.skills.semantic.enabled=false，未启用语义匹配，跳过")
        raise typer.Exit(code=0)
    registry = SkillRegistry.from_dir(settings.skills.standards_dir)
    index = SemanticIndex(settings)
    index.rebuild(registry.all())
    typer.echo(f"语义索引重建完成：{len(index)} 条 skill，已写入 {settings.skills.semantic.cache_path}")


@skills_index_app.command("status")
def skills_index_status(
    config: str = typer.Option("config.yml", "--config", "-c"),
) -> None:
    """查看语义索引当前状态（缓存路径、是否启用、命中样例查询）。"""
    settings = get_settings(config)
    cfg = settings.skills.semantic
    typer.echo(f"enabled={cfg.enabled}")
    typer.echo(f"model={cfg.model}")
    typer.echo(f"cache_path={cfg.cache_path} (exists={cfg.cache_path.exists()})")
    typer.echo(f"top_k={cfg.top_k}, min_score={cfg.min_score}")


@skills_app.command("test")
def skills_test(
    config: str = typer.Option("config.yml", "--config", "-c"),
    skill: str | None = typer.Option(None, "--skill", "-s", help="只跑指定 skill 的测试"),
    no_ai: bool = typer.Option(
        False, "--no-ai", help="只校验 trigger 不调 AI（零成本，适合 CI 快速门）"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    show_usage: bool = typer.Option(True, "--usage/--no-usage", help="结束后打印 token 汇总"),
) -> None:
    """跑 standards/ 下所有 *.tests.yml 用例。"""
    _configure_logging(verbose)
    settings = get_settings(config)

    runner = SkillTestRunner(settings, call_ai=not no_ai)
    results = asyncio.run(runner.run_all(skill_filter=skill))

    if not results:
        typer.echo("未发现任何测试集（standards/ 下没有 *.tests.yml）")
        raise typer.Exit(code=0)

    exit_code = print_test_results(results, verbose=verbose)
    if show_usage and runner.collector.summary.total_calls > 0:
        print_usage_summary(runner.collector.summary)
    raise typer.Exit(code=exit_code)


@app.command("serve")
def serve(
    config: str = typer.Option("config.yml", "--config", "-c"),
    host: str | None = typer.Option(None, "--host", help="覆盖 config.webhook.host"),
    port: int | None = typer.Option(None, "--port", help="覆盖 config.webhook.port"),
    reload: bool = typer.Option(False, "--reload", help="开发模式自动重载"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """启动 Webhook 服务，监听 GitLab MR 事件实时审查。"""
    _configure_logging(verbose)
    settings = get_settings(config)
    import uvicorn

    bind_host = host or settings.webhook.host
    bind_port = port or settings.webhook.port
    log_level = "debug" if verbose else "info"
    typer.echo(f"Webhook 服务启动：http://{bind_host}:{bind_port}{settings.webhook.path}")
    uvicorn.run(
        "app.webhook.app:create_app",
        factory=True,
        host=bind_host,
        port=bind_port,
        reload=reload,
        log_level=log_level,
    )


if __name__ == "__main__":
    app()
