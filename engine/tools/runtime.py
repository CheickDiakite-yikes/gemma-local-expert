from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from engine.contracts.api import (
    AssetAnalysisStatus,
    AssetCareContext,
    AssetKind,
    AssetSummary,
    CanvasSelectionContext,
    CanvasSelectionEditAction,
    ConversationTurnRequest,
    EvidencePacket,
    GroundingStatus,
    ExportRequest,
    SearchResultItem,
    new_id,
)
from engine.persistence.repositories import PersistenceStore


@dataclass(slots=True)
class ToolPlan:
    tool_name: str
    payload: dict[str, object]


class ToolRuntime:
    def __init__(
        self,
        store: PersistenceStore,
        *,
        asset_storage_dir: str = "data/uploads",
        export_storage_dir: str = "data/exports",
    ) -> None:
        self.store = store
        self.asset_storage_dir = Path(asset_storage_dir)
        self.asset_storage_dir.mkdir(parents=True, exist_ok=True)
        self.export_storage_dir = Path(export_storage_dir)
        self.export_storage_dir.mkdir(parents=True, exist_ok=True)

    def plan(
        self,
        turn: ConversationTurnRequest,
        tool_name: str,
        retrieval_results: list[SearchResultItem],
        *,
        evidence_packet: EvidencePacket | None = None,
        specialist_analysis_text: str | None = None,
        context_assets: list[AssetSummary] | None = None,
        context_summary: str | None = None,
    ) -> ToolPlan:
        if tool_name == "create_note":
            payload = {
                "title": self._title_from_request(turn.text, fallback="Field Note"),
                "content": self._build_note_content(
                    turn,
                    evidence_packet=evidence_packet,
                    specialist_analysis_text=specialist_analysis_text,
                ),
                "kind": "note",
            }
            self._add_grounding_metadata(payload, evidence_packet)
            return ToolPlan(
                tool_name=tool_name,
                payload=payload,
            )

        if tool_name == "create_report":
            payload = {
                "title": self._report_title(turn.text, fallback="Field Report"),
                "content": self._build_report_content(
                    turn,
                    evidence_packet=evidence_packet,
                    specialist_analysis_text=specialist_analysis_text,
                ),
                "kind": "report",
            }
            self._add_grounding_metadata(payload, evidence_packet)
            return ToolPlan(
                tool_name=tool_name,
                payload=payload,
            )

        if tool_name == "create_message_draft":
            payload = {
                "title": self._message_draft_title(turn.text, fallback="Message Draft"),
                "content": self._build_message_draft_content(
                    turn,
                    evidence_packet=evidence_packet,
                    specialist_analysis_text=specialist_analysis_text,
                    context_summary=context_summary,
                ),
                "kind": "message_draft",
            }
            self._add_grounding_metadata(payload, evidence_packet)
            return ToolPlan(
                tool_name=tool_name,
                payload=payload,
            )

        if tool_name == "create_task":
            return ToolPlan(
                tool_name=tool_name,
                payload={
                    "title": self._title_from_request(turn.text, fallback="New Task"),
                    "details": self._build_task_details(
                        turn,
                        specialist_analysis_text=specialist_analysis_text,
                    ),
                    "status": "open",
                },
            )

        if tool_name == "create_checklist":
            payload = {
                "title": self._title_from_request(turn.text, fallback="Checklist"),
                "content": self._build_checklist_content(
                    turn,
                    retrieval_results,
                    evidence_packet=evidence_packet,
                    specialist_analysis_text=specialist_analysis_text,
                    context_assets=context_assets or [],
                    context_summary=context_summary,
                ),
                "kind": "checklist",
            }
            self._add_grounding_metadata(payload, evidence_packet)
            return ToolPlan(
                tool_name=tool_name,
                payload=payload,
            )

        if tool_name == "log_observation":
            return ToolPlan(
                tool_name=tool_name,
                payload={
                    "title": self._title_from_request(turn.text, fallback="Observation"),
                    "content": turn.text.strip(),
                    "kind": "observation",
                },
            )

        if tool_name == "generate_heatmap_overlay":
            source_asset = self._select_image_asset(context_assets or [])
            return ToolPlan(
                tool_name=tool_name,
                payload={
                    "title": self._heatmap_title(source_asset),
                    "source_asset_id": source_asset.id if source_asset else None,
                    "source_display_name": source_asset.display_name if source_asset else None,
                    "care_context": (
                        source_asset.care_context.value
                        if source_asset
                        else AssetCareContext.GENERAL.value
                    ),
                    "request": turn.text.strip(),
                },
            )

        if tool_name == "export_brief":
            content = self._build_note_content(
                turn,
                evidence_packet=evidence_packet,
                specialist_analysis_text=specialist_analysis_text,
            )
            title = self._export_title(turn.text, content, fallback="Field Brief")
            payload = {
                "conversation_id": turn.conversation_id,
                "title": title,
                "content": content,
                "export_type": "markdown",
                "destination_path": self._default_export_path(title),
            }
            self._add_grounding_metadata(payload, evidence_packet)
            return ToolPlan(
                tool_name=tool_name,
                payload=payload,
            )

        return ToolPlan(tool_name=tool_name, payload={"request": turn.text.strip()})

    def execute(self, tool_name: str, payload: dict[str, object]) -> dict[str, object]:
        if tool_name in {
            "create_note",
            "create_report",
            "create_message_draft",
            "create_checklist",
            "log_observation",
        }:
            note = self.store.create_note(
                title=str(payload.get("title", "Untitled Note")),
                content=str(payload.get("content", "")),
                kind=str(payload.get("kind", "note")),
            )
            return {
                "entity_type": self._note_entity_type(note.kind),
                "entity_id": note.id,
                "title": note.title,
                "kind": note.kind,
            }

        if tool_name == "create_task":
            task = self.store.create_task(
                title=str(payload.get("title", "Untitled Task")),
                details=str(payload.get("details", "")) or None,
                status=str(payload.get("status", "open")),
            )
            return {
                "entity_type": "task",
                "entity_id": task.id,
                "title": task.title,
                "status": task.status,
            }

        if tool_name == "generate_heatmap_overlay":
            return self._execute_heatmap_overlay(payload)

        if tool_name == "export_brief":
            return self._execute_markdown_export(payload)

        return {
            "entity_type": "noop",
            "tool_name": tool_name,
            "message": "No executor is implemented for this tool yet.",
        }

    def merge_edited_payload(
        self,
        tool_name: str,
        base_payload: dict[str, object],
        edited_payload: dict[str, object] | None,
    ) -> dict[str, object]:
        merged = dict(base_payload)
        if not edited_payload:
            return merged

        if tool_name in {
            "create_note",
            "create_report",
            "create_message_draft",
            "create_checklist",
            "log_observation",
        }:
            title = self._edited_text(edited_payload.get("title"), max_chars=120)
            content = self._edited_text(edited_payload.get("content"), max_chars=12000)
            kind = self._edited_kind(tool_name, edited_payload.get("kind"))
            if title is not None:
                merged["title"] = title
            if content is not None:
                merged["content"] = content
            if kind is not None:
                merged["kind"] = kind
            self._validate_grounded_edit(tool_name, base_payload, merged, edited_payload)
            return merged

        if tool_name == "create_task":
            title = self._edited_text(edited_payload.get("title"), max_chars=120)
            details = self._edited_text(edited_payload.get("details"), max_chars=12000)
            status = self._edited_task_status(edited_payload.get("status"))
            if title is not None:
                merged["title"] = title
            if details is not None:
                merged["details"] = details
            if status is not None:
                merged["status"] = status
            return merged

        if tool_name == "export_brief":
            title = self._edited_text(edited_payload.get("title"), max_chars=120)
            content = self._edited_text(edited_payload.get("content"), max_chars=12000)
            if title is not None:
                merged["title"] = title
                merged["destination_path"] = self._default_export_path(title)
            if content is not None:
                merged["content"] = content
            self._validate_grounded_edit(tool_name, base_payload, merged, edited_payload)
            return merged

        return merged

    def revise_pending_payload(
        self,
        tool_name: str,
        base_payload: dict[str, object],
        instruction: str,
    ) -> dict[str, object] | None:
        lowered = instruction.lower().strip()
        if not lowered:
            return None

        edited: dict[str, object] = {}
        title = str(base_payload.get("title") or "").strip()

        explicit_title = self._extract_requested_title(instruction)
        if explicit_title:
            edited["title"] = explicit_title

        if tool_name in {
            "create_note",
            "create_report",
            "create_message_draft",
            "create_checklist",
            "log_observation",
            "export_brief",
        }:
            if self._looks_like_tighten_request(lowered):
                if not explicit_title and title:
                    tighter_title = self._tighten_title(title)
                    if tighter_title and tighter_title != title:
                        edited["title"] = tighter_title
                original_content = str(base_payload.get("content") or "")
                tightened = self._tighten_content(original_content)
                if tightened and tightened.strip() != original_content.strip():
                    edited["content"] = tightened
                else:
                    further_tightened = self._tighten_content_further(original_content)
                    if further_tightened and further_tightened.strip() != original_content.strip():
                        edited["content"] = further_tightened

        if tool_name == "create_task":
            if self._looks_like_tighten_request(lowered):
                if not explicit_title and title:
                    tighter_title = self._tighten_title(title)
                    if tighter_title and tighter_title != title:
                        edited["title"] = tighter_title
                original_details = str(base_payload.get("details") or "")
                tightened = self._tighten_content(original_details)
                if tightened and tightened.strip() != original_details.strip():
                    edited["details"] = tightened

        if not edited:
            return None

        merged = self.merge_edited_payload(tool_name, base_payload, edited)
        return merged if merged != base_payload else None

    def revise_pending_payload_selection(
        self,
        tool_name: str,
        base_payload: dict[str, object],
        selection: CanvasSelectionContext,
    ) -> dict[str, object] | None:
        if selection.action == CanvasSelectionEditAction.EXPLAIN:
            return None

        field_name = selection.field_name or "content"
        if field_name not in {"content", "details"}:
            return None
        if field_name == "details" and tool_name != "create_task":
            return None
        if field_name == "content" and tool_name == "create_task":
            return None

        current_payload = dict(selection.current_payload or {})
        effective_payload = (
            self.merge_edited_payload(tool_name, base_payload, current_payload)
            if current_payload
            else dict(base_payload)
        )

        target_text = (
            selection.visible_content
            if isinstance(selection.visible_content, str)
            else str(effective_payload.get(field_name) or "")
        )
        if selection.end <= selection.start or selection.end > len(target_text):
            return None
        if target_text[selection.start : selection.end] != selection.text:
            field_text = str(effective_payload.get(field_name) or "")
            if (
                selection.end > len(field_text)
                or field_text[selection.start : selection.end] != selection.text
            ):
                return None
            target_text = field_text

        replacement = self.transform_selected_canvas_text(selection.text, selection.action)
        if replacement == selection.text:
            return None

        next_text = (
            target_text[: selection.start]
            + replacement
            + target_text[selection.end :]
        )
        edited_payload = dict(current_payload)
        if field_name == "content":
            edited_payload["content"] = self._compose_selected_canvas_content(
                tool_name=tool_name,
                base_payload=base_payload,
                effective_payload=effective_payload,
                next_visible_content=next_text,
            )
        else:
            edited_payload[field_name] = next_text

        merged = self.merge_edited_payload(tool_name, base_payload, edited_payload)
        return merged if merged != base_payload else None

    def transform_selected_canvas_text(
        self,
        text: str,
        action: CanvasSelectionEditAction,
    ) -> str:
        if action == CanvasSelectionEditAction.SHORTEN:
            return self._shorten_selection_text(text)
        if action == CanvasSelectionEditAction.NEUTRAL:
            return self._neutralize_selection_text(text)
        if action == CanvasSelectionEditAction.REWRITE:
            return self._rewrite_selection_text(text)
        return text

    def explain_selection_text(self, text: str) -> str:
        clean = self._clean_selection_body(text)
        if not clean:
            return "That selection is empty, so there is nothing to explain yet."
        return f"That selected text is saying: {self._ensure_terminal_punctuation(clean)}"

    def _title_from_request(self, text: str, *, fallback: str) -> str:
        cleaned = re.sub(r"^(create|make|build|write|log)\s+(a|an|the)?\s*", "", text, flags=re.I)
        cleaned = cleaned.strip().rstrip(".")
        if not cleaned:
            return fallback
        if len(cleaned) > 80:
            cleaned = cleaned[:77].rstrip() + "..."
        return cleaned[:1].upper() + cleaned[1:]

    def _export_title(self, request_text: str, content: str, *, fallback: str) -> str:
        lowered = request_text.lower()
        if "field assistant architecture" in lowered:
            return "Field Assistant Architecture Briefing"
        if "workspace" in lowered and any(token in lowered for token in {"brief", "briefing"}):
            return "Workspace Briefing"
        heading = self._title_from_content(content)
        if heading:
            return heading

        cleaned = re.sub(
            r"\b(and )?(export( it)?|save( it)?)( as)? (markdown|a document|document)\b",
            "",
            request_text,
            flags=re.I,
        )
        cleaned = re.sub(r"\bfrom the relevant files\b", "", cleaned, flags=re.I)
        return self._title_from_request(cleaned, fallback=fallback)

    def _report_title(self, request_text: str, *, fallback: str) -> str:
        lowered = request_text.lower()
        if "field assistant architecture" in lowered:
            return "Field Assistant Architecture Report"

        cleaned = re.sub(
            r"\b(create|make|build|write|prepare|draft)\b",
            "",
            request_text,
            flags=re.I,
        )
        cleaned = re.sub(r"\b(short|concise|brief)\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\ba\b|\ban\b|\bthe\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\breport\b", "", cleaned, flags=re.I)
        cleaned = re.sub(
            r"\b(using|from)\s+(relevant\s+)?workspace files\b",
            "",
            cleaned,
            flags=re.I,
        )
        cleaned = re.sub(
            r"\b(using|from)\s+(the\s+)?relevant\s+workspace\s+files\b",
            "",
            cleaned,
            flags=re.I,
        )
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" .-")
        title = self._title_from_request(cleaned, fallback=fallback)
        if "report" not in title.lower():
            title = f"{title} Report"
        return title

    def _message_draft_title(self, request_text: str, *, fallback: str) -> str:
        lowered = request_text.lower()
        if "logistics lead" in lowered and any(
            token in lowered for token in {"shortage", "shortages", "supply", "supplies"}
        ):
            return "Logistics Lead Shortage Update Draft"

        cleaned = re.sub(
            r"\b(create|make|build|write|prepare|draft)\b",
            "",
            request_text,
            flags=re.I,
        )
        cleaned = re.sub(r"\b(short|brief|quick)\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\ba\b|\ban\b|\bthe\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\b(reply|response|message|email|text)\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\b(those|same)\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"^\s*to\s+", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" .-")
        title = self._title_from_request(cleaned, fallback=fallback)
        if "draft" not in title.lower():
            title = f"{title} Draft"
        return title

    def _title_from_content(self, content: str) -> str | None:
        for raw_line in content.splitlines():
            line = raw_line.strip().lstrip("#").strip()
            if not line:
                continue
            if line.endswith(":"):
                continue
            if line.startswith("- ") or re.match(r"^\d+\.\s+", line):
                continue
            if len(line) > 88:
                continue
            return line
        return None

    def _build_report_content(
        self,
        turn: ConversationTurnRequest,
        *,
        evidence_packet: EvidencePacket | None = None,
        specialist_analysis_text: str | None = None,
    ) -> str:
        title = self._report_title(turn.text, fallback="Field Report")
        if evidence_packet is None and not specialist_analysis_text:
            return self._conversation_report_content(turn.text, title=title)
        content = self._build_note_content(
            turn,
            evidence_packet=evidence_packet,
            specialist_analysis_text=specialist_analysis_text,
        ).strip()
        if content.startswith("# "):
            return content
        if content.lower().startswith(title.lower()):
            return f"# {title}\n\n{content[len(title):].lstrip()}"
        return f"# {title}\n\n{content}"

    def _conversation_report_content(self, request_text: str, *, title: str) -> str:
        focus = self._report_focus_from_request(request_text)
        return "\n".join(
            [
                f"# {title}",
                "",
                "## Summary",
                f"This draft captures a concise report about {focus}.",
                "",
                "Key points:",
                f"- Focus on the main structure, responsibilities, and current constraints around {focus}.",
                "- Keep the report practical and easy to review before it is saved locally.",
                "- Confirm the strongest supporting details or examples before finalizing it.",
                "- Tighten or retitle the draft if the audience needs a shorter version.",
            ]
        ).strip()

    def _report_focus_from_request(self, request_text: str) -> str:
        lowered = request_text.lower()
        if "field assistant architecture" in lowered:
            return "the current field assistant architecture"

        cleaned = re.sub(
            r"\b(create|make|build|write|prepare|draft|summarize|summarise)\b",
            "",
            request_text,
            flags=re.I,
        )
        cleaned = re.sub(r"\b(short|brief|concise|current)\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\ba\b|\ban\b|\bthe\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\breport\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" .-")
        if not cleaned:
            return "the current topic"
        normalized = cleaned[:1].lower() + cleaned[1:]
        if normalized.startswith(("this ", "that ", "these ", "those ")):
            return normalized
        return f"the {normalized}"

    def _build_message_draft_content(
        self,
        turn: ConversationTurnRequest,
        *,
        evidence_packet: EvidencePacket | None = None,
        specialist_analysis_text: str | None = None,
        context_summary: str | None = None,
    ) -> str:
        if not self._looks_like_workspace_synthesis_request(turn.text):
            context_message = self._message_draft_from_context_summary(context_summary)
            if context_message:
                return self._format_message_draft(context_message)

            if evidence_packet and evidence_packet.facts:
                body = self._message_draft_from_evidence_packet(evidence_packet)
                if body:
                    return self._format_message_draft(body)

            if specialist_analysis_text:
                cleaned = self._clean_specialist_text(specialist_analysis_text).strip()
                if cleaned and not self._looks_like_raw_message_source(cleaned):
                    return self._format_message_draft(cleaned)

        request = turn.text.strip().rstrip(".")
        request = re.sub(
            r"^(create|make|build|write|prepare|draft)\s+(a|an|the)?\s*(reply|response|message|email|text)\s*(to\s+)?",
            "",
            request,
            flags=re.I,
        ).strip()
        if not request:
            request = "Thanks. Here is the message draft."
        request = request[:1].upper() + request[1:]
        return self._format_message_draft(request)

    def _format_message_draft(self, body: str) -> str:
        compact = body.strip()
        if not compact:
            compact = "Thanks. Here is the message draft."
        if compact.lower().startswith(("hi,", "hello,", "dear ")):
            return compact
        return f"Hi,\n\n{compact}\n\nBest,"

    def _message_draft_from_context_summary(self, context_summary: str | None) -> str | None:
        cleaned = self._clean_specialist_text(context_summary or "").strip()
        if not cleaned or self._looks_like_raw_message_source(cleaned):
            return None

        shortages = self._labeled_section_items(cleaned, [r"shortages?"])
        actions = self._labeled_section_items(
            cleaned,
            [r"prioritized\s+actions?", r"recommended\s+actions?", r"next\s+actions?"],
        )

        if shortages:
            body = f"Before departure, we still need {self._join_human_list(shortages)}."
            if actions:
                primary_action = actions[0].rstrip(".")
                body += f" First priority is to {self._lowercase_leading_token(primary_action)}."
                if len(actions) > 1:
                    follow_up = actions[1].rstrip(".")
                    body += f" After that, {self._lowercase_leading_token(follow_up)}."
            return body

        return cleaned

    def _labeled_section_items(self, text: str, label_patterns: list[str]) -> list[str]:
        normalized = " ".join(text.replace("\r", "\n").replace("\n", " ").split())
        if not normalized:
            return []

        items: list[str] = []
        label_group = "|".join(label_patterns)
        match = re.search(
            rf"(?:{label_group})\s*:\s*(.+?)(?:(?:shortages?|prioritized\s+actions?|recommended\s+actions?|next\s+actions?)\s*:|$)",
            normalized,
            flags=re.I,
        )
        if not match:
            return []

        for raw_item in re.split(r"[.;]|,|\band\b", match.group(1), flags=re.I):
            cleaned = raw_item.strip(" .:-")
            if len(cleaned) < 3:
                continue
            items.append(cleaned)
        return items[:4]

    def _join_human_list(self, items: list[str]) -> str:
        if not items:
            return ""
        normalized = [self._lowercase_leading_token(item.strip()) for item in items if item.strip()]
        if not normalized:
            return ""
        if len(normalized) == 1:
            return normalized[0]
        if len(normalized) == 2:
            return f"{normalized[0]} and {normalized[1]}"
        return f"{', '.join(normalized[:-1])}, and {normalized[-1]}"

    def _looks_like_raw_message_source(self, text: str) -> bool:
        lowered = " ".join(text.split()).lower()
        if "visible text extracted from the image" in lowered:
            return True
        digit_count = sum(char.isdigit() for char in lowered)
        uppercase_tokens = re.findall(r"\b[A-Z0-9]{2,}\b", text)
        short_line_tokens = len(re.findall(r"\b[a-z]{2,}\b", lowered))
        return digit_count >= 3 and bool(uppercase_tokens) and short_line_tokens >= 6

    def _note_entity_type(self, kind: str) -> str:
        normalized = kind.strip().lower()
        mapping = {
            "note": "note",
            "report": "report",
            "message_draft": "message draft",
            "checklist": "checklist",
            "observation": "observation",
        }
        return mapping.get(normalized, "note")

    def _edited_text(self, value: object, *, max_chars: int) -> str | None:
        if value is None:
            return None
        text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return None
        return text[:max_chars]

    def _edited_kind(self, tool_name: str, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        allowed_by_tool = {
            "create_note": {"note", "observation"},
            "create_report": {"report"},
            "create_message_draft": {"message_draft"},
            "create_checklist": {"checklist"},
            "log_observation": {"observation"},
        }
        if normalized in allowed_by_tool.get(tool_name, set()):
            return normalized
        return None

    def _edited_task_status(self, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in {"open", "in_progress", "blocked", "done"}:
            return normalized
        return None

    def _looks_like_tighten_request(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in {"shorten", "shorter", "tighten", "trim", "condense", "more concise"}
        )

    def _extract_requested_title(self, instruction: str) -> str | None:
        patterns = (
            r"\b(?:rename|retitle)\s+(?:that|this|the)?\s*(?:draft|note|report|message|reply|email|checklist|task|export|markdown|document)?\s*to\s+[\"“]?(.+?)[\"”]?(?:[.?!]|$)",
            r"\bcall\s+(?:it|that|this)\s+[\"“]?(.+?)[\"”]?(?:[.?!]|$)",
            r"\btitle\s+(?:it|that|this)\s+[\"“]?(.+?)[\"”]?(?:[.?!]|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, instruction, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = match.group(1).strip().strip("\"'“”")
            candidate = re.sub(r"\s{2,}", " ", candidate).strip(" -")
            if candidate:
                return candidate[:120]
        return None

    def _compose_selected_canvas_content(
        self,
        *,
        tool_name: str,
        base_payload: dict[str, object],
        effective_payload: dict[str, object],
        next_visible_content: str,
    ) -> str:
        if tool_name not in {"create_note", "create_report", "export_brief", "log_observation"}:
            return next_visible_content
        if not (
            self._payload_uses_title_heading(base_payload)
            or self._payload_uses_title_heading(effective_payload)
        ):
            return next_visible_content

        title = str(effective_payload.get("title") or base_payload.get("title") or "").strip()
        content = next_visible_content.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not title or not content:
            return next_visible_content

        lines = content.split("\n")
        first_meaningful_index = next(
            (
                index
                for index, line in enumerate(lines)
                if self._strip_markdown_to_text(line).strip()
            ),
            None,
        )
        if first_meaningful_index is not None:
            first_raw = lines[first_meaningful_index].strip()
            first_text = self._strip_markdown_to_text(first_raw).strip().lower()
            if re.match(r"^#{1,6}\s+", first_raw) and first_text == title.lower():
                return content

        return f"# {title}\n\n{content}"

    def _payload_uses_title_heading(self, payload: dict[str, object]) -> bool:
        title = self._strip_markdown_to_text(str(payload.get("title") or "")).strip().lower()
        content = str(payload.get("content") or "")
        if not title or not content.strip():
            return False
        for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if not self._strip_markdown_to_text(line).strip():
                continue
            first_raw = line.strip()
            first_text = self._strip_markdown_to_text(first_raw).strip().lower()
            return bool(re.match(r"^#{1,6}\s+", first_raw)) and first_text == title
        return False

    def _split_selection_prefix(self, text: str) -> tuple[str, str]:
        match = re.match(r"^(\s*(?:[-*+]\s+|\d+\.\s+|#{1,6}\s+|>\s*)?)([\s\S]*?)$", str(text or ""))
        if not match:
            return "", str(text or "")
        return match.group(1), match.group(2)

    def _sentence_case(self, text: str) -> str:
        trimmed = str(text or "").strip()
        if not trimmed:
            return ""
        return f"{trimmed[0].upper()}{trimmed[1:]}"

    def _ensure_terminal_punctuation(self, text: str) -> str:
        trimmed = str(text or "").strip()
        if not trimmed or re.search(r"[.!?]$", trimmed):
            return trimmed
        return f"{trimmed}."

    def _strip_markdown_to_text(self, text: str) -> str:
        cleaned = str(text or "")
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        cleaned = re.sub(r"^\s*#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*>\s+", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)
        cleaned = cleaned.replace("*", "").replace("_", "").replace("~", "")
        return cleaned

    def _clean_selection_body(self, text: str) -> str:
        return re.sub(
            r"\s+([,.;:!?])",
            r"\1",
            re.sub(r"\s+", " ", self._strip_markdown_to_text(text)),
        ).strip()

    def _shorten_selection_text(self, text: str) -> str:
        prefix, body = self._split_selection_prefix(text)
        clean = self._clean_selection_body(body)
        replacements = (
            (r"\b(currently|really|very|clearly|basically|immediately|actually)\b", ""),
            (
                r"\b(main structure, responsibilities, and current constraints)\b",
                "structure and constraints",
            ),
            (r"\bbefore (?:it is|it's|we are|we're)?\s*saved locally\b", "before saving"),
            (r"\bif the audience needs a shorter version\b", "for the audience"),
        )
        for pattern, replacement in replacements:
            clean = re.sub(pattern, replacement, clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s{2,}", " ", clean).strip()
        first_sentence = re.split(r"(?<=[.!?])\s+", clean)[0] if clean else ""
        if len(first_sentence) > 120:
            first_sentence = f"{first_sentence[:117].rstrip()}..."
        shortened = self._ensure_terminal_punctuation(first_sentence)
        return f"{prefix}{self._sentence_case(shortened)}"

    def _neutralize_selection_text(self, text: str) -> str:
        prefix, body = self._split_selection_prefix(text)
        clean = self._clean_selection_body(body)
        replacements = (
            (r"\bmust\b", "should"),
            (r"\bwill\b", "may"),
            (r"\bdefinitely\b", "may"),
            (r"\bclearly\b", "carefully"),
            (r"\bimmediately\b", "soon"),
            (r"\bstrongest\b", "best-supported"),
            (r"\bstrong\b", "well-supported"),
            (r"\burgent\b", "important"),
            (r"\bclaims?\b", "points"),
            (r"\bprove\b", "support"),
        )
        for pattern, replacement in replacements:
            clean = re.sub(pattern, replacement, clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s{2,}", " ", clean).strip()
        return f"{prefix}{self._ensure_terminal_punctuation(self._sentence_case(clean))}"

    def _rewrite_selection_text(self, text: str) -> str:
        prefix, body = self._split_selection_prefix(text)
        clean = self._ensure_terminal_punctuation(
            self._sentence_case(self._clean_selection_body(body))
        )
        return f"{prefix}{clean}"

    def _tighten_title(self, title: str) -> str | None:
        revised = title
        replacements = (
            ("current ", ""),
            ("relevant ", ""),
            ("workspace ", ""),
            ("architecture overview", "Architecture Brief"),
            ("briefing", "Brief"),
        )
        for old, new in replacements:
            revised = re.sub(old, new, revised, flags=re.IGNORECASE)
        revised = re.sub(r"\s{2,}", " ", revised).strip(" -")
        if not revised or revised.lower() == title.lower():
            return None
        return revised[:120]

    def _tighten_content(self, content: str) -> str | None:
        normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return None

        lines = [line.rstrip() for line in normalized.split("\n")]
        meaningful = [line.strip() for line in lines if line.strip()]
        if not meaningful:
            return None

        output: list[str] = []
        heading = meaningful[0]
        if heading.startswith("#") or (len(heading) <= 88 and not heading.endswith(":")):
            output.append(heading)

        key_point_index = next(
            (index for index, line in enumerate(meaningful) if line.lower().startswith("key points:")),
            None,
        )
        if key_point_index is not None:
            output.append("Key points:")
            bullets = [
                line
                for line in meaningful[key_point_index + 1 :]
                if re.match(r"^[-*+]\s+|^\d+\.\s+", line)
            ]
            if bullets:
                output.extend(bullets[:3])
                return "\n".join(self._dedupe_preserving_order(output)).strip()

        bullets = [line for line in meaningful if re.match(r"^[-*+]\s+|^\d+\.\s+", line)]
        if bullets:
            output.extend(bullets[:3])
            return "\n".join(self._dedupe_preserving_order(output)).strip()

        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", normalized) if paragraph.strip()]
        if output and paragraphs:
            first_paragraph = paragraphs[0].strip()
            if self._normalize_heading(first_paragraph) == self._normalize_heading(output[0]):
                paragraphs = paragraphs[1:]
        clipped = [self._clip_sentence_block(paragraph, 220) for paragraph in paragraphs[:2]]
        output.extend(block for block in clipped if block)
        tightened = "\n\n".join(self._dedupe_preserving_order(output)).strip()
        return tightened or self._clip_sentence_block(normalized, 320)

    def _tighten_content_further(self, content: str) -> str | None:
        normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return None

        lines = [line.rstrip() for line in normalized.split("\n")]
        meaningful = [line.strip() for line in lines if line.strip()]
        if not meaningful:
            return None

        output: list[str] = []
        heading = meaningful[0]
        if heading.startswith("#") or (len(heading) <= 88 and not heading.endswith(":")):
            output.append(heading)

        key_point_index = next(
            (index for index, line in enumerate(meaningful) if line.lower().startswith("key points:")),
            None,
        )
        if key_point_index is not None:
            bullets = [
                line
                for line in meaningful[key_point_index + 1 :]
                if re.match(r"^[-*+]\s+|^\d+\.\s+", line)
            ]
            if bullets:
                output.append("Key points:")
                if len(bullets) >= 2:
                    output.append(bullets[0])
                    output.append(bullets[1])
                else:
                    output.append(self._clip_bullet_line(bullets[0], 140))
                tightened = "\n".join(self._dedupe_preserving_order(output)).strip()
                return tightened if tightened != normalized else None

        bullets = [line for line in meaningful if re.match(r"^[-*+]\s+|^\d+\.\s+", line)]
        if bullets:
            output.append(self._clip_bullet_line(bullets[0], 140))
            tightened = "\n".join(self._dedupe_preserving_order(output)).strip()
            return tightened if tightened != normalized else None

        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", normalized) if paragraph.strip()]
        if output and paragraphs:
            first_paragraph = paragraphs[0].strip()
            if self._normalize_heading(first_paragraph) == self._normalize_heading(output[0]):
                paragraphs = paragraphs[1:]
        if paragraphs:
            output.append(self._clip_sentence_block(paragraphs[0], 160))
            tightened = "\n\n".join(self._dedupe_preserving_order(output)).strip()
            return tightened if tightened != normalized else None
        return None

    def _clip_bullet_line(self, bullet: str, max_chars: int) -> str:
        match = re.match(r"^([-*+]\s+|\d+\.\s+)(.*)$", bullet)
        if not match:
            return self._clip_sentence_block(bullet, max_chars)
        prefix, body = match.groups()
        clipped_body = self._clip_sentence_block(body, max_chars)
        return f"{prefix}{clipped_body}".rstrip()

    def _clip_sentence_block(self, text: str, max_chars: int) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) <= max_chars:
            return cleaned
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        clipped: list[str] = []
        total = 0
        for sentence in sentences:
            if not sentence:
                continue
            proposed = total + len(sentence) + (1 if clipped else 0)
            if clipped and proposed > max_chars:
                break
            clipped.append(sentence)
            total = proposed
            if total >= max_chars:
                break
        if clipped:
            return " ".join(clipped)
        return cleaned[: max_chars - 1].rstrip() + "…"

    def _dedupe_preserving_order(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            normalized = self._normalize_heading(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(value)
        return deduped

    def _normalize_heading(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower().lstrip("#").strip())

    def _default_export_path(self, title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "field-brief"
        return str((self.export_storage_dir / f"{slug}.md").resolve())

    def _build_checklist_content(
        self,
        turn: ConversationTurnRequest,
        retrieval_results: list[SearchResultItem],
        *,
        evidence_packet: EvidencePacket | None,
        specialist_analysis_text: str | None,
        context_assets: list[AssetSummary],
        context_summary: str | None,
    ) -> str:
        candidate_item_sets: list[list[str]] = []
        if evidence_packet and evidence_packet.facts:
            packet_items = [f"- [ ] {fact.summary}" for fact in evidence_packet.facts[:5]]
            if packet_items:
                candidate_item_sets.append(packet_items)
        if specialist_analysis_text and not self._looks_like_unavailable_specialist_text(
            specialist_analysis_text
        ):
            specialist_items = self._checklist_items_from_specialist_analysis(
                specialist_analysis_text
            )
            if specialist_items:
                candidate_item_sets.append(specialist_items)

        if context_summary:
            context_items = self._checklist_items_from_specialist_analysis(context_summary)
            if context_items:
                candidate_item_sets.append(context_items)

        if candidate_item_sets:
            best_items = max(candidate_item_sets, key=self._checklist_item_set_score)
            return "\n".join(best_items)

        if any(asset.kind == AssetKind.IMAGE for asset in context_assets):
            return "\n".join(
                [
                    "- [ ] Review the attached image findings",
                    "- [ ] Confirm the urgent items shown",
                    "- [ ] Restock or follow up on the shortages",
                ]
            )

        if retrieval_results:
            excerpt = retrieval_results[0].excerpt
            raw_items = re.split(r",| and ", excerpt)
            items = []
            for item in raw_items:
                cleaned = item.strip(" .")
                if len(cleaned) < 4:
                    continue
                items.append(f"- [ ] {cleaned}")
                if len(items) == 6:
                    break
            if items:
                return "\n".join(items)

        return "\n".join(
            [
                "- [ ] Confirm destination and route",
                "- [ ] Prepare translation and contact materials",
                "- [ ] Pack supplies and backup power",
            ]
        )

    def _checklist_item_set_score(self, items: list[str]) -> tuple[int, int, int]:
        actionable = sum(
            1
            for item in items
            if any(
                token in item.lower()
                for token in {"restock", "top up", "confirm", "buy", "purchase"}
            )
        )
        concise = sum(1 for item in items if len(item) <= 80)
        return (len(items), actionable, concise)

    def _checklist_items_from_specialist_analysis(self, text: str) -> list[str]:
        if self._looks_like_unavailable_specialist_text(text):
            return []
        priority_items = self._priority_items_from_specialist_analysis(text)
        if priority_items:
            return priority_items

        action_items = self._action_items_from_specialist_analysis(text)
        if action_items:
            return action_items

        raw_segments = re.split(r"[\n;]+", text)
        items: list[str] = []
        shortage_subjects: list[str] = []
        shortage_subjects: list[str] = []
        for segment in raw_segments:
            sentences = re.split(r"(?<=[.!?])\s+", segment)
            for sentence in sentences:
                cleaned = sentence.strip(" -*\t")
                cleaned = re.sub(r"^(summary|observation|visible text)\s*:\s*", "", cleaned, flags=re.I)
                cleaned = cleaned.rstrip(".")
                if len(cleaned) < 12:
                    continue
                items.append(f"- [ ] {cleaned}")
                if len(items) == 5:
                    return items
        return items

    def _build_note_content(
        self,
        turn: ConversationTurnRequest,
        *,
        evidence_packet: EvidencePacket | None = None,
        specialist_analysis_text: str | None,
    ) -> str:
        if evidence_packet and evidence_packet.facts:
            if evidence_packet.source_domain.value == "workspace":
                lines = ["Key points:"]
                lines.extend(f"- {fact.summary}" for fact in evidence_packet.facts[:6])
                if evidence_packet.refs:
                    lines.append("")
                    lines.append("Files reviewed:")
                    lines.extend(f"- {ref.label}" for ref in evidence_packet.refs[:6])
                return "\n".join(lines).strip()
            return "\n".join(
                f"- {fact.summary}"
                + (f" ({', '.join(ref.ref for ref in fact.refs)})" if fact.refs else "")
                for fact in evidence_packet.facts[:8]
            )
        if specialist_analysis_text:
            if self._looks_like_workspace_synthesis_request(turn.text):
                if self._looks_like_raw_ocr_payload(specialist_analysis_text):
                    return turn.text.strip()
                cleaned_workspace_note = self._workspace_note_from_synthesis(
                    specialist_analysis_text
                )
                if cleaned_workspace_note:
                    return cleaned_workspace_note
            if any(
                keyword in turn.text.lower()
                for keyword in {"brief", "briefing", "workspace", "report"}
            ):
                return specialist_analysis_text.strip()
            lines = self._normalized_specialist_lines(specialist_analysis_text)
            if lines:
                return "\n".join(f"- {line}" for line in lines[:8])
        return turn.text.strip()

    def _execute_markdown_export(self, payload: dict[str, object]) -> dict[str, object]:
        title = str(payload.get("title") or "Field Brief").strip() or "Field Brief"
        destination_path = Path(
            str(payload.get("destination_path") or self._default_export_path(title))
        ).expanduser()
        if not destination_path.is_absolute():
            destination_path = (self.export_storage_dir / destination_path).resolve()
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        content = str(payload.get("content") or "").strip()
        destination_path.write_text(self._markdown_document(title, content), encoding="utf-8")

        export = self.store.create_export(
            ExportRequest(
                conversation_id=str(payload.get("conversation_id") or ""),
                export_type=str(payload.get("export_type") or "markdown"),
                destination_path=str(destination_path),
            ),
            status="completed",
        )
        return {
            "entity_type": "export",
            "entity_id": export.export_id,
            "title": title,
            "status": export.status,
            "destination_path": str(destination_path),
            "message": f"Exported markdown to {destination_path}.",
        }

    def _markdown_document(self, title: str, content: str) -> str:
        if not content:
            return f"# {title}\n"
        if content.lstrip().startswith("# "):
            return content.rstrip() + "\n"
        return f"# {title}\n\n{content.rstrip()}\n"

    def _build_task_details(
        self,
        turn: ConversationTurnRequest,
        *,
        specialist_analysis_text: str | None,
    ) -> str:
        if specialist_analysis_text:
            priority_items = self._priority_items_from_specialist_analysis(specialist_analysis_text)
            if priority_items:
                return "\n".join(priority_items)
            action_items = self._action_items_from_specialist_analysis(specialist_analysis_text)
            if action_items:
                return "\n".join(action_items)
        return turn.text.strip()

    def _add_grounding_metadata(
        self,
        payload: dict[str, object],
        evidence_packet: EvidencePacket | None,
    ) -> None:
        if evidence_packet is None:
            return
        payload["source_domain"] = evidence_packet.source_domain.value
        payload["evidence_packet_id"] = evidence_packet.id
        payload["source_asset_ids"] = list(evidence_packet.asset_ids)
        payload["grounding_status"] = evidence_packet.grounding_status.value

    def _validate_grounded_edit(
        self,
        tool_name: str,
        base_payload: dict[str, object],
        merged_payload: dict[str, object],
        edited_payload: dict[str, object] | None,
    ) -> None:
        if not edited_payload or not self._is_grounded_draft_payload(base_payload):
            return
        if not self._grounded_body_changed(tool_name, base_payload, merged_payload):
            return

        base_text = self._grounded_edit_text(tool_name, base_payload)
        merged_text = self._grounded_edit_text(tool_name, merged_payload)
        if not base_text or not merged_text:
            return

        base_tokens = self._grounding_tokens(base_text)
        merged_tokens = self._grounding_tokens(merged_text)
        if not base_tokens or not merged_tokens:
            return

        shared_tokens = base_tokens & merged_tokens
        novel_tokens = merged_tokens - base_tokens
        overlap_count = len(shared_tokens)
        merged_overlap = overlap_count / max(len(merged_tokens), 1)
        base_overlap = overlap_count / max(len(base_tokens), 1)
        novel_ratio = len(novel_tokens) / max(len(merged_tokens), 1)
        required_shared = min(12, max(4, len(merged_tokens) // 6))

        if (
            (
                overlap_count < required_shared
                and merged_overlap < 0.45
                and not (merged_overlap >= 0.28 and base_overlap >= 0.18)
            )
            or (
                len(novel_tokens) >= 5
                and novel_ratio > 0.45
                and merged_overlap < 0.62
            )
        ):
            domain = self._grounded_source_label(base_payload)
            raise ValueError(
                f"This draft is grounded in earlier local {domain} evidence. "
                "Please refine or shorten it instead of replacing it or mixing in unrelated content."
            )

    def _is_grounded_draft_payload(self, payload: dict[str, object]) -> bool:
        grounding_status = str(payload.get("grounding_status") or "").lower()
        evidence_packet_id = str(payload.get("evidence_packet_id") or "").strip()
        source_domain = str(payload.get("source_domain") or "").strip()
        return (
            grounding_status in {
                GroundingStatus.GROUNDED.value,
                GroundingStatus.PARTIAL.value,
            }
            and bool(evidence_packet_id)
            and bool(source_domain)
        )

    def _grounded_body_changed(
        self,
        tool_name: str,
        base_payload: dict[str, object],
        merged_payload: dict[str, object],
    ) -> bool:
        field_name = self._grounded_body_field(tool_name)
        if not field_name:
            return False
        return str(base_payload.get(field_name) or "") != str(merged_payload.get(field_name) or "")

    def _grounded_body_field(self, tool_name: str) -> str | None:
        if tool_name == "create_task":
            return "details"
        if tool_name in {
            "create_note",
            "create_report",
            "create_message_draft",
            "create_checklist",
            "log_observation",
            "export_brief",
        }:
            return "content"
        return None

    def _grounded_edit_text(self, tool_name: str, payload: dict[str, object]) -> str:
        parts = [str(payload.get("title") or "").strip()]
        body_field = self._grounded_body_field(tool_name)
        if body_field:
            parts.append(str(payload.get(body_field) or "").strip())
        return "\n".join(part for part in parts if part).strip()

    def _grounding_tokens(self, text: str) -> set[str]:
        stop_words = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "before",
            "but",
            "by",
            "for",
            "from",
            "has",
            "have",
            "in",
            "into",
            "is",
            "it",
            "its",
            "local",
            "of",
            "on",
            "or",
            "that",
            "the",
            "their",
            "this",
            "to",
            "with",
            "you",
            "your",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if len(token) >= 3 and token not in stop_words
        }

    def _grounded_source_label(self, payload: dict[str, object]) -> str:
        domain = str(payload.get("source_domain") or "").strip().lower()
        if domain == "video":
            return "video"
        if domain == "image":
            return "image"
        if domain == "document":
            return "document"
        if domain == "workspace":
            return "workspace"
        return "grounded"

    def _message_draft_from_evidence_packet(
        self, evidence_packet: EvidencePacket
    ) -> str | None:
        if evidence_packet.grounding_status == GroundingStatus.UNAVAILABLE:
            return None
        fact_text = [fact.summary.rstrip(".") for fact in evidence_packet.facts[:3] if fact.summary.strip()]
        if not fact_text:
            return None
        if evidence_packet.source_domain.value == "video":
            return (
                "I reviewed the local video evidence. "
                + " ".join(fact_text[:2])
            )
        if evidence_packet.source_domain.value == "document":
            return (
                "I reviewed the local document. "
                + " ".join(fact_text[:2])
            )
        return " ".join(fact_text[:2])

    def _looks_like_workspace_synthesis_request(self, text: str) -> bool:
        lowered = text.lower()
        scope_tokens = {"workspace", "project", "repo", "repository", "folder", "file", "files"}
        action_tokens = {"brief", "briefing", "summary", "summarize", "summarise", "architecture", "report"}
        return any(token in lowered for token in scope_tokens) and any(
            token in lowered for token in action_tokens
        )

    def _looks_like_raw_ocr_payload(self, text: str) -> bool:
        lowered = text.lower().strip()
        return lowered.startswith("visible text extracted from the image:")

    def _looks_like_unavailable_specialist_text(self, text: str) -> bool:
        lowered = " ".join(text.split()).lower()
        return any(
            marker in lowered
            for marker in {
                "no local vision specialist model is available",
                "no local video specialist model is available",
                "not available for this follow-up turn",
                "attachment metadata only",
                "cannot make pixel-level claims",
            }
        )

    def _workspace_note_from_synthesis(self, text: str) -> str | None:
        cleaned = text.strip()
        if not cleaned:
            return None

        filtered_lines: list[str] = []
        skipped_lede = False
        previous_blank = True

        for raw_line in cleaned.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw_line.strip()
            lowered = line.lower()

            if not line:
                if not previous_blank and filtered_lines:
                    filtered_lines.append("")
                previous_blank = True
                continue

            if not skipped_lede and (
                lowered.startswith("i reviewed ")
                or lowered.startswith("i reviewed the allowed workspace scope")
            ):
                skipped_lede = True
                continue

            if re.match(r"^(related docs|related brief|related local docs|working title)\s*:", lowered):
                continue
            if re.match(r"^[-*+]\s+\[[^\]]+\]\([^)]+\)\s*$", line):
                continue

            filtered_lines.append(line)
            previous_blank = False

        result = "\n".join(filtered_lines).replace("\n\n\n", "\n\n").strip()
        return result or cleaned

    def _priority_items_from_specialist_analysis(self, text: str) -> list[str]:
        items: list[str] = []
        items.extend(self._labeled_summary_items(text))
        lines = self._normalized_specialist_lines(text)

        for line in lines:
            lowered = line.lower()
            if lowered.startswith("action note:"):
                action_text = line.split(":", 1)[1].strip().rstrip(".")
                for chunk in re.split(r"\band\b|,", action_text, flags=re.I):
                    cleaned = chunk.strip()
                    if len(cleaned) < 4:
                        continue
                    items.append(f"- [ ] {cleaned[:1].upper() + cleaned[1:]}")

            match_low = re.match(r"(.+?)\s+low$", line, flags=re.I)
            if match_low:
                subject = match_low.group(1).strip()
                if ":" in subject:
                    subject = subject.split(":", 1)[-1].strip()
                checklist_item = self._checklist_item_for_shortage(subject)
                if checklist_item:
                    items.append(checklist_item)
                continue

            if "needs top" in lowered and ":" not in line:
                subject = re.split(r"_|needs", line, maxsplit=1, flags=re.I)[0].strip()
                if subject:
                    items.append(f"- [ ] Top up {self._lowercase_leading_token(subject)}")

        items.extend(self._shortage_sentence_items(text))

        deduped: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = item.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(item)
            if len(deduped) == 5:
                break
        return deduped

    def _labeled_summary_items(self, text: str) -> list[str]:
        normalized = " ".join(text.replace("\r", "\n").replace("\n", " ").split())
        if not normalized:
            return []

        items: list[str] = []
        shortage_subjects: list[str] = []

        shortage_match = re.search(
            r"shortages?\s*:\s*(.+?)(?:(?:prioritized|recommended|next)\s+actions?\s*:|$)",
            normalized,
            flags=re.I,
        )
        if shortage_match:
            raw_items = re.split(r"[.;]|,|\band\b", shortage_match.group(1), flags=re.I)
            for raw_item in raw_items:
                cleaned = raw_item.strip(" .:-")
                if len(cleaned) < 4:
                    continue
                shortage_subjects.append(cleaned)
                checklist_item = self._checklist_item_for_shortage(cleaned)
                if checklist_item:
                    items.append(checklist_item)

        action_match = re.search(
            r"(?:prioritized|recommended|next)\s+actions?\s*:\s*(.+?)(?:$)",
            normalized,
            flags=re.I,
        )
        if action_match:
            raw_actions = re.split(r"[.;]|,|\band\b", action_match.group(1), flags=re.I)
            for raw_action in raw_actions:
                cleaned = raw_action.strip(" .:-")
                if len(cleaned) < 4:
                    continue
                normalized_action = cleaned[:1].upper() + cleaned[1:]
                if normalized_action.lower().startswith("top up "):
                    matched_shortage = self._matching_shortage_subject(
                        normalized_action[7:], shortage_subjects
                    )
                    if matched_shortage:
                        normalized_action = f"Top up {self._lowercase_leading_token(matched_shortage)}"
                items.append(f"- [ ] {normalized_action}")

        deduped: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized_item = item.lower()
            if normalized_item in seen:
                continue
            seen.add(normalized_item)
            deduped.append(item)
            if len(deduped) == 5:
                break
        return deduped

    def _matching_shortage_subject(
        self, action_subject: str, shortage_subjects: list[str]
    ) -> str | None:
        lowered_action = action_subject.lower()
        action_tokens = {
            token
            for token in re.split(r"[^a-z0-9]+", lowered_action)
            if token and token not in {"the", "a", "an", "up"}
        }
        if not action_tokens:
            return None

        best_match: str | None = None
        best_score = 0
        for shortage in shortage_subjects:
            shortage_tokens = {
                token
                for token in re.split(r"[^a-z0-9]+", shortage.lower())
                if token and token not in {"the", "a", "an"}
            }
            overlap = len(action_tokens & shortage_tokens)
            if overlap > best_score:
                best_score = overlap
                best_match = shortage

        if best_score == 0:
            return None
        return best_match

    def _lowercase_leading_token(self, text: str) -> str:
        if not text:
            return text
        return text[:1].lower() + text[1:]

    def _shortage_sentence_items(self, text: str) -> list[str]:
        normalized = " ".join(text.replace("\r", "\n").replace("\n", " ").split())
        if not normalized:
            return []

        items: list[str] = []
        patterns = (
            r"(?:two|clearest|main|biggest|key)\s+shortages?\s+(?:are|were)\s+(.+?)(?:\.|$)",
            r"shortages?\s+(?:are|were)\s+(.+?)(?:\.|$)",
            r"shortage\s+(?:is|was)\s+(.+?)(?:\.|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.I)
            if not match:
                continue
            raw_items = re.split(r",|\band\b", match.group(1), flags=re.I)
            for raw_item in raw_items:
                cleaned = re.sub(
                    r"\b(?:because|since|which|that)\b.*$",
                    "",
                    raw_item,
                    flags=re.I,
                ).strip(" .:-")
                cleaned = re.sub(r"^(the|a|an)\s+", "", cleaned, flags=re.I)
                if len(cleaned) < 4:
                    continue
                checklist_item = self._checklist_item_for_shortage(cleaned)
                if checklist_item:
                    items.append(checklist_item)
            if items:
                break
        return items

    def _checklist_item_for_shortage(self, shortage: str) -> str | None:
        cleaned = shortage.strip()
        if not cleaned:
            return None
        display_text = self._lowercase_leading_token(cleaned)
        lowered = cleaned.lower()
        if any(token in lowered for token in {"credit", "credits", "airtime", "top-up", "top up"}):
            return f"- [ ] Top up {display_text}"
        if any(
            token in lowered
            for token in {
                "battery",
                "batteries",
                "tablet",
                "tablets",
                "salt",
                "salts",
                "kit",
                "kits",
                "forms",
                "supply",
                "supplies",
            }
        ):
            return f"- [ ] Restock {display_text}"
        return f"- [ ] Confirm {display_text}"

    def _action_items_from_specialist_analysis(self, text: str) -> list[str]:
        items: list[str] = []
        lines = self._normalized_specialist_lines(text)

        for line in lines:
            if re.match(r"^\d{1,2}:\d{2}\s+", line):
                action = re.sub(r"^\d{1,2}:\d{2}\s+", "", line).strip()
                if action:
                    items.append(f"- [ ] {action}")
                continue

            if " @ " in line:
                items.append(f"- [ ] Verify purchase: {line}")
                continue

            if any(
                keyword in line.lower()
                for keyword in {
                    "load ",
                    "meet ",
                    "lesson",
                    "lunch",
                    "battery swap",
                    "follow-up visits",
                    "follow up visits",
                    "buy ",
                    "top up ",
                }
            ):
                items.append(f"- [ ] {line}")
                continue

        deduped: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = item.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(item)
            if len(deduped) == 6:
                break
        return deduped

    def _normalized_specialist_lines(self, text: str) -> list[str]:
        lines: list[str] = []
        for raw_line in text.splitlines():
            for segment in raw_line.split(";"):
                cleaned = segment.strip().strip("*")
                if not cleaned:
                    continue
                lowered = cleaned.lower().rstrip(":")
                if lowered in {
                    "visible text extracted from the image",
                    "visible text extracted from the medical image",
                }:
                    continue
                lines.append(cleaned.rstrip("."))
        return lines

    def _clean_specialist_text(self, text: str) -> str:
        lines = self._normalized_specialist_lines(text)
        if not lines:
            return ""
        if len(lines) == 1:
            return lines[0]
        return " ".join(lines[:6])

    def _select_image_asset(self, assets: list[AssetSummary]) -> AssetSummary | None:
        for asset in assets:
            if asset.kind == AssetKind.IMAGE:
                return asset
        return None

    def _heatmap_title(self, source_asset: AssetSummary | None) -> str:
        if source_asset is None:
            return "Segmented heatmap overlay"
        stem = Path(source_asset.display_name).stem.replace("_", " ").strip()
        if not stem:
            return "Segmented heatmap overlay"
        return f"{stem[:1].upper() + stem[1:]} segmented heatmap"

    def _execute_heatmap_overlay(self, payload: dict[str, object]) -> dict[str, object]:
        source_asset_id = str(payload.get("source_asset_id") or "").strip()
        if not source_asset_id:
            return {
                "entity_type": "noop",
                "tool_name": "generate_heatmap_overlay",
                "message": "A source image is required before generating a segmented heatmap overlay.",
            }

        source_asset = self.store.get_asset(source_asset_id)
        source_path = self.store.get_asset_local_path(source_asset_id)
        if source_asset is None or not source_path:
            raise FileNotFoundError(f"Source asset {source_asset_id} is unavailable.")

        source_file = Path(source_path)
        if not source_file.exists():
            raise FileNotFoundError(source_file)

        overlay_asset_id = new_id("asset")
        output_path = self.asset_storage_dir / f"{overlay_asset_id}.png"
        overlay_summary = self._render_segmented_heatmap(source_file, output_path)
        asset = self.store.create_asset_record(
            asset_id=overlay_asset_id,
            source_path=source_asset.source_path,
            display_name=f"{Path(source_asset.display_name).stem}-segmented-heatmap.png",
            description="Derived segmented heatmap overlay generated from a local image.",
            media_type="image/png",
            kind=AssetKind.IMAGE,
            byte_size=output_path.stat().st_size,
            local_path=str(output_path),
            care_context=source_asset.care_context,
            analysis_status=AssetAnalysisStatus.READY,
            analysis_summary=overlay_summary,
        )
        return {
            "entity_type": "asset",
            "entity_id": asset.id,
            "title": asset.display_name,
            "status": "ready",
            "asset_id": asset.id,
            "asset_ids": [asset.id],
            "asset": asset.model_dump(mode="json"),
            "message": overlay_summary,
            "source_asset_id": source_asset_id,
        }

    def _render_segmented_heatmap(self, source_path: Path, output_path: Path) -> str:
        with Image.open(source_path) as opened:
            base = opened.convert("RGB")

        grayscale = base.convert("L")
        grayscale_array = np.asarray(grayscale, dtype=np.float32) / 255.0
        blurred = np.asarray(grayscale.filter(ImageFilter.GaussianBlur(radius=14)), dtype=np.float32) / 255.0
        edges = np.asarray(grayscale.filter(ImageFilter.FIND_EDGES), dtype=np.float32) / 255.0
        density = 1.0 - grayscale_array
        local_contrast = np.abs(grayscale_array - blurred)
        heat = np.clip((density * 0.62) + (local_contrast * 0.23) + (edges * 0.15), 0.0, 1.0)
        heat = (heat - heat.min()) / max(float(heat.max() - heat.min()), 1e-6)

        bands = np.digitize(heat, bins=np.array([0.18, 0.34, 0.52, 0.7, 0.86]))
        palette = np.array(
            [
                [20, 34, 58, 0],
                [56, 189, 248, 46],
                [52, 211, 153, 72],
                [250, 204, 21, 102],
                [249, 115, 22, 132],
                [239, 68, 68, 162],
            ],
            dtype=np.uint8,
        )
        overlay_array = palette[bands]
        overlay = Image.fromarray(overlay_array, mode="RGBA").filter(ImageFilter.GaussianBlur(radius=1.5))
        blended = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
        canvas = self._compose_overlay_board(base, blended)
        canvas.save(output_path, format="PNG", optimize=True)

        emphasized_ratio = float((bands >= 3).sum()) / float(bands.size)
        emphasis_label = "focused hotspots" if emphasized_ratio < 0.18 else "broad hotspot regions"
        return (
            "Derived segmented heatmap overlay generated locally. "
            f"It highlights {emphasis_label} using brightness, density, and edge contrast heuristics; "
            "it is a visual aid, not a clinical segmentation."
        )

    def _compose_overlay_board(self, original: Image.Image, overlay: Image.Image) -> Image.Image:
        gutter = 26
        padding = 20
        header_height = 52
        legend_height = 66
        width = original.width * 2 + gutter + padding * 2
        height = original.height + header_height + legend_height + padding * 2
        canvas = Image.new("RGB", (width, height), "#090b10")
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()
        left_x = padding
        top_y = padding + header_height
        right_x = left_x + original.width + gutter

        draw.text((left_x, padding), "Original", fill="#c8cfdc", font=font)
        draw.text((right_x, padding), "Segmented heatmap overlay", fill="#f3efe6", font=font)
        canvas.paste(original, (left_x, top_y))
        canvas.paste(overlay, (right_x, top_y))

        legend_y = top_y + original.height + 18
        labels = [
            ("cool", "#38bdf8"),
            ("mid", "#34d399"),
            ("warm", "#facc15"),
            ("hot", "#f97316"),
            ("peak", "#ef4444"),
        ]
        swatch_x = right_x
        for label, color in labels:
            draw.rounded_rectangle(
                (swatch_x, legend_y, swatch_x + 18, legend_y + 18),
                radius=5,
                fill=color,
            )
            draw.text((swatch_x + 26, legend_y + 2), label, fill="#c8cfdc", font=font)
            swatch_x += 84

        draw.text(
            (left_x, legend_y + 30),
            "Local heuristic overlay for inspection and follow-up conversation.",
            fill="#7f8796",
            font=font,
        )
        return canvas
