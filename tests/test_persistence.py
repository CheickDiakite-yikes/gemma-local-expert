from pathlib import Path

from engine.api.app import build_container
from engine.config.settings import Settings
from engine.contracts.api import (
    AgentRunStatus,
    ApprovalMode,
    AssistantMode,
    ConversationCreateRequest,
    ConversationItemKind,
    ConversationTurnRecord,
    RuntimeProfile,
    SandboxMode,
    TurnExecutionPolicy,
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
