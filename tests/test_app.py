import json
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.app import build_container, create_app
from engine.config.settings import Settings
from engine.contracts.api import (
    ApprovalCategory,
    AssetCareContext,
    AssetKind,
    ApprovalMode,
    ConversationMemoryEntry,
    ConversationMemoryKind,
    ConversationItemKind,
    PermissionClass,
    SourceDomain,
    SandboxMode,
    new_id,
)
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


def test_system_tools_expose_permission_classes_and_approval_categories(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-tools-endpoint.db"))
    client = TestClient(create_app(settings))

    response = client.get("/v1/system/tools")

    assert response.status_code == 200
    tools = {tool["name"]: tool for tool in response.json()}

    assert tools["create_report"]["approval_category"] == "durable_write"
    assert "durable_output" in tools["create_report"]["permission_classes"]
    assert tools["export_brief"]["approval_category"] == "audited_export"
    assert "audit_log" in tools["export_brief"]["permission_classes"]
    assert tools["generate_heatmap_overlay"]["approval_category"] is None


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


def test_stream_events_include_item_snapshots_for_assistant_and_approval_state(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-stream-items.db"))
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations", json={"title": "Stream items", "mode": "research"}
    ).json()

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
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    completed = next(line for line in lines if line["type"] == "assistant.message.completed")
    proposed = next(line for line in lines if line["type"] == "tool.proposed")
    approval = next(line for line in lines if line["type"] == "approval.required")

    assert completed["payload"]["item"]["kind"] == "assistant_message"
    assert completed["payload"]["item"]["turn_id"] == completed["turn_id"]
    assert proposed["payload"]["item"]["kind"] == "tool_proposal"
    assert proposed["payload"]["item"]["payload"]["tool_name"] == "create_report"
    assert approval["payload"]["item"]["kind"] == "approval"
    assert approval["payload"]["item"]["payload"]["approval"]["id"] == approval["payload"]["id"]
    assert approval["payload"]["work_product_item"]["kind"] == "work_product"
    assert approval["payload"]["work_product_item"]["payload"]["approval_id"] == approval["payload"]["id"]
    assert approval["payload"]["work_product_item"]["payload"]["work_product"]["title"] == "Field Assistant Architecture Report"
    assert approval["payload"]["category"] == "durable_write"
    assert "durable_output" in approval["payload"]["permission_classes"]


def test_turn_records_capture_policy_and_items_for_simple_chat(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-turn-records.db"))
    app = create_app(settings)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={"title": "Turns", "mode": "general"}).json()

    response = client.post(
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

    assert response.status_code == 200
    turns = app.state.container.store.list_turn_records(conversation["id"])
    assert len(turns) == 1
    turn = turns[0]
    assert turn.route_kind == "conversation"
    assert turn.policy.workspace_root == settings.workspace_root
    assert turn.policy.cwd == settings.workspace_root
    assert turn.policy.sandbox_mode == SandboxMode.READ_ONLY
    assert turn.policy.approval_mode == ApprovalMode.NONE
    assert turn.policy.permission_classes == [PermissionClass.LOCAL_READ]
    assert turn.policy.requires_confirmation is False
    assert turn.policy.approval_summary is None
    assert turn.user_message_id
    assert turn.assistant_message_id

    items = app.state.container.store.list_items(conversation["id"], turn_id=turn.id)
    assert [item.kind for item in items] == [
        ConversationItemKind.USER_MESSAGE,
        ConversationItemKind.ASSISTANT_MESSAGE,
    ]


def test_durable_turn_persists_approval_item_and_workspace_write_policy(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-turn-approval-ledger.db"))
    app = create_app(settings)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={"title": "Draft", "mode": "general"}).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Create a report summarizing the current field assistant architecture.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    turns = app.state.container.store.list_turn_records(conversation["id"])
    assert len(turns) == 1
    turn = turns[0]
    assert turn.policy.sandbox_mode == SandboxMode.WORKSPACE_WRITE
    assert turn.policy.approval_mode == ApprovalMode.DURABLE_WRITE
    assert turn.policy.approval_category == ApprovalCategory.DURABLE_WRITE
    assert PermissionClass.WORKSPACE_WRITE in turn.policy.permission_classes
    assert PermissionClass.TOOL_EXECUTION in turn.policy.permission_classes
    assert PermissionClass.DURABLE_OUTPUT in turn.policy.permission_classes
    assert turn.policy.requires_confirmation is True
    assert "durable local report" in (turn.policy.approval_summary or "").lower()

    items = app.state.container.store.list_items(conversation["id"], turn_id=turn.id)
    kinds = [item.kind for item in items]
    assert ConversationItemKind.USER_MESSAGE in kinds
    assert ConversationItemKind.ASSISTANT_MESSAGE in kinds
    assert ConversationItemKind.APPROVAL in kinds
    assert ConversationItemKind.WORK_PRODUCT in kinds


def test_turn_and_item_endpoints_expose_internal_thread_state(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-thread-state-endpoints.db"))
    app = create_app(settings)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={"title": "State", "mode": "general"}).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Create a report summarizing the current field assistant architecture.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert response.status_code == 200

    turns_response = client.get(f"/v1/conversations/{conversation['id']}/turns")
    items_response = client.get(f"/v1/conversations/{conversation['id']}/items")

    assert turns_response.status_code == 200
    assert items_response.status_code == 200

    turns = turns_response.json()
    items = items_response.json()

    assert len(turns) == 1
    assert turns[0]["route_kind"]
    assert turns[0]["policy"]["sandbox_mode"] == "workspace_write"
    assert turns[0]["policy"]["approval_mode"] == "durable_write"
    assert turns[0]["policy"]["approval_category"] == "durable_write"
    assert "workspace_write" in turns[0]["policy"]["permission_classes"]
    assert "tool_execution" in turns[0]["policy"]["permission_classes"]
    assert turns[0]["policy"]["requires_confirmation"] is True
    assert any(item["kind"] == "approval" for item in items)


def test_conversation_state_endpoint_returns_coherent_thread_surface(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-conversation-state.db"))
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={"title": "State", "mode": "general"}).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Create a report summarizing the current field assistant architecture.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert response.status_code == 200

    state_response = client.get(f"/v1/conversations/{conversation['id']}/state")
    assert state_response.status_code == 200
    snapshot = state_response.json()

    assert snapshot["conversation"]["id"] == conversation["id"]
    assert [message["role"] for message in snapshot["messages"]] == ["user", "assistant"]
    assert len(snapshot["turns"]) == 1
    assert isinstance(snapshot["runs"], list)

    assistant_message = snapshot["messages"][-1]
    turn = snapshot["turns"][0]
    approval_item = next(item for item in snapshot["items"] if item["kind"] == "approval")
    work_product_item = next(item for item in snapshot["items"] if item["kind"] == "work_product")

    assert assistant_message["approval"] is not None
    assert assistant_message["approval"]["id"] == approval_item["payload"]["approval"]["id"]
    assert turn["assistant_message_id"] == assistant_message["id"]
    assert turn["route_kind"]
    assert turn["policy"]["sandbox_mode"] == "workspace_write"
    assert turn["policy"]["approval_mode"] == "durable_write"
    assert turn["policy"]["approval_category"] == "durable_write"
    assert "durable_output" in turn["policy"]["permission_classes"]
    assert turn["policy"]["requires_confirmation"] is True
    assert approval_item["turn_id"] == assistant_message["turn_id"]
    assert work_product_item["turn_id"] == assistant_message["turn_id"]
    assert work_product_item["payload"]["approval_id"] == assistant_message["approval"]["id"]


def test_archive_endpoint_hides_conversation_from_default_list_but_keeps_transcript(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-archive-endpoint.db"))
    app = create_app(settings)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={"title": "Archive", "mode": "general"}).json()

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

    archive_response = client.post(f"/v1/conversations/{conversation['id']}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["archived_at"] is not None

    default_list = client.get("/v1/conversations").json()
    archived_list = client.get("/v1/conversations?include_archived=true").json()
    transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()

    assert all(item["id"] != conversation["id"] for item in default_list)
    assert any(item["id"] == conversation["id"] for item in archived_list)
    assert [message["role"] for message in transcript] == ["user", "assistant"]


def test_conversation_detail_and_fork_endpoints_expose_lineage_and_workspace_binding(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-fork-endpoint.db"))
    app = create_app(settings)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={"title": "Fork source", "mode": "research"}).json()

    turn_response = client.post(
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
    assert turn_response.status_code == 200

    conversation_detail = client.get(f"/v1/conversations/{conversation['id']}")
    assert conversation_detail.status_code == 200
    assert conversation_detail.json()["workspace_binding"]["root"] == settings.workspace_root

    source_turns = client.get(f"/v1/conversations/{conversation['id']}/turns").json()
    fork_response = client.post(
        f"/v1/conversations/{conversation['id']}/fork",
        json={"up_to_turn_id": source_turns[0]["id"]},
    )

    assert fork_response.status_code == 200
    forked = fork_response.json()
    assert forked["parent_conversation_id"] == conversation["id"]
    assert forked["forked_from_turn_id"] == source_turns[0]["id"]
    assert forked["workspace_binding"]["isolation"] == "forked"

    forked_transcript = client.get(f"/v1/conversations/{forked['id']}/messages").json()
    assert [message["role"] for message in forked_transcript] == ["user", "assistant"]
    assert forked_transcript[-1]["approval"] is not None


def test_fork_endpoint_can_branch_from_earlier_turn_only(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-fork-partial.db"))
    app = create_app(settings)
    client = TestClient(app)
    conversation = client.post("/v1/conversations", json={"title": "Fork partial", "mode": "research"}).json()

    prompts = [
        "Say hello normally.",
        "Create a report summarizing the current field assistant architecture.",
    ]
    for prompt in prompts:
        response = client.post(
            f"/v1/conversations/{conversation['id']}/turns",
            json={
                "conversation_id": conversation["id"],
                "mode": "research",
                "text": prompt,
                "asset_ids": [],
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {
                    "style": "concise",
                    "citations": True,
                    "audio_reply": False,
                },
            },
        )
        assert response.status_code == 200

    source_turns = client.get(f"/v1/conversations/{conversation['id']}/turns").json()
    fork_response = client.post(
        f"/v1/conversations/{conversation['id']}/fork",
        json={"title": "Branch earlier", "up_to_turn_id": source_turns[0]["id"]},
    )
    assert fork_response.status_code == 200

    forked = fork_response.json()
    forked_turns = client.get(f"/v1/conversations/{forked['id']}/turns").json()
    forked_transcript = client.get(f"/v1/conversations/{forked['id']}/messages").json()

    assert len(forked_turns) == 1
    assert forked["title"] == "Branch earlier"
    assert [message["role"] for message in forked_transcript] == ["user", "assistant"]
    assert forked_transcript[-1]["approval"] is None


def test_rollback_endpoint_archives_source_and_restores_earlier_turn_state(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-rollback-endpoint.db"))
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={"title": "Rollback source", "mode": "research"}).json()

    prompts = [
        "Say hello normally.",
        "Create a report summarizing the current field assistant architecture.",
    ]
    for prompt in prompts:
        response = client.post(
            f"/v1/conversations/{conversation['id']}/turns",
            json={
                "conversation_id": conversation["id"],
                "mode": "research",
                "text": prompt,
                "asset_ids": [],
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {
                    "style": "concise",
                    "citations": True,
                    "audio_reply": False,
                },
            },
        )
        assert response.status_code == 200

    source_turns = client.get(f"/v1/conversations/{conversation['id']}/turns").json()
    rollback_response = client.post(
        f"/v1/conversations/{conversation['id']}/rollback",
        json={"up_to_turn_id": source_turns[0]["id"]},
    )
    assert rollback_response.status_code == 200

    rolled_back = rollback_response.json()
    archived_source = client.get(f"/v1/conversations/{conversation['id']}").json()
    rolled_back_state = client.get(f"/v1/conversations/{rolled_back['id']}/state").json()

    assert archived_source["archived_at"] is not None
    assert rolled_back["title"] == conversation["title"]
    assert rolled_back["parent_conversation_id"] == conversation["id"]
    assert rolled_back["forked_from_turn_id"] == source_turns[0]["id"]
    assert len(rolled_back_state["turns"]) == 1
    assert [message["role"] for message in rolled_back_state["messages"]] == ["user", "assistant"]
    assert "report" not in rolled_back_state["messages"][-1]["content"].lower()
    assert rolled_back_state["messages"][-1]["approval"] is None


def test_compact_and_steer_endpoints_append_thread_ops_to_conversation_state(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-compact-steer-endpoints.db"))
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={"title": "Compact/steer", "mode": "research"}).json()

    turn_response = client.post(
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
    assert turn_response.status_code == 200
    turns = client.get(f"/v1/conversations/{conversation['id']}/turns").json()

    steer_response = client.post(
        f"/v1/conversations/{conversation['id']}/steer",
        json={"instruction": "Keep the thread focused on architecture and product state."},
    )
    compact_response = client.post(
        f"/v1/conversations/{conversation['id']}/compact",
        json={"up_to_turn_id": turns[0]["id"]},
    )

    assert steer_response.status_code == 200
    assert compact_response.status_code == 200
    assert steer_response.json()["kind"] == "steer"
    assert compact_response.json()["kind"] == "compaction_marker"

    state = client.get(f"/v1/conversations/{conversation['id']}/state").json()
    steer_item = next(item for item in state["items"] if item["kind"] == "steer")
    compact_item = next(item for item in state["items"] if item["kind"] == "compaction_marker")

    assert steer_item["payload"]["instruction"] == "Keep the thread focused on architecture and product state."
    assert compact_item["payload"]["up_to_turn_id"] == turns[0]["id"]
    assert "pending draft" in compact_item["payload"]["summary"].lower()


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
    app = create_app(settings)
    client = TestClient(app)
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

    app.state.container.store.create_conversation_memory(
        ConversationMemoryEntry(
            id=new_id("memory"),
            conversation_id=conversation["id"],
            turn_id="turn_memory",
            kind=ConversationMemoryKind.GENERAL,
            topic="Deletion test memory",
            summary="This memory should disappear when the conversation is deleted.",
            keywords=["deletion", "memory"],
            source_domain=SourceDomain.CONVERSATION,
        )
    )
    assert app.state.container.store.list_conversation_memories(conversation["id"])

    delete_response = client.delete(f"/v1/conversations/{conversation['id']}")
    assert delete_response.status_code == 204
    assert delete_response.text == ""

    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 404

    conversations_response = client.get("/v1/conversations")
    assert conversations_response.status_code == 200
    conversations = conversations_response.json()
    assert all(item["id"] != conversation["id"] for item in conversations)
    assert app.state.container.store.list_conversation_memories(conversation["id"]) == []


def test_turn_persists_conversation_memory_entry(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-memory-persist.db"))
    app = create_app(settings)
    client = TestClient(app)
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Memory", "mode": "field"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "field",
            "text": "Teach me how to explain oral rehydration solution simply.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    memories = app.state.container.store.list_conversation_memories(conversation["id"])
    assert memories
    assert memories[0].kind == ConversationMemoryKind.TEACHING
    assert memories[0].summary


def test_follow_up_can_use_selected_conversation_memory_after_topic_pivot(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-memory-follow-up.db"))
    app = create_app(settings)
    client = TestClient(app)
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Memory follow up", "mode": "general"},
    ).json()
    store = app.state.container.store

    store.append_transcript(
        conversation["id"],
        "user",
        "Explain the architecture direction plainly.",
        turn_id="turn_seed_user",
    )
    store.append_transcript(
        conversation["id"],
        "assistant",
        "The main direction is one orchestrator with grounded specialist routes and explicit approvals.",
        turn_id="turn_seed_assistant",
    )
    store.append_transcript(
        conversation["id"],
        "user",
        "Separate tangent about lunch.",
        turn_id="turn_pivot_user",
    )
    store.append_transcript(
        conversation["id"],
        "assistant",
        "We can talk about lunch too.",
        turn_id="turn_pivot_assistant",
    )
    store.create_conversation_memory(
        ConversationMemoryEntry(
            id=new_id("memory"),
            conversation_id=conversation["id"],
            turn_id="turn_seed_assistant",
            kind=ConversationMemoryKind.GENERAL,
            topic="Architecture direction",
            summary="Keep one orchestrator with grounded specialist routes and explicit approvals.",
            keywords=["architecture", "orchestrator", "approvals"],
            source_domain=SourceDomain.CONVERSATION,
        )
    )
    store.create_conversation_memory(
        ConversationMemoryEntry(
            id=new_id("memory"),
            conversation_id=conversation["id"],
            turn_id="turn_pivot_assistant",
            kind=ConversationMemoryKind.GENERAL,
            topic="Lunch tangent",
            summary="We switched to a short aside about lunch and coffee.",
            keywords=["lunch", "coffee"],
            source_domain=SourceDomain.CONVERSATION,
        )
    )

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "general",
            "text": "Can we go back to that architecture point again?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    assert "one orchestrator" in response.text.lower()
    assert "grounded specialist routes" in response.text.lower()


def test_teaching_follow_ups_keep_using_grounded_base_memory_after_short_paraphrase_turns(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-teaching-followups.db"))
    app = create_app(settings)
    client = TestClient(app)
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Teaching follow ups", "mode": "research"},
    ).json()

    turns = [
        "Teach me how to prepare oral rehydration solution in the field.",
        "What should I emphasize first to a volunteer with no medical training?",
        "Separate tangent about lunch and coffee for a second.",
        "Can we go back to that oral rehydration point again?",
        "If I had to say that in one sentence, how would you put it?",
        "What should make me stop and escalate?",
    ]

    completed_texts: list[str] = []
    for text in turns:
        response = client.post(
            f"/v1/conversations/{conversation['id']}/turns",
            json={
                "conversation_id": conversation["id"],
                "mode": "research",
                "text": text,
                "asset_ids": [],
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
            },
        )
        assert response.status_code == 200
        completed = next(
            json.loads(line)
            for line in response.text.splitlines()
            if '"type":"assistant.message.completed"' in line
        )
        completed_texts.append(completed["payload"]["text"])

    assert "earlier we were talking about how to prepare oral rehydration solution in the field" in completed_texts[3].lower()
    assert completed_texts[4].lower().startswith("in one sentence:")
    assert "grounded in [ors guidance]" in completed_texts[4].lower()
    assert (
        "stop and escalate if you see worsening weakness, confusion, or inability to drink"
        in completed_texts[5].lower()
    )
    assert "leave that aside for a minute" in completed_texts[2].lower()
    assert "talk about lunch and coffee" in completed_texts[2].lower()
    assert "new main thread" not in completed_texts[2].lower()

    memories = app.state.container.store.list_conversation_memories(conversation["id"])
    memory_summaries = [memory.summary.lower() for memory in memories]
    assert not any(summary.startswith("in one sentence:") for summary in memory_summaries)
    assert not any("stop and escalate if you see" in summary for summary in memory_summaries)


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
    approval = approval_response.json()
    assert approval["status"] == "executed"
    assert approval["item"]["kind"] == "approval"
    assert approval["item"]["payload"]["approval"]["status"] == "executed"
    assert approval["run"] is None

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
    assert approval_response.json()["item"]["payload"]["approval"]["status"] == "executed"

    items_response = client.get(f"/v1/conversations/{conversation['id']}/items")
    assert items_response.status_code == 200
    approval_items = [item for item in items_response.json() if item["kind"] == "approval"]
    assert approval_items
    latest_approval = approval_items[-1]["payload"]["approval"]
    assert latest_approval["id"] == approval_id
    assert latest_approval["status"] == "executed"

    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 200
    assistant_message = next(
        message for message in transcript_response.json() if message["role"] == "assistant"
    )
    assert assistant_message["approval"]["id"] == approval_id
    assert assistant_message["approval"]["status"] == "executed"


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
    assert approval_payload["payload"]["payload"]["title"] == "Field Assistant Architecture Report"
    completed_event = next(line for line in lines if '"type":"assistant.message.completed"' in line)
    completed_payload = json.loads(completed_event)
    assert completed_payload["payload"]["text"] == "I drafted a report here."
    approval_id = approval_payload["payload"]["id"]

    decision = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"action": "approve", "edited_payload": {}},
    )

    assert decision.status_code == 200
    approval = decision.json()
    assert approval["status"] == "executed"
    assert approval["result"]["entity_type"] == "report"
    assert approval["result"]["kind"] == "report"

    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()


def test_pending_report_follow_up_can_update_same_report_before_save(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-pending-report-follow-up.db"))
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={"title": "Report follow up", "mode": "research"}).json()

    first = client.post(
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
    assert first.status_code == 200

    follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Keep the same report, but make it shorter before I save it.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert follow_up.status_code == 200

    lines = [json.loads(line) for line in follow_up.text.splitlines() if line.strip()]
    completed = next(line for line in lines if line["type"] == "assistant.message.completed")
    approval_event = next(line for line in lines if line["type"] == "approval.required")
    text = completed["payload"]["text"].lower()
    payload = approval_event["payload"]["payload"]

    assert 'i updated the report "field assistant architecture report"' in text
    assert "what are the key sections you want to keep" not in text
    assert "## Summary" not in str(payload["content"])
    assert "Key points:" in str(payload["content"])
    assert "tighten or retitle the draft" not in str(payload["content"]).lower()

    transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
    original_assistant = next(
        message
        for message in transcript
        if message["role"] == "assistant" and message["content"] == "I drafted a report here."
    )
    latest_assistant = next(
        message
        for message in transcript
        if message["role"] == "assistant"
        and 'I updated the report "Field Assistant Architecture Report" here.' in message["content"]
    )

    assert original_assistant.get("approval") is None
    assert latest_assistant.get("approval") is not None
    assert latest_assistant["approval"]["id"] == approval_event["payload"]["id"]
    assert (
        latest_assistant["approval"]["payload"]["content"]
        == approval_event["payload"]["payload"]["content"]
    )

    items_response = client.get(f"/v1/conversations/{conversation['id']}/items")
    assert items_response.status_code == 200
    approval_items = [item for item in items_response.json() if item["kind"] == "approval"]
    assert approval_items
    latest_approval_item = approval_items[-1]
    assert latest_approval_item["payload"]["approval"]["id"] == approval_event["payload"]["id"]
    assert latest_approval_item["payload"]["approval"]["turn_id"] == latest_assistant["turn_id"]
    assert (
        latest_approval_item["payload"]["approval"]["payload"]["content"]
        == approval_event["payload"]["payload"]["content"]
    )


def test_selected_canvas_text_edit_updates_pending_approval_and_items(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-selected-canvas-edit.db"))
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations", json={"title": "Selected canvas edit", "mode": "research"}
    ).json()

    first = client.post(
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
    assert first.status_code == 200
    first_lines = [json.loads(line) for line in first.text.splitlines() if line.strip()]
    initial_approval = next(line for line in first_lines if line["type"] == "approval.required")
    approval_id = initial_approval["payload"]["id"]

    selected_text = "We must make the strongest claims immediately."
    visible_content = "\n".join(
        [
            "Field Assistant Architecture Report",
            "",
            "Local canvas edit: keep this concise, plain, and human.",
            "",
            selected_text,
        ]
    )
    start = visible_content.index(selected_text)
    revised = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "make this selection more neutral",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
            "canvas_selection": {
                "approval_id": approval_id,
                "field_name": "content",
                "start": start,
                "end": start + len(selected_text),
                "text": selected_text,
                "visible_content": visible_content,
                "action": "neutral",
                "current_payload": {
                    "title": "Field Assistant Architecture Report",
                    "kind": "report",
                    "content": visible_content,
                },
            },
        },
    )
    assert revised.status_code == 200

    revised_lines = [json.loads(line) for line in revised.text.splitlines() if line.strip()]
    document_edit_event = next(line for line in revised_lines if line["type"] == "document.edited")
    completed = next(line for line in revised_lines if line["type"] == "assistant.message.completed")
    approval_event = next(line for line in revised_lines if line["type"] == "approval.required")
    payload = approval_event["payload"]["payload"]

    assert document_edit_event["payload"]["approval_id"] == approval_id
    assert document_edit_event["payload"]["item"]["kind"] == "document_edit"
    assert document_edit_event["payload"]["item"]["turn_id"] == document_edit_event["turn_id"]
    assert document_edit_event["payload"]["before_text"] == selected_text
    assert document_edit_event["payload"]["after_text"] == (
        "We should make the best-supported points soon."
    )
    assert (
        document_edit_event["payload"]["item"]["payload"]["visible_content_before"]
        == visible_content
    )
    assert "We should make the best-supported points soon." in (
        document_edit_event["payload"]["item"]["payload"]["visible_content_after"]
    )
    assert approval_event["payload"]["id"] == approval_id
    assert "selected draft text in the canvas" in completed["payload"]["text"].lower()
    assert "We should make the best-supported points soon." in payload["content"]
    assert selected_text not in payload["content"]
    assert "Local canvas edit: keep this concise, plain, and human." in payload["content"]
    assert approval_event["payload"]["item"]["kind"] == "approval"
    assert approval_event["payload"]["work_product_item"]["kind"] == "work_product"
    assert (
        approval_event["payload"]["work_product_item"]["payload"]["work_product"]["content"]
        == payload["content"]
    )

    items = client.get(f"/v1/conversations/{conversation['id']}/items").json()
    document_edit_item = next(item for item in items if item["kind"] == "document_edit")
    assert document_edit_item["id"] == document_edit_event["payload"]["item"]["id"]
    assert document_edit_item["payload"]["payload_after"]["content"] == payload["content"]
    assert document_edit_item["payload"]["payload_before"]["content"] == visible_content

    transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
    latest_assistant = next(
        message for message in reversed(transcript) if message["role"] == "assistant"
    )
    assert latest_assistant["content"] == completed["payload"]["text"]
    assert latest_assistant["approval"]["id"] == approval_id
    assert latest_assistant["approval"]["payload"]["content"] == payload["content"]


def test_conversation_state_endpoint_reanchors_pending_approval_to_latest_revision_turn(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-conversation-state-approval-owner.db"))
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={"title": "State owner", "mode": "research"}).json()

    first = client.post(
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
    assert first.status_code == 200

    follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Keep the same report, but make it shorter before I save it.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert follow_up.status_code == 200

    snapshot_response = client.get(f"/v1/conversations/{conversation['id']}/state")
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()

    original_assistant = next(
        message
        for message in snapshot["messages"]
        if message["role"] == "assistant" and message["content"] == "I drafted a report here."
    )
    latest_assistant = next(
        message
        for message in snapshot["messages"]
        if message["role"] == "assistant"
        and 'I updated the report "Field Assistant Architecture Report" here.' in message["content"]
    )
    latest_turn = next(turn for turn in snapshot["turns"] if turn["id"] == latest_assistant["turn_id"])
    latest_approval_item = [
        item for item in snapshot["items"] if item["kind"] == "approval"
    ][-1]

    assert original_assistant.get("approval") is None
    assert latest_assistant.get("approval") is not None
    assert latest_assistant["approval"]["id"] == latest_approval_item["payload"]["approval"]["id"]
    assert latest_approval_item["payload"]["approval"]["turn_id"] == latest_assistant["turn_id"]
    assert latest_turn["assistant_message_id"] == latest_assistant["id"]
    assert (
        latest_assistant["approval"]["payload"]["content"]
        == latest_approval_item["payload"]["approval"]["payload"]["content"]
    )


def test_items_endpoint_exposes_full_pending_approval_snapshot_for_canvas_ownership(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-approval-item-snapshot.db"))
    client = TestClient(create_app(settings))
    conversation = client.post("/v1/conversations", json={"title": "Snapshot", "mode": "research"}).json()

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
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    approval_event = next(line for line in lines if line["type"] == "approval.required")

    items_response = client.get(f"/v1/conversations/{conversation['id']}/items")
    assert items_response.status_code == 200
    approval_item = next(item for item in items_response.json() if item["kind"] == "approval")

    assert approval_item["payload"]["approval_id"] == approval_event["payload"]["id"]
    assert approval_item["payload"]["approval"]["id"] == approval_event["payload"]["id"]
    assert approval_item["payload"]["approval"]["turn_id"] == approval_event["payload"]["turn_id"]
    assert (
        approval_item["payload"]["approval"]["payload"]["content"]
        == approval_event["payload"]["payload"]["content"]
    )


def test_pending_report_survives_casual_interruptions_before_save(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-pending-report-casual-interruptions.db"))
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations", json={"title": "Report casual interruptions", "mode": "research"}
    ).json()

    create_turn = client.post(
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
    assert create_turn.status_code == 200
    create_lines = [json.loads(line) for line in create_turn.text.splitlines() if line.strip()]
    create_completed = next(line for line in create_lines if line["type"] == "assistant.message.completed")
    create_approval = next(line for line in create_lines if line["type"] == "approval.required")
    initial_approval_id = create_approval["payload"]["id"]

    thanks_turn = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Thanks",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert thanks_turn.status_code == 200
    thanks_lines = [json.loads(line) for line in thanks_turn.text.splitlines() if line.strip()]
    thanks_completed = next(line for line in thanks_lines if line["type"] == "assistant.message.completed")
    assert thanks_completed["payload"]["text"] == "Of course. I'm here when you want to keep going."
    assert thanks_completed["payload"]["models"]["assistant_backend"] == "deterministic"
    assert not any(line["type"] == "approval.required" for line in thanks_lines)

    yoo_turn = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "yoo",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert yoo_turn.status_code == 200
    yoo_lines = [json.loads(line) for line in yoo_turn.text.splitlines() if line.strip()]
    yoo_completed = next(line for line in yoo_lines if line["type"] == "assistant.message.completed")
    assert yoo_completed["payload"]["text"] == "Hey. What's up?"
    assert yoo_completed["payload"]["models"]["assistant_backend"] == "deterministic"
    assert not any(line["type"] == "approval.required" for line in yoo_lines)

    revise_turn = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Keep the same report, but make it shorter before I save it.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert revise_turn.status_code == 200
    revise_lines = [json.loads(line) for line in revise_turn.text.splitlines() if line.strip()]
    revise_completed = next(line for line in revise_lines if line["type"] == "assistant.message.completed")
    revise_approval = next(line for line in revise_lines if line["type"] == "approval.required")
    assert 'i updated the report "field assistant architecture report"' in revise_completed["payload"]["text"].lower()
    assert revise_completed["payload"]["models"]["assistant_backend"] == "deterministic"
    assert revise_approval["payload"]["id"] == initial_approval_id

    transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
    assistant_messages = [message for message in transcript if message["role"] == "assistant"]
    assert assistant_messages[0]["content"] == create_completed["payload"]["text"]
    assert assistant_messages[0].get("approval") is None
    assert assistant_messages[1]["content"] == "Of course. I'm here when you want to keep going."
    assert assistant_messages[1].get("approval") is None
    assert assistant_messages[2]["content"] == "Hey. What's up?"
    assert assistant_messages[2].get("approval") is None
    assert assistant_messages[3]["content"] == revise_completed["payload"]["text"]
    assert assistant_messages[3]["approval"]["id"] == initial_approval_id


def test_pending_report_can_shorten_again_after_conversational_detours(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-pending-report-repeat-tighten.db"))
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations", json={"title": "Repeat tighten after detours", "mode": "research"}
    ).json()

    create_turn = client.post(
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
    assert create_turn.status_code == 200
    create_lines = [json.loads(line) for line in create_turn.text.splitlines() if line.strip()]
    initial_approval = next(line for line in create_lines if line["type"] == "approval.required")
    approval_id = initial_approval["payload"]["id"]

    for text in [
        "Thanks",
        "Can we just talk normally for a second?",
        "What do you mean by that?",
        "What is that report called?",
        "Okay, go back to that report. What's the main point in one sentence?",
    ]:
        response = client.post(
            f"/v1/conversations/{conversation['id']}/turns",
            json={
                "conversation_id": conversation["id"],
                "mode": "research",
                "text": text,
                "asset_ids": [],
                "enabled_knowledge_pack_ids": [],
                "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
            },
        )
        assert response.status_code == 200

    first_shorten = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Keep the same report, but make it shorter before I save it.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert first_shorten.status_code == 200
    first_lines = [json.loads(line) for line in first_shorten.text.splitlines() if line.strip()]
    first_approval = next(line for line in first_lines if line["type"] == "approval.required")
    first_content = str(first_approval["payload"]["payload"]["content"])
    assert first_approval["payload"]["id"] == approval_id

    second_shorten = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Keep the same report, but shorten it even more.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert second_shorten.status_code == 200
    second_lines = [json.loads(line) for line in second_shorten.text.splitlines() if line.strip()]
    second_completed = next(line for line in second_lines if line["type"] == "assistant.message.completed")
    second_approval = next(line for line in second_lines if line["type"] == "approval.required")
    second_text = second_completed["payload"]["text"].lower()
    second_content = str(second_approval["payload"]["payload"]["content"])

    assert 'i updated the report "field assistant architecture report"' in second_text
    assert "need to know what aspect you want to prioritize" not in second_text
    assert "please specify" not in second_text
    assert second_approval["payload"]["id"] == approval_id
    assert second_content != first_content
    assert len(second_content) < len(first_content)

    transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
    latest_assistant = next(
        message
        for message in reversed(transcript)
        if message["role"] == "assistant"
    )
    assert latest_assistant["content"] == second_completed["payload"]["text"]
    assert latest_assistant["approval"]["id"] == approval_id
    assert latest_assistant["approval"]["payload"]["content"] == second_content


def test_message_draft_turn_after_image_blocks_when_current_grounding_is_unavailable(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "test-message-draft-approval.db"))
    app = create_app(settings)

    class FlakyVisionRuntime:
        backend_name = "fake-vision"

        def __init__(self) -> None:
            self.calls = 0

        def analyze(self, request):
            self.calls += 1
            if self.calls <= 2:
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
            return VisionAnalysisResult(
                text="No local vision specialist model is available for this follow-up turn.",
                backend="metadata",
                model_name=request.specialist_model_name,
                model_source=None,
                available=False,
                unavailable_reason="No local vision specialist model is available.",
            )

    app.state.container.orchestrator.vision_runtime = FlakyVisionRuntime()
    client = TestClient(app)
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
            "text": "What shortages stand out in this image? Give me the main shortages first and then the first two actions you would prioritize.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )
    assert second_turn.status_code == 200

    third_turn = client.post(
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
    assert third_turn.status_code == 200
    lines = [line for line in third_turn.text.splitlines() if line.strip()]
    assert not any('"type":"approval.required"' in line for line in lines)
    completed_event = next(line for line in lines if '"type":"assistant.message.completed"' in line)
    completed_payload = json.loads(completed_event)
    text = completed_payload["payload"]["text"].lower()
    assert "need current grounded local evidence" in text or "need stronger grounded evidence" in text

    transcript_response = client.get(f"/v1/conversations/{conversation['id']}/messages")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()
    assistant_message = transcript[-1]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["turn_id"]
    assert assistant_message.get("approval") is None


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

    turns = client.get(f"/v1/conversations/{conversation['id']}/turns").json()
    assert len(turns) == 1
    assert turns[0]["policy"]["approval_mode"] == "medical_strict"
    assert turns[0]["policy"]["approval_category"] == "medical_specialist"
    assert "medical_specialist" in turns[0]["policy"]["permission_classes"]
    assert turns[0]["policy"]["requires_confirmation"] is True


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
    assert completed_event["payload"]["item"]["kind"] == "tool_result"
    assert completed_event["payload"]["item"]["payload"]["tool_name"] == "generate_heatmap_overlay"
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

    items_response = client.get(f"/v1/conversations/{conversation['id']}/items")
    assert items_response.status_code == 200
    items = items_response.json()
    assert any(item["kind"] == "tool_proposal" for item in items)
    assert any(item["kind"] == "tool_result" for item in items)


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


def test_capabilities_endpoint_marks_ffmpeg_profile_as_fallback_only(tmp_path: Path) -> None:
    settings = Settings(
        database_path=str(tmp_path / "test-capabilities-ffmpeg.db"),
        workspace_root=str(tmp_path),
        tracking_backend="ffmpeg",
    )
    client = TestClient(create_app(settings))

    response = client.get("/v1/system/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tracking_backend"] == "ffmpeg"
    assert payload["tracking_execution_available"] is False
    assert payload["isolation_execution_available"] is False
    assert payload["video_analysis_fallback_only"] is True


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
    assert "just talk this through" in response.text.lower()
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
    assert "keep it conversational" in first.text.lower()
    assert "rough shape" in first.text.lower()

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
    assert "keep it conversational" in second.text.lower()

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


def test_thread_steering_biases_workspace_run_and_streams_agent_run_items(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-assistant-architecture.md").write_text(
        "Local-first assistant built on Gemma.\nUses bounded routing and explicit approvals.\n",
        encoding="utf-8",
    )
    (workspace_root / "trip-checklist.md").write_text(
        "Pack batteries.\nConfirm translator contact sheet before departure.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-steered-workspace-run.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Steered workspace run", "mode": "research"},
    ).json()

    steer_response = client.post(
        f"/v1/conversations/{conversation['id']}/steer",
        json={"instruction": "Keep the thread focused on architecture and product state."},
    )
    assert steer_response.status_code == 200

    response = client.post(
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

    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    agent_status = next(
        line
        for line in lines
        if line["type"] == "turn.status"
        and isinstance(line["payload"].get("item"), dict)
        and line["payload"]["item"]["kind"] == "agent_run"
    )
    approval_event = next(line for line in lines if line["type"] == "approval.required")

    assert agent_status["payload"]["item"]["payload"]["status"] in {
        "running",
        "awaiting_approval",
        "completed",
        "blocked",
        "failed",
    }
    assert (
        agent_status["payload"]["item"]["payload"]["run"]["goal"]
        == agent_status["payload"]["run"]["goal"]
    )
    assert "Local-first assistant built on Gemma" in approval_event["payload"]["payload"]["content"]

    runs = client.get(f"/v1/conversations/{conversation['id']}/runs").json()
    assert len(runs) == 1
    assert "Thread steering: Keep the thread focused on architecture and product state." in runs[0]["goal"]


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
    assert approval["item"]["payload"]["approval"]["status"] == "executed"
    assert approval["work_product_item"]["kind"] == "work_product"
    assert approval["work_product_item"]["payload"]["approval"]["status"] == "executed"
    assert approval["work_product_item"]["payload"]["work_product"]["title"] == "Edited workspace briefing"
    assert approval["run"]["status"] == "completed"

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


def test_grounded_approval_edit_rejects_unrelated_overwrite_and_stays_pending(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-assistant-architecture.md").write_text(
        "Field Assistant Architecture Overview\n"
        "- Local-first assistant built on Gemma.\n"
        "- Uses bounded routing, retrieval, vision, and approvals.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-grounded-approval-guardrail.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Grounded Edit", "mode": "research"},
    ).json()

    response = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Prepare a short workspace briefing about the current field assistant architecture.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "concise", "citations": True, "audio_reply": False},
        },
    )

    assert response.status_code == 200
    lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    approval_event = next(line for line in lines if line["type"] == "approval.required")
    approval_id = approval_event["payload"]["id"]

    decision_response = client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={
            "action": "approve",
            "edited_payload": {
                "title": "Weekend errands",
                "content": "Shopping list\n- Buy oranges\n- Fix the porch light\n",
            },
        },
    )

    assert decision_response.status_code == 400
    assert "grounded in earlier local workspace evidence" in decision_response.json()["detail"]

    transcript = client.get(f"/v1/conversations/{conversation['id']}/messages").json()
    assert transcript[-1]["approval"]["status"] == "pending"

    notes_response = client.get("/v1/notes")
    assert notes_response.status_code == 200
    assert notes_response.json() == []


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
    assert "i updated the markdown export" in tighten_text.lower()
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


def test_same_type_output_recall_can_resolve_first_report_by_ordinal(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-assistant-architecture.md").write_text(
        "Field Assistant architecture overview\n"
        "Local-first assistant built on Gemma.\n"
        "Uses bounded routing and approvals.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-first-report-recall.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "First Report Recall", "mode": "research"},
    ).json()

    first_report = client.post(
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
    first_lines = [json.loads(line) for line in first_report.text.splitlines() if line.strip()]
    first_approval = next(line for line in first_lines if line["type"] == "approval.required")
    client.post(
        f"/v1/approvals/{first_approval['payload']['id']}/decisions",
        json={"action": "approve", "edited_payload": {"title": "Architecture baseline report"}},
    )

    second_report = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Create another report summarizing the current field assistant architecture.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    second_lines = [json.loads(line) for line in second_report.text.splitlines() if line.strip()]
    second_approval = next(line for line in second_lines if line["type"] == "approval.required")
    client.post(
        f"/v1/approvals/{second_approval['payload']['id']}/decisions",
        json={"action": "approve", "edited_payload": {"title": "Architecture follow-up report"}},
    )

    follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "What was in the first report again?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert follow_up.status_code == 200
    completed = next(
        json.loads(line)
        for line in follow_up.text.splitlines()
        if '"type":"assistant.message.completed"' in line
    )
    text = completed["payload"]["text"]
    assert "Architecture baseline report" in text
    assert "Architecture follow-up report" not in text


def test_saved_checklist_title_follow_up_answers_directly(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "test-saved-checklist-title.db"))
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Saved checklist title", "mode": "research"},
    ).json()

    checklist = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Create a checklist from those two shortages for tomorrow morning.",
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
                "content": "- Pack lantern batteries\n- Refill translator phone credits",
            },
        },
    )

    follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "What is that checklist called?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )

    assert follow_up.status_code == 200
    completed = next(
        json.loads(line)
        for line in follow_up.text.splitlines()
        if '"type":"assistant.message.completed"' in line
    )
    text = completed["payload"]["text"]
    assert "Departure shortage checklist" in text
    assert "next step practical" not in text.lower()
    assert "talk normally" not in text.lower()


