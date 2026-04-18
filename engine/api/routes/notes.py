from __future__ import annotations

from fastapi import APIRouter, Depends

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import Note

router = APIRouter(prefix="/v1/notes", tags=["notes"])


@router.get("", response_model=list[Note])
async def list_notes(container: ServiceContainer = Depends(get_container)) -> list[Note]:
    return container.store.list_notes()
