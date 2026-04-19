from __future__ import annotations

from dataclasses import dataclass, field

from engine.contracts.api import (
    AssetCareContext,
    AssetKind,
    AssetSummary,
    AssistantMode,
    ConversationMessage,
    ConversationTurnRequest,
)
from engine.tools.registry import ToolRegistry


@dataclass(slots=True)
class RouteDecision:
    needs_retrieval: bool = False
    specialist_model: str | None = None
    proposed_tool: str | None = None
    agent_run: bool = False
    interaction_kind: str = "general"
    is_follow_up: bool = False
    reasons: list[str] = field(default_factory=list)


class RouterService:
    _WORKSPACE_AGENT_PHRASES = {
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
    _VISUAL_HINTS = {
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
        "analyse",
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
    _VIDEO_HINTS = {
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
        "analyse",
        "review",
        "inspect",
    }
    _SOURCE_SEEKING_TOKENS = {
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
        "summarise",
    }
    _LOCAL_KNOWLEDGE_TOPICS = {
        "ors",
        "oral rehydration",
        "trip checklist",
        "checklist",
        "field prep",
        "field",
        "village",
        "translator",
        "route",
        "debrief",
        "kenya",
        "guidance",
        "visit",
        "briefing",
    }
    _TEACHING_PHRASES = {
        "teach me",
        "walk me through",
        "show me how",
        "how do i",
        "how to",
        "help me understand",
        "explain how",
    }
    _CASUAL_CONVERSATION_PHRASES = {
        "hi",
        "hello",
        "hey",
        "how are you",
        "what's up",
        "whats up",
        "thank you",
        "thanks",
        "can we just talk",
        "talk normally",
        "tell me about yourself",
        "who are you",
    }
    _TOPIC_RESET_PHRASES = {
        "switch topics",
        "switch gears",
        "chat normally again",
        "talk normally again",
        "just chat normally again",
        "just talk normally again",
        "just chat for a second",
        "just talk for a second",
    }
    _FOLLOW_UP_PREFIXES = (
        "and ",
        "also ",
        "what about",
        "how about",
        "what do you mean",
        "why",
        "which one",
        "what should",
        "what else",
        "can you expand",
        "tell me more",
        "go deeper",
    )

    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    def decide(
        self,
        turn: ConversationTurnRequest,
        assets: list[AssetSummary] | None = None,
        history: list[ConversationMessage] | None = None,
    ) -> RouteDecision:
        lowered = turn.text.lower().strip()
        decision = RouteDecision()
        image_assets = [asset for asset in assets or [] if asset.kind == AssetKind.IMAGE]
        video_assets = [asset for asset in assets or [] if asset.kind == AssetKind.VIDEO]
        medical_image_assets = [
            asset for asset in image_assets if asset.care_context == AssetCareContext.MEDICAL
        ]
        has_visual_context = bool(image_assets)
        has_video_context = bool(video_assets)
        history = history or []
        explicit_workspace_request = any(
            phrase in lowered for phrase in self._WORKSPACE_AGENT_PHRASES
        )
        explicit_topic_reset = self._looks_like_topic_reset(lowered)

        if (explicit_workspace_request or explicit_topic_reset) and (
            has_visual_context or has_video_context
        ):
            image_assets = []
            video_assets = []
            medical_image_assets = []
            has_visual_context = False
            has_video_context = False
            decision.reasons.append(
                "Explicit user intent overrides the most recent media context."
            )

        decision.is_follow_up = self._looks_like_follow_up(
            lowered,
            history=history,
            has_visual_context=has_visual_context,
            has_video_context=has_video_context,
            explicit_topic_reset=explicit_topic_reset or explicit_workspace_request,
        )
        if decision.is_follow_up:
            decision.reasons.append("Turn looks like a follow-up to recent conversation context.")

        if self._looks_like_teaching_request(lowered):
            decision.interaction_kind = "teaching"
            decision.reasons.append("Turn looks like a teaching or explanation request.")
        elif self._looks_like_general_conversation(
            lowered,
            mode=turn.mode,
            has_visual_context=has_visual_context,
            has_video_context=has_video_context,
        ):
            decision.interaction_kind = "conversation"
            decision.reasons.append("Turn looks like ordinary conversation.")

        agentic_workspace_request = explicit_workspace_request
        if agentic_workspace_request:
            decision.agent_run = True
            decision.interaction_kind = "agent"
            decision.reasons.append("Turn matches the workspace-scoped agent path.")

        if medical_image_assets:
            decision.specialist_model = "medgemma"
            decision.interaction_kind = "medical_vision"
            decision.reasons.append("Attached image is marked for medical analysis.")
        elif turn.mode == AssistantMode.MEDICAL:
            decision.specialist_model = "medgemma"
            decision.interaction_kind = "medical_vision"
            decision.reasons.append("Explicit medical mode is active.")

        if decision.specialist_model != "medgemma" and (
            any(word in lowered for word in {"translate", "translation"})
            or (image_assets and "what does this say" in lowered)
        ):
            decision.specialist_model = "translategemma"
            decision.interaction_kind = "translation"
            decision.reasons.append("Turn looks like a translation workflow.")

        if decision.specialist_model not in {"medgemma", "translategemma"} and has_visual_context:
            if any(word in lowered for word in self._VISUAL_HINTS):
                decision.reasons.append("Turn likely needs structured visual extraction.")
            else:
                decision.reasons.append("Using the most recent image context for a follow-up turn.")
            decision.specialist_model = "paligemma"
            decision.interaction_kind = "vision"

        if decision.specialist_model not in {"medgemma", "translategemma"} and has_video_context:
            if any(word in lowered for word in self._VIDEO_HINTS):
                decision.reasons.append("Turn likely needs local video detection or tracking.")
            else:
                decision.reasons.append("Using the most recent video context for a follow-up turn.")
            decision.specialist_model = "sam3"
            decision.interaction_kind = "video"

        explicit_retrieval = any(token in lowered for token in self._SOURCE_SEEKING_TOKENS)
        image_safe_retrieval = any(
            token in lowered for token in {"source", "sources", "document", "documents", "library", "reference"}
        )
        knowledge_guided_teaching = (
            decision.interaction_kind == "teaching"
            and turn.mode in {AssistantMode.FIELD, AssistantMode.RESEARCH}
            and any(topic in lowered for topic in self._LOCAL_KNOWLEDGE_TOPICS)
        )

        if not decision.agent_run and (
            turn.enabled_knowledge_pack_ids
            or (
                not self._looks_like_general_conversation(
                    lowered,
                    mode=turn.mode,
                    has_visual_context=has_visual_context,
                    has_video_context=has_video_context,
                )
                and (
                    explicit_retrieval
                    and ((not has_visual_context and not has_video_context) or image_safe_retrieval)
                    or knowledge_guided_teaching
                )
            )
        ):
            decision.needs_retrieval = True
            decision.reasons.append("Turn benefits from local retrieval before synthesis.")

        decision.proposed_tool = self.tools.propose(turn.text)
        if decision.proposed_tool == "generate_heatmap_overlay" and not has_visual_context:
            decision.proposed_tool = None
        if decision.proposed_tool:
            decision.interaction_kind = "task"
            decision.reasons.append(f"Detected tool intent for `{decision.proposed_tool}`.")
            if decision.needs_retrieval and not any(
                token in lowered
                for token in {"source", "sources", "document", "documents", "reference", "references", "library"}
            ):
                decision.needs_retrieval = False
                decision.reasons = [
                    reason
                    for reason in decision.reasons
                    if reason != "Turn benefits from local retrieval before synthesis."
                ]

        return decision

    def _looks_like_teaching_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in self._TEACHING_PHRASES)

    def _looks_like_general_conversation(
        self,
        lowered: str,
        *,
        mode: AssistantMode,
        has_visual_context: bool,
        has_video_context: bool,
    ) -> bool:
        if has_visual_context or has_video_context:
            return False
        if any(phrase == lowered or phrase in lowered for phrase in self._CASUAL_CONVERSATION_PHRASES):
            return True
        if self._looks_like_topic_reset(lowered):
            return True
        if self._looks_like_teaching_request(lowered):
            return False
        if any(token in lowered for token in self._WORKSPACE_AGENT_PHRASES):
            return False
        if self.tools.propose(lowered):
            return False
        if any(token in lowered for token in self._SOURCE_SEEKING_TOKENS):
            return False
        if mode == AssistantMode.GENERAL and len(lowered.split()) <= 14:
            return True
        return False

    def _looks_like_follow_up(
        self,
        lowered: str,
        *,
        history: list[ConversationMessage],
        has_visual_context: bool,
        has_video_context: bool,
        explicit_topic_reset: bool,
    ) -> bool:
        if not history:
            return False
        if explicit_topic_reset:
            return False
        if has_visual_context or has_video_context:
            return True
        if lowered.startswith(self._FOLLOW_UP_PREFIXES):
            return True
        if len(lowered.split()) <= 10 and any(
            lowered.startswith(prefix)
            for prefix in {"it", "that", "those", "they", "and", "also", "why", "what", "how"}
        ):
            return True
        return False

    def _looks_like_topic_reset(self, lowered: str) -> bool:
        if any(phrase in lowered for phrase in self._TOPIC_RESET_PHRASES):
            return True
        return any(
            phrase in lowered
            for phrase in {
                "can we just talk normally again",
                "can we switch topics",
                "can we switch gears",
            }
        )
