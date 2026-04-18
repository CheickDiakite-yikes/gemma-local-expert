from __future__ import annotations

from fastapi import APIRouter, Depends

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import AssetIngestRequest, AssetIngestResult

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


@router.post("/assets", response_model=AssetIngestResult)
async def ingest_assets(
    request: AssetIngestRequest,
    container: ServiceContainer = Depends(get_container),
) -> AssetIngestResult:
    result = container.store.ingest_assets(request)
    container.audit.record("assets.ingested", asset_ids=result.asset_ids)
    return result
