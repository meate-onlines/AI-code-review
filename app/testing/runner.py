"""Skill 单测运行器。

校验两个维度：
1. **触发器测试（trigger）**：仅跑 SkillSelector，不调 AI；速度快，成本零。
2. **端到端测试（e2e）**：跑 chain.ainvoke，验证 AI 是否检出 / 不误报；
   消耗 AI 调用，建议在 CI 里按需开启（`--no-ai` 切换）。

设计要点：
- 使用一个共享的 review_chain（已带重试、结构化输出）；
- 通过 RunnableConfig 注入 metadata + UsageCollector，让测试也能产出 token 报告；
- 用例失败原因尽可能具体，便于规范维护者快速定位。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from app.adapters.language_detect import detect_language
from app.chains import ReviewResult, build_review_chain
from app.observability import UsageCollector, build_run_config, configure_langsmith
from app.settings import Settings
from app.skills.models import Skill
from app.skills.prompt_builder import render_standards_block
from app.skills.registry import SkillRegistry
from app.skills.selector import ReviewContext, SkillSelector
from app.testing.case_loader import load_all
from app.testing.models import (
    CaseResult,
    Expect,
    SkillTestCase,
    SkillTestSuite,
    SuiteResult,
)

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


class SkillTestRunner:
    """Skill 单测的运行器。"""

    def __init__(
        self,
        settings: Settings,
        *,
        call_ai: bool = True,
        concurrency: int | None = None,
    ) -> None:
        self.settings = settings
        self.call_ai = call_ai
        self.concurrency = concurrency or settings.review.concurrency

        registry = SkillRegistry.from_dir(settings.skills.standards_dir)
        self.registry = registry
        self.selector = SkillSelector(registry, max_skills=settings.skills.max_skills_per_file)

        self.collector = UsageCollector()
        if call_ai:
            configure_langsmith(settings.langsmith)
            self.chain = build_review_chain(settings)
        else:
            self.chain = None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    async def run_all(self, skill_filter: str | None = None) -> list[SuiteResult]:
        """跑 ``standards/`` 下所有测试集，可按 skill name 过滤。"""
        suites = list(load_all(self.settings.skills.standards_dir))
        if skill_filter:
            suites = [s for s in suites if s.skill == skill_filter]

        results: list[SuiteResult] = []
        for suite in suites:
            results.append(await self.run_suite(suite))
        return results

    async def run_suite(self, suite: SkillTestSuite) -> SuiteResult:
        skill = self.registry.get(suite.skill)
        suite_result = SuiteResult(skill=suite.skill, source_path=suite.source_path)

        if skill is None:
            for case in suite.cases:
                suite_result.cases.append(
                    CaseResult(
                        case_name=case.name,
                        skill=suite.skill,
                        file_path=case.file_path,
                        passed=False,
                        failures=[f"skill '{suite.skill}' 未在 registry 中找到"],
                    )
                )
            return suite_result

        sem = asyncio.Semaphore(self.concurrency)

        async def _bounded(case: SkillTestCase) -> CaseResult:
            async with sem:
                return await self._run_case(skill, case)

        suite_result.cases = list(await asyncio.gather(*[_bounded(c) for c in suite.cases]))
        return suite_result

    # ------------------------------------------------------------------
    # 单 case
    # ------------------------------------------------------------------
    async def _run_case(self, skill: Skill, case: SkillTestCase) -> CaseResult:
        start = time.perf_counter()
        language = case.language or detect_language(case.file_path)
        ctx = ReviewContext(
            file_path=case.file_path,
            language=language,
            diff=case.diff or "",
            code=case.code,
        )
        matched = self.selector.match(ctx)
        matched_names = [s.name for s in matched]

        failures: list[str] = []
        notes: list[str] = []

        # 1. 触发器维度
        self._check_trigger(skill, case.expect, matched_names, failures)

        # 当用例本意就是验证"不该触发"时，没必要再调 AI
        if not self._trigger_hit_ok_for_ai(skill, case.expect, matched_names):
            return CaseResult(
                case_name=case.name,
                skill=skill.name,
                file_path=case.file_path,
                passed=not failures,
                duration_ms=int((time.perf_counter() - start) * 1000),
                failures=failures,
                matched_skills=matched_names,
                notes=notes,
            )

        # 2. 端到端 AI 维度
        if not self.call_ai or self.chain is None:
            notes.append("跳过 AI 调用（--no-ai 模式），仅校验 trigger")
            return CaseResult(
                case_name=case.name,
                skill=skill.name,
                file_path=case.file_path,
                passed=not failures,
                skipped=case.expect.ai_should_find_issue is not None,
                duration_ms=int((time.perf_counter() - start) * 1000),
                failures=failures,
                matched_skills=matched_names,
                notes=notes,
            )

        standards_block, chosen = render_standards_block(
            matched, token_budget=self.settings.review.standards_token_budget
        )
        chosen_names = [s.name for s in chosen]
        result = await self._invoke_chain(case, language, standards_block, chosen_names)

        if result is None:
            failures.append("AI 调用失败（详见日志）")
            return CaseResult(
                case_name=case.name,
                skill=skill.name,
                file_path=case.file_path,
                passed=False,
                duration_ms=int((time.perf_counter() - start) * 1000),
                failures=failures,
                matched_skills=matched_names,
            )

        self._check_ai(skill, case.expect, result, failures)

        return CaseResult(
            case_name=case.name,
            skill=skill.name,
            file_path=case.file_path,
            passed=not failures,
            duration_ms=int((time.perf_counter() - start) * 1000),
            failures=failures,
            matched_skills=matched_names,
            ai_issue_count=len(result.issues),
            notes=notes,
        )

    async def _invoke_chain(
        self,
        case: SkillTestCase,
        language: str,
        standards_block: str,
        applied: list[str],
    ) -> ReviewResult | None:
        cfg = build_run_config(
            file_path=case.file_path,
            language=language,
            applied_skills=applied,
            collector=self.collector,
            extra_tags=["test", f"case:{case.name}"],
        )
        try:
            result: ReviewResult = await self.chain.ainvoke(
                {
                    "file_path": case.file_path,
                    "language": language,
                    "code": case.code,
                    "diff": case.diff,
                    "standards_block": standards_block,
                },
                config=cfg,
            )
            for issue in result.issues:
                self.collector.summary.add_issue(issue.standard_id)
            return result
        except Exception as exc:
            logger.exception("test case AI 调用异常 %s: %s", case.name, exc)
            return None

    # ------------------------------------------------------------------
    # 断言
    # ------------------------------------------------------------------
    @staticmethod
    def _check_trigger(
        skill: Skill,
        expect: Expect,
        matched_names: list[str],
        failures: list[str],
    ) -> None:
        if expect.skill_should_hit is None:
            return
        hit = skill.name in matched_names
        if expect.skill_should_hit and not hit:
            failures.append(
                f"期望命中 skill '{skill.name}' 但未命中（实际命中：{matched_names or '空'}）"
            )
        elif (not expect.skill_should_hit) and hit:
            failures.append(f"期望不命中 skill '{skill.name}' 但命中了")

    @staticmethod
    def _trigger_hit_ok_for_ai(skill: Skill, expect: Expect, matched_names: list[str]) -> bool:
        """如果用例明确期望 skill 不被命中，就没必要继续跑 AI。"""
        if expect.skill_should_hit is False:
            return False
        return True

    @staticmethod
    def _check_ai(
        skill: Skill,
        expect: Expect,
        result: ReviewResult,
        failures: list[str],
    ) -> None:
        related = [i for i in result.issues if (i.standard_id == skill.name) or not expect.must_reference_standard]
        if expect.ai_should_find_issue is True:
            if expect.must_reference_standard:
                pool = [i for i in result.issues if i.standard_id == skill.name]
                if not pool:
                    failures.append(
                        f"期望 AI 找到指向 '{skill.name}' 的 issue，实际无（issues={len(result.issues)}）"
                    )
                    return
            elif not result.issues:
                failures.append("期望 AI 至少返回 1 个 issue，实际为 0")
                return
        elif expect.ai_should_find_issue is False:
            # 既不应找到相关 issue，也不应被 skip（skip 等于漏审）
            if expect.must_reference_standard:
                pool = [i for i in result.issues if i.standard_id == skill.name]
                if pool:
                    failures.append(
                        f"期望 AI 不返回与 '{skill.name}' 相关的 issue，实际有 {len(pool)} 条"
                    )
            elif result.issues:
                failures.append(f"期望 AI 不返回 issue，实际返回 {len(result.issues)} 条")

        if expect.min_severity is not None:
            threshold = _SEVERITY_ORDER[expect.min_severity]
            pool = related if expect.must_reference_standard else result.issues
            if not any(_SEVERITY_ORDER[i.severity] >= threshold for i in pool):
                failures.append(
                    f"期望至少一条 issue severity >= {expect.min_severity}，"
                    f"实际：{[i.severity for i in pool] or '空'}"
                )

        if expect.issue_keywords:
            pool = related if expect.must_reference_standard else result.issues
            joined = "\n".join((i.message or "") + " " + (i.suggestion or "") for i in pool)
            if not any(kw in joined for kw in expect.issue_keywords):
                failures.append(
                    f"期望 issue 文本命中关键词之一 {expect.issue_keywords}，实际未命中"
                )

        if expect.forbid_issue_keywords:
            joined = "\n".join((i.message or "") + " " + (i.suggestion or "") for i in result.issues)
            hit = [kw for kw in expect.forbid_issue_keywords if kw in joined]
            if hit:
                failures.append(f"出现了禁止的关键词：{hit}")


# ---------------------------------------------------------------------------
# 终端报表（rich）
# ---------------------------------------------------------------------------
def print_results(results: list[SuiteResult], verbose: bool = False) -> int:
    """打印测试结果汇总，返回非 0 退出码代表存在失败用例。"""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    overview = Table(title="Skill 单测结果")
    overview.add_column("Skill")
    overview.add_column("通过", justify="right", style="green")
    overview.add_column("失败", justify="right", style="red")
    overview.add_column("跳过", justify="right", style="yellow")
    overview.add_column("用时(ms)", justify="right")
    overview.add_column("文件")

    total_failed = 0
    for suite in results:
        used_ms = sum(c.duration_ms for c in suite.cases)
        total_failed += suite.failed
        overview.add_row(
            suite.skill,
            str(suite.passed),
            str(suite.failed),
            str(suite.skipped),
            str(used_ms),
            Path(suite.source_path or "").name,
        )
    console.print(overview)

    fail_cases = [(s, c) for s in results for c in s.cases if not c.passed and not c.skipped]
    if fail_cases:
        console.rule("[bold red]失败详情")
        for suite, case in fail_cases:
            console.print(f"[red]✗[/red] [{suite.skill}] {case.case_name}  ({case.file_path})")
            for f in case.failures:
                console.print(f"    - {f}")
            if verbose:
                console.print(f"    matched_skills={case.matched_skills}, "
                              f"ai_issues={case.ai_issue_count}")

    return 1 if total_failed > 0 else 0
