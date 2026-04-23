from pathlib import Path

from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import (
    AgentRunStatus,
    ApprovalCategory,
    ApprovalMode,
    AssistantMode,
    ConversationCompactRequest,
    ConversationCreateRequest,
    ConversationForkRequest,
    ConversationSteerRequest,
    ConversationRollbackRequest,
    ConversationItemKind,
    ConversationTurnRecord,
    PermissionClass,
    RuntimeProfile,
    SandboxMode,
    TurnExecutionPolicy,
    WorkspaceBinding,
    WorkspaceIsolationMode,
    new_id,
)


def test_conversation_persists_across_container_rebuilds(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "persist.db"))

    container = build_container(settings)
    created = container.store.create_conversation(
        ConversationCreateRequest(title="Field Trip", mode=AssistantMode.FIELD)
    )
    container.store.close()

    reloaded = build_container(settings)
    restored = reloaded.store.ensure_conversation(created.id)
    reloaded.store.close()

    assert restored.id == created.id
    assert restored.title == "Field Trip"
    assert restored.mode == AssistantMode.FIELD


def test_agent_run_persists_across_container_rebuilds(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "agent-run-persist.db"))

    container = build_container(settings)
    conversation = container.store.create_conversation(
        ConversationCreateRequest(title="Workspace", mode=AssistantMode.RESEARCH)
    )
    run = container.store.create_agent_run(
        conversation.id,
        "turn_demo",
        "Search this workspace and summarize the docs.",
        str(tmp_path),
        status=AgentRunStatus.COMPLETED,
        result_summary="Completed a bounded workspace run.",
    )
    items_before = container.store.list_items(conversation.id)
    container.store.close()

    reloaded = build_container(settings)
    restored = reloaded.store.get_agent_run(run.id)
    restored_items = reloaded.store.list_items(conversation.id)
    reloaded.store.close()

    assert restored is not None
    assert restored.id == run.id
    assert restored.status == AgentRunStatus.COMPLETED
    assert restored.result_summary == "Completed a bounded workspace run."
    assert any(
        item.kind == ConversationItemKind.AGENT_RUN
        and item.payload["run"]["id"] == run.id
        and item.payload["run"]["status"] == AgentRunStatus.COMPLETED.value
        for item in items_before
    )
    assert any(
        item.kind == ConversationItemKind.AGENT_RUN
        and item.payload["run"]["id"] == run.id
        and item.payload["run"]["status"] == AgentRunStatus.COMPLETED.value
        for item in restored_items
    )


def test_turn_record_and_item_ledger_persist_across_container_rebuilds(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "turn-ledger-persist.db"))

    container = build_container(settings)
    conversation = container.store.create_conversation(
        ConversationCreateRequest(title="Ledger", mode=AssistantMode.GENERAL)
    )
    turn = container.store.create_turn_record(
        ConversationTurnRecord(
            id=new_id("turn"),
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            user_text="Say hello.",
            workspace_root=settings.workspace_root,
            cwd=settings.workspace_root,
            policy=TurnExecutionPolicy(
                workspace_root=settings.workspace_root,
                cwd=settings.workspace_root,
                sandbox_mode=SandboxMode.READ_ONLY,
                network_access=False,
                approval_mode=ApprovalMode.NONE,
                active_profile=RuntimeProfile.FULL_LOCAL,
            ),
        )
    )
    container.store.append_transcript(
        conversation.id,
        "user",
        "Say hello.",
        turn_id=turn.id,
    )
    container.store.append_transcript(
        conversation.id,
        "assistant",
        "Hello.",
        turn_id=turn.id,
    )
    items_before = container.store.list_items(conversation.id, turn_id=turn.id)
    container.store.close()

    reloaded = build_container(settings)
    restored_turn = reloaded.store.get_turn_record(turn.id)
    restored_items = reloaded.store.list_items(conversation.id, turn_id=turn.id)
    reloaded.store.close()

    assert restored_turn is not None
    assert restored_turn.id == turn.id
    assert restored_turn.policy.sandbox_mode == SandboxMode.READ_ONLY
    assert [item.kind for item in items_before] == [
        ConversationItemKind.USER_MESSAGE,
        ConversationItemKind.ASSISTANT_MESSAGE,
    ]
    assert [item.kind for item in restored_items] == [
        ConversationItemKind.USER_MESSAGE,
        ConversationItemKind.ASSISTANT_MESSAGE,
    ]


