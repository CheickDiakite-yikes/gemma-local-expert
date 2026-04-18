from __future__ import annotations

from fastapi import APIRouter, Depends

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import ToolDescriptor

router = APIRouter(tags=["system"])


@router.get("/")
async def root() -> dict[str, str]:
    return {"name": "Field Assistant Engine", "status": "ok"}


@router.get("/v1/system/health")
async def health(container: ServiceContainer = Depends(get_container)) -> dict[str, str]:
    return {
        "status": "ok",
        "environment": container.settings.environment,
        "assistant_backend": container.settings.assistant_backend,
        "assistant_model": container.settings.default_assistant_model,
        "specialist_backend": container.settings.specialist_backend,
        "vision_model": container.settings.default_vision_model,
        "tracking_backend": container.settings.tracking_backend,
        "tracking_model": container.settings.default_tracking_model,
        "medical_model": container.settings.default_medical_model,
        "embedding_backend": container.settings.embedding_backend,
        "embedding_model": container.settings.default_embedding_model,
    }


@router.get("/v1/system/tools", response_model=list[ToolDescriptor])
async def list_tools(container: ServiceContainer = Depends(get_container)) -> list[ToolDescriptor]:
    return container.tools.list_tools()
