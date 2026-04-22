from __future__ import annotations

from typing import TYPE_CHECKING

from engine.contracts.api import (
    ConversationMemoryEntry,
    ConversationMemoryKind,
    EvidencePacket,
    SourceDomain,
    new_id,
)
from engine.models.runtime import (
    ConversationMemoryRankingRequest,
    AssistantRuntime,
    ConversationMemoryRequest,
    MemoryFocusRequest,
    MemoryFocusResult,
)

if TYPE_CHECKING:
    from engine.context.service import ConversationContextSnapshot


class ConversationMemoryService:
    def __init__(self, runtime: AssistantRuntime) -> None:
        self.runtime = runtime

    def build_entry(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        user_text: str,
        assistant_text: str,
        interaction_kind: str,
        active_topic: str | None,
        source_domain: SourceDomain | None,
        asset_ids: list[str] | None,
        referent_kind: str | None,
        referent_title: str | None,
        referent_excerpt: str | None,
        evidence_packet: EvidencePacket | None,
        workspace_summary_text: str | None,
        tool_name: str | None,
    ) -> ConversationMemoryEntry | None:
        if not self._should_store(
            user_text=user_text,
            assistant_text=assistant_text,
            interaction_kind=interaction_kind,
            source_domain=source_domain,
            referent_kind=referent_kind,
            evidence_packet=evidence_packet,
            workspace_summary_text=workspace_summary_text,
            tool_name=tool_name,
        ):
            return None

        memory = self.runtime.synthesize_memory(
            ConversationMemoryRequest(
                conversation_id=conversation_id,
                turn_id=turn_id,
                user_text=user_text,
                assistant_text=assistant_text,
                interaction_kind=interaction_kind,
                active_topic=active_topic,
                source_domain=source_domain,
                asset_ids=list(asset_ids or []),
                referent_kind=referent_kind,
                referent_title=referent_title,
                referent_excerpt=referent_excerpt,
                evidence_packet=evidence_packet,
                workspace_summary_text=workspace_summary_text,
                tool_name=tool_name,
            )
        )
        if memory is None or not memory.topic.strip() or not memory.summary.strip():
            return None

        kind = self._memory_kind(
            interaction_kind=interaction_kind,
            source_domain=source_domain,
            tool_name=tool_name,
        )
        memory_asset_ids = (
            list(asset_ids)
            if asset_ids
            else (list(evidence_packet.asset_ids) if evidence_packet else [])
        )
        return ConversationMemoryEntry(
            id=new_id("memory"),
            conversation_id=conversation_id,
            turn_id=turn_id,
            kind=kind,
            topic=memory.topic.strip(),
            summary=memory.summary.strip(),
            keywords=memory.keywords[:8],
            source_domain=source_domain,
            asset_ids=memory_asset_ids,
            tool_name=tool_name,
            referent_title=referent_title,
        )

    def rerank_entries(
        self,
        *,
        user_text: str,
        active_topic: str | None,
        entries: list[ConversationMemoryEntry],
        limit: int,
    ) -> list[ConversationMemoryEntry]:
        if len(entries) <= 1:
            return entries
        bounded = list(entries[:limit])
        ranking = self.runtime.rank_memories(
            ConversationMemoryRankingRequest(
                user_text=user_text,
                active_topic=active_topic,
                memories=bounded,
            )
        )
        if ranking is None or not ranking.ordered_ids:
            return entries
        by_id = {entry.id: entry for entry in bounded}
        ranked = [by_id[memory_id] for memory_id in ranking.ordered_ids if memory_id in by_id]
        seen = {entry.id for entry in ranked}
        remaining = [entry for entry in bounded if entry.id not in seen]
        return ranked + remaining + list(entries[limit:])

    def resolve_focus(
        self,
        *,
        user_text: str,
        conversation_context: "ConversationContextSnapshot",
        entries: list[ConversationMemoryEntry],
        limit: int,
    ) -> MemoryFocusResult | None:
        deterministic = self._deterministic_focus(conversation_context)
        if deterministic is not None:
            return deterministic
        bounded = list(entries[:limit])
        return self.runtime.resolve_memory_focus(
            MemoryFocusRequest(
                user_text=user_text,
                active_topic=conversation_context.active_topic,
                selected_referent_kind=conversation_context.selected_referent_kind,
                selected_referent_title=conversation_context.selected_referent_title,
                selected_referent_summary=conversation_context.selected_referent_summary,
                selected_evidence_summary=conversation_context.selected_evidence_summary,
                selected_evidence_facts=list(conversation_context.selected_evidence_facts),
                recent_topics=list(conversation_context.recent_topics),
                memories=bounded,
            )
        )

    def _deterministic_focus(
        self,
        conversation_context: "ConversationContextSnapshot",
    ) -> MemoryFocusResult | None:
        if conversation_context.selected_referent_kind in {"pending_output", "saved_output"}:
            topic_frame = (
                conversation_context.selected_referent_title
                or conversation_context.selected_referent_summary
            )
            return MemoryFocusResult(
                primary_anchor_kind="referent",
                memory_id=None,
                topic_frame=topic_frame,
                reason="An explicit current work product is already selected.",
                confidence=1.0,
                conflict_note=None,
                ask_clarifying_question=None,
                backend="deterministic",
            )
        if conversation_context.selected_evidence_summary:
            return MemoryFocusResult(
                primary_anchor_kind="grounded_evidence",
                memory_id=None,
                topic_frame=conversation_context.selected_referent_title
                or conversation_context.active_topic,
                reason="Grounded evidence is already selected and should outrank conversation memory.",
                confidence=0.98,
                conflict_note=None,
                ask_clarifying_question=None,
                backend="deterministic",
            )
        return None

    def _should_store(
        self,
        *,
        user_text: str,
        assistant_text: str,
        interaction_kind: str,
        source_domain: SourceDomain | None,
        referent_kind: str | None,
        evidence_packet: EvidencePacket | None,
        workspace_summary_text: str | None,
        tool_name: str | None,
    ) -> bool:
        lowered = user_text.lower().strip()
        if lowered in {
            "ok",
            "okay",
            "thanks",
            "thank you",
            "continue",
            "lets continue",
            "let's continue",
        }:
            return False
        if self._is_derivative_teaching_follow_up(
            lowered=lowered,
            interaction_kind=interaction_kind,
            source_domain=source_domain,
            tool_name=tool_name,
            evidence_packet=evidence_packet,
            workspace_summary_text=workspace_summary_text,
        ):
            return False
        if referent_kind == "missing_output":
            return False
        if interaction_kind == "draft_follow_up" and not tool_name:
            return False
        if referent_kind in {"pending_output", "saved_output"} and not tool_name:
            return False
        if self._is_low_signal_assistant_text(
            assistant_text=assistant_text,
            interaction_kind=interaction_kind,
            source_domain=source_domain,
            evidence_packet=evidence_packet,
            workspace_summary_text=workspace_summary_text,
            tool_name=tool_name,
        ):
            return False
        if len(" ".join(assistant_text.split())) < 48:
            return False
        if evidence_packet or workspace_summary_text or tool_name:
            return True
        return interaction_kind in {"conversation", "teaching", "draft_follow_up"}

    def _is_derivative_teaching_follow_up(
        self,
        *,
        lowered: str,
        interaction_kind: str,
        source_domain: SourceDomain | None,
        tool_name: str | None,
        evidence_packet: EvidencePacket | None,
        workspace_summary_text: str | None,
    ) -> bool:
        if tool_name or evidence_packet or workspace_summary_text:
            return False
        if source_domain in {SourceDomain.IMAGE, SourceDomain.VIDEO, SourceDomain.DOCUMENT}:
            return False
        if interaction_kind not in {"conversation", "teaching"}:
            return False
        return any(
            phrase in lowered
            for phrase in {
                "what did you mean by that",
                "what do you mean by that",
                "can you explain that",
                "tell me more about that",
                "go back to that",
                "bring that up again",
                "come back to that",
                "go deeper on that",
                "what was the point again",
                "what was the main point again",
                "remind me what we were saying",
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
        )

    def _is_low_signal_assistant_text(
        self,
        *,
        assistant_text: str,
        interaction_kind: str,
        source_domain: SourceDomain | None,
        evidence_packet: EvidencePacket | None,
        workspace_summary_text: str | None,
        tool_name: str | None,
    ) -> bool:
        cleaned = " ".join(assistant_text.lower().split())
        if not cleaned:
            return True
        if tool_name or evidence_packet or workspace_summary_text:
            return False
        if source_domain in {SourceDomain.IMAGE, SourceDomain.VIDEO, SourceDomain.DOCUMENT}:
            return False
        if interaction_kind not in {"conversation", "draft_follow_up"}:
            return False
        low_signal_prefixes = (
            "hi. we can talk normally here",
            "yes. we can talk normally here",
            "yes. we can just talk this through",
            "hey. what's on your mind",
            "hey. what's up",
            "i'm doing well. what's on your mind",
            "of course. i'm here when you want to keep going",
            "i mean we can keep this conversational",
            "to build on what we were just discussing",
            "to build on the last point",
            "staying with that, i would keep the next step simple and concrete",
            "i would keep the next step simple and concrete",
            "yes. we can stay with what we were just discussing",
            "yes. we can stay with the earlier thread",
            "sure. let's come back to that",
        )
        return cleaned.startswith(low_signal_prefixes)

    def _memory_kind(
        self,
        *,
        interaction_kind: str,
        source_domain: SourceDomain | None,
        tool_name: str | None,
    ) -> ConversationMemoryKind:
        if tool_name:
            return ConversationMemoryKind.OUTPUT
        if source_domain == SourceDomain.WORKSPACE:
            return ConversationMemoryKind.WORKSPACE
        if source_domain in {SourceDomain.IMAGE, SourceDomain.VIDEO, SourceDomain.DOCUMENT}:
            return ConversationMemoryKind.MEDIA
        if interaction_kind == "teaching":
            return ConversationMemoryKind.TEACHING
        return ConversationMemoryKind.GENERAL
