from __future__ import annotations

from engine.contracts.api import ApprovalCategory, PermissionClass, ToolDescriptor


class ToolRegistry:
    def __init__(self) -> None:
        self._tools = {
            "create_note": ToolDescriptor(
                name="create_note",
                requires_confirmation=True,
                approval_category=ApprovalCategory.DURABLE_WRITE,
                approval_summary="Confirmation is required before writing a durable local note.",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.DURABLE_OUTPUT,
                ],
            ),
            "create_report": ToolDescriptor(
                name="create_report",
                requires_confirmation=True,
                approval_category=ApprovalCategory.DURABLE_WRITE,
                approval_summary="Confirmation is required before writing a durable local report.",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.DURABLE_OUTPUT,
                ],
            ),
            "create_message_draft": ToolDescriptor(
                name="create_message_draft",
                requires_confirmation=True,
                approval_category=ApprovalCategory.DURABLE_WRITE,
                approval_summary="Confirmation is required before saving a message draft locally.",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.DURABLE_OUTPUT,
                ],
            ),
            "update_note": ToolDescriptor(
                name="update_note",
                requires_confirmation=True,
                approval_category=ApprovalCategory.DURABLE_WRITE,
                approval_summary="Confirmation is required before changing a saved local note.",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.DURABLE_OUTPUT,
                ],
            ),
            "create_task": ToolDescriptor(
                name="create_task",
                requires_confirmation=True,
                approval_category=ApprovalCategory.DURABLE_WRITE,
                approval_summary="Confirmation is required before creating a durable local task.",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.DURABLE_OUTPUT,
                ],
            ),
            "update_task": ToolDescriptor(
                name="update_task",
                requires_confirmation=True,
                approval_category=ApprovalCategory.DURABLE_WRITE,
                approval_summary="Confirmation is required before changing a saved local task.",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.DURABLE_OUTPUT,
                ],
            ),
            "create_checklist": ToolDescriptor(
                name="create_checklist",
                requires_confirmation=True,
                approval_category=ApprovalCategory.DURABLE_WRITE,
                approval_summary="Confirmation is required before saving a checklist locally.",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.DURABLE_OUTPUT,
                ],
            ),
            "log_observation": ToolDescriptor(
                name="log_observation",
                requires_confirmation=True,
                approval_category=ApprovalCategory.DURABLE_WRITE,
                approval_summary="Confirmation is required before saving a local observation.",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.DURABLE_OUTPUT,
                ],
            ),
            "export_brief": ToolDescriptor(
                name="export_brief",
                requires_confirmation=True,
                approval_category=ApprovalCategory.AUDITED_EXPORT,
                approval_summary="Confirmation is required before writing an audited markdown export.",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.DURABLE_OUTPUT,
                    PermissionClass.AUDIT_LOG,
                ],
            ),
            "medical_case_summary": ToolDescriptor(
                name="medical_case_summary",
                requires_confirmation=True,
                namespace="medical",
                approval_category=ApprovalCategory.MEDICAL_SPECIALIST,
                approval_summary="Explicit guarded medical specialist review is required.",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.MEDICAL_SPECIALIST,
                ],
            ),
            "workspace_search": ToolDescriptor(
                name="workspace_search",
                requires_confirmation=False,
                namespace="agent",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.WORKSPACE_AGENT,
                ],
            ),
            "workspace_read_files": ToolDescriptor(
                name="workspace_read_files",
                requires_confirmation=False,
                namespace="agent",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.WORKSPACE_AGENT,
                ],
            ),
            "workspace_summarize": ToolDescriptor(
                name="workspace_summarize",
                requires_confirmation=False,
                namespace="agent",
                permission_classes=[
                    PermissionClass.TOOL_EXECUTION,
                    PermissionClass.WORKSPACE_AGENT,
                ],
            ),
            "generate_heatmap_overlay": ToolDescriptor(
                name="generate_heatmap_overlay",
                requires_confirmation=False,
                namespace="vision",
                permission_classes=[PermissionClass.TOOL_EXECUTION],
            ),
        }

    def list_tools(self) -> list[ToolDescriptor]:
        return list(self._tools.values())

    def requires_confirmation(self, tool_name: str) -> bool:
        tool = self._tools.get(tool_name)
        return bool(tool and tool.requires_confirmation)

    def descriptor_for(self, tool_name: str) -> ToolDescriptor | None:
        return self._tools.get(tool_name)

    def namespace_for(self, tool_name: str) -> str:
        tool = self._tools.get(tool_name)
        return tool.namespace if tool else "general"

    def propose(self, text: str) -> str | None:
        lowered = text.lower()
        if self._looks_like_work_product_reference_question(lowered) or self._looks_like_work_product_edit_reference(lowered):
            return None
        if any(
            token in lowered
            for token in {"heatmap", "overlay", "segmented", "segment", "layering"}
        ) and any(
            token in lowered
            for token in {"image", "xray", "x-ray", "radiograph", "scan", "photo", "picture"}
        ):
            return "generate_heatmap_overlay"
        if "checklist" in lowered and any(
            word in lowered for word in {"create", "make", "build", "draft", "generate"}
        ):
            return "create_checklist"
        if "task" in lowered:
            return "create_task"
        if (
            "report" in lowered
            and not any(token in lowered for token in {"export", "markdown", "document"})
            and any(
                word in lowered
                for word in {"save", "create", "write", "make", "build", "draft", "prepare"}
            )
        ):
            return "create_report"
        if "note" in lowered and any(word in lowered for word in {"save", "create", "write"}):
            return "create_note"
        if any(token in lowered for token in {"message", "reply", "email"}) and any(
            word in lowered for word in {"save", "create", "write", "make", "build", "draft", "prepare"}
        ):
            return "create_message_draft"
        if self._looks_like_export_action(lowered):
            return "export_brief"
        if "observation" in lowered or "log this" in lowered:
            return "log_observation"
        if "case summary" in lowered and "medical" in lowered:
            return "medical_case_summary"
        return None

    def _looks_like_work_product_reference_question(self, lowered: str) -> bool:
        reference_phrases = {
            "what title are you using",
            "what title is that",
            "what is the draft called",
            "what is that draft called",
            "what is the title now",
            "what is the draft title",
            "what did you call that",
            "what are you calling that",
            "what was in that",
            "what is in that",
            "what's in that",
            "show me that draft",
            "remind me what is in",
        }
        if any(phrase in lowered for phrase in reference_phrases):
            return True
        if not lowered.startswith(("what ", "which ", "show ", "remind ")):
            return False
        return any(
            token in lowered
            for token in {
                "draft",
                "note",
                "report",
                "message",
                "reply",
                "email",
                "checklist",
                "export",
                "markdown",
                "document",
                "task",
            }
        )

    def _looks_like_work_product_edit_reference(self, lowered: str) -> bool:
        reference_cues = {
            "that",
            "this",
            "same",
            "current",
            "again",
            "before i save",
            "before we save",
            "before you save",
        }
        work_product_nouns = {
            "draft",
            "note",
            "report",
            "message",
            "reply",
            "email",
            "checklist",
            "export",
            "markdown",
            "document",
            "task",
            "title",
        }
        edit_tokens = {
            "title",
            "rename",
            "retitle",
            "revise",
            "rewrite",
            "edit",
            "update",
            "shorter",
            "shorten",
            "clearer",
            "tighten",
            "before save",
        }
        return (
            any(token in lowered for token in reference_cues)
            and any(token in lowered for token in work_product_nouns)
            and any(token in lowered for token in edit_tokens)
        )

    def _looks_like_export_action(self, lowered: str) -> bool:
        explicit_export_phrases = {
            "export a",
            "export an",
            "export the",
            "export this",
            "export that",
            "please export",
            "can you export",
        }
        if "export" in lowered and any(phrase in lowered for phrase in explicit_export_phrases):
            return True

        if any(token in lowered for token in {"markdown", "document"}) and any(
            word in lowered for word in {"save", "create", "write", "make", "build", "draft", "prepare", "export"}
        ):
            return True

        return False
