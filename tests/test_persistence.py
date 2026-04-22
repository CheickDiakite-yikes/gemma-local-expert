from pathlib import Path

from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import (
    AgentRunStatus,
    ApprovalMode,
    AssistantMode,
    ConversationCreateRequest,
    ConversationForkRequest,
    ConversationItemKind,
    ConversationTurnRecord,
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
    container.store.close()

    reloaded = build_container(settings)
    restored = reloaded.store.get_agent_run(run.id)
    reloaded.store.close()

    assert restored is not None
    assert restored.id == run.id
    assert restored.status == AgentRunStatus.COMPLETED
    assert restored.result_summary == "Completed a bounded workspace run."


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
