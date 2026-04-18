from __future__ import annotations

from engine.contracts.api import ToolDescriptor


class ToolRegistry:
    def __init__(self) -> None:
        self._tools = {
            "create_note": ToolDescriptor(name="create_note", requires_confirmation=True),
            "update_note": ToolDescriptor(name="update_note", requires_confirmation=True),
            "create_task": ToolDescriptor(name="create_task", requires_confirmation=True),
            "update_task": ToolDescriptor(name="update_task", requires_confirmation=True),
            "create_checklist": ToolDescriptor(
                name="create_checklist", requires_confirmation=True
            ),
            "draft_report": ToolDescriptor(name="draft_report", requires_confirmation=False),
            "draft_message": ToolDescriptor(name="draft_message", requires_confirmation=False),
            "log_observation": ToolDescriptor(
                name="log_observation", requires_confirmation=True
            ),
            "export_brief": ToolDescriptor(name="export_brief", requires_confirmation=True),
            "medical_case_summary": ToolDescriptor(
                name="medical_case_summary",
                requires_confirmation=True,
                namespace="medical",
            ),
            "workspace_search": ToolDescriptor(
                name="workspace_search",
                requires_confirmation=False,
                namespace="agent",
            ),
            "workspace_read_files": ToolDescriptor(
                name="workspace_read_files",
                requires_confirmation=False,
                namespace="agent",
            ),
            "workspace_summarize": ToolDescriptor(
                name="workspace_summarize",
                requires_confirmation=False,
                namespace="agent",
            ),
            "generate_heatmap_overlay": ToolDescriptor(
                name="generate_heatmap_overlay",
                requires_confirmation=False,
                namespace="vision",
            ),
        }

    def list_tools(self) -> list[ToolDescriptor]:
        return list(self._tools.values())

    def requires_confirmation(self, tool_name: str) -> bool:
        tool = self._tools.get(tool_name)
        return bool(tool and tool.requires_confirmation)

    def namespace_for(self, tool_name: str) -> str:
        tool = self._tools.get(tool_name)
        return tool.namespace if tool else "general"

    def propose(self, text: str) -> str | None:
        lowered = text.lower()
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
        if "note" in lowered and any(word in lowered for word in {"save", "create", "write"}):
            return "create_note"
        if "report" in lowered:
            return "draft_report"
        if "message" in lowered or "reply" in lowered:
            return "draft_message"
        if "observation" in lowered or "log this" in lowered:
            return "log_observation"
        if "export" in lowered:
            return "export_brief"
        if "case summary" in lowered and "medical" in lowered:
            return "medical_case_summary"
        return None
