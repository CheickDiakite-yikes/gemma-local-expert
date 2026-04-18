from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import AgentRun

router = APIRouter(tags=["runs"])


@router.get(
    "/v1/conversations/{conversation_id}/runs",
    response_model=list[AgentRun],
)
async def list_conversation_runs(
    conversation_id: str,
    container: ServiceContainer = Depends(get_container),
) -> list[AgentRun]:
    if container.store.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return container.store.list_agent_runs(conversation_id)


@router.get("/v1/runs/{run_id}", response_model=AgentRun)
async def get_run(
    run_id: str,
    container: ServiceContainer = Depends(get_container),
) -> AgentRun:
    run = container.store.get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return run
