from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Protocol

from engine.contracts.api import (
    AssistantMode,
    ConversationMemoryEntry,
    ConversationMemoryKind,
    EvidencePacket,
    ExecutionMode,
    GroundingStatus,
    SearchResultItem,
    SourceDomain,
)
from engine.models.sources import resolve_model_source


def _mlx_lm_runtime():
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    return generate, load, make_sampler


@dataclass(slots=True)
class AssistantGenerationRequest:
    conversation_id: str
    turn_id: str
    mode: AssistantMode
    user_text: str
    messages: list[dict[str, str]]
    citations: list[SearchResultItem]
    interaction_kind: str
    is_follow_up: bool
    active_topic: str | None
    conversation_context_summary: str | None
    selected_memory_topic: str | None
    selected_memory_summary: str | None
    memory_focus_kind: str | None
    memory_focus_reason: str | None
    memory_focus_confidence: float | None
    memory_focus_topic_frame: str | None
    memory_focus_clarifying_question: str | None
    turn_adaptation_kind: str | None
    turn_adaptation_reason: str | None
    foreground_anchor_kind: str | None
    foreground_anchor_title: str | None
    referent_kind: str | None
    referent_tool: str | None
    referent_title: str | None
    referent_summary: str | None
    referent_excerpt: str | None
    proposed_tool: str | None
    approval_required: bool
    tool_result: dict[str, object] | None
    assistant_model_name: str
    assistant_model_source: str | None
    specialist_model_name: str | None
    evidence_packet: EvidencePacket | None
    specialist_analysis_text: str | None
    workspace_summary_text: str | None
    max_tokens: int
    temperature: float
    top_p: float


@dataclass(slots=True)
class AssistantGenerationResult:
    text: str
    backend: str
    model_name: str
    model_source: str | None


@dataclass(slots=True)
class ConversationMemoryRequest:
    conversation_id: str
    turn_id: str
    user_text: str
    assistant_text: str
    interaction_kind: str
    active_topic: str | None
    source_domain: SourceDomain | None
    asset_ids: list[str]
    referent_kind: str | None
    referent_title: str | None
    referent_excerpt: str | None
    evidence_packet: EvidencePacket | None
    workspace_summary_text: str | None
    tool_name: str | None


@dataclass(slots=True)
class ConversationMemoryResult:
    topic: str
    summary: str
    keywords: list[str]
    backend: str


@dataclass(slots=True)
class ConversationMemoryRankingRequest:
    user_text: str
    active_topic: str | None
    memories: list[ConversationMemoryEntry]


@dataclass(slots=True)
class ConversationMemoryRankingResult:
    ordered_ids: list[str]
    backend: str


@dataclass(slots=True)
class MemoryFocusRequest:
    user_text: str
    active_topic: str | None
    selected_referent_kind: str | None
    selected_referent_title: str | None
    selected_referent_summary: str | None
    selected_evidence_summary: str | None
    selected_evidence_facts: list[str]
    recent_topics: list[str]
    memories: list[ConversationMemoryEntry]


@dataclass(slots=True)
class MemoryFocusResult:
    primary_anchor_kind: str
    memory_id: str | None
    topic_frame: str | None
    reason: str
    confidence: float
    conflict_note: str | None
    ask_clarifying_question: str | None
    backend: str


class AssistantRuntime(Protocol):
    backend_name: str

    def generate(self, request: AssistantGenerationRequest) -> AssistantGenerationResult: ...

    def synthesize_memory(
        self, request: ConversationMemoryRequest
    ) -> ConversationMemoryResult | None: ...

    def rank_memories(
        self, request: ConversationMemoryRankingRequest
    ) -> ConversationMemoryRankingResult | None: ...

    def resolve_memory_focus(
        self, request: MemoryFocusRequest
    ) -> MemoryFocusResult | None: ...


