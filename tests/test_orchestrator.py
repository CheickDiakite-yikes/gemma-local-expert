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
    EvidenceFact,
    EvidencePacket,
    EvidenceRef,
    ExecutionMode,
    GroundingStatus,
    RuntimeProfile,
    SourceDomain,
    StreamEventType,
)
from engine.models.runtime import AssistantGenerationResult
from engine.models.document import DocumentAnalysisResult
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
        assert "just talk this through" in text.lower()
        assert "retrieved local sources" not in text.lower()
    finally:
        container.store.close()


def test_orchestrator_tracking_request_uses_truthful_unavailable_reply(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-video-guardrail.db"))
    container = build_container(settings)
    try:
        class FakeVideoRuntime:
            backend_name = "fake-video"

            def analyze(self, request):
                return VideoAnalysisResult(
                    text="Fallback video sampling only.",
                    backend="fake-video",
                    model_name=request.tracking_model_name,
                    model_source="/tmp/fake-sam",
                    available=True,
                    evidence_packet=EvidencePacket(
                        source_domain=SourceDomain.VIDEO,
                        asset_ids=[request.assets[0].asset_id],
                        profile=RuntimeProfile.LOW_MEMORY,
                        execution_mode=ExecutionMode.FALLBACK,
                        grounding_status=GroundingStatus.PARTIAL,
                        summary="Sampled fallback video frames only.",
                        facts=[
                            EvidenceFact(
                                summary="Sampled the clip around 00:16 and 00:41.",
                                refs=[EvidenceRef(label="Timestamp", ref="00:16")],
                            )
                        ],
                        uncertainties=[
                            "Full tracking and isolation did not run from the fallback path."
                        ],
                    ),
                )

        container.orchestrator.video_runtime = FakeVideoRuntime()
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Video Guardrail", mode=AssistantMode.GENERAL)
        )
        video_path = tmp_path / "guardrail.mp4"
        video_path.write_bytes(b"fake-video-bytes")
        ingest_result = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(video_path)])
        )

        request = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Use local SAM tracking or local video isolation on this video.",
            asset_ids=ingest_result.asset_ids,
        )

        events = asyncio.run(_collect_events(container, request))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"].lower()
        assert "could not run local sam tracking or video isolation" in text
        assert "executing local sam tracking" not in text
    finally:
        container.store.close()


def test_orchestrator_video_comparison_reply_stays_grounded_to_both_packets(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-video-compare.db"))
    container = build_container(settings)
    try:
        class FakeVideoRuntime:
            backend_name = "fake-video"

            def analyze(self, request):
                return VideoAnalysisResult(
                    text="Fallback video comparison only.",
                    backend="fake-video",
                    model_name=request.tracking_model_name,
                    model_source="/tmp/fake-sam",
                    available=True,
                    evidence_packet=EvidencePacket(
                        source_domain=SourceDomain.VIDEO,
                        asset_ids=[asset.asset_id for asset in request.assets],
                        profile=RuntimeProfile.LOW_MEMORY,
                        execution_mode=ExecutionMode.FALLBACK,
                        grounding_status=GroundingStatus.PARTIAL,
                        summary="Prepared separate local evidence for both videos.",
                        facts=[
                            EvidenceFact(
                                summary=(
                                    "Prepared separate local evidence for first.mov, second.mov so they can be contrasted conservatively without claiming synchronized tracking."
                                ),
                                refs=[
                                    EvidenceRef(label="first.mov", ref="00:16"),
                                    EvidenceRef(label="second.mov", ref="00:11"),
                                ],
                            ),
                            EvidenceFact(
                                summary="first.mov: Visible on-screen text from sampled frames includes \"Vous définissez vous-même\".",
                                refs=[EvidenceRef(label="first.mov sample", ref="01:05")],
                            ),
                            EvidenceFact(
                                summary="second.mov: Visible on-screen text from sampled frames includes \": TIMES ARCHIVES\".",
                                refs=[EvidenceRef(label="second.mov sample", ref="00:44")],
                            ),
                        ],
                        uncertainties=[
                            "Cross-video comparison is limited to per-video sampled evidence and derived artifacts; no synchronized tracking or isolation ran across the pair.",
                            "No local pixel-level object or action recognizer ran on the sampled frames in this profile.",
                        ],
                    ),
                )

        container.orchestrator.video_runtime = FakeVideoRuntime()
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Video Compare", mode=AssistantMode.GENERAL)
        )
        first_video = tmp_path / "first.mov"
        second_video = tmp_path / "second.mov"
        first_video.write_bytes(b"first-video")
        second_video.write_bytes(b"second-video")
        ingest_result = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(first_video), str(second_video)])
        )

        request = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Compare both videos. Are the same tools, processes, or possible weapon-like items present in both?",
            asset_ids=ingest_result.asset_ids,
        )

        events = asyncio.run(_collect_events(container, request))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"].lower()
        assert "compared both videos conservatively" in text
        assert "cannot confirm the same specific tools" in text
        assert "first.mov" in text
        assert "second.mov" in text
        assert "synchronized tracking" in text
    finally:
        container.store.close()


