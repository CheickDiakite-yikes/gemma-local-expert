from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from engine.api.dependencies import ServiceContainer, get_container
from engine.contracts.api import ApprovalDecision, ApprovalState

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


@router.post("/{approval_id}/decisions", response_model=ApprovalState)
async def decide_approval(
    approval_id: str,
    request: ApprovalDecision,
    container: ServiceContainer = Depends(get_container),
) -> ApprovalState:
    if container.store.get_approval(approval_id) is None:
        raise HTTPException(status_code=404, detail="Approval not found.")
    approval = container.store.resolve_approval(approval_id, request)
    if request.action.value == "approve":
        try:
            result = container.tool_runtime.execute(approval.tool_name, approval.payload)
            approval = container.store.finalize_approval(
                approval_id,
                status="executed",
                result=result,
            )
            container.audit.record(
                "tool.executed",
                approval_id=approval_id,
                tool_name=approval.tool_name,
                result=result,
            )
        except Exception as exc:
            approval = container.store.finalize_approval(
                approval_id,
                status="failed",
                result={"error": str(exc)},
            )
            container.audit.record(
                "tool.failed",
                approval_id=approval_id,
                tool_name=approval.tool_name,
                error=str(exc),
            )
    container.audit.record(
        "approval.resolved",
        approval_id=approval_id,
        status=approval.status,
    )
    return approval