def test_saved_export_title_follow_up_answers_directly(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-assistant-architecture.md").write_text(
        "Field Assistant architecture overview\n"
        "Local-first assistant built on Gemma.\n"
        "Uses bounded routing and approvals.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-saved-export-title.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Saved export title", "mode": "research"},
    ).json()

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
        json={"action": "approve", "edited_payload": {"title": "Field Assistant Architecture Briefing"}},
    )

    follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "What's the export title now?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )

    assert follow_up.status_code == 200
    completed = next(
        json.loads(line)
        for line in follow_up.text.splitlines()
        if '"type":"assistant.message.completed"' in line
    )
    text = completed["payload"]["text"]
    assert "Field Assistant Architecture Briefing" in text
    assert "next step practical" not in text.lower()
    assert "talk normally" not in text.lower()


def test_saved_export_topic_reentry_answers_from_saved_export_content(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "field-assistant-architecture.md").write_text(
        "Field Assistant architecture overview\n"
        "Local-first assistant built on Gemma.\n"
        "Uses bounded routing, retrieval, vision, and approvals.\n",
        encoding="utf-8",
    )

    settings = Settings(
        database_path=str(tmp_path / "test-saved-export-topic-reentry.db"),
        workspace_root=str(workspace_root),
    )
    client = TestClient(create_app(settings))
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Saved export recall", "mode": "research"},
    ).json()

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
        json={"action": "approve", "edited_payload": {"title": "Field Assistant Architecture Brief"}},
    )

    title_turn = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "What's the export title now?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert title_turn.status_code == 200

    follow_up = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "research",
            "text": "Go back to that architecture point again.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )

    assert follow_up.status_code == 200
    completed = next(
        json.loads(line)
        for line in follow_up.text.splitlines()
        if '"type":"assistant.message.completed"' in line
    )
    text = completed["payload"]["text"].lower()
    assert "field assistant architecture brief" in text
    assert "local-first assistant built on gemma" in text
    assert "bounded routing" in text
    assert "we can stay with what we were just discussing" not in text


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

    assert "just talk this through" in turn_responses[0].lower()
    assert "ors guidance" in turn_responses[1].lower()
    assert "most practical first point" in turn_responses[2].lower()
    assert "from the image" in turn_responses[3].lower()
    assert "lantern batteries low" in turn_responses[3].lower()
    assert "two clearest shortages" in turn_responses[4].lower()
    assert "translator phone credits" in turn_responses[4].lower()
    assert "just talk this through" in turn_responses[5].lower()
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


