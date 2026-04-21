from engine.contracts.api import AssistantMode
from engine.models.runtime import AssistantGenerationRequest, MockAssistantRuntime


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
