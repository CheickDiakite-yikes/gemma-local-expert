import json
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import build_container, create_app
from engine.config.settings import Settings
from engine.contracts.api import AssetCareContext, AssetKind
from engine.models.video import VideoAnalysisResult, VideoArtifact
from engine.models.vision import VisionAnalysisResult


def test_health_endpoint(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-health.db"))
    client = TestClient(create_app(settings))

    response = client.get("/v1/system/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["tracking_backend"] == settings.tracking_backend
    assert response.json()["tracking_model"] == settings.default_tracking_model


def test_conversation_turn_streams_completion_event(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-turn.db"))
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={"title": "Test", "mode": "research"}).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Summarize the Kenya trip checklist.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    assert "assistant.message.completed" in response.text


def test_conversation_listing_and_transcript_endpoints(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-listing.db"))
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Field Session", "mode": "research"},
    ).json()

    turn_response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Summarize the Kenya trip checklist.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert turn_response.status_code == 200

    conversations_response = client.get("/v1/conversations")
    assert conversations_response.status_code == 200
    conversations = conversations_response.json()
    assert conversations
    assert conversations[0]["id"] == conversation["id"]
    assert conversations[0]["last_message_preview"]

    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()
    assert [message["role"] for message in transcript] == ["user", "assistant"]


def test_conversation_delete_removes_transcript_and_listing(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-delete.db"))
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Delete me", "mode": "general"},
    ).json()

    turn_response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Say hello normally.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert turn_response.status_code == 200

    delete_response = client.delete(f"/v1/conversations/{conversation['id']}")
    assert delete_response.status_code == 204
    assert delete_response.text == ""

    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 404

    conversations_response = client.get("/v1/conversations")
    assert conversations_response.status_code == 200
    conversations = conversations_response.json()
    assert all(item["id"] != conversation["id"] for item in conversations)


def test_approval_executes_checklist_tool_and_persists_note(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-approval.db"))
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={"title": "Tool", "mode": "field"}).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "field",
            "text": "Create a checklist for tomorrow's village visits.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    lines = [line for line in response.text.splitlines() if line.strip()]
    approval_event = next(line for line in lines if '"type":"approval.required"' in line)
    approval_payload = json.loads(approval_event)
    approval_id = approval_payload["payload"]["id"]

    approval_response = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )

    assert approval_response.status_code == 200
    assert approval_response.json()["status"] == "executed"

    notes_response = client.get("/v1/notes")
    assert notes_response.status_code == 200
    notes = notes_response.json()
    assert notes
    assert notes[0]["kind"] == "checklist"


def test_conversational_image_turn_does_not_force_tool_output(tmp_path: Path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "test-image-chat.db"),
        asset_storage_dir=str(tmp_path / "uploads"),
        specialist_backend="mock",
    )
    app = create_app(settings)

    class FakeVisionRuntime:
        backend_name = "fake-vision"

        def analyze(self, request):
            return VisionAnalysisResult(
                text=(
                    "Visible text extracted from the image:\n"
                    "Lantern batteries low\n"
                    "Translator phone credits low"
                ),
                backend="fake-vision",
                model_name=request.specialist_model_name,
                model_source="/tmp/fake-paligemma",
                available=True,
            )

    app.state.container.orchestrator.vision_runtime = FakeVisionRuntime()
    client = TestClient(app)
    image_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("board.png", _tiny_png_bytes(), "image/png")},
    ).json()["asset"]
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Image chat", "mode": "general"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "I'm not trying to save anything right now. What do you notice first in this image?",
            "asset_ids": [image_asset["id"]],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    assert "From the image" in response.text
    assert '"type":"approval.required"' not in response.text


def test_transcript_rehydrates_executed_approval_state(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-approval-transcript.db"))
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={"title": "Tool", "mode": "field"}).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "field",
            "text": "Create a checklist for tomorrow's village visits.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    lines = [line for line in response.text.splitlines() if line.strip()]
    approval_event = next(line for line in lines if '"type":"approval.required"' in line)
    approval_payload = json.loads(approval_event)
    approval_id = approval_payload["payload"]["id"]

    approval_response = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )
    assert approval_response.status_code == 200
    assert approval_response.json()["status"] == "executed"


def test_report_turn_requires_approval_and_persists_report_kind(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-report-approval.db"))
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={"title": "Report", "mode": "research"}).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Create a report summarizing the current field assistant architecture.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    lines = [line for line in response.text.splitlines() if line.strip()]
    approval_event = next(line for line in lines if '"type":"approval.required"' in line)
    approval_payload = json.loads(approval_event)
    assert approval_payload["payload"]["tool_name"] == "create_report"
    approval_id = approval_payload["payload"]["id"]

    decision = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )

    assert decision.status_code == 200
    approval = decision.json()
    assert approval["status"] == "executed"
    assert approval["result"]["entity_type"] == "note"
    assert approval["result"]["kind"] == "report"

    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()