def test_checklist_follow_up_reuses_earlier_image_summary_when_current_vision_is_unavailable(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=str(tmp_path / "test-checklist-from-context.db"),
        asset_storage_dir=str(tmp_path / "uploads"),
        specialist_backend="mock",
    )
    app = create_app(settings)

    class FlakyVisionRuntime:
        backend_name = "fake-vision"

        def __init__(self) -> None:
            self.calls = 0

        def analyze(self, request):
            self.calls += 1
            if self.calls <= 2:
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
            return VisionAnalysisResult(
                text="No local vision specialist model is available for this follow-up turn.",
                backend="metadata",
                model_name=request.specialist_model_name,
                model_source=None,
                available=False,
                unavailable_reason="No local vision specialist model is available.",
            )

    app.state.container.orchestrator.vision_runtime = FlakyVisionRuntime()
    client = TestClient(app)

    image_asset = client.post(
        "/v1/assets/upload",
        data={"care_context": "general"},
        files={"file": ("board.png", _tiny_png_bytes(), "image/png")},
    ).json()["asset"]
    conversation = client.post(
        "/v1/conversations",
        json={"title": "Checklist from context", "mode": "field"},
    ).json()

    describe = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "field",
            "text": "Describe the attached supply image conservatively.",
            "asset_ids": [image_asset["id"]],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert describe.status_code == 200
    assert "lantern batteries low" in describe.text.lower()

    shortages = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "field",
            "text": "Which two shortages matter most before departure?",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert shortages.status_code == 200

    checklist = client.post(
        f"/v1/conversations/{conversation['id']}/turns",
        json={
            "conversation_id": conversation["id"],
            "mode": "field",
            "text": "Create a checklist for tomorrow's departure based on the supply board shortages.",
            "asset_ids": [],
            "enabled_knowledge_pack_ids": [],
            "response_preferences": {"style": "normal", "citations": True, "audio_reply": False},
        },
    )
    assert checklist.status_code == 200
    checklist_lines = [json.loads(line) for line in checklist.text.splitlines() if line.strip()]
    approval = next(line for line in checklist_lines if line["type"] == "approval.required")
    payload = approval["payload"]["payload"]

    assert "Restock lantern batteries" in payload["content"]
    assert "Top up translator phone credits" in payload["content"]
    assert "Confirm destination and route" not in payload["content"]


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
    assert "oral rehydration salts" not in completed_texts[3].lower()
    assert "translator contact sheet" not in completed_texts[3].lower()
    assert "pit edge" not in completed_texts[6].lower()
    assert "field assistant architecture brief" not in completed_texts[6].lower()
    assert "lantern batteries" in completed_texts[7].lower()
    assert "pit edge" not in completed_texts[7].lower()


