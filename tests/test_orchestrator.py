import asyncio
from pathlib import Path

from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import (
    AssetCareContext,
    AssetKind,
    AssistantMode,
    AssetIngestRequest,
    ConversationCreateRequest,
    ConversationTurnRequest,
    StreamEventType,
)
from engine.models.video import VideoAnalysisResult, VideoArtifact
from engine.models.vision import VisionAnalysisResult


def test_orchestrator_generates_completed_message_with_mock_runtime(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator.db"))
    container = build_container(settings)
    conversation = container.store.create_conversation(
        ConversationCreateRequest(title="Research", mode=AssistantMode.RESEARCH)
    )
    request = ConversationTurnRequest(
        conversation_id=conversation.id,
        mode=AssistantMode.RESEARCH,
        text="Summarize the ORS guidance and cite the best local source.",
    )

    events = asyncio.run(_collect_events(container, request))
    container.store.close()

    completed = [event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED]
    assert completed
    assert "ORS Guidance" in completed[0].payload["text"]
    assert completed[0].payload["models"]["assistant_backend"] == "mock"


async def _collect_events(container, request):
    return [event async for event in container.orchestrator.stream_turn(request)]


def test_orchestrator_uses_specialist_visual_analysis_in_mock_response(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-vision.db"))
    container = build_container(settings)
    try:
        class FakeVisionRuntime:
            backend_name = "fake"

            def analyze(self, request):
                return VisionAnalysisResult(
                    text="Visible interface text: Ask ChatGPT. Dark screen with bottom composer.",
                    backend="fake",
                    model_name=request.specialist_model_name,
                    model_source="/tmp/fake-paligemma",
                    available=True,
                )

        container.orchestrator.vision_runtime = FakeVisionRuntime()
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Visual", mode=AssistantMode.GENERAL)
        )
        image_path = tmp_path / "screen.png"
        image_path.write_bytes(_tiny_png_bytes())
        ingest_result = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(image_path)])
        )

        request = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Describe the attached screenshot conservatively.",
            asset_ids=ingest_result.asset_ids,
        )

        events = asyncio.run(_collect_events(container, request))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        assert "ask chatgpt" in completed[0].payload["text"].lower()
        assert "available specialist analysis" not in completed[0].payload["text"].lower()
        assert completed[0].payload["models"]["specialist_backend"] == "fake"
    finally:
        container.store.close()


