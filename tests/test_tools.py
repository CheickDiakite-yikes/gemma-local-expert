from engine.contracts.api import AssistantMode, ConversationTurnRequest
from engine.tools.runtime import ToolRuntime


class _UnusedStore:
    def create_note(self, *args, **kwargs):  # pragma: no cover - not used in this test
        raise NotImplementedError

    def create_task(self, *args, **kwargs):  # pragma: no cover - not used in this test
        raise NotImplementedError

    def create_export(self, *args, **kwargs):  # pragma: no cover - not used in this test
        raise NotImplementedError


class _ExportStore(_UnusedStore):
    def create_export(self, request, status="queued"):
        return type(
            "_Result",
            (),
            {
                "export_id": "export_test",
                "destination_path": request.destination_path,
                "status": status,
            },
        )()


def test_checklist_planner_prefers_priority_lines_from_specialist_analysis() -> None:
    runtime = ToolRuntime(_UnusedStore())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Create a checklist for the shortages shown in this board.",
    )

    plan = runtime.plan(
        request,
        "create_checklist",
        [],
        specialist_analysis_text=(
            "Visible text extracted from the image:\n"
            "Lantern batteries LOW\n"
            "Translator phone credits _ NEEDS TOP-UP\n"
            "Action note: Buy batteries and top up translator credit before leaving base."
        ),
        context_assets=[],
    )

    assert "Restock Lantern batteries" in plan.payload["content"]
    assert "Top up Translator phone credits" in plan.payload["content"]
    assert "Buy batteries" in plan.payload["content"]


def test_checklist_planner_uses_action_lines_for_schedule_images() -> None:
    runtime = ToolRuntime(_UnusedStore())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Create a checklist from this whiteboard plan.",
    )

    plan = runtime.plan(
        request,
        "create_checklist",
        [],
        specialist_analysis_text=(
            "Visible text extracted from the image:\n"
            "Tuesday Field Route\n"
            "Team: Ruth, Samuel, Mariam\n"
            "08:00 Load water filter demo kits\n"
            "09:15 Meet translator at Mako junction\n"
            "10:00 School hygiene lesson in Kati village"
        ),
        context_assets=[],
    )

    assert "Load water filter demo kits" in plan.payload["content"]
    assert "Meet translator at Mako junction" in plan.payload["content"]
    assert "Visible text extracted from the image" not in plan.payload["content"]


def test_note_planner_uses_specialist_lines_when_available() -> None:
    runtime = ToolRuntime(_UnusedStore())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Create a note summarizing the purchases from this receipt.",
    )

    plan = runtime.plan(
        request,
        "create_note",
        [],
        specialist_analysis_text=(
            "Visible text extracted from the image:\n"
            "Lantern batteries 2 @ 48.00\n"
            "Phone credit top-up 4 @ 42.50\n"
            "TOTAL 58.25"
        ),
        context_assets=[],
    )

    assert "Lantern batteries 2 @ 48.00" in plan.payload["content"]
    assert "Create a note summarizing the purchases from this receipt." not in plan.payload["content"]


def test_note_planner_does_not_use_raw_ocr_for_workspace_briefing_requests() -> None:
    runtime = ToolRuntime(_UnusedStore())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text=(
            "Separate topic again. Prepare a short workspace briefing about the current "
            "field assistant architecture and save it as a note."
        ),
    )

    plan = runtime.plan(
        request,
        "create_note",
        [],
        specialist_analysis_text=(
            "Visible text extracted from the image:\n"
            "[eater eet\n:\n— —\n"
            "ooto oot"
        ),
        context_assets=[],
    )

    assert "Visible text extracted from the image" not in plan.payload["content"]
    assert "workspace briefing" in plan.payload["content"].lower()


def test_note_planner_strips_workspace_review_lede_from_synthesized_note() -> None:
    runtime = ToolRuntime(_UnusedStore())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text="Prepare a short workspace briefing about the field assistant architecture.",
    )

    plan = runtime.plan(
        request,
        "create_note",
        [],
        specialist_analysis_text=(
            "I reviewed 4 workspace files in the workspace and pulled together the most relevant points.\n\n"
            "Key points:\n"
            "- Working title: Field Assistant\n"
            "- Key specifications live in the product spec\n\n"
            "Files reviewed:\n"
            "- offline-field-assistant-v1-product-spec.md"
        ),
        context_assets=[],
    )

    assert not plan.payload["content"].startswith("I reviewed")
    assert plan.payload["content"].startswith("Key points:")
    assert "Files reviewed:" in plan.payload["content"]


def test_export_brief_plan_and_execute_writes_markdown(tmp_path) -> None:
    runtime = ToolRuntime(_ExportStore(), export_storage_dir=str(tmp_path))
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text="Export a short workspace briefing as markdown.",
    )

    plan = runtime.plan(
        request,
        "export_brief",
        [],
        specialist_analysis_text=(
            "Key points:\n"
            "- Working title: Field Assistant\n\n"
            "Files reviewed:\n"
            "- offline-field-assistant-v1-product-spec.md"
        ),
        context_assets=[],
    )

    result = runtime.execute("export_brief", plan.payload)

    destination = tmp_path / "export-a-short-workspace-briefing-as-markdown.md"
    assert destination.exists()
    assert destination.read_text(encoding="utf-8").startswith(
        "# Export a short workspace briefing as markdown"
    )
    assert result["entity_type"] == "export"
    assert result["status"] == "completed"
