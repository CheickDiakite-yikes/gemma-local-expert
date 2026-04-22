from engine.context.memory import ConversationMemoryService
from engine.contracts.api import SourceDomain
from engine.context.service import ConversationContextSnapshot
from engine.models.runtime import MockAssistantRuntime


def test_memory_service_skips_generic_talk_normally_reply() -> None:
    service = ConversationMemoryService(MockAssistantRuntime())

    entry = service.build_entry(
        conversation_id="conv_1",
        turn_id="turn_1",
        user_text="Actually just talk normally with me for a second.",
        assistant_text=(
            "Yes. We can just talk this through."
        ),
        interaction_kind="conversation",
        active_topic="Actually just talk normally with me for a second.",
        source_domain=None,
        asset_ids=[],
        referent_kind=None,
        referent_title=None,
        referent_excerpt=None,
        evidence_packet=None,
        workspace_summary_text=None,
        tool_name=None,
    )

    assert entry is None


def test_memory_service_skips_missing_output_reply() -> None:
    service = ConversationMemoryService(MockAssistantRuntime())

    entry = service.build_entry(
        conversation_id="conv_1",
        turn_id="turn_2",
        user_text="What was in the report again?",
        assistant_text=(
            "There is no current report yet. I held off on creating it because the local "
            "evidence is not grounded enough for a durable draft."
        ),
        interaction_kind="draft_follow_up",
        active_topic="Create a report summarizing the site review.",
        source_domain=None,
        asset_ids=[],
        referent_kind="missing_output",
        referent_title=None,
        referent_excerpt=None,
        evidence_packet=None,
        workspace_summary_text=None,
        tool_name=None,
    )

    assert entry is None


def test_memory_service_skips_output_recall_turn_without_new_tool() -> None:
    service = ConversationMemoryService(MockAssistantRuntime())

    entry = service.build_entry(
        conversation_id="conv_1",
        turn_id="turn_2b",
        user_text="Compare the report title and export title for me.",
        assistant_text=(
            "There is no current report yet. "
            'The newer export is titled "Field Assistant Architecture Brief".'
        ),
        interaction_kind="draft_follow_up",
        active_topic="What is the export title now?",
        source_domain=None,
        asset_ids=[],
        referent_kind=None,
        referent_title=None,
        referent_excerpt=None,
        evidence_packet=None,
        workspace_summary_text=None,
        tool_name=None,
    )

    assert entry is None


def test_memory_service_keeps_grounded_workspace_content_for_output_memory() -> None:
    service = ConversationMemoryService(MockAssistantRuntime())

    entry = service.build_entry(
        conversation_id="conv_1",
        turn_id="turn_3",
        user_text="Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.",
        assistant_text=(
            "Here is a concise briefing:\n\n"
            "Key points:\n- Uses bounded routing, retrieval, vision, and approvals\n"
            "- Local-first assistant built on Gemma"
        ),
        interaction_kind="agent",
        active_topic="Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.",
        source_domain=SourceDomain.WORKSPACE,
        asset_ids=[],
        referent_kind="pending_output",
        referent_title="Field Assistant Architecture Brief",
        referent_excerpt=None,
        evidence_packet=None,
        workspace_summary_text=(
            "I reviewed 1 workspace file in the workspace and pulled together the most relevant points.\n\n"
            "Key points:\n"
            "- Uses bounded routing, retrieval, vision, and approvals\n"
            "- Local-first assistant built on Gemma\n\n"
            "Files reviewed:\n- field-assistant-architecture.md"
        ),
        tool_name="export_brief",
    )

    assert entry is not None
    assert entry.kind.value == "output"
    assert entry.source_domain == SourceDomain.WORKSPACE
    assert entry.summary.startswith('Markdown Export "Field Assistant Architecture Brief" centers on:')
    assert "local-first assistant built on gemma" in entry.summary.lower()
    assert "i reviewed" not in entry.summary.lower()
    assert "files reviewed" not in entry.summary.lower()