def test_message_draft_turn_after_image_requires_approval_and_persists_message_draft_kind(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-message-draft-approval.db"))
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Message draft", "mode": "general"},
    ).json()

    image_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("board.png", _tiny_png_bytes(), "image/png")},
    ).json()["asset"]

    first_turn = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Describe this supply image conservatively.",
            "asset_ids": [image_asset["id"]],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert first_turn.status_code == 200

    second_turn = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Draft a short message to the logistics lead about the two shortages that matter most before departure.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert second_turn.status_code == 200
    lines = [line for line in second_turn.text.splitlines() if line.strip()]
    approval_event = next(line for line in lines if '"type":"approval.required"' in line)
    approval_payload = json.loads(approval_event)
    assert approval_payload["payload"]["tool_name"] == "create_message_draft"
    approval_id = approval_payload["payload"]["id"]

    decision = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )
    assert decision.status_code == 200
    approval = decision.json()
    assert approval["status"] == "executed"
    assert approval["result"]["entity_type"] == "note"
    assert approval["result"]["kind"] == "message_draft"

    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()
    assistant_message = transcript[-1]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["turn_id"]
    assert assistant_message["approval"]["id"] == approval_id
    assert assistant_message["approval"]["status"] == "executed"
    assert assistant_message["approval"]["result"]["entity_type"] == "note"


def test_build_container_supports_mlx_embedding_backend(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeEmbeddingProvider:
        provider_name = "mlx"
        model_id = "google/embeddinggemma-300m"
        dimensions = 768

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * self.dimensions for _ in texts]

    monkeypatch.setattr(
        "engine.api.app.MLXEmbeddingGemmaProvider",
        lambda model_id, model_source, max_length: FakeEmbeddingProvider(),
    )

    settings = Settings(
        database_path=str(tmp_path / "test-mlx-embed.db"),
        embedding_backend="mlx",
    )
    container = build_container(settings)
    try:
        assert container.store.embedding_provider.provider_name == "mlx"
    finally:
        container.store.close()


def test_build_container_supports_auto_specialist_backend(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeVisionRuntime:
        backend_name = "mlx"

        def __init__(self, *, allow_remote: bool) -> None:
            self.allow_remote = allow_remote

    monkeypatch.setattr(
        "engine.api.app.MLXVisionRuntime",
        lambda allow_remote: FakeVisionRuntime(allow_remote=allow_remote),
    )

    settings = Settings(
        database_path=str(tmp_path / "test-auto-specialist.db"),
        specialist_backend="auto",
    )
    container = build_container(settings)
    try:
        assert container.vision_runtime.backend_name == "mlx"
        assert container.vision_runtime.allow_remote is False
    finally:
        container.store.close()


def test_build_container_supports_ocr_specialist_backend(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeVisionRuntime:
        backend_name = "tesseract"

    monkeypatch.setattr(
        "engine.api.app.TesseractVisionRuntime",
        lambda: FakeVisionRuntime(),
    )

    settings = Settings(
        database_path=str(tmp_path / "test-ocr-specialist.db"),
        specialist_backend="ocr",
    )
    container = build_container(settings)
    try:
        assert container.vision_runtime.backend_name == "tesseract"
    finally:
        container.store.close()


def test_asset_upload_content_and_transcript_linking(tmp_path: Path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "test-assets.db"),
        asset_storage_dir=str(tmp_path / "uploads"),
    )
    client = TestClient(create_app(settings))

    upload_response = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("poster.png", _tiny_png_bytes(), "image/png")},
    )

    assert upload_response.status_code == 200
    asset = upload_response.json()["asset"]
    assert asset["kind"] == "image"
    assert asset["content_url"]

    content_response = client.get(asset["content_url"])
    assert content_response.status_code == 200
    assert content_response.content.startswith(b"\x89PNG")

    conversation = client.post(
        "/v1/conversations",
        json={"title": "Images", "mode": "general"},
    ).json()
    turn_response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Describe the attached image conservatively.",
            "asset_ids": [asset["id"]],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert turn_response.status_code == 200
    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()
    assert transcript[0]["assets"][0]["id"] == asset["id"]
    assert transcript[0]["assets"][0]["kind"] == "image"


def test_video_upload_content_and_transcript_linking(tmp_path: Path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "test-video-assets.db"),
        asset_storage_dir=str(tmp_path / "uploads"),
        tracking_backend="mock",
    )
    client = TestClient(create_app(settings))

    upload_response = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("site-review.mov", b"fake-video-bytes", "video/quicktime")},
    )

    assert upload_response.status_code == 200
    asset = upload_response.json()["asset"]
    assert asset["kind"] == "video"
    assert asset["content_url"]
    assert asset["preview_url"] == asset["content_url"]

    content_response = client.get(asset["content_url"])
    assert content_response.status_code == 200
    assert content_response.content == b"fake-video-bytes"

    conversation = client.post(
        "/v1/conversations",
        json={"title": "Video", "mode": "general"},
    ).json()
    turn_response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
          "conversation_id": conversation["id"],
          "mode": "general",
          "text": "Review the attached mining video conservatively.",
          "asset_ids": [asset["id"]],
          "enabled_knowledge_pack_ids": [],
          "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert turn_response.status_code == 200
    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()
    assert transcript[0]["assets"][0]["id"] == asset["id"]
    assert transcript[0]["assets"][0]["kind"] == "video"


