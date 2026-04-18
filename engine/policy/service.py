from __future__ import annotations

from dataclasses import dataclass, field

from engine.contracts.api import AssistantMode, ConversationTurnRequest
from engine.routing.service import RouteDecision
from engine.tools.registry import ToolRegistry


@dataclass(slots=True)
class PolicyDecision:
    blocked: bool = False
    approval_required: bool = False
    warnings: list[str] = field(default_factory=list)


class PolicyService:
    def __init__(self, tools: ToolRegistry, *, medical_mode_enabled: bool = True) -> None:
        self.tools = tools
        self.medical_mode_enabled = medical_mode_enabled

    def evaluate(self, turn: ConversationTurnRequest, route: RouteDecision) -> PolicyDecision:
        decision = PolicyDecision()

        if route.specialist_model == "medgemma":
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

        if route.proposed_tool and self.tools.requires_confirmation(route.proposed_tool):
            decision.approval_required = True

        if route.proposed_tool == "export_brief":
            decision.warnings.append("Exports should produce an audit record.")

        return decision
