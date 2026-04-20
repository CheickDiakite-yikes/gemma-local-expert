from engine.contracts.api import AssistantMode, ConversationTurnRequest
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