def test_medical_image_requires_explicit_session(tmp_path: Path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "test-medical-assets.db"),
        asset_storage_dir=str(tmp_path / "uploads"),
    )
    client = TestClient(create_app(settings))
    asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "medical"},
        files={"file": ("xray.png", _tiny_png_bytes(), "image/png")},
    ).json()["asset"]
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Medical", "mode": "general"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Interpret this x-ray image.",
            "asset_ids": [asset["id"]],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    assert "Medical specialist access requires an explicit medical session." in response.text
    assert "Request blocked by policy." in response.text


def test_heatmap_overlay_tool_generates_asset_and_persists_on_assistant_message(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=str(tmp_path / "test-heatmap.db"),
        asset_storage_dir=str(tmp_path / "uploads"),
        specialist_backend="mock",
    )
    client = TestClient(create_app(settings))

    upload_response = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("xray.png", _tiny_png_bytes(), "image/png")},
    )
    assert upload_response.status_code == 200
    asset = upload_response.json()["asset"]

    conversation = client.post(
        "/v1/conversations",
        json={"title": "Heatmap", "mode": "general"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Do a segmented heatmap layering of this x-ray image.",
            "asset_ids": [asset["id"]],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert any(line["type"] == "tool.started" for line in lines)

    completed_event = next(line for line in lines if line["type"] == "tool.completed")
    generated_asset = completed_event["payload"]["assets"][0]
    assert generated_asset["content_url"]
    assert generated_asset["display_name"].endswith("-segmented-heatmap.png")

    content_response = client.get(generated_asset["content_url"])
    assert content_response.status_code == 200
    assert content_response.content.startswith(b"\x89PNG")

    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()
    assistant_message = transcript[-1]
    assert assistant_message["assets"][0]["id"] == generated_asset["id"]


def test_capabilities_endpoint_reports_runtime_truth(tmp_path: Path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "test-capabilities.db"),
        workspace_root=str(tmp_path),
    )
    client = TestClient(create_app(settings))

    response = client.get("/v1/system/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_backend"] == settings.assistant_backend
    assert payload["workspace_root"] == str(tmp_path)
    assert "tesseract_available" in payload
    assert "ffmpeg_available" in payload


def test_general_conversation_turn_reads_naturally_without_retrieval_disclaimer(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-general-conversation.db"))
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "General", "mode": "general"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Hey, can we just talk normally for a minute?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    assert "talk normally" in response.text.lower()
    assert "retrieved local sources" not in response.text.lower()


def test_supportive_field_turn_avoids_retrieval_even_with_enabled_local_packs(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-supportive-conversation.db"))
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Support", "mode": "field"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "field",
            "text": (
                "Honestly I'm a little anxious about tomorrow. "
                "No checklist right now, just help me calm down for a second."
            ),
            "asset_ids": [],
            "enabled_knowledge_pack_ids": ["local-pack"],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    completed = next(line for line in lines if line["type"] == "assistant.message.completed")
    assert "take a breath" in completed["payload"]["text"].lower()
    assert not any(line["type"] == "citation.added" for line in lines)


def test_long_mixed_conversation_handles_general_follow_up_and_workspace_action(
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
        database_path=str(tmp_path / "test-long-mixed.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Mixed", "mode": "research"},
    ).json()

    first = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Hey, can we talk normally while you help me think through field work?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert first.status_code == 200
    assert "talk normally" in first.text.lower()

    second = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "What do you mean by that?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert second.status_code == 200
    assert "keep the conversation natural" in second.text.lower()

    third = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Prepare a briefing from the relevant workspace files.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert third.status_code == 200
    lines = [json.loads(line) for line in third.text.splitlines() if line.strip()]
    approval_event = next(line for line in lines if line["type"] == "approval.required")
    approval_id = approval_event["payload"]["id"]
    approval_content = approval_event["payload"]["payload"]["content"]
    assert "Key points:" in approval_content
    assert "Files reviewed:" in approval_content
    assert "Goal:" not in approval_content
    assert "Workspace scope:" not in approval_content

    decision = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={
            "action": "approve",
            "edited_payload": {
                "title": "Reviewed field briefing",
                "content": "Reviewed field briefing\n- Pack oral rehydration salts\n- Confirm translator contact sheet before departure\n",
            },
        },
    )
    assert decision.status_code == 200

    transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
    assert len(transcript) == 6
    assert [message["role"] for message in transcript] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert transcript[-1]["approval"]["status"] == "executed"


def test_workspace_agent_turn_persists_completed_run(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-prep.md").write_text(
        "Field prep checklist\nPack oral rehydration salts\nPack batteries\n",
        encoding="utf-8",
    )
    (workspace_root / "contacts.txt").write_text(
        "Translator contact sheet and village visit route.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-agent.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Workspace", "mode": "research"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Search this workspace and summarize the field prep docs.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    assert "Here is a concise briefing:" in response.text
    assert "Key points:" in response.text
    assert "I reviewed" not in response.text
    assert "Goal:" not in response.text
    assert "Workspace scope:" not in response.text

    runs_response = client.get(f"/v1/conversations/{conversation['id']}/runs")
    assert runs_response.status_code == 200
    runs = runs_response.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"
    assert runs[0]["executed_steps"]
    assert runs[0]["result_summary"]


def test_workspace_agent_briefing_requires_approval_and_completes_after_decision(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "trip.md").write_text(
        "Trip prep\nPack oral rehydration salts\nPack translator contact sheets\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-agent-approval.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Workspace Brief", "mode": "field"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "field",
            "text": "Prepare a briefing from the relevant workspace files.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    approval_event = next(line for line in lines if line["type"] == "approval.required")
    approval_id = approval_event["payload"]["id"]
    run_id = approval_event["payload"]["run_id"]

    runs_response = client.get(f"/v1/conversations/{conversation['id']}/runs")
    assert runs_response.status_code == 200
    runs = runs_response.json()
    assert runs[0]["id"] == run_id
    assert runs[0]["status"] == "awaiting_approval"

    decision_response = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={
            "action": "approve",
            "edited_payload": {
                "title": "Edited workspace briefing",
                "content": (
                    "Workspace briefing\n"
                    "- Pack oral rehydration salts\n"
                    "- Carry translator contact sheets\n"
                    "- Confirm the village route before departure\n"
                ),
            },
        },
    )
    assert decision_response.status_code == 200
    approval = decision_response.json()
    assert approval["payload"]["title"] == "Edited workspace briefing"

    run_response = client.get(f"/v1/runs/{run_id}")
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["status"] == "completed"
    assert run["approval_id"] == approval_id

    notes_response = client.get("/v1/notes")
    assert notes_response.status_code == 200
    notes = notes_response.json()
    assert notes
    assert notes[0]["title"] == "Edited workspace briefing"
    assert "Confirm the village route before departure" in notes[0]["content"]


def test_workspace_agent_can_export_brief_as_markdown(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "trip.md").write_text(
        "Trip prep\nPack oral rehydration salts\nPack translator contact sheets\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-agent-export.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Workspace Export", "mode": "field"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "field",
            "text": "Prepare a short workspace briefing from the relevant files and export it as markdown.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    approval_event = next(line for line in lines if line["type"] == "approval.required")
    approval_id = approval_event["payload"]["id"]
    assert approval_event["payload"]["tool_name"] == "export_brief"

    decision_response = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )
    assert decision_response.status_code == 200
    approval = decision_response.json()
    assert approval["status"] == "executed"
    assert approval["result"]["entity_type"] == "export"
    assert approval["result"]["title"] == "Workspace Briefing"
    assert approval["result"]["destination_path"].endswith(".md")
    assert Path(approval["result"]["destination_path"]).exists()
    assert "Key points:" in Path(approval["result"]["destination_path"]).read_text(encoding="utf-8")


def test_pending_export_follow_up_can_answer_title_without_reusing_media_context(
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
        database_path=str(tmp_path / "test-export-follow-up.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Export Follow-up", "mode": "research"},
    ).json()

    first = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert first.status_code == 200

    follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "What title are you using for that draft?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert follow_up.status_code == 200
    lines = [json.loads(line) for line in follow_up.text.splitlines() if line.strip()]
    completed = next(line for line in lines if line["type"] == "assistant.message.completed")
    text = completed["payload"]["text"]
    assert "Field Assistant Architecture Briefing" in text
    assert "pit edge" not in text.lower()

    summary_follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "What's in that draft again?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert summary_follow_up.status_code == 200
    summary_lines = [json.loads(line) for line in summary_follow_up.text.splitlines() if line.strip()]
    summary_completed = next(
        line for line in summary_lines if line["type"] == "assistant.message.completed"
    )
    summary_text = summary_completed["payload"]["text"]
    assert "currently centers on" in summary_text.lower()
    assert "local-first assistant built on gemma" in summary_text.lower()
    assert "pit edge" not in summary_text.lower()

    tighten_follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Keep the same draft, but make that shorter before I save it.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert tighten_follow_up.status_code == 200
    tighten_lines = [json.loads(line) for line in tighten_follow_up.text.splitlines() if line.strip()]
    tighten_completed = next(
        line for line in tighten_lines if line["type"] == "assistant.message.completed"
    )
    tighten_approval = next(line for line in tighten_lines if line["type"] == "approval.required")
    tighten_text = tighten_completed["payload"]["text"]
    assert "i tightened the current markdown export draft" in tighten_text.lower()
    assert "field assistant architecture brief" in tighten_text.lower()
    assert "pit edge" not in tighten_text.lower()
    assert (
        tighten_approval["payload"]["payload"]["title"]
        == "Field Assistant Architecture Brief"
    )
    assert "Files reviewed:" not in tighten_approval["payload"]["payload"]["content"]

    transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
    assistant_with_pending = next(
        message
        for message in transcript
        if message["role"] == "assistant"
        and message.get("approval")
        and message["approval"]["status"] == "pending"
    )
    assert (
        assistant_with_pending["approval"]["payload"]["title"]
        == "Field Assistant Architecture Brief"
    )


def test_multi_output_recall_question_does_not_trigger_new_export(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-assistant-architecture.md").write_text(
        "Field Assistant architecture overview\n"
        "Local-first assistant built on Gemma.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-multi-output-recall.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Multi-output Recall", "mode": "research"},
    ).json()

    report = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Create a report summarizing the current field assistant architecture.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    report_lines = [json.loads(line) for line in report.text.splitlines() if line.strip()]
    report_approval = next(line for line in report_lines if line["type"] == "approval.required")
    client.post(
        f"/v1/approvals/{report_approval['payload']['id']}/decisions",
        json={
            "action": "approve",
            "edited_payload": {"title": "Architecture status report"},
        },
    )

    checklist = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Create a checklist for tomorrow's departure.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    checklist_lines = [json.loads(line) for line in checklist.text.splitlines() if line.strip()]
    checklist_approval = next(
        line for line in checklist_lines if line["type"] == "approval.required"
    )
    client.post(
        f"/v1/approvals/{checklist_approval['payload']['id']}/decisions",
        json={
            "action": "approve",
            "edited_payload": {
                "title": "Departure shortage checklist",
                "content": "- [ ] Replace low lantern batteries\n- [ ] Confirm consent forms",
            },
        },
    )

    export = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    export_lines = [json.loads(line) for line in export.text.splitlines() if line.strip()]
    export_approval = next(line for line in export_lines if line["type"] == "approval.required")
    client.post(
        f"/v1/approvals/{export_approval['payload']['id']}/decisions",
        json={
            "action": "approve",
            "edited_payload": {"title": "Field Assistant Architecture Briefing"},
        },
    )

    follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "What was in the earlier report again, what was in the checklist, and what is the newer export called?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert follow_up.status_code == 200
    follow_up_lines = [json.loads(line) for line in follow_up.text.splitlines() if line.strip()]
    assert not any(line["type"] == "approval.required" for line in follow_up_lines)
    completed = next(line for line in follow_up_lines if line["type"] == "assistant.message.completed")
    text = completed["payload"]["text"]
    assert "Architecture status report" in text
    assert "Departure shortage checklist" in text
    assert "Field Assistant Architecture Briefing" in text


def test_multimodal_conversation_handles_topic_pivots_follow_ups_and_workspace_output(
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
        database_path=str(tmp_path / "test-multimodal-mixed.db"),
        workspace_root=str(workspace_root),
        asset_storage_dir=str(tmp_path / "uploads"),
        specialist_backend="mock",
        tracking_backend="mock",
    )
    app = create_app(settings)

    class FakeVisionRuntime:
        backend_name = "fake-vision"

        def analyze(self, request):
            return VisionAnalysisResult(
                text=(
                    "Visible text extracted from the image:\n"
                    "Lantern batteries low\n"
                    "Translator phone credits low"
                ),
                backend="fake-vision",
                model_name=request.specialist_model_name,
                model_source="/tmp/fake-paligemma",
                available=True,
            )

    class FakeVideoRuntime:
        backend_name = "fake-video"

        def analyze(self, request):
            contact_sheet_path = tmp_path / "mine-contact-sheet.png"
            contact_sheet_path.write_bytes(_tiny_png_bytes())
            return VideoAnalysisResult(
                text=(
                    "Reviewed the attached mining clip conservatively. "
                    "I can see workers near excavation equipment and repeated tool handling around the pit edge."
                ),
                backend="fake-video",
                model_name=request.tracking_model_name,
                model_source="/tmp/fake-sam",
                available=True,
                artifacts=[
                    VideoArtifact(
                        display_name="mine-contact-sheet.png",
                        local_path=str(contact_sheet_path),
                        media_type="image/png",
                        kind=AssetKind.IMAGE,
                        care_context=AssetCareContext.GENERAL,
                        analysis_summary="Sampled contact sheet from the uploaded video for local review.",
                    )
                ],
            )

    app.state.container.orchestrator.vision_runtime = FakeVisionRuntime()
    app.state.container.orchestrator.video_runtime = FakeVideoRuntime()
    client = TestClient(app)

    image_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("board.png", _tiny_png_bytes(), "image/png")},
    ).json()["asset"]
    video_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("mine.mov", b"fake-video-bytes", "video/quicktime")},
    ).json()["asset"]

    conversation = client.post(
        "/v1/conversations",
        json={"title": "Multimodal Mixed", "mode": "research"},
    ).json()

    turn_responses: list[str] = []
    approval_id = None
    approval_content = None

    turns = [
        ("Hey, can we just think out loud for a second?", []),
        ("Teach me how to prepare oral rehydration solution in the field.", []),
        ("What should I emphasize first to a volunteer with no medical training?", []),
        ("Describe the attached supply image conservatively.", [image_asset["id"]]),
        ("Which two shortages matter most before departure?", []),
        ("Also, can we switch topics and just chat normally again for a second?", []),
        (
            "Honestly I'm a little anxious about tomorrow. "
            "No checklist right now, just help me calm down for a second.",
            [],
        ),
        ("Review the attached mining video conservatively.", [video_asset["id"]]),
        (
            "Separate topic again. Prepare a short workspace briefing about the current "
            "field assistant architecture and save it as a note, but keep it concise.",
            [],
        ),
    ]

    for text, asset_ids in turns:
        response = client.post(
            f"/v1/conversations/{conversation['id']}/turns",
            json={
                "conversation_id": conversation["id"],
                "mode": "research",
                "text": text,
                "asset_ids": asset_ids,
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
            },
        )
        assert response.status_code == 200
        turn_responses.append(response.text)
        if '"type":"approval.required"' in response.text:
            approval_line = next(
                json.loads(line)
                for line in response.text.splitlines()
                if '"type":"approval.required"' in line
            )
            approval_id = approval_line["payload"]["id"]
            approval_content = approval_line["payload"]["payload"]["content"]

    assert "talk normally" in turn_responses[0].lower()
    assert "ors guidance" in turn_responses[1].lower()
    assert "most practical first point" in turn_responses[2].lower()
    assert "from the image" in turn_responses[3].lower()
    assert "lantern batteries low" in turn_responses[3].lower()
    assert "two clearest shortages" in turn_responses[4].lower()
    assert "translator phone credits" in turn_responses[4].lower()
    assert any(
        phrase in turn_responses[5].lower()
        for phrase in {"talk normally", "normal conversation"}
    )
    assert "take a breath" in turn_responses[6].lower()
    assert "checklist" not in turn_responses[6].lower()
    assert "workers near excavation equipment" in turn_responses[7].lower()
    assert "available specialist analysis" not in turn_responses[3].lower()
    assert "available specialist analysis" not in turn_responses[7].lower()
    assert approval_id is not None
    assert approval_content is not None
    assert "Key points:" in approval_content
    assert "Files reviewed:" in approval_content
    assert not approval_content.startswith("I reviewed")
    assert "Visible text extracted from the image" not in approval_content
    assert "Goal:" not in approval_content
    assert "Workspace scope:" not in approval_content

    decision = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )
    assert decision.status_code == 200

    transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
    assert len(transcript) == 18
    assert transcript[-1]["approval"]["status"] == "executed"

    notes = client.get("/v1/notes").json()
    assert notes
    assert "Key points:" in notes[0]["content"]
    assert "Files reviewed:" in notes[0]["content"]
    assert not notes[0]["content"].startswith("I reviewed")
    assert "Goal:" not in notes[0]["content"]
    assert "Workspace scope:" not in notes[0]["content"]


