from __future__ import annotations

from dataclasses import dataclass, field

from engine.contracts.api import (
    ApprovalCategory,
    AssistantMode,
    ConversationTurnRequest,
)
from engine.routing.service import RouteDecision
from engine.tools.registry import ToolRegistry


@dataclass(slots=True)
class PolicyDecision:
    blocked: bool = False
    approval_required: bool = False
    approval_category: ApprovalCategory | None = None
    approval_summary: str | None = None
    warnings: list[str] = field(default_factory=list)


class PolicyService:
    def __init__(self, tools: ToolRegistry, *, medical_mode_enabled: bool = True) -> None:
        self.tools = tools
        self.medical_mode_enabled = medical_mode_enabled

    def evaluate(self, turn: ConversationTurnRequest, route: RouteDecision) -> PolicyDecision:
        decision = PolicyDecision()

        if route.agent_run:
            decision.warnings.append(
                "Workspace agent actions are limited to the configured local workspace scope."
            )

        if route.specialist_model == "medgemma":
            decision.approval_category = ApprovalCategory.MEDICAL_SPECIALIST
            decision.approval_summary = "Explicit guarded medical specialist workflow is required."
            if not self.medical_mode_enabled:
                decision.blocked = True
                decision.warnings.append("Medical mode is disabled in this environment.")
                return decision
            if turn.mode != AssistantMode.MEDICAL or not turn.medical_session_id:
                decision.blocked = True
                decision.warnings.append(
                    "Medical specialist access requires an explicit medical session."
                )
                return decision
            decision.approval_required = True
            decision.warnings.append("Medical mode responses must remain assistive and auditable.")

        if route.proposed_tool:
            descriptor = self.tools.descriptor_for(route.proposed_tool)
            if descriptor and descriptor.requires_confirmation:
                decision.approval_required = True
                if decision.approval_category is None:
                    decision.approval_category = descriptor.approval_category
                if decision.approval_summary is None:
                    decision.approval_summary = descriptor.approval_summary

        if route.proposed_tool == "export_brief":
            decision.warnings.append("Exports should produce an audit record.")

        return decision
