"""Skill 索引。

预先按 language / tag 建二级索引，运行期匹配只需 O(N_lang) 而非全表扫描；
当前规范量小，直接全表也不慢，此处主要是为未来扩展留口。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from app.skills.loader import load_skills
from app.skills.models import Skill


class SkillRegistry:
    def __init__(self, skills: list[Skill]) -> None:
        self._skills: list[Skill] = list(skills)
        self._by_language: dict[str, list[Skill]] = defaultdict(list)
        self._by_tag: dict[str, list[Skill]] = defaultdict(list)
        self._build_indexes()

    @classmethod
    def from_dir(cls, standards_dir: str | Path) -> "SkillRegistry":
        return cls(load_skills(standards_dir))

    def _build_indexes(self) -> None:
        for s in self._skills:
            for lang in s.triggers.languages or ["*"]:
                self._by_language[lang.lower()].append(s)
            for tag in s.tags:
                self._by_tag[tag.lower()].append(s)

    def all(self) -> list[Skill]:
        return list(self._skills)

    def for_language(self, language: str) -> list[Skill]:
        lang_key = (language or "").lower()
        return list({s.name: s for s in self._by_language.get(lang_key, []) + self._by_language.get("*", [])}.values())

    def get(self, name: str) -> Skill | None:
        for s in self._skills:
            if s.name == name:
                return s
        return None

    def __len__(self) -> int:
        return len(self._skills)
