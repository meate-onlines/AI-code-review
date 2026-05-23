"""集中式配置：pydantic-settings + YAML 双通道加载。

支持两种来源（优先级从高到低）：
1. 环境变量（前缀 ``REVIEW__``，嵌套用 ``__`` 分隔，便于 CI/容器场景覆盖）
2. ``config.yml`` 文件（保留旧版本的配置入口，团队日常维护更直观）

所有字段都有类型校验和合理默认值，配置缺失或类型不匹配在启动期即失败。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GitLabConfig(BaseModel):
    url: str
    token: SecretStr
    user: str | None = None
    timeout: int = 30


class AIConfig(BaseModel):
    base_url: str
    api_key: SecretStr
    model: str
    temperature: float = 0.2
    max_tokens: int | None = 2048
    timeout: int = 60
    role_desc: str = "你是一名资深的代码评审专家。"


class ReviewConfig(BaseModel):
    """审查行为相关参数。"""

    include_patterns: list[str] = Field(
        default_factory=lambda: [
            "**/*.java",
            "**/*.kt",
            "**/*.py",
            "**/*.go",
            "**/*.ts",
            "**/*.tsx",
            "**/*.js",
            "**/*.jsx",
            "**/*.xml",
        ]
    )
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            "**/generated/**",
            "**/*.min.js",
            "**/node_modules/**",
            "**/vendor/**",
            "**/dist/**",
            "**/build/**",
        ]
    )
    max_file_size_kb: int = 200
    concurrency: int = 4
    comment_min_severity: Literal["info", "warning", "critical"] = "warning"
    standards_token_budget: int = 4000
    # 当 AI 返回 skip=True 时是否完全跳过评论
    respect_skip_flag: bool = True


class EmbeddingConfig(BaseModel):
    """语义匹配兜底使用的 embedding 模型。

    默认走 OpenAI 兼容协议（DashScope `text-embedding-v3` 等），
    不启用时 SkillSelector 仅做硬匹配。
    """

    enabled: bool = False
    base_url: str | None = None  # 为空则复用 AIConfig.base_url
    api_key: SecretStr | None = None  # 为空则复用 AIConfig.api_key
    model: str = "text-embedding-v3"
    cache_path: Path = Path(".cache/skills_index.json")
    # 单次查询返回的最大语义补充条数（与硬匹配合并去重后再截断）
    top_k: int = 3
    # 余弦相似度阈值，低于此值的不补充
    min_score: float = 0.55


class SkillsConfig(BaseModel):
    """规范库（skills）配置。"""

    enabled: bool = True
    standards_dir: Path = Path("standards")
    # 必须命中规范才发评论；否则会兜底用通用 prompt
    require_match: bool = False
    # 当一个文件命中过多 skill 时的上限（按 severity 排序后截断）
    max_skills_per_file: int = 8
    # 语义匹配兜底；硬匹配命中数 < hard_match_floor 时启用补充
    semantic: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    hard_match_floor: int = 2


class WebhookConfig(BaseModel):
    """GitLab Webhook 服务配置。"""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    path: str = "/gitlab/webhook"
    # GitLab Webhook 的 secret token；必须与项目配置一致才放行
    secret: SecretStr | None = None
    # 同时审查的 MR 数上限（保护下游 GitLab/AI 接口）
    max_concurrent_reviews: int = 2
    # 同一 (project, mr, head_sha) 在 TTL 内只审查一次，避免 rebase 重复触发
    dedupe_ttl_seconds: int = 1800
    # 启动时是否预热 GitLab 连接（失败则 server 拒绝启动）
    warmup_on_start: bool = True
    # 是否在每次 MR 审查结束后把 usage 写到日志（非 CLI 环境无法用 rich）
    log_summary_per_mr: bool = True


class LangSmithConfig(BaseModel):
    """LangSmith 追踪配置；关闭时也可只用本地 UsageCollector。"""

    enabled: bool = False
    api_key: SecretStr | None = None
    endpoint: str = "https://api.smith.langchain.com"
    project: str = "ai-code-review"
    # 是否在每次 review 结束后打印本地 usage 汇总（与是否上报 LangSmith 解耦）
    local_summary: bool = True


class Settings(BaseSettings):
    """顶层配置对象。"""

    model_config = SettingsConfigDict(
        env_prefix="REVIEW__",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gitlab: GitLabConfig
    ai: AIConfig
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    langsmith: LangSmithConfig = Field(default_factory=LangSmithConfig)

    def resolved_embedding(self) -> tuple[str, SecretStr]:
        """返回 (base_url, api_key)，未配置 embedding 专用时回落到 AI 端点。"""
        emb = self.skills.semantic
        base = emb.base_url or self.ai.base_url
        key = emb.api_key or self.ai.api_key
        return base, key

    @classmethod
    def from_yaml(cls, path: str | Path = "config.yml") -> "Settings":
        """从 YAML 加载并合并环境变量覆盖。"""
        config_path = Path(path).resolve()
        if not config_path.is_file():
            raise FileNotFoundError(f"配置文件不存在：{config_path}")
        with config_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls(**raw)


@lru_cache(maxsize=1)
def get_settings(config_path: str | Path = "config.yml") -> Settings:
    """全局单例入口；首次调用时加载，后续复用。"""
    return Settings.from_yaml(config_path)
