import json
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import build_container, create_app
from engine.config.settings import Settings
from engine.models.video import VideoAnalysisResult
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
    assert "I reviewed" in response.text
    assert "Key points:" in response.text
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


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc``\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\x18"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