class MockAssistantRuntime:
    backend_name = "mock"

    def generate(self, request: AssistantGenerationRequest) -> AssistantGenerationResult:
        lines = []
        lowered = request.user_text.lower().strip()
        work_product_reply = self._work_product_follow_up(request, lowered)

        if work_product_reply:
            lines.append(work_product_reply)
        elif request.workspace_summary_text:
            lines.append(self._workspace_response(request.workspace_summary_text))
        elif request.evidence_packet:
            lines.append(self._evidence_response(request.evidence_packet))
        elif request.specialist_analysis_text:
            lines.append(self._specialist_response(request))
        elif request.citations:
            lines.append(self._retrieval_response(request))
        elif request.proposed_tool or request.tool_result:
            pass
        else:
            lines.append(self._general_local_response(request))

        if request.specialist_model_name and not request.specialist_analysis_text and not request.evidence_packet:
            lines.append(f"Selected specialist route: {request.specialist_model_name}.")
            if not request.citations:
                lines.append(
                    "This backend is currently using attachment metadata only, so it cannot make pixel-level claims about the image contents yet."
                )

        if request.tool_result:
            lines.append(self._tool_result_summary(request.tool_result))

        if request.proposed_tool:
            tool_label = self._tool_label(request.proposed_tool)
            if request.approval_required:
                lines.append(self._drafted_work_product_reply(request.proposed_tool))
            elif request.tool_result:
                lines.append(f"I already completed the {tool_label} for this turn.")
            else:
                lines.append(f"I can turn this into a {tool_label} if you want that action.")

        return AssistantGenerationResult(
            text=self._join_sections(lines),
            backend=self.backend_name,
            model_name=request.assistant_model_name,
            model_source=request.assistant_model_source,
        )

    def synthesize_memory(
        self, request: ConversationMemoryRequest
    ) -> ConversationMemoryResult | None:
        return _heuristic_memory_result(request, backend=self.backend_name)

    def rank_memories(
        self, request: ConversationMemoryRankingRequest
    ) -> ConversationMemoryRankingResult | None:
        return _heuristic_memory_ranking(request, backend=self.backend_name)

    def resolve_memory_focus(
        self, request: MemoryFocusRequest
    ) -> MemoryFocusResult | None:
        return _heuristic_memory_focus(request, backend=self.backend_name)

    def _summary_from_sources(self, citations: list[SearchResultItem]) -> str:
        primary = citations[0]
        return f"Most relevant source: [{primary.label}] {primary.excerpt}"

    def _retrieval_response(self, request: AssistantGenerationRequest) -> str:
        lowered = request.user_text.lower().strip()
        primary = self._preferred_retrieval_primary(request.citations, lowered)

        synthesis_reply = self._conversation_synthesis_response(request, lowered)
        if synthesis_reply:
            return synthesis_reply

        direct_reply = self._direct_general_response(request, lowered)
        if direct_reply:
            return direct_reply

        if request.interaction_kind == "teaching":
            topic = self._topic_from_request(request.user_text)
            if self._is_oral_rehydration_topic(topic):
                return self._oral_rehydration_teaching_response(primary.label)
            return (
                f"{self._teaching_intro(topic)} start with the core action from "
                f"[{primary.label}] {primary.excerpt}"
            )

        if request.is_follow_up and any(
            phrase in lowered for phrase in {"what should i emphasize first", "what matters first"}
        ):
            if request.active_topic:
                return (
                    "For what we were just discussing, start with the most practical point from "
                    f"[{primary.label}] {primary.excerpt}"
                )

        if len(request.citations) == 1:
            return f"The strongest local reference here is [{primary.label}] {primary.excerpt}"

        secondary_labels = ", ".join(citation.label for citation in request.citations[1:3])
        return (
            f"The clearest local point here comes from [{primary.label}] {primary.excerpt} "
            f"I also checked {secondary_labels}."
        )

    def _preferred_retrieval_primary(
        self,
        citations: list[SearchResultItem],
        lowered: str,
    ) -> SearchResultItem:
        if not citations:
            raise ValueError("citations must not be empty")
        if not self._looks_like_guidance_request(lowered):
            return citations[0]

        best = citations[0]
        best_score = -10.0
        for index, citation in enumerate(citations):
            score = -index
            label_text = citation.label.lower()
            excerpt_text = citation.excerpt.lower()
            if "guidance" in label_text:
                score += 6
            if "guidance" in excerpt_text:
                score += 2
            if "checklist" in label_text:
                score -= 3
            if "template" in label_text:
                score -= 2
            if "oral rehydration" in excerpt_text:
                score += 2
            if score > best_score:
                best = citation
                best_score = score
        return best

    def _looks_like_guidance_request(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in {
                "teach me",
                "show me how",
                "walk me through",
                "help me understand",
                "explain how",
                "how do i",
                "how to",
                "prepare",
            }
        )

    def _specialist_response(self, request: AssistantGenerationRequest) -> str:
        lowered = request.user_text.lower().strip()
        cleaned = self._clean_specialist_text(request.specialist_analysis_text or "")
        low_items = self._low_items_from_analysis(cleaned)
        if self._looks_like_video_sampling_summary(cleaned):
            if any(
                token in lowered
                for token in {"illegal", "unsafe", "track", "tracking", "monitor", "detect"}
            ):
                return (
                    "I loaded the video locally and sampled a few frames into a contact sheet for review. "
                    "That fallback can help us inspect what is visible frame by frame, but I would avoid stronger claims "
                    "about unsafe or illegal behavior until the local tracking backend is available."
                )
            return (
                "I pulled a few video frames into a local contact sheet and reviewed them. "
                "I can help inspect those sampled frames conservatively, but I cannot do full tracking or behavior inference "
                "from this fallback path alone."
            )

        if any(
            phrase in lowered
            for phrase in {
                "which two shortages",
                "which two items",
                "matter most",
                "prioritize before departure",
                "prioritise before departure",
            }
        ) and len(low_items) >= 2:
            first, second = low_items[:2]
            return (
                f"The two clearest shortages are {first} and {second}. "
                "Those matter most before departure because the local review marks them low and both affect basic field operations."
            )

        if any(
            phrase in lowered
            for phrase in {
                "which shortage mattered most",
                "which shortage matters most",
                "what shortage mattered most",
                "what shortage matters most",
                "what stood out first",
                "which shortage stood out first",
            }
        ) and low_items:
            first = low_items[0]
            return (
                f"The clearest shortage is {first}. "
                "It stands out first because the local review marks it low and frames it like an immediate field-readiness risk."
            )

        if "visible text" in (request.specialist_analysis_text or "").lower():
            if low_items:
                return "From the image, the clearest visible items are: " + "; ".join(
                    f"{item} low" for item in low_items[:3]
                ) + "."
            return f"From the image, I can read: {cleaned}"

        if any(
            token in lowered
            for token in {"review", "video", "clip", "camera", "track", "monitor", "mining"}
        ):
            return cleaned

        if any(token in lowered for token in {"describe", "summarize", "summarise", "inspect"}):
            return f"From the local review, {cleaned[:1].lower() + cleaned[1:]}"

        return cleaned

    def _evidence_response(self, packet: EvidencePacket) -> str:
        if packet.source_domain == SourceDomain.VIDEO:
            if packet.execution_mode == ExecutionMode.UNAVAILABLE:
                return (
                    "I could not run local tracking or sampled-frame review for the video in this profile, "
                    "so I cannot safely make claims about what the clip shows yet."
                )
            lines = ["I took a local look at the video."]
            if packet.execution_mode == ExecutionMode.FALLBACK:
                lines[0] = "I took a local look at sampled video frames."
            if packet.facts:
                lines.append("What stands out:")
                for fact in packet.facts[:3]:
                    refs = ", ".join(ref.ref for ref in fact.refs)
                    suffix = f" ({refs})" if refs else ""
                    lines.append(f"- {fact.summary}{suffix}")
            if packet.uncertainties:
                lines.append("Limits:")
                for item in packet.uncertainties[:2]:
                    lines.append(f"- {item}")
            return "\n".join(lines)

        if packet.source_domain == SourceDomain.DOCUMENT:
            if packet.grounding_status == GroundingStatus.UNAVAILABLE:
                return packet.summary
            lines = ["I pulled out what I could from the document locally."]
            if packet.facts:
                lines.append("Key grounded points:")
                for fact in packet.facts[:4]:
                    refs = ", ".join(ref.ref for ref in fact.refs)
                    suffix = f" ({refs})" if refs else ""
                    lines.append(f"- {fact.summary}{suffix}")
            if packet.uncertainties:
                lines.append("Limits:")
                for item in packet.uncertainties[:2]:
                    lines.append(f"- {item}")
            return "\n".join(lines)

        if packet.source_domain == SourceDomain.IMAGE:
            if packet.grounding_status == GroundingStatus.UNAVAILABLE:
                return packet.summary
            if packet.facts:
                return "From the image, here is what stands out:\n" + "\n".join(
                    f"- {fact.summary}" for fact in packet.facts[:4]
                )
            return packet.summary

        return packet.summary

    def _general_local_response(self, request: AssistantGenerationRequest) -> str:
        lowered = request.user_text.lower().strip()
        work_product_reply = self._work_product_follow_up(request, lowered)
        if work_product_reply:
            return work_product_reply
        if any(token in lowered for token in {"thank you", "thanks", "appreciate it"}):
            return "Of course. I'm here when you want to keep going."
        if self._is_supportive_request(lowered):
            return (
                "Take a breath. You do not need to solve the whole day right this second. "
                "We can slow this down and handle one piece at a time. "
                "If you want, tell me what feels heaviest and we will just work that one part."
            )
        direct_reply = self._direct_general_response(request, lowered)
        if direct_reply:
            return direct_reply
        if self._is_plain_conversation_request(lowered):
            return "Yes. We can just talk this through."
        if self._is_casual_greeting(lowered):
            return self._casual_greeting_response(lowered)
        if request.turn_adaptation_kind == "casual_detour" and request.foreground_anchor_title:
            return (
                f"Sure. We can leave {request.foreground_anchor_title} aside for a second and just talk."
            )
        if request.turn_adaptation_kind == "task_pivot":
            direct_pivot_response = self._task_pivot_direct_response(lowered)
            if direct_pivot_response is not None:
                return direct_pivot_response
            if lowered.endswith("?") or lowered.startswith(("what ", "why ", "how ", "which ")):
                return "Sure. We can focus on that directly."
            return "Sure. We can leave that aside for a minute and focus on this instead."
        if request.is_follow_up:
            prior_topic = request.memory_focus_topic_frame or request.active_topic or self._recent_topic(
                request.messages, request.user_text
            )
            recall_topic = request.selected_memory_topic
            recall_summary = request.selected_memory_summary
            if recall_summary is None:
                fallback_memory = self._recent_memory_from_context_summary(
                    request.conversation_context_summary or "",
                    request.user_text,
                )
                if fallback_memory is not None:
                    recall_topic, recall_summary = fallback_memory
            if not request.selected_memory_summary and any(
                phrase in lowered
                for phrase in {
                    "what was the main point again",
                    "what was the point again",
                    "remind me what we were saying",
                    "what were we saying",
                    "bring that up again",
                    "go back to that",
                    "come back to that",
                    "go deeper on that",
                }
            ):
                fallback_memory = self._recent_memory_from_context_summary(
                    request.conversation_context_summary or "",
                    request.user_text,
                )
                if fallback_memory is not None:
                    recall_topic, recall_summary = fallback_memory
                    if recall_topic:
                        return (
                            f"Yes. Earlier we were talking about {self._memory_topic_for_recall(recall_topic)}. "
                            f"The main point was: {self._memory_summary_for_recall(recall_summary)}"
                        )
                    return (
                        f"Yes. The main point there was: "
                        f"{self._memory_summary_for_recall(recall_summary)}"
                    )
            targeted_teaching_reply = self._grounded_teaching_follow_up(
                lowered,
                recall_summary,
            )
            if targeted_teaching_reply:
                return targeted_teaching_reply
            if (
                request.memory_focus_clarifying_question
                and request.memory_focus_confidence is not None
                and request.memory_focus_confidence < 0.55
                and request.selected_memory_summary is None
            ):
                return request.memory_focus_clarifying_question
            if "what do you mean by that" in lowered:
                if recall_summary:
                    return (
                        "I mean "
                        f"{self._plain_summary_sentence(self._memory_summary_for_recall(recall_summary))}"
                    )
                return (
                    "I mean we can keep this conversational and only get more structured if that would actually help."
                )
            if any(
                phrase in lowered
                for phrase in {
                    "what was the main point again",
                    "what was the point again",
                    "remind me what we were saying",
                    "what were we saying",
                    "bring that up again",
                    "go back to that",
                    "come back to that",
                    "go deeper on that",
                }
            ) and request.selected_memory_summary:
                if recall_topic:
                    return (
                        f"Yes. Earlier we were talking about {self._memory_topic_for_recall(recall_topic)}. "
                        f"The main point was: {self._memory_summary_for_recall(request.selected_memory_summary)}"
                    )
                return (
                    f"Yes. The main point there was: "
                    f"{self._memory_summary_for_recall(request.selected_memory_summary)}"
                )
            if any(phrase in lowered for phrase in {"bring that up again", "go back to that", "come back to that"}):
                if recall_summary:
                    return (
                        "Sure. The main point there was "
                        f"{self._plain_summary_sentence(self._memory_summary_for_recall(recall_summary))}"
                    )
                return "Sure. Let's come back to that."
            if any(phrase in lowered for phrase in {"what should i emphasize first", "what matters first"}):
                return (
                    "Start with the most practical first point: state the goal plainly, show the first action once, and repeat the safety check."
                )
            if self._is_escalation_follow_up(lowered) and self._conversation_mentions(
                request, "oral rehydration"
            ):
                return (
                    "Stop and escalate if you see worsening weakness, confusion, or inability to drink. "
                    "That comes from [ORS guidance]."
                )
            if prior_topic:
                return "Staying with that, I would keep the next step simple and concrete."
            return "I would keep the next step simple and concrete."
        if request.interaction_kind == "teaching":
            topic = self._topic_from_request(request.user_text)
            if self._is_oral_rehydration_topic(topic):
                return self._oral_rehydration_teaching_response()
            return (
                f"{self._teaching_intro(topic)} start with the immediate goal, "
                "break it into a few simple steps, explain the first step plainly, and check understanding before adding detail."
            )
        return "Yes. We can just talk this through."

    def _direct_general_response(
        self, request: AssistantGenerationRequest, lowered: str
    ) -> str | None:
        synthesis_reply = self._conversation_synthesis_response(request, lowered)
        if synthesis_reply:
            return synthesis_reply

        if "local-first" in lowered or "local first" in lowered:
            return (
                "Local-first means the useful parts of the assistant run on this machine before depending on the cloud. "
                "In weak internet, that matters because notes, drafts, attachments, and basic review can keep working even when the connection is slow or gone."
            )

        if self._is_plain_conversation_request(lowered) and any(
            phrase in lowered
            for phrase in {
                "field visit",
                "field work",
                "tomorrow",
                "think through",
                "help me think",
            }
        ):
            return (
                "Yes. We can keep it conversational. Tell me the rough shape of tomorrow first: where you are going, "
                "who you need to support, and what would make the day feel successful."
            )

        if "difference between memory and context" in lowered or (
            "memory" in lowered and "context" in lowered and lowered.startswith(("what", "explain", "how"))
        ):
            return (
                "Sure. Context is the live working set for this turn. "
                "Memory is older distilled state we only bring back when it helps."
            )

        return None

    def _conversation_synthesis_response(
        self, request: AssistantGenerationRequest, lowered: str
    ) -> str | None:
        wants_synthesis = (
            "summarize what you know" in lowered
            or "summarise what you know" in lowered
            or ("what you know" in lowered and ("what you do not know" in lowered or "what you don't know" in lowered))
        )
        wants_next_action = "safest next action" in lowered or "safe next action" in lowered
        if not wants_synthesis:
            return None

        next_action = (
            "Safest next action: verify the critical supplies and plan manually before departure, then use the app for drafts, notes, and conservative review."
            if wants_next_action
            else "Next action: keep the plan conservative and verify anything operational before relying on it."
        )
        return (
            "What I know: you are preparing for field work, you want the app to stay conversational, "
            "and the current local profile can keep a draft/canvas open while you switch topics. "
            "The image path is honest but limited when no local vision model is available; the video path can sample frames and create a contact sheet. "
            "What I do not know: the real site conditions, true supply levels, or whether stronger local vision/tracking models are installed for this run. "
            f"{next_action}"
        )

    def _is_oral_rehydration_topic(self, topic: str) -> bool:
        return "oral rehydration" in topic.lower() or "ors" in topic.lower()

    def _oral_rehydration_teaching_response(self, source_label: str | None = None) -> str:
        source = f" Grounded in [{source_label}]." if source_label else ""
        return (
            "For a new volunteer, keep ORS simple: use clean water, follow the packet or local clinic instructions exactly, "
            "stir until fully dissolved, and label when it was prepared. Offer small frequent sips, and escalate quickly if the person is confused, very weak, cannot drink, or is getting worse."
            f"{source}"
        )

    def _is_escalation_follow_up(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in {
                "what should make me stop",
                "what should make you stop",
                "what should make us stop",
                "what should i watch for",
                "what would make me stop",
                "what would make me escalate",
                "what should make me escalate",
                "stop and escalate",
            }
        )

    def _conversation_mentions(self, request: AssistantGenerationRequest, phrase: str) -> bool:
        lowered_phrase = phrase.lower()
        parts = [
            request.active_topic,
            request.conversation_context_summary,
            request.selected_memory_topic,
            request.selected_memory_summary,
            request.memory_focus_topic_frame,
        ]
        parts.extend(str(message.get("content") or "") for message in request.messages)
        return lowered_phrase in " ".join(part for part in parts if part).lower()

    def _task_pivot_direct_response(self, lowered: str) -> str | None:
        if "memory" in lowered and "context" in lowered:
            return (
                "Sure. Context is the live working set for this turn. "
                "Memory is older distilled state we only bring back when it helps."
            )
        if "tangent" in lowered or "for a second" in lowered:
            topic = self._lightweight_tangent_topic(lowered)
            if topic is not None:
                return f"Sure. We can leave that aside for a minute and talk about {topic}."
            return "Sure. We can leave that aside for a minute. What do you want to talk through?"
        return None

    def _lightweight_tangent_topic(self, lowered: str) -> str | None:
        match = re.search(
            r"(?:tangent|topic|question)\s+about\s+([a-z0-9 ,'\-]+?)(?:\s+for a second|\s+again|[?.!]|$)",
            lowered,
        )
        if match:
            topic = " ".join(match.group(1).split())
            if topic:
                return topic
        return None

    def _work_product_follow_up(
        self, request: AssistantGenerationRequest, lowered: str
    ) -> str | None:
        multi_output_reply = self._multi_output_work_product_follow_up(request, lowered)
        if multi_output_reply:
            return multi_output_reply

        if request.referent_kind not in {"pending_output", "saved_output"}:
            return None

        draft_label = self._tool_label(request.referent_tool or "")
        saved_label = self._saved_output_label(request.referent_tool or "")
        title = request.referent_title or (
            "Untitled draft" if request.referent_kind == "pending_output" else "Untitled output"
        )
        recall_intent = lowered.startswith(
            ("what was in", "what is in", "what's in", "remind me", "show me")
        )
        topic_reentry_intent = any(
            phrase in lowered
            for phrase in {
                "go back to that",
                "bring that up again",
                "come back to that",
                "go deeper on that",
                "what was the main point again",
                "what was the point again",
                "remind me what we were saying",
                "what were we saying",
            }
        )
        title_intent = self._is_work_product_title_query(lowered)

        if title_intent:
            if request.referent_kind == "pending_output":
                return (
                    f'The current {draft_label} is titled "{title}". '
                    "If you want, I can help tighten the title or the body before you save it."
                )
            return f'The latest {saved_label} is titled "{title}".'

        if any(
            phrase in lowered
            for phrase in {
                "make that shorter",
                "shorter",
                "tighten",
                "edit",
                "rename",
                "retitle",
                "revise",
                "rewrite",
            }
        ):
            if request.referent_kind == "pending_output":
                revised_bits = [f'I tightened the current {draft_label}.']
                if title:
                    revised_bits.append(f'It is now titled "{title}".')
                if request.referent_excerpt:
                    revised_bits.append(
                        f"It now centers on: {request.referent_excerpt}"
                    )
                revised_bits.append("It is still waiting for your approval.")
                return " ".join(revised_bits)
            return (
                f'The latest {saved_label} is "{title}". '
                "If you want a revised version, I can prepare an updated draft."
            )

        if any(
            phrase in lowered
            for phrase in {
                "what is in that draft",
                "what's in that draft",
                "what was in that draft",
                "what is in that export",
                "what's in that export",
                "what was in that export",
                "what is in that checklist",
                "what's in that checklist",
                "what was in that checklist",
                "what is in that note",
                "what's in that note",
                "what was in that note",
                "what is in that task",
                "what's in that task",
                "what was in that task",
                "what is in that document",
                "what's in that document",
                "what was in that document",
                "summarize that draft",
                "summarise that draft",
                "summarize that export",
                "summarise that export",
            }
        ) or recall_intent:
            if request.referent_excerpt:
                if request.referent_kind == "pending_output":
                    return (
                        f'The {draft_label} is "{title}". '
                        f"It currently centers on: {request.referent_excerpt}"
                    )
                return (
                    f'The {saved_label} "{title}" centers on: '
                    f"{request.referent_excerpt}"
                )
            return (
                f'The {(draft_label if request.referent_kind == "pending_output" else saved_label)} is "{title}". '
                "I can also summarize it more tightly or prepare a revised version if you want."
            )

        if topic_reentry_intent:
            if request.referent_excerpt:
                cleaned_excerpt = self._memory_summary_for_recall(request.referent_excerpt)
                if request.referent_kind == "pending_output":
                    return (
                        f'Yes. In the current {draft_label} "{title}", the main point is: '
                        f"{cleaned_excerpt}"
                    )
                return (
                    f'Yes. In the {saved_label} "{title}", the main point is: '
                    f"{cleaned_excerpt}"
                )
            if request.referent_kind == "pending_output":
                return (
                    f'Yes. The current {draft_label} is "{title}". '
                    "I can summarize the body more tightly if you want."
                )
            return (
                f'Yes. The latest {saved_label} is "{title}". '
                "I can summarize the body more tightly if you want."
            )

        return None

    def _multi_output_work_product_follow_up(
        self, request: AssistantGenerationRequest, lowered: str
    ) -> str | None:
        mentioned_labels: list[str] = []
        if "report" in lowered:
            mentioned_labels.append("report")
        if "checklist" in lowered:
            mentioned_labels.append("checklist")
        if any(token in lowered for token in {"export", "markdown", "document"}):
            mentioned_labels.append("markdown export")
        if len(set(mentioned_labels)) < 2:
            return None
        if not any(
            token in lowered
            for token in {"what", "again", "called", "title", "summarize", "summarise", "summary"}
        ):
            return None

        outputs = self._recent_outputs_from_summary(request.conversation_context_summary or "")
        if not outputs:
            return None

        by_label = {label: title for label, title in outputs}
        parts: list[str] = []
        if "report" in mentioned_labels:
            if by_label.get("report"):
                parts.append(f'The earlier report was "{by_label["report"]}".')
            else:
                parts.append("There is no current report yet.")
        if "checklist" in mentioned_labels and by_label.get("checklist"):
            parts.append(f'The checklist was "{by_label["checklist"]}".')
        if "markdown export" in mentioned_labels and by_label.get("markdown export"):
            parts.append(f'The newer export was "{by_label["markdown export"]}".')
        if not parts:
            return None
        return " ".join(parts)

    def _is_work_product_title_query(self, lowered: str) -> bool:
        explicit_phrases = {
            "what title are you using",
            "what title is that",
            "what is the draft called",
            "what is that draft called",
            "what is the title now",
            "what is the draft title",
            "what did you call that",
            "what are you calling that",
            "what is that checklist called",
            "what is this checklist called",
            "what is the checklist called",
            "what is that report called",
            "what is this report called",
            "what is the report called",
            "what is that export called",
            "what is this export called",
            "what is the export called",
            "what's the export title now",
            "what is the export title now",
            "what's the checklist title now",
            "what is the checklist title now",
        }
        if any(phrase in lowered for phrase in explicit_phrases):
            return True

        has_reference = any(token in lowered for token in {"that", "this", "the", "current", "latest", "newer"})
        has_output = any(
            token in lowered
            for token in {"draft", "checklist", "report", "export", "note", "task", "message", "email", "document"}
        )
        has_title_word = any(token in lowered for token in {"title", "called", "name", "named"})
        return has_reference and has_output and has_title_word

    def _recent_outputs_from_summary(self, summary: str) -> list[tuple[str, str]]:
        if not summary:
            return []
        return re.findall(
            r'(report|checklist|markdown export|message draft|note|task)\s+"([^"]+)"',
            summary,
            flags=re.IGNORECASE,
        )

    def _recent_memory_from_context_summary(
        self,
        summary: str,
        user_text: str,
    ) -> tuple[str | None, str] | None:
        if not summary:
            return None
        selected_match = re.search(r"Selected conversation memory:\s*(.+)", summary)
        candidates: list[tuple[str | None, str]] = []
        if selected_match:
            parsed = self._parse_memory_label(selected_match.group(1).strip())
            if parsed is not None:
                candidates.append(parsed)
        recent_match = re.search(r"Recent conversation memories:\s*(.+)", summary)
        if recent_match:
            for chunk in recent_match.group(1).split(" ; "):
                parsed = self._parse_memory_label(chunk.strip())
                if parsed is not None:
                    candidates.append(parsed)
        if not candidates:
            return None

        query_tokens = _ranking_tokens(user_text)
        best_candidate: tuple[str | None, str] | None = None
        best_score = 0
        for index, candidate in enumerate(candidates):
            topic, memory_summary = candidate
            searchable = " ".join(part for part in [topic or "", memory_summary] if part)
            score = len(query_tokens & _ranking_tokens(searchable)) * 8
            score += max(0, 4 - index)
            if score > best_score:
                best_score = score
                best_candidate = candidate
        return best_candidate if best_score > 0 else candidates[0]

    def _parse_memory_label(self, text: str) -> tuple[str | None, str] | None:
        if not text:
            return None
        if ":" not in text:
            return None
        topic, summary = text.split(":", 1)
        cleaned_topic = topic.strip() or None
        cleaned_summary = summary.strip()
        if not cleaned_summary:
            return None
        return cleaned_topic, cleaned_summary

    def _workspace_response(self, text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""
        paragraphs = [
            paragraph.strip() for paragraph in re.split(r"\n\s*\n", cleaned) if paragraph.strip()
        ]
        if not paragraphs:
            return cleaned

        remaining = paragraphs
        if paragraphs[0].lower().startswith("i reviewed "):
            remaining = paragraphs[1:] or paragraphs

        if remaining and remaining[0].lower().startswith("key points:"):
            return "Here is a concise briefing:\n\n" + "\n\n".join(remaining)

        return "\n\n".join(remaining)

    def _memory_summary_for_recall(self, summary: str) -> str:
        cleaned = " ".join(summary.split())
        cleaned = re.sub(
            r"^Here is a practical way to (?:approach )?[^:]+:\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned

    def _grounded_teaching_follow_up(self, lowered: str, summary: str | None) -> str | None:
        if not summary:
            return None
        if not any(
            phrase in lowered
            for phrase in {
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
            return None

        cleaned = self._memory_summary_for_recall(summary)
        source_label = self._summary_source_label(cleaned)
        body = self._teaching_body_from_summary(cleaned)
        first_action = self._teaching_first_action(body)
        warning = self._teaching_warning(body)

        if any(
            phrase in lowered
            for phrase in {
                "what should make me stop",
                "what should make you stop",
                "what should make us stop",
                "what should i watch for",
                "what would make me stop",
                "what would make me escalate",
                "what should make me escalate",
            }
        ) and warning:
            source = f" That comes from [{source_label}]." if source_label else ""
            return f"Stop and escalate if you see {warning}.{source}"

        if any(
            phrase in lowered
            for phrase in {
                "what's the first action again",
                "what is the first action again",
                "first action again",
            }
        ) and first_action:
            source = f" That first step comes from [{source_label}]." if source_label else ""
            return f"First, {first_action}.{source}"

        if any(
            phrase in lowered
            for phrase in {
                "one sentence",
                "say that plainly",
                "say that simply",
                "put it plainly",
            }
        ) and body:
            if source_label:
                return f"In one sentence: {body} Grounded in [{source_label}]."
            return f"In one sentence: {body}"
        return None

    def _memory_topic_for_recall(self, topic: str) -> str:
        cleaned = topic.strip().rstrip(".")
        lowered = cleaned.lower()
        if lowered.startswith("how to "):
            return cleaned
        if lowered.startswith(
            (
                "prepare ",
                "build ",
                "create ",
                "write ",
                "review ",
                "compare ",
                "pack ",
                "run ",
                "manage ",
                "set ",
                "organize ",
                "organise ",
                "draft ",
                "explain ",
                "analyze ",
                "analyse ",
            )
        ):
            return f"how to {cleaned}"
        return cleaned

    def _summary_source_label(self, summary: str) -> str | None:
        match = re.search(r"\[([^\]]+)\]", summary)
        if not match:
            return None
        return match.group(1).strip() or None

    def _teaching_body_from_summary(self, summary: str) -> str:
        body = summary
        if ":" in body:
            body = body.split(":", 1)[1].strip()
        body = re.sub(r"\s+", " ", body).strip()
        if body.endswith("."):
            return body
        return body

    def _teaching_first_action(self, body: str) -> str | None:
        if not body:
            return None
        primary = re.split(r"\.\s+|Watch for ", body, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        return primary.rstrip(".") or None

    def _teaching_warning(self, body: str) -> str | None:
        if not body:
            return None
        match = re.search(r"Watch for ([^.]+)", body, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip().rstrip(".")

    def _teaching_intro(self, topic: str) -> str:
        first = topic.strip().split(" ", 1)[0].lower() if topic.strip() else ""
        if first in {
            "prepare",
            "build",
            "create",
            "write",
            "review",
            "compare",
            "explain",
            "pack",
            "run",
            "manage",
            "set",
            "organize",
            "draft",
        }:
            return f"A practical way to {topic} is to"
        return f"A practical way to approach {topic} is to"

    def _join_sections(self, sections: list[str]) -> str:
        cleaned = [section.strip() for section in sections if section and section.strip()]
        if not cleaned:
            return ""
        if any("\n" in section for section in cleaned):
            return "\n\n".join(cleaned)
        return " ".join(cleaned)

    def _tool_result_summary(self, result: dict[str, object]) -> str:
        message = str(result.get("message") or "").strip()
        if message:
            return message
        title = str(result.get("title") or "").strip()
        if title:
            return f"Completed tool result: {title}."
        return "A local tool completed successfully for this turn."

    def _tool_label(self, tool_name: str) -> str:
        mapping = {
            "create_note": "note draft",
            "create_report": "report draft",
            "create_message_draft": "message draft",
            "create_checklist": "checklist draft",
            "create_task": "task draft",
            "log_observation": "saved observation",
            "export_brief": "markdown export draft",
            "generate_heatmap_overlay": "heatmap overlay",
        }
        return mapping.get(tool_name, tool_name.replace("_", " "))

    def _drafted_work_product_reply(self, tool_name: str) -> str:
        mapping = {
            "create_note": "I drafted a note here.",
            "create_report": "I drafted a report here.",
            "create_message_draft": "I drafted a message here.",
            "create_checklist": "I drafted a checklist here.",
            "create_task": "I drafted a task here.",
            "log_observation": "I drafted an observation here.",
            "export_brief": "I drafted an export here.",
            "generate_heatmap_overlay": "I prepared a heatmap overlay draft here.",
        }
        return mapping.get(tool_name, f"I drafted a {self._tool_label(tool_name)} here.")

    def _saved_output_label(self, tool_name: str) -> str:
        mapping = {
            "create_note": "note",
            "create_report": "report",
            "create_message_draft": "message draft",
            "create_checklist": "checklist",
            "create_task": "task",
            "log_observation": "saved observation",
            "export_brief": "export",
            "generate_heatmap_overlay": "heatmap overlay",
        }
        return mapping.get(tool_name, tool_name.replace("_", " "))

    def _tighter_title(self, title: str) -> str | None:
        lowered = title.lower()
        replacements = (
            ("current ", ""),
            ("relevant ", ""),
            ("workspace ", ""),
            ("architecture overview", "architecture brief"),
            ("briefing", "brief"),
        )
        revised = title
        for old, new in replacements:
            revised = re.sub(old, new, revised, flags=re.IGNORECASE)
        revised = re.sub(r"\s{2,}", " ", revised).strip(" -")
        if not revised:
            return None
        if revised.lower() == lowered:
            return None
        return revised

    def _clean_specialist_text(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = cleaned.removeprefix("Visible text extracted from the image:\n")
        cleaned = cleaned.removeprefix("Visible text extracted from the medical image:\n")
        cleaned = cleaned.strip()
        return cleaned

    def _low_items_from_analysis(self, cleaned_text: str) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()

        for line in cleaned_text.splitlines():
            stripped = line.strip().rstrip(".")
            if not stripped:
                continue
            lowered = stripped.lower()
            if lowered.endswith(" low"):
                item = stripped[:-4].strip()
                normalized = item.lower()
                if item and normalized not in seen:
                    seen.add(normalized)
                    items.append(item)

        if items:
            return items

        lowered = cleaned_text.lower()
        if "marked low" in lowered and " and " in lowered:
            prefix = cleaned_text.split("marked low", 1)[0]
            if "shows " in prefix.lower():
                prefix = prefix.split("shows ", 1)[1]
            for chunk in prefix.split(" and "):
                item = chunk.strip(" ,.")
                normalized = item.lower()
                if item and normalized not in seen:
                    seen.add(normalized)
                    items.append(item)
        return items

    def _looks_like_video_sampling_summary(self, cleaned_text: str) -> bool:
        lowered = cleaned_text.lower()
        return lowered.startswith("video loaded locally:") and "contact sheet" in lowered

    def _recent_topic(self, messages: list[dict[str, str]], current_user_text: str) -> str | None:
        current = current_user_text.strip().lower().rstrip("?.! ")
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            text = str(message.get("content") or "").strip()
            if text.startswith("User request:"):
                topic = text.removeprefix("User request:").strip().splitlines()[0]
            else:
                topic = text.splitlines()[0]
            topic = topic.rstrip("?.! ")
            if topic and topic.strip().lower() != current:
                return topic[:72]
        return None

    def _topic_from_request(self, text: str) -> str:
        cleaned = _normalized_memory_topic_text(text)
        return cleaned or "this"

    def _is_plain_conversation_request(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in {
                "talk normally",
                "just talk",
                "just chat",
                "chat normally",
                "think out loud",
                "keep this conversational",
            }
        )

    def _is_casual_greeting(self, lowered: str) -> bool:
        return bool(
            lowered == "how are you"
            or re.match(r"^(hi|hello|hey|yo|yoo|sup|what's up|whats up)\b", lowered)
        )

    def _casual_greeting_response(self, lowered: str) -> str:
        if lowered == "how are you":
            return "I'm doing well. What's on your mind?"
        if lowered.startswith(("yo", "yoo", "sup", "what's up", "whats up")):
            return "Hey. What's up?"
        return "Hey. What's on your mind?"

    def _plain_summary_sentence(self, summary: str) -> str:
        cleaned = " ".join(summary.split()).strip()
        if not cleaned:
            return "we can keep this simple."
        normalized = cleaned[0].lower() + cleaned[1:] if len(cleaned) > 1 else cleaned.lower()
        if normalized.endswith("."):
            return normalized
        return normalized + "."

    def _is_supportive_request(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in {
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
        )


class MLXAssistantRuntime:
    backend_name = "mlx"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[object, object]] = {}

    def generate(self, request: AssistantGenerationRequest) -> AssistantGenerationResult:
        resolved_source = resolve_model_source(
            request.assistant_model_source,
            request.assistant_model_name,
        )
        if not resolved_source:
            raise RuntimeError(
                "No assistant model source is configured. Set "
                "FIELD_ASSISTANT_ASSISTANT_MODEL_SOURCE or provide a locally cached "
                "Gemma model before using the MLX backend."
            )

        model, tokenizer = self._load_model(resolved_source)
        prompt = self._build_prompt(tokenizer, request.messages)
        generate, _, make_sampler = _mlx_lm_runtime()
        sampler = make_sampler(temp=request.temperature, top_p=request.top_p)
        text = generate(
            model,
            tokenizer,
            prompt,
            verbose=False,
            max_tokens=request.max_tokens,
            sampler=sampler,
        ).strip()

        return AssistantGenerationResult(
            text=text,
            backend=self.backend_name,
            model_name=request.assistant_model_name,
            model_source=resolved_source,
        )

    def synthesize_memory(
        self, request: ConversationMemoryRequest
    ) -> ConversationMemoryResult | None:
        heuristic = _heuristic_memory_result(request, backend=self.backend_name)
        if heuristic is None:
            return None

        messages = [
            {
                "role": "system",
                "content": (
                    "You compress a single assistant turn into a bounded continuity memory. "
                    "Return strict JSON with keys topic, summary, keywords. "
                    "The summary must stay factual, concise, and grounded in the provided turn only. "
                    "Do not invent new details, advice, or citations."
                ),
            },
            {
                "role": "user",
                "content": "\n".join(
                    [
                        f"user_text={request.user_text}",
                        f"assistant_text={request.assistant_text}",
                        f"interaction_kind={request.interaction_kind}",
                        f"active_topic={request.active_topic or ''}",
                        f"source_domain={request.source_domain.value if request.source_domain else ''}",
                        f"referent_title={request.referent_title or ''}",
                        f"heuristic_topic={heuristic.topic}",
                        f"heuristic_summary={heuristic.summary}",
                        "Return JSON only.",
                    ]
                ),
            },
        ]
        try:
            model_source = next(iter(self._cache), None)
            if model_source is None:
                return heuristic
            model, tokenizer = self._load_model(model_source)
            prompt = self._build_prompt(tokenizer, messages)
            generate, _, make_sampler = _mlx_lm_runtime()
            sampler = make_sampler(temp=0.1, top_p=0.9)
            text = generate(
                model,
                tokenizer,
                prompt,
                verbose=False,
                max_tokens=140,
                sampler=sampler,
            ).strip()
            parsed = _parse_memory_json(text)
            if parsed is None:
                return heuristic
            return ConversationMemoryResult(
                topic=parsed.topic or heuristic.topic,
                summary=parsed.summary or heuristic.summary,
                keywords=parsed.keywords or heuristic.keywords,
                backend=self.backend_name,
            )
        except Exception:
            return heuristic

    def rank_memories(
        self, request: ConversationMemoryRankingRequest
    ) -> ConversationMemoryRankingResult | None:
        heuristic = _heuristic_memory_ranking(request, backend=self.backend_name)
        if heuristic is None or not heuristic.ordered_ids:
            return heuristic

        memory_lines = []
        for memory in request.memories[:6]:
            memory_lines.append(
                "\n".join(
                    [
                        f"id={memory.id}",
                        f"topic={memory.topic}",
                        f"summary={memory.summary}",
                        f"keywords={','.join(memory.keywords[:8])}",
                        f"source_domain={memory.source_domain.value if memory.source_domain else ''}",
                        f"referent_title={memory.referent_title or ''}",
                    ]
                )
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "You rerank a bounded set of conversation memories for one new user turn. "
                    "Return strict JSON with key ordered_ids containing memory ids in best-first order. "
                    "Prefer memories whose topic or summary best match the current request. "
                    "Do not invent ids. Keep stronger explicit referents and grounded evidence out of scope; this ranking is only for topic-level continuity."
                ),
            },
            {
                "role": "user",
                "content": "\n\n".join(
                    [
                        f"user_text={request.user_text}",
                        f"active_topic={request.active_topic or ''}",
                        "candidate_memories:",
                        *memory_lines,
                        f"heuristic_order={','.join(heuristic.ordered_ids)}",
                        "Return JSON only.",
                    ]
                ),
            },
        ]
        try:
            model_source = next(iter(self._cache), None)
            if model_source is None:
                return heuristic
            model, tokenizer = self._load_model(model_source)
            prompt = self._build_prompt(tokenizer, messages)
            generate, _, make_sampler = _mlx_lm_runtime()
            sampler = make_sampler(temp=0.1, top_p=0.9)
            text = generate(
                model,
                tokenizer,
                prompt,
                verbose=False,
                max_tokens=120,
                sampler=sampler,
            ).strip()
            parsed = _parse_memory_ranking_json(text, request.memories)
            if parsed is None or not parsed.ordered_ids:
                return heuristic
            return ConversationMemoryRankingResult(
                ordered_ids=parsed.ordered_ids,
                backend=self.backend_name,
            )
        except Exception:
            return heuristic

    def resolve_memory_focus(
        self, request: MemoryFocusRequest
    ) -> MemoryFocusResult | None:
        heuristic = _heuristic_memory_focus(request, backend=self.backend_name)
        if heuristic is None:
            return None
        if not request.memories:
            return heuristic

        memory_lines = []
        for memory in request.memories[:6]:
            memory_lines.append(
                "\n".join(
                    [
                        f"id={memory.id}",
                        f"kind={memory.kind.value}",
                        f"topic={memory.topic}",
                        f"summary={memory.summary}",
                        f"keywords={','.join(memory.keywords[:8])}",
                        f"source_domain={memory.source_domain.value if memory.source_domain else ''}",
                    ]
                )
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "You choose the strongest bounded continuity anchor for one new user turn. "
                    "Return strict JSON with keys primary_anchor_kind, memory_id, topic_frame, reason, confidence, conflict_note, ask_clarifying_question. "
                    "Valid primary_anchor_kind values are conversation_memory, topic, none. "
                    "Do not invent ids. Keep explicit referents and grounded evidence out of scope because they already override memory."
                ),
            },
            {
                "role": "user",
                "content": "\n\n".join(
                    [
                        f"user_text={request.user_text}",
                        f"active_topic={request.active_topic or ''}",
                        f"selected_referent_kind={request.selected_referent_kind or ''}",
                        f"selected_referent_title={request.selected_referent_title or ''}",
                        f"selected_evidence_summary={request.selected_evidence_summary or ''}",
                        "candidate_memories:",
                        *memory_lines,
                        (
                            "heuristic="
                            + ",".join(
                                [
                                    f"kind={heuristic.primary_anchor_kind}",
                                    f"memory_id={heuristic.memory_id or ''}",
                                    f"topic_frame={heuristic.topic_frame or ''}",
                                    f"confidence={heuristic.confidence:.2f}",
                                ]
                            )
                        ),
                        "Return JSON only.",
                    ]
                ),
            },
        ]
        try:
            model_source = next(iter(self._cache), None)
            if model_source is None:
                return heuristic
            model, tokenizer = self._load_model(model_source)
            prompt = self._build_prompt(tokenizer, messages)
            generate, _, make_sampler = _mlx_lm_runtime()
            sampler = make_sampler(temp=0.1, top_p=0.9)
            text = generate(
                model,
                tokenizer,
                prompt,
                verbose=False,
                max_tokens=140,
                sampler=sampler,
            ).strip()
            parsed = _parse_memory_focus_json(text, request.memories)
            if parsed is None:
                return heuristic
            return parsed
        except Exception:
            return heuristic

    def _load_model(self, source: str) -> tuple[object, object]:
        with self._lock:
            cached = self._cache.get(source)
            if cached is not None:
                return cached
            _, load, _ = _mlx_lm_runtime()
            model, tokenizer = load(source)
            self._cache[source] = (model, tokenizer)
            return model, tokenizer

    def _build_prompt(self, tokenizer: object, messages: list[dict[str, str]]) -> str:
        if hasattr(tokenizer, "apply_chat_template"):
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )

        parts = []
        for message in messages:
            parts.append(f"{message['role'].upper()}:\n{message['content']}")
        parts.append("ASSISTANT:\n")
        return "\n\n".join(parts)


def _heuristic_memory_result(
    request: ConversationMemoryRequest,
    *,
    backend: str,
) -> ConversationMemoryResult | None:
    topic = _memory_topic(request)
    summary = _memory_summary(request)
    if not topic or not summary:
        return None
    return ConversationMemoryResult(
        topic=topic,
        summary=summary,
        keywords=_memory_keywords(request, topic, summary),
        backend=backend,
    )


def _heuristic_memory_ranking(
    request: ConversationMemoryRankingRequest,
    *,
    backend: str,
) -> ConversationMemoryRankingResult | None:
    if not request.memories:
        return None
    query_tokens = _ranking_tokens(request.user_text)
    active_topic_tokens = _ranking_tokens(request.active_topic or "")
    teaching_follow_up = _looks_like_teaching_follow_up_request(request.user_text.lower())
    if not query_tokens and request.active_topic:
        query_tokens = _ranking_tokens(request.active_topic)
    scored: list[tuple[int, int, str]] = []
    for index, memory in enumerate(request.memories):
        searchable = " ".join(
            [
                memory.topic,
                memory.summary,
                " ".join(memory.keywords),
                memory.referent_title or "",
            ]
        )
        memory_tokens = _ranking_tokens(searchable)
        score = max(0, 24 - index * 2)
        score += len(query_tokens & memory_tokens) * 8
        if memory.referent_title and memory.referent_title.lower() in request.user_text.lower():
            score += 12
        if memory.topic and memory.topic.lower() in request.user_text.lower():
            score += 16
        if teaching_follow_up and memory.kind == ConversationMemoryKind.TEACHING:
            score += 12
            overlap = len(active_topic_tokens & memory_tokens)
            if overlap:
                score += 8 + (overlap * 4)
        if (
            request.active_topic
            and memory.topic.lower() == request.active_topic.lower()
            and len(query_tokens) <= 1
        ):
            score += 10
        scored.append((score, index, memory.id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return ConversationMemoryRankingResult(
        ordered_ids=[memory_id for _, _, memory_id in scored],
        backend=backend,
    )


def _heuristic_memory_focus(
    request: MemoryFocusRequest,
    *,
    backend: str,
) -> MemoryFocusResult | None:
    if request.selected_referent_kind in {"pending_output", "saved_output"}:
        topic_frame = request.selected_referent_title or request.selected_referent_summary
        return MemoryFocusResult(
            primary_anchor_kind="referent",
            memory_id=None,
            topic_frame=topic_frame,
            reason="An explicit current work-product referent is already selected.",
            confidence=1.0,
            conflict_note=None,
            ask_clarifying_question=None,
            backend=backend,
        )
    if request.selected_evidence_summary and (
        request.selected_referent_kind in {"image", "video", "document"}
        or request.selected_referent_kind is None
    ):
        return MemoryFocusResult(
            primary_anchor_kind="grounded_evidence",
            memory_id=None,
            topic_frame=request.selected_referent_title or request.active_topic,
            reason="Grounded evidence is already selected for this turn and should outrank memory.",
            confidence=0.98,
            conflict_note=None,
            ask_clarifying_question=None,
            backend=backend,
        )
    if not request.memories:
        if request.active_topic:
            return MemoryFocusResult(
                primary_anchor_kind="topic",
                memory_id=None,
                topic_frame=request.active_topic,
                reason="No bounded memory candidate is available, so the active topic is the best continuity anchor.",
                confidence=0.46,
                conflict_note=None,
                ask_clarifying_question=None,
                backend=backend,
            )
        return MemoryFocusResult(
            primary_anchor_kind="none",
            memory_id=None,
            topic_frame=None,
            reason="No suitable memory anchor is available for this turn.",
            confidence=0.0,
            conflict_note=None,
            ask_clarifying_question=None,
            backend=backend,
        )

    lowered = request.user_text.lower().strip()
    query_tokens = _ranking_tokens(request.user_text)
    active_topic_tokens = _ranking_tokens(request.active_topic or "")
    recent_topic_tokens = _ranking_tokens(" ".join(request.recent_topics[:3]))
    teaching_follow_up = _looks_like_teaching_follow_up_request(lowered)
    generic_follow_up = _is_generic_memory_follow_up(lowered)
    scored: list[tuple[float, int, ConversationMemoryEntry]] = []
    for index, memory in enumerate(request.memories):
        searchable = " ".join(
            [
                memory.topic,
                memory.summary,
                " ".join(memory.keywords),
                memory.referent_title or "",
            ]
        )
        memory_tokens = _ranking_tokens(searchable)
        score = max(0.0, 24.0 - index * 2.0)
        score += len(query_tokens & memory_tokens) * 8.0
        score += len(active_topic_tokens & memory_tokens) * 5.0
        score += len(recent_topic_tokens & memory_tokens) * 2.0
        if memory.referent_title and memory.referent_title.lower() in lowered:
            score += 12.0
        if memory.topic and memory.topic.lower() in lowered:
            score += 16.0
        if teaching_follow_up and memory.kind == ConversationMemoryKind.TEACHING:
            score += 12.0
            score += len(active_topic_tokens & _ranking_tokens(memory.topic)) * 4.0
        if generic_follow_up and memory.kind in {
            ConversationMemoryKind.GENERAL,
            ConversationMemoryKind.TEACHING,
            ConversationMemoryKind.WORKSPACE,
        }:
            score += 5.0
        scored.append((score, index, memory))

    scored.sort(key=lambda item: (-item[0], item[1]))
    best_score, _, best_memory = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None
    confidence = min(0.98, 0.25 + (best_score / 60.0))
    conflict_note = None
    ask_clarifying_question = None
    if (
        runner_up is not None
        and best_score > 0
        and abs(best_score - runner_up[0]) <= 6
        and runner_up[2].topic.lower() != best_memory.topic.lower()
    ):
        conflict_note = (
            f'Two continuity candidates remain close: "{best_memory.topic}" and "{runner_up[2].topic}".'
        )
        if confidence < 0.62:
            ask_clarifying_question = (
                f'Do you mean "{best_memory.topic}" or "{runner_up[2].topic}"?'
            )

    if best_score <= 6 and request.active_topic:
        return MemoryFocusResult(
            primary_anchor_kind="topic",
            memory_id=None,
            topic_frame=request.active_topic,
            reason="The active topic is stronger than the available bounded memory candidates for this turn.",
            confidence=max(0.4, confidence - 0.1),
            conflict_note=conflict_note,
            ask_clarifying_question=ask_clarifying_question,
            backend=backend,
        )

    return MemoryFocusResult(
        primary_anchor_kind="conversation_memory",
        memory_id=best_memory.id,
        topic_frame=best_memory.topic,
        reason=f'The best bounded continuity anchor for this turn is "{best_memory.topic}".',
        confidence=confidence,
        conflict_note=conflict_note,
        ask_clarifying_question=ask_clarifying_question,
        backend=backend,
    )


def _memory_topic(request: ConversationMemoryRequest) -> str | None:
    if request.referent_title:
        return _trim_memory_text(request.referent_title, 96)
    cleaned = _normalized_memory_topic_text(request.user_text)
    lowered = cleaned.lower()
    if cleaned and not _is_generic_memory_follow_up(lowered):
        return _trim_memory_text(cleaned, 96)
    if request.active_topic:
        return _trim_memory_text(_normalized_memory_topic_text(request.active_topic), 96)
    return _trim_memory_text(cleaned, 96) if cleaned else None


def _memory_summary(request: ConversationMemoryRequest) -> str | None:
    if request.tool_name and request.referent_title:
        label = _tool_memory_label(request.tool_name)
        if request.referent_excerpt:
            grounded = _trim_memory_text(request.referent_excerpt.strip(), 140)
            return _trim_memory_text(
                f'{label.title()} "{request.referent_title}" centers on: {grounded}',
                180,
            )
        if request.evidence_packet and request.evidence_packet.summary.strip():
            grounded = _trim_memory_text(request.evidence_packet.summary.strip(), 140)
            return _trim_memory_text(
                f'{label.title()} "{request.referent_title}" centers on: {grounded}',
                180,
            )
        if request.workspace_summary_text:
            cleaned_workspace = _workspace_memory_summary(request.workspace_summary_text)
            grounded = _trim_memory_text(cleaned_workspace, 140)
            return _trim_memory_text(
                f'{label.title()} "{request.referent_title}" centers on: {grounded}',
                180,
            )
        assistant_excerpt = _assistant_output_memory_excerpt(request.assistant_text)
        if assistant_excerpt:
            grounded = _trim_memory_text(assistant_excerpt, 140)
            return _trim_memory_text(
                f'{label.title()} "{request.referent_title}" centers on: {grounded}',
                180,
            )
        return _trim_memory_text(
            f'{label.title()} "{request.referent_title}" is the current work product for this thread.',
            180,
        )
    if request.evidence_packet and request.evidence_packet.summary.strip():
        return _trim_memory_text(request.evidence_packet.summary.strip(), 220)
    if request.workspace_summary_text:
        cleaned_workspace = request.workspace_summary_text.strip().split("\n\n")[0]
        return _trim_memory_text(cleaned_workspace, 220)
    cleaned = _normalized_stored_memory_summary(request.assistant_text)
    return _trim_memory_text(cleaned, 360) if cleaned else None


def _memory_keywords(
    request: ConversationMemoryRequest,
    topic: str,
    summary: str,
) -> list[str]:
    stop_words = {
        "the",
        "and",
        "that",
        "this",
        "with",
        "from",
        "what",
        "when",
        "where",
        "which",
        "have",
        "your",
        "about",
        "into",
        "just",
    }
    seen: set[str] = set()
    keywords: list[str] = []
    for token in re.findall(r"[a-z0-9]+", " ".join([request.user_text, topic, summary]).lower()):
        if len(token) < 4 or token in stop_words or token in seen:
            continue
        seen.add(token)
        keywords.append(token)
        if len(keywords) == 8:
            break
    return keywords


def _ranking_tokens(text: str) -> set[str]:
    stop_words = {
        "the",
        "and",
        "that",
        "this",
        "with",
        "from",
        "what",
        "when",
        "where",
        "which",
        "have",
        "your",
        "about",
        "into",
        "just",
        "again",
        "back",
        "point",
        "topic",
        "please",
        "really",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in stop_words
    }


def _tool_memory_label(tool_name: str) -> str:
    mapping = {
        "create_note": "note",
        "create_report": "report",
        "create_message_draft": "message draft",
        "create_checklist": "checklist",
        "create_task": "task",
        "export_brief": "markdown export",
        "log_observation": "observation",
    }
    return mapping.get(tool_name, tool_name.replace("_", " "))


def _normalized_memory_topic_text(text: str) -> str:
    cleaned = text.strip().splitlines()[0].rstrip("?.! ")
    prefixes = (
        "teach me",
        "walk me through",
        "show me how",
        "how do i",
        "how to",
        "help me understand",
        "explain how",
    )
    changed = True
    while changed and cleaned:
        changed = False
        lowered = cleaned.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip(" :,-")
                changed = True
                break
    return cleaned


def _workspace_memory_summary(text: str) -> str:
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text.strip())
        if paragraph.strip()
    ]
    if not paragraphs:
        return text.strip()

    kept: list[str] = []
    for paragraph in paragraphs:
        lowered = paragraph.lower()
        if lowered.startswith("i reviewed "):
            continue
        if lowered.startswith("here is a concise briefing:"):
            continue
        if lowered.startswith("files reviewed:"):
            continue
        kept.append(paragraph)
    if not kept:
        kept = paragraphs
    return " ".join(kept)


def _assistant_output_memory_excerpt(text: str) -> str | None:
    compact = " ".join(text.split())
    patterns = (
        r"(?:it now centers on:|it currently centers on:)\s*(.+?)(?:\s+it is still waiting for your approval\.?|$)",
        r"(?:the markdown export draft is|the report draft is|the checklist draft is|the note draft is)\s*\"[^\"]+\"\.\s*it currently centers on:\s*(.+?)(?:$)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _normalized_stored_memory_summary(text: str) -> str:
    cleaned = " ".join(text.split())
    patterns = (
        r"^Here is a practical way to (?:approach )?[^:]+:\s*",
        r"^Yes\. Earlier we were talking about [^.]+\.\s*The main point was:\s*",
        r"^Yes\. The main point there was:\s*",
        r"^The main point was:\s*",
    )
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _trim_memory_text(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _is_generic_memory_follow_up(lowered: str) -> bool:
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
            "actually just talk normally",
            "talk normally again",
        }
    )


def _looks_like_teaching_follow_up_request(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in {
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


def _parse_memory_json(text: str) -> ConversationMemoryResult | None:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        import json

        payload = json.loads(match.group(0))
    except Exception:
        return None
    topic = _trim_memory_text(str(payload.get("topic") or "").strip(), 96)
    summary = _trim_memory_text(str(payload.get("summary") or "").strip(), 180)
    raw_keywords = payload.get("keywords") if isinstance(payload, dict) else None
    keywords = []
    if isinstance(raw_keywords, list):
        keywords = [str(item).strip().lower() for item in raw_keywords if str(item).strip()][:8]
    if not topic or not summary:
        return None
    return ConversationMemoryResult(
        topic=topic,
        summary=summary,
        keywords=keywords,
        backend="mlx",
    )


def _parse_memory_ranking_json(
    text: str,
    memories: list[ConversationMemoryEntry],
) -> ConversationMemoryRankingResult | None:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        import json

        payload = json.loads(match.group(0))
    except Exception:
        return None
    raw_ids = payload.get("ordered_ids") if isinstance(payload, dict) else None
    if not isinstance(raw_ids, list):
        return None
    valid_ids = {memory.id for memory in memories}
    ordered_ids = [str(item) for item in raw_ids if str(item) in valid_ids]
    if not ordered_ids:
        return None
    remaining = [memory.id for memory in memories if memory.id not in ordered_ids]
    return ConversationMemoryRankingResult(
        ordered_ids=ordered_ids + remaining,
        backend="mlx",
    )


def _parse_memory_focus_json(
    text: str,
    memories: list[ConversationMemoryEntry],
) -> MemoryFocusResult | None:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        import json

        payload = json.loads(match.group(0))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    memory_ids = {memory.id for memory in memories}
    anchor_kind = str(payload.get("primary_anchor_kind") or "").strip().lower()
    if anchor_kind not in {"conversation_memory", "topic", "none", "referent", "grounded_evidence"}:
        return None
    memory_id = str(payload.get("memory_id") or "").strip() or None
    if memory_id is not None and memory_id not in memory_ids:
        return None
    topic_frame = _trim_memory_text(str(payload.get("topic_frame") or "").strip(), 96) or None
    reason = _trim_memory_text(str(payload.get("reason") or "").strip(), 180)
    if not reason:
        return None
    try:
        confidence = float(payload.get("confidence"))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    conflict_note = _trim_memory_text(str(payload.get("conflict_note") or "").strip(), 180) or None
    ask_clarifying_question = (
        _trim_memory_text(str(payload.get("ask_clarifying_question") or "").strip(), 140)
        or None
    )
    return MemoryFocusResult(
        primary_anchor_kind=anchor_kind,
        memory_id=memory_id,
        topic_frame=topic_frame,
        reason=reason,
        confidence=confidence,
        conflict_note=conflict_note,
        ask_clarifying_question=ask_clarifying_question,
        backend="mlx",
    )
