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
        route=RouteDecision(),
        policy=PolicyDecision(),
        model_selection=ModelRouteSelection(
            assistant_model="gemma-4-e2b-it-4bit",
            embedding_model="embeddinggemma-300m",
        ),
        results=[],
        tool_result=None,
    )

    assert "capable field instructor" in context.messages[0]["content"]