def test_orchestrator_document_turn_stays_grounded_when_extraction_is_partial(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-document-guardrail.db"))
    container = build_container(settings)
    try:
        class FakeDocumentRuntime:
            backend_name = "fake-document"

            def analyze(self, request):
                asset = request.assets[0]
                packet = EvidencePacket(
                    source_domain=SourceDomain.DOCUMENT,
                    asset_ids=[asset.asset_id],
                    profile=RuntimeProfile.LOW_MEMORY,
                    execution_mode=ExecutionMode.FALLBACK,
                    grounding_status=GroundingStatus.PARTIAL,
                    summary="Mali at a Turning Point:",
                    facts=[
                        EvidenceFact(
                            summary="Mali at a Turning Point:",
                            refs=[EvidenceRef(label="Page 1", ref="p1")],
                        ),
                        EvidenceFact(
                            summary="The world is entering a new age of intelligence.",
                            refs=[EvidenceRef(label="Page 2", ref="p2")],
                        ),
                    ],
                    uncertainties=[
                        "The document summary is based on OCR fallback rather than embedded text."
                    ],
                )
                return DocumentAnalysisResult(
                    text="I reviewed the document locally.",
                    backend="fake-document",
                    model_name="ocr-fallback",
                    model_source=None,
                    available=True,
                    evidence_packet=packet,
                    unavailable_reason="Embedded PDF text was unavailable, so OCR fallback was used.",
                )

        container.orchestrator.document_runtime = FakeDocumentRuntime()
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Document Guardrail", mode=AssistantMode.GENERAL)
        )
        pdf_path = tmp_path / "report.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        ingest_result = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(pdf_path)])
        )

        request = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text=(
                "From that same document, extract the main sections, key named entities, "
                "and any clear action items or claims."
            ),
            asset_ids=ingest_result.asset_ids,
        )

        events = asyncio.run(_collect_events(container, request))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"].lower()
        assert "do not have a clean enough document extraction" in text
        assert "main sections" in text
        assert "p1" in text or "p2" in text
    finally:
        container.store.close()


