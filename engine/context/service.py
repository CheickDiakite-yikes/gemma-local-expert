from __future__ import annotations

from dataclasses import dataclass, field

from engine.contracts.api import AssetKind, AssetSummary, TranscriptMessage


_LOW_SIGNAL_USER_TURNS = {
    "k",
    "kk",
    "ok",
    "okay",
    "sounds good",
    "lets continue",
    "let's continue",
    "continue",
    "thanks",
    "thank you",
}

_IMAGE_REFERENCE_TOKENS = {
    "image",
    "picture",
    "photo",
    "screenshot",
    "xray",
    "x-ray",
    "radiograph",
    "scan",
}

_VIDEO_REFERENCE_TOKENS = {
    "video",
    "clip",
    "camera",
    "footage",
    "recording",
    "frame",
}

_MEDIA_FOLLOW_UP_CUES = {
    "before departure",
    "item",
    "items",
    "prioritize",
    "prioritise",
    "which one",
    "what stands out",
    "what do you notice",
    "what matters most",
    "most important",
    "looks off",
    "look off",
    "shortage",
    "shortages",
    "urgent",
    "visible",
    "shown",
    "compare this",
}

_WORK_PRODUCT_REFERENCE_PHRASES = {
    "that draft",
    "this draft",
    "the draft",
    "that note",
    "this note",
    "the note",
    "that checklist",
    "this checklist",
    "the checklist",
    "that task",
    "this task",
    "the task",
    "that export",
    "this export",
    "the export",
    "that markdown",
    "this markdown",
    "the markdown",
    "that document",
    "this document",
    "the document",
    "before i save",
    "before you save",
    "save locally",
    "ready to save",
    "what title are you using",
    "what title is that",
    "what is the draft called",
    "what is that draft called",
    "what is the title now",
    "what is the draft title",
    "what did you call that",
    "rename that",
    "retitle that",
    "make that shorter",
    "tighten that draft",
}

_WORK_PRODUCT_NOUNS = {
    "draft",
    "note",
    "checklist",
    "task",
    "export",
    "markdown",
    "document",
    "file",
    "title",
}

_WORK_PRODUCT_EDIT_TOKENS = {
    "edit",
    "rename",
    "retitle",
    "revise",
    "rewrite",
    "shorten",
    "shorter",
    "lengthen",
    "longer",
    "tighten",
    "called",
    "update",
    "save",
}

_TOPIC_REFERENCE_PHRASES = {
    "what did you mean by that",
    "what do you mean by that",
    "can you explain that",
    "tell me more about that",
    "go back to that",
    "bring that up again",
    "come back to that",
    "go deeper on that",
}

_REFERENT_METADATA_PREFIXES = {
    "key points:",
    "files reviewed:",
    "related docs:",
    "related brief:",
    "related local docs:",
    "working title:",
    "goal:",
    "workspace scope:",
}


