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
            lines.append("I used the bounded workspace-agent findings for this turn.")
            lines.append(request.workspace_summary_text)
        elif request.specialist_analysis_text:
            lines.append("I used the available specialist image context for this turn.")
            lines.append(request.specialist_analysis_text)
        elif request.citations:
            top_labels = ", ".join(citation.label for citation in request.citations[:2])
            lines.append(f"I found relevant local material: {top_labels}.")
            lines.append(self._summary_from_sources(request.citations))
        else:
            lines.append(
                "I do not have retrieved local sources for this turn yet, so this is a best-effort local mock response."
            )

        if request.specialist_model_name and not request.specialist_analysis_text:
            lines.append(f"Selected specialist route: {request.specialist_model_name}.")
            if not request.citations:
                lines.append(
                    "This backend is currently using attachment metadata only, so it cannot make pixel-level claims about the image contents yet."
                )

        if request.tool_result:
            lines.append(self._tool_result_summary(request.tool_result))

        if request.proposed_tool:
            if request.approval_required:
                lines.append(
                    f"I can prepare `{request.proposed_tool}`, but it is currently gated for approval."
                )
            elif request.tool_result:
                lines.append(f"I already completed `{request.proposed_tool}` for this turn.")
            else:
                lines.append(f"I can proceed with `{request.proposed_tool}` if you want that action.")

        return AssistantGenerationResult(
            text=" ".join(lines),
            backend=self.backend_name,
            model_name=request.assistant_model_name,
            model_source=request.assistant_model_source,
        )

    def _summary_from_sources(self, citations: list[SearchResultItem]) -> str:
        primary = citations[0]
        return f"Most relevant source: [{primary.label}] {primary.excerpt}"

    def _tool_result_summary(self, result: dict[str, object]) -> str:
        message = str(result.get("message") or "").strip()
        if message:
            return message
        title = str(result.get("title") or "").strip()
        if title:
            return f"Completed tool result: {title}."
        return "A local tool completed successfully for this turn."


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
