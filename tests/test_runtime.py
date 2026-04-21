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

    assert "architecture direction" in result.text.lower()
    assert "one orchestrator" in result.text.lower()
    assert "grounded specialist routes" in result.text.lower()


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
