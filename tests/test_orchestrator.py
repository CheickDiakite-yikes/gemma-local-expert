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
        assert "Visible interface text: Ask ChatGPT" in completed[0].payload["text"]
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
        assert completed[0].payload["models"]["specialist_backend"] == "fake"
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