def test_mixed_multimodal_conversation_handles_topic_pivots_without_magic_reset_phrase(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-assistant-architecture.md").write_text(
        "Field Assistant architecture overview\n"
        "Local-first assistant built on Gemma.\n"
        "Uses a bounded orchestrator with retrieval, vision, and approvals.\n",
        encoding="utf-8",
    )
    (workspace_root / "field-assistant-product-spec.md").write_text(
        "Field Assistant product spec\n"
        "Primary goal is grounded field help with conversational fallback.\n",
        encoding="utf-8",
    )
    settings = Settings(
        database_path=str(tmp_path / "test-multimodal-topic-pivots.db"),
        workspace_root=str(workspace_root),
        asset_storage_dir=str(tmp_path / "uploads"),
        specialist_backend="mock",
        tracking_backend="mock",
    )
    app = create_app(settings)

    class FakeVisionRuntime:
        backend_name = "fake-vision"

        def analyze(self, request):
            return VisionAnalysisResult(
                text=(
                    "Visible text extracted from the image:\n"
                    "Lantern batteries low\n"
                    "Translator phone credits low"
                ),
                backend="fake-vision",
                model_name=request.specialist_model_name,
                model_source="/tmp/fake-paligemma",
                available=True,
            )

    class FakeVideoRuntime:
        backend_name = "fake-video"

        def analyze(self, request):
            return VideoAnalysisResult(
                text=(
                    "Reviewed the attached mining clip conservatively. "
                    "I can see workers near excavation equipment and repeated tool handling around the pit edge."
                ),
                backend="fake-video",
                model_name=request.tracking_model_name,
                model_source="/tmp/fake-sam",
                available=True,
            )

    app.state.container.orchestrator.vision_runtime = FakeVisionRuntime()
    app.state.container.orchestrator.video_runtime = FakeVideoRuntime()
    client = TestClient(app)

    image_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("board.png", _tiny_png_bytes(), "image/png")},
    ).json()["asset"]
    video_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("mine.mov", b"fake-video-bytes", "video/quicktime")},
    ).json()["asset"]
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Mixed pivots", "mode": "research"},
    ).json()

    turns = [
        ("Describe the attached supply image conservatively.", [image_asset["id"]]),
        ("Which two shortages matter most before departure?", []),
        ("Teach me how to explain oral rehydration solution to a new volunteer.", []),
        ("Review the attached mining video conservatively.", [video_asset["id"]]),
        (
            "Honestly I'm a little anxious about tomorrow. "
            "No checklist right now, just help me calm down for a second.",
            [],
        ),
        ("Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.", []),
    ]

    turn_responses: list[str] = []
    approval_id = None
    approval_content = ""
    for text, asset_ids in turns:
        response = client.post(
            f"/v1/conversations/{conversation['id']}/turns",
            json={
                "conversation_id": conversation["id"],
                "mode": "research",
                "text": text,
                "asset_ids": asset_ids,
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
            },
        )
        assert response.status_code == 200
        turn_responses.append(response.text)
        if '"type":"approval.required"' in response.text:
            approval_line = next(
                json.loads(line)
                for line in response.text.splitlines()
                if '"type":"approval.required"' in line
            )
            approval_id = approval_line["payload"]["id"]
            approval_content = approval_line["payload"]["payload"]["content"]
            assert approval_line["payload"]["tool_name"] == "export_brief"

    assert "from the image" in turn_responses[0].lower()
    assert "two clearest shortages" in turn_responses[1].lower()
    assert "ors guidance" in turn_responses[2].lower()
    assert "lantern batteries" not in turn_responses[2].lower()
    assert "workers near excavation equipment" in turn_responses[3].lower()
    assert "take a breath" in turn_responses[4].lower()
    assert "workers near excavation equipment" not in turn_responses[4].lower()
    assert approval_id is not None
    assert "Key points:" in approval_content
    assert "Files reviewed:" in approval_content
    assert "Related docs:" not in approval_content
    assert "Related brief:" not in approval_content
    assert "Working title:" not in approval_content
    assert "Visible text extracted from the image" not in approval_content
    assert "workers near excavation equipment" not in approval_content

    decision = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )
    assert decision.status_code == 200
    approval = decision.json()
    assert approval["status"] == "executed"
    assert approval["result"]["entity_type"] == "export"
    export_path = Path(approval["result"]["destination_path"])
    assert export_path.exists()
    exported = export_path.read_text(encoding="utf-8")
    assert "Key points:" in exported
    assert "Files reviewed:" in exported
    assert "Related docs:" not in exported
    assert "Related brief:" not in exported
    assert "Working title:" not in exported
    assert "Visible text extracted from the image" not in exported
    assert "workers near excavation equipment" not in exported


