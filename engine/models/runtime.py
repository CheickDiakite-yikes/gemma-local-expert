from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Protocol

from mlx_lm import generate, load
from mlx_lm.sample_utils import make_sampler

from engine.contracts.api import (
    AssistantMode,
    EvidencePacket,
    ExecutionMode,
    GroundingStatus,
    SearchResultItem,
    SourceDomain,
)
from engine.models.sources import resolve_model_source


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


class AssistantRuntime(Protocol):
    backend_name: str

    def generate(self, request: AssistantGenerationRequest) -> AssistantGenerationResult: ...


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
                lines.append(f"I prepared a {tool_label} and it is ready for your approval.")
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

    def _summary_from_sources(self, citations: list[SearchResultItem]) -> str:
        primary = citations[0]
        return f"Most relevant source: [{primary.label}] {primary.excerpt}"

    def _retrieval_response(self, request: AssistantGenerationRequest) -> str:
        top_labels = ", ".join(citation.label for citation in request.citations[:2])
        primary = request.citations[0]
        lowered = request.user_text.lower().strip()

        if request.interaction_kind == "teaching":
            topic = self._topic_from_request(request.user_text)
            return (
                f"Here is a practical way to approach {topic}: start with the core action from "
                f"[{primary.label}] {primary.excerpt}"
            )

        if request.is_follow_up and any(
            phrase in lowered for phrase in {"what should i emphasize first", "what matters first"}
        ):
            if request.active_topic:
                return (
                    f"For the earlier topic about {request.active_topic}, start with the most practical point from "
                    f"[{primary.label}] {primary.excerpt}"
                )

        return (
            f"I found relevant local material in {top_labels}. "
            f"{self._summary_from_sources(request.citations)}"
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
                "I loaded the video locally and sampled a few frames into a contact sheet for review. "
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
            lines = ["I reviewed the video locally."]
            if packet.execution_mode == ExecutionMode.FALLBACK:
                lines[0] = "I reviewed sampled video frames locally."
            if packet.facts:
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
            lines = ["I reviewed the document locally."]
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
                return "From the image, the clearest grounded points are:\n" + "\n".join(
                    f"- {fact.summary}" for fact in packet.facts[:4]
                )
            return packet.summary

        return packet.summary

    def _general_local_response(self, request: AssistantGenerationRequest) -> str:
        lowered = request.user_text.lower().strip()
        work_product_reply = self._work_product_follow_up(request, lowered)
        if work_product_reply:
            return work_product_reply
        if any(token in lowered for token in {"thank you", "thanks"}):
            return "You're welcome. We can keep talking normally, or turn the next step into a local action if useful."
        if any(token == lowered or token in lowered for token in {"hi", "hello", "hey", "how are you"}):
            return "Hi. We can talk normally here, reason through a question, or switch into local research and tasks when needed."
        if self._is_supportive_request(lowered):
            return (
                "Take a breath. You do not need to solve the whole day right this second. "
                "You care, you have already been thinking it through, and it is okay to slow down for a minute. "
                "Pick one small next step, then stop there. If you want, tell me what part feels heaviest and we can just handle that one piece."
            )
        if request.is_follow_up:
            prior_topic = request.active_topic or self._recent_topic(
                request.messages, request.user_text
            )
            if "what do you mean by that" in lowered:
                if prior_topic:
                    return (
                        f"I mean we can keep the conversation natural while still preserving continuity with the earlier thread about {prior_topic}, "
                        "and only switch into local retrieval, media analysis, or saved actions when that actually helps."
                    )
                return (
                    "I mean we can keep the conversation natural, and only switch into local retrieval, analysis, or saved actions when that actually helps."
                )
            if any(phrase in lowered for phrase in {"bring that up again", "go back to that", "come back to that"}):
                if prior_topic:
                    return f"Yes. The main thread we were on was {prior_topic}. We can stay with that and go deeper."
                return "Yes. We can stay with the earlier thread and go deeper."
            if any(phrase in lowered for phrase in {"what should i emphasize first", "what matters first"}):
                if prior_topic:
                    return (
                        f"Start with the most practical first point from our earlier discussion about {prior_topic}: "
                        "state the goal in plain language, demonstrate the first action once, and repeat the key safety check."
                    )
                return (
                    "Start with the most practical first point: state the goal in plain language, demonstrate the first action once, and repeat the key safety check."
                )
            if prior_topic:
                return f"To build on the earlier discussion about {prior_topic}, I would keep the next step practical and easy to act on."
            return "To build on the last point, I would keep the next step practical and easy to act on."
        if request.interaction_kind == "teaching":
            topic = self._topic_from_request(request.user_text)
            return (
                f"Here is a practical way to approach {topic}: start with the immediate goal, "
                "break it into a few simple steps, explain the first step plainly, and check understanding before adding detail."
            )
        return (
            "Yes. We can have a normal conversation here, and I can also switch into local analysis or task execution when you want."
        )

    def _work_product_follow_up(
        self, request: AssistantGenerationRequest, lowered: str
    ) -> str | None:
        multi_output_reply = self._multi_output_work_product_follow_up(request, lowered)
        if multi_output_reply:
            return multi_output_reply

        if request.referent_kind not in {"pending_output", "saved_output"}:
            return None

        title = request.referent_title or "Untitled draft"
        label = self._tool_label(request.referent_tool or "")

        if any(
            phrase in lowered
            for phrase in {
                "what title are you using",
                "what title is that",
                "what is the draft called",
                "what is that draft called",
                "what is the title now",
                "what is the draft title",
                "what did you call that",
                "what are you calling that",
            }
        ):
            if request.referent_kind == "pending_output":
                return (
                    f'The current {label} draft is titled "{title}". '
                    "If you want, I can help tighten the title or the body before you save it."
                )
            return f'The most recent saved {label} is titled "{title}".'

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
                revised_bits = [f'I tightened the current {label} draft.']
                if title:
                    revised_bits.append(f'It is now titled "{title}".')
                if request.referent_excerpt:
                    revised_bits.append(
                        f"It now centers on: {request.referent_excerpt}"
                    )
                revised_bits.append("It is still waiting for your approval.")
                return " ".join(revised_bits)
            return (
                f'The most recent saved {label} is "{title}". '
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
        ):
            if request.referent_excerpt:
                return (
                    f'The current {label} is "{title}". '
                    f"It currently centers on: {request.referent_excerpt}"
                )
            return (
                f'The current {label} draft is "{title}". '
                "You can review the full content in the draft panel, and I can help tighten the wording before you save it."
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
        if "report" in mentioned_labels and by_label.get("report"):
            parts.append(f'The earlier report was "{by_label["report"]}".')
        if "checklist" in mentioned_labels and by_label.get("checklist"):
            parts.append(f'The checklist was "{by_label["checklist"]}".')
        if "markdown export" in mentioned_labels and by_label.get("markdown export"):
            parts.append(f'The newer export was "{by_label["markdown export"]}".')
        if not parts:
            return None
        return " ".join(parts)

    def _recent_outputs_from_summary(self, summary: str) -> list[tuple[str, str]]:
        if not summary:
            return []
        return re.findall(
            r'(report|checklist|markdown export|message draft|note|task)\s+"([^"]+)"',
            summary,
            flags=re.IGNORECASE,
        )

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
            "export_brief": "markdown export",
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
        cleaned = text.strip().rstrip("?.! ")
        lowered = cleaned.lower()
        for prefix in ("teach me", "walk me through", "show me how", "how do i", "how to", "help me understand"):
            if lowered.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip(" :,-")
                break
        return cleaned or "this"

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

    def _load_model(self, source: str) -> tuple[object, object]:
        with self._lock:
            cached = self._cache.get(source)
            if cached is not None:
                return cached
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
