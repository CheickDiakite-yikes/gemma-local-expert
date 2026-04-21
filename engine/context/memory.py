from __future__ import annotations

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
)


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
        evidence_packet: EvidencePacket | None,
        workspace_summary_text: str | None,
        tool_name: str | None,
    ) -> ConversationMemoryEntry | None:
        if not self._should_store(
            user_text=user_text,
            assistant_text=assistant_text,
            interaction_kind=interaction_kind,
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

    def _should_store(
        self,
        *,
        user_text: str,
        assistant_text: str,
        interaction_kind: str,
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
        if len(" ".join(assistant_text.split())) < 48:
            return False
        if evidence_packet or workspace_summary_text or tool_name:
            return True
        return interaction_kind in {"conversation", "teaching", "draft_follow_up"}

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