def test_approval_policy_metadata_persists_across_store_reads(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "approval-policy-persist.db"))
    container = build_container(settings)
    conversation = container.store.create_conversation(
        ConversationCreateRequest(title="Approvals", mode=AssistantMode.GENERAL)
    )
    turn = container.store.create_turn_record(
        ConversationTurnRecord(
            id=new_id("turn"),
            conversation_id=conversation.id,
            mode=AssistantMode.GENERAL,
            user_text="Export a markdown brief.",
            workspace_root=settings.workspace_root,
            cwd=settings.workspace_root,
            policy=TurnExecutionPolicy(
                workspace_root=settings.workspace_root,
                cwd=settings.workspace_root,
                sandbox_mode=SandboxMode.WORKSPACE_WRITE,
                network_access=False,
                approval_mode=ApprovalMode.DURABLE_WRITE,
                active_profile=RuntimeProfile.FULL_LOCAL,
            ),
            route_kind="task",
        )
    )

    approval = container.store.create_approval(
        conversation.id,
        turn.id,
        "export_brief",
        "Confirmation is required before writing an audited markdown export.",
        payload={"title": "Architecture Brief", "content": "Summary"},
        category=ApprovalCategory.AUDITED_EXPORT,
        permission_classes=[
            PermissionClass.TOOL_EXECUTION,
            PermissionClass.DURABLE_OUTPUT,
            PermissionClass.AUDIT_LOG,
        ],
    )

    restored = container.store.get_approval(approval.id)
    items = container.store.list_items(conversation.id, turn_id=turn.id)
    container.store.close()

    assert restored is not None
    assert restored.category == ApprovalCategory.AUDITED_EXPORT
    assert PermissionClass.AUDIT_LOG in restored.permission_classes
    approval_item = next(item for item in items if item.kind == ConversationItemKind.APPROVAL)
    work_product_item = next(item for item in items if item.kind == ConversationItemKind.WORK_PRODUCT)
    assert approval_item.payload["category"] == "audited_export"
    assert "audit_log" in approval_item.payload["permission_classes"]
    assert approval_item.payload["approval"]["category"] == "audited_export"
    assert work_product_item.payload["approval_id"] == approval.id
    assert work_product_item.payload["work_product"]["title"] == "Architecture Brief"
    assert work_product_item.payload["category"] == "audited_export"


def test_archive_conversation_hides_default_listing_but_preserves_record(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "archive-persist.db"))

    container = build_container(settings)
    created = container.store.create_conversation(
        ConversationCreateRequest(title="Archive me", mode=AssistantMode.GENERAL)
    )
    archived = container.store.archive_conversation(created.id)

    assert archived is not None
    assert archived.archived_at is not None

    default_list = container.store.list_conversations()
    archived_list = container.store.list_conversations(include_archived=True)
    restored = container.store.get_conversation(created.id)
    container.store.close()

    assert all(item.id != created.id for item in default_list)
    assert any(item.id == created.id for item in archived_list)
    assert restored is not None
    assert restored.archived_at is not None


