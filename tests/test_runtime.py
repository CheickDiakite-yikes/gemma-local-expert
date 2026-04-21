from engine.contracts.api import (
    AssistantMode,
    ConversationMemoryEntry,
    ConversationMemoryKind,
    SourceDomain,
)
from engine.models.runtime import (
    AssistantGenerationRequest,
    ConversationMemoryRankingRequest,
    MockAssistantRuntime,
)


def _request(**overrides) -> AssistantGenerationRequest:
    payload = {
        "conversation_id": "conv_1",
        "turn_id": "turn_1",
        "mode": AssistantMode.GENERAL,
        "user_text": "Can we go back to that architecture point again?",
        "messages": [],
        "citations": [],
        "interaction_kind": "conversation",
        "is_follow_up": True,
        "active_topic": "Explain the architecture direction plainly.",
        "conversation_context_summary": None,
        "selected_memory_topic": "Architecture direction",
        "selected_memory_summary": (
            "Keep one orchestrator with grounded specialist routes and explicit approvals."
        ),
        "referent_kind": None,
        "referent_tool": None,
        "referent_title": None,
        "referent_summary": None,
        "referent_excerpt": None,
        "proposed_tool": None,
        "approval_required": False,
        "tool_result": None,
        "assistant_model_name": "gemma-4-e2b-it-4bit",
        "assistant_model_source": None,
        "specialist_model_name": None,
        "evidence_packet": None,
        "specialist_analysis_text": None,
        "workspace_summary_text": None,
        "max_tokens": 256,
        "temperature": 0.0,
        "top_p": 1.0,
    }
    payload.update(overrides)
    return AssistantGenerationRequest(**payload)


def test_mock_runtime_uses_selected_memory_for_topic_recall_follow_up() -> None:
    runtime = MockAssistantRuntime()

    result = runtime.generate(_request())

    assert "earlier we were talking about architecture direction" in result.text.lower()
    assert "architecture direction" in result.text.lower()
    assert "one orchestrator" in result.text.lower()
    assert "grounded specialist routes" in result.text.lower()


def test_mock_runtime_humanizes_action_topic_in_memory_recall() -> None:
    runtime = MockAssistantRuntime()

    result = runtime.generate(
        _request(
            user_text="Can we go back to that oral rehydration point again?",
            selected_memory_topic="prepare oral rehydration solution in the field",
            selected_memory_summary=(
                "Here is a practical way to prepare oral rehydration solution in the field: "
                "start with the core action from [ORS Guidance] Oral rehydration guidance."
            ),
            active_topic="Separate tangent about lunch.",
        )
    )

    assert "earlier we were talking about how to prepare oral rehydration solution in the field" in result.text.lower()
    assert "was about prepare oral rehydration" not in result.text.lower()
    assert "main point was: start with the core action" in result.text.lower()


def test_mock_runtime_ranks_matching_memory_above_newer_distractor() -> None:
    runtime = MockAssistantRuntime()
    ranking = runtime.rank_memories(
        ConversationMemoryRankingRequest(
            user_text="Can we go back to the architecture point again?",
            active_topic="Separate tangent about lunch.",
            memories=[
                ConversationMemoryEntry(
                    id="memory_lunch",
                    conversation_id="conv_1",
                    turn_id="turn_lunch",
                    kind=ConversationMemoryKind.GENERAL,
                    topic="Lunch tangent",
                    summary="We briefly talked about lunch options and coffee.",
                    keywords=["lunch", "coffee"],
                    source_domain=SourceDomain.CONVERSATION,
                ),
                ConversationMemoryEntry(
                    id="memory_architecture",
                    conversation_id="conv_1",
                    turn_id="turn_architecture",
                    kind=ConversationMemoryKind.GENERAL,
                    topic="Architecture direction",
                    summary="Keep one orchestrator with grounded specialist routes and explicit approvals.",
                    keywords=["architecture", "orchestrator", "approvals"],
                    source_domain=SourceDomain.CONVERSATION,
                ),
            ],
        )
    )

    assert ranking is not None
    assert ranking.ordered_ids[0] == "memory_architecture"


def test_mock_runtime_can_fallback_to_recent_context_memory_summary() -> None:
    runtime = MockAssistantRuntime()

    result = runtime.generate(
        _request(
            selected_memory_topic=None,
            selected_memory_summary=None,
            conversation_context_summary=(
                "Active topic: What is the export title now?\n"
                "Recent conversation memories: "
                "Field Assistant Architecture Briefing: Markdown Export \"Field Assistant Architecture Briefing\" centers on: "
                "Uses bounded routing and approvals with a local-first assistant built on Gemma. ; "
                "Teach me how to prepare oral rehydration solution in the field: "
                "Start with the core action from ORS guidance."
            ),
            user_text="Go back to that architecture point again.",
        )
    )

    assert "field assistant architecture briefing" in result.text.lower()
    assert "local-first assistant" in result.text.lower()


def test_mock_runtime_saved_output_title_follow_up_avoids_draft_wording() -> None:
    runtime = MockAssistantRuntime()

    result = runtime.generate(
        _request(
            interaction_kind="draft_follow_up",
            referent_kind="saved_output",
            referent_tool="create_checklist",
            referent_title="Departure shortage checklist",
            user_text="What is that checklist called?",
        )
    )

    assert 'Departure shortage checklist' in result.text
    assert "saved checklist is titled" in result.text.lower()
    assert "saved checklist draft" not in result.text.lower()


def test_mock_runtime_tool_proposal_does_not_prepend_generic_chat_filler() -> None:
    runtime = MockAssistantRuntime()

    result = runtime.generate(
        _request(
            interaction_kind="task",
            is_follow_up=False,
            user_text="Create a checklist from those two shortages for tomorrow morning.",
            proposed_tool="create_checklist",
            approval_required=True,
            selected_memory_topic=None,
            selected_memory_summary=None,
            active_topic=None,
        )
    )

    assert "ready for your approval" in result.text.lower()
    assert "talk normally" not in result.text.lower()
