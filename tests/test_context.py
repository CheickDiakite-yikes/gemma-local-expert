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