def test_fork_conversation_copies_lineage_and_visible_thread_state(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "fork-persist.db"))
    container = build_container(settings)

    created = container.store.create_conversation(
        ConversationCreateRequest(
            title="Original",
            mode=AssistantMode.RESEARCH,
            workspace_binding=WorkspaceBinding(
                root=settings.workspace_root,
                cwd=settings.workspace_root,
            ),
        )
    )
    turn = container.store.create_turn_record(
        ConversationTurnRecord(
            id=new_id("turn"),
            conversation_id=created.id,
            mode=AssistantMode.RESEARCH,
            user_text="Create a report.",
            workspace_root=settings.workspace_root,
            cwd=settings.workspace_root,
            policy=TurnExecutionPolicy(
                workspace_root=settings.workspace_root,
                cwd=settings.workspace_root,
                sandbox_mode=SandboxMode.WORKSPACE_WRITE,
                network_access=False,
                approval_mode=ApprovalMode.DURABLE_WRITE,
                active_profile=RuntimeProfile.FULL_LOCAL,
            ),
            route_kind="task",
        )
    )
    container.store.append_transcript(created.id, "user", "Create a report.", turn_id=turn.id)
    container.store.append_transcript(
        created.id,
        "assistant",
        "I drafted a report here.",
        turn_id=turn.id,
    )
    container.store.create_approval(
        created.id,
        turn.id,
        "create_report",
        "Save a report locally.",
        payload={"title": "Original Report", "content": "Summary"},
    )

    forked = container.store.fork_conversation(created.id, ConversationForkRequest())

    assert forked is not None
    assert forked.parent_conversation_id == created.id
    assert forked.forked_from_turn_id == turn.id
    assert forked.workspace_binding is not None
    assert forked.workspace_binding.isolation == WorkspaceIsolationMode.FORKED

    forked_turns = container.store.list_turn_records(forked.id)
    forked_transcript = container.store.list_transcript(forked.id)
    forked_items = container.store.list_items(forked.id)
    container.store.close()

    assert len(forked_turns) == 1
    assert forked_turns[0].id != turn.id
    assert forked_turns[0].route_kind == "task"
    assert [message.role for message in forked_transcript] == ["user", "assistant"]
    assert forked_transcript[-1].approval is not None
    assert forked_transcript[-1].approval.tool_name == "create_report"
    assert any(item.kind == ConversationItemKind.APPROVAL for item in forked_items)
    assert any(item.kind == ConversationItemKind.WORK_PRODUCT for item in forked_items)


def test_rollback_conversation_archives_source_and_restores_earlier_turn_state(
    tmp_path: Path,
) -> None:
    settings = Settings(database_path=str(tmp_path / "rollback-persist.db"))
    container = build_container(settings)

    created = container.store.create_conversation(
        ConversationCreateRequest(title="Rollback me", mode=AssistantMode.RESEARCH)
    )
    first_turn = container.store.create_turn_record(
        ConversationTurnRecord(
            id=new_id("turn"),
            conversation_id=created.id,
            mode=AssistantMode.RESEARCH,
            user_text="Say hello normally.",
            workspace_root=settings.workspace_root,
            cwd=settings.workspace_root,
            policy=TurnExecutionPolicy(
                workspace_root=settings.workspace_root,
                cwd=settings.workspace_root,
                sandbox_mode=SandboxMode.READ_ONLY,
                network_access=False,
                approval_mode=ApprovalMode.NONE,
                active_profile=RuntimeProfile.FULL_LOCAL,
            ),
            route_kind="conversation",
        )
    )
    container.store.append_transcript(created.id, "user", "Say hello normally.", turn_id=first_turn.id)
    container.store.append_transcript(created.id, "assistant", "Hello.", turn_id=first_turn.id)

    second_turn = container.store.create_turn_record(
        ConversationTurnRecord(
            id=new_id("turn"),
            conversation_id=created.id,
            mode=AssistantMode.RESEARCH,
            user_text="Create a report.",
            workspace_root=settings.workspace_root,
            cwd=settings.workspace_root,
            policy=TurnExecutionPolicy(
                workspace_root=settings.workspace_root,
                cwd=settings.workspace_root,
                sandbox_mode=SandboxMode.WORKSPACE_WRITE,
                network_access=False,
                approval_mode=ApprovalMode.DURABLE_WRITE,
                active_profile=RuntimeProfile.FULL_LOCAL,
            ),
            route_kind="task",
        )
    )
    container.store.append_transcript(created.id, "user", "Create a report.", turn_id=second_turn.id)
    container.store.append_transcript(
        created.id,
        "assistant",
        "I drafted a report here.",
        turn_id=second_turn.id,
    )
    container.store.create_approval(
        created.id,
        second_turn.id,
        "create_report",
        "Save a report locally.",
        payload={"title": "Rollback Report", "content": "Summary"},
    )

    rolled_back = container.store.rollback_conversation(
        created.id,
        ConversationRollbackRequest(up_to_turn_id=first_turn.id),
    )

    assert rolled_back is not None
    assert rolled_back.title == created.title
    assert rolled_back.parent_conversation_id == created.id
    assert rolled_back.forked_from_turn_id == first_turn.id

    archived_source = container.store.get_conversation(created.id)
    rolled_back_turns = container.store.list_turn_records(rolled_back.id)
    rolled_back_transcript = container.store.list_transcript(rolled_back.id)

    assert archived_source is not None
    assert archived_source.archived_at is not None
    assert len(rolled_back_turns) == 1
    assert [message.role for message in rolled_back_transcript] == ["user", "assistant"]
    assert rolled_back_transcript[-1].content == "Hello."
    assert rolled_back_transcript[-1].approval is None


