"""加载 ``standards/`` 目录下的 ``*.tests.yml`` 测试集。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import yaml
from pydantic import ValidationError

from app.testing.models import SkillTestSuite

logger = logging.getLogger(__name__)


def discover_test_files(standards_dir: str | Path) -> list[Path]:
    """递归扫描 ``standards/`` 下所有 ``*.tests.yml``。"""
    root = Path(standards_dir).resolve()
    if not root.exists():
        return []
    return sorted(root.rglob("*.tests.yml"))


def load_test_file(path: str | Path) -> SkillTestSuite | None:
    """读取单个测试集文件；失败时记录日志并返回 None。"""
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.error("测试文件 YAML 解析失败 %s: %s", p, exc)
        return None
    try:
        suite = SkillTestSuite(**raw)
        suite.source_path = str(p)
        return suite
    except ValidationError as exc:
        logger.error("测试文件字段校验失败 %s: %s", p, exc)
        return None


def load_all(standards_dir: str | Path) -> Iterable[SkillTestSuite]:
    for path in discover_test_files(standards_dir):
        suite = load_test_file(path)
        if suite is not None:
            yield suite