def test_multimodal_conversation_can_return_to_earlier_image_after_video_turn(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=str(tmp_path / "test-multimodal-rereference.db"),
        asset_storage_dir=str(tmp_path / "uploads"),
        specialist_backend="mock",
        tracking_backend="mock",
    )
    app = create_app(settings)

    class FakeVisionRuntime:
        backend_name = "fake-vision"

        def analyze(self, request):
            asset_name = request.assets[0].display_name.lower()
            if "board" in asset_name:
                text = (
                    "Visible text extracted from the image:\n"
                    "Lantern batteries low\n"
                    "Translator phone credits low"
                )
            else:
                text = "Visible text extracted from the image:\nGeneric field note"
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
                text=(
                    "Reviewed the attached mining clip conservatively. "
                    "I can see workers near excavation equipment and repeated tool handling around the pit edge."
                ),
                backend="fake-video",
                model_name=request.tracking_model_name,
                model_source="/tmp/fake-sam",
                available=True,
            )

    app.state.container.orchestrator.vision_runtime = FakeVisionRuntime()
    app.state.container.orchestrator.video_runtime = FakeVideoRuntime()
    client = TestClient(app)

    image_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("board.png", _tiny_png_bytes(), "image/png")},
    ).json()["asset"]
    video_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("mine.mov", b"fake-video-bytes", "video/quicktime")},
    ).json()["asset"]
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Multimodal Re-reference", "mode": "general"},
    ).json()

    for text, asset_ids in [
        ("Describe the attached supply image conservatively.", [image_asset["id"]]),
        ("Review the attached mining video conservatively.", [video_asset["id"]]),
    ]:
        response = client.post(
            f"/v1/conversations/{conversation['id']}/turns",
            json={
                "conversation_id": conversation["id"],
                "mode": "general",
                "text": text,
                "asset_ids": asset_ids,
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
            },
        )
        assert response.status_code == 200

    third = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Go back to the earlier image for a second. Which shortage mattered most?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert third.status_code == 200
    third_text = third.text.lower()
    assert "lantern batteries" in third_text
    assert "pit edge" not in third_text
    assert "eater" not in third_text