def test_memory_service_normalizes_teaching_topic_before_storing() -> None:
    service = ConversationMemoryService(MockAssistantRuntime())

    entry = service.build_entry(
        conversation_id="conv_1",
        turn_id="turn_4",
        user_text="Teach me how to prepare oral rehydration solution in the field.",
        assistant_text=(
            "Here is a practical way to approach oral rehydration solution in the field: "
            "start with the core action from ORS guidance."
        ),
        interaction_kind="teaching",
        active_topic="Teach me how to prepare oral rehydration solution in the field.",
        source_domain=None,
        asset_ids=[],
        referent_kind=None,
        referent_title=None,
        referent_excerpt=None,
        evidence_packet=None,
        workspace_summary_text=None,
        tool_name=None,
    )

    assert entry is not None
    assert entry.topic.lower() == "prepare oral rehydration solution in the field"
    assert entry.summary.lower().startswith("start with the core action from ors guidance")
    assert "here is a practical way" not in entry.summary.lower()


def test_memory_service_prefers_referent_excerpt_for_output_memory() -> None:
    service = ConversationMemoryService(MockAssistantRuntime())

    entry = service.build_entry(
        conversation_id="conv_1",
        turn_id="turn_5",
        user_text="Create a checklist from those two shortages for tomorrow morning.",
        assistant_text="I prepared a checklist draft and it is ready for your approval.",
        interaction_kind="task",
        active_topic="Create a checklist from those two shortages for tomorrow morning.",
        source_domain=SourceDomain.IMAGE,
        asset_ids=["asset_image_1"],
        referent_kind="pending_output",
        referent_title="Departure shortage checklist",
        referent_excerpt="Pack lantern batteries. Refill translator phone credits.",
        evidence_packet=None,
        workspace_summary_text=None,
        tool_name="create_checklist",
    )

    assert entry is not None
    assert "current work product" not in entry.summary.lower()
    assert "lantern batteries" in entry.summary.lower()


def test_memory_service_normalizes_recap_style_summary_before_storing() -> None:
    service = ConversationMemoryService(MockAssistantRuntime())

    entry = service.build_entry(
        conversation_id="conv_1",
        turn_id="turn_6",
        user_text="Summarize the architecture direction plainly.",
        assistant_text=(
            "Yes. Earlier we were talking about architecture direction. "
            "The main point was: Keep one orchestrator with grounded specialist routes "
            "and explicit approvals."
        ),
        interaction_kind="conversation",
        active_topic="Architecture direction",
        source_domain=None,
        asset_ids=[],
        referent_kind=None,
        referent_title=None,
        referent_excerpt=None,
        evidence_packet=None,
        workspace_summary_text=None,
        tool_name=None,
    )

    assert entry is not None
    assert entry.summary == "Keep one orchestrator with grounded specialist routes and explicit approvals."


def test_memory_service_skips_derivative_teaching_follow_up_turn() -> None:
    service = ConversationMemoryService(MockAssistantRuntime())

    entry = service.build_entry(
        conversation_id="conv_1",
        turn_id="turn_7",
        user_text="What should make me stop and escalate?",
        assistant_text=(
            "Stop and escalate if you see worsening weakness, confusion, or inability to drink. "
            "That comes from [ORS Guidance]."
        ),
        interaction_kind="conversation",
        active_topic="Can we go back to that oral rehydration point again?",
        source_domain=None,
        asset_ids=[],
        referent_kind=None,
        referent_title=None,
        referent_excerpt=None,
        evidence_packet=None,
        workspace_summary_text=None,
        tool_name=None,
    )

    assert entry is None


def test_memory_service_resolve_focus_keeps_explicit_referent_override() -> None:
    service = ConversationMemoryService(MockAssistantRuntime())

    focus = service.resolve_focus(
        user_text="What title is that draft using?",
        conversation_context=ConversationContextSnapshot(
            active_topic="Field Assistant Architecture Briefing",
            selected_referent_kind="pending_output",
            selected_referent_tool="export_brief",
            selected_referent_title="Field Assistant Architecture Brief",
            selected_referent_summary="Field Assistant Architecture Brief",
        ),
        entries=[],
        limit=4,
    )

    assert focus is not None
    assert focus.primary_anchor_kind == "referent"
    assert focus.topic_frame == "Field Assistant Architecture Brief"
