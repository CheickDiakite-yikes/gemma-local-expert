from engine.contracts.api import (
    ApprovalState,
    AssetCareContext,
    AssetKind,
    AssetSummary,
    AssistantMode,
    ConversationMessage,
    ConversationTurnRequest,
    SourceDomain,
    TranscriptMessage,
)
from engine.context.service import ConversationContextService
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


def test_report_turn_proposes_report_tool() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text="Create a report summarizing the current field assistant architecture.",
    )

    route = router.decide(request)

    assert route.proposed_tool == "create_report"


def test_video_report_request_does_not_false_match_workspace_agent() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.FIELD,
        text=(
            "Prepare a report comparing both videos, call out any possible weapon or process "
            "findings conservatively, and save it as a report."
        ),
    )

    route = router.decide(request)

    assert route.agent_run is False
    assert route.proposed_tool == "create_report"


def test_message_draft_turn_proposes_message_draft_tool() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Draft a reply confirming tomorrow's field visit at 8am.",
    )

    route = router.decide(request)

    assert route.proposed_tool == "create_message_draft"


def test_export_reference_question_does_not_propose_export_tool() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="What was in the earlier report again, what was in the checklist, and what is the newer export called?",
    )

    route = router.decide(request)

    assert route.proposed_tool is None


def test_report_title_question_does_not_propose_report_tool() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="What title are you using for that report draft right now?",
    )

    route = router.decide(request)

    assert route.proposed_tool is None


def test_report_draft_edit_reference_does_not_propose_fresh_report_tool() -> None:
    router = RouterService(ToolRegistry())
    context = ConversationContextService().build(
        turn_text="Keep that same report draft, but make the title shorter and clearer before we save it.",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="assistant",
                content="I prepared a message draft for approval.",
                approval=ApprovalState(
                    id="approval_1",
                    conversation_id="conv_test",
                    turn_id="turn_1",
                    tool_name="create_message_draft",
                    reason="save locally",
                    status="pending",
                    payload={
                        "title": "Supervisor summary",
                        "content": "Short summary for the supervisor.",
                    },
                ),
            ),
        ],
        attached_assets=[],
    )
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Keep that same report draft, but make the title shorter and clearer before we save it.",
    )

    route = router.decide(
        request,
        history=[ConversationMessage(role="assistant", content="I prepared a message draft for approval.")],
        conversation_context=context,
    )

    assert route.proposed_tool is None
    assert route.interaction_kind == "draft_follow_up"


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


def test_attached_document_summary_stays_document_grounded_not_workspace_agent() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text=(
            "Now switch to the attached document. Summarize it conservatively and tell me "
            "what kind of file understanding you can do locally."
        ),
        asset_ids=["asset_doc"],
    )

    route = router.decide(
        request,
        assets=[
            AssetSummary(
                id="asset_doc",
                display_name="report.pdf",
                source_path="report.pdf",
                kind=AssetKind.DOCUMENT,
                care_context=AssetCareContext.GENERAL,
            )
        ],
    )

    assert route.agent_run is False
    assert route.specialist_model == "document"
    assert route.source_domain == SourceDomain.DOCUMENT


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


def test_conversational_preface_does_not_clear_explicit_video_reference() -> None:
    router = RouterService(ToolRegistry())
    video_asset = AssetSummary(
        id="asset_video",
        display_name="clip.mov",
        source_path="clip.mov",
        kind=AssetKind.VIDEO,
    )
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Talk normally with me for a second: after both videos, what are you still most uncertain about?",
    )

    route = router.decide(
        request,
        history=[
            ConversationMessage(
                role="assistant",
                content="I reviewed both videos conservatively from sampled frames.",
            )
        ],
        contextual_assets=[video_asset],
    )

    assert route.specialist_model == "sam3"
    assert route.source_domain == SourceDomain.VIDEO
    assert route.is_follow_up is True


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


def test_teaching_request_does_not_get_stuck_on_recent_image_context() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text="Teach me how to explain oral rehydration solution to a new volunteer.",
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
            ConversationMessage(role="assistant", content="From the image, the clearest visible items are lantern batteries and ORS packets.")
        ],
    )

    assert route.interaction_kind == "teaching"
    assert route.specialist_model is None
    assert route.needs_retrieval is True


def test_source_seeking_request_does_not_reuse_recent_video_context() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text="Search local guidance on oral rehydration and dehydration risk.",
        enabled_knowledge_pack_ids=["local-pack"],
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
            ConversationMessage(role="assistant", content="Reviewed the attached mining clip conservatively.")
        ],
    )

    assert route.specialist_model is None
    assert route.needs_retrieval is True


def test_media_follow_up_without_explicit_image_word_can_reuse_recent_image_context() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Which two shortages matter most before departure?",
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
            ConversationMessage(role="assistant", content="From the image, the clearest visible items are lantern batteries low and translator phone credits low.")
        ],
    )

    assert route.interaction_kind == "vision"
    assert route.specialist_model == "paligemma"


