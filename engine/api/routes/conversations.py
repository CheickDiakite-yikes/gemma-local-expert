from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import (
    Conversation,
    ConversationCreateRequest,
    ConversationSummary,
    ConversationTurnRequest,
    TranscriptMessage,
)

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


@router.post("", response_model=Conversation)
async def create_conversation(
    request: ConversationCreateRequest,
    container: ServiceContainer = Depends(get_container),
) -> Conversation:
    return container.store.create_conversation(request)


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    container: ServiceContainer = Depends(get_container),
) -> list[ConversationSummary]:
    return container.store.list_conversations(limit=limit)


@router.get("/{conversation_id}/messages", response_model=list[TranscriptMessage])
async def list_conversation_messages(
    conversation_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    container: ServiceContainer = Depends(get_container),
) -> list[TranscriptMessage]:
    if container.store.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return container.store.list_transcript(conversation_id, limit=limit)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    container: ServiceContainer = Depends(get_container),
) -> Response:
    deleted = container.store.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return Response(status_code=204)


@router.post("/{conversation_id}/turns")
async def submit_turn(
    conversation_id: str,
    request: ConversationTurnRequest,
    container: ServiceContainer = Depends(get_container),
) -> StreamingResponse:
    if request.conversation_id != conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id does not match path.")

    async def event_stream():
        async for event in container.orchestrator.stream_turn(request):
            yield event.model_dump_json() + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