def test_orchestrator_reuses_recent_image_context_for_follow_up(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-follow-up.db"))
    container = build_container(settings)
    try:
        class FakeVisionRuntime:
            backend_name = "fake"

            def analyze(self, request):
                return VisionAnalysisResult(
                    text=(
                        "The board shows oral rehydration salts and water purification tablets "
                        "marked low before departure."
                    ),
                    backend="fake",
                    model_name=request.specialist_model_name,
                    model_source="/tmp/fake-paligemma",
                    available=True,
                )

        container.orchestrator.vision_runtime = FakeVisionRuntime()
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Follow-up", mode=AssistantMode.GENERAL)
        )
        image_path = tmp_path / "board.png"
        image_path.write_bytes(_tiny_png_bytes())
        ingest_result = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(image_path)])
        )

        first_request = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Summarize the visible supply situation and note what looks low or urgent.",
            asset_ids=ingest_result.asset_ids,
        )
        follow_up_request = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Which two items should we prioritize before departure, and why?",
            asset_ids=[],
        )

        asyncio.run(_collect_events(container, first_request))
        follow_up_events = asyncio.run(_collect_events(container, follow_up_request))
        completed = [
            event
            for event in follow_up_events
            if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        assert "oral rehydration salts" in completed[0].payload["text"]
        assert "available specialist analysis" not in completed[0].payload["text"].lower()
        assert completed[0].payload["models"]["specialist_backend"] == "fake"
    finally:
        container.store.close()


def test_orchestrator_can_return_to_earlier_image_after_video_turn(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-earlier-image.db"))
    container = build_container(settings)
    try:
        class FakeVisionRuntime:
            backend_name = "fake-vision"

            def analyze(self, request):
                asset_name = request.assets[0].display_name.lower()
                if "board" in asset_name:
                    text = (
                        "The board shows lantern batteries and translator phone credits marked low "
                        "before departure."
                    )
                else:
                    text = "The image shows generic field notes."
                return VisionAnalysisResult(
                    text=text,
                    backend="fake-vision",
                    model_name=request.specialist_model_name,
                    model_source="/tmp/fake-paligemma",
                    available=True,
                )

        class FakeVideoRuntime:
            backend_name = "fake-video"

            def analyze(self, request):
                return VideoAnalysisResult(
                    text="The video shows heavy vehicle movement near the pit edge.",
                    backend="fake-video",
                    model_name=request.tracking_model_name,
                    model_source="/tmp/fake-sam",
                    available=True,
                )

        container.orchestrator.vision_runtime = FakeVisionRuntime()
        container.orchestrator.video_runtime = FakeVideoRuntime()
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Mixed media", mode=AssistantMode.GENERAL)
        )

        image_path = tmp_path / "board.png"
        image_path.write_bytes(_tiny_png_bytes())
        image_asset_id = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(image_path)])
        ).asset_ids[0]

        video_path = tmp_path / "mine.mp4"
        video_path.write_bytes(b"fake-video-bytes")
        video_asset_id = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(video_path)])
        ).asset_ids[0]

        asyncio.run(
            _collect_events(
                container,
                ConversationTurnRequest(
                    conversation_id=conversation.id,
                    mode=AssistantMode.GENERAL,
                    text="What stands out in this image?",
                    asset_ids=[image_asset_id],
                ),
            )
        )
        asyncio.run(
            _collect_events(
                container,
                ConversationTurnRequest(
                    conversation_id=conversation.id,
                    mode=AssistantMode.GENERAL,
                    text="Now review this mining video conservatively.",
                    asset_ids=[video_asset_id],
                ),
            )
        )

        follow_up_events = asyncio.run(
            _collect_events(
                container,
                ConversationTurnRequest(
                    conversation_id=conversation.id,
                    mode=AssistantMode.GENERAL,
                    text="Go back to the earlier image for a second. Which shortage mattered most?",
                ),
            )
        )
        completed = [
            event
            for event in follow_up_events
            if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"].lower()
        assert "lantern batteries" in text
        assert "pit edge" not in text
        assert completed[0].payload["models"]["specialist_backend"] == "fake-vision"
    finally:
        container.store.close()


def test_orchestrator_supports_normal_conversation_without_retrieval_warning(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-general.db"))
    container = build_container(settings)
    try:
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="General", mode=AssistantMode.GENERAL)
        )
        request = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Hey, can we just talk normally for a minute?",
        )

        events = asyncio.run(_collect_events(container, request))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"]
        assert "talk normally" in text.lower()
        assert "retrieved local sources" not in text.lower()
    finally:
        container.store.close()


def test_orchestrator_follow_up_turn_keeps_conversation_continuity_with_mock_runtime(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-follow-up-general.db"))
    container = build_container(settings)
    try:
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="General Follow-up", mode=AssistantMode.GENERAL)
        )
        first_turn = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Can we just talk normally here too?",
        )
        second_turn = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="What do you mean by that?",
        )

        asyncio.run(_collect_events(container, first_turn))
        events = asyncio.run(_collect_events(container, second_turn))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        assert "keep the conversation natural" in completed[0].payload["text"].lower()
    finally:
        container.store.close()


def test_orchestrator_supportive_turn_stays_warm_without_local_retrieval(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-supportive.db"))
    container = build_container(settings)
    try:
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Support", mode=AssistantMode.FIELD)
        )
        request = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.FIELD,
            text=(
                "Honestly I'm a little anxious about tomorrow. "
                "No checklist right now, just help me calm down for a second."
            ),
            enabled_knowledge_pack_ids=["local-pack"],
        )

        events = asyncio.run(_collect_events(container, request))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"].lower()
        assert "take a breath" in text
        assert "checklist" not in text
        assert not any(event.type == StreamEventType.CITATION_ADDED for event in events)
    finally:
        container.store.close()


def test_orchestrator_workspace_summary_reads_like_assistant_synthesis(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-prep.md").write_text(
        "Field prep checklist\nPack oral rehydration salts\nPack backup batteries\n",
        encoding="utf-8",
    )
    (workspace_root / "route-notes.md").write_text(
        "Village route briefing\nConfirm translator contact sheet before departure.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "orchestrator-workspace.db"),
        workspace_root=str(workspace_root),
    )
    container = build_container(settings)
    try:
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Workspace", mode=AssistantMode.RESEARCH)
        )
        request = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.RESEARCH,
            text="Search this workspace and summarize the field prep docs.",
        )

        events = asyncio.run(_collect_events(container, request))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"]
        assert "Here is a concise briefing:" in text
        assert "Key points:" in text
        assert "Files reviewed:" in text
        assert "I reviewed" not in text
        assert "Goal:" not in text
        assert "Workspace scope:" not in text
    finally:
        container.store.close()


