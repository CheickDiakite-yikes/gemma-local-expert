from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import (
    AssetAnalysisStatus,
    AssetCareContext,
    AssetKind,
    AssetSummary,
    AssetUploadResponse,
    new_id,
)

router = APIRouter(prefix="/v1/assets", tags=["assets"])


@router.post("/upload", response_model=AssetUploadResponse)
async def upload_asset(
    file: UploadFile = File(...),
    care_context: AssetCareContext = Form(default=AssetCareContext.GENERAL),
    description: str | None = Form(default=None),
    container: ServiceContainer = Depends(get_container),
) -> AssetUploadResponse:
    display_name = file.filename or "attachment"
    suffix = Path(display_name).suffix or _suffix_for_media_type(file.content_type)
    asset_id = new_id("asset")
    storage_dir = Path(container.settings.asset_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"{asset_id}{suffix}"

    content = await file.read()
    stored_path.write_bytes(content)

    media_type = file.content_type or _guess_media_type(display_name)
    kind = _guess_asset_kind(media_type, display_name)
    asset = container.store.create_asset_record(
        asset_id=asset_id,
        source_path=display_name,
        display_name=display_name,
        description=description,
        media_type=media_type,
        kind=kind,
        byte_size=len(content),
        local_path=str(stored_path),
        care_context=care_context,
        analysis_status=AssetAnalysisStatus.METADATA_ONLY,
        analysis_summary=_analysis_summary(
            display_name=display_name,
            media_type=media_type,
            byte_size=len(content),
            kind=kind,
            care_context=care_context,
        ),
    )
    container.audit.record(
        "asset.uploaded",
        asset_id=asset.id,
        care_context=asset.care_context.value,
        kind=asset.kind.value,
    )
    return AssetUploadResponse(asset=asset)


@router.get("/{asset_id}", response_model=AssetSummary)
async def get_asset(
    asset_id: str,
    container: ServiceContainer = Depends(get_container),
) -> AssetSummary:
    asset = container.store.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return asset


@router.get("/{asset_id}/content")
async def get_asset_content(
    asset_id: str,
    container: ServiceContainer = Depends(get_container),
) -> FileResponse:
    asset = container.store.get_asset(asset_id)
    if asset is None or not asset.content_url:
        raise HTTPException(status_code=404, detail="Asset content is unavailable.")

    local_path = container.store.get_asset_local_path(asset_id)
    if local_path is None:
        raise HTTPException(status_code=404, detail="Asset content is unavailable.")
    file_path = Path(local_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Asset file is missing on disk.")

    return FileResponse(
        file_path,
        media_type=asset.media_type,
        filename=asset.display_name,
    )


def _guess_media_type(source_name: str) -> str | None:
    suffix = Path(source_name).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".mp4":
        return "video/mp4"
    if suffix == ".mov":
        return "video/quicktime"
    if suffix == ".webm":
        return "video/webm"
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".txt":
        return "text/plain"
    return None


def _suffix_for_media_type(media_type: str | None) -> str:
    if media_type == "image/png":
        return ".png"
    if media_type == "image/jpeg":
        return ".jpg"
    if media_type == "image/webp":
        return ".webp"
    if media_type == "image/gif":
        return ".gif"
    if media_type == "video/mp4":
        return ".mp4"
    if media_type == "video/quicktime":
        return ".mov"
    if media_type == "video/webm":
        return ".webm"
    if media_type == "application/pdf":
        return ".pdf"
    return ""


def _guess_asset_kind(media_type: str | None, display_name: str) -> AssetKind:
    if media_type:
        if media_type.startswith("image/"):
            return AssetKind.IMAGE
        if media_type.startswith("video/"):
            return AssetKind.VIDEO
        if media_type.startswith("audio/"):
            return AssetKind.AUDIO
        if media_type.startswith("text/") or media_type == "application/pdf":
            return AssetKind.DOCUMENT
    suffix = Path(display_name).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return AssetKind.IMAGE
    if suffix in {".mp4", ".mov", ".webm"}:
        return AssetKind.VIDEO
    if suffix in {".pdf", ".txt", ".md"}:
        return AssetKind.DOCUMENT
    return AssetKind.OTHER


def _analysis_summary(
    *,
    display_name: str,
    media_type: str | None,
    byte_size: int,
    kind: AssetKind,
    care_context: AssetCareContext,
) -> str:
    size_kb = max(byte_size / 1024, 0.1)
    if kind == AssetKind.IMAGE and care_context == AssetCareContext.MEDICAL:
        return (
            f"Attached medical image {display_name} ({media_type or 'image'}, {size_kb:.1f} KB). "
            "Stored locally; dedicated MedGemma analysis has not run yet."
        )
    if kind == AssetKind.IMAGE:
        return (
            f"Attached image {display_name} ({media_type or 'image'}, {size_kb:.1f} KB). "
            "Stored locally; dedicated vision analysis has not run yet."
        )
    if kind == AssetKind.VIDEO:
        return (
            f"Attached video {display_name} ({media_type or 'video'}, {size_kb:.1f} KB). "
            "Stored locally; local sampling or tracking analysis has not run yet."
        )
    return f"Attached file {display_name} ({media_type or kind.value}, {size_kb:.1f} KB)."
