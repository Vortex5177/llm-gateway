"""GET /v1/models（OpenAI 协议面）与 GET /api/models（看板模型目录）。"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Request

from app.config import GatewayConfig, ProviderConfig, provider_kind
from app.routes.health import check_provider

router = APIRouter(tags=["models"])


@router.get("/v1/models")
async def list_models(request: Request) -> dict[str, Any]:
    registry = request.app.state.registry
    return {"object": "list", "data": registry.model_list()}


def _key_info(provider: ProviderConfig) -> dict[str, Any]:
    """密钥来源描述；永不返回密钥值本身。"""
    if provider.api_key:
        return {"source": "literal"}
    if provider.api_key_env:
        return {
            "source": "env",
            "name": provider.api_key_env,
            "configured": bool(os.environ.get(provider.api_key_env)),
        }
    return {"source": "none"}


def _model_entries(config: GatewayConfig) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name, ref in config.models.items():
        fallbacks = [
            {"tag": key.split("@", 1)[1], "chain": chain}
            if "@" in key
            else {"tag": None, "chain": chain}
            for key, chain in config.fallbacks.items()
            if key == name or key.startswith(name + "@")
        ]
        fallbacks.sort(key=lambda item: (item["tag"] is not None, item["tag"] or ""))
        entries.append(
            {
                "id": name,
                "kind": provider_kind(config.providers[ref.provider]),
                "provider": ref.provider,
                "upstream": ref.upstream,
                "aliases": sorted(
                    alias
                    for alias, target in config.aliases.items()
                    if target == name
                ),
                "fallbacks": fallbacks,
            }
        )
    return entries


@router.get("/api/models")
async def model_catalog(request: Request) -> dict[str, Any]:
    """看板数据：模型目录（名称/本地或云/别名/回退链）+ provider 接入状态。"""
    config: GatewayConfig = request.app.state.config
    transport = getattr(request.app.state, "http_transport", None)

    names = list(config.providers)
    checks = await asyncio.gather(
        *(check_provider(config.providers[name], transport) for name in names)
    )
    providers = []
    for name, check in zip(names, checks):
        provider = config.providers[name]
        providers.append(
            {
                "name": name,
                "kind": provider_kind(provider),
                "base_url": provider.base_url,
                "key": _key_info(provider),
                "reachable": check["reachable"],
                "latency_ms": check["latency_ms"],
                "detail": check["detail"],
                "models": [
                    model
                    for model, ref in config.models.items()
                    if ref.provider == name
                ],
            }
        )
    return {
        "models": _model_entries(config),
        "providers": providers,
        "aliases": config.aliases,
    }
