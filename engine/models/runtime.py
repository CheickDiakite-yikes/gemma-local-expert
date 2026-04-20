from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from mlx_lm import generate, load
from mlx_lm.sample_utils import make_sampler

from engine.contracts.api import AssistantMode, SearchResultItem
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
    proposed_tool: str | None
    approval_required: bool
    tool_result: dict[str, object] | None
    assistant_model_name: str
    assistant_model_source: str | None
    specialist_model_name: str | None
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

        if request.workspace_summary_text:
            lines.append(request.workspace_summary_text.strip())
        elif request.specialist_analysis_text:
            lines.append(self._specialist_response(request))
        elif request.citations:
            top_labels = ", ".join(citation.label for citation in request.citations[:2])
            lines.append(f"I found relevant local material in {top_labels}.")
            lines.append(self._summary_from_sources(request.citations))
        else:
            lines.append(self._general_local_response(request))

        if request.specialist_model_name and not request.specialist_analysis_text:
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
            text=" ".join(lines),
            backend=self.backend_name,
            model_name=request.assistant_model_name,
            model_source=request.assistant_model_source,
        )

    def _summary_from_sources(self, citations: list[SearchResultItem]) -> str:
        primary = citations[0]
        return f"Most relevant source: [{primary.label}] {primary.excerpt}"

    def _specialist_response(self, request: AssistantGenerationRequest) -> str:
        lowered = request.user_text.lower().strip()
        cleaned = self._clean_specialist_text(request.specialist_analysis_text or "")
        low_items = self._low_items_from_analysis(cleaned)

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

    def _general_local_response(self, request: AssistantGenerationRequest) -> str:
        lowered = request.user_text.lower().strip()
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
            prior_topic = self._recent_topic(request.messages, request.user_text)
            if "what do you mean by that" in lowered:
                return (
                    "I mean we can keep the conversation natural, and only switch into local retrieval, analysis, or saved actions when that actually helps."
                )
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
            "create_checklist": "checklist draft",
            "create_task": "task draft",
            "log_observation": "saved observation",
            "export_brief": "markdown export",
            "generate_heatmap_overlay": "heatmap overlay",
        }
        return mapping.get(tool_name, tool_name.replace("_", " "))

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
