"""GET /health：存活 + 各 provider 可达性。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request

from app.config import ProviderConfig, resolve_api_key

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_SECONDS = 3.0


async def _check_provider(name: str, provider: ProviderConfig) -> dict[str, Any]:
    key = resolve_api_key(provider)
    if provider.api_key_env and key is None:
        return {
            "reachable": False,
            "latency_ms": None,
            "detail": f"密钥未配置（环境变量 {provider.api_key_env} 缺失）",
        }
    url = provider.base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return {"reachable": False, "latency_ms": None, "detail": f"不可达: {exc}"}
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    if resp.status_code < 400:
        return {
            "reachable": True,
            "latency_ms": latency_ms,
            "detail": f"HTTP {resp.status_code}",
        }
    detail = f"HTTP {resp.status_code}"
    if resp.status_code in (401, 403):
        detail += "（认证失败）"
    return {"reachable": False, "latency_ms": latency_ms, "detail": detail}


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    config = request.app.state.config
    names = list(config.providers)
    checks = await asyncio.gather(
        *(_check_provider(name, config.providers[name]) for name in names)
    )
    return {"status": "ok", "providers": dict(zip(names, checks))}