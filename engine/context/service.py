from __future__ import annotations

import re
from dataclasses import dataclass, field

from engine.contracts.api import (
    AssetKind,
    AssetSummary,
    ConversationMemoryEntry,
    ConversationMemoryKind,
    EvidencePacket,
    TranscriptMessage,
)


_LOW_SIGNAL_USER_TURNS = {
    "k",
    "kk",
    "ok",
    "okay",
    "sounds good",
    "lets continue",
    "let's continue",
    "continue",
    "thanks",
    "thank you",
}

_IMAGE_REFERENCE_TOKENS = {
    "image",
    "picture",
    "photo",
    "screenshot",
    "xray",
    "x-ray",
    "radiograph",
    "scan",
}

_VIDEO_REFERENCE_TOKENS = {
    "video",
    "clip",
    "camera",
    "footage",
    "recording",
    "frame",
}

_DOCUMENT_REFERENCE_TOKENS = {
    "document",
    "pdf",
    "page",
    "pages",
    "section",
    "sections",
    "file",
    "files",
}

_MEDIA_FOLLOW_UP_CUES = {
    "before departure",
    "item",
    "items",
    "prioritize",
    "prioritise",
    "which one",
    "what stands out",
    "what do you notice",
    "what matters most",
    "most important",
    "looks off",
    "look off",
    "shortage",
    "shortages",
    "urgent",
    "visible",
    "shown",
    "compare this",
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
    "what title is that",
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

_TEACHING_FOLLOW_UP_PHRASES = {
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

_EARLIER_REFERENCE_TOKENS = {
    "earlier",
    "previous",
    "prior",
    "before",
    "original",
}

_LATEST_REFERENCE_TOKENS = {
    "current",
    "latest",
    "newest",
    "recent",
}

_TOPIC_REFERENCE_PHRASES = {
    "what did you mean by that",
    "what do you mean by that",
    "can you explain that",
    "tell me more about that",
    "go back to that",
    "bring that up again",
    "come back to that",
    "go deeper on that",
}

_REFERENT_METADATA_PREFIXES = {
    "key points:",
    "files reviewed:",
    "related docs:",
    "related brief:",
    "related local docs:",
    "working title:",
    "goal:",
    "workspace scope:",
}

_REFERENT_STOPWORDS = {
    "the",
    "a",
    "an",
    "that",
    "this",
    "again",
    "what",
    "was",
    "is",
    "in",
    "called",
    "title",
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
    "save",
    "before",
    "earlier",
    "previous",
    "prior",
    "current",
    "latest",
    "newest",
}


@dataclass(slots=True)
class GroundedEvidenceMemory:
    domain: str
    asset_ids: list[str] = field(default_factory=list)
    asset_labels: list[str] = field(default_factory=list)
    summary: str | None = None
    fact_lines: list[str] = field(default_factory=list)
    uncertainty_lines: list[str] = field(default_factory=list)
    execution_mode: str | None = None
    grounding_status: str | None = None
    turn_id: str | None = None


@dataclass(slots=True)
class ConversationContextSnapshot:
    active_topic: str | None = None
    active_domain: str | None = None
    active_asset_ids: list[str] = field(default_factory=list)
    active_asset_labels: list[str] = field(default_factory=list)
    recent_topics: list[str] = field(default_factory=list)
    last_user_request: str | None = None
    last_assistant_reply: str | None = None
    last_image_assets: list[AssetSummary] = field(default_factory=list)
    last_video_assets: list[AssetSummary] = field(default_factory=list)
    selected_context_assets: list[AssetSummary] = field(default_factory=list)
    selected_context_kind: str | None = None
    selected_context_reason: str | None = None
    selected_context_summary: str | None = None
    selected_evidence_summary: str | None = None
    selected_evidence_facts: list[str] = field(default_factory=list)
    selected_evidence_uncertainties: list[str] = field(default_factory=list)
    selected_referent_kind: str | None = None
    selected_referent_tool: str | None = None
    selected_referent_title: str | None = None
    selected_referent_reason: str | None = None
    selected_referent_summary: str | None = None
    selected_referent_excerpt: str | None = None
    pending_approval_id: str | None = None
    pending_approval_tool: str | None = None
    pending_approval_summary: str | None = None
    pending_approval_excerpt: str | None = None
    active_draft_lineage: str | None = None
    last_completed_output_tool: str | None = None
    last_completed_output_title: str | None = None
    last_completed_output_excerpt: str | None = None
    last_agent_summary: str | None = None
    recent_outputs: list["WorkProductReference"] = field(default_factory=list)
    recent_evidence_memories: list[GroundedEvidenceMemory] = field(default_factory=list)
    recent_conversation_memories: list[ConversationMemoryEntry] = field(default_factory=list)
    selected_memory_topic: str | None = None
    selected_memory_summary: str | None = None
    memory_focus_kind: str | None = None
    memory_focus_reason: str | None = None
    memory_focus_confidence: float | None = None
    memory_focus_topic_frame: str | None = None
    memory_focus_conflict_note: str | None = None
    memory_focus_clarifying_question: str | None = None

    def prompt_lines(self) -> list[str]:
        lines: list[str] = []
        if self.active_topic:
            lines.append(f"Active topic: {self.active_topic}")
        if self.active_domain:
            lines.append(f"Active domain: {self.active_domain}")
        if self.active_asset_labels:
            lines.append("Active asset set: " + ", ".join(self.active_asset_labels[:3]))
        if self.recent_topics[1:]:
            recent = ", ".join(self.recent_topics[1:3])
            if recent:
                lines.append(f"Recent earlier topics: {recent}")
        if self.selected_referent_kind:
            lines.append(
                "Likely current referent: "
                + self._format_referent(
                    kind=self.selected_referent_kind,
                    tool_name=self.selected_referent_tool,
                    title=self.selected_referent_title,
                )
            )
        if self.selected_referent_summary:
            lines.append(f"Likely referent summary: {self.selected_referent_summary}")
        if self.selected_referent_excerpt:
            lines.append(f"Likely referent preview: {self.selected_referent_excerpt}")
        if self.selected_context_assets:
            labels = ", ".join(asset.display_name for asset in self.selected_context_assets[:2])
            kind = self.selected_context_kind or "media"
            lines.append(f"Relevant earlier {kind}: {labels}")
            if self.selected_context_summary:
                lines.append(f"Relevant earlier {kind} summary: {self.selected_context_summary}")
            if self.selected_evidence_summary:
                lines.append(f"Relevant grounded {kind} evidence: {self.selected_evidence_summary}")
            for fact in self.selected_evidence_facts[:3]:
                lines.append(f"Relevant grounded fact: {fact}")
            for item in self.selected_evidence_uncertainties[:2]:
                lines.append(f"Relevant grounded limit: {item}")
        elif self.last_image_assets or self.last_video_assets:
            available: list[str] = []
            if self.last_image_assets:
                available.append("image")
            if self.last_video_assets:
                available.append("video")
            lines.append("Recent media available: " + ", ".join(available))
        if (
            self.pending_approval_tool
            and self.selected_referent_kind not in {"pending_output", "saved_output"}
        ):
            lines.append(
                "Pending draft: "
                + self._format_referent(
                    kind="pending_output",
                    tool_name=self.pending_approval_tool,
                    title=self.pending_approval_summary,
                )
            )
            if self.pending_approval_excerpt:
                lines.append(f"Pending draft preview: {self.pending_approval_excerpt}")
        if self.active_draft_lineage:
            lines.append(f"Active draft lineage: {self.active_draft_lineage}")
        if (
            self.last_completed_output_tool
            and self.last_completed_output_title
            and self.selected_referent_kind not in {"pending_output", "saved_output"}
        ):
            lines.append(
                "Most recent saved output: "
                + self._format_referent(
                    kind="saved_output",
                    tool_name=self.last_completed_output_tool,
                    title=self.last_completed_output_title,
                )
            )
            if self.last_completed_output_excerpt:
                lines.append(
                    f"Most recent saved output preview: {self.last_completed_output_excerpt}"
                )
        if len(self.recent_outputs) > 1:
            labels = [
                self._format_referent(
                    kind=output.kind,
                    tool_name=output.tool_name,
                    title=output.title,
                )
                for output in self.recent_outputs[:3]
            ]
            if labels:
                lines.append("Recent local outputs: " + "; ".join(labels))
        if self.recent_evidence_memories:
            evidence_labels = []
            for memory in self.recent_evidence_memories[:3]:
                label = memory.domain
                if memory.asset_labels:
                    label += f" ({', '.join(memory.asset_labels[:2])})"
                evidence_labels.append(label)
            if evidence_labels:
                lines.append("Recent grounded evidence memory: " + "; ".join(evidence_labels))
        if self.selected_memory_summary:
            selected_memory = self.selected_memory_summary
            if self.selected_memory_topic:
                selected_memory = f"{self.selected_memory_topic}: {selected_memory}"
            lines.append(f"Selected conversation memory: {selected_memory}")
        if self.memory_focus_kind:
            confidence = (
                f"{self.memory_focus_confidence:.2f}"
                if self.memory_focus_confidence is not None
                else "unknown"
            )
            lines.append(f"Memory focus: kind={self.memory_focus_kind} confidence={confidence}")
            if self.memory_focus_topic_frame:
                lines.append(f"Memory focus topic: {self.memory_focus_topic_frame}")
            if self.memory_focus_reason:
                lines.append(f"Memory focus reason: {self.memory_focus_reason}")
            if self.memory_focus_conflict_note:
                lines.append(f"Memory focus conflict: {self.memory_focus_conflict_note}")
            if self.memory_focus_clarifying_question:
                lines.append(
                    f"Memory focus clarification: {self.memory_focus_clarifying_question}"
                )
        elif self.recent_conversation_memories:
            memory_labels = [
                self._trim(f"{memory.topic}: {memory.summary}", 140)
                for memory in self.recent_conversation_memories[:2]
            ]
            if memory_labels:
                lines.append("Recent conversation memories: " + " ; ".join(memory_labels))
        return lines

    def _format_referent(
        self,
        *,
        kind: str,
        tool_name: str | None,
        title: str | None,
    ) -> str:
        if kind == "pending_output":
            base = f"{self._tool_label(tool_name)} draft"
            return f'{base} "{title}"' if title else base
        if kind == "saved_output":
            base = self._tool_label(tool_name)
            return f'{base} "{title}"' if title else base
        if kind in {"image", "video"}:
            base = f"earlier {kind}"
            return f'{base} "{title}"' if title else base
        if kind == "topic":
            return title or "the earlier topic"
        return title or kind.replace("_", " ")

    def _tool_label(self, tool_name: str | None) -> str:
        mapping = {
            "create_note": "note",
            "create_report": "report",
            "create_message_draft": "message draft",
            "create_checklist": "checklist",
            "create_task": "task",
            "export_brief": "markdown export",
            "log_observation": "observation",
        }
        if tool_name in mapping:
            return mapping[tool_name]
        if not tool_name:
            return "output"
        return tool_name.replace("_", " ")

    def _trim(self, text: str, limit: int) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 1].rstrip() + "…"


@dataclass(slots=True)
class WorkProductReference:
    kind: str
    tool_name: str | None
    title: str | None
    excerpt: str | None
    approval_id: str | None = None


class ConversationContextService:
    def describe_payload(
        self, payload: dict[str, object] | None
    ) -> tuple[str | None, str | None]:
        if not isinstance(payload, dict):
            return None, None
        summary = None
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            summary = self._trim(self._compact(title), 96)
        excerpt = self._work_product_excerpt(payload)
        return summary, excerpt

    def build(
        self,
        *,
        turn_text: str,
        transcript: list[TranscriptMessage],
        attached_assets: list[AssetSummary],
        recent_memories: list[ConversationMemoryEntry] | None = None,
    ) -> ConversationContextSnapshot:
        snapshot = ConversationContextSnapshot()
        snapshot.recent_topics = self._recent_topics(transcript)
        snapshot.active_topic = snapshot.recent_topics[0] if snapshot.recent_topics else None
        snapshot.last_user_request = snapshot.active_topic
        snapshot.last_assistant_reply = self._last_message_text(transcript, role="assistant")
        snapshot.last_agent_summary = self._last_agent_summary(transcript)
        snapshot.recent_outputs = self._recent_work_products(transcript)
        (
            snapshot.pending_approval_id,
            snapshot.pending_approval_tool,
            snapshot.pending_approval_summary,
            snapshot.pending_approval_excerpt,
        ) = self._pending_approval(transcript)
        (
            snapshot.last_completed_output_tool,
            snapshot.last_completed_output_title,
            snapshot.last_completed_output_excerpt,
        ) = self._last_completed_output(transcript)
        image_reference_groups = self._recent_reference_assets_by_kind(
            transcript, AssetKind.IMAGE
        )
        video_reference_groups = self._recent_reference_assets_by_kind(
            transcript, AssetKind.VIDEO
        )
        document_reference_groups = self._recent_reference_assets_by_kind(
            transcript, AssetKind.DOCUMENT
        )
        snapshot.recent_conversation_memories = list(recent_memories or [])
        snapshot.last_image_assets = image_reference_groups[0] if image_reference_groups else []
        snapshot.last_video_assets = video_reference_groups[0] if video_reference_groups else []
        snapshot.recent_evidence_memories = self._recent_evidence_memories(transcript)

        if not attached_assets or self._should_mix_attached_assets_with_prior_context(turn_text):
            (
                snapshot.selected_context_assets,
                snapshot.selected_context_kind,
                snapshot.selected_context_reason,
            ) = self._select_context_assets(
                turn_text=turn_text,
                transcript=transcript,
                image_reference_groups=image_reference_groups,
                video_reference_groups=video_reference_groups,
                document_reference_groups=document_reference_groups,
            )
            if snapshot.selected_context_assets and snapshot.selected_context_kind:
                snapshot.selected_context_summary = self._asset_context_summary(
                    turn_text=turn_text,
                    transcript=transcript,
                    assets=snapshot.selected_context_assets,
                    kind=snapshot.selected_context_kind,
                )
        selected_evidence = self._select_evidence_memory(
            turn_text=turn_text,
            snapshot=snapshot,
        )
        if selected_evidence is not None:
            snapshot.selected_evidence_summary = selected_evidence.summary
            snapshot.selected_evidence_facts = selected_evidence.fact_lines
            snapshot.selected_evidence_uncertainties = selected_evidence.uncertainty_lines
        (
            snapshot.selected_referent_kind,
            snapshot.selected_referent_tool,
            snapshot.selected_referent_title,
            snapshot.selected_referent_excerpt,
            snapshot.selected_referent_reason,
        ) = self._select_referent(turn_text=turn_text, snapshot=snapshot)
        if snapshot.selected_referent_kind == "pending_output":
            snapshot.selected_referent_summary = snapshot.selected_referent_title
        elif snapshot.selected_referent_kind == "saved_output":
            snapshot.selected_referent_summary = snapshot.selected_referent_title
        elif snapshot.selected_referent_kind in {"image", "video", "document"}:
            media_summary = snapshot.selected_context_summary or snapshot.selected_evidence_summary
            snapshot.selected_referent_summary = media_summary
            snapshot.selected_referent_excerpt = media_summary
        elif snapshot.selected_referent_kind == "topic" and snapshot.active_topic:
            snapshot.selected_referent_summary = snapshot.active_topic
        selected_memory = self._select_conversation_memory(
            turn_text=turn_text,
            snapshot=snapshot,
        )
        if selected_memory is not None:
            snapshot.selected_memory_topic = selected_memory.topic
            snapshot.selected_memory_summary = selected_memory.summary
        snapshot.active_domain = (
            snapshot.selected_referent_kind
            or snapshot.selected_context_kind
            or (selected_evidence.domain if selected_evidence is not None else None)
        )
        if snapshot.selected_context_assets:
            snapshot.active_asset_ids = [asset.id for asset in snapshot.selected_context_assets]
            snapshot.active_asset_labels = [
                asset.display_name for asset in snapshot.selected_context_assets[:3]
            ]
        elif selected_evidence is not None:
            snapshot.active_asset_ids = selected_evidence.asset_ids[:3]
            snapshot.active_asset_labels = selected_evidence.asset_labels[:3]
        snapshot.active_draft_lineage = snapshot.pending_approval_id
        return snapshot

    def _select_conversation_memory(
        self,
        *,
        turn_text: str,
        snapshot: ConversationContextSnapshot,
    ) -> ConversationMemoryEntry | None:
        if not snapshot.recent_conversation_memories:
            return None
        if snapshot.selected_referent_kind in {
            "pending_output",
            "saved_output",
            "image",
            "video",
            "document",
        }:
            return None
        if snapshot.selected_context_assets or snapshot.selected_evidence_summary:
            return None
        query_tokens = self._meaningful_referent_tokens(turn_text)
        lowered_turn = turn_text.lower().strip()
        teaching_follow_up = self._looks_like_teaching_follow_up(lowered_turn)
        best_memory: ConversationMemoryEntry | None = None
        best_score = 0
        for index, memory in enumerate(snapshot.recent_conversation_memories):
            score = max(0, 10 - index)
            searchable = " ".join(
                part
                for part in [
                    memory.topic,
                    memory.summary,
                    " ".join(memory.keywords),
                    memory.referent_title or "",
                ]
                if part
            )
            memory_tokens = self._meaningful_referent_tokens(searchable)
            score += len(query_tokens & memory_tokens) * 5
            if memory.referent_title and memory.referent_title.lower() in turn_text.lower():
                score += 12
            if not query_tokens and self._looks_like_topic_reference(turn_text.lower().strip()):
                score += 4
            if teaching_follow_up and memory.kind == ConversationMemoryKind.TEACHING:
                score += 10
                if snapshot.active_topic:
                    active_topic_tokens = self._meaningful_referent_tokens(snapshot.active_topic)
                    overlap = len(active_topic_tokens & memory_tokens)
                    if overlap:
                        score += 6 + (overlap * 2)
            if score > best_score:
                best_score = score
                best_memory = memory
        return best_memory if best_score > 6 else None

    def _recent_evidence_memories(
        self,
        transcript: list[TranscriptMessage],
    ) -> list[GroundedEvidenceMemory]:
        asset_lookup: dict[str, AssetSummary] = {}
        for message in transcript:
            for asset in message.assets:
                asset_lookup[asset.id] = asset

        memories: list[GroundedEvidenceMemory] = []
        seen_packet_ids: set[str] = set()
        for message in reversed(transcript):
            evidence_packet = message.evidence_packet
            if evidence_packet is None or evidence_packet.id in seen_packet_ids:
                continue
            seen_packet_ids.add(evidence_packet.id)
            asset_labels = self._evidence_asset_labels(
                evidence_packet=evidence_packet,
                message=message,
                asset_lookup=asset_lookup,
            )
            memories.append(
                GroundedEvidenceMemory(
                    domain=evidence_packet.source_domain.value,
                    asset_ids=list(evidence_packet.asset_ids),
                    asset_labels=asset_labels,
                    summary=self._trim(self._compact(evidence_packet.summary), 180),
                    fact_lines=self._evidence_fact_lines(evidence_packet),
                    uncertainty_lines=[
                        self._trim(self._compact(item), 140)
                        for item in evidence_packet.uncertainties[:3]
                        if self._compact(item)
                    ],
                    execution_mode=evidence_packet.execution_mode.value,
                    grounding_status=evidence_packet.grounding_status.value,
                    turn_id=message.turn_id,
                )
            )
            if len(memories) == 6:
                break
        return memories

    def _evidence_asset_labels(
        self,
        *,
        evidence_packet: EvidencePacket,
        message: TranscriptMessage,
        asset_lookup: dict[str, AssetSummary],
    ) -> list[str]:
        labels: list[str] = []
        seen_ids: set[str] = set()
        for asset_id in evidence_packet.asset_ids:
            asset = asset_lookup.get(asset_id)
            if asset is None or asset.id in seen_ids:
                continue
            seen_ids.add(asset.id)
            labels.append(asset.display_name)
        if labels:
            return labels
        for asset in message.assets:
            if asset.id in seen_ids or self._is_video_contact_sheet(asset):
                continue
            seen_ids.add(asset.id)
            labels.append(asset.display_name)
        return labels

    def _evidence_fact_lines(self, evidence_packet: EvidencePacket) -> list[str]:
        fact_lines: list[str] = []
        for fact in evidence_packet.facts[:4]:
            summary = self._compact(fact.summary)
            if not summary:
                continue
            refs = ", ".join(ref.ref for ref in fact.refs[:2] if ref.ref)
            line = f"{summary} ({refs})" if refs else summary
            fact_lines.append(self._trim(line, 160))
        return fact_lines

    def _select_evidence_memory(
        self,
        *,
        turn_text: str,
        snapshot: ConversationContextSnapshot,
    ) -> GroundedEvidenceMemory | None:
        if not snapshot.recent_evidence_memories:
            return None

        query_tokens = self._meaningful_referent_tokens(turn_text)
        selected_asset_ids = {asset.id for asset in snapshot.selected_context_assets}
        selected_domain = snapshot.selected_context_kind
        best_memory: GroundedEvidenceMemory | None = None
        best_score = -1
        best_signal = -1

        for index, memory in enumerate(snapshot.recent_evidence_memories):
            score = max(0, 12 - index)
            signal = 0
            if selected_domain and memory.domain == selected_domain:
                score += 18
                signal += 18
            overlap = len(selected_asset_ids & set(memory.asset_ids))
            if overlap:
                score += overlap * 60
                signal += overlap * 60
            if (
                snapshot.selected_referent_kind
                and snapshot.selected_referent_kind == memory.domain
            ):
                score += 10
                signal += 10

            memory_tokens = self._meaningful_referent_tokens(
                " ".join(
                    [
                        memory.summary or "",
                        " ".join(memory.fact_lines[:3]),
                        " ".join(memory.asset_labels[:2]),
                    ]
                )
            )
            token_overlap = len(query_tokens & memory_tokens) * 5
            score += token_overlap
            signal += token_overlap

            if best_memory is None or (signal, score) > (best_signal, best_score):
                best_memory = memory
                best_score = score
                best_signal = signal

        if best_signal <= 0:
            return None
        return best_memory

    def _should_mix_attached_assets_with_prior_context(self, turn_text: str) -> bool:
        lowered = turn_text.lower().strip()
        if not lowered:
            return False
        if any(
            phrase in lowered
            for phrase in {
                "compare both",
                "both videos",
                "both images",
                "both documents",
                "different from the first",
                "go back to the first",
                "go back to the earlier",
            }
        ):
            return True
        return any(
            token in lowered
            for token in {
                "first one",
                "second one",
                "earlier one",
                "previous one",
                "both",
                "compare",
                "different from",
            }
        )

    def _recent_topics(self, transcript: list[TranscriptMessage]) -> list[str]:
        topics: list[str] = []
        seen: set[str] = set()
        for message in reversed(transcript):
            if message.role != "user":
                continue
            cleaned = self._topic_text(message.content)
            if not cleaned:
                continue
            normalized = cleaned.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            topics.append(cleaned)
            if len(topics) == 4:
                break
        return topics

    def _topic_text(self, content: str) -> str | None:
        cleaned = self._compact(content)
        if not cleaned:
            return None
        lowered = cleaned.lower().strip("?.! ")
        if lowered in _LOW_SIGNAL_USER_TURNS:
            return None
        if self._looks_like_low_signal_topic_follow_up(lowered):
            return None
        first_line = cleaned.splitlines()[0].strip()
        return self._trim(first_line, 96)

    def _looks_like_low_signal_topic_follow_up(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in _TEACHING_FOLLOW_UP_PHRASES)

    def _last_message_text(self, transcript: list[TranscriptMessage], *, role: str) -> str | None:
        for message in reversed(transcript):
            if message.role != role:
                continue
            cleaned = self._compact(message.content)
            if cleaned:
                return self._trim(cleaned, 160)
        return None

    def _last_agent_summary(self, transcript: list[TranscriptMessage]) -> str | None:
        for message in reversed(transcript):
            if message.role != "assistant":
                continue
            cleaned = self._compact(message.content)
            if not cleaned:
                continue
            if "Files reviewed:" in cleaned or "Key points:" in cleaned or "I reviewed" in cleaned:
                return self._trim(cleaned, 180)
        return None

    def _pending_approval(
        self, transcript: list[TranscriptMessage]
    ) -> tuple[str | None, str | None, str | None, str | None]:
        for message in reversed(transcript):
            approval = message.approval
            if approval is None or approval.status != "pending":
                continue
            summary, excerpt = self.describe_payload(
                approval.payload if isinstance(approval.payload, dict) else None
            )
            return approval.id, approval.tool_name, summary, excerpt
        return None, None, None, None

    def _last_completed_output(
        self, transcript: list[TranscriptMessage]
    ) -> tuple[str | None, str | None, str | None]:
        for message in reversed(transcript):
            approval = message.approval
            if approval is None or approval.status != "executed":
                continue
            title, excerpt = self._approval_referent_details(approval)
            return approval.tool_name, title, excerpt
        return None, None, None

    def _recent_work_products(
        self, transcript: list[TranscriptMessage]
    ) -> list[WorkProductReference]:
        outputs: list[WorkProductReference] = []
        seen_ids: set[str] = set()
        for message in reversed(transcript):
            approval = message.approval
            if approval is None or approval.id in seen_ids:
                continue
            if approval.status not in {"pending", "executed"}:
                continue
            seen_ids.add(approval.id)
            title, excerpt = self._approval_referent_details(approval)
            outputs.append(
                WorkProductReference(
                    kind="pending_output" if approval.status == "pending" else "saved_output",
                    tool_name=approval.tool_name,
                    title=title,
                    excerpt=excerpt,
                    approval_id=approval.id,
                )
            )
            if len(outputs) == 6:
                break
        return outputs

    def _approval_referent_details(self, approval) -> tuple[str | None, str | None]:
        payload = approval.payload if isinstance(approval.payload, dict) else None
        result = approval.result if isinstance(approval.result, dict) else None

        title = None
        if result:
            result_title = result.get("title")
            if isinstance(result_title, str) and result_title.strip():
                title = self._trim(self._compact(result_title), 96)
        if title is None and payload:
            payload_title = payload.get("title")
            if isinstance(payload_title, str) and payload_title.strip():
                title = self._trim(self._compact(payload_title), 96)

        payload_excerpt = self._work_product_excerpt(payload)
        excerpt = self._work_product_excerpt(result)
        if payload_excerpt and (
            excerpt is None
            or (title and excerpt.lower() == title.lower())
            or self._looks_like_output_execution_message(excerpt)
        ):
            excerpt = payload_excerpt
        return title, excerpt

    def _recent_reference_assets_by_kind(
        self, transcript: list[TranscriptMessage], kind: AssetKind
    ) -> list[list[AssetSummary]]:
        preferred = self._recent_assets_by_kind(
            transcript,
            kind,
            roles={"user"},
            skip_contact_sheet=True,
        )
        if preferred:
            return preferred
        fallback = self._recent_assets_by_kind(
            transcript,
            kind,
            roles={"assistant"},
            skip_contact_sheet=True,
        )
        if fallback:
            return fallback
        return self._recent_assets_by_kind(
            transcript,
            kind,
            roles=None,
            skip_contact_sheet=True,
        )

    def _recent_assets_by_kind(
        self,
        transcript: list[TranscriptMessage],
        kind: AssetKind,
        *,
        roles: set[str] | None,
        skip_contact_sheet: bool,
    ) -> list[list[AssetSummary]]:
        groups: list[list[AssetSummary]] = []
        seen_signatures: set[tuple[str, ...]] = set()
        for message in reversed(transcript):
            if roles is not None and message.role not in roles:
                continue
            matching = [
                asset
                for asset in message.assets
                if asset.kind == kind
                and not (skip_contact_sheet and self._is_video_contact_sheet(asset))
            ]
            if matching:
                signature = tuple(asset.id for asset in matching)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                groups.append(matching)
                if len(groups) == 4:
                    break
        return groups

    def _select_context_assets(
        self,
        *,
        turn_text: str,
        transcript: list[TranscriptMessage],
        image_reference_groups: list[list[AssetSummary]],
        video_reference_groups: list[list[AssetSummary]],
        document_reference_groups: list[list[AssetSummary]],
    ) -> tuple[list[AssetSummary], str | None, str | None]:
        lowered = turn_text.lower().strip()
        if not lowered:
            return [], None, None

        if any(token in lowered for token in _VIDEO_REFERENCE_TOKENS) and video_reference_groups:
            selected_video_assets = self._select_referenced_asset_group(
                lowered,
                kind="video",
                groups=video_reference_groups,
            )
            return selected_video_assets, "video", "User referred back to an earlier video."
        if any(token in lowered for token in _IMAGE_REFERENCE_TOKENS) and image_reference_groups:
            selected_image_assets = self._select_referenced_asset_group(
                lowered,
                kind="image",
                groups=image_reference_groups,
            )
            return selected_image_assets, "image", "User referred back to an earlier image."
        if any(token in lowered for token in _DOCUMENT_REFERENCE_TOKENS) and document_reference_groups:
            selected_document_assets = self._select_referenced_asset_group(
                lowered,
                kind="document",
                groups=document_reference_groups,
            )
            return selected_document_assets, "document", "User referred back to an earlier document."

        if self._looks_like_media_follow_up(lowered):
            last_media_assets, last_media_kind = self._last_media_assets(transcript)
            if last_media_assets:
                return (
                    last_media_assets,
                    last_media_kind,
                    "Follow-up appears to continue the most recent media context.",
                )

        return [], None, None

    def _select_referent(
        self,
        *,
        turn_text: str,
        snapshot: ConversationContextSnapshot,
    ) -> tuple[str | None, str | None, str | None, str | None, str | None]:
        lowered = turn_text.lower().strip()
        if not lowered:
            return None, None, None, None, None

        if self._looks_like_work_product_reference(lowered):
            requested_tools = self._requested_work_product_tools(lowered)
            if self._looks_like_multi_output_reference(lowered, requested_tools):
                return None, None, None, None, None
            if requested_tools:
                matched_output = self._match_recent_output(
                    snapshot.recent_outputs,
                    requested_tools=requested_tools,
                    lowered=lowered,
                )
                if matched_output:
                    return (
                        matched_output.kind,
                        matched_output.tool_name,
                        matched_output.title,
                        matched_output.excerpt,
                        f"User referred back to the recent {self._tool_label(matched_output.tool_name)} output.",
                    )
                if snapshot.pending_approval_tool in requested_tools:
                    return (
                        "pending_output",
                        snapshot.pending_approval_tool,
                        snapshot.pending_approval_summary,
                        snapshot.pending_approval_excerpt,
                        "User referred to the current local draft.",
                    )
                if snapshot.last_completed_output_tool in requested_tools:
                    return (
                        "saved_output",
                        snapshot.last_completed_output_tool,
                        snapshot.last_completed_output_title,
                        snapshot.last_completed_output_excerpt,
                        "User referred back to the most recent saved local output.",
                    )
                requested_tool = sorted(requested_tools)[0]
                return (
                    "missing_output",
                    requested_tool,
                    None,
                    None,
                    f"User asked about a {self._tool_label(requested_tool)} that does not exist yet.",
                )
            if snapshot.pending_approval_tool:
                return (
                    "pending_output",
                    snapshot.pending_approval_tool,
                    snapshot.pending_approval_summary,
                    snapshot.pending_approval_excerpt,
                    "User referred to the current local draft.",
                )
            if snapshot.last_completed_output_tool:
                return (
                    "saved_output",
                    snapshot.last_completed_output_tool,
                    snapshot.last_completed_output_title,
                    snapshot.last_completed_output_excerpt,
                    "User referred back to the most recent saved local output.",
                )

        topic_reentry_output = self._match_output_by_topic_reentry(
            snapshot.recent_outputs,
            lowered=lowered,
        )
        if topic_reentry_output is not None:
            return (
                topic_reentry_output.kind,
                topic_reentry_output.tool_name,
                topic_reentry_output.title,
                topic_reentry_output.excerpt,
                f"User referred back to the earlier {self._tool_label(topic_reentry_output.tool_name)} by topic.",
            )

        if snapshot.selected_context_assets:
            title = ", ".join(
                asset.display_name for asset in snapshot.selected_context_assets[:2]
            )
            return (
                snapshot.selected_context_kind,
                None,
                title,
                None,
                snapshot.selected_context_reason,
            )

        if snapshot.active_topic and self._looks_like_topic_reference(lowered):
            return (
                "topic",
                None,
                self._trim(snapshot.active_topic, 96),
                None,
                "User is referring back to the earlier topic.",
            )

        return None, None, None, None, None

    def _requested_work_product_tools(self, lowered: str) -> set[str]:
        requested_tools: set[str] = set()
        if "checklist" in lowered:
            requested_tools.add("create_checklist")
        if "task" in lowered:
            requested_tools.add("create_task")
        if "observation" in lowered:
            requested_tools.add("log_observation")
        if "note" in lowered:
            requested_tools.add("create_note")
        if "report" in lowered:
            requested_tools.add("create_report")
        if any(token in lowered for token in {"message", "reply", "email"}):
            requested_tools.add("create_message_draft")
        if any(token in lowered for token in {"export", "markdown", "document"}):
            requested_tools.add("export_brief")
        return requested_tools

    def _looks_like_multi_output_reference(
        self, lowered: str, requested_tools: set[str]
    ) -> bool:
        if len(requested_tools) < 2:
            return False
        if any(token in lowered for token in {"compare", "both", "all three", "each"}):
            return True
        if " and " in lowered:
            return True
        return any(token in lowered for token in _EARLIER_REFERENCE_TOKENS | _LATEST_REFERENCE_TOKENS)

    def _match_recent_output(
        self,
        recent_outputs: list[WorkProductReference],
        *,
        requested_tools: set[str],
        lowered: str,
    ) -> WorkProductReference | None:
        filtered = [
            output
            for output in recent_outputs
            if not requested_tools or output.tool_name in requested_tools
        ]
        if not filtered:
            return None

        title_match = self._match_output_by_title_tokens(filtered, lowered)
        if title_match is not None:
            return title_match

        ordinal_match = self._match_output_by_ordinal(filtered, lowered)
        if ordinal_match is not None:
            return ordinal_match

        if "first" in lowered or "original" in lowered:
            return filtered[-1]

        if any(token in lowered for token in _EARLIER_REFERENCE_TOKENS):
            return filtered[1] if len(filtered) > 1 else filtered[0]

        if any(token in lowered for token in _LATEST_REFERENCE_TOKENS):
            return filtered[0]

        return filtered[0]

    def _match_output_by_title_tokens(
        self,
        outputs: list[WorkProductReference],
        lowered: str,
    ) -> WorkProductReference | None:
        query_tokens = self._meaningful_referent_tokens(lowered)
        if not query_tokens:
            return None

        best_match: WorkProductReference | None = None
        best_score = 0
        for output in outputs:
            search_tokens = self._meaningful_referent_tokens(
                " ".join(part for part in {output.title or "", output.excerpt or ""} if part)
            )
            if not search_tokens:
                continue
            score = len(query_tokens & search_tokens)
            if score > best_score:
                best_score = score
                best_match = output
        return best_match if best_score > 0 else None

    def _match_output_by_ordinal(
        self,
        outputs: list[WorkProductReference],
        lowered: str,
    ) -> WorkProductReference | None:
        ordered = list(reversed(outputs))
        ordinal_map = {
            "first": 0,
            "1st": 0,
            "second": 1,
            "2nd": 1,
            "third": 2,
            "3rd": 2,
        }
        for token, index in ordinal_map.items():
            if token in lowered and len(ordered) > index:
                return ordered[index]
        return None

    def _match_output_by_topic_reentry(
        self,
        outputs: list[WorkProductReference],
        *,
        lowered: str,
    ) -> WorkProductReference | None:
        if not outputs:
            return None
        if not any(phrase in lowered for phrase in _TOPIC_REFERENCE_PHRASES):
            return None

        query_tokens = self._meaningful_referent_tokens(lowered)
        if not query_tokens:
            return None

        best_match: WorkProductReference | None = None
        best_score = 0
        for output in outputs:
            search_tokens = self._meaningful_referent_tokens(
                " ".join(part for part in {output.title or "", output.excerpt or ""} if part)
            )
            if not search_tokens:
                continue
            score = len(query_tokens & search_tokens)
            if score > best_score:
                best_score = score
                best_match = output
        return best_match if best_score > 0 else None

    def _meaningful_referent_tokens(self, text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if token not in _REFERENT_STOPWORDS and len(token) > 2
        }

    def _tool_label(self, tool_name: str | None) -> str:
        mapping = {
            "create_note": "note",
            "create_report": "report",
            "create_message_draft": "message draft",
            "create_checklist": "checklist",
            "create_task": "task",
            "export_brief": "markdown export",
            "log_observation": "observation",
        }
        if tool_name in mapping:
            return mapping[tool_name]
        if not tool_name:
            return "output"
        return tool_name.replace("_", " ")

    def _last_media_assets(
        self, transcript: list[TranscriptMessage]
    ) -> tuple[list[AssetSummary], str | None]:
        for kind in (AssetKind.VIDEO, AssetKind.IMAGE):
            preferred = self._recent_assets_by_kind(
                transcript,
                kind,
                roles={"user"},
                skip_contact_sheet=True,
            )
            if preferred:
                return preferred[0], "video" if kind == AssetKind.VIDEO else "image"
        for message in reversed(transcript):
            media_assets = [
                asset
                for asset in message.assets
                if asset.kind in {AssetKind.IMAGE, AssetKind.VIDEO}
                and not self._is_video_contact_sheet(asset)
            ]
            if not media_assets:
                continue
            first_kind = media_assets[0].kind
            if first_kind == AssetKind.IMAGE:
                return media_assets, "image"
            if first_kind == AssetKind.VIDEO:
                return media_assets, "video"
        return [], None

    def _looks_like_media_follow_up(self, lowered: str) -> bool:
        if any(cue in lowered for cue in _MEDIA_FOLLOW_UP_CUES):
            return True
        return len(lowered.split()) <= 12 and any(
            lowered.startswith(prefix)
            for prefix in {"what about", "which one", "is that", "is there", "does that", "do those"}
        )

    def _looks_like_work_product_reference(self, lowered: str) -> bool:
        if any(phrase in lowered for phrase in _WORK_PRODUCT_REFERENCE_PHRASES):
            return True
        has_noun = any(token in lowered for token in _WORK_PRODUCT_NOUNS)
        has_edit_intent = any(token in lowered for token in _WORK_PRODUCT_EDIT_TOKENS)
        has_reference_cue = any(token in lowered for token in _WORK_PRODUCT_REFERENCE_CUES)
        has_recall_intent = lowered.startswith(
            ("what was in", "what is in", "what's in", "remind me", "show me")
        )
        return has_noun and (has_recall_intent or (has_edit_intent and has_reference_cue))

    def _looks_like_topic_reference(self, lowered: str) -> bool:
        if any(phrase in lowered for phrase in _TOPIC_REFERENCE_PHRASES):
            return True
        return lowered.startswith(("and what", "so what", "why is that", "how so"))

    def _looks_like_teaching_follow_up(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in _TEACHING_FOLLOW_UP_PHRASES)

    def _is_video_contact_sheet(self, asset: AssetSummary) -> bool:
        lowered_name = asset.display_name.lower().strip()
        lowered_source = asset.source_path.lower().strip()
        lowered_summary = (asset.analysis_summary or "").lower()
        if "contact-sheet" in lowered_name or "contact sheet" in lowered_name:
            return True
        if "contact-sheet" in lowered_source or "contact sheet" in lowered_source:
            return True
        return "contact sheet" in lowered_summary and "video" in lowered_summary

    def _select_referenced_asset_group(
        self,
        lowered: str,
        *,
        kind: str,
        groups: list[list[AssetSummary]],
    ) -> list[AssetSummary]:
        if not groups:
            return []
        if f"both {kind}s" in lowered or f"both {kind}" in lowered:
            combined: list[AssetSummary] = []
            seen_ids: set[str] = set()
            for group in groups[:2]:
                for asset in group:
                    if asset.id in seen_ids:
                        continue
                    seen_ids.add(asset.id)
                    combined.append(asset)
            if combined:
                return combined
        if any(phrase in lowered for phrase in {f"first {kind}", f"original {kind}", f"initial {kind}"}):
            return groups[-1]
        if any(phrase in lowered for phrase in {f"second {kind}", f"newer {kind}"}):
            return groups[0] if len(groups) > 1 else groups[0]
        if any(
            phrase in lowered
            for phrase in {f"earlier {kind}", f"previous {kind}", f"prior {kind}"}
        ) and len(groups) > 1:
            return groups[1]
        if any(phrase in lowered for phrase in {f"latest {kind}", f"last {kind}", f"recent {kind}"}):
            return groups[0]
        return groups[0]

    def _asset_context_summary(
        self,
        *,
        turn_text: str,
        transcript: list[TranscriptMessage],
        assets: list[AssetSummary],
        kind: str,
    ) -> str | None:
        if len(assets) > 1:
            combined_summaries: list[str] = []
            for asset in assets[:2]:
                excerpt = self._assistant_summary_for_single_asset_context(
                    turn_text=turn_text,
                    transcript=transcript,
                    asset=asset,
                )
                if excerpt:
                    combined_summaries.append(f"{asset.display_name}: {excerpt}")
            if combined_summaries:
                return " | ".join(combined_summaries)

        assistant_summary = self._assistant_summary_for_asset_context(
            turn_text=turn_text,
            transcript=transcript,
            assets=assets,
        )
        if assistant_summary:
            return assistant_summary
        for asset in assets:
            if asset.analysis_summary and not self._is_video_contact_sheet(asset):
                return self._trim(self._compact(asset.analysis_summary), 140)
        if assets:
            label = ", ".join(asset.display_name for asset in assets[:2])
            return f"Earlier {kind}: {label}"
        return None

    def _assistant_summary_for_asset_context(
        self,
        *,
        turn_text: str,
        transcript: list[TranscriptMessage],
        assets: list[AssetSummary],
    ) -> str | None:
        if len(assets) == 1:
            return self._assistant_summary_for_single_asset_context(
                turn_text=turn_text,
                transcript=transcript,
                asset=assets[0],
            )
        target_ids = {asset.id for asset in assets}
        anchor_index: int | None = None
        for index, message in enumerate(transcript):
            if any(asset.id in target_ids for asset in message.assets):
                anchor_index = index
        if anchor_index is None:
            return None

        candidates: list[tuple[int, int, str]] = []
        for index in range(anchor_index + 1, len(transcript)):
            follow_up = transcript[index]
            if follow_up.role == "user" and follow_up.assets:
                if not any(asset.id in target_ids for asset in follow_up.assets):
                    break
            if follow_up.role != "assistant":
                continue
            excerpt = self._best_media_context_excerpt(follow_up.content)
            if not excerpt:
                continue
            score = self._asset_context_excerpt_score(excerpt, turn_text=turn_text)
            candidates.append((score, index, excerpt))

        if not candidates:
            return None

        best_score, _, best_excerpt = max(candidates, key=lambda item: (item[0], item[1]))
        if best_score > 0:
            return best_excerpt
        return candidates[0][2]

    def _assistant_summary_for_single_asset_context(
        self,
        *,
        turn_text: str,
        transcript: list[TranscriptMessage],
        asset: AssetSummary,
    ) -> str | None:
        target_ids = {asset.id}
        anchor_index: int | None = None
        for index, message in enumerate(transcript):
            if any(item.id in target_ids for item in message.assets):
                anchor_index = index
        if anchor_index is None:
            return None

        candidates: list[tuple[int, int, str]] = []
        for index in range(anchor_index + 1, len(transcript)):
            follow_up = transcript[index]
            if follow_up.role == "user" and follow_up.assets:
                if not any(item.id in target_ids for item in follow_up.assets):
                    break
            if follow_up.role != "assistant":
                continue
            excerpt = self._best_media_context_excerpt(follow_up.content)
            if not excerpt:
                continue
            score = self._asset_context_excerpt_score(excerpt, turn_text=turn_text)
            candidates.append((score, index, excerpt))

        if not candidates:
            return None

        best_score, _, best_excerpt = max(candidates, key=lambda item: (item[0], item[1]))
        if best_score > 0:
            return best_excerpt
        return candidates[0][2]

    def _asset_context_excerpt_score(self, excerpt: str, *, turn_text: str) -> int:
        lowered_turn = turn_text.lower()
        lowered_excerpt = excerpt.lower()
        score = 0

        query_tokens = self._meaningful_referent_tokens(lowered_turn)
        excerpt_tokens = self._meaningful_referent_tokens(lowered_excerpt)
        score += len(query_tokens & excerpt_tokens) * 3

        if "shortage" in lowered_turn and "shortage" in lowered_excerpt:
            score += 8
        if "departure" in lowered_turn and "departure" in lowered_excerpt:
            score += 3
        if "checklist" in lowered_turn and any(
            token in lowered_excerpt for token in {"low", "top up", "urgent", "restock"}
        ):
            score += 4
        if any(cue in lowered_turn for cue in {"what matters most", "which two", "priority"}):
            if any(token in lowered_excerpt for token in {"shortage", "urgent", "low"}):
                score += 4

        if lowered_excerpt.startswith("here is a conservative description"):
            score -= 2
        if lowered_excerpt.startswith("from the image") and "shortage" not in lowered_excerpt:
            score -= 1
        return score

    def _work_product_excerpt(self, payload: dict[str, object] | None) -> str | None:
        if not payload:
            return None
        title = payload.get("title")
        normalized_title = title if isinstance(title, str) else None
        for key in ("content", "details", "summary", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                excerpt = (
                    self._best_work_product_body_excerpt(value, normalized_title)
                    if key == "content"
                    else self._best_excerpt(value)
                )
                if excerpt:
                    return excerpt
        if isinstance(title, str) and title.strip():
            return self._trim(self._compact(title), 120)
        return None

    def _looks_like_output_execution_message(self, excerpt: str | None) -> bool:
        if not excerpt:
            return False
        lowered = excerpt.lower().strip()
        if not lowered:
            return False
        if lowered.startswith(("exported ", "created ", "saved ", "wrote ")):
            return True
        return "/private/" in lowered or "/exports/" in lowered or "/notes/" in lowered

    def _best_work_product_body_excerpt(
        self,
        text: str,
        title: str | None,
    ) -> str | None:
        title_line = self._compact(title).lower() if title else None
        lines: list[str] = []
        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            cleaned = self._clean_line(raw_line)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if title_line and lowered == title_line:
                continue
            if lowered in _REFERENT_METADATA_PREFIXES or lowered.startswith(tuple(_REFERENT_METADATA_PREFIXES)):
                continue
            if self._looks_like_filename_line(cleaned):
                continue
            lines.append(cleaned)
            if len(lines) == 3:
                break
        if not lines:
            return self._best_excerpt(text)
        compact = " ".join(lines)
        compact = re.sub(r"^key points:\s*", "", compact, flags=re.IGNORECASE)
        return self._trim(compact, 220)

    def _best_excerpt(self, text: str) -> str | None:
        lines: list[str] = []
        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            cleaned = self._clean_line(raw_line)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in _REFERENT_METADATA_PREFIXES or lowered.startswith(tuple(_REFERENT_METADATA_PREFIXES)):
                continue
            if self._looks_like_filename_line(cleaned):
                continue
            lines.append(cleaned)
            if len(lines) == 2:
                break
        if not lines:
            compact = self._compact(text)
            return self._trim(compact, 140) if compact else None
        return self._trim(" ".join(lines), 140)

    def _best_media_context_excerpt(self, text: str) -> str | None:
        lines: list[str] = []
        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            cleaned = self._clean_line(raw_line)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in _REFERENT_METADATA_PREFIXES or lowered.startswith(tuple(_REFERENT_METADATA_PREFIXES)):
                continue
            if self._looks_like_filename_line(cleaned):
                continue
            lines.append(cleaned)
            if len(lines) == 4:
                break
        if not lines:
            compact = self._compact(text)
            return self._trim(compact, 180) if compact else None
        if len(lines) <= 2:
            return self._trim(" ".join(lines), 180)

        first_line = lines[0].lower()
        if any(token in first_line for token in {"shortage", "shortages", "items", "priority", "priorities"}):
            return self._trim(" ".join(lines[:4]), 220)
        return self._trim(" ".join(lines[:2]), 180)

    def _clean_line(self, line: str) -> str:
        cleaned = line.strip()
        if not cleaned:
            return ""
        cleaned = cleaned.lstrip("#").strip()
        cleaned = cleaned.removeprefix("- ").removeprefix("* ").strip()
        cleaned = cleaned.replace("**", "")
        cleaned = cleaned.replace("`", "")
        cleaned = cleaned.replace("[", "").replace("]", "")
        cleaned = cleaned.replace("(", " ").replace(")", " ")
        return self._compact(cleaned)

    def _looks_like_filename_line(self, text: str) -> bool:
        lowered = text.lower().strip()
        if "/" in lowered and " " not in lowered:
            return True
        if lowered.count(".") == 1 and lowered.endswith(
            (".md", ".txt", ".json", ".png", ".jpg", ".jpeg", ".mov", ".mp4")
        ):
            return True
        return False

    def _compact(self, text: str) -> str:
        return " ".join(text.strip().split())

    def _trim(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"
