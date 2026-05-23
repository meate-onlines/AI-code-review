"""FastAPI 应用工厂。

直接启动：
    uvicorn app.webhook.app:create_app --factory --host 0.0.0.0 --port 8000

或者通过 CLI：
    python -m app.cli serve

路由：
- POST /gitlab/webhook   接收 GitLab Merge Request Hook
- GET  /healthz          活性探针
- GET  /ready            就绪探针（校验 GitLab 可连通）
- GET  /usage            返回累计 token / skill 命中统计 JSON
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.adapters import verify_webhook_token
from app.settings import Settings, get_settings
from app.webhook.handlers import WebhookHandler
from app.webhook.models import GitLabMRPayload

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """FastAPI app 工厂，便于在测试中注入伪 Settings。"""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="AI Code Review Webhook",
        version="0.2.0",
        docs_url="/docs",
        redoc_url=None,
    )

    handler = WebhookHandler(settings)

    @app.on_event("startup")
    async def _startup() -> None:
        try:
            await handler.warmup()
        except Exception:
            logger.exception("启动预热失败，服务仍会启动但 /ready 将返回 503")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        try:
            handler.reviewer.gitlab.list_mrs_updated_today()
            return JSONResponse({"status": "ready"}, status_code=200)
        except Exception as exc:
            return JSONResponse({"status": "degraded", "error": str(exc)}, status_code=503)

    @app.get("/usage")
    async def usage() -> dict:
        s = handler.reviewer.collector.summary
        return {
            "total_calls": s.total_calls,
            "errors": s.errors,
            "prompt_tokens": s.total_prompt_tokens,
            "completion_tokens": s.total_completion_tokens,
            "total_tokens": s.total_tokens,
            "skill_hits": dict(s.skill_hits),
            "skill_issue_counts": dict(s.skill_issue_counts),
            "dedupe_size": len(handler.dedupe),
        }

    @app.post(settings.webhook.path)
    async def gitlab_webhook(
        request: Request,
        x_gitlab_token: str | None = Header(default=None, alias="X-Gitlab-Token"),
        x_gitlab_event: str | None = Header(default=None, alias="X-Gitlab-Event"),
    ) -> dict:
        expected = (
            settings.webhook.secret.get_secret_value() if settings.webhook.secret else None
        )
        if not verify_webhook_token(expected, x_gitlab_token):
            logger.warning("Webhook token 校验失败 event=%s", x_gitlab_event)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")

        # GitLab 用 X-Gitlab-Event: Merge Request Hook 区分事件类型
        if x_gitlab_event and "Merge Request" not in x_gitlab_event:
            return {"status": "ignored", "reason": f"event={x_gitlab_event}"}

        try:
            raw = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid json: {exc}")

        try:
            payload = GitLabMRPayload.model_validate(raw)
        except Exception as exc:
            logger.warning("payload 校验失败：%s", exc)
            raise HTTPException(status_code=400, detail="invalid payload")

        result = await handler.handle_mr_event(payload)
        return {"status": result, "mr_iid": payload.object_attributes.iid}

    return app
