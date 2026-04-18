from __future__ import annotations

from fastapi import APIRouter, Depends

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import TranslationRequest, TranslationResult

router = APIRouter(prefix="/v1", tags=["translation"])


@router.post("/translate", response_model=TranslationResult)
async def translate(
    request: TranslationRequest,
    container: ServiceContainer = Depends(get_container),
) -> TranslationResult:
    source = request.text or f"[asset:{request.asset_id}]"
    translated = (
        f"[{request.source_language}->{request.target_language}] "
        f"{source}"
    )
    container.audit.record(
        "translation.requested",
        source_language=request.source_language,
        target_language=request.target_language,
    )
    return TranslationResult(
        translated_text=translated,
        model=container.settings.default_translation_model,
    )
