from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import SystemCapabilities, ToolDescriptor
from engine.models.document import document_extraction_available
from engine.models.sources import resolve_local_model_source
from engine.models.video import detect_tracking_runtime_status

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


@router.get("/v1/system/capabilities", response_model=SystemCapabilities)
async def capabilities(
    container: ServiceContainer = Depends(get_container),
) -> SystemCapabilities:
    settings = container.settings
    low_memory_profile = (
        settings.default_assistant_model == "gemma-4-e2b-it-4bit"
        and settings.specialist_backend == "ocr"
        and settings.embedding_backend == "hash"
    )
    tracking_status = detect_tracking_runtime_status(
        tracking_backend=settings.tracking_backend,
        tracking_model_source=settings.tracking_model_source,
        tracking_model_name=settings.default_tracking_model,
    )
    return SystemCapabilities(
        assistant_backend=settings.assistant_backend,
        assistant_model=settings.default_assistant_model,
        embedding_backend=settings.embedding_backend,
        embedding_model=settings.default_embedding_model,
        specialist_backend=settings.specialist_backend,
        vision_model=settings.default_vision_model,
        tracking_backend=settings.tracking_backend,
        tracking_model=settings.default_tracking_model,
        medical_model=settings.default_medical_model,
        workspace_root=settings.workspace_root,
        tesseract_available=shutil.which("tesseract") is not None,
        ffmpeg_available=shutil.which("ffmpeg") is not None,
        assistant_model_available=(
            resolve_local_model_source(
                settings.assistant_model_source, settings.default_assistant_model
            )
            is not None
        ),
        embedding_model_available=(
            resolve_local_model_source(
                settings.embedding_model_source, settings.default_embedding_model
            )
            is not None
        ),
        vision_model_available=(
            resolve_local_model_source(
                settings.vision_model_source, settings.default_vision_model
            )
            is not None
        ),
        tracking_model_available=tracking_status.tracking_model_available,
        medical_model_available=(
            resolve_local_model_source(
                settings.medical_model_source, settings.default_medical_model
            )
            is not None
        ),
        low_memory_profile=low_memory_profile,
        active_profile="low_memory" if low_memory_profile else "full_local",
        document_extraction_available=document_extraction_available(),
        video_analysis_fallback_only=tracking_status.video_analysis_fallback_only,
        tracking_execution_available=tracking_status.tracking_execution_available,
        isolation_execution_available=tracking_status.isolation_execution_available,
    )


@router.get("/v1/system/tools", response_model=list[ToolDescriptor])
async def list_tools(container: ServiceContainer = Depends(get_container)) -> list[ToolDescriptor]:
    return container.tools.list_tools()
