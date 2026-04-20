from __future__ import annotations

from dataclasses import dataclass

from engine.context.service import ConversationContextSnapshot
from engine.contracts.api import (
    AssetSummary,
    AssistantMode,
    ConversationMessage,
    ConversationTurnRequest,
    SearchResultItem,
)
from engine.models.gateway import ModelRouteSelection
from engine.policy.service import PolicyDecision
from engine.routing.service import RouteDecision


@dataclass(slots=True)
class PromptContext:
    messages: list[dict[str, str]]
    source_count: int


class PromptBuilder:
    def build(
        self,
        *,
        turn: ConversationTurnRequest,
        history: list[ConversationMessage],
        assets: list[AssetSummary],
        context_assets: list[AssetSummary],
        conversation_context: ConversationContextSnapshot | None,
        specialist_analysis: str | None,
        workspace_summary: str | None,
        route: RouteDecision,
        policy: PolicyDecision,
        model_selection: ModelRouteSelection,
        results: list[SearchResultItem],
        tool_result: dict[str, object] | None = None,
    ) -> PromptContext:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": self._system_prompt(
                    turn.mode,
                    turn.text,
                    route,
                    policy,
                    conversation_context,
                    model_selection,
                    results,
                    specialist_analysis,
                    workspace_summary,
                    tool_result,
                ),
            }
        ]

        for message in history:
            messages.append({"role": message.role, "content": message.content})

        messages.append(
            {
                "role": "user",
                "content": self._user_prompt(
                    turn,
                    assets,
                    context_assets,
                    conversation_context,
                    specialist_analysis,
                    workspace_summary,
                    route,
                    policy,
                    results,
                    tool_result,
                ),
            }
        )
        return PromptContext(messages=messages, source_count=len(results))

    def _system_prompt(
        self,
        mode: AssistantMode,
        user_text: str,
        route: RouteDecision,
        policy: PolicyDecision,
        conversation_context: ConversationContextSnapshot | None,
        model_selection: ModelRouteSelection,
        results: list[SearchResultItem],
        specialist_analysis: str | None,
        workspace_summary: str | None,
        tool_result: dict[str, object] | None,
    ) -> str:
        lines = [
            "You are Field Assistant, a local-first offline work assistant.",
            f"Active mode: {mode.value}.",
            "Prefer grounded answers from provided local sources over model memory.",
            "Keep answers practical and concise unless the user asks for detail.",
            "Use clean markdown-style formatting when helpful: short headings, flat bullets, and compact sections.",
            "Sound like a calm capable collaborator, not a memo or policy document.",
            "Avoid stiff openings like 'Understood' or 'I can certainly' unless the user asked for formal tone.",
            "Avoid decorative separators, raw tool ids, and operational boilerplate in normal replies.",
        ]

        if route.interaction_kind == "conversation":
            lines.append(
                "This is ordinary conversation. Answer naturally, directly, and with minimal ceremony."
            )
            lines.append(
                "Do not explain obvious limitations unless they are necessary to answer the user's question."
            )
            if self._is_supportive_request(user_text):
                lines.append(
                    "The user wants reassurance or emotional grounding. Be warm, brief, and human."
                )
                lines.append(
                    "Do not turn this into a checklist, numbered framework, or coaching worksheet unless the user asks for that structure."
                )
                lines.append(
                    "Do not drag in earlier task context unless the user explicitly asks you to connect it."
                )
        elif route.interaction_kind == "draft_follow_up":
            lines.append(
                "This turn is about a current local draft or recent saved output. Stay anchored to that work product instead of switching back to older media or retrieval context."
            )
            lines.append(
                "If the user asks what it is called, answer with the current title. If they ask to tighten or rename it, keep the reply practical and pre-save."
            )
            lines.append(
                "If the continuity snapshot includes a draft preview, use it directly. When the user asks what is in the draft, summarize that preview. When they ask to shorten it, propose a tighter title or opening instead of only saying you can help."
            )

        if route.is_follow_up:
            lines.append(
                "This is a follow-up turn. Preserve continuity with the recent conversation instead of restarting from scratch."
            )
        if conversation_context and conversation_context.prompt_lines():
            lines.append(
                "A structured continuity snapshot is provided in the user context. Use it to resolve references like 'that', 'earlier image', 'the draft', or 'go back to the video' without making the user restate everything."
            )
            lines.append(
                "Treat the referent summary and referent preview in that snapshot as the main continuity anchor for follow-up turns."
            )

        if self._is_teaching_request(user_text):
            lines.append(
                "The user is asking to learn. Answer like a practical field instructor: use one short setup sentence, then 3 to 5 short steps or bullets, include one concrete example or caution, and keep the tone plain."
            )
            lines.append(
                "Avoid handout-style headings like 'Orientation' or 'Practical Steps' unless the user explicitly wants a formal guide."
            )

        if results:
            lines.append(
                "When using provided local sources, cite them inline by source label."
            )
        if route.proposed_tool:
            lines.append(
                f"The router detected a possible tool action: {route.proposed_tool}. "
                "Do not claim the tool already ran unless approval and execution happened."
            )
        if route.agent_run:
            lines.append(
                "A bounded workspace agent gathered local file findings for this turn. Use those findings directly and do not imply arbitrary shell access."
            )
        if policy.approval_required:
            lines.append(
                "A gated action may require user approval. Keep that mention short, avoid raw tool names, and let the UI carry most of the workflow detail."
            )
        if route.specialist_model:
            lines.append(
                f"A specialist route was requested: {route.specialist_model}. "
                "If specialist execution is unavailable, answer conservatively."
            )
        if route.specialist_model in {"paligemma", "medgemma"}:
            lines.append(
                "Do not claim to see image details unless the prompt includes explicit extracted "
                "visual notes. Attached image metadata alone is not enough for pixel-level claims."
            )
        if route.specialist_model == "sam3":
            lines.append(
                "For video work, separate object detection or tracking from higher-level judgment. "
                "Tracked tools, people, or machines are evidence inputs, not proof of unsafe or illegal conduct by themselves."
            )
        if tool_result:
            lines.append(
                "A safe helper tool already ran during this turn. Explain clearly what it produced and how the user can use it."
            )
        if specialist_analysis:
            lines.append(
                "Specialist visual analysis is provided in the user context. Prefer it over "
                "guessing from attachment metadata."
            )
        if workspace_summary:
            lines.append(
                "Workspace-agent findings are provided in the user context. Prefer them over unsupported guesses about repository contents."
            )
            lines.append(
                "Summarize workspace findings like assistant synthesis, not a serialized trace."
            )
        if not results and not specialist_analysis and not workspace_summary and not tool_result:
            lines.append(
                "If no local sources are provided, you can still answer from general reasoning. Do not mention missing retrieval unless the user explicitly asked for grounded evidence."
            )
        lines.append(
            f"Primary assistant model route: {model_selection.assistant_model}."
        )
        return " ".join(lines)

    def _user_prompt(
        self,
        turn: ConversationTurnRequest,
        assets: list[AssetSummary],
        context_assets: list[AssetSummary],
        conversation_context: ConversationContextSnapshot | None,
        specialist_analysis: str | None,
        workspace_summary: str | None,
        route: RouteDecision,
        policy: PolicyDecision,
        results: list[SearchResultItem],
        tool_result: dict[str, object] | None,
    ) -> str:
        sections = [f"User request:\n{turn.text}"]

        if assets:
            sections.append("Attached assets:\n" + "\n".join(self._asset_lines(assets)))

        if context_assets:
            sections.append(
                "Relevant recent assets from the conversation:\n"
                + "\n".join(self._asset_lines(context_assets))
            )

        if conversation_context:
            continuity_lines = conversation_context.prompt_lines()
            if continuity_lines:
                sections.append(
                    "Conversation continuity snapshot:\n- "
                    + "\n- ".join(continuity_lines)
                )

        if specialist_analysis:
            sections.append("Specialist visual analysis:\n" + specialist_analysis)

        if workspace_summary:
            sections.append("Workspace agent findings:\n" + workspace_summary)

        if self._should_include_router_notes(route):
            sections.append("Router notes:\n- " + "\n- ".join(route.reasons))

        if results:
            source_lines = []
            for result in results:
                source_lines.append(
                    f"[{result.label}] score={result.score:.3f} excerpt={result.excerpt}"
                )
            sections.append("Local sources:\n" + "\n".join(source_lines))

        if tool_result:
            sections.append("Tool result:\n" + self._format_tool_result(tool_result))

        if policy.approval_required:
            sections.append("Policy status:\nA follow-up approval may be required for any write action.")

        return "\n\n".join(sections)

    def _asset_lines(self, assets: list[AssetSummary]) -> list[str]:
        asset_lines: list[str] = []
        for asset in assets:
            detail_bits = [asset.kind.value]
            if asset.media_type:
                detail_bits.append(asset.media_type)
            detail_bits.append(f"context={asset.care_context.value}")
            if asset.analysis_summary:
                detail_bits.append(asset.analysis_summary)
            asset_lines.append(f"[{asset.display_name}] " + " | ".join(detail_bits))
        return asset_lines

    def _format_tool_result(self, tool_result: dict[str, object]) -> str:
        lines: list[str] = []
        if tool_result.get("title"):
            lines.append(f"title={tool_result['title']}")
        if tool_result.get("message"):
            lines.append(f"message={tool_result['message']}")
        if tool_result.get("status"):
            lines.append(f"status={tool_result['status']}")
        asset = tool_result.get("asset")
        if isinstance(asset, dict):
            display_name = asset.get("display_name")
            content_url = asset.get("content_url")
            if display_name:
                lines.append(f"asset={display_name}")
            if content_url:
                lines.append(f"asset_url={content_url}")
        if not lines:
            lines.append(str(tool_result))
        return "\n".join(lines)

    def _is_teaching_request(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            phrase in lowered
            for phrase in {"teach me", "walk me through", "show me how", "how do i", "how to"}
        )

    def _is_supportive_request(self, text: str) -> bool:
        lowered = text.lower()
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

    def _should_include_router_notes(self, route: RouteDecision) -> bool:
        return bool(
            route.agent_run
            or route.specialist_model
            or route.proposed_tool
            or route.needs_retrieval
            or route.is_follow_up
        )
