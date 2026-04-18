from engine.contracts.api import AssistantMode, ConversationTurnRequest
from engine.tools.runtime import ToolRuntime


class _UnusedStore:
    def create_note(self, *args, **kwargs):  # pragma: no cover - not used in this test
        raise NotImplementedError

    def create_task(self, *args, **kwargs):  # pragma: no cover - not used in this test
        raise NotImplementedError


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
