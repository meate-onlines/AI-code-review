"""从磁盘加载 ``standards/`` 目录下的所有 skill。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import frontmatter
from pydantic import ValidationError

from app.skills.models import Skill, SkillTriggers

logger = logging.getLogger(__name__)


def _iter_markdown_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        logger.warning("standards 目录不存在：%s", root)
        return []
    return (p for p in root.rglob("*.md") if not p.name.startswith("_"))


def _parse_one(path: Path) -> Skill | None:
    try:
        post = frontmatter.load(path)
    except Exception as exc:
        logger.error("解析 skill 失败 %s: %s", path, exc)
        return None

    meta = dict(post.metadata or {})
    if "name" not in meta:
        logger.error("skill 缺少 name 字段，跳过：%s", path)
        return None

    triggers_data = meta.pop("triggers", {}) or {}
    try:
        triggers = SkillTriggers(**triggers_data)
        skill = Skill(
            name=meta.pop("name"),
            description=meta.pop("description", ""),
            severity=meta.pop("severity", "warning"),
            version=str(meta.pop("version", "1.0")),
            tags=meta.pop("tags", []) or [],
            owner=meta.pop("owner", None),
            triggers=triggers,
            body=post.content,
            source_path=str(path),
        )
    except ValidationError as exc:
        logger.error("skill 字段校验失败 %s: %s", path, exc)
        return None
    return skill


def load_skills(standards_dir: str | Path) -> list[Skill]:
    """递归加载目录下所有 .md，返回 Skill 列表（顺序无关，调度器会再排序）。"""
    root = Path(standards_dir).resolve()
    skills: list[Skill] = []
    names_seen: set[str] = set()

    for path in _iter_markdown_files(root):
        skill = _parse_one(path)
        if skill is None:
            continue
        if skill.name in names_seen:
            logger.error("skill name 重复 %s（来源 %s），跳过该条", skill.name, path)
            continue
        names_seen.add(skill.name)
        skills.append(skill)

    logger.info("加载 skills 完成，共 %d 条（目录 %s）", len(skills), root)
    return skills
