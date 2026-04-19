from __future__ import annotations

from dataclasses import dataclass

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
        ]

        if route.interaction_kind == "conversation":
            lines.append(
                "This is ordinary conversation. Answer naturally and directly without operational boilerplate."
            )

        if route.is_follow_up:
            lines.append(
                "This is a follow-up turn. Preserve continuity with the recent conversation instead of restarting from scratch."
            )

        if self._is_teaching_request(user_text):
            lines.append(
                "The user is asking to learn. Answer like a capable field instructor: begin with a direct orientation, then give short ordered steps, include one practical tip or example, and end with a useful next-step question only if it helps."
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
                "A gated action may require user approval. Make that explicit in the response."
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

    def _should_include_router_notes(self, route: RouteDecision) -> bool:
        return bool(
            route.agent_run
            or route.specialist_model
            or route.proposed_tool
            or route.needs_retrieval
            or route.is_follow_up
        )
