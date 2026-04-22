from engine.contracts.api import (
    AssistantMode,
    ConversationMemoryEntry,
    ConversationMemoryKind,
    SourceDomain,
)
from engine.models.runtime import (
    AssistantGenerationRequest,
    ConversationMemoryRankingRequest,
    MemoryFocusRequest,
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
        "memory_focus_kind": "conversation_memory",
        "memory_focus_reason": "The best bounded continuity anchor is Architecture direction.",
        "memory_focus_confidence": 0.88,
        "memory_focus_topic_frame": "Architecture direction",
        "memory_focus_clarifying_question": None,
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


def test_mock_runtime_can_answer_one_sentence_teaching_follow_up_from_memory() -> None:
    runtime = MockAssistantRuntime()

    result = runtime.generate(
        _request(
            user_text="If I had to say that in one sentence, how would you put it?",
            selected_memory_topic="prepare oral rehydration solution in the field",
            selected_memory_summary=(
                "start with the core action from [ORS Guidance] Oral rehydration guidance: "
                "mix the packet with safe water, continue small frequent sips, and monitor dehydration signs. "
                "Watch for worsening weakness, confusion, or inability to drink."
            ),
            active_topic="prepare oral rehydration solution in the field",
        )
    )

    assert result.text.startswith("In one sentence:")
    assert "mix the packet with safe water" in result.text.lower()
    assert "grounded in [ors guidance]" in result.text.lower()


def test_mock_runtime_can_answer_escalation_follow_up_from_memory() -> None:
    runtime = MockAssistantRuntime()

    result = runtime.generate(
        _request(
            user_text="What should make me stop and escalate?",
            selected_memory_topic="prepare oral rehydration solution in the field",
            selected_memory_summary=(
                "start with the core action from [ORS Guidance] Oral rehydration guidance: "
                "mix the packet with safe water, continue small frequent sips, and monitor dehydration signs. "
                "Watch for worsening weakness, confusion, or inability to drink."
            ),
            active_topic="prepare oral rehydration solution in the field",
        )
    )

    assert "stop and escalate if you see worsening weakness, confusion, or inability to drink" in result.text.lower()
    assert "ors guidance" in result.text.lower()


def test_mock_runtime_uses_saved_output_referent_for_topic_reentry() -> None:
    runtime = MockAssistantRuntime()

    result = runtime.generate(
        _request(
            user_text="Go back to that architecture point again.",
            selected_memory_topic=None,
            selected_memory_summary=None,
            memory_focus_kind="referent",
            memory_focus_reason="An explicit saved export is already selected.",
            memory_focus_confidence=1.0,
            memory_focus_topic_frame="Field Assistant Architecture Brief",
            referent_kind="saved_output",
            referent_tool="export_brief",
            referent_title="Field Assistant Architecture Brief",
            referent_excerpt=(
                "Local-first assistant built on Gemma. "
                "Uses bounded routing, retrieval, vision, and approvals."
            ),
        )
    )

    assert 'export "Field Assistant Architecture Brief"' in result.text
    assert "local-first assistant built on gemma" in result.text.lower()
    assert "bounded routing" in result.text.lower()
    assert "we can stay with what we were just discussing" not in result.text.lower()


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


def test_mock_runtime_ranks_grounded_teaching_memory_above_newer_teaching_distractor() -> None:
    runtime = MockAssistantRuntime()
    ranking = runtime.rank_memories(
        ConversationMemoryRankingRequest(
            user_text="If I had to say that in one sentence, how would you put it?",
            active_topic="Can we go back to that oral rehydration point again?",
            memories=[
                ConversationMemoryEntry(
                    id="memory_emphasis",
                    conversation_id="conv_1",
                    turn_id="turn_emphasis",
                    kind=ConversationMemoryKind.TEACHING,
                    topic="emphasize the first volunteer teaching point",
                    summary=(
                        "State the goal in plain language, demonstrate the first action once, "
                        "and repeat the key safety check."
                    ),
                    keywords=["volunteer", "first", "action"],
                    source_domain=SourceDomain.CONVERSATION,
                ),
                ConversationMemoryEntry(
                    id="memory_ors",
                    conversation_id="conv_1",
                    turn_id="turn_ors",
                    kind=ConversationMemoryKind.TEACHING,
                    topic="prepare oral rehydration solution in the field",
                    summary=(
                        "start with the core action from [ORS Guidance] Oral rehydration guidance: "
                        "mix the packet with safe water, continue small frequent sips, and monitor dehydration signs. "
                        "Watch for worsening weakness, confusion, or inability to drink."
                    ),
                    keywords=["oral", "rehydration", "guidance"],
                    source_domain=SourceDomain.CONVERSATION,
                ),
            ],
        )
    )

    assert ranking is not None
    assert ranking.ordered_ids[0] == "memory_ors"


def test_mock_runtime_resolves_memory_focus_to_stronger_teaching_memory() -> None:
    runtime = MockAssistantRuntime()

    focus = runtime.resolve_memory_focus(
        MemoryFocusRequest(
            user_text="If I had to say that in one sentence, how would you put it?",
            active_topic="Can we go back to that oral rehydration point again?",
            selected_referent_kind=None,
            selected_referent_title=None,
            selected_referent_summary=None,
            selected_evidence_summary=None,
            selected_evidence_facts=[],
            recent_topics=[
                "Can we go back to that oral rehydration point again?",
                "Separate tangent about lunch and coffee for a second.",
            ],
            memories=[
                ConversationMemoryEntry(
                    id="memory_emphasis",
                    conversation_id="conv_1",
                    turn_id="turn_emphasis",
                    kind=ConversationMemoryKind.TEACHING,
                    topic="emphasize the first volunteer teaching point",
                    summary=(
                        "State the goal in plain language, demonstrate the first action once, "
                        "and repeat the key safety check."
                    ),
                    keywords=["volunteer", "first", "action"],
                    source_domain=SourceDomain.CONVERSATION,
                ),
                ConversationMemoryEntry(
                    id="memory_ors",
                    conversation_id="conv_1",
                    turn_id="turn_ors",
                    kind=ConversationMemoryKind.TEACHING,
                    topic="prepare oral rehydration solution in the field",
                    summary=(
                        "start with the core action from [ORS Guidance] Oral rehydration guidance: "
                        "mix the packet with safe water, continue small frequent sips, and monitor dehydration signs. "
                        "Watch for worsening weakness, confusion, or inability to drink."
                    ),
                    keywords=["oral", "rehydration", "guidance"],
                    source_domain=SourceDomain.CONVERSATION,
                ),
            ],
        )
    )

    assert focus is not None
    assert focus.primary_anchor_kind == "conversation_memory"
    assert focus.memory_id == "memory_ors"
    assert focus.topic_frame == "prepare oral rehydration solution in the field"


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
    assert "latest checklist is titled" in result.text.lower()
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

    assert "i drafted a checklist here." in result.text.lower()
    assert "ready for your approval" not in result.text.lower()
    assert "talk normally" not in result.text.lower()


def test_mock_runtime_plain_conversation_request_stays_simple() -> None:
    runtime = MockAssistantRuntime()

    result = runtime.generate(
        _request(
            user_text="Can we just talk normally for a minute?",
            selected_memory_topic=None,
            selected_memory_summary=None,
            active_topic=None,
        )
    )

    assert result.text == "Yes. We can just talk this through."
    assert "local analysis" not in result.text.lower()
    assert "task execution" not in result.text.lower()


def test_mock_runtime_handles_colloquial_greeting_naturally() -> None:
    runtime = MockAssistantRuntime()

    result = runtime.generate(
        _request(
            user_text="yoo",
            is_follow_up=False,
            selected_memory_topic=None,
            selected_memory_summary=None,
            active_topic=None,
        )
    )

    assert result.text == "Hey. What's up?"
