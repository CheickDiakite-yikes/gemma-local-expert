from engine.contracts.api import AssistantMode, ConversationTurnRequest
from engine.context.service import ConversationContextSnapshot
from engine.models.gateway import ModelRouteSelection
from engine.orchestrator.prompting import PromptBuilder
from engine.policy.service import PolicyDecision
from engine.routing.service import RouteDecision


def test_prompt_builder_adds_teaching_guidance_for_how_to_turns() -> None:
    builder = PromptBuilder()
    context = builder.build(
        turn=ConversationTurnRequest(
            conversation_id="conv_teach",
            mode=AssistantMode.FIELD,
            text="Teach me how to prepare oral rehydration solution in the field.",
        ),
        history=[],
        assets=[],
        context_assets=[],
        conversation_context=None,
        specialist_analysis=None,
        workspace_summary=None,
        route=RouteDecision(),
        policy=PolicyDecision(),
        model_selection=ModelRouteSelection(
            assistant_model="gemma-4-e2b-it-4bit",
            embedding_model="embeddinggemma-300m",
        ),
        results=[],
        tool_result=None,
    )

    assert "practical field instructor" in context.messages[0]["content"]
    assert "Avoid handout-style headings" in context.messages[0]["content"]


def test_prompt_builder_adds_conversation_style_guidance() -> None:
    builder = PromptBuilder()
    context = builder.build(
        turn=ConversationTurnRequest(
            conversation_id="conv_chat",
            mode=AssistantMode.FIELD,
            text="Hey, can you help me think through tomorrow without overcomplicating it?",
        ),
        history=[],
        assets=[],
        context_assets=[],
        conversation_context=None,
        specialist_analysis=None,
        workspace_summary=None,
        route=RouteDecision(interaction_kind="conversation"),
        policy=PolicyDecision(),
        model_selection=ModelRouteSelection(
            assistant_model="gemma-4-e2b-it-4bit",
            embedding_model="embeddinggemma-300m",
        ),
        results=[],
        tool_result=None,
    )

    prompt = context.messages[0]["content"]
    assert "Sound like a calm capable collaborator" in prompt
    assert "Avoid stiff openings like 'Understood' or 'I can certainly'" in prompt
    assert "This is ordinary conversation. Answer naturally, directly, and with minimal ceremony." in prompt


def test_prompt_builder_adds_supportive_conversation_guidance() -> None:
    builder = PromptBuilder()
    context = builder.build(
        turn=ConversationTurnRequest(
            conversation_id="conv_support",
            mode=AssistantMode.FIELD,
            text=(
                "Honestly I'm a little anxious about tomorrow. "
                "No checklist right now, just help me calm down for a second."
            ),
        ),
        history=[],
        assets=[],
        context_assets=[],
        conversation_context=None,
        specialist_analysis=None,
        workspace_summary=None,
        route=RouteDecision(interaction_kind="conversation"),
        policy=PolicyDecision(),
        model_selection=ModelRouteSelection(
            assistant_model="gemma-4-e2b-it-4bit",
            embedding_model="embeddinggemma-300m",
        ),
        results=[],
        tool_result=None,
    )

    prompt = context.messages[0]["content"]
    assert "The user wants reassurance or emotional grounding." in prompt
    assert "Do not turn this into a checklist" in prompt


def test_prompt_builder_includes_continuity_snapshot_when_available() -> None:
    builder = PromptBuilder()
    context = builder.build(
        turn=ConversationTurnRequest(
            conversation_id="conv_context",
            mode=AssistantMode.GENERAL,
            text="What did you mean by that?",
        ),
        history=[],
        assets=[],
        context_assets=[],
        conversation_context=ConversationContextSnapshot(
            active_topic="Teach me how to explain oral rehydration solution to a new volunteer.",
            selected_context_reason=None,
            selected_referent_kind="pending_output",
            selected_referent_tool="create_note",
            selected_referent_title="Architecture brief",
            selected_referent_summary="Architecture brief",
            selected_referent_excerpt="Field Assistant architecture overview Uses bounded routing and explicit approvals.",
            pending_approval_tool="create_note",
            pending_approval_summary="Architecture brief",
            pending_approval_excerpt="Field Assistant architecture overview Uses bounded routing and explicit approvals.",
        ),
        specialist_analysis=None,
        workspace_summary=None,
        route=RouteDecision(interaction_kind="conversation", is_follow_up=True),
        policy=PolicyDecision(),
        model_selection=ModelRouteSelection(
            assistant_model="gemma-4-e2b-it-4bit",
            embedding_model="embeddinggemma-300m",
        ),
        results=[],
        tool_result=None,
    )

    system_prompt = context.messages[0]["content"]
    user_prompt = context.messages[-1]["content"]
    assert "structured continuity snapshot" in system_prompt
    assert "Active topic:" in user_prompt
    assert "Likely current referent:" in user_prompt
    assert "Likely referent preview:" in user_prompt


def test_prompt_builder_adds_draft_follow_up_guidance() -> None:
    builder = PromptBuilder()
    context = builder.build(
        turn=ConversationTurnRequest(
            conversation_id="conv_draft",
            mode=AssistantMode.RESEARCH,
            text="What title are you using for that draft?",
        ),
        history=[],
        assets=[],
        context_assets=[],
        conversation_context=ConversationContextSnapshot(
            selected_referent_kind="pending_output",
            selected_referent_tool="create_note",
            selected_referent_title="Architecture brief",
            selected_referent_summary="Architecture brief",
            selected_referent_excerpt="Field Assistant architecture overview Uses bounded routing and explicit approvals.",
            pending_approval_tool="create_note",
            pending_approval_summary="Architecture brief",
            pending_approval_excerpt="Field Assistant architecture overview Uses bounded routing and explicit approvals.",
        ),
        specialist_analysis=None,
        workspace_summary=None,
        route=RouteDecision(interaction_kind="draft_follow_up", is_follow_up=True),
        policy=PolicyDecision(),
        model_selection=ModelRouteSelection(
            assistant_model="gemma-4-e2b-it-4bit",
            embedding_model="embeddinggemma-300m",
        ),
        results=[],
        tool_result=None,
    )

    prompt = context.messages[0]["content"]
    assert "current local draft or recent saved output" in prompt
    assert "answer with the current title" in prompt
    assert "summarize that preview" in prompt
