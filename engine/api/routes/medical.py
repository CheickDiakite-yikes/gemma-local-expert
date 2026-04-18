from __future__ import annotations

from fastapi import APIRouter, Depends

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import MedicalSession

router = APIRouter(prefix="/v1/medical", tags=["medical"])


@router.post("/sessions", response_model=MedicalSession)
async def create_medical_session(
    conversation_id: str,
    container: ServiceContainer = Depends(get_container),
) -> MedicalSession:
    session = container.store.create_medical_session(conversation_id)
    container.audit.record(
        "medical.session.opened",
        medical_session_id=session.id,
        conversation_id=conversation_id,
    )
    return session
