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
    existing = container.store.get_approval(approval_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Approval not found.")

    effective_payload = existing.payload
    if request.action.value == "approve":
        effective_payload = container.tool_runtime.merge_edited_payload(
            existing.tool_name,
            existing.payload,
            request.edited_payload,
        )
    approval = container.store.resolve_approval(
        approval_id,
        request,
        payload=effective_payload,
    )
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
            if approval.run_id:
                artifact_ids = [
                    asset_id
                    for asset_id in result.get("asset_ids", [])
                    if isinstance(asset_id, str)
                ]
                summary = (
                    f"Created {result['entity_type']}: {result['title']}"
                    if result.get("entity_type") and result.get("title")
                    else result.get("message")
                    or f"Executed `{approval.tool_name}` after approval."
                )
                container.store.update_agent_run(
                    approval.run_id,
                    status="completed",
                    artifact_ids=artifact_ids,
                    result_summary=str(summary),
                    approval_id=approval.id,
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
            if approval.run_id:
                container.store.update_agent_run(
                    approval.run_id,
                    status="failed",
                    result_summary=f"`{approval.tool_name}` failed after approval: {exc}",
                    approval_id=approval.id,
                )
    elif approval.run_id:
        container.store.update_agent_run(
            approval.run_id,
            status="blocked",
            result_summary=f"The workspace run stopped because `{approval.tool_name}` was {approval.status}.",
            approval_id=approval.id,
        )
    container.audit.record(
        "approval.resolved",
        approval_id=approval_id,
        status=approval.status,
    )
    return approval