def test_orchestrator_document_follow_up_keeps_document_context(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-document-follow-up.db"))
    container = build_container(settings)
    try:
        class FakeDocumentRuntime:
            backend_name = "fake-document"

            def analyze(self, request):
                asset = request.assets[0]
                packet = EvidencePacket(
                    source_domain=SourceDomain.DOCUMENT,
                    asset_ids=[asset.asset_id],
                    profile=RuntimeProfile.LOW_MEMORY,
                    execution_mode=ExecutionMode.FALLBACK,
                    grounding_status=GroundingStatus.PARTIAL,
                    summary="Mali at a Turning Point:",
                    facts=[
                        EvidenceFact(
                            summary="Mali at a Turning Point:",
                            refs=[EvidenceRef(label="Page 1", ref="p1")],
                        ),
                        EvidenceFact(
                            summary="The world is entering a new age of intelligence.",
                            refs=[EvidenceRef(label="Page 2", ref="p2")],
                        ),
                    ],
                    uncertainties=[
                        "The document summary is based on OCR fallback rather than embedded text."
                    ],
                )
                return DocumentAnalysisResult(
                    text="I reviewed the document locally.",
                    backend="fake-document",
                    model_name="ocr-fallback",
                    model_source=None,
                    available=True,
                    evidence_packet=packet,
                    unavailable_reason="Embedded PDF text was unavailable, so OCR fallback was used.",
                )

        container.orchestrator.document_runtime = FakeDocumentRuntime()
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Document Follow-up", mode=AssistantMode.GENERAL)
        )
        pdf_path = tmp_path / "followup.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        ingest_result = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(pdf_path)])
        )

        asyncio.run(
            _collect_events(
                container,
                ConversationTurnRequest(
                    conversation_id=conversation.id,
                    mode=AssistantMode.GENERAL,
                    text=(
                        "Now switch to the attached document. Summarize it conservatively and tell me "
                        "what kind of file understanding you can do locally."
                    ),
                    asset_ids=ingest_result.asset_ids,
                ),
            )
        )
        events = asyncio.run(
            _collect_events(
                container,
                ConversationTurnRequest(
                    conversation_id=conversation.id,
                    mode=AssistantMode.GENERAL,
                    text=(
                        "From that same document, extract the main sections, key named entities, "
                        "and any clear action items or claims."
                    ),
                ),
            )
        )
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"].lower()
        assert "clean enough document extraction" in text
        assert "mali at a turning point" in text
    finally:
        container.store.close()


def test_orchestrator_blocks_partial_video_report_until_user_overrides(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-video-report.db"))
    container = build_container(settings)
    try:
        class FakeVideoRuntime:
            backend_name = "fake-video"

            def analyze(self, request):
                return VideoAnalysisResult(
                    text="Fallback video sampling only.",
                    backend="fake-video",
                    model_name=request.tracking_model_name,
                    model_source="/tmp/fake-sam",
                    available=True,
                    evidence_packet=EvidencePacket(
                        source_domain=SourceDomain.VIDEO,
                        asset_ids=[request.assets[0].asset_id],
                        profile=RuntimeProfile.LOW_MEMORY,
                        execution_mode=ExecutionMode.FALLBACK,
                        grounding_status=GroundingStatus.PARTIAL,
                        summary="Sampled fallback video frames only.",
                        facts=[
                            EvidenceFact(
                                summary="Sampled the clip around 00:16 and 00:41.",
                                refs=[EvidenceRef(label="Timestamp", ref="00:16")],
                            )
                        ],
                        uncertainties=[
                            "Full tracking and isolation did not run from the fallback path."
                        ],
                    ),
                )

        container.orchestrator.video_runtime = FakeVideoRuntime()
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Video Report Guardrail", mode=AssistantMode.GENERAL)
        )
        video_path = tmp_path / "compare.mp4"
        video_path.write_bytes(b"fake-video-bytes")
        ingest_result = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(video_path)])
        )

        first_turn = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Review this video conservatively first.",
            asset_ids=ingest_result.asset_ids,
        )
        second_turn = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Prepare a report based on that video and save it as a report.",
        )

        asyncio.run(_collect_events(container, first_turn))
        events = asyncio.run(_collect_events(container, second_turn))
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"].lower()
        assert "need stronger grounded evidence" in text
        assert "prepare that durable draft" in text
    finally:
        container.store.close()


