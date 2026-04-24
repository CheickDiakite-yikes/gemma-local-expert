from __future__ import annotations

from dataclasses import dataclass
import re

from engine.context.service import ConversationContextSnapshot
from engine.contracts.api import (
    AssetSummary,
    AssistantMode,
    ConversationMessage,
    ConversationTurnRequest,
    EvidencePacket,
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
    _RECENT_HISTORY_WINDOW = 6
    _MAX_USER_HISTORY_CHARS = 320
    _MAX_ASSISTANT_HISTORY_CHARS = 520
    _HISTORY_STOPWORDS = {
        "about",
        "again",
        "also",
        "assistant",
        "before",
        "built",
        "brief",
        "briefing",
        "called",
        "current",
        "draft",
        "earlier",
        "field",
        "first",
        "from",
        "image",
        "keep",
        "local",
        "markdown",
        "most",
        "note",
        "output",
        "please",
        "reviewed",
        "same",
        "save",
        "short",
        "shorter",
        "that",
        "them",
        "this",
        "title",
        "video",
        "what",
        "with",
        "workspace",
    }
    _LOW_SIGNAL_HISTORY_PREFIXES = (
        "please confirm",
        "please approve",
        "policy status:",
        "router notes:",
        "workspace scope:",
        "goal:",
        "related local docs:",
        "working title:",
        "tool action detected:",
        "tool writes durable state",
        "approve the draft below",
        "approve the draft",
        "approve the creation",
    )
    _LOW_SIGNAL_HISTORY_EXACT_LINES = {
        "context",
        "draft ready",
        "ready to save",
        "needs approval",
        "working locally",
    }

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
        evidence_packet: EvidencePacket | None = None,
    ) -> PromptContext:
        history_messages = self._select_history_messages(
            history=history,
            route=route,
            conversation_context=conversation_context,
        )
        history_trimmed = len(history_messages) < len(
            [message for message in history if message.content.strip()]
        )
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": self._system_prompt(
                    turn.mode,
                    turn.text,
                    route,
                    policy,
                    conversation_context,
                    context_assets,
                    model_selection,
                    results,
                    specialist_analysis,
                    workspace_summary,
                    tool_result,
                    history_trimmed,
                    evidence_packet,
                ),
            }
        ]

        messages.extend(history_messages)

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
                    history_trimmed,
                    evidence_packet,
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
        context_assets: list[AssetSummary],
        model_selection: ModelRouteSelection,
        results: list[SearchResultItem],
        specialist_analysis: str | None,
        workspace_summary: str | None,
        tool_result: dict[str, object] | None,
        history_trimmed: bool,
        evidence_packet: EvidencePacket | None = None,
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
                "For greetings, thanks, quick clarifications, and casual check-ins, answer in one to three natural sentences."
            )
            lines.append(
                "Do not advertise product capabilities or explain obvious limitations unless they are necessary to answer the user's question."
            )
            lines.append(
                "If the user is casual, be casual. If they are reflective or emotional, meet them there without turning the reply into process language."
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
                "When the user only asks for the current title, answer with the title directly and do not add an extra body summary."
            )
            lines.append(
                "If the continuity snapshot includes a draft preview, use it directly. When the user asks what is in the draft, summarize that preview. When they ask to shorten it, propose a tighter title or opening instead of only saying you can help."
            )
            lines.append(
                "If the continuity snapshot identifies a checklist, note, task, or export specifically, answer about that exact work product and do not switch to a different output just because it is newer."
            )
            if (
                conversation_context
                and conversation_context.selected_referent_kind not in {"pending_output", "saved_output"}
                and len(conversation_context.recent_outputs) > 1
            ):
                lines.append(
                    "The user may be referring to multiple recent local outputs at once. Use the titles from Recent local outputs explicitly, distinguish report versus checklist versus export by name, and do not prepare a new write action unless the user clearly asks you to create, save, or export something new."
                )
                lines.append(
                    "If Recent saved output titles are provided, treat them as the exact title-to-type mapping and repeat them literally instead of paraphrasing."
                )

        if route.is_follow_up:
            lines.append(
                "This is a follow-up turn. Preserve continuity with the recent conversation instead of restarting from scratch."
            )
        if history_trimmed:
            lines.append(
                "Only a bounded slice of earlier chat is included below. Use the continuity snapshot as the primary anchor for older references instead of reviving stale details."
            )
        if conversation_context and conversation_context.prompt_lines():
            lines.append(
                "A structured continuity snapshot is provided in the user context. Use it to resolve references like 'that', 'earlier image', 'the draft', or 'go back to the video' without making the user restate everything."
            )
            lines.append(
                "Treat the referent summary and referent preview in that snapshot as the main continuity anchor for follow-up turns."
            )
            if conversation_context.active_compaction_summary:
                lines.append(
                    "If the continuity snapshot includes a compaction summary, treat it as the current condensed thread state and prefer it over reviving older low-signal details."
                )
            if conversation_context.active_steering_instruction:
                lines.append(
                    "If the continuity snapshot includes an active thread steering note, treat it as explicit thread guidance unless the current user turn clearly overrides it."
                )
            if conversation_context.turn_adaptation_kind == "casual_detour":
                lines.append(
                    "If the continuity snapshot marks this turn as a casual detour, answer the current turn naturally and do not drag the foreground draft, media, or earlier task back into the reply unless the user explicitly returns to it."
                )
            elif conversation_context.turn_adaptation_kind == "task_pivot":
                lines.append(
                    "If the continuity snapshot marks this turn as a task pivot, treat the current user turn as the new primary problem. Do not revive older draft, media, or steering context just because it exists."
                )
            elif conversation_context.turn_adaptation_kind == "return_to_anchor":
                lines.append(
                    "If the continuity snapshot marks this turn as a return to anchor, re-anchor to that earlier draft, media, or topic immediately."
                )
            if conversation_context.selected_evidence_summary:
                lines.append(
                    "If the continuity snapshot includes grounded evidence memory, prefer it over assistant prose. Reuse its facts directly and treat its uncertainty lines as hard limits."
                )
            if conversation_context.selected_memory_summary:
                lines.append(
                    "If the continuity snapshot includes a selected conversation memory, treat it as a secondary continuity hint. Use it to recover topic-level context only when there is no stronger explicit referent or grounded evidence for this turn."
                )
            if conversation_context.memory_focus_kind:
                lines.append(
                    "If the continuity snapshot includes a memory focus block, treat it as the current best bounded continuity guess. Explicit referents and grounded evidence still override it."
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
            if context_assets and conversation_context and conversation_context.selected_context_summary:
                lines.append(
                    "This action is grounded in earlier conversation media that already has a usable local summary. "
                    "Use that summary directly and do not ask the user to restate the image or video unless the summary is too weak to act on safely."
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
            lines.append(
                "If the user asks for tracking, SAM, isolation, or segment extraction and the evidence packet says fallback or unavailable, say clearly that tracking/isolation did not run. Do not narrate that it is executing now."
            )
        if evidence_packet:
            lines.append(
                f"An evidence packet is provided for the current source domain ({evidence_packet.source_domain.value}). "
                f"Execution mode is {evidence_packet.execution_mode.value} and grounding is {evidence_packet.grounding_status.value}."
            )
            lines.append(
                "Only make claims supported by the evidence packet facts and refs. Treat its uncertainties as hard limits, not soft suggestions."
            )
            if evidence_packet.source_domain.value == "document":
                lines.append(
                    "For document turns, do not invent clean sections, entities, or action items from sparse OCR lines. If extraction is partial or fallback-only, say so directly and quote only the grounded lines you actually have."
                )
        if tool_result:
            lines.append(
                "A safe helper tool already ran during this turn. Explain clearly what it produced and how the user can use it."
            )
        if evidence_packet:
            lines.append(
                "The evidence packet in user context is the primary grounding source for specialist/media/document turns."
            )
        elif specialist_analysis:
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
        if not results and not evidence_packet and not specialist_analysis and not workspace_summary and not tool_result:
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
        history_trimmed: bool,
        evidence_packet: EvidencePacket | None = None,
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
            if history_trimmed and conversation_context.active_compaction_summary:
                sections.append(
                    "Compacted earlier thread state:\n"
                    + conversation_context.active_compaction_summary
                )
            continuity_lines = conversation_context.prompt_lines()
            if continuity_lines:
                sections.append(
                    "Conversation continuity snapshot:\n- "
                    + "\n- ".join(continuity_lines)
                )
            if (
                conversation_context.turn_adaptation_kind not in {"casual_detour", "task_pivot"}
                and (
                conversation_context.selected_referent_kind not in {"pending_output", "saved_output"}
                and len(conversation_context.recent_outputs) > 1
                )
            ):
                title_lines = self._recent_output_title_lines(
                    conversation_context.recent_outputs
                )
                if title_lines:
                    sections.append(
                        "Recent saved output titles:\n- " + "\n- ".join(title_lines)
                    )
            if conversation_context.selected_referent_kind in {"pending_output", "saved_output"}:
                referent_lines: list[str] = []
                if conversation_context.selected_referent_tool:
                    referent_lines.append(
                        f"tool={conversation_context.selected_referent_tool}"
                    )
                if conversation_context.selected_referent_title:
                    referent_lines.append(
                        f"title={conversation_context.selected_referent_title}"
                    )
                if conversation_context.selected_referent_excerpt:
                    referent_lines.append(
                        f"preview={conversation_context.selected_referent_excerpt}"
                    )
                if referent_lines:
                    sections.append(
                        "Selected work-product referent:\n- "
                        + "\n- ".join(referent_lines)
                    )

        if evidence_packet:
            evidence_lines = [
                f"domain={evidence_packet.source_domain.value}",
                f"execution_mode={evidence_packet.execution_mode.value}",
                f"grounding_status={evidence_packet.grounding_status.value}",
                f"summary={evidence_packet.summary}",
            ]
            for fact in evidence_packet.facts[:6]:
                refs = ", ".join(ref.ref for ref in fact.refs)
                evidence_lines.append(
                    f"fact={fact.summary}" + (f" refs={refs}" if refs else "")
                )
            for item in evidence_packet.uncertainties[:3]:
                evidence_lines.append(f"uncertainty={item}")
            sections.append("Evidence packet:\n- " + "\n- ".join(evidence_lines))
        elif conversation_context and conversation_context.selected_evidence_summary:
            evidence_memory_lines = [
                f"domain={conversation_context.active_domain or 'unknown'}",
                f"summary={conversation_context.selected_evidence_summary}",
            ]
            for fact in conversation_context.selected_evidence_facts[:4]:
                evidence_memory_lines.append(f"fact={fact}")
            for item in conversation_context.selected_evidence_uncertainties[:3]:
                evidence_memory_lines.append(f"uncertainty={item}")
            sections.append(
                "Selected grounded evidence memory:\n- "
                + "\n- ".join(evidence_memory_lines)
            )
        elif specialist_analysis:
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

    def _recent_output_title_lines(self, recent_outputs) -> list[str]:
        order = {
            "report": 0,
            "checklist": 1,
            "message draft": 2,
            "note": 3,
            "task": 4,
            "markdown export": 5,
            "observation": 6,
        }
        grouped_titles: dict[str, list[str]] = {}
        for output in recent_outputs:
            label = self._tool_label(output.tool_name)
            if not output.title:
                continue
            grouped_titles.setdefault(label, [])
            if output.title not in grouped_titles[label]:
                grouped_titles[label].append(output.title)

        lines: list[str] = []
        for label in sorted(grouped_titles, key=lambda item: (order.get(item, 99), item)):
            titles = grouped_titles[label]
            if len(titles) == 1:
                lines.append(f"{label}={titles[0]}")
                continue
            latest = titles[0]
            oldest = titles[-1]
            lines.append(f"{label}.latest={latest}")
            lines.append(f"{label}.first={oldest}")
            if len(titles) > 2:
                lines.append(f"{label}.second={titles[-2]}")
        return lines

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

    def _select_history_messages(
        self,
        *,
        history: list[ConversationMessage],
        route: RouteDecision,
        conversation_context: ConversationContextSnapshot | None,
    ) -> list[dict[str, str]]:
        cleaned = [message for message in history if message.content.strip()]
        if not cleaned:
            return []

        if (
            route.interaction_kind == "draft_follow_up"
            and conversation_context
            and conversation_context.selected_referent_kind in {"pending_output", "saved_output"}
        ):
            return []

        recent_start = max(0, len(cleaned) - self._RECENT_HISTORY_WINDOW)
        selected_indices = set(range(recent_start, len(cleaned)))
        if recent_start > 0:
            selected_indices.update(
                self._anchor_history_indices(
                    history=cleaned[:recent_start],
                    route=route,
                    conversation_context=conversation_context,
                )
            )

        selected_messages: list[dict[str, str]] = []
        for index, message in enumerate(cleaned):
            if index not in selected_indices:
                continue
            compressed = self._compress_history_content(message.role, message.content)
            if not compressed:
                continue
            selected_messages.append({"role": message.role, "content": compressed})
        return selected_messages

    def _anchor_history_indices(
        self,
        *,
        history: list[ConversationMessage],
        route: RouteDecision,
        conversation_context: ConversationContextSnapshot | None,
    ) -> set[int]:
        if not history:
            return set()

        keywords = self._history_anchor_keywords(route, conversation_context)
        if not keywords:
            if route.interaction_kind == "draft_follow_up":
                start = max(0, len(history) - 2)
                return set(range(start, len(history)))
            return set()

        for index in range(len(history) - 1, -1, -1):
            lowered = history[index].content.lower()
            if any(keyword in lowered for keyword in keywords):
                indices = {index}
                if history[index].role == "assistant" and index > 0:
                    indices.add(index - 1)
                elif history[index].role == "user" and index + 1 < len(history):
                    indices.add(index + 1)
                return indices
        return set()

    def _history_anchor_keywords(
        self,
        route: RouteDecision,
        conversation_context: ConversationContextSnapshot | None,
    ) -> list[str]:
        texts: list[str] = []
        if conversation_context:
            if conversation_context.turn_adaptation_kind in {"casual_detour", "task_pivot"}:
                texts = [
                    text
                    for text in (
                        conversation_context.selected_referent_title,
                        conversation_context.selected_referent_summary,
                        conversation_context.selected_referent_excerpt,
                        conversation_context.selected_context_summary,
                        conversation_context.active_topic,
                    )
                    if text
                ]
                return self._keyword_list(texts)
            texts.extend(
                text
                for text in (
                    conversation_context.selected_referent_title,
                    conversation_context.selected_referent_summary,
                    conversation_context.selected_referent_excerpt,
                    conversation_context.selected_context_summary,
                    conversation_context.active_topic,
                )
                if text
            )
            if conversation_context.selected_referent_kind not in {"pending_output", "saved_output"}:
                texts.extend(
                    text
                    for text in (
                        conversation_context.pending_approval_summary,
                        conversation_context.pending_approval_excerpt,
                    )
                    if text
                )

        if route.interaction_kind == "draft_follow_up":
            texts.extend(["draft", "ready to save", "save locally"])
        elif route.interaction_kind == "video":
            texts.extend(["video", "clip", "workers near excavation equipment"])
        elif route.interaction_kind == "vision":
            texts.extend(["image", "shortage", "lantern batteries"])

        keywords: list[str] = []
        seen: set[str] = set()
        for text in texts:
            lowered = text.lower().strip()
            if lowered and len(lowered) <= 120 and lowered not in seen:
                keywords.append(lowered)
                seen.add(lowered)
            for token in re.findall(r"[a-z0-9]{4,}", lowered):
                if token in self._HISTORY_STOPWORDS or token in seen:
                    continue
                keywords.append(token)
                seen.add(token)
                if len(keywords) >= 10:
                    return keywords
        return keywords

    def _keyword_list(self, texts: list[str]) -> list[str]:
        keywords: list[str] = []
        seen: set[str] = set()
        for text in texts:
            lowered = text.lower().strip()
            if lowered and len(lowered) <= 120 and lowered not in seen:
                keywords.append(lowered)
                seen.add(lowered)
            for token in re.findall(r"[a-z0-9]{4,}", lowered):
                if token in self._HISTORY_STOPWORDS or token in seen:
                    continue
                keywords.append(token)
                seen.add(token)
                if len(keywords) >= 10:
                    return keywords
        return keywords

    def _compress_history_content(self, role: str, content: str) -> str:
        if role == "assistant":
            stripped = self._strip_low_signal_history_lines(content)
            return self._clip_text(
                self._compact(stripped or content),
                self._MAX_ASSISTANT_HISTORY_CHARS,
            )
        return self._clip_text(self._compact(content), self._MAX_USER_HISTORY_CHARS)

    def _strip_low_signal_history_lines(self, content: str) -> str:
        lines: list[str] = []
        for raw_line in content.replace("\r\n", "\n").split("\n"):
            stripped = raw_line.strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if lowered in self._LOW_SIGNAL_HISTORY_EXACT_LINES:
                continue
            if any(lowered.startswith(prefix) for prefix in self._LOW_SIGNAL_HISTORY_PREFIXES):
                continue
            lines.append(stripped)
        return "\n".join(lines).strip()

    def _compact(self, text: str) -> str:
        compacted = re.sub(r"\s+", " ", text).strip()
        return compacted

    def _clip_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        clipped = text[: limit - 1].rstrip()
        last_break = max(clipped.rfind(". "), clipped.rfind("; "), clipped.rfind(", "))
        if last_break >= int(limit * 0.55):
            clipped = clipped[:last_break].rstrip(" ,;.")
        return clipped + "…"
