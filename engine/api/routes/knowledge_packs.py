from __future__ import annotations

from fastapi import APIRouter, Depends

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import KnowledgePackImportRequest, KnowledgePackImportResult

router = APIRouter(prefix="/v1/knowledge-packs", tags=["knowledge-packs"])


@router.post("/import", response_model=KnowledgePackImportResult)
async def import_knowledge_pack(
    request: KnowledgePackImportRequest,
    container: ServiceContainer = Depends(get_container),
) -> KnowledgePackImportResult:
    result = container.store.import_knowledge_pack(request)
    container.audit.record(
        "knowledge-pack.imported",
        knowledge_pack_id=result.knowledge_pack_id,
        document_count=result.imported_document_count,
    )
    return result
