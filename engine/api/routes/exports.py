from __future__ import annotations

from fastapi import APIRouter, Depends

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import ExportRequest, ExportResult

router = APIRouter(prefix="/v1", tags=["exports"])


@router.post("/exports", response_model=ExportResult)
async def export_artifact(
    request: ExportRequest,
    container: ServiceContainer = Depends(get_container),
) -> ExportResult:
    result = container.store.create_export(request)
    container.audit.record(
        "export.queued",
        export_id=result.export_id,
        destination_path=result.destination_path,
    )
    return result
