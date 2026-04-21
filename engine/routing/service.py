from __future__ import annotations

from dataclasses import dataclass, field
import re

from engine.context.service import ConversationContextSnapshot
from engine.contracts.api import (
    AssetCareContext,
    AssetKind,
    AssetSummary,
    AssistantMode,
    ConversationMessage,
    ConversationTurnRequest,
    SourceDomain,
)
from engine.tools.registry import ToolRegistry


@dataclass(slots=True)
class RouteDecision:
    needs_retrieval: bool = False
    specialist_model: str | None = None
    proposed_tool: str | None = None
    agent_run: bool = False
    source_domain: SourceDomain | None = None
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
    _WORKSPACE_SCOPE_TOKENS = {
        "workspace",
        "project",
        "repo",
        "repository",
        "folder",
    }
    _WORKSPACE_ACTION_TOKENS = {
        "search",
        "scan",
        "review",
        "read",
        "find",
        "brief",
        "briefing",
        "summary",
        "summarize",
        "summarise",
        "inspect",
        "architecture",
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
    _DOCUMENT_HINTS = {
        "document",
        "pdf",
        "page",
        "pages",
        "section",
        "sections",
        "extract",
        "summarize",
        "summarise",
        "quote",
        "text",
        "read",
        "review",
        "analyze",
        "analyse",
    }
    _MEDIA_REFERENCE_PHRASES = {
        "this image",
        "that image",
        "the image",
        "this picture",
        "that picture",
        "the picture",
        "this photo",
        "that photo",
        "the photo",
        "this screenshot",
        "that screenshot",
        "the screenshot",
        "this x-ray",
        "that x-ray",
        "the x-ray",
        "this video",
        "that video",
        "the video",
        "this clip",
        "that clip",
        "the clip",
        "from the image",
        "from the video",
        "in the image",
        "in the video",
        "what does this say",
        "what stands out",
        "what do you notice",
        "anything look off",
        "what is shown",
        "what's shown",
        "which shortages",
        "which tools",
        "which machine",
        "which machines",
        "compare this",
        "same image",
        "same video",
    }
    _MEDIA_FOLLOW_UP_CUES = {
        "before departure",
        "item",
        "items",
        "shortage",
        "shortages",
        "urgent",
        "visible",
        "shown",
        "notice",
        "stands out",
        "looks off",
        "look off",
        "matters most",
        "most important",
        "prioritize",
        "prioritise",
        "first thing",
        "people",
        "worker",
        "workers",
        "equipment",
        "machine",
        "machines",
        "tool",
        "tools",
        "pit edge",
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
    _WORK_PRODUCT_REFERENCE_PHRASES = {
        "that draft",
        "this draft",
        "the draft",
        "that note",
        "this note",
        "the note",
        "that checklist",
        "this checklist",
        "the checklist",
        "that task",
        "this task",
        "the task",
        "that export",
        "this export",
        "the export",
        "that report",
        "this report",
        "the report",
        "that message",
        "this message",
        "the message",
        "that reply",
        "this reply",
        "the reply",
        "that email",
        "this email",
        "the email",
        "that markdown",
        "this markdown",
        "the markdown",
        "that document",
        "this document",
        "the document",
        "before i save",
        "before you save",
        "save locally",
        "ready to save",
        "what title are you using",
        "what is the draft called",
        "what is that draft called",
        "what is the title now",
        "what is the draft title",
        "what did you call that",
        "rename that",
        "retitle that",
        "make that shorter",
        "tighten that draft",
    }
    _WORK_PRODUCT_NOUNS = {
        "draft",
        "note",
        "checklist",
        "task",
        "export",
        "report",
        "message",
        "reply",
        "email",
        "markdown",
        "document",
        "file",
        "title",
    }
    _WORK_PRODUCT_EDIT_TOKENS = {
        "edit",
        "rename",
        "retitle",
        "revise",
        "rewrite",
        "shorten",
        "shorter",
        "lengthen",
        "longer",
        "tighten",
        "called",
        "update",
        "save",
    }
    _WORK_PRODUCT_REFERENCE_CUES = {
        "that",
        "this",
        "same",
        "current",
        "earlier",
        "latest",
        "newer",
        "again",
        "title",
        "called",
        "before i save",
        "before you save",
        "ready to save",
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
    _SUPPORTIVE_CONVERSATION_PHRASES = {
        "i'm anxious",
        "i am anxious",
        "i'm nervous",
        "i am nervous",
        "i'm overwhelmed",
        "i am overwhelmed",
        "i'm stressed",
        "i am stressed",
        "i'm worried",
        "i am worried",
        "calm me down",
        "help me calm down",
        "talk me down",
        "reassure me",
        "no checklist right now",
        "like a normal person would",
    }
    _TOPIC_RESET_PHRASES = {
        "switch topics",
        "switch gears",
        "separate topic",
        "separate topic again",
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
        contextual_assets: list[AssetSummary] | None = None,
        conversation_context: ConversationContextSnapshot | None = None,
    ) -> RouteDecision:
        lowered = turn.text.lower().strip()
        decision = RouteDecision()
        attached_assets = assets or []
        contextual_assets = contextual_assets or []
        attached_image_assets = [
            asset for asset in attached_assets if asset.kind == AssetKind.IMAGE
        ]
        attached_video_assets = [
            asset for asset in attached_assets if asset.kind == AssetKind.VIDEO
        ]
        attached_document_assets = [
            asset for asset in attached_assets if asset.kind == AssetKind.DOCUMENT
        ]
        contextual_image_assets = [
            asset for asset in contextual_assets if asset.kind == AssetKind.IMAGE
        ]
        contextual_video_assets = [
            asset for asset in contextual_assets if asset.kind == AssetKind.VIDEO
        ]
        contextual_document_assets = [
            asset for asset in contextual_assets if asset.kind == AssetKind.DOCUMENT
        ]
        image_assets = attached_image_assets + contextual_image_assets
        video_assets = attached_video_assets + contextual_video_assets
        document_assets = attached_document_assets + contextual_document_assets
        medical_image_assets = [
            asset for asset in image_assets if asset.care_context == AssetCareContext.MEDICAL
        ]
        has_visual_context = bool(image_assets)
        has_video_context = bool(video_assets)
        has_document_context = bool(document_assets)
        history = history or []
        explicit_workspace_request = self._looks_like_workspace_agent_request(lowered)
        explicit_topic_reset = self._looks_like_topic_reset(lowered)
        explicit_conversation_override = self._looks_like_conversation_override(lowered)
        explicit_teaching_request = self._looks_like_teaching_request(lowered)
        explicit_source_request = any(token in lowered for token in self._SOURCE_SEEKING_TOKENS)
        explicit_media_reference = self._looks_like_explicit_media_reference(lowered)
        explicit_work_product_reference = self._looks_like_work_product_reference(
            lowered, conversation_context
        )
        explicit_non_media_override = (
            explicit_workspace_request
            or explicit_topic_reset
            or (explicit_conversation_override and not explicit_media_reference)
            or explicit_work_product_reference
            or (explicit_teaching_request and not explicit_media_reference)
            or (explicit_source_request and not explicit_media_reference)
        )

        if explicit_non_media_override and (
            contextual_image_assets or contextual_video_assets or contextual_document_assets
        ):
            contextual_image_assets = []
            contextual_video_assets = []
            contextual_document_assets = []
            image_assets = attached_image_assets
            video_assets = attached_video_assets
            document_assets = attached_document_assets
            medical_image_assets = [
                asset for asset in image_assets if asset.care_context == AssetCareContext.MEDICAL
            ]
            has_visual_context = bool(image_assets)
            has_video_context = bool(video_assets)
            has_document_context = bool(document_assets)
            decision.reasons.append(
                "Explicit user intent overrides the most recent media context."
            )

        general_conversation = self._looks_like_general_conversation(
            lowered,
            mode=turn.mode,
            has_visual_context=bool(attached_image_assets),
            has_video_context=bool(attached_video_assets),
            has_document_context=bool(attached_document_assets),
        )

        decision.is_follow_up = self._looks_like_follow_up(
            lowered,
            history=history,
            conversation_context=conversation_context,
            has_visual_context=has_visual_context,
            has_video_context=has_video_context,
            has_document_context=has_document_context,
            explicit_media_reference=explicit_media_reference,
            explicit_topic_reset=explicit_topic_reset or explicit_workspace_request,
        )
        if decision.is_follow_up:
            decision.reasons.append("Turn looks like a follow-up to recent conversation context.")

        if explicit_teaching_request:
            decision.interaction_kind = "teaching"
            decision.reasons.append("Turn looks like a teaching or explanation request.")
        elif explicit_work_product_reference:
            decision.interaction_kind = "draft_follow_up"
            decision.reasons.append("Turn refers to the current local draft or saved output.")
        elif general_conversation:
            decision.interaction_kind = "conversation"
            decision.reasons.append("Turn looks like ordinary conversation.")

        agentic_workspace_request = explicit_workspace_request
        if agentic_workspace_request:
            decision.agent_run = True
            decision.interaction_kind = "agent"
            decision.source_domain = SourceDomain.WORKSPACE
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

        contextual_media_follow_up = self._looks_like_contextual_media_follow_up(
            lowered,
            is_follow_up=decision.is_follow_up,
            explicit_media_reference=explicit_media_reference,
            explicit_non_media_override=explicit_non_media_override,
        )

        if decision.specialist_model not in {"medgemma", "translategemma"} and (
            attached_image_assets or (contextual_image_assets and contextual_media_follow_up)
        ):
            if attached_image_assets and any(word in lowered for word in self._VISUAL_HINTS):
                decision.reasons.append("Turn likely needs structured visual extraction.")
            elif contextual_image_assets:
                decision.reasons.append("Using the most recent image context for a follow-up turn.")
            else:
                decision.reasons.append("Using the attached image for this turn.")
            decision.specialist_model = "paligemma"
            decision.interaction_kind = "vision"
            decision.source_domain = SourceDomain.IMAGE

        if decision.specialist_model not in {"medgemma", "translategemma"} and (
            attached_video_assets or (contextual_video_assets and contextual_media_follow_up)
        ):
            if attached_video_assets and any(word in lowered for word in self._VIDEO_HINTS):
                decision.reasons.append("Turn likely needs local video detection or tracking.")
            elif contextual_video_assets:
                decision.reasons.append("Using the most recent video context for a follow-up turn.")
            else:
                decision.reasons.append("Using the attached video for this turn.")
            decision.specialist_model = "sam3"
            decision.interaction_kind = "video"
            decision.source_domain = SourceDomain.VIDEO

        if decision.specialist_model not in {"medgemma", "translategemma", "paligemma", "sam3"} and (
            attached_document_assets or (contextual_document_assets and decision.is_follow_up)
        ):
            if attached_document_assets and any(word in lowered for word in self._DOCUMENT_HINTS):
                decision.reasons.append("Turn likely needs local document extraction.")
            elif contextual_document_assets:
                decision.reasons.append("Using the most recent document context for a follow-up turn.")
            else:
                decision.reasons.append("Using the attached document for this turn.")
            decision.specialist_model = "document"
            decision.interaction_kind = "document"
            decision.source_domain = SourceDomain.DOCUMENT

        explicit_retrieval = any(token in lowered for token in self._SOURCE_SEEKING_TOKENS)
        image_safe_retrieval = any(
            token in lowered for token in {"source", "sources", "document", "documents", "library", "reference"}
        )
        knowledge_guided_teaching = (
            decision.interaction_kind == "teaching"
            and turn.mode in {AssistantMode.FIELD, AssistantMode.RESEARCH}
            and any(topic in lowered for topic in self._LOCAL_KNOWLEDGE_TOPICS)
        )

        if not decision.agent_run and not general_conversation and (
            turn.enabled_knowledge_pack_ids
            or (
                explicit_retrieval
                and (
                    (not has_visual_context and not has_video_context and not has_document_context)
                    or (
                        image_safe_retrieval
                        and has_visual_context
                        and not has_video_context
                        and not has_document_context
                    )
                )
                or knowledge_guided_teaching
            )
        ):
            decision.needs_retrieval = True
            decision.reasons.append("Turn benefits from local retrieval before synthesis.")

        if explicit_work_product_reference and decision.needs_retrieval:
            decision.needs_retrieval = False
            decision.reasons = [
                reason
                for reason in decision.reasons
                if reason != "Turn benefits from local retrieval before synthesis."
            ]
            decision.reasons.append(
                "Stayed anchored to the referenced local output instead of reopening retrieval."
            )

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
        has_document_context: bool,
    ) -> bool:
        if has_visual_context or has_video_context or has_document_context:
            return False
        if any(self._matches_phrase(lowered, phrase) for phrase in self._CASUAL_CONVERSATION_PHRASES):
            return True
        if any(self._matches_phrase(lowered, phrase) for phrase in self._SUPPORTIVE_CONVERSATION_PHRASES):
            return True
        if self._looks_like_topic_reset(lowered):
            return True
        if self._looks_like_teaching_request(lowered):
            return False
        if self._looks_like_workspace_agent_request(lowered):
            return False
        if self.tools.propose(lowered):
            return False
        if any(token in lowered for token in self._SOURCE_SEEKING_TOKENS):
            return False
        if mode == AssistantMode.GENERAL and len(lowered.split()) <= 14:
            return True
        return False

    def _looks_like_conversation_override(self, lowered: str) -> bool:
        return (
            any(self._matches_phrase(lowered, phrase) for phrase in self._CASUAL_CONVERSATION_PHRASES)
            or any(self._matches_phrase(lowered, phrase) for phrase in self._SUPPORTIVE_CONVERSATION_PHRASES)
            or self._looks_like_topic_reset(lowered)
        )

    def _looks_like_workspace_agent_request(self, lowered: str) -> bool:
        if any(phrase in lowered for phrase in self._WORKSPACE_AGENT_PHRASES):
            return True

        has_scope = any(self._contains_term(lowered, token) for token in self._WORKSPACE_SCOPE_TOKENS)
        has_action = any(self._contains_term(lowered, token) for token in self._WORKSPACE_ACTION_TOKENS)
        return has_scope and has_action

    def _looks_like_explicit_media_reference(self, lowered: str) -> bool:
        if any(phrase in lowered for phrase in self._MEDIA_REFERENCE_PHRASES):
            return True
        return any(
            token in lowered
            for token in {
                "image",
                "picture",
                "photo",
                "screenshot",
                "xray",
                "x-ray",
                "video",
                "clip",
                "frame",
                "document",
                "pdf",
                "page",
                "section",
            }
        )

    def _looks_like_contextual_media_follow_up(
        self,
        lowered: str,
        *,
        is_follow_up: bool,
        explicit_media_reference: bool,
        explicit_non_media_override: bool,
    ) -> bool:
        if explicit_non_media_override:
            return False
        if explicit_media_reference:
            return True
        if any(cue in lowered for cue in self._MEDIA_FOLLOW_UP_CUES):
            return True
        return is_follow_up and any(
            cue in lowered
            for cue in {
                "what about",
                "which one",
                "is that",
                "is there",
                "does that",
                "do those",
            }
        )

    def _matches_phrase(self, lowered: str, phrase: str) -> bool:
        if " " in phrase:
            return phrase in lowered
        words = lowered.replace("?", " ").replace("!", " ").replace(".", " ").split()
        return phrase in words

    def _contains_term(self, lowered: str, term: str) -> bool:
        if " " in term:
            return term in lowered
        return re.search(rf"\b{re.escape(term)}\b", lowered) is not None

    def _looks_like_follow_up(
        self,
        lowered: str,
        *,
        history: list[ConversationMessage],
        conversation_context: ConversationContextSnapshot | None,
        has_visual_context: bool,
        has_video_context: bool,
        has_document_context: bool,
        explicit_media_reference: bool,
        explicit_topic_reset: bool,
    ) -> bool:
        has_prior_context = bool(history) or bool(
            conversation_context
            and (
                conversation_context.active_topic
                or conversation_context.pending_approval_tool
                or conversation_context.last_completed_output_tool
            )
        )
        if not has_prior_context:
            return False
        if explicit_topic_reset:
            return False
        if self._looks_like_work_product_reference(lowered, conversation_context):
            return True
        if explicit_media_reference and (has_visual_context or has_video_context or has_document_context):
            return True
        if lowered.startswith(self._FOLLOW_UP_PREFIXES):
            return True
        if any(
            phrase in lowered
            for phrase in {
                "what do you mean by that",
                "what did you mean by that",
                "can you explain that",
                "tell me more about that",
                "go back to that",
                "bring that up again",
                "one sentence",
                "say that plainly",
                "say that simply",
                "put it plainly",
                "what should make me stop",
                "what should make you stop",
                "what should make us stop",
                "what should i watch for",
                "what would make me stop",
                "what would make me escalate",
                "what should make me escalate",
                "what's the first action again",
                "what is the first action again",
                "first action again",
            }
        ):
            return True
        if len(lowered.split()) <= 12 and any(
            lowered.startswith(prefix)
            for prefix in {"it", "that", "those", "they", "and", "also", "why", "what", "how", "which"}
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

    def _looks_like_work_product_reference(
        self,
        lowered: str,
        conversation_context: ConversationContextSnapshot | None,
    ) -> bool:
        if not conversation_context:
            return False
        if not (
            conversation_context.pending_approval_tool
            or conversation_context.last_completed_output_tool
        ):
            return False
        if any(phrase in lowered for phrase in self._WORK_PRODUCT_REFERENCE_PHRASES):
            return True
        has_noun = any(token in lowered for token in self._WORK_PRODUCT_NOUNS)
        has_edit_intent = any(token in lowered for token in self._WORK_PRODUCT_EDIT_TOKENS)
        has_reference_cue = any(token in lowered for token in self._WORK_PRODUCT_REFERENCE_CUES)
        has_recall_intent = lowered.startswith(
            ("what was in", "what is in", "what's in", "remind me", "show me")
        )
        return has_noun and (has_recall_intent or (has_edit_intent and has_reference_cue))
