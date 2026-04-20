from engine.contracts.api import (
    AssetCareContext,
    AssetKind,
    AssetSummary,
    AssistantMode,
    ConversationMessage,
    ConversationTurnRequest,
)
from engine.routing.service import RouterService
from engine.tools.registry import ToolRegistry


def test_translation_turn_routes_to_translation_specialist() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.FIELD,
        text="Translate this poster into English.",
        asset_ids=["asset_1"],
    )

    route = router.decide(request)

    assert route.specialist_model == "translategemma"


def test_checklist_turn_proposes_checklist_tool() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.FIELD,
        text="Create a checklist for tomorrow.",
    )

    route = router.decide(request)

    assert route.proposed_tool == "create_checklist"


def test_image_description_routes_to_vision_specialist() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Describe this screenshot conservatively.",
        asset_ids=["asset_1"],
    )

    route = router.decide(
        request,
        assets=[
            AssetSummary(
                id="asset_1",
                display_name="screen.png",
                source_path="screen.png",
                kind=AssetKind.IMAGE,
                care_context=AssetCareContext.GENERAL,
            )
        ],
    )

    assert route.specialist_model == "paligemma"
    assert route.needs_retrieval is False


def test_image_summary_routes_to_vision_specialist_without_retrieval() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Summarize the visible supply situation and note what looks low or urgent.",
        asset_ids=["asset_1"],
    )

    route = router.decide(
        request,
        assets=[
            AssetSummary(
                id="asset_1",
                display_name="board.png",
                source_path="board.png",
                kind=AssetKind.IMAGE,
                care_context=AssetCareContext.GENERAL,
            )
        ],
    )

    assert route.specialist_model == "paligemma"
    assert route.needs_retrieval is False


def test_conversational_image_turn_stays_conversational_without_tool_proposal() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="I'm not trying to save anything right now. What do you notice first in this image?",
        asset_ids=["asset_1"],
    )

    route = router.decide(
        request,
        assets=[
            AssetSummary(
                id="asset_1",
                display_name="board.png",
                source_path="board.png",
                kind=AssetKind.IMAGE,
                care_context=AssetCareContext.GENERAL,
            )
        ],
    )

    assert route.specialist_model == "paligemma"
    assert route.proposed_tool is None
    assert route.interaction_kind == "vision"


def test_heatmap_request_routes_to_overlay_tool_with_image_context() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Do a segmented heatmap layering of this x-ray image.",
        asset_ids=["asset_1"],
    )

    route = router.decide(
        request,
        assets=[
            AssetSummary(
                id="asset_1",
                display_name="xray.png",
                source_path="xray.png",
                kind=AssetKind.IMAGE,
                care_context=AssetCareContext.GENERAL,
            )
        ],
    )

    assert route.specialist_model == "paligemma"
    assert route.proposed_tool == "generate_heatmap_overlay"


def test_video_monitoring_turn_routes_to_tracking_specialist() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Review this mining video and track unsafe tools or machines conservatively.",
        asset_ids=["asset_video"],
    )

    route = router.decide(
        request,
        assets=[
            AssetSummary(
                id="asset_video",
                display_name="mining-site.mov",
                source_path="mining-site.mov",
                kind=AssetKind.VIDEO,
                care_context=AssetCareContext.GENERAL,
            )
        ],
    )

    assert route.specialist_model == "sam3"
    assert route.needs_retrieval is False


def test_workspace_agent_turn_routes_to_agent_path() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text="Search this workspace and summarize the field prep docs.",
    )

    route = router.decide(request)

    assert route.agent_run is True
    assert route.needs_retrieval is False


def test_general_conversation_stays_on_general_path() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Hey, can we just talk normally for a minute?",
    )

    route = router.decide(request)

    assert route.needs_retrieval is False
    assert route.specialist_model is None
    assert route.proposed_tool is None
    assert route.interaction_kind == "conversation"


def test_supportive_field_turn_stays_conversational_without_retrieval() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.FIELD,
        text=(
            "Honestly I'm a little anxious about tomorrow. "
            "No checklist right now, just help me calm down for a second."
        ),
        enabled_knowledge_pack_ids=["local-pack"],
    )

    route = router.decide(request)

    assert route.interaction_kind == "conversation"
    assert route.needs_retrieval is False
    assert route.specialist_model is None


def test_follow_up_short_turn_is_marked_as_follow_up() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="What do you mean by that?",
    )

    route = router.decide(
        request,
        history=[
            ConversationMessage(
                role="assistant",
                content="You can talk normally here or switch into local task work.",
            )
        ],
    )

    assert route.is_follow_up is True
    assert route.interaction_kind == "conversation"


def test_field_teaching_request_can_trigger_local_retrieval() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.FIELD,
        text="Teach me how to prepare oral rehydration solution in the field.",
    )

    route = router.decide(request)

    assert route.interaction_kind == "teaching"
    assert route.needs_retrieval is True


def test_workspace_request_overrides_recent_video_context() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text="Prepare a briefing from the relevant workspace files.",
    )

    route = router.decide(
        request,
        contextual_assets=[
            AssetSummary(
                id="asset_video",
                display_name="mine.mov",
                source_path="mine.mov",
                kind=AssetKind.VIDEO,
                care_context=AssetCareContext.GENERAL,
            )
        ],
        history=[
            ConversationMessage(role="assistant", content="Reviewed the attached mining clip.")
        ],
    )

    assert route.agent_run is True
    assert route.specialist_model is None


def test_separate_topic_workspace_briefing_overrides_recent_video_context() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text=(
            "Separate topic again. Prepare a short workspace briefing about the current "
            "field assistant architecture and save it as a note, but keep it concise."
        ),
    )

    route = router.decide(
        request,
        contextual_assets=[
            AssetSummary(
                id="asset_video",
                display_name="mine.mov",
                source_path="mine.mov",
                kind=AssetKind.VIDEO,
                care_context=AssetCareContext.GENERAL,
            )
        ],
        history=[
            ConversationMessage(role="assistant", content="Reviewed the attached mining clip.")
        ],
    )

    assert route.agent_run is True
    assert route.specialist_model is None


def test_topic_reset_overrides_recent_image_context() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Also, can we switch topics and just chat normally again for a second?",
    )

    route = router.decide(
        request,
        contextual_assets=[
            AssetSummary(
                id="asset_image",
                display_name="board.png",
                source_path="board.png",
                kind=AssetKind.IMAGE,
                care_context=AssetCareContext.GENERAL,
            )
        ],
        history=[
            ConversationMessage(
                role="assistant",
                content="Visible text extracted from the image: Lantern batteries low.",
            )
        ],
    )

    assert route.interaction_kind == "conversation"
    assert route.specialist_model is None
    assert route.is_follow_up is False


def test_unrelated_conversation_does_not_reuse_recent_video_context() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="I’m tired tonight. How would you tell me to wind down simply?",
    )

    route = router.decide(
        request,
        contextual_assets=[
            AssetSummary(
                id="asset_video",
                display_name="mine.mov",
                source_path="mine.mov",
                kind=AssetKind.VIDEO,
                care_context=AssetCareContext.GENERAL,
            )
        ],
        history=[
            ConversationMessage(role="assistant", content="Reviewed the attached mining clip.")
        ],
    )

    assert route.interaction_kind == "conversation"
    assert route.specialist_model is None