def test_generic_follow_up_question_after_image_does_not_force_media_reuse() -> None:
    router = RouterService(ToolRegistry())
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="What do you mean by that?",
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
            ConversationMessage(role="assistant", content="From the image, the clearest visible items are lantern batteries low and translator phone credits low.")
        ],
    )

    assert route.specialist_model is None
    assert route.interaction_kind == "conversation"


def test_earlier_image_reference_can_override_newer_video_context() -> None:
    router = RouterService(ToolRegistry())
    context_service = ConversationContextService()
    image_asset = AssetSummary(
        id="asset_image",
        display_name="board.png",
        source_path="board.png",
        kind=AssetKind.IMAGE,
        care_context=AssetCareContext.GENERAL,
    )
    video_asset = AssetSummary(
        id="asset_video",
        display_name="mine.mov",
        source_path="mine.mov",
        kind=AssetKind.VIDEO,
        care_context=AssetCareContext.GENERAL,
    )
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="Go back to the earlier image for a second. Which shortage mattered most?",
    )
    context = context_service.build(
        turn_text=request.text,
        transcript=[
            TranscriptMessage(id="m1", role="user", content="What do you notice in this image?"),
            TranscriptMessage(
                id="m2",
                role="assistant",
                content="From the image, lantern batteries look low.",
                assets=[image_asset],
            ),
            TranscriptMessage(id="m3", role="user", content="Now review this mining video."),
            TranscriptMessage(
                id="m4",
                role="assistant",
                content="From the video, heavy vehicle movement stands out.",
                assets=[video_asset],
            ),
        ],
        attached_assets=[],
    )

    route = router.decide(
        request,
        contextual_assets=context.selected_context_assets,
        conversation_context=context,
    )

    assert route.specialist_model == "paligemma"
    assert route.interaction_kind == "vision"


def test_clarification_turn_can_use_structured_context_without_full_history() -> None:
    router = RouterService(ToolRegistry())
    context_service = ConversationContextService()
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.GENERAL,
        text="What did you mean by that?",
    )
    context = context_service.build(
        turn_text=request.text,
        transcript=[
            TranscriptMessage(
                id="m1",
                role="user",
                content="Teach me how to explain oral rehydration solution to a new volunteer.",
            ),
            TranscriptMessage(
                id="m2",
                role="assistant",
                content="Start with the goal, then demonstrate the first step plainly.",
            ),
        ],
        attached_assets=[],
    )

    route = router.decide(request, conversation_context=context)

    assert route.is_follow_up is True
    assert route.interaction_kind == "conversation"


def test_pending_draft_reference_overrides_recent_video_context() -> None:
    router = RouterService(ToolRegistry())
    context_service = ConversationContextService()
    approval = ApprovalState(
        id="approval_1",
        conversation_id="conv_test",
        turn_id="turn_1",
        tool_name="create_note",
        reason="save locally",
        status="pending",
        payload={"title": "Architecture brief"},
    )
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text="What title are you using for that draft?",
    )
    context = context_service.build(
        turn_text=request.text,
        transcript=[
            TranscriptMessage(
                id="m1",
                role="assistant",
                content="Reviewed the attached mining clip conservatively.",
                assets=[
                    AssetSummary(
                        id="asset_video",
                        display_name="mine.mov",
                        source_path="mine.mov",
                        kind=AssetKind.VIDEO,
                        care_context=AssetCareContext.GENERAL,
                    )
                ],
            ),
            TranscriptMessage(
                id="m2",
                role="assistant",
                content="I prepared a note draft for approval.",
                approval=approval,
            ),
        ],
        attached_assets=[],
    )

    route = router.decide(
        request,
        contextual_assets=context.selected_context_assets,
        conversation_context=context,
    )

    assert route.specialist_model is None
    assert route.interaction_kind == "draft_follow_up"
    assert route.is_follow_up is True


def test_work_product_follow_up_does_not_reopen_retrieval() -> None:
    router = RouterService(ToolRegistry())
    context_service = ConversationContextService()
    approval = ApprovalState(
        id="approval_1",
        conversation_id="conv_test",
        turn_id="turn_1",
        tool_name="create_checklist",
        reason="save locally",
        status="pending",
        payload={"title": "Departure checklist", "content": "- Pack batteries"},
    )
    request = ConversationTurnRequest(
        conversation_id="conv_test",
        mode=AssistantMode.RESEARCH,
        text="What was in that checklist again?",
    )
    context = context_service.build(
        turn_text=request.text,
        transcript=[
            TranscriptMessage(
                id="m1",
                role="assistant",
                content="I prepared a checklist draft for approval.",
                approval=approval,
            )
        ],
        attached_assets=[],
    )

    route = router.decide(
        request,
        contextual_assets=context.selected_context_assets,
        conversation_context=context,
    )

    assert route.interaction_kind == "draft_follow_up"
    assert route.needs_retrieval is False