def test_mixed_conversation_can_revisit_media_and_pending_draft_after_pivot(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-assistant-architecture.md").write_text(
        "Field Assistant architecture overview\n"
        "Local-first assistant built on Gemma.\n"
        "Uses bounded routing, retrieval, vision, and approvals.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-mixed-context-recovery.db"),
        workspace_root=str(workspace_root),
        asset_storage_dir=str(tmp_path / "uploads"),
        specialist_backend="mock",
        tracking_backend="mock",
    )
    app = create_app(settings)

    class FakeVisionRuntime:
        backend_name = "fake-vision"

        def analyze(self, request):
            return VisionAnalysisResult(
                text=(
                    "Visible text extracted from the image:\n"
                    "Lantern batteries low\n"
                    "Translator phone credits low"
                ),
                backend="fake-vision",
                model_name=request.specialist_model_name,
                model_source="/tmp/fake-paligemma",
                available=True,
            )

    class FakeVideoRuntime:
        backend_name = "fake-video"

        def analyze(self, request):
            return VideoAnalysisResult(
                text=(
                    "Reviewed the attached mining clip conservatively. "
                    "I can see workers near excavation equipment and repeated tool handling around the pit edge."
                ),
                backend="fake-video",
                model_name=request.tracking_model_name,
                model_source="/tmp/fake-sam",
                available=True,
            )

    app.state.container.orchestrator.vision_runtime = FakeVisionRuntime()
    app.state.container.orchestrator.video_runtime = FakeVideoRuntime()
    client = TestClient(app)

    image_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("board.png", _tiny_png_bytes(), "image/png")},
    ).json()["asset"]
    video_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("mine.mov", b"fake-video-bytes", "video/quicktime")},
    ).json()["asset"]
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Mixed context recovery", "mode": "research"},
    ).json()

    turns = [
        ("Describe the attached supply image conservatively.", [image_asset["id"]]),
        ("Which two shortages matter most before departure?", []),
        ("Review the attached mining video conservatively.", [video_asset["id"]]),
        ("Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.", []),
        ("What's in that draft again?", []),
        ("Keep the same draft, but make that shorter before I save it.", []),
        ("Actually, just talk normally with me for a second.", []),
        ("Go back to the earlier image for a second. Which shortage mattered most?", []),
        ("And what is the draft called now?", []),
    ]

    responses: list[str] = []
    latest_approval_payload = None
    completed_texts: list[str] = []
    for text, asset_ids in turns:
        response = client.post(
            f"/v1/conversations/{conversation['id']}/turns",
            json={
                "conversation_id": conversation["id"],
                "mode": "research",
                "text": text,
                "asset_ids": asset_ids,
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
            },
        )
        assert response.status_code == 200
        responses.append(response.text)
        completed_line = next(
            json.loads(line)
            for line in response.text.splitlines()
            if '"type":"assistant.message.completed"' in line
        )
        completed_texts.append(completed_line["payload"]["text"])
        if '"type":"approval.required"' in response.text:
            latest_approval_payload = next(
                json.loads(line)["payload"]
                for line in response.text.splitlines()
                if '"type":"approval.required"' in line
            )

    assert "workers near excavation equipment" in responses[2].lower()
    assert latest_approval_payload is not None
    assert latest_approval_payload["payload"]["title"] == "Field Assistant Architecture Brief"
    assert "pit edge" not in completed_texts[6].lower()
    assert "field assistant architecture brief" not in completed_texts[6].lower()
    assert "lantern batteries" in completed_texts[7].lower()
    assert "pit edge" not in completed_texts[7].lower()


def test_follow_up_can_target_earlier_checklist_even_after_newer_export_draft(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-assistant-architecture.md").write_text(
        "Field Assistant architecture overview\n"
        "Local-first assistant built on Gemma.\n"
        "Uses bounded routing, retrieval, vision, and approvals.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-output-kind-resolution.db"),
        workspace_root=str(workspace_root),
        asset_storage_dir=str(tmp_path / "uploads"),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Output kind resolution", "mode": "research"},
    ).json()

    checklist_turn = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Create a checklist for tomorrow's village visits.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert checklist_turn.status_code == 200

    export_turn = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert export_turn.status_code == 200

    follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "What was in that checklist again?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert follow_up.status_code == 200

    completed_line = next(
        json.loads(line)
        for line in follow_up.text.splitlines()
        if '"type":"assistant.message.completed"' in line
    )
    text = completed_line["payload"]["text"].lower()
    assert "current checklist" in text
    assert "checklist for tomorrow's village visits" in text
    assert "markdown export" not in text


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc``\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\x18"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
