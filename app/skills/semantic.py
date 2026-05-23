"""Skill 语义索引（embedding 兜底）。

主要职责：
- 启动时把每条 skill 的"描述 + 标签 + 正文摘要"做 embedding，落本地缓存；
- 给定文件上下文（path/language/code 前缀），返回 top-k 语义相近的 skill；
- 规范内容变化（hash 改变）才重新 embed，启动开销可忽略；
- embedding 服务不可用时彻底降级（不抛错），保证主链路可用。

为什么不直接引 chroma/faiss：
- 规范数量在百级以内，内存 ndarray + 余弦完全够用；
- 减少额外依赖与部署复杂度。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from app.skills.models import Skill

if TYPE_CHECKING:
    from app.settings import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 文本构造（query 与 doc 用相同字段拼装，保证向量空间一致）
# ---------------------------------------------------------------------------
_SKILL_TEXT_MAX = 1500
_QUERY_CODE_MAX = 2000


def _skill_text(skill: Skill) -> str:
    tags = ", ".join(skill.tags) if skill.tags else "—"
    body = skill.body.strip()
    if len(body) > _SKILL_TEXT_MAX:
        body = body[:_SKILL_TEXT_MAX]
    return f"name: {skill.name}\ndescription: {skill.description}\ntags: {tags}\n\n{body}"


def _query_text(file_path: str, language: str, code: str) -> str:
    snippet = (code or "")[:_QUERY_CODE_MAX]
    return f"file: {file_path}\nlanguage: {language}\n\n{snippet}"


def _content_hash(skill: Skill) -> str:
    return hashlib.sha256(_skill_text(skill).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class _Vec:
    name: str
    hash: str
    vector: np.ndarray  # shape: (dim,) float32, L2-normalized
    severity: str


# ---------------------------------------------------------------------------
# 主类
# ---------------------------------------------------------------------------
class SemanticIndex:
    """skill 语义索引。线程不安全，单实例使用。"""

    def __init__(self, settings: "Settings") -> None:
        self.settings = settings
        self._vectors: list[_Vec] = []
        self._matrix: np.ndarray | None = None  # (N, dim)
        self._model_name: str = settings.skills.semantic.model
        self._cache_path: Path = settings.skills.semantic.cache_path
        self._embeddings = None  # 懒加载，避免没启用时也加载

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def build(self, skills: list[Skill]) -> None:
        """对全部 skill 构建索引；命中缓存的不重 embed。"""
        cache = self._load_cache()
        kept: dict[str, _Vec] = {}
        to_embed: list[Skill] = []

        for s in skills:
            h = _content_hash(s)
            cached = cache.get(s.name)
            if cached and cached["hash"] == h and cached.get("model") == self._model_name:
                kept[s.name] = _Vec(
                    name=s.name,
                    hash=h,
                    vector=np.asarray(cached["vector"], dtype=np.float32),
                    severity=s.severity,
                )
            else:
                to_embed.append(s)

        if to_embed:
            try:
                new_vecs = self._embed_texts([_skill_text(s) for s in to_embed])
            except Exception as exc:
                logger.warning("embedding 计算失败，语义匹配本次禁用：%s", exc)
                self._vectors = list(kept.values())
                self._rebuild_matrix()
                return

            for s, v in zip(to_embed, new_vecs):
                vec = _normalize(np.asarray(v, dtype=np.float32))
                kept[s.name] = _Vec(name=s.name, hash=_content_hash(s), vector=vec, severity=s.severity)

        self._vectors = [kept[s.name] for s in skills if s.name in kept]
        self._rebuild_matrix()
        self._save_cache()
        logger.info(
            "SemanticIndex 构建完成：共 %d 条，其中新 embed %d 条",
            len(self._vectors), len(to_embed),
        )

    def rebuild(self, skills: list[Skill]) -> None:
        """强制忽略缓存重建（CLI ``skills index rebuild`` 用）。"""
        if self._cache_path.exists():
            try:
                self._cache_path.unlink()
            except OSError as exc:
                logger.warning("删除缓存失败：%s", exc)
        self.build(skills)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def search(
        self,
        file_path: str,
        language: str,
        code: str,
        top_k: int,
        min_score: float,
    ) -> list[tuple[str, float]]:
        """返回 [(skill_name, similarity)]，按相似度 desc。"""
        if self._matrix is None or len(self._vectors) == 0:
            return []
        try:
            q = self._embed_texts([_query_text(file_path, language, code)])[0]
        except Exception as exc:
            logger.warning("query embedding 失败，跳过语义匹配：%s", exc)
            return []
        qv = _normalize(np.asarray(q, dtype=np.float32))
        scores = self._matrix @ qv  # 已 L2-normalized，点积即余弦
        order = np.argsort(-scores)
        out: list[tuple[str, float]] = []
        for idx in order[:top_k]:
            score = float(scores[idx])
            if score < min_score:
                break
            out.append((self._vectors[idx].name, score))
        return out

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _embeddings_client(self):
        if self._embeddings is None:
            from langchain_openai import OpenAIEmbeddings

            base, key = self.settings.resolved_embedding()
            self._embeddings = OpenAIEmbeddings(
                model=self._model_name,
                api_key=key.get_secret_value(),
                base_url=base,
                check_embedding_ctx_length=False,  # DashScope 等不一定声明 ctx
            )
        return self._embeddings

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._embeddings_client().embed_documents(texts)

    def _rebuild_matrix(self) -> None:
        if not self._vectors:
            self._matrix = None
            return
        self._matrix = np.vstack([v.vector for v in self._vectors])

    def _load_cache(self) -> dict[str, dict]:
        if not self._cache_path.exists():
            return {}
        try:
            return json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("读取语义索引缓存失败，将重建：%s", exc)
            return {}

    def _save_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                v.name: {
                    "hash": v.hash,
                    "model": self._model_name,
                    "vector": v.vector.tolist(),
                }
                for v in self._vectors
            }
            self._cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            logger.warning("保存语义索引缓存失败：%s", exc)

    def __len__(self) -> int:
        return len(self._vectors)


def _normalize(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    if norm == 0.0:
        return v
    return v / norm
