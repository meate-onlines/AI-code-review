"""审查链工厂：把 LLM + Prompt + 结构化输出 + 重试 拼成 Runnable。

调用方只需要：
    chain = build_review_chain(settings)
    result = await chain.ainvoke({"file_path": ..., "language": ..., "code": ..., ...})
拿到的就是带类型的 ``ReviewResult``。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import Runnable, RunnableLambda
from langchain_openai import ChatOpenAI

from app.chains.prompts import build_review_prompt, render_diff_block
from app.chains.schemas import ReviewResult
from app.settings import Settings

logger = logging.getLogger(__name__)


def _build_llm(settings: Settings) -> ChatOpenAI:
    """构造 LLM 客户端。

    阿里 DashScope / DeepSeek / OpenAI 等 OpenAI 兼容协议端点直接通过 base_url 接入；
    更换厂商只需要改 config，不动代码。
    """
    ai = settings.ai
    return ChatOpenAI(
        model=ai.model,
        api_key=ai.api_key.get_secret_value(),
        base_url=ai.base_url,
        temperature=ai.temperature,
        max_tokens=ai.max_tokens,
        timeout=ai.timeout,
    )


def _normalize_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """把 diff 渲染成 prompt 友好的字符串块，并补全可选字段默认值。"""
    return {
        "file_path": inputs["file_path"],
        "language": inputs.get("language") or "text",
        "code": inputs.get("code") or "",
        "diff_block": render_diff_block(inputs.get("diff")),
        "standards_block": inputs.get("standards_block") or "（本次未匹配到适用的团队规范，按通用最佳实践审查）",
    }


def build_review_chain(settings: Settings) -> Runnable:
    """组装 LCEL 链：预处理 → prompt → LLM(结构化输出) → 重试封装。"""
    llm = _build_llm(settings)
    prompt = build_review_prompt(settings.ai.role_desc)

    structured_llm = llm.with_structured_output(ReviewResult, method="function_calling")

    chain: Runnable = (
        RunnableLambda(_normalize_inputs).with_config(run_name="normalize_inputs")
        | prompt
        | structured_llm
    )

    return chain.with_retry(
        stop_after_attempt=3,
        wait_exponential_jitter=True,
        retry_if_exception_type=(Exception,),
    )