def test_long_horizon_mixed_conversation_keeps_earlier_image_after_history_cutoff(
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
        database_path=str(tmp_path / "test-long-horizon-mixed-context.db"),
        workspace_root=str(workspace_root),
        asset_storage_dir=str(tmp_path / "uploads"),
        specialist_backend="mock",
        tracking_backend="mock",
        continuity_history_limit=16,
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
        json={"title": "Long horizon mixed context", "mode": "research"},
    ).json()

    turns = [
        ("Hey, can we talk normally while you help me think through field work?", []),
        ("Teach me how to prepare oral rehydration solution in the field.", []),
        ("What should I emphasize first to a volunteer with no medical training?", []),
        ("Separate tangent about lunch and coffee for a second.", []),
        ("Can we go back to that oral rehydration point again?", []),
        ("If I had to say that in one sentence, how would you put it?", []),
        ("What should make me stop and escalate?", []),
        ("Describe the attached supply image conservatively.", [image_asset["id"]]),
        ("Which two shortages matter most before departure?", []),
        ("Create a checklist from those two shortages for tomorrow morning.", []),
        ("What is that checklist called?", []),
        ("Thanks", []),
        ("yoo", []),
        ("Actually just talk normally with me for a second.", []),
        ("Review the attached mining video conservatively.", [video_asset["id"]]),
        ("Summarize what stands out in that video, but keep it cautious.", []),
        ("Create a short report from that video review.", []),
        ("What is the report called?", []),
        ("Prepare a short workspace briefing about the current field assistant architecture and export it as markdown.", []),
        ("What's the export title now?", []),
        ("Go back to that architecture point again.", []),
        ("What was in that checklist again?", []),
        ("What was in the report again?", []),
        ("Compare the report title and export title for me.", []),
        (
            "Actually, forget the report for a second. "
            "What's the real difference between memory and context here?",
            [],
        ),
        ("Go back to the earlier image for a second. Which shortage mattered most?", []),
    ]

    completed_texts: list[str] = []
    pending_tool_names: list[str] = []
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
        completed_line = next(
            json.loads(line)
            for line in response.text.splitlines()
            if '"type":"assistant.message.completed"' in line
        )
        completed_texts.append(completed_line["payload"]["text"])
        approval_line = next(
            (
                json.loads(line)["payload"]
                for line in response.text.splitlines()
                if '"type":"approval.required"' in line
            ),
            None,
        )
        if approval_line is not None:
            pending_tool_names.append(approval_line["tool_name"])
            edited_payload: dict[str, str] = {}
            if approval_line["tool_name"] == "create_checklist":
                edited_payload = {
                    "title": "Departure shortage checklist",
                    "content": "- Pack lantern batteries\n- Refill translator phone credits\n",
                }
            elif approval_line["tool_name"] == "create_report":
                edited_payload = {
                    "title": "Mining Video Review Report",
                    "content": (
                        "Mining Video Review Report\n\n"
                        "Key points:\n"
                        "- Workers are visible near excavation equipment.\n"
                        "- The review remains conservative and sampled-frame based.\n"
                    ),
                }
            elif approval_line["tool_name"] == "export_brief":
                edited_payload = {
                    "title": "Field Assistant Architecture Brief",
                    "content": (
                        "Field Assistant Architecture Brief\n\n"
                        "Key points:\n"
                        "- Local-first assistant built on Gemma.\n"
                        "- Uses bounded routing, retrieval, vision, and approvals.\n"
                    ),
                }
            decision = client.post(
                f"/v1/approvals/{approval_line['id']}/decisions",
                json={"action": "approve", "edited_payload": edited_payload},
            )
            assert decision.status_code == 200

    assert pending_tool_names == ["create_checklist", "export_brief"]
    assert completed_texts[11] == "Of course. I'm here when you want to keep going."
    assert completed_texts[12] == "Hey. What's up?"
    assert "leave that aside for a minute" in completed_texts[3].lower()
    assert "talk about lunch and coffee" in completed_texts[3].lower()
    assert "new main thread" not in completed_texts[3].lower()
    assert "field assistant architecture brief" in completed_texts[20].lower()
    assert "there is no current report yet" in completed_texts[22].lower()
    assert "context is the live working set" in completed_texts[24].lower()
    assert "memory is older distilled state" in completed_texts[24].lower()
    assert "mining video review report" not in completed_texts[24].lower()
    assert "field assistant architecture brief" not in completed_texts[24].lower()
    assert "lantern batteries" in completed_texts[25].lower()
    assert "pit edge" not in completed_texts[25].lower()
    assert "mining clip" not in completed_texts[25].lower()


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
    assert "checklist" in text
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
