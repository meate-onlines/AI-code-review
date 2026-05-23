"""把一组命中的 skill 拼成 prompt 中的 ``standards_block``。

包含 token 预算控制：粗略按 ``len(text)/3`` 估算 token 数（中英文混合的折中近似），
超出预算时按 severity 优先级保留高严重度规范，被截断的条目会用占位行说明。
"""

from __future__ import annotations

from app.skills.models import Skill

_SEVERITY_RANK = {"critical": 2, "warning": 1, "info": 0}


def _estimate_tokens(text: str) -> int:
    """非常粗略的 token 估算，仅用于做截断决策，不用于计费。"""
    return max(1, len(text) // 3)


def render_standards_block(skills: list[Skill], token_budget: int = 4000) -> tuple[str, list[Skill]]:
    """渲染 standards 块文本，并返回最终被纳入的 skill 列表。

    返回值同时给出实际使用的 skill 列表，便于上层把 ``standard_id`` 写回 ReviewResult。
    """
    if not skills:
        return "（本次未匹配到适用的团队规范，按通用最佳实践审查）", []

    sorted_skills = sorted(
        skills,
        key=lambda s: (-_SEVERITY_RANK.get(s.severity, 0), s.name),
    )

    chosen: list[Skill] = []
    chunks: list[str] = []
    used_tokens = 0

    for skill in sorted_skills:
        rendered = skill.render()
        cost = _estimate_tokens(rendered)
        if used_tokens + cost > token_budget and chosen:
            break
        chunks.append(rendered)
        chosen.append(skill)
        used_tokens += cost

    dropped = len(sorted_skills) - len(chosen)
    block = "\n---\n\n".join(chunks)
    if dropped > 0:
        block += f"\n\n> 注：另有 {dropped} 条低严重度规范因 token 预算被折叠，未注入正文。"
    return block, chosen
