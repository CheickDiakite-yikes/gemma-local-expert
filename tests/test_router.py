from engine.contracts.api import AssetCareContext, AssetKind, AssetSummary, AssistantMode, ConversationTurnRequest
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