def test_orchestrator_does_not_retarget_missing_report_to_message_draft(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-missing-report.db"))
    container = build_container(settings)
    try:
        class FakeVideoRuntime:
            backend_name = "fake-video"

            def analyze(self, request):
                return VideoAnalysisResult(
                    text="Fallback video sampling only.",
                    backend="fake-video",
                    model_name=request.tracking_model_name,
                    model_source="/tmp/fake-sam",
                    available=True,
                    evidence_packet=EvidencePacket(
                        source_domain=SourceDomain.VIDEO,
                        asset_ids=[asset.asset_id for asset in request.assets],
                        profile=RuntimeProfile.LOW_MEMORY,
                        execution_mode=ExecutionMode.FALLBACK,
                        grounding_status=GroundingStatus.PARTIAL,
                        summary="Sampled fallback video frames only.",
                        facts=[
                            EvidenceFact(
                                summary="Sampled the clip around 00:16 and 00:41.",
                                refs=[EvidenceRef(label="Timestamp", ref="00:16")],
                            )
                        ],
                        uncertainties=[
                            "Full tracking and isolation did not run from the fallback path."
                        ],
                    ),
                )

        container.orchestrator.video_runtime = FakeVideoRuntime()
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Missing Report Guardrail", mode=AssistantMode.GENERAL)
        )
        video_path = tmp_path / "missing-report.mp4"
        video_path.write_bytes(b"fake-video-bytes")
        ingest_result = container.store.ingest_assets(
            AssetIngestRequest(source_paths=[str(video_path)])
        )

        asyncio.run(
            _collect_events(
                container,
                ConversationTurnRequest(
                    conversation_id=conversation.id,
                    mode=AssistantMode.GENERAL,
                    text="Review this video conservatively first.",
                    asset_ids=ingest_result.asset_ids,
                ),
            )
        )
        asyncio.run(
            _collect_events(
                container,
                ConversationTurnRequest(
                    conversation_id=conversation.id,
                    mode=AssistantMode.GENERAL,
                    text="Draft a short message to a supervisor summarizing the first video conservatively.",
                ),
            )
        )
        asyncio.run(
            _collect_events(
                container,
                ConversationTurnRequest(
                    conversation_id=conversation.id,
                    mode=AssistantMode.GENERAL,
                    text="Prepare a report based on that video and save it as a report.",
                ),
            )
        )
        events = asyncio.run(
            _collect_events(
                container,
                ConversationTurnRequest(
                    conversation_id=conversation.id,
                    mode=AssistantMode.GENERAL,
                    text="What title are you using for that report draft right now?",
                ),
            )
        )
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"].lower()
        assert "there is no current report" in text
        assert "message draft" not in text

        events = asyncio.run(
            _collect_events(
                container,
                ConversationTurnRequest(
                    conversation_id=conversation.id,
                    mode=AssistantMode.GENERAL,
                    text="Keep that same report draft, but make the title shorter and clearer before we save it.",
                ),
            )
        )
        completed = [
            event for event in events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert completed
        text = completed[0].payload["text"].lower()
        assert "there is no current report" in text
        assert "what is the current draft you are referring to" not in text
        assert not any(event.type == StreamEventType.APPROVAL_REQUIRED for event in events)
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
        assert "keep this conversational" in completed[0].payload["text"].lower()
    finally:
        container.store.close()


def test_orchestrator_conversation_shortcut_overrides_runtime_for_small_talk(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-conversation-shortcut.db"))
    container = build_container(settings)
    try:
        class FakeAssistantRuntime:
            backend_name = "fake-assistant"

            def generate(self, request):
                return AssistantGenerationResult(
                    text="MODEL DRIFTED OFF TOPIC",
                    backend=self.backend_name,
                    model_name="fake-assistant",
                    model_source=None,
                )

            def synthesize_memory(self, request):
                return None

            def rank_memories(self, request):
                return None

            def resolve_memory_focus(self, request):
                return None

        container.orchestrator.runtime = FakeAssistantRuntime()
        container.orchestrator.memory_service = container.orchestrator.memory_service.__class__(
            container.orchestrator.runtime
        )
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Shortcut", mode=AssistantMode.GENERAL)
        )

        first = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="Hey, can we just talk normally for a minute?",
        )
        second = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            text="yoo",
        )

        first_events = asyncio.run(_collect_events(container, first))
        second_events = asyncio.run(_collect_events(container, second))

        first_completed = [
            event for event in first_events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        second_completed = [
            event for event in second_events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert first_completed
        assert second_completed
        assert first_completed[0].payload["text"] == "Yes. We can just talk this through."
        assert second_completed[0].payload["text"] == "Hey. What's up?"
    finally:
        container.store.close()


def test_orchestrator_conversation_shortcut_handles_thanks_during_pending_draft(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-thanks-shortcut.db"))
    container = build_container(settings)
    try:
        class FakeAssistantRuntime:
            backend_name = "fake-assistant"

            def generate(self, request):
                return AssistantGenerationResult(
                    text="MODEL DRIFTED BACK INTO THE DRAFT",
                    backend=self.backend_name,
                    model_name="fake-assistant",
                    model_source=None,
                )

            def synthesize_memory(self, request):
                return None

            def rank_memories(self, request):
                return None

            def resolve_memory_focus(self, request):
                return None

        container.orchestrator.runtime = FakeAssistantRuntime()
        container.orchestrator.memory_service = container.orchestrator.memory_service.__class__(
            container.orchestrator.runtime
        )
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Thanks during draft", mode=AssistantMode.RESEARCH)
        )

        first = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.RESEARCH,
            text="Create a report summarizing the current field assistant architecture.",
        )
        second = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.RESEARCH,
            text="Thanks",
        )

        first_events = asyncio.run(_collect_events(container, first))
        second_events = asyncio.run(_collect_events(container, second))

        first_completed = [
            event for event in first_events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        second_completed = [
            event for event in second_events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert first_completed
        assert second_completed
        assert first_completed[0].payload["text"] == "I drafted a report here."
        assert second_completed[0].payload["text"] == "Of course. I'm here when you want to keep going."
    finally:
        container.store.close()


def test_orchestrator_conversation_shortcut_handles_colloquial_turn_during_pending_draft(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "orchestrator-yoo-shortcut.db"))
    container = build_container(settings)
    try:
        class FakeAssistantRuntime:
            backend_name = "fake-assistant"

            def generate(self, request):
                return AssistantGenerationResult(
                    text="MODEL DRIFTED BACK INTO THE DRAFT",
                    backend=self.backend_name,
                    model_name="fake-assistant",
                    model_source=None,
                )

            def synthesize_memory(self, request):
                return None

            def rank_memories(self, request):
                return None

            def resolve_memory_focus(self, request):
                return None

        container.orchestrator.runtime = FakeAssistantRuntime()
        container.orchestrator.memory_service = container.orchestrator.memory_service.__class__(
            container.orchestrator.runtime
        )
        conversation = container.store.create_conversation(
            ConversationCreateRequest(title="Yoo during draft", mode=AssistantMode.RESEARCH)
        )

        first = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.RESEARCH,
            text="Create a report summarizing the current field assistant architecture.",
        )
        second = ConversationTurnRequest(
            conversation_id=conversation.id,
            mode=AssistantMode.RESEARCH,
            text="yoo",
        )

        first_events = asyncio.run(_collect_events(container, first))
        second_events = asyncio.run(_collect_events(container, second))

        first_completed = [
            event for event in first_events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        second_completed = [
            event for event in second_events if event.type == StreamEventType.ASSISTANT_MESSAGE_COMPLETED
        ]
        assert first_completed
        assert second_completed
        assert first_completed[0].payload["text"] == "I drafted a report here."
        assert second_completed[0].payload["text"] == "Hey. What's up?"
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
        assert "i updated the markdown export" in tighten_text.lower()
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
                    evidence_packet=EvidencePacket(
                        source_domain=SourceDomain.VIDEO,
                        asset_ids=[asset.asset_id for asset in request.assets],
                        profile=RuntimeProfile.LOW_MEMORY,
                        execution_mode=ExecutionMode.FALLBACK,
                        grounding_status=GroundingStatus.PARTIAL,
                        summary="Sampled frames show vehicle movement near the pit edge.",
                        facts=[
                            EvidenceFact(
                                summary="Heavy vehicle movement is visible near the pit edge.",
                                refs=[
                                    EvidenceRef(
                                        label="contact sheet",
                                        ref="site-contact-sheet.png",
                                    )
                                ],
                            )
                        ],
                        uncertainties=[
                            "Tracking and isolation did not run in this test runtime."
                        ],
                    ),
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
        assert assistant_message.evidence_packet is not None
        assert assistant_message.evidence_packet.source_domain == SourceDomain.VIDEO
        assert assistant_message.evidence_packet.summary
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
