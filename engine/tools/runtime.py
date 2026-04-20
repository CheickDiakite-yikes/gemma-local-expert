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
    ConversationTurnRequest,
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
        specialist_analysis_text: str | None = None,
        context_assets: list[AssetSummary] | None = None,
    ) -> ToolPlan:
        if tool_name == "create_note":
            return ToolPlan(
                tool_name=tool_name,
                payload={
                    "title": self._title_from_request(turn.text, fallback="Field Note"),
                    "content": self._build_note_content(
                        turn,
                        specialist_analysis_text=specialist_analysis_text,
                    ),
                    "kind": "note",
                },
            )

        if tool_name == "create_report":
            return ToolPlan(
                tool_name=tool_name,
                payload={
                    "title": self._report_title(turn.text, fallback="Field Report"),
                    "content": self._build_report_content(
                        turn,
                        specialist_analysis_text=specialist_analysis_text,
                    ),
                    "kind": "report",
                },
            )

        if tool_name == "create_message_draft":
            return ToolPlan(
                tool_name=tool_name,
                payload={
                    "title": self._message_draft_title(turn.text, fallback="Message Draft"),
                    "content": self._build_message_draft_content(
                        turn,
                        specialist_analysis_text=specialist_analysis_text,
                    ),
                    "kind": "message_draft",
                },
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
            return ToolPlan(
                tool_name=tool_name,
                payload={
                    "title": self._title_from_request(turn.text, fallback="Checklist"),
                    "content": self._build_checklist_content(
                        turn,
                        retrieval_results,
                        specialist_analysis_text=specialist_analysis_text,
                        context_assets=context_assets or [],
                    ),
                    "kind": "checklist",
                },
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
                specialist_analysis_text=specialist_analysis_text,
            )
            title = self._export_title(turn.text, content, fallback="Field Brief")
            return ToolPlan(
                tool_name=tool_name,
                payload={
                    "conversation_id": turn.conversation_id,
                    "title": title,
                    "content": content,
                    "export_type": "markdown",
                    "destination_path": self._default_export_path(title),
                },
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
                "entity_type": "note",
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
                tightened = self._tighten_content(str(base_payload.get("content") or ""))
                if tightened and tightened != str(base_payload.get("content") or ""):
                    edited["content"] = tightened

        if tool_name == "create_task":
            if self._looks_like_tighten_request(lowered):
                if not explicit_title and title:
                    tighter_title = self._tighten_title(title)
                    if tighter_title and tighter_title != title:
                        edited["title"] = tighter_title
                tightened = self._tighten_content(str(base_payload.get("details") or ""))
                if tightened and tightened != str(base_payload.get("details") or ""):
                    edited["details"] = tightened

        if not edited:
            return None

        merged = self.merge_edited_payload(tool_name, base_payload, edited)
        return merged if merged != base_payload else None

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
        cleaned = re.sub(
            r"\b(create|make|build|write|prepare|draft)\b",
            "",
            request_text,
            flags=re.I,
        )
        cleaned = re.sub(r"\ba\b|\ban\b|\bthe\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\breport\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" .-")
        title = self._title_from_request(cleaned, fallback=fallback)
        if "report" not in title.lower():
            title = f"{title} Report"
        return title

    def _message_draft_title(self, request_text: str, *, fallback: str) -> str:
        cleaned = re.sub(
            r"\b(create|make|build|write|prepare|draft)\b",
            "",
            request_text,
            flags=re.I,
        )
        cleaned = re.sub(r"\ba\b|\ban\b|\bthe\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\b(reply|response|message|email|text)\b", "", cleaned, flags=re.I)
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
        specialist_analysis_text: str | None = None,
    ) -> str:
        content = self._build_note_content(
            turn,
            specialist_analysis_text=specialist_analysis_text,
        ).strip()
        title = self._report_title(turn.text, fallback="Field Report")
        if content.startswith("# "):
            return content
        if content.lower().startswith(title.lower()):
            return f"# {title}\n\n{content[len(title):].lstrip()}"
        return f"# {title}\n\n{content}"

    def _build_message_draft_content(
        self,
        turn: ConversationTurnRequest,
        *,
        specialist_analysis_text: str | None = None,
    ) -> str:
        if specialist_analysis_text and not self._looks_like_workspace_brief_request(turn.text):
            cleaned = self._clean_specialist_text(specialist_analysis_text).strip()
            if cleaned and "visible text extracted from the image" not in cleaned.lower():
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
        specialist_analysis_text: str | None,
        context_assets: list[AssetSummary],
    ) -> str:
        if specialist_analysis_text:
            specialist_items = self._checklist_items_from_specialist_analysis(
                specialist_analysis_text
            )
            if specialist_items:
                return "\n".join(specialist_items)

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

    def _checklist_items_from_specialist_analysis(self, text: str) -> list[str]:
        priority_items = self._priority_items_from_specialist_analysis(text)
        if priority_items:
            return priority_items

        action_items = self._action_items_from_specialist_analysis(text)
        if action_items:
            return action_items

        raw_segments = re.split(r"[\n;]+", text)
        items: list[str] = []
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
        specialist_analysis_text: str | None,
    ) -> str:
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
                items.append(f"- [ ] Restock {match_low.group(1).strip()}")
                continue

            if "needs top" in lowered and ":" not in line:
                subject = re.split(r"_|needs", line, maxsplit=1, flags=re.I)[0].strip()
                if subject:
                    items.append(f"- [ ] Top up {subject}")

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
            cleaned = raw_line.strip().strip("*")
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
