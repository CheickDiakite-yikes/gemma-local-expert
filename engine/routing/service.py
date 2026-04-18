from __future__ import annotations

from dataclasses import dataclass, field

from engine.contracts.api import AssetCareContext, AssetKind, AssetSummary, AssistantMode, ConversationTurnRequest
from engine.tools.registry import ToolRegistry


@dataclass(slots=True)
class RouteDecision:
    needs_retrieval: bool = False
    specialist_model: str | None = None
    proposed_tool: str | None = None
    agent_run: bool = False
    reasons: list[str] = field(default_factory=list)


class RouterService:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    def decide(
        self,
        turn: ConversationTurnRequest,
        assets: list[AssetSummary] | None = None,
    ) -> RouteDecision:
        lowered = turn.text.lower()
        decision = RouteDecision()
        image_assets = [asset for asset in assets or [] if asset.kind == AssetKind.IMAGE]
        video_assets = [asset for asset in assets or [] if asset.kind == AssetKind.VIDEO]
        medical_image_assets = [
            asset for asset in image_assets if asset.care_context == AssetCareContext.MEDICAL
        ]
        has_visual_context = bool(image_assets)
        has_video_context = bool(video_assets)
        agentic_workspace_request = (
            not has_visual_context
            and not has_video_context
            and any(
                phrase in lowered
                for phrase in {
                    "search this workspace",
                    "search the workspace",
                    "search this project",
                    "search the project",
                    "search this repo",
                    "search the repo",
                    "find files about",
                    "find files in",
                    "look through the workspace",
                    "review the workspace",
                    "scan the workspace",
                    "summarize documents in",
                    "summarize documents from",
                    "summarise documents in",
                    "prepare a brief from",
                    "prepare a briefing from",
                    "from the workspace",
                    "from this workspace",
                    "from the project",
                    "in this folder",
                    "in the workspace",
                }
            )
        )
        if agentic_workspace_request:
            decision.agent_run = True
            decision.reasons.append("Turn matches the workspace-scoped agent path.")

        if medical_image_assets:
            decision.specialist_model = "medgemma"
            decision.reasons.append("Attached image is marked for medical analysis.")
        elif turn.mode == AssistantMode.MEDICAL:
            decision.specialist_model = "medgemma"
            decision.reasons.append("Explicit medical mode is active.")

        if decision.specialist_model != "medgemma" and (
            any(word in lowered for word in {"translate", "translation"}) or (
                image_assets and "what does this say" in lowered
            )
        ):
            decision.specialist_model = "translategemma"
            decision.reasons.append("Turn looks like a translation workflow.")

        if decision.specialist_model not in {"medgemma", "translategemma"} and has_visual_context:
            if any(
                word in lowered
                for word in {
                    "extract",
                    "form",
                    "ocr",
                    "label",
                    "photo",
                    "image",
                    "picture",
                    "screenshot",
                    "describe",
                    "inspect",
                    "analyze",
                    "review",
                    "summarize",
                    "heatmap",
                    "overlay",
                    "segment",
                    "segmented",
                    "layer",
                    "visible",
                    "shown",
                    "looks",
                }
            ):
                decision.reasons.append("Turn likely needs structured visual extraction.")
            else:
                decision.reasons.append("Using the most recent image context for a follow-up turn.")
            decision.specialist_model = "paligemma"

        if decision.specialist_model not in {"medgemma", "translategemma"} and has_video_context:
            if any(
                word in lowered
                for word in {
                    "video",
                    "clip",
                    "camera",
                    "track",
                    "detect",
                    "monitor",
                    "movement",
                    "unsafe",
                    "illegal",
                    "tool",
                    "tools",
                    "process",
                    "machine",
                    "vehicle",
                    "site",
                    "mining",
                    "analyze",
                    "review",
                    "inspect",
                }
            ):
                decision.reasons.append("Turn likely needs local video detection or tracking.")
            else:
                decision.reasons.append("Using the most recent video context for a follow-up turn.")
            decision.specialist_model = "sam3"

        explicit_retrieval = any(
            token in lowered
            for token in {
                "find",
                "search",
                "source",
                "sources",
                "document",
                "documents",
                "library",
                "knowledge",
                "reference",
                "references",
                "guidance",
                "brief",
                "compare",
                "checklist",
                "summarize",
            }
        )
        image_safe_retrieval = any(
            token in lowered
            for token in {"source", "sources", "document", "documents", "library", "reference"}
        )

        if not decision.agent_run and (
            turn.enabled_knowledge_pack_ids or (
            explicit_retrieval and (not has_visual_context and not has_video_context or image_safe_retrieval)
            )
        ):
            decision.needs_retrieval = True
            decision.reasons.append("Turn benefits from local retrieval before synthesis.")

        decision.proposed_tool = self.tools.propose(turn.text)
        if decision.proposed_tool == "generate_heatmap_overlay" and not has_visual_context:
            decision.proposed_tool = None
        if decision.proposed_tool:
            decision.reasons.append(f"Detected tool intent for `{decision.proposed_tool}`.")

        return decision
