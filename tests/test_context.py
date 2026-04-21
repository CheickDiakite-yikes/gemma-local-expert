from engine.context.service import ConversationContextService
from engine.contracts.api import (
    ApprovalState,
    AssetKind,
    AssetSummary,
    TranscriptMessage,
)


def test_context_service_can_reselect_earlier_image_after_newer_video() -> None:
    service = ConversationContextService()
    image_asset = AssetSummary(
        id="asset_image",
        display_name="board.png",
        source_path="board.png",
        kind=AssetKind.IMAGE,
    )
    video_asset = AssetSummary(
        id="asset_video",
        display_name="mine.mov",
        source_path="mine.mov",
        kind=AssetKind.VIDEO,
    )

    snapshot = service.build(
        turn_text="Go back to the earlier image for a second. What stood out first?",
        transcript=[
            TranscriptMessage(id="msg1", role="user", content="What do you notice in this image?"),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="From the image, lantern batteries look low.",
                assets=[image_asset],
            ),
            TranscriptMessage(id="msg3", role="user", content="Now review this mining video."),
            TranscriptMessage(
                id="msg4",
                role="assistant",
                content="From the video, I noticed heavy vehicle movement near the pit edge.",
                assets=[video_asset],
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.selected_context_kind == "image"
    assert snapshot.selected_context_assets
    assert snapshot.selected_context_assets[0].id == "asset_image"


def test_context_service_ignores_video_contact_sheet_when_user_refers_to_earlier_image() -> None:
    service = ConversationContextService()
    image_asset = AssetSummary(
        id="asset_image",
        display_name="board.png",
        source_path="board.png",
        kind=AssetKind.IMAGE,
    )
    video_asset = AssetSummary(
        id="asset_video",
        display_name="mine.mov",
        source_path="mine.mov",
        kind=AssetKind.VIDEO,
    )
    contact_sheet = AssetSummary(
        id="asset_contact_sheet",
        display_name="mine-contact-sheet.png",
        source_path="derived/mine-contact-sheet.png",
        kind=AssetKind.IMAGE,
        analysis_summary="Sampled contact sheet from the uploaded video for local review.",
    )

    snapshot = service.build(
        turn_text="Go back to the earlier image for a second. Which shortage mattered most?",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="user",
                content="Describe the attached supply image conservatively.",
                assets=[image_asset],
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="From the image, lantern batteries look low.",
            ),
            TranscriptMessage(
                id="msg3",
                role="user",
                content="Review the attached mining video conservatively.",
                assets=[video_asset],
            ),
            TranscriptMessage(
                id="msg4",
                role="assistant",
                content="I sampled frames into a contact sheet for review.",
                assets=[contact_sheet],
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.selected_context_kind == "image"
    assert snapshot.selected_context_assets
    assert snapshot.selected_context_assets[0].id == "asset_image"
    assert snapshot.selected_context_summary is not None
    assert "lantern batteries" in snapshot.selected_context_summary.lower()


def test_context_service_tracks_pending_approval_and_recent_topic() -> None:
    service = ConversationContextService()
    approval = ApprovalState(
        id="approval_1",
        conversation_id="conv_1",
        turn_id="turn_1",
        tool_name="create_note",
        reason="save locally",
        status="pending",
        payload={
            "title": "Architecture brief",
            "content": "Field Assistant architecture overview\nUses bounded routing and explicit approvals.\n",
        },
    )

    snapshot = service.build(
        turn_text="Can you tighten that draft?",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="user",
                content="Prepare a short workspace briefing about the current field assistant architecture.",
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="I reviewed the local architecture docs and prepared a note draft.",
                approval=approval,
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.active_topic == (
        "Prepare a short workspace briefing about the current field assistant architecture."
    )
    assert snapshot.pending_approval_tool == "create_note"
    assert snapshot.pending_approval_summary == "Architecture brief"
    assert snapshot.pending_approval_excerpt is not None
    assert "field assistant architecture overview" in snapshot.pending_approval_excerpt.lower()


def test_context_service_selects_pending_draft_referent() -> None:
    service = ConversationContextService()
    approval = ApprovalState(
        id="approval_1",
        conversation_id="conv_1",
        turn_id="turn_1",
        tool_name="create_note",
        reason="save locally",
        status="pending",
        payload={
            "title": "Architecture brief",
            "content": "Field Assistant architecture overview\nUses bounded routing and explicit approvals.\n",
        },
    )

    snapshot = service.build(
        turn_text="What title are you using for that draft?",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="user",
                content="Prepare a short workspace briefing about the current field assistant architecture.",
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="I prepared a note draft for approval.",
                approval=approval,
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.selected_referent_kind == "pending_output"
    assert snapshot.selected_referent_tool == "create_note"
    assert snapshot.selected_referent_title == "Architecture brief"
    assert snapshot.selected_referent_excerpt is not None
    assert "bounded routing" in snapshot.selected_referent_excerpt.lower()


def test_context_service_selects_last_saved_output_referent() -> None:
    service = ConversationContextService()
    approval = ApprovalState(
        id="approval_1",
        conversation_id="conv_1",
        turn_id="turn_1",
        tool_name="export_brief",
        reason="save locally",
        status="executed",
        payload={
            "title": "Workspace Briefing",
            "content": "Field Assistant architecture overview\nUses bounded routing and explicit approvals.\n",
        },
        result={"title": "Field Assistant Architecture Briefing"},
    )

    snapshot = service.build(
        turn_text="What did you call that export again?",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="assistant",
                content="I exported the markdown briefing locally.",
                approval=approval,
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.selected_referent_kind == "saved_output"
    assert snapshot.selected_referent_tool == "export_brief"
    assert snapshot.selected_referent_title == "Field Assistant Architecture Briefing"
    assert snapshot.selected_referent_excerpt is not None
    assert "field assistant architecture overview" in snapshot.selected_referent_excerpt.lower()


def test_context_service_prefers_matching_output_kind_over_newer_pending_draft() -> None:
    service = ConversationContextService()
    checklist_approval = ApprovalState(
        id="approval_checklist",
        conversation_id="conv_1",
        turn_id="turn_checklist",
        tool_name="create_checklist",
        reason="save locally",
        status="executed",
        payload={
            "title": "Departure checklist",
            "content": "- Pack lantern batteries\n- Bring consent forms\n",
        },
        result={"title": "Departure checklist"},
    )
    export_approval = ApprovalState(
        id="approval_export",
        conversation_id="conv_1",
        turn_id="turn_export",
        tool_name="export_brief",
        reason="save locally",
        status="pending",
        payload={
            "title": "Field Assistant Architecture Briefing",
            "content": "Field Assistant architecture overview\nUses bounded routing and approvals.\n",
        },
    )

    snapshot = service.build(
        turn_text="What was in that checklist again?",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="assistant",
                content="I created the checklist locally.",
                approval=checklist_approval,
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="I prepared a markdown export for approval.",
                approval=export_approval,
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.pending_approval_tool == "export_brief"
    assert snapshot.selected_referent_kind == "saved_output"
    assert snapshot.selected_referent_tool == "create_checklist"
    assert snapshot.selected_referent_title == "Departure checklist"
    assert snapshot.selected_referent_excerpt is not None
    assert "lantern batteries" in snapshot.selected_referent_excerpt.lower()


def test_context_service_keeps_matching_pending_output_preview_when_newer_pending_exists() -> None:
    service = ConversationContextService()
    checklist_approval = ApprovalState(
        id="approval_checklist_pending",
        conversation_id="conv_1",
        turn_id="turn_checklist_pending",
        tool_name="create_checklist",
        reason="save locally",
        status="pending",
        payload={
            "title": "Checklist for tomorrow's village visits",
            "content": "- Pack oral rehydration salts\n- Confirm translator contact sheet before departure\n",
        },
    )
    export_approval = ApprovalState(
        id="approval_export_pending",
        conversation_id="conv_1",
        turn_id="turn_export_pending",
        tool_name="export_brief",
        reason="save locally",
        status="pending",
        payload={
            "title": "Field Assistant Architecture Briefing",
            "content": "This document converts the v1 product spec into an implementation architecture.\n",
        },
    )

    snapshot = service.build(
        turn_text="What was in that checklist again?",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="assistant",
                content="I prepared a checklist draft for approval.",
                approval=checklist_approval,
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="I prepared a markdown export for approval.",
                approval=export_approval,
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.pending_approval_tool == "export_brief"
    assert snapshot.selected_referent_kind == "pending_output"
    assert snapshot.selected_referent_tool == "create_checklist"
    assert snapshot.selected_referent_title == "Checklist for tomorrow's village visits"
    assert snapshot.selected_referent_summary == "Checklist for tomorrow's village visits"
    assert snapshot.selected_referent_excerpt is not None
    assert "translator contact sheet" in snapshot.selected_referent_excerpt.lower()
    assert "implementation architecture" not in snapshot.selected_referent_excerpt.lower()


def test_context_service_can_refer_back_to_first_image_when_two_images_exist() -> None:
    service = ConversationContextService()
    first_image = AssetSummary(
        id="asset_image_first",
        display_name="board-one.png",
        source_path="board-one.png",
        kind=AssetKind.IMAGE,
    )
    second_image = AssetSummary(
        id="asset_image_second",
        display_name="board-two.png",
        source_path="board-two.png",
        kind=AssetKind.IMAGE,
    )

    snapshot = service.build(
        turn_text="Go back to the first image. What stood out there?",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="user",
                content="Describe the first attached supply image.",
                assets=[first_image],
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="From the image, lantern batteries look low.",
            ),
            TranscriptMessage(
                id="msg3",
                role="user",
                content="Now describe this second attached supply image.",
                assets=[second_image],
            ),
            TranscriptMessage(
                id="msg4",
                role="assistant",
                content="From the image, consent forms look fully stocked.",
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.selected_context_kind == "image"
    assert snapshot.selected_context_assets
    assert snapshot.selected_context_assets[0].id == "asset_image_first"
    assert snapshot.selected_context_summary is not None
    assert "lantern batteries" in snapshot.selected_context_summary.lower()


def test_context_service_preserves_earlier_image_across_longer_transcript_with_casual_pivot() -> None:
    service = ConversationContextService()
    image_asset = AssetSummary(
        id="asset_image",
        display_name="board.png",
        source_path="board.png",
        kind=AssetKind.IMAGE,
    )
    video_asset = AssetSummary(
        id="asset_video",
        display_name="mine.mov",
        source_path="mine.mov",
        kind=AssetKind.VIDEO,
    )
    transcript = [
        TranscriptMessage(
            id="msg1",
            role="user",
            content="Describe the attached supply image conservatively.",
            assets=[image_asset],
        ),
        TranscriptMessage(
            id="msg2",
            role="assistant",
            content="From the image, lantern batteries look low.",
        ),
        TranscriptMessage(
            id="msg3",
            role="user",
            content="Which two shortages matter most before departure?",
        ),
        TranscriptMessage(
            id="msg4",
            role="assistant",
            content="The two clearest shortages are lantern batteries and translator phone credits.",
        ),
        TranscriptMessage(
            id="msg5",
            role="user",
            content="Review the attached mining video conservatively.",
            assets=[video_asset],
        ),
        TranscriptMessage(
            id="msg6",
            role="assistant",
            content="From the video, I noticed workers near excavation equipment.",
        ),
        TranscriptMessage(
            id="msg7",
            role="user",
            content="Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.",
        ),
        TranscriptMessage(
            id="msg8",
            role="assistant",
            content="Here is a concise briefing with key points and files reviewed.",
        ),
        TranscriptMessage(
            id="msg9",
            role="user",
            content="Keep the same draft, but make that shorter before I save it.",
        ),
        TranscriptMessage(
            id="msg10",
            role="assistant",
            content="I tightened the current markdown export draft.",
        ),
        TranscriptMessage(
            id="msg11",
            role="user",
            content="Actually, just talk normally with me for a second.",
        ),
        TranscriptMessage(
            id="msg12",
            role="assistant",
            content="Yes. We can have a normal conversation here.",
        ),
    ]

    snapshot = service.build(
        turn_text="Go back to the earlier image for a second. Which shortage mattered most?",
        transcript=transcript,
        attached_assets=[],
    )

    assert snapshot.selected_context_kind == "image"
    assert snapshot.selected_context_assets
    assert snapshot.selected_context_assets[0].id == "asset_image"
    assert snapshot.selected_context_summary is not None
    assert "lantern batteries" in snapshot.selected_context_summary.lower()


def test_context_service_combines_both_video_summaries_for_comparison_follow_up() -> None:
    service = ConversationContextService()
    first_video = AssetSummary(
        id="asset_video_first",
        display_name="north-gate.mov",
        source_path="north-gate.mov",
        kind=AssetKind.VIDEO,
    )
    second_video = AssetSummary(
        id="asset_video_second",
        display_name="south-gate.mov",
        source_path="south-gate.mov",
        kind=AssetKind.VIDEO,
    )

    snapshot = service.build(
        turn_text="Compare both videos conservatively. What is most different?",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="user",
                content="Review the first attached gate video conservatively.",
                assets=[first_video],
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="From the video, the north gate clip shows workers moving around a staging table.",
            ),
            TranscriptMessage(
                id="msg3",
                role="user",
                content="Now review this second gate video conservatively.",
                assets=[second_video],
            ),
            TranscriptMessage(
                id="msg4",
                role="assistant",
                content="From the video, the south gate clip shows a quieter checkpoint with less visible movement.",
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.selected_context_kind == "video"
    assert len(snapshot.selected_context_assets) == 2
    assert snapshot.selected_context_summary is not None
    assert "north-gate.mov" in snapshot.selected_context_summary
    assert "south-gate.mov" in snapshot.selected_context_summary


def test_context_service_keeps_earlier_video_when_new_video_is_attached_for_comparison() -> None:
    service = ConversationContextService()
    first_video = AssetSummary(
        id="asset_video_first",
        display_name="first.mov",
        source_path="first.mov",
        kind=AssetKind.VIDEO,
    )
    second_video = AssetSummary(
        id="asset_video_second",
        display_name="second.mov",
        source_path="second.mov",
        kind=AssetKind.VIDEO,
    )

    snapshot = service.build(
        turn_text="Now review this second attached video conservatively and tell me what looks meaningfully different from the first one.",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="user",
                content="Review the first attached video conservatively.",
                assets=[first_video],
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="From the video, the first clip shows workers moving around a staging table.",
            ),
        ],
        attached_assets=[second_video],
    )

    assert snapshot.selected_context_kind == "video"
    assert snapshot.selected_context_assets
    assert snapshot.selected_context_assets[0].id == "asset_video_first"


def test_context_service_prefers_later_image_follow_up_when_it_matches_current_need() -> None:
    service = ConversationContextService()
    image_asset = AssetSummary(
        id="asset_image",
        display_name="field_supply_board.png",
        source_path="field_supply_board.png",
        kind=AssetKind.IMAGE,
    )

    snapshot = service.build(
        turn_text="Create a checklist for tomorrow's departure based on the supply board shortages.",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="user",
                content="Describe the attached supply image conservatively.",
                assets=[image_asset],
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content=(
                    "Here is a conservative description of the supply board:\n"
                    "Village Visit Supply Board\n\n"
                    "This board lists supplies needed before a 7:30 PM departure.\n\n"
                    "Supplies:\n"
                    "- ORS packets: 18\n"
                    "- Lantern batteries: LOW\n"
                    "- Consent forms: 42\n\n"
                    "Action Note:\n"
                    "- Buy batteries and top up translator credit before leaving base.\n"
                ),
            ),
            TranscriptMessage(
                id="msg3",
                role="user",
                content="Which two shortages matter most before departure?",
            ),
            TranscriptMessage(
                id="msg4",
                role="assistant",
                content=(
                    "The two shortages that matter most before departure are:\n"
                    "- Lantern batteries: Marked as LOW.\n"
                    "- Translator phone credits: Explicitly noted as needing to be topped up.\n"
                ),
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.selected_context_kind == "image"
    assert snapshot.selected_context_summary is not None
    assert "translator phone credits" in snapshot.selected_context_summary.lower()
    assert "shortages that matter most" in snapshot.selected_context_summary.lower()


def test_context_service_can_select_earlier_report_among_multiple_reports() -> None:
    service = ConversationContextService()
    earlier_report = ApprovalState(
        id="approval_report_1",
        conversation_id="conv_1",
        turn_id="turn_report_1",
        tool_name="create_report",
        reason="save locally",
        status="executed",
        payload={
            "title": "Architecture status report",
            "content": "# Architecture status report\n\n- Local-first orchestrator.\n",
        },
        result={"title": "Architecture status report"},
    )
    latest_report = ApprovalState(
        id="approval_report_2",
        conversation_id="conv_1",
        turn_id="turn_report_2",
        tool_name="create_report",
        reason="save locally",
        status="executed",
        payload={
            "title": "Mining review report",
            "content": "# Mining review report\n\n- Workers near the pit edge.\n",
        },
        result={"title": "Mining review report"},
    )

    snapshot = service.build(
        turn_text="What was in the earlier architecture report again?",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="assistant",
                content="I saved the architecture report locally.",
                approval=earlier_report,
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="I saved the mining review report locally.",
                approval=latest_report,
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.selected_referent_kind == "saved_output"
    assert snapshot.selected_referent_tool == "create_report"
    assert snapshot.selected_referent_title == "Architecture status report"
    assert snapshot.selected_referent_excerpt is not None
    assert "local-first orchestrator" in snapshot.selected_referent_excerpt.lower()


def test_context_service_does_not_force_single_referent_for_multi_output_recall() -> None:
    service = ConversationContextService()
    report = ApprovalState(
        id="approval_report",
        conversation_id="conv_1",
        turn_id="turn_report",
        tool_name="create_report",
        reason="save locally",
        status="executed",
        payload={
            "title": "Architecture status report",
            "content": "# Architecture status report\n\n- Local-first orchestrator.\n",
        },
        result={"title": "Architecture status report"},
    )
    checklist = ApprovalState(
        id="approval_checklist",
        conversation_id="conv_1",
        turn_id="turn_checklist",
        tool_name="create_checklist",
        reason="save locally",
        status="executed",
        payload={
            "title": "Departure shortage checklist",
            "content": "- [ ] Replace low lantern batteries\n",
        },
        result={"title": "Departure shortage checklist"},
    )
    export = ApprovalState(
        id="approval_export",
        conversation_id="conv_1",
        turn_id="turn_export",
        tool_name="export_brief",
        reason="save locally",
        status="executed",
        payload={
            "title": "Field Assistant Architecture Briefing",
            "content": "# Field Assistant Architecture Briefing\n\nKey points:\n",
        },
        result={"title": "Field Assistant Architecture Briefing"},
    )

    snapshot = service.build(
        turn_text="What was in the earlier report again, what was in the checklist, and what is the newer export called?",
        transcript=[
            TranscriptMessage(
                id="msg1",
                role="assistant",
                content="I saved the architecture report locally.",
                approval=report,
            ),
            TranscriptMessage(
                id="msg2",
                role="assistant",
                content="I saved the checklist locally.",
                approval=checklist,
            ),
            TranscriptMessage(
                id="msg3",
                role="assistant",
                content="I saved the markdown export locally.",
                approval=export,
            ),
        ],
        attached_assets=[],
    )

    assert snapshot.selected_referent_kind is None
    assert snapshot.selected_referent_tool is None
    assert len(snapshot.recent_outputs) == 3
