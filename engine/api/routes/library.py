from __future__ import annotations

from fastapi import APIRouter, Depends

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import LibrarySearchRequest, LibrarySearchResult

router = APIRouter(prefix="/v1/library", tags=["library"])


@router.post("/search", response_model=LibrarySearchResult)
async def search_library(
    request: LibrarySearchRequest,
    container: ServiceContainer = Depends(get_container),
) -> LibrarySearchResult:
    return LibrarySearchResult(results=container.retrieval.search(request))
