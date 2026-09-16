"""GET /v1/models：模型与别名列表。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["models"])


@router.get("/v1/models")
async def list_models(request: Request) -> dict[str, Any]:
    registry = request.app.state.registry
    return {"object": "list", "data": registry.model_list()}