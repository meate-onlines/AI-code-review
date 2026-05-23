"""Skill 调度器：根据 ReviewContext 决定本次注入哪些 skill。

匹配流程：
    硬匹配（语言 / 路径 / 排除 / 关键词）
        ↓
    语义兜底（可选；仅当硬匹配数 < hard_match_floor 时启用）
        ↓
    去重 + 排序（severity desc，硬匹配优先，其次按名字）
        ↓
    截断（最多 max_skills_per_file 条）

语义兜底来源：``SemanticIndex.search`` 返回的 (name, score)；
失败/未启用时该步直接跳过，不影响主链路。
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch

from app.skills.models import Skill
from app.skills.registry import SkillRegistry
from app.skills.semantic import SemanticIndex

_SEVERITY_ORDER = {"critical": 2, "warning": 1, "info": 0}


@dataclass(slots=True)
class ReviewContext:
    """匹配 skill 时使用的上下文快照。"""

    file_path: str
    language: str
    diff: str = ""
    code: str = ""
    tags_hint: list[str] | None = None


@dataclass(slots=True)
class MatchInfo:
    """单条命中的来源信息，便于调试与日志。"""

    skill: Skill
    source: str  # "hard" | "semantic"
    score: float | None = None  # semantic 命中时给出余弦相似度


class SkillSelector:
    def __init__(
        self,
        registry: SkillRegistry,
        max_skills: int = 8,
        *,
        semantic_index: SemanticIndex | None = None,
        hard_match_floor: int = 2,
        semantic_top_k: int = 3,
        semantic_min_score: float = 0.55,
    ) -> None:
        self._registry = registry
        self._max_skills = max_skills
        self._semantic = semantic_index
        self._hard_floor = hard_match_floor
        self._semantic_top_k = semantic_top_k
        self._semantic_min_score = semantic_min_score

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def match(self, ctx: ReviewContext) -> list[Skill]:
        """返回最终命中的 skill 列表（已排序与截断）。"""
        infos = self.match_with_info(ctx)
        return [info.skill for info in infos]

    def match_with_info(self, ctx: ReviewContext) -> list[MatchInfo]:
        """带来源信息的匹配结果，便于日志/调试。"""
        hard = [s for s in self._registry.for_language(ctx.language) if self._is_match(s, ctx)]
        hard_infos = [MatchInfo(skill=s, source="hard") for s in hard]

        semantic_infos: list[MatchInfo] = []
        if self._semantic is not None and len(hard_infos) < self._hard_floor:
            hard_names = {s.name for s in hard}
            for name, score in self._semantic.search(
                file_path=ctx.file_path,
                language=ctx.language,
                code=ctx.code,
                top_k=self._semantic_top_k,
                min_score=self._semantic_min_score,
            ):
                if name in hard_names:
                    continue
                skill = self._registry.get(name)
                if skill is None:
                    continue
                semantic_infos.append(MatchInfo(skill=skill, source="semantic", score=score))

        merged = self._rank(hard_infos + semantic_infos)
        return merged[: self._max_skills]

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _match_patterns(file_path: str, patterns: list[str]) -> bool:
        return any(fnmatch(file_path, p) for p in patterns)

    @staticmethod
    def _hit_keywords(text: str, keywords: list[str]) -> bool:
        if not keywords:
            return True
        return any(k in text for k in keywords)

    def _is_match(self, skill: Skill, ctx: ReviewContext) -> bool:
        trig = skill.triggers

        if trig.languages:
            if ctx.language.lower() not in [lang.lower() for lang in trig.languages]:
                return False

        if trig.file_patterns and not self._match_patterns(ctx.file_path, trig.file_patterns):
            return False

        if trig.path_excludes and self._match_patterns(ctx.file_path, trig.path_excludes):
            return False

        if trig.keywords:
            haystack = (ctx.diff or "") + "\n" + (ctx.code or "")
            if not self._hit_keywords(haystack, trig.keywords):
                return False

        return True

    @staticmethod
    def _rank(infos: list[MatchInfo]) -> list[MatchInfo]:
        """硬匹配始终优先；同源内部 severity desc，再 name asc。"""

        def key(info: MatchInfo) -> tuple[int, int, str]:
            source_rank = 0 if info.source == "hard" else 1
            sev_rank = -_SEVERITY_ORDER.get(info.skill.severity, 0)
            return source_rank, sev_rank, info.skill.name

        # 同一 skill 重复出现时去重，优先保留硬匹配那条
        seen: dict[str, MatchInfo] = {}
        for info in sorted(infos, key=key):
            seen.setdefault(info.skill.name, info)
        return list(seen.values())
