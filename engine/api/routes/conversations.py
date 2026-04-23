from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import (
    Conversation,
    ConversationCompactRequest,
    ConversationCreateRequest,
    ConversationForkRequest,
    ConversationItem,
    ConversationRollbackRequest,
    ConversationState,
    ConversationSummary,
    ConversationSteerRequest,
    ConversationTurnRecord,
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
    include_archived: bool = Query(default=False),
    container: ServiceContainer = Depends(get_container),
    ) -> list[ConversationSummary]:
    return container.store.list_conversations(
        limit=limit,
        include_archived=include_archived,
    )


@router.get("/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    container: ServiceContainer = Depends(get_container),
) -> Conversation:
    conversation = container.store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


@router.get("/{conversation_id}/state", response_model=ConversationState)
async def get_conversation_state(
    conversation_id: str,
    message_limit: int = Query(default=200, ge=1, le=500),
    turn_limit: int = Query(default=100, ge=1, le=500),
    item_limit: int = Query(default=500, ge=1, le=2000),
    container: ServiceContainer = Depends(get_container),
) -> ConversationState:
    state = container.store.get_conversation_state(
        conversation_id,
        message_limit=message_limit,
        turn_limit=turn_limit,
        item_limit=item_limit,
    )
    if state is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return state


@router.get("/{conversation_id}/messages", response_model=list[TranscriptMessage])
async def list_conversation_messages(
    conversation_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    container: ServiceContainer = Depends(get_container),
) -> list[TranscriptMessage]:
    if container.store.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return container.store.list_transcript(conversation_id, limit=limit)


@router.get("/{conversation_id}/turns", response_model=list[ConversationTurnRecord])
async def list_conversation_turns(
    conversation_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    container: ServiceContainer = Depends(get_container),
) -> list[ConversationTurnRecord]:
    if container.store.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return container.store.list_turn_records(conversation_id, limit=limit)


@router.get("/{conversation_id}/items", response_model=list[ConversationItem])
async def list_conversation_items(
    conversation_id: str,
    turn_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    container: ServiceContainer = Depends(get_container),
) -> list[ConversationItem]:
    if container.store.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return container.store.list_items(conversation_id, turn_id=turn_id, limit=limit)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    container: ServiceContainer = Depends(get_container),
) -> Response:
    deleted = container.store.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return Response(status_code=204)


@router.post("/{conversation_id}/archive", response_model=Conversation)
async def archive_conversation(
    conversation_id: str,
    container: ServiceContainer = Depends(get_container),
) -> Conversation:
    archived = container.store.archive_conversation(conversation_id)
    if archived is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return archived


@router.post("/{conversation_id}/fork", response_model=Conversation)
async def fork_conversation(
    conversation_id: str,
    request: ConversationForkRequest,
    container: ServiceContainer = Depends(get_container),
) -> Conversation:
    try:
        forked = container.store.fork_conversation(conversation_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if forked is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return forked


@router.post("/{conversation_id}/rollback", response_model=Conversation)
async def rollback_conversation(
    conversation_id: str,
    request: ConversationRollbackRequest,
    container: ServiceContainer = Depends(get_container),
) -> Conversation:
    try:
        rolled_back = container.store.rollback_conversation(conversation_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if rolled_back is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return rolled_back


@router.post("/{conversation_id}/compact", response_model=ConversationItem)
async def compact_conversation(
    conversation_id: str,
    request: ConversationCompactRequest,
    container: ServiceContainer = Depends(get_container),
) -> ConversationItem:
    try:
        compaction = container.store.compact_conversation(conversation_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if compaction is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return compaction


@router.post("/{conversation_id}/steer", response_model=ConversationItem)
async def steer_conversation(
    conversation_id: str,
    request: ConversationSteerRequest,
    container: ServiceContainer = Depends(get_container),
) -> ConversationItem:
    try:
        steer_item = container.store.steer_conversation(conversation_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if steer_item is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return steer_item


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