def test_orchestrator_can_answer_follow_up_about_pending_export_title(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-assistant-architecture.md").write_text(
        "Field Assistant architecture overview\n"
        "Local-first assistant built on Gemma.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "orchestrator-export-follow-up.db"),
        workspace_root=str(workspace_root),
    )
    container = build_container(settings)
    try:
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Export Follow-up", mode=AssistantMode.RESEARCH)
        )
        first_turn = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.RESEARCH,
            text="Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.",
        )
        follow_up = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.RESEARCH,
            text="What title are you using for that draft?",
        )
        summary_follow_up = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.RESEARCH,
            text="What's in that draft again?",
        )
        tighten_follow_up = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.RESEARCH,
            text="Keep the same draft, but make that shorter before I save it.",
        )

        asyncio.run(_collect_events(container, first_turn))
        events = asyncio.run(_collect_events(container, follow_up))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"]
        assert 'Field Assistant Architecture Briefing' in text
        assert "pit edge" not in text.lower()

        summary_events = asyncio.run(_collect_events(container, summary_follow_up))
        summary_completed = [
            event
            for event in summary_events
            if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert summary_completed
        summary_text = summary_completed[0].payload["text"]
        assert "currently centers on" in summary_text.lower()
        assert "local-first assistant built on gemma" in summary_text.lower()

        tighten_events = asyncio.run(_collect_events(container, tighten_follow_up))
        tighten_completed = [
            event
            for event in tighten_events
            if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        tighten_approval_events = [
            event for event in tighten_events if event.type == StreamEventType.APPROVAL_REQUIRED
        ]
        assert tighten_completed
        assert tighten_approval_events
        tighten_text = tighten_completed[0].payload["text"]
        assert "i tightened the current markdown export draft" in tighten_text.lower()
        assert 'field assistant architecture brief' in tighten_text.lower()
        approval_payload = tighten_approval_events[0].payload
        assert approval_payload["id"].startswith("approval_")
        assert approval_payload["payload"]["title"] == "Field Assistant Architecture Brief"
        assert "Files reviewed:" not in approval_payload["payload"]["content"]
    finally:
        container.store.close()


def test_orchestrator_persists_video_specialist_artifacts_and_streams_them(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=str(tmp_path / "orchestrator-video.db"),
        tracking_backend="mock",
    )
    container = build_container(settings)
    try:
        class FakeVideoRuntime:
            backend_name = "fake-video"

            def analyze(self, request):
                contact_sheet_path = tmp_path / "site-contact-sheet.png"
                contact_sheet_path.write_bytes(_tiny_png_bytes())
                return VideoAnalysisResult(
                    text="Sampled the uploaded mining clip and prepared a local contact sheet for review.",
                    backend="fake-video",
                    model_name=request.tracking_model_name,
                    model_source="/tmp/fake-sam",
                    available=True,
                    artifacts=[
                        VideoArtifact(
                            display_name="site-contact-sheet.png",
                            local_path=str(contact_sheet_path),
                            media_type="image/png",
                            kind=AssetKind.IMAGE,
                            care_context=AssetCareContext.GENERAL,
                            analysis_summary="Local contact sheet sampled from the uploaded video.",
                        )
                    ],
                )

        container.orchestrator.video_runtime = FakeVideoRuntime()
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Video", mode=AssistantMode.GENERAL)
        )
        video_path = tmp_path / "mine-site.mp4"
        video_path.write_bytes(b"not-a-real-video-but-good-enough-for-fake-runtime")
        ingest_result = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(video_path)])
        )

        request = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Review the attached mining video conservatively.",
            asset_ids=ingest_result.asset_ids,
        )

        events = asyncio.run(_collect_events(container, request))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        assert completed[0].payload["assets"]
        assert completed[0].payload["assets"][0]["display_name"] == "site-contact-sheet.png"
        assert completed[0].payload["models"]["specialist_backend"] == "fake-video"

        transcript = container.store.list_transcript(conversation.id)
        assistant_message = transcript[-1]
        assert assistant_message.assets
        assert assistant_message.assets[0].display_name == "site-contact-sheet.png"
    finally:
        container.store.close()


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc``\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\x18"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