def test_compact_and_steer_conversation_append_item_backed_thread_ops(tmp_path: Path) -> None:
    settings = Settings(database_path=str(tmp_path / "compact-steer-persist.db"))
    container = build_container(settings)

    created = container.store.create_conversation(
        ConversationCreateRequest(title="Compact me", mode=AssistantMode.RESEARCH)
    )
    turn = container.store.create_turn_record(
        ConversationTurnRecord(
            id=new_id("turn"),
            conversation_id=created.id,
            mode=AssistantMode.RESEARCH,
            user_text="Create a report.",
            workspace_root=settings.workspace_root,
            cwd=settings.workspace_root,
            policy=TurnExecutionPolicy(
                workspace_root=settings.workspace_root,
                cwd=settings.workspace_root,
                sandbox_mode=SandboxMode.WORKSPACE_WRITE,
                network_access=False,
                approval_mode=ApprovalMode.DURABLE_WRITE,
                active_profile=RuntimeProfile.FULL_LOCAL,
            ),
            route_kind="task",
        )
    )
    container.store.append_transcript(created.id, "user", "Create a report.", turn_id=turn.id)
    container.store.append_transcript(
        created.id,
        "assistant",
        "I drafted a report here.",
        turn_id=turn.id,
    )
    container.store.create_approval(
        created.id,
        turn.id,
        "create_report",
        "Save a report locally.",
        payload={"title": "Compact Report", "content": "Summary"},
    )

    steer_item = container.store.steer_conversation(
        created.id,
        ConversationSteerRequest(instruction="Keep the thread focused on architecture."),
    )
    compact_item = container.store.compact_conversation(
        created.id,
        ConversationCompactRequest(up_to_turn_id=turn.id),
    )

    assert steer_item is not None
    assert steer_item.kind == ConversationItemKind.STEER
    assert steer_item.payload["instruction"] == "Keep the thread focused on architecture."

    assert compact_item is not None
    assert compact_item.kind == ConversationItemKind.COMPACTION_MARKER
    assert compact_item.payload["up_to_turn_id"] == turn.id
    assert compact_item.payload["turn_count"] == 1
    assert "pending draft" in compact_item.payload["summary"].lower()

    state = container.store.get_conversation_state(created.id)
    container.store.close()

    assert state is not None
    kinds = [item.kind for item in state.items]
    assert ConversationItemKind.STEER in kinds
    assert ConversationItemKind.COMPACTION_MARKER in kinds
