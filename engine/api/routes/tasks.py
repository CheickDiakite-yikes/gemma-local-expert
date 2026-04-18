from __future__ import annotations

from fastapi import APIRouter, Depends

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import Task

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])


@router.get("", response_model=list[Task])
async def list_tasks(container: ServiceContainer = Depends(get_container)) -> list[Task]:
    return container.store.list_tasks()