@dataclass(slots=True)
class ConversationContextSnapshot:
    active_topic: str | None = None
    recent_topics: list[str] = field(default_factory=list)
    last_user_request: str | None = None
    last_assistant_reply: str | None = None
    last_image_assets: list[AssetSummary] = field(default_factory=list)
    last_video_assets: list[AssetSummary] = field(default_factory=list)
    selected_context_assets: list[AssetSummary] = field(default_factory=list)
    selected_context_kind: str | None = None
    selected_context_reason: str | None = None
    selected_context_summary: str | None = None
    selected_referent_kind: str | None = None
    selected_referent_tool: str | None = None
    selected_referent_title: str | None = None
    selected_referent_reason: str | None = None
    selected_referent_summary: str | None = None
    selected_referent_excerpt: str | None = None
    pending_approval_id: str | None = None
    pending_approval_tool: str | None = None
    pending_approval_summary: str | None = None
    pending_approval_excerpt: str | None = None
    last_completed_output_tool: str | None = None
    last_completed_output_title: str | None = None
    last_completed_output_excerpt: str | None = None
    last_agent_summary: str | None = None
    recent_outputs: list["WorkProductReference"] = field(default_factory=list)

    def prompt_lines(self) -> list[str]:
        lines: list[str] = []
        if self.active_topic:
            lines.append(f"Active topic: {self.active_topic}")
        if self.recent_topics[1:]:
            recent = ", ".join(self.recent_topics[1:3])
            if recent:
                lines.append(f"Recent earlier topics: {recent}")
        if self.selected_referent_kind:
            lines.append(
                "Likely current referent: "
                + self._format_referent(
                    kind=self.selected_referent_kind,
                    tool_name=self.selected_referent_tool,
                    title=self.selected_referent_title,
                )
            )
        if self.selected_referent_summary:
            lines.append(f"Likely referent summary: {self.selected_referent_summary}")
        if self.selected_referent_excerpt:
            lines.append(f"Likely referent preview: {self.selected_referent_excerpt}")
        if self.selected_context_assets:
            labels = ", ".join(asset.display_name for asset in self.selected_context_assets[:2])
            kind = self.selected_context_kind or "media"
            lines.append(f"Relevant earlier {kind}: {labels}")
            if self.selected_context_summary:
                lines.append(f"Relevant earlier {kind} summary: {self.selected_context_summary}")
        elif self.last_image_assets or self.last_video_assets:
            available: list[str] = []
            if self.last_image_assets:
                available.append("image")
            if self.last_video_assets:
                available.append("video")
            lines.append("Recent media available: " + ", ".join(available))
        if (
            self.pending_approval_tool
            and self.selected_referent_kind not in {"pending_output", "saved_output"}
        ):
            lines.append(
                "Pending draft: "
                + self._format_referent(
                    kind="pending_output",
                    tool_name=self.pending_approval_tool,
                    title=self.pending_approval_summary,
                )
            )
            if self.pending_approval_excerpt:
                lines.append(f"Pending draft preview: {self.pending_approval_excerpt}")
        if (
            self.last_completed_output_tool
            and self.last_completed_output_title
            and self.selected_referent_kind not in {"pending_output", "saved_output"}
        ):
            lines.append(
                "Most recent saved output: "
                + self._format_referent(
                    kind="saved_output",
                    tool_name=self.last_completed_output_tool,
                    title=self.last_completed_output_title,
                )
            )
            if self.last_completed_output_excerpt:
                lines.append(
                    f"Most recent saved output preview: {self.last_completed_output_excerpt}"
                )
        return lines

    def _format_referent(
        self,
        *,
        kind: str,
        tool_name: str | None,
        title: str | None,
    ) -> str:
        if kind == "pending_output":
            base = f"{self._tool_label(tool_name)} draft"
            return f'{base} "{title}"' if title else base
        if kind == "saved_output":
            base = self._tool_label(tool_name)
            return f'{base} "{title}"' if title else base
        if kind in {"image", "video"}:
            base = f"earlier {kind}"
            return f'{base} "{title}"' if title else base
        if kind == "topic":
            return title or "the earlier topic"
        return title or kind.replace("_", " ")

    def _tool_label(self, tool_name: str | None) -> str:
        mapping = {
            "create_note": "note",
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


@dataclass(slots=True)
class WorkProductReference:
    kind: str
    tool_name: str | None
    title: str | None
    excerpt: str | None
    approval_id: str | None = None


class ConversationContextService:
    def describe_payload(
        self, payload: dict[str, object] | None
    ) -> tuple[str | None, str | None]:
        if not isinstance(payload, dict):
            return None, None
        summary = None
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            summary = self._trim(self._compact(title), 96)
        excerpt = self._work_product_excerpt(payload)
        return summary, excerpt

    def build(
        self,
        *,
        turn_text: str,
        transcript: list[TranscriptMessage],
        attached_assets: list[AssetSummary],
    ) -> ConversationContextSnapshot:
        snapshot = ConversationContextSnapshot()
        snapshot.recent_topics = self._recent_topics(transcript)
        snapshot.active_topic = snapshot.recent_topics[0] if snapshot.recent_topics else None
        snapshot.last_user_request = snapshot.active_topic
        snapshot.last_assistant_reply = self._last_message_text(transcript, role="assistant")
        snapshot.last_agent_summary = self._last_agent_summary(transcript)
        snapshot.recent_outputs = self._recent_work_products(transcript)
        (
            snapshot.pending_approval_id,
            snapshot.pending_approval_tool,
            snapshot.pending_approval_summary,
            snapshot.pending_approval_excerpt,
        ) = self._pending_approval(transcript)
        (
            snapshot.last_completed_output_tool,
            snapshot.last_completed_output_title,
            snapshot.last_completed_output_excerpt,
        ) = self._last_completed_output(transcript)
        image_reference_groups = self._recent_reference_assets_by_kind(
            transcript, AssetKind.IMAGE
        )
        video_reference_groups = self._recent_reference_assets_by_kind(
            transcript, AssetKind.VIDEO
        )
        snapshot.last_image_assets = image_reference_groups[0] if image_reference_groups else []
        snapshot.last_video_assets = video_reference_groups[0] if video_reference_groups else []

        if not attached_assets:
            (
                snapshot.selected_context_assets,
                snapshot.selected_context_kind,
                snapshot.selected_context_reason,
            ) = self._select_context_assets(
                turn_text=turn_text,
                transcript=transcript,
                image_reference_groups=image_reference_groups,
                video_reference_groups=video_reference_groups,
            )
            if snapshot.selected_context_assets and snapshot.selected_context_kind:
                snapshot.selected_context_summary = self._asset_context_summary(
                    transcript=transcript,
                    assets=snapshot.selected_context_assets,
                    kind=snapshot.selected_context_kind,
                )
        (
            snapshot.selected_referent_kind,
            snapshot.selected_referent_tool,
            snapshot.selected_referent_title,
            snapshot.selected_referent_excerpt,
            snapshot.selected_referent_reason,
        ) = self._select_referent(turn_text=turn_text, snapshot=snapshot)
        if snapshot.selected_referent_kind == "pending_output":
            snapshot.selected_referent_summary = snapshot.selected_referent_title
        elif snapshot.selected_referent_kind == "saved_output":
            snapshot.selected_referent_summary = snapshot.selected_referent_title
        elif snapshot.selected_referent_kind in {"image", "video"}:
            snapshot.selected_referent_summary = snapshot.selected_context_summary
            snapshot.selected_referent_excerpt = snapshot.selected_context_summary
        elif snapshot.selected_referent_kind == "topic" and snapshot.active_topic:
            snapshot.selected_referent_summary = snapshot.active_topic
        return snapshot

    def _recent_topics(self, transcript: list[TranscriptMessage]) -> list[str]:
        topics: list[str] = []
        seen: set[str] = set()
        for message in reversed(transcript):
            if message.role != "user":
                continue
            cleaned = self._topic_text(message.content)
            if not cleaned:
                continue
            normalized = cleaned.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            topics.append(cleaned)
            if len(topics) == 4:
                break
        return topics

    def _topic_text(self, content: str) -> str | None:
        cleaned = self._compact(content)
        if not cleaned:
            return None
        lowered = cleaned.lower().strip("?.! ")
        if lowered in _LOW_SIGNAL_USER_TURNS:
            return None
        first_line = cleaned.splitlines()[0].strip()
        return self._trim(first_line, 96)

    def _last_message_text(self, transcript: list[TranscriptMessage], *, role: str) -> str | None:
        for message in reversed(transcript):
            if message.role != role:
                continue
            cleaned = self._compact(message.content)
            if cleaned:
                return self._trim(cleaned, 160)
        return None

    def _last_agent_summary(self, transcript: list[TranscriptMessage]) -> str | None:
        for message in reversed(transcript):
            if message.role != "assistant":
                continue
            cleaned = self._compact(message.content)
            if not cleaned:
                continue
            if "Files reviewed:" in cleaned or "Key points:" in cleaned or "I reviewed" in cleaned:
                return self._trim(cleaned, 180)
        return None

    def _pending_approval(
        self, transcript: list[TranscriptMessage]
    ) -> tuple[str | None, str | None, str | None, str | None]:
        for message in reversed(transcript):
            approval = message.approval
            if approval is None or approval.status != "pending":
                continue
            summary, excerpt = self.describe_payload(
                approval.payload if isinstance(approval.payload, dict) else None
            )
            return approval.id, approval.tool_name, summary, excerpt
        return None, None, None, None

    def _last_completed_output(
        self, transcript: list[TranscriptMessage]
    ) -> tuple[str | None, str | None, str | None]:
        for message in reversed(transcript):
            approval = message.approval
            if approval is None or approval.status != "executed":
                continue
            title, excerpt = self._approval_referent_details(approval)
            return approval.tool_name, title, excerpt
        return None, None, None

    def _recent_work_products(
        self, transcript: list[TranscriptMessage]
    ) -> list[WorkProductReference]:
        outputs: list[WorkProductReference] = []
        seen_ids: set[str] = set()
        for message in reversed(transcript):
            approval = message.approval
            if approval is None or approval.id in seen_ids:
                continue
            if approval.status not in {"pending", "executed"}:
                continue
            seen_ids.add(approval.id)
            title, excerpt = self._approval_referent_details(approval)
            outputs.append(
                WorkProductReference(
                    kind="pending_output" if approval.status == "pending" else "saved_output",
                    tool_name=approval.tool_name,
                    title=title,
                    excerpt=excerpt,
                    approval_id=approval.id,
                )
            )
            if len(outputs) == 6:
                break
        return outputs

    def _approval_referent_details(self, approval) -> tuple[str | None, str | None]:
        payload = approval.payload if isinstance(approval.payload, dict) else None
        result = approval.result if isinstance(approval.result, dict) else None

        title = None
        if result:
            result_title = result.get("title")
            if isinstance(result_title, str) and result_title.strip():
                title = self._trim(self._compact(result_title), 96)
        if title is None and payload:
            payload_title = payload.get("title")
            if isinstance(payload_title, str) and payload_title.strip():
                title = self._trim(self._compact(payload_title), 96)

        payload_excerpt = self._work_product_excerpt(payload)
        excerpt = self._work_product_excerpt(result)
        if payload_excerpt and (excerpt is None or (title and excerpt.lower() == title.lower())):
            excerpt = payload_excerpt
        return title, excerpt

    def _recent_reference_assets_by_kind(
        self, transcript: list[TranscriptMessage], kind: AssetKind
    ) -> list[list[AssetSummary]]:
        preferred = self._recent_assets_by_kind(
            transcript,
            kind,
            roles={"user"},
            skip_contact_sheet=True,
        )
        if preferred:
            return preferred
        fallback = self._recent_assets_by_kind(
            transcript,
            kind,
            roles={"assistant"},
            skip_contact_sheet=True,
        )
        if fallback:
            return fallback
        return self._recent_assets_by_kind(
            transcript,
            kind,
            roles=None,
            skip_contact_sheet=True,
        )

    def _recent_assets_by_kind(
        self,
        transcript: list[TranscriptMessage],
        kind: AssetKind,
        *,
        roles: set[str] | None,
        skip_contact_sheet: bool,
    ) -> list[list[AssetSummary]]:
        groups: list[list[AssetSummary]] = []
        seen_signatures: set[tuple[str, ...]] = set()
        for message in reversed(transcript):
            if roles is not None and message.role not in roles:
                continue
            matching = [
                asset
                for asset in message.assets
                if asset.kind == kind
                and not (skip_contact_sheet and self._is_video_contact_sheet(asset))
            ]
            if matching:
                signature = tuple(asset.id for asset in matching)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                groups.append(matching)
                if len(groups) == 4:
                    break
        return groups

    def _select_context_assets(
        self,
        *,
        turn_text: str,
        transcript: list[TranscriptMessage],
        image_reference_groups: list[list[AssetSummary]],
        video_reference_groups: list[list[AssetSummary]],
    ) -> tuple[list[AssetSummary], str | None, str | None]:
        lowered = turn_text.lower().strip()
        if not lowered:
            return [], None, None

        if any(token in lowered for token in _VIDEO_REFERENCE_TOKENS) and video_reference_groups:
            selected_video_assets = self._select_referenced_asset_group(
                lowered,
                kind="video",
                groups=video_reference_groups,
            )
            return selected_video_assets, "video", "User referred back to an earlier video."
        if any(token in lowered for token in _IMAGE_REFERENCE_TOKENS) and image_reference_groups:
            selected_image_assets = self._select_referenced_asset_group(
                lowered,
                kind="image",
                groups=image_reference_groups,
            )
            return selected_image_assets, "image", "User referred back to an earlier image."

        if self._looks_like_media_follow_up(lowered):
            last_media_assets, last_media_kind = self._last_media_assets(transcript)
            if last_media_assets:
                return (
                    last_media_assets,
                    last_media_kind,
                    "Follow-up appears to continue the most recent media context.",
                )

        return [], None, None

    def _select_referent(
        self,
        *,
        turn_text: str,
        snapshot: ConversationContextSnapshot,
    ) -> tuple[str | None, str | None, str | None, str | None, str | None]:
        lowered = turn_text.lower().strip()
        if not lowered:
            return None, None, None, None, None

        if self._looks_like_work_product_reference(lowered):
            requested_tools = self._requested_work_product_tools(lowered)
            if requested_tools:
                matched_output = self._match_recent_output(
                    snapshot.recent_outputs,
                    requested_tools=requested_tools,
                )
                if matched_output:
                    return (
                        matched_output.kind,
                        matched_output.tool_name,
                        matched_output.title,
                        matched_output.excerpt,
                        f"User referred back to the recent {self._tool_label(matched_output.tool_name)} output.",
                    )
            if snapshot.pending_approval_tool:
                return (
                    "pending_output",
                    snapshot.pending_approval_tool,
                    snapshot.pending_approval_summary,
                    snapshot.pending_approval_excerpt,
                    "User referred to the current local draft.",
                )
            if snapshot.last_completed_output_tool:
                return (
                    "saved_output",
                    snapshot.last_completed_output_tool,
                    snapshot.last_completed_output_title,
                    snapshot.last_completed_output_excerpt,
                    "User referred back to the most recent saved local output.",
                )

        if snapshot.selected_context_assets:
            title = ", ".join(
                asset.display_name for asset in snapshot.selected_context_assets[:2]
            )
            return (
                snapshot.selected_context_kind,
                None,
                title,
                None,
                snapshot.selected_context_reason,
            )

        if snapshot.active_topic and self._looks_like_topic_reference(lowered):
            return (
                "topic",
                None,
                self._trim(snapshot.active_topic, 96),
                None,
                "User is referring back to the earlier topic.",
            )

        return None, None, None, None, None

    def _requested_work_product_tools(self, lowered: str) -> set[str]:
        requested_tools: set[str] = set()
        if "checklist" in lowered:
            requested_tools.add("create_checklist")
        if "task" in lowered:
            requested_tools.add("create_task")
        if "observation" in lowered:
            requested_tools.add("log_observation")
        if "note" in lowered:
            requested_tools.add("create_note")
        if any(token in lowered for token in {"export", "markdown", "document"}):
            requested_tools.add("export_brief")
        return requested_tools

    def _match_recent_output(
        self,
        recent_outputs: list[WorkProductReference],
        *,
        requested_tools: set[str],
    ) -> WorkProductReference | None:
        for output in recent_outputs:
            if output.tool_name in requested_tools:
                return output
        return None

    def _tool_label(self, tool_name: str | None) -> str:
        mapping = {
            "create_note": "note",
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

    def _last_media_assets(
        self, transcript: list[TranscriptMessage]
    ) -> tuple[list[AssetSummary], str | None]:
        for kind in (AssetKind.VIDEO, AssetKind.IMAGE):
            preferred = self._recent_assets_by_kind(
                transcript,
                kind,
                roles={"user"},
                skip_contact_sheet=True,
            )
            if preferred:
                return preferred[0], "video" if kind == AssetKind.VIDEO else "image"
        for message in reversed(transcript):
            media_assets = [
                asset
                for asset in message.assets
                if asset.kind in {AssetKind.IMAGE, AssetKind.VIDEO}
                and not self._is_video_contact_sheet(asset)
            ]
            if not media_assets:
                continue
            first_kind = media_assets[0].kind
            if first_kind == AssetKind.IMAGE:
                return media_assets, "image"
            if first_kind == AssetKind.VIDEO:
                return media_assets, "video"
        return [], None

    def _looks_like_media_follow_up(self, lowered: str) -> bool:
        if any(cue in lowered for cue in _MEDIA_FOLLOW_UP_CUES):
            return True
        return len(lowered.split()) <= 12 and any(
            lowered.startswith(prefix)
            for prefix in {"what about", "which one", "is that", "is there", "does that", "do those"}
        )

    def _looks_like_work_product_reference(self, lowered: str) -> bool:
        if any(phrase in lowered for phrase in _WORK_PRODUCT_REFERENCE_PHRASES):
            return True
        has_noun = any(token in lowered for token in _WORK_PRODUCT_NOUNS)
        has_edit_intent = any(token in lowered for token in _WORK_PRODUCT_EDIT_TOKENS)
        return has_noun and has_edit_intent

    def _looks_like_topic_reference(self, lowered: str) -> bool:
        if any(phrase in lowered for phrase in _TOPIC_REFERENCE_PHRASES):
            return True
        return lowered.startswith(("and what", "so what", "why is that", "how so"))

    def _is_video_contact_sheet(self, asset: AssetSummary) -> bool:
        lowered_name = asset.display_name.lower().strip()
        lowered_source = asset.source_path.lower().strip()
        lowered_summary = (asset.analysis_summary or "").lower()
        if "contact-sheet" in lowered_name or "contact sheet" in lowered_name:
            return True
        if "contact-sheet" in lowered_source or "contact sheet" in lowered_source:
            return True
        return "contact sheet" in lowered_summary and "video" in lowered_summary

    def _select_referenced_asset_group(
        self,
        lowered: str,
        *,
        kind: str,
        groups: list[list[AssetSummary]],
    ) -> list[AssetSummary]:
        if not groups:
            return []
        if any(phrase in lowered for phrase in {f"first {kind}", f"original {kind}", f"initial {kind}"}):
            return groups[-1]
        if any(
            phrase in lowered
            for phrase in {f"earlier {kind}", f"previous {kind}", f"prior {kind}"}
        ) and len(groups) > 1:
            return groups[1]
        if any(phrase in lowered for phrase in {f"latest {kind}", f"last {kind}", f"recent {kind}"}):
            return groups[0]
        return groups[0]

    def _asset_context_summary(
        self,
        *,
        transcript: list[TranscriptMessage],
        assets: list[AssetSummary],
        kind: str,
    ) -> str | None:
        assistant_summary = self._assistant_summary_for_asset_context(
            transcript=transcript,
            assets=assets,
        )
        if assistant_summary:
            return assistant_summary
        for asset in assets:
            if asset.analysis_summary and not self._is_video_contact_sheet(asset):
                return self._trim(self._compact(asset.analysis_summary), 140)
        if assets:
            label = ", ".join(asset.display_name for asset in assets[:2])
            return f"Earlier {kind}: {label}"
        return None

    def _assistant_summary_for_asset_context(
        self,
        *,
        transcript: list[TranscriptMessage],
        assets: list[AssetSummary],
    ) -> str | None:
        target_ids = {asset.id for asset in assets}
        target_kind = assets[0].kind if assets else None
        for index, message in enumerate(transcript):
            matching_assets = {
                asset.id
                for asset in message.assets
                if asset.id in target_ids
                or (
                    target_kind is not None
                    and asset.kind == target_kind
                    and not self._is_video_contact_sheet(asset)
                )
            }
            if not matching_assets and not (
                message.role == "user"
                and any(
                    asset.id in target_ids
                    or (
                        target_kind is not None
                        and asset.kind == target_kind
                        and not self._is_video_contact_sheet(asset)
                    )
                    for asset in message.assets
                )
            ):
                continue
            for follow_up in transcript[index + 1 :]:
                if follow_up.role != "assistant":
                    continue
                excerpt = self._best_excerpt(follow_up.content)
                if excerpt:
                    return excerpt
        return None

    def _work_product_excerpt(self, payload: dict[str, object] | None) -> str | None:
        if not payload:
            return None
        for key in ("content", "details", "summary", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                excerpt = self._best_excerpt(value)
                if excerpt:
                    return excerpt
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            return self._trim(self._compact(title), 120)
        return None

    def _best_excerpt(self, text: str) -> str | None:
        lines: list[str] = []
        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            cleaned = self._clean_line(raw_line)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in _REFERENT_METADATA_PREFIXES or lowered.startswith(tuple(_REFERENT_METADATA_PREFIXES)):
                continue
            if self._looks_like_filename_line(cleaned):
                continue
            lines.append(cleaned)
            if len(lines) == 2:
                break
        if not lines:
            compact = self._compact(text)
            return self._trim(compact, 140) if compact else None
        return self._trim(" ".join(lines), 140)

    def _clean_line(self, line: str) -> str:
        cleaned = line.strip()
        if not cleaned:
            return ""
        cleaned = cleaned.lstrip("#").strip()
        cleaned = cleaned.removeprefix("- ").removeprefix("* ").strip()
        cleaned = cleaned.replace("**", "")
        cleaned = cleaned.replace("`", "")
        cleaned = cleaned.replace("[", "").replace("]", "")
        cleaned = cleaned.replace("(", " ").replace(")", " ")
        return self._compact(cleaned)

    def _looks_like_filename_line(self, text: str) -> bool:
        lowered = text.lower().strip()
        if "/" in lowered and " " not in lowered:
            return True
        if lowered.count(".") == 1 and lowered.endswith(
            (".md", ".txt", ".json", ".png", ".jpg", ".jpeg", ".mov", ".mp4")
        ):
            return True
        return False

    def _compact(self, text: str) -> str:
        return " ".join(text.strip().split())

    def _trim(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"
