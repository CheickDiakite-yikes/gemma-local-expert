from engine.contracts.api import AssistantMode, ConversationTurnRequest
from engine.contracts.api import ConversationMessage
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
    assert "answer with the title directly" in prompt


def test_prompt_builder_adds_selected_work_product_referent_block() -> None:
    builder = PromptBuilder()
    context = builder.build(
        turn=ConversationTurnRequest(
            conversation_id="conv_draft",
            mode=AssistantMode.RESEARCH,
            text="What was in that checklist again?",
        ),
        history=[],
        assets=[],
        context_assets=[],
        conversation_context=ConversationContextSnapshot(
            selected_referent_kind="pending_output",
            selected_referent_tool="create_checklist",
            selected_referent_title="Departure checklist",
            selected_referent_excerpt="Pack lantern batteries Bring consent forms",
            pending_approval_tool="create_checklist",
            pending_approval_summary="Departure checklist",
        ),
        specialist_analysis=None,
        workspace_summary=None,
        route=RouteDecision(interaction_kind="draft_follow_up", is_follow_up=True),
        policy=PolicyDecision(approval_required=False),
        results=[],
        tool_result=None,
        model_selection=ModelRouteSelection(
            assistant_model="gemma-4-e2b-it-4bit",
            embedding_model="embeddinggemma-300m",
        ),
    )

    prompt = "\n\n".join(message["content"] for message in context.messages)
    assert "Selected work-product referent:" in prompt
    assert "tool=create_checklist" in prompt
    assert "title=Departure checklist" in prompt
    assert "answer with the current title" in prompt
    assert "summarize that preview" in prompt


def test_prompt_builder_keeps_draft_follow_up_anchor_without_replaying_history() -> None:
    builder = PromptBuilder()
    history = [
        ConversationMessage(
            role="user",
            content="Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.",
        ),
        ConversationMessage(
            role="assistant",
            content=(
                "Here is a concise briefing:\n\n"
                "Field Assistant Architecture Overview\n\n"
                "- Local-first assistant built on Gemma\n"
                "- Uses bounded routing, retrieval, vision, and approvals."
            ),
        ),
        ConversationMessage(role="user", content="Totally different tangent about lunch plans."),
        ConversationMessage(role="assistant", content="We can talk about lunch too if you want."),
        ConversationMessage(role="user", content="Another unrelated aside about coffee beans."),
        ConversationMessage(role="assistant", content="Coffee notes are separate from the draft."),
        ConversationMessage(role="user", content="Short filler one."),
        ConversationMessage(role="assistant", content="Short filler reply one."),
        ConversationMessage(role="user", content="Short filler two."),
        ConversationMessage(role="assistant", content="Short filler reply two."),
    ]
    context = builder.build(
        turn=ConversationTurnRequest(
            conversation_id="conv_long_history",
            mode=AssistantMode.RESEARCH,
            text="What's in that draft again?",
        ),
        history=history,
        assets=[],
        context_assets=[],
        conversation_context=ConversationContextSnapshot(
            active_topic="Prepare a short workspace briefing about the current field assistant architecture.",
            selected_referent_kind="pending_output",
            selected_referent_tool="export_brief",
            selected_referent_title="Field Assistant Architecture Briefing",
            selected_referent_summary="Field Assistant Architecture Briefing",
            selected_referent_excerpt="Local-first assistant built on Gemma. Uses bounded routing, retrieval, vision, and approvals.",
            pending_approval_id="approval_demo",
            pending_approval_tool="export_brief",
            pending_approval_summary="Field Assistant Architecture Briefing",
            pending_approval_excerpt="Local-first assistant built on Gemma. Uses bounded routing, retrieval, vision, and approvals.",
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

    prompt_messages = context.messages[1:-1]
    user_prompt = context.messages[-1]["content"]
    assert "bounded slice of earlier chat" in context.messages[0]["content"]
    assert prompt_messages == []
    assert "Selected work-product referent:" in user_prompt
    assert "title=Field Assistant Architecture Briefing" in user_prompt
    assert "Local-first assistant built on Gemma" in user_prompt
    assert "totally different tangent about lunch plans" not in user_prompt.lower()


def test_prompt_builder_strips_low_signal_workflow_lines_from_assistant_history() -> None:
    builder = PromptBuilder()
    context = builder.build(
        turn=ConversationTurnRequest(
            conversation_id="conv_history_cleanup",
            mode=AssistantMode.FIELD,
            text="What did you mean by that?",
        ),
        history=[
            ConversationMessage(
                role="assistant",
                content=(
                    "Please confirm if you would like me to proceed with creating the checklist.\n"
                    "Workspace scope: /Users/example/project\n"
                    "Key points:\n"
                    "- Pack oral rehydration salts\n"
                    "- Pack backup batteries"
                ),
            )
        ],
        assets=[],
        context_assets=[],
        conversation_context=ConversationContextSnapshot(
            active_topic="Checklist for tomorrow's visit."
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

    assistant_history = context.messages[1]["content"]
    assert "Please confirm" not in assistant_history
    assert "Workspace scope:" not in assistant_history
    assert "Pack oral rehydration salts" in assistant_history


def test_prompt_builder_keeps_work_product_follow_up_singular() -> None:
    builder = PromptBuilder()
    history = [
        ConversationMessage(
            role="assistant",
            content="I created the checklist draft for tomorrow's village visits.",
        ),
        ConversationMessage(
            role="assistant",
            content=(
                "Here is a brief overview of the current Field Assistant architecture.\n"
                "This document converts the v1 product specification into an implementation architecture."
            ),
        ),
    ]
    context = builder.build(
        turn=ConversationTurnRequest(
            conversation_id="conv_singular_follow_up",
            mode=AssistantMode.RESEARCH,
            text="What was in that checklist again?",
        ),
        history=history,
        assets=[],
        context_assets=[],
        conversation_context=ConversationContextSnapshot(
            selected_referent_kind="saved_output",
            selected_referent_tool="create_checklist",
            selected_referent_title="Checklist for tomorrow's village visits",
            selected_referent_summary="Checklist for tomorrow's village visits",
            selected_referent_excerpt="Pack oral rehydration salts. Confirm translator contact sheet before departure.",
            pending_approval_tool="export_brief",
            pending_approval_summary="Field Assistant Architecture Briefing",
            pending_approval_excerpt="This document converts the v1 product specification into an implementation architecture.",
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

    assert [message["role"] for message in context.messages] == ["system", "user"]
    prompt = context.messages[-1]["content"]
    assert "Selected work-product referent:" in prompt
    assert "title=Checklist for tomorrow's village visits" in prompt
    assert "Pending draft:" not in prompt
    assert "Most recent saved output:" not in prompt
