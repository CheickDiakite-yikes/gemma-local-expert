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
            title = self._title_from_request(turn.text, fallback="Field Brief")
            return ToolPlan(
                tool_name=tool_name,
                payload={
                    "conversation_id": turn.conversation_id,
                    "title": title,
                    "content": self._build_note_content(
                        turn,
                        specialist_analysis_text=specialist_analysis_text,
                    ),
                    "export_type": "markdown",
                    "destination_path": self._default_export_path(title),
                },
            )

        return ToolPlan(tool_name=tool_name, payload={"request": turn.text.strip()})

    def execute(self, tool_name: str, payload: dict[str, object]) -> dict[str, object]:
        if tool_name in {"create_note", "create_checklist", "log_observation"}:
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

        if tool_name in {"create_note", "create_checklist", "log_observation"}:
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

    def _title_from_request(self, text: str, *, fallback: str) -> str:
        cleaned = re.sub(r"^(create|make|build|write|log)\s+(a|an|the)?\s*", "", text, flags=re.I)
        cleaned = cleaned.strip().rstrip(".")
        if not cleaned:
            return fallback
        if len(cleaned) > 80:
            cleaned = cleaned[:77].rstrip() + "..."
        return cleaned[:1].upper() + cleaned[1:]

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

        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", cleaned) if paragraph.strip()]
        if not paragraphs:
            return cleaned

        remaining: list[str] = []
        skipped_lede = False
        for paragraph in paragraphs:
            lowered = paragraph.lower()
            if not skipped_lede and (
                lowered.startswith("i reviewed ")
                or lowered.startswith("i reviewed the allowed workspace scope")
            ):
                skipped_lede = True
                continue
            remaining.append(paragraph)

        result = "\n\n".join(remaining).strip()
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
